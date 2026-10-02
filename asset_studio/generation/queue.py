"""Generation job queue: registering, cancelling, retrying and clearing jobs."""

import copy
import re
import secrets
import uuid

from ..compose import compose
from ..i18n import Msg
from ..library.service import ConflictError
from ..lora.apply import merge_loras
from ..util import atomic_json, code, now
from .workflow import validate_settings


class JobQueueMixin:
    """Queue operations of ``Studio``. Expects ``jobs``, ``paused``, ``lock``, ``store``,
    ``comfy``, ``library``, ``validation``, ``root`` and ``state_path`` on the instance."""

    def persist(self):
        atomic_json(
            self.state_path, {'schema_version': 1, 'paused': self.paused, 'jobs': self.jobs}
        )

    def public_jobs(self):
        with self.lock:
            return {
                'paused': self.paused,
                'jobs': [
                    {k: v for k, v in j.items() if k not in ('snapshot', 'workflow')}
                    for j in self.jobs[-1000:]
                ],
            }

    def enqueue(self, request, _catalog=None, _prepare_only=False, _work_catalog=None):
        execution_group = request.get('execution_group')
        if execution_group is not None and (
            not isinstance(execution_group, str)
            or not re.fullmatch(r'[A-Za-z0-9:_-]{1,128}', execution_group)
        ):
            raise ValueError('execution_group must be a short identifier')
        refs = request.get('expressions', [])
        if not isinstance(refs, list) or not 1 <= len(refs) <= 500:
            raise ValueError(
                Msg('server.queue.select_1_to_500_expressions', 'Select 1 to 500 expressions.')
            )
        count = request.get('count', 1)
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 50:
            raise ValueError(
                Msg(
                    'server.queue.the_count_must_be_a_whole',
                    'The count must be a whole number from 1 to 50.',
                )
            )
        if len(refs) * count > 3000:
            raise ValueError(
                Msg('server.queue.up_to_3_000_images_per', 'Up to 3,000 images per request.')
            )
        catalog = _catalog or self.comfy.catalog()
        if not catalog['connected']:
            raise ValueError(catalog['error'])
        settings = validate_settings(request.get('settings', {}), catalog)
        work_catalog = _work_catalog or self.store.catalog(code(request['work_id']))
        prepared = []
        for ref in refs:
            snap = compose(self.store, request, ref, single=len(refs) == 1, catalog=work_catalog)
            for _ in range(count):
                seed = secrets.randbits(32) if settings.get('seed', -1) == -1 else settings['seed']
                actual = {**settings, 'seed': seed}
                if snap.get('auto_loras'):
                    actual['loras'] = merge_loras(actual.get('loras'), snap['auto_loras'])
                    missing = [
                        lora['name']
                        for lora in actual['loras']
                        if lora.get('auto') and lora['name'] not in catalog.get('loras', [])
                    ]
                    if missing:
                        raise ValueError(
                            Msg(
                                'server.queue.automatic_lora_files_are_missing_in',
                                'Automatic LoRA files are missing in ComfyUI: {missing}',
                                missing=', '.join(missing),
                            )
                        )
                snapshot = copy.deepcopy({**snap, 'settings': actual})
                prepared.append(
                    dict(
                        id=uuid.uuid4().hex,
                        status='queued',
                        created_at=now(),
                        work_id=snap['work_id'],
                        character_id=snap['character_id'],
                        outfit_id=snap['outfit_id'],
                        expression_id=snap['expression_id'],
                        expression_name=snap['expression_name'],
                        category=snap['category'],
                        seed=seed,
                        snapshot=snapshot,
                    )
                )
                if execution_group:
                    prepared[-1]['execution_group'] = execution_group
                    snapshot['execution_group'] = execution_group
        if _prepare_only:
            return prepared
        with self.lock:
            if sum(j['status'] == 'queued' for j in self.jobs) + len(prepared) > 5000:
                raise ValueError(
                    Msg(
                        'server.queue.too_many_queued_jobs_let_the',
                        'Too many queued jobs. Let the queue run first.',
                    )
                )
            for job in prepared:
                job['review_requested'] = bool(self.validation.settings['enabled'])
            self.jobs.extend(prepared)
            self.persist()
            self.validation.register_jobs(prepared)
        return {
            'ok': True,
            'jobs': [{k: v for k, v in j.items() if k != 'snapshot'} for j in prepared],
        }

    def enqueue_batch(self, body):
        requests = body.get('requests')
        if not isinstance(requests, list) or not 1 <= len(requests) <= 500:
            raise ValueError(
                Msg('server.queue.select_1_to_500_targets', 'Select 1 to 500 targets.')
            )
        catalog = self.comfy.catalog()
        prepared = []
        batch_id = uuid.uuid4().hex
        with self.lock:
            if (
                body.get('library_revision')
                and body['library_revision'] != self.library.version()['revision']
            ):
                raise ConflictError(
                    Msg(
                        'server.queue.the_library_changed_check_the_latest',
                        'The library changed. Check the latest prompts before queueing.',
                    )
                )
            work_catalogs = {}
            for request in requests:
                work_id = code(request['work_id'])
                if work_id not in work_catalogs:
                    work_catalogs[work_id] = self.store.catalog(work_id)
                prepared.extend(
                    self.enqueue(
                        request,
                        _catalog=catalog,
                        _prepare_only=True,
                        _work_catalog=work_catalogs[work_id],
                    )
                )
                if len(prepared) > 3000:
                    raise ValueError(
                        Msg(
                            'server.queue.up_to_3_000_images_can',
                            'Up to 3,000 images can be queued at once.',
                        )
                    )
            if sum(j['status'] == 'queued' for j in self.jobs) + len(prepared) > 5000:
                raise ValueError(Msg('server.queue.too_many_queued_jobs', 'Too many queued jobs.'))
            for job in prepared:
                job['review_requested'] = bool(self.validation.settings['enabled'])
                job['batch_id'] = batch_id
                job['snapshot']['batch_id'] = batch_id
                preset_id = body.get('generation_preset_id')
                if preset_id:
                    presets = work_catalogs[job['work_id']]['presets']['generation']
                    preset = next((p for p in presets if p['id'] == preset_id), None)
                    if preset:
                        job['snapshot']['generation_preset'] = {
                            'id': preset['id'],
                            'scope': 'global',
                            'name': preset.get('name', preset['id']),
                            'settings_modified': body.get('settings_modified', False),
                        }
            previous = self.jobs[:]
            self.jobs.extend(prepared)
            try:
                self.persist()
                self.validation.register_jobs(prepared)
            except Exception:
                self.jobs = previous
                raise
        return {
            'ok': True,
            'batch_id': batch_id,
            'count': len(prepared),
            'jobs': [{k: v for k, v in j.items() if k != 'snapshot'} for j in prepared],
        }

    def cancel(self, job_id):
        with self.lock:
            job = next(j for j in self.jobs if j['id'] == job_id)
            if job['status'] == 'queued':
                job['status'] = 'cancelled'
            elif job['status'] == 'running':
                job['status'] = 'cancelling'
            self.persist()
        return {'ok': True}

    def remove_finished(self, job_id=None):
        with self.lock:
            finished = {'completed', 'failed', 'cancelled', 'interrupted'}
            if job_id is not None:
                job = next((j for j in self.jobs if j['id'] == job_id), None)
                if job is None:
                    raise ValueError(Msg('server.queue.job_not_found', 'Job not found.'))
                if job['status'] not in finished:
                    raise ValueError(
                        Msg(
                            'server.queue.only_finished_jobs_can_be_cleared',
                            'Only finished jobs can be cleared. Cancel running or queued ones '
                            'first.',
                        )
                    )
            removed = [
                j
                for j in self.jobs
                if j['status'] in finished and (job_id is None or j['id'] == job_id)
            ]
            if removed:
                atomic_json(
                    self.root
                    / 'data'
                    / 'backups'
                    / ('queue-removed-' + uuid.uuid4().hex + '.json'),
                    {'schema_version': 1, 'removed_at': now(), 'jobs': removed},
                )
                previous = self.jobs
                removed_ids = {j['id'] for j in removed}
                self.jobs = [j for j in previous if j['id'] not in removed_ids]
                try:
                    self.persist()
                except Exception:
                    self.jobs = previous
                    raise
            return {'ok': True, 'removed': len(removed)}

    def retry(self, job_id):
        with self.lock:
            old = next(j for j in self.jobs if j['id'] == job_id)
            if old['status'] not in ('failed', 'cancelled', 'interrupted'):
                raise ValueError(
                    Msg(
                        'server.queue.only_failed_cancelled_or_interrupted_jobs',
                        'Only failed, cancelled or interrupted jobs can be retried.',
                    )
                )
            job = {
                k: copy.deepcopy(v)
                for k, v in old.items()
                if k
                in (
                    'work_id',
                    'character_id',
                    'outfit_id',
                    'expression_id',
                    'expression_name',
                    'category',
                    'seed',
                    'snapshot',
                    'execution_group',
                    'kind',
                    'lab_group',
                    'lab_index',
                    'lab_row',
                    'lab_column',
                    'lab_variant',
                    'title',
                    'review_requested',
                    'tool_item',
                    'tag_settings',
                    'post_op',
                    'post_options',
                    'post_prefix',
                    'post_source',
                )
            }
            job.update(id=uuid.uuid4().hex, status='queued', created_at=now())
            self.validation.attach_retry(old, job)
            self.jobs.append(job)
            self.persist()
        return {'ok': True}

    def set_paused(self, paused):
        with self.lock:
            self.paused = bool(paused)
            self.persist()
            return {'ok': True, 'paused': self.paused}

    def cancel_queued(self):
        """Cancel every waiting job; the running image still finishes."""
        with self.lock:
            for job in self.jobs:
                if job['status'] == 'queued':
                    job['status'] = 'cancelled'
            self.persist()
            return {'ok': True, 'paused': self.paused}
