"""Run one LoRA training at a time with the external trainer (anima_lora).

A run waits for the GPU, exports the dataset to the trainer, preprocesses, trains,
then copies every saved epoch into the ComfyUI LoRA folder. Generation does not
start while a run holds the GPU.
"""

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path, PureWindowsPath

from PIL import Image

from ..util import code, now, settings_file
from . import records, trainer_setup
from .trainer_setup import BASE_ALIASES, configured_bases

DEFAULT_SETTINGS = {
    'trainer_dir': 'vendor/anima_lora',
    'trainer_python': '.venv/Scripts/python.exe',
    'trainer_method': 'asset_studio_tlora',
    'trainer_preset': 'asset_studio_base',
    'trainer_cache_dir': 'post_image_dataset/lora_base',
    'base_model': 'anima-base-v1.0',
    'lora_dir': '',
}
DEFAULT_PARAMS = {
    'epochs': 40,
    'save_every': 10,
    'learning_rate': '1e-4',
    'method': 'asset_studio_tlora',
    'base': 'official',
}
# Training methods (anima_lora configs/methods) and base models (configs/presets.toml).
METHODS = {
    'asset_studio_tlora': 'T-LoRA (dim 32, alpha 32)',
    'asset_studio_lora': 'LoRA (dim 32, alpha 128)',
}


def options(root):
    """Choices the training form offers; only bases with model paths set are listed."""
    settings = load_settings(root)
    return {
        'methods': [{'id': k, 'label': v} for k, v in METHODS.items()],
        'bases': [{'id': k, 'label': v['label']} for k, v in configured_bases(settings).items()],
        'defaults': DEFAULT_PARAMS,
    }


WAIT_POLL_SECONDS = 2
INTERRUPTED = '서버가 꺼져 학습을 더 따라갈 수 없습니다. 학습 도구의 로그와 결과 파일을 확인하세요.'


def load_settings(root):
    """Trainer paths from data/settings/lora_pipeline.json on top of the defaults."""
    settings = dict(DEFAULT_SETTINGS)
    path = settings_file(root, 'lora_pipeline.json')
    if path.is_file():
        settings.update(json.loads(path.read_text(encoding='utf-8')))
    settings['trainer_dir'] = str((Path(root) / settings['trainer_dir']).resolve())
    return settings


def last_progress(path):
    """Latest step / checkpoint / end event of the trainer's progress.jsonl."""
    path = Path(path)
    if not path.is_file():
        return {}
    with path.open('rb') as stream:
        stream.seek(max(0, path.stat().st_size - 65536))
        lines = stream.read().decode('utf-8', 'replace').splitlines()
    result = {}
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get('ev')
        if kind == 'run_start':
            result.update(
                total_steps=event.get('total_steps'), total_epochs=event.get('total_epochs')
            )
        elif kind == 'step':
            result.update(
                step=event.get('global_step'),
                epoch=event.get('epoch'),
                loss=event.get('loss/average'),
            )
        elif kind == 'run_end':
            result.update(finished=event.get('status'), error=event.get('error'))
    return result


class Cancelled(Exception):
    pass


class LoraTrainer:
    """Training runs of one Studio. Only one run is active at a time."""

    def __init__(self, studio):
        self.studio = studio
        self.lock = threading.RLock()
        self.process = None
        self.active = None  # (work_id, character_id, run_id)
        self.cancel_requested = False
        self._recover()

    # ---- records ---------------------------------------------------------------------

    def _path(self, work_id, character_id, run_id):
        return records.run_file(self.studio.store, work_id, character_id, run_id)

    def _write(self, run):
        self.studio.store.write(self._path(run['work_id'], run['character_id'], run['id']), run)

    def _update(self, run, **changes):
        with self.lock:
            run.update(changes, updated_at=now())
            self._write(run)

    def _recover(self):
        """A run that was active when the server stopped cannot be followed any more."""
        works = self.studio.store.root / 'works'
        for path in sorted(works.glob('*/characters/*/lora_runs/*.json')) if works.is_dir() else []:
            run = self.studio.store.read(path)
            if run.get('status') in records.ACTIVE_RUN_STATES:
                run.update(
                    status='interrupted',
                    updated_at=now(),
                    error=INTERRUPTED,
                )
                self.studio.store.write(path, run)

    def list(self, work_id, character_id):
        return {
            'runs': [
                self._with_progress(run)
                for run in records.list_runs(self.studio.store, code(work_id), code(character_id))
            ]
        }

    def get(self, work_id, character_id, run_id):
        return self._with_progress(
            self.studio.store.read(self._path(code(work_id), code(character_id), run_id))
        )

    @staticmethod
    def _with_progress(run):
        if run.get('progress_path'):
            run = {**run, 'progress': last_progress(run['progress_path'])}
        return run

    # ---- start / cancel ----------------------------------------------------------------

    def start(self, body):
        work_id, character_id = code(body.get('work_id')), code(body.get('character_id'))
        dataset_path = records.dataset_file(
            self.studio.store, work_id, character_id, body.get('dataset_id')
        )
        if not dataset_path.is_file():
            raise ValueError('데이터셋을 먼저 저장하세요.')
        dataset = self.studio.store.read(dataset_path)
        if not dataset.get('items'):
            raise ValueError('데이터셋에 이미지가 없습니다.')
        settings = load_settings(self.studio.root)
        if not settings['lora_dir']:
            raise ValueError('설정 › LoRA 학습에서 LoRA 저장 폴더를 지정하세요.')
        params = {
            **DEFAULT_PARAMS,
            **{k: v for k, v in (body.get('params') or {}).items() if v not in (None, '')},
        }
        for key in ('epochs', 'save_every'):
            if (
                isinstance(params[key], bool)
                or not str(params[key]).isdigit()
                or int(params[key]) < 1
            ):
                raise ValueError(f'{key}는 1 이상의 정수여야 합니다.')
            params[key] = int(params[key])
        float(params['learning_rate'])
        if params['method'] not in METHODS:
            raise ValueError('학습 방식을 목록에서 고르세요.')
        params['base'] = BASE_ALIASES.get(params['base'], params['base'])
        bases = trainer_setup.prepare(self.studio.root, settings)
        if params['base'] not in bases:
            raise ValueError('베이스 모델을 목록에서 고르세요.')
        base = bases[params['base']]
        settings = {**settings, 'trainer_method': params['method']}
        settings.update(trainer_preset=base['preset'], trainer_cache_dir=base['cache_dir'])
        settings['base_model'] = base['base_model']
        with self.lock:
            if self.active:
                raise ValueError('다른 LoRA 학습이 진행 중입니다. 끝난 뒤에 시작하세요.')
            run_id = records.next_id(
                records.list_runs(self.studio.store, work_id, character_id), 'R'
            )
            name = f'{work_id}_{character_id}_{dataset["outfit_set_id"]}_{run_id}'.lower()
            logs = self.studio.root / 'logs' / 'lora' / name
            run = {
                'id': run_id,
                'schema_version': 1,
                'work_id': work_id,
                'character_id': character_id,
                'outfit_set_id': dataset['outfit_set_id'],
                'dataset_id': dataset['id'],
                'dataset_sha': [item['sha256'] for item in dataset['items']],
                'output_name': name,
                'triggers': dataset['triggers'],
                'settings': {
                    'method': settings['trainer_method'],
                    'preset': settings['trainer_preset'],
                    'base_model': settings['base_model'],
                    **params,
                },
                'status': 'waiting_gpu',
                'created_at': now(),
                'outputs': [],
                'log_path': str(logs / 'trainer.log'),
                'progress_path': str(logs / 'progress.jsonl'),
            }
            self._write(run)
            self.active = (work_id, character_id, run_id)
            self.cancel_requested = False
        threading.Thread(
            target=self._execute, args=(run, dataset, settings), daemon=True, name='lora-training'
        ).start()
        return {'ok': True, 'run': run}

    def cancel(self, body):
        with self.lock:
            key = (code(body.get('work_id')), code(body.get('character_id')), body.get('run_id'))
            if self.active != key:
                raise ValueError('진행 중인 학습이 아닙니다.')
            self.cancel_requested = True
            if self.process and self.process.poll() is None:
                # The trainer starts worker processes of its own; stop the whole tree.
                subprocess.call(
                    ['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        return {'ok': True}

    # ---- the run itself ----------------------------------------------------------------

    def _check_cancel(self):
        if self.cancel_requested:
            raise Cancelled()

    def _wait_for_gpu(self, run):
        """Take the GPU once no image is being generated. Queued jobs then wait for us."""
        gpu = self.studio.gpu
        while True:
            self._check_cancel()
            if gpu.generation_allowed() and gpu.admit('training'):
                time.sleep(WAIT_POLL_SECONDS)
                continue
            with self.studio.lock:
                running = any(
                    job['status'] in ('running', 'cancelling') for job in self.studio.jobs
                )
                if not running and gpu.acquire('training', 'preparing', run['output_name']):
                    return
            time.sleep(WAIT_POLL_SECONDS)

    def _export(self, run, dataset, settings):
        trainer = Path(settings['trainer_dir'])
        name = run['output_name']
        # Captions and images of an earlier run would survive in the trainer's caches.
        for stale in (
            trainer / 'image_dataset' / name,
            trainer / 'post_image_dataset' / 'resized' / name,
            trainer / settings['trainer_cache_dir'] / name,
        ):
            if stale.exists():
                shutil.rmtree(stale)
        target = trainer / 'image_dataset' / name
        target.mkdir(parents=True)
        for item in dataset['items']:
            source = self.studio.gallery._safe_path(item['path'])
            if self.studio.review_store.sha256(item['path'], fresh=True) != item['sha256']:
                raise ValueError(f'데이터셋을 만든 뒤 바뀐 이미지입니다: {item["path"]}')
            stem = Path(item['path']).stem
            with Image.open(source) as image:
                image.convert('RGB').save(target / f'{stem}.png')
            (target / f'{stem}.txt').write_text(item['caption'], encoding='utf-8')

    def _call(self, settings, arguments, log_path, env=None):
        python = Path(settings['trainer_dir']) / settings['trainer_python']
        with open(log_path, 'a', encoding='utf-8') as log:
            log.write(f'\n$ {" ".join(map(str, arguments))}\n')
            log.flush()
            with self.lock:
                self._check_cancel()
                self.process = subprocess.Popen(
                    [str(python), *map(str, arguments)],
                    cwd=settings['trainer_dir'],
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env={**os.environ, **(env or {})},
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            exit_code = self.process.wait()
        self._check_cancel()
        if exit_code:
            raise RuntimeError(
                f'학습 도구가 실패했습니다 (종료 코드 {exit_code}). {log_path}을 확인하세요.'
            )

    def _execute(self, run, dataset, settings):
        gpu = self.studio.gpu
        try:
            self._wait_for_gpu(run)
            Path(run['log_path']).parent.mkdir(parents=True, exist_ok=True)
            try:
                self.studio.comfy.request('/free', {'unload_models': True, 'free_memory': True})
            except Exception:
                logging.info('ComfyUI did not answer /free before training; continuing.')
            self._export(run, dataset, settings)
            name, params = run['output_name'], run['settings']
            gpu.update('training', 'preprocessing')
            self._update(run, status='preprocessing', started_at=now())
            env = {
                'METHOD': params['method'],
                'PRESET': params['preset'],
                'PREPROCESS_PATH_PATTERN': f'{name}/*',
            }
            self._call(settings, ['tasks.py', 'preprocess'], run['log_path'], env)
            gpu.update('training', 'training')
            self._update(run, status='training')
            self._call(
                settings,
                [
                    'train.py',
                    '--method',
                    params['method'],
                    '--preset',
                    params['preset'],
                    '--output_name',
                    name,
                    '--path_pattern',
                    f'{name}/*',
                    '--learning_rate',
                    params['learning_rate'],
                    '--max_train_epochs',
                    params['epochs'],
                    '--save_every_n_epochs',
                    params['save_every'],
                    '--checkpointing_epochs',
                    params['save_every'],
                    '--progress_jsonl',
                    run['progress_path'],
                ],
                run['log_path'],
            )
            outputs = self._collect_outputs(run, settings)
            # Give the GPU back before reporting "done", so a finished run never blocks generation.
            gpu.release('training')
            self._update(run, status='done', finished_at=now(), outputs=outputs)
        except Cancelled:
            self._update(run, status='cancelled', finished_at=now())
        except Exception as exc:
            logging.exception('LoRA training failed: %s', run['output_name'])
            self._update(run, status='failed', finished_at=now(), error=str(exc)[:500])
        finally:
            with self.lock:
                self.process = None
                self.active = None
            gpu.release('training')

    def _collect_outputs(self, run, settings):
        name = run['output_name']
        checkpoints = Path(settings['trainer_dir']) / 'output' / 'ckpt'
        found = [
            (int(path.stem.rsplit('-', 1)[1]), path)
            for path in sorted((checkpoints / name).glob(f'{name}-*.safetensors'))
            if path.stem.rsplit('-', 1)[1].isdigit()
        ]
        final = checkpoints / f'{name}.safetensors'
        if not final.is_file():
            raise RuntimeError(f'학습은 끝났지만 {final}이 없습니다.')
        found.append((int(run['settings']['epochs']), final))
        outputs = []
        for epoch, source in sorted(set(found)):
            destination = Path(settings['lora_dir']) / f'{name}-e{epoch:02d}.safetensors'
            shutil.copy2(source, destination)
            outputs.append({'epoch': epoch, 'file': destination.name})
        return outputs

    # ---- registry ------------------------------------------------------------------------

    def register(self, body):
        """Add one epoch of a finished run to the LoRA registry (character scope)."""
        run = self.get(body.get('work_id'), body.get('character_id'), body.get('run_id'))
        output = next((o for o in run.get('outputs', []) if o['epoch'] == body.get('epoch')), None)
        if run.get('status') != 'done' or output is None:
            raise ValueError('끝난 학습의 에폭을 고르세요.')
        ident = Path(output['file']).stem
        # ComfyUI names files in sub-folders with the folder (``anima\name.safetensors``).
        catalog = self.studio.comfy.catalog().get('loras', [])
        comfy_name = next(
            (name for name in catalog if PureWindowsPath(name).name == output['file']),
            output['file'],
        )
        payload = {
            'id': ident,
            'name': body.get('name') or ident,
            'file': comfy_name,
            'apply_to': body.get('apply_to', 'character'),
            'model_family': 'anima',
            'origin': {
                'work_id': run['work_id'],
                'character_id': run['character_id'],
                'outfit_set_id': run['outfit_set_id'],
                'run_id': run['id'],
                'epoch': output['epoch'],
            },
            'scope': 'character',
            'auto_apply': bool(body.get('auto_apply', False)),
            'strength': body.get('strength', 1.0),
            'triggers': run.get('triggers', {}),
            'base_model': run['settings'].get('base_model'),
        }
        path = records.lora_file(self.studio.store, ident)
        return self.studio.library.save(
            {
                'kind': 'lora',
                'payload': payload,
                'expected_revision': self.studio.library.revision(path, 'lora'),
            }
        )
