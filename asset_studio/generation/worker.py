"""Background worker: sends queued jobs to ComfyUI and stores the results."""

import copy
import io
import json
import logging
import time
from urllib.parse import quote, urlencode

from PIL import Image, PngImagePlugin

from ..util import atomic_json, code, now, replace_file
from .workflow import build_ui_workflow, build_workflow


class WorkerMixin:
    """Generation loop of ``Studio``. Runs in one daemon thread."""

    def save_result(self, job, image_bytes, graph, prompt_id):
        """Save the image as PNG with the ComfyUI ``prompt``/``workflow`` chunks and a JSON sidecar.

        The chunks follow ComfyUI's own PNG format, so the file still explains itself
        after it leaves Studio (and ComfyUI can open it as a workflow).
        """
        image = Image.open(io.BytesIO(image_bytes))
        image.load()
        if all(high == 0 for low, high in image.convert('RGB').getextrema()):
            raise RuntimeError(
                '완전 검정 이미지가 반환됐습니다. 정상 결과로 저장하지 않고 큐를 일시정지했습니다.'
            )
        if job.get('kind') == 'lab':
            # Lab tries are not assets: one folder per day, named by time, group and order.
            stamp = time.localtime()
            folder = self.root / 'outputs' / '_lab' / time.strftime('%Y-%m-%d', stamp)
            stem = '{}_{}_{:02d}'.format(
                time.strftime('%H%M%S', stamp), job['lab_group'][:6], job['lab_index']
            )
        else:
            folder = (
                self.root
                / 'outputs'
                / code(job['work_id'])
                / code(job['character_id'])
                / code(job['outfit_id'])
            )
            stem = code(job['expression_id'])
        folder.mkdir(parents=True, exist_ok=True)
        index = 1
        while True:
            candidate = stem if index == 1 else f'{stem}_{index:03d}'
            path = folder / (candidate + '.png')
            # A WebP from before the PNG switch may share the stem and the sidecar name.
            taken = [path, path.with_suffix('.webp'), path.with_suffix('.json')]
            if not any(item.exists() for item in taken):
                break
            index += 1
        metadata = copy.deepcopy(job['snapshot'])
        metadata.update(
            schema_version=1,
            created_at=now(),
            job_id=job['id'],
            prompt_id=prompt_id,
            workflow=graph,
            image_size=list(image.size),
            postprocessing={'applied': False, 'source_image': None},
        )
        snapshot = metadata['settings']
        info = PngImagePlugin.PngInfo()
        info.add_text('prompt', json.dumps(graph, ensure_ascii=False))
        try:
            editor_graph = build_ui_workflow(
                snapshot, metadata['positive'], metadata['negative'], job['seed']
            )
            info.add_text('workflow', json.dumps(editor_graph, ensure_ascii=False))
        except (KeyError, ValueError):
            logging.warning(
                'No editor workflow for job %s; the API prompt is still saved.', job['id']
            )
        info.add_text(
            'asset_studio',
            json.dumps({k: v for k, v in metadata.items() if k != 'workflow'}, ensure_ascii=False),
        )
        temp = path.with_suffix('.png.tmp')
        image.save(temp, format='PNG', pnginfo=info, compress_level=6)
        atomic_json(path.with_suffix('.json'), metadata)
        replace_file(temp, path)
        return '/outputs/' + quote(path.relative_to(self.root / 'outputs').as_posix(), safe='/')

    def worker(self):
        while not self.stop.wait(0.5):
            with self.lock:
                pending = any(job['status'] == 'queued' for job in self.jobs)
                free = not self.paused and self.gpu.generation_allowed()
            # Another program on the GPU holds new jobs back; the reason is shown in the UI.
            if pending and free and self.gpu.admit('generation'):
                continue
            with self.lock:
                free = not self.paused and self.gpu.generation_allowed()
                job = self.validation.next_generation_job() if free else None
                if job is not None:
                    job.update(status='running', started_at=now(), progress='ComfyUI 연결 중')
                    self.persist()
            if job is None:
                try:
                    self.validation.process_ready()
                except Exception:
                    logging.exception('VLM validation halted')
                continue
            try:
                # Wait for other clients; never clear or interrupt someone else's queue.
                deadline = time.monotonic() + 1800
                while True:
                    if self.stop.is_set():
                        return
                    with self.lock:
                        cancelling = job['status'] == 'cancelling'
                    if cancelling:
                        break
                    queue = self.comfy.request('/queue')
                    if not queue.get('queue_running') and not queue.get('queue_pending'):
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError('ComfyUI의 다른 작업을 30분 동안 기다렸습니다.')
                    self.stop.wait(2)
                if cancelling:
                    with self.lock:
                        job['status'] = 'cancelled'
                        self.persist()
                    continue
                snap = job['snapshot']
                self.validation.ensure_generation_safe()
                tagging = job.get('kind') == 'tag'
                if tagging:
                    graph = self.tag_graph(job)
                elif job.get('kind') == 'post':
                    graph = self.post_graph(job)
                else:
                    graph = build_workflow(
                        snap['settings'], snap['positive'], snap['negative'], job['seed']
                    )
                response = self.comfy.request(
                    '/prompt', {'prompt': graph, 'client_id': 'asset-studio-' + job['id']}
                )
                if response.get('node_errors') or not response.get('prompt_id'):
                    raise RuntimeError(
                        '워크플로우 검증 실패: ' + json.dumps(response, ensure_ascii=False)[:3000]
                    )
                prompt_id = response['prompt_id']
                with self.lock:
                    working = '생성 중' if job.get('kind') in (None, 'lab') else '처리 중'
                    job.update(prompt_id=prompt_id, progress=working)
                    self.persist()
                deadline = time.monotonic() + 1800
                interrupt_sent = False
                while not self.stop.wait(1):
                    with self.lock:
                        cancelling = job['status'] == 'cancelling'
                    if cancelling and not interrupt_sent:
                        queue = self.comfy.request('/queue')
                        if any(item[1] == prompt_id for item in queue.get('queue_running', [])):
                            self.comfy.request('/interrupt', {'prompt_id': prompt_id})
                        elif any(item[1] == prompt_id for item in queue.get('queue_pending', [])):
                            self.comfy.request('/queue', {'delete': [prompt_id]})
                            break
                        interrupt_sent = True
                    history = self.comfy.request('/history/' + quote(prompt_id))
                    if prompt_id in history:
                        entry = history[prompt_id]
                        if entry.get('status', {}).get('status_str') == 'error':
                            if cancelling:
                                break
                            raise RuntimeError(
                                'ComfyUI 생성 오류: '
                                + json.dumps(
                                    entry['status'].get('messages', []), ensure_ascii=False
                                )[-2500:]
                            )
                        if cancelling:
                            break
                        if tagging:
                            tags = self.finish_tags(job, entry)
                            with self.lock:
                                job.update(
                                    status='completed',
                                    tag_count=len(tags),
                                    finished_at=now(),
                                    progress='완료',
                                )
                                self.persist()
                            break
                        images = entry.get('outputs', {}).get('output', {}).get('images', [])
                        if not images:
                            raise RuntimeError('ComfyUI가 결과 이미지를 반환하지 않았습니다.')
                        item = images[0]
                        data = self.comfy.request(
                            '/view?'
                            + urlencode(
                                {k: item.get(k, '') for k in ('filename', 'subfolder', 'type')}
                            ),
                            raw=True,
                        )
                        if job.get('kind') == 'post':
                            image_url, _ = self.save_post(job, data, graph)
                        else:
                            image_url = self.save_result(job, data, graph, prompt_id)
                        with self.lock:
                            job.update(
                                status='completed',
                                image_url=image_url,
                                metadata_url=image_url.rsplit('.', 1)[0] + '.json',
                                finished_at=now(),
                                progress='완료',
                            )
                            self.persist()
                        break
                    if time.monotonic() > deadline:
                        raise RuntimeError(
                            '생성 결과 대기 시간이 30분을 넘었습니다. '
                            'ComfyUI에서 진행 상태를 확인하세요.'
                        )
                if cancelling:
                    with self.lock:
                        job.update(status='cancelled', finished_at=now(), progress='취소')
                        self.persist()
            except Exception as e:
                logging.exception('Job failed: %s', job['id'])
                with self.lock:
                    job.update(status='failed', error=str(e), finished_at=now(), progress='실패')
                    self.paused = True
                    self.persist()
