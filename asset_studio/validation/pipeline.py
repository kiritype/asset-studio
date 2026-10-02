"""Durable, bounded review rounds. The queue remains the generation authority."""

from __future__ import annotations

import copy
import json
import secrets
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote

from ..i18n import Msg
from ..util import replace_file, settings_file, state_file
from .vlm import LocalVLM, VLMError


def _now():
    return datetime.now(timezone.utc).isoformat()


def _atomic(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        replace_file(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class ValidationPipeline:
    def __init__(self, studio):
        self.studio = studio
        self.root = studio.root
        self.vlm = LocalVLM(self.root)
        self.settings_path = settings_file(self.root, 'review_settings.json')
        self.path = state_file(self.root, 'review_rounds.json')
        self.settings = {'enabled': False, 'max_auto_regenerations': 10}
        if self.settings_path.exists():
            saved = json.loads(self.settings_path.read_text(encoding='utf-8'))
            self.settings.update({key: saved[key] for key in self.settings if key in saved})
        self.rounds = (
            json.loads(self.path.read_text(encoding='utf-8')).get('rounds', [])
            if self.path.exists()
            else []
        )
        self._lock = threading.RLock()
        # A POST or a model switch can be uncertain across process death. Never
        # silently replay one; a person can start a new round after inspection.
        for round_ in self.rounds:
            if round_['status'] in ('reviewing', 'switching', 'queueing'):
                round_['status'] = 'needs_attention'
                round_['error'] = (
                    'Interrupted operation; inspect ComfyUI and VLM before continuing.'
                )
        if self.path.exists():
            self.persist()

    def persist(self):
        _atomic(self.path, {'schema_version': 1, 'rounds': self.rounds})

    def public_settings(self):
        """Review settings plus whether a local VLM is set up at all."""
        return {**self.settings, 'configured': self.vlm.enabled}

    def save_settings(self, body):
        if not isinstance(body, dict):
            raise ValueError('Invalid review settings')
        if self.studio.gpu.held_by('validation'):
            raise ValueError(
                Msg(
                    'server.pipeline.vlm_review_is_using_the_gpu',
                    'VLM review is using the GPU. Change this after it finishes.',
                )
            )
        self.vlm.reload()
        max_count = body.get('max_auto_regenerations', self.settings['max_auto_regenerations'])
        enabled = body.get('enabled', self.settings['enabled'])
        if (
            isinstance(max_count, bool)
            or not isinstance(max_count, int)
            or not 0 <= max_count <= 100
        ):
            raise ValueError('max_auto_regenerations must be an integer from 0 to 100')
        if not isinstance(enabled, bool):
            raise ValueError('enabled must be boolean')
        if enabled and not self.vlm.enabled:
            raise ValueError('Configure the local VLM before enabling review')
        self.settings = {'enabled': enabled, 'max_auto_regenerations': max_count}
        _atomic(self.settings_path, self.settings)
        return self.public_settings()

    def status(self):
        gpu = self.studio.gpu
        gpu_state = gpu.state if gpu.held_by('validation') else 'idle'
        gpu_error = gpu.error if gpu.held_by('validation') else None
        state = 'error' if gpu_error else gpu_state
        status_error = gpu_error or self.vlm.error
        loaded = False
        other_instances = 0
        if self.vlm.enabled:
            try:
                instances = self.vlm._loaded_instances()
                loaded = self.vlm.is_loaded()
                other_instances = len(instances) - int(loaded)
            except Exception as exc:
                state = 'error'
                status_error = 'VLM status unavailable: ' + type(exc).__name__
        return {
            **self.vlm.public_status(),
            'enabled': self.settings['enabled'],
            'status': state,
            'error': status_error,
            'gpu_state': gpu_state,
            'gpu_error': gpu_error,
            'loaded': loaded,
            'other_instances_loaded': other_instances,
            'review_enabled': self.settings['enabled'],
            'pending_rounds': sum(
                r['status'] in ('waiting_generation', 'pending_review') for r in self.rounds
            ),
        }

    def test_connection(self):
        gpu = self.studio.gpu
        with self.studio.lock:
            if gpu.held_by('validation') and gpu.state == 'blocked':
                if self.studio.control.operation or any(
                    j['status'] in ('running', 'cancelling') for j in self.studio.jobs
                ):
                    raise ValueError('Wait for GPU activity before recovering VLM ownership')
                queue = self.studio.comfy.request('/queue')
                if (
                    queue.get('queue_running')
                    or queue.get('queue_pending')
                    or self.vlm._loaded_instances()
                ):
                    raise ValueError(
                        'VLM or ComfyUI work is still loaded; generation remains blocked'
                    )
                # The GPU is verified empty, so the blocked review gives it back.
                self.vlm.owned = False
                gpu.release('validation')
            elif not gpu.generation_allowed() or any(
                j['status'] in ('running', 'cancelling') for j in self.studio.jobs
            ):
                raise ValueError('Wait for GPU activity to finish before testing the VLM')
            self.vlm.reload()
            return self.vlm.test()

    def retry_validation(self, round_ids):
        """Explicitly retry verification of existing outputs, never generation."""
        if (
            not isinstance(round_ids, list)
            or not 1 <= len(round_ids) <= 100
            or any(not isinstance(x, str) for x in round_ids)
            or len(set(round_ids)) != len(round_ids)
        ):
            raise ValueError('Select 1 to 100 unique round IDs')
        with self.studio.lock, self._lock:
            if (
                self.studio.paused
                or not self.studio.gpu.generation_allowed()
                or self.studio.control.operation
            ):
                raise ValueError('Validation cannot resume while paused or GPU control is busy')
            if not self.settings['enabled'] or not self.vlm.enabled:
                raise ValueError('Enable local review first')
            active_group = self.active_execution_group()
            if any(
                j['status'] in ('queued', 'running', 'cancelling')
                and (active_group is None or j.get('execution_group') == active_group)
                for j in self.studio.jobs
            ):
                raise ValueError('Wait for generation to finish')
            queue = self.studio.comfy.request('/queue')
            if (
                queue.get('queue_running')
                or queue.get('queue_pending')
                or self.vlm._loaded_instances()
            ):
                raise ValueError('ComfyUI and VLM must be idle')
            selected = []
            for rid in round_ids:
                round_ = next((r for r in self.rounds if r['id'] == rid), None)
                if (
                    not round_
                    or round_['status'] != 'needs_attention'
                    or self._human_accepted(round_)
                ):
                    raise ValueError('Only unresolved needs_attention rounds can retry validation')
                if active_group is not None and round_.get('execution_group') != active_group:
                    raise ValueError('Finish the active execution group first')
                job = next(
                    (j for j in self.studio.jobs if j['id'] == round_['current_job_id']), None
                )
                if not job or job['status'] != 'completed' or not job.get('image_url'):
                    raise ValueError('Completed output required')
                path = unquote(job['image_url'].removeprefix('/outputs/'))
                if not self.studio.gallery._safe_path(path).is_file():
                    raise ValueError('Output image missing')
                selected.append(round_)
            for round_ in selected:
                round_.setdefault('validation_retries', []).append(
                    {
                        'at': _now(),
                        'previous_error': round_.get('error'),
                        'technical_errors': round_['technical_errors'],
                    }
                )
                round_['status'] = 'pending_review'
                round_.pop('error', None)
            self.persist()
            return {'ok': True, 'round_ids': round_ids, 'count': len(selected)}

    def ensure_generation_safe(self):
        if self.vlm.enabled and self.vlm._loaded_instances():
            raise VLMError('A VLM instance is loaded; generation is blocked to avoid GPU overlap')

    def public_rounds(self):
        """Rounds that still matter to the user; dismissed ones stay in the file only."""
        with self.studio.lock, self._lock:
            jobs = {job['id']: job for job in self.studio.jobs}
            rounds = []
            for round_ in self.rounds:
                if round_['status'] == 'dismissed':
                    continue
                # A waiting round whose job is gone from the queue will never move again.
                waiting = round_['status'] in ('waiting_generation', 'pending_review')
                rounds.append(
                    {
                        **copy.deepcopy(round_),
                        'stale': waiting and not self._has_live_work(round_, jobs),
                    }
                )
        return {'rounds': rounds, 'paused': self.studio.paused, 'enabled': self.settings['enabled']}

    def _has_live_work(self, round_, jobs):
        """True while the round's image is being generated or is waiting to be reviewed."""
        if round_['status'] in ('reviewing', 'switching', 'queueing'):
            return True
        if round_['status'] not in ('waiting_generation', 'pending_review'):
            return False
        job = jobs.get(round_['current_job_id'])
        return bool(job and job['status'] in ('queued', 'running', 'cancelling', 'completed'))

    def dismiss_rounds(self):
        """Put away every round with nothing left to do, e.g. after old images were archived.

        The rounds stay in the file with their previous status; they only stop being
        listed and scheduled.
        """
        with self.studio.lock, self._lock:
            if self.studio.gpu.held_by('validation'):
                raise ValueError(
                    Msg(
                        'server.pipeline.vlm_review_is_running_clear_rounds',
                        'VLM review is running. Clear rounds after it finishes.',
                    )
                )
            jobs = {job['id']: job for job in self.studio.jobs}
            count = 0
            for round_ in self.rounds:
                if round_['status'] == 'dismissed' or self._has_live_work(round_, jobs):
                    continue
                round_.update(
                    dismissed_from=round_['status'], dismissed_at=_now(), status='dismissed'
                )
                count += 1
            if count:
                self.persist()
            return {'ok': True, 'dismissed': count}

    @staticmethod
    def combo(job):
        return tuple(
            str(job.get(key) or '')
            for key in ('work_id', 'character_id', 'outfit_id', 'category', 'expression_id')
        )

    def _round(self, job, source_path='', manual=False):
        combo = self.combo(job)
        store = getattr(self.studio, 'review_store', None)
        baseline = store.human_acceptance_revision(combo) if store else None
        return {
            'id': uuid.uuid4().hex,
            'status': 'waiting_generation',
            'created_at': _now(),
            'source_path': source_path,
            'source_job_id': job['id'],
            'current_job_id': job['id'],
            'combo': combo,
            'manual': manual,
            'regenerations': 0,
            'execution_group': job.get('execution_group'),
            'human_baseline_revision': baseline or 0,
            'round_number': 1 + sum(tuple(r['combo']) == combo for r in self.rounds),
            'max_auto_regenerations': self.settings['max_auto_regenerations'],
            'technical_errors': 0,
            'attempts': [],
        }

    def register_jobs(self, jobs):
        if not self.settings['enabled']:
            return
        with self._lock:
            known = {r['source_job_id'] for r in self.rounds}
            changed = False
            for job in jobs:
                if (
                    job.get('review_requested')
                    and not job.get('review_round_id')
                    and job['id'] not in known
                ):
                    self.rounds.append(self._round(job))
                    known.add(job['id'])
                    changed = True
            if changed:
                self.persist()

    def attach_retry(self, old, new):
        """An explicit technical retry keeps the same quality attempt/seed."""
        with self._lock:
            round_ = next((r for r in self.rounds if r['current_job_id'] == old['id']), None)
            if round_ is None:
                return
            if self._human_accepted(round_) or round_['status'] == 'human_accepted':
                raise ValueError(
                    'This combination was approved by a person; start a new round to generate again'
                )
            new['review_round_id'] = round_['id']
            new['regeneration'] = round_['regenerations']
            new['review_requested'] = False
            round_['current_job_id'] = new['id']
            round_['status'] = 'waiting_generation'
            round_.pop('error', None)
            self.persist()

    def reconcile(self):
        # Handles a crash between queue persistence and round persistence.
        if self.settings['enabled']:
            self.register_jobs(self.studio.jobs)
        with self._lock:
            changed = False
            by_id = {job['id']: job for job in self.studio.jobs}
            for round_ in self.rounds:
                if round_['status'] != 'waiting_generation':
                    continue
                job = by_id.get(round_['current_job_id'])
                if job and job['status'] == 'completed' and job.get('image_url'):
                    round_['status'] = 'pending_review'
                    if not round_['source_path']:
                        round_['source_path'] = unquote(job['image_url'].removeprefix('/outputs/'))
                    changed = True
                elif job and job['status'] in ('failed', 'cancelled', 'interrupted'):
                    round_['status'] = 'needs_attention'
                    round_['error'] = Msg(
                        'server.pipeline.generation_did_not_finish_check_it',
                        'Generation did not finish. Check it, then use Retry in the queue.',
                    )
                    changed = True
                elif job is None:
                    round_['status'] = 'needs_attention'
                    round_['error'] = Msg(
                        'server.pipeline.the_queue_history_has_no_job',
                        'The queue history has no job for this round. Check it, then start a new '
                        'round.',
                    )
                    changed = True
            if changed:
                self.persist()

    @staticmethod
    def _group_round_terminal(round_):
        if round_['status'] in ('awaiting_human', 'human_accepted', 'limit_reached', 'dismissed'):
            return True
        # An uncertain visual verdict is a completed quality review for queue
        # scheduling. Technical errors still require explicit recovery.
        return (
            round_['status'] == 'needs_attention'
            and not round_.get('error')
            and bool(round_.get('attempts'))
            and round_['attempts'][-1]['verdict'] == 'uncertain'
        )

    def active_execution_group(self):
        """First submitted group with generation or review work still open."""
        groups = dict.fromkeys(
            j['execution_group'] for j in self.studio.jobs if j.get('execution_group')
        )
        for group in groups:
            if any(
                j.get('execution_group') == group
                and j['status'] in ('queued', 'running', 'cancelling')
                for j in self.studio.jobs
            ):
                return group
            if any(
                r.get('execution_group') == group and not self._group_round_terminal(r)
                for r in self.rounds
            ):
                return group
        return None

    def next_generation_job(self):
        group = self.active_execution_group()
        if group is not None:
            # A finished generation batch must enter review before a later
            # character's queued work can start.
            return next(
                (
                    j
                    for j in self.studio.jobs
                    if j['status'] == 'queued' and j.get('execution_group') == group
                ),
                None,
            )
        return next((j for j in self.studio.jobs if j['status'] == 'queued'), None)

    def _source_job(self, path):
        image = self.studio.gallery._safe_path(path)
        if not image.is_file():
            raise ValueError('Source image not found')
        meta = self.studio.gallery.metadata(path)
        snapshot = (
            meta if isinstance(meta, dict) and isinstance(meta.get('settings'), dict) else None
        )
        if not snapshot or not snapshot.get('positive') or 'negative' not in snapshot:
            raise ValueError('Source has no original generation snapshot')
        source_job = next(
            (job for job in self.studio.jobs if job['id'] == meta.get('job_id')), None
        )
        keys = (
            'work_id',
            'character_id',
            'outfit_id',
            'expression_id',
            'expression_name',
            'category',
        )
        job = {key: meta.get(key) for key in keys}
        job['id'] = str(meta.get('job_id') or '')
        job['seed'] = meta.get('settings', {}).get('seed')
        if any(
            not job[key]
            for key in ('work_id', 'character_id', 'outfit_id', 'expression_id', 'category')
        ):
            raise ValueError('Source generation identifiers are incomplete')
        job['snapshot'] = copy.deepcopy(source_job['snapshot'] if source_job else snapshot)
        if source_job and source_job.get('execution_group'):
            job['execution_group'] = source_job['execution_group']
        elif snapshot.get('execution_group'):
            job['execution_group'] = snapshot['execution_group']
        job['source_generation_job_id'] = meta.get('job_id')
        job['source_generation_path'] = path
        job['source_is_postprocessed'] = bool((meta.get('postprocessing') or {}).get('applied'))
        return job

    def _fresh_job(self, source, round_id, regeneration):
        job = copy.deepcopy(source)
        seed = secrets.randbits(32)
        if seed == source.get('seed'):
            seed = (seed + 1) % (2**32)
        job.update(
            id=uuid.uuid4().hex,
            status='queued',
            created_at=_now(),
            seed=seed,
            regeneration=regeneration,
        )
        job['snapshot']['settings']['seed'] = seed
        job['snapshot']['source_generation_job_id'] = source.get(
            'source_generation_job_id'
        ) or source.get('id')
        job['snapshot']['source_generation_path'] = source.get('source_generation_path')
        job['snapshot']['source_was_postprocessed'] = bool(source.get('source_is_postprocessed'))
        job['snapshot']['regeneration'] = regeneration
        job['snapshot'].pop('review_round_id', None)
        if round_id is not None:
            job['review_round_id'] = round_id
            job['snapshot']['review_round_id'] = round_id
        if job.get('execution_group'):
            job['snapshot']['execution_group'] = job['execution_group']
        job['snapshot'].pop('postprocessing', None)
        return job

    def manual_regenerate(self, items):
        """Queue each image again with a new seed.

        With VLM review on, every image starts a review round. With it off, the new
        jobs are plain queue entries and a person judges the results.
        """
        reviewing = bool(self.settings['enabled'] and self.vlm.enabled)
        if not isinstance(items, list) or not 1 <= len(items) <= 100:
            raise ValueError('Select 1 to 100 images')
        import hashlib

        with self.studio.lock, self._lock:
            prepared = []
            seen = set()
            combos = set()
            postprocessed_selected = False
            for item in items:
                path = item.get('path') if isinstance(item, dict) else None
                if not isinstance(path, str) or path in seen:
                    raise ValueError('Each image path must be unique')
                seen.add(path)
                image = self.studio.gallery._safe_path(path)
                if (
                    item.get('sha256')
                    and hashlib.sha256(image.read_bytes()).hexdigest() != item['sha256']
                ):
                    raise ValueError('Image changed; refresh the gallery')
                source = self._source_job(path)
                postprocessed_selected = postprocessed_selected or source['source_is_postprocessed']
                if not reviewing:
                    prepared.append((None, self._fresh_job(source, None, 0)))
                    continue
                combo = self.combo(source)
                if combo in combos:
                    raise ValueError('Select one source image per combination')
                combos.add(combo)
                if any(
                    r['status']
                    in (
                        'waiting_generation',
                        'pending_review',
                        'reviewing',
                        'switching',
                        'queueing',
                    )
                    and tuple(r['combo']) == combo
                    for r in self.rounds
                ):
                    raise ValueError('A review round is already active for this combination')
                round_ = self._round(source, path, manual=True)
                fresh = self._fresh_job(source, round_['id'], 0)
                round_['current_job_id'] = fresh['id']
                prepared.append((round_, fresh))
            if sum(j['status'] == 'queued' for j in self.studio.jobs) + len(prepared) > 5000:
                raise ValueError('Generation queue is full')
            # Reserve round identity before the queue write. Restart uncertainty
            # becomes needs_attention, never another generation POST.
            rounds = [r for r, _ in prepared if r is not None]
            if rounds:
                self.rounds.extend(rounds)
                self.persist()
            self.studio.jobs.extend(j for _, j in prepared)
            self.studio.persist()
            return {
                'ok': True,
                'count': len(prepared),
                'reviewing': reviewing,
                'rounds': copy.deepcopy(rounds),
                'warning': Msg(
                    'server.pipeline.post_processed_images_are_regenerated_from',
                    'Post-processed images are regenerated from their original settings; later '
                    'corrections are not reproduced.',
                )
                if postprocessed_selected
                else '',
            }

    def _review_record(self, round_, job, verdict, evidence):
        path = job['image_url'].removeprefix('/outputs/')
        path = unquote(path)
        entry = {
            'job_id': job['id'],
            'path': path,
            'verdict': verdict,
            'evidence': evidence,
            'reviewed_at': _now(),
            'regeneration': round_['regenerations'],
        }
        entry['reviewer_model'] = self.vlm._value(self.vlm.config, 'model')
        entry['reviewer_model_resource'] = self.vlm.config.get('model_resource')
        entry['review_instruction_version'] = self.vlm.config.get('review_instruction_version')
        entry['max_output_tokens'] = self.vlm.config.get('max_output_tokens')
        round_['attempts'].append(entry)
        if hasattr(self.studio, 'review_store'):
            self.studio.review_store.record_auto(
                path, verdict, evidence, {'round_id': round_['id'], 'job_id': job['id']}
            )

    def process_ready(self):
        self.reconcile()
        if self.studio.paused or not self.settings['enabled'] or not self.vlm.enabled:
            return False
        with self.studio.lock, self._lock:
            active_group = self.active_execution_group()
            if not self.studio.gpu.generation_allowed() or any(
                j['status'] in ('queued', 'running', 'cancelling')
                and (active_group is None or j.get('execution_group') == active_group)
                for j in self.studio.jobs
            ):
                return False
            ready = [
                r
                for r in self.rounds
                if r['status'] == 'pending_review'
                and (active_group is None or r.get('execution_group') == active_group)
            ]
            if not ready:
                return False
            if not self.studio.gpu.acquire('validation', 'waiting_comfy_idle'):
                return False
            for round_ in ready:
                round_['status'] = 'switching'
            self.persist()
        unloaded = False
        load_started = False
        try:
            queue = self.studio.comfy.request('/queue')
            if queue.get('queue_running') or queue.get('queue_pending'):
                with self._lock:
                    for round_ in ready:
                        round_['status'] = 'pending_review'
                    self.persist()
                unloaded = True
                return False
            if all(round_['status'] == 'human_accepted' for round_ in ready):
                unloaded = True
                return False
            gpu = self.studio.gpu
            gpu.update('validation', 'freeing_comfy')
            self.studio.comfy.request('/free', {'unload_models': True, 'free_memory': True})
            if gpu.admit('vlm'):
                # Not enough room for the VLM; the rounds wait for the next pass.
                with self._lock:
                    for round_ in ready:
                        if round_['status'] == 'switching':
                            round_['status'] = 'pending_review'
                    self.persist()
                unloaded = True
                return False
            gpu.update('validation', 'loading_vlm')
            load_started = True
            self.vlm.load()
            gpu.update('validation', 'reviewing')
            for round_ in ready:
                with self.studio.lock, self._lock:
                    if round_['status'] == 'human_accepted':
                        continue
                    if self.studio.paused:
                        round_['status'] = 'pending_review'
                        self.persist()
                        continue
                    job = next(
                        (j for j in self.studio.jobs if j['id'] == round_['current_job_id']), None
                    )
                    if not job or job['status'] != 'completed':
                        round_['status'] = 'needs_attention'
                        round_['error'] = 'Completed job missing from queue history.'
                        self.persist()
                        continue
                    path = self.studio.gallery._safe_path(
                        unquote(job['image_url'].removeprefix('/outputs/'))
                    )
                    round_['status'] = 'reviewing'
                    self.persist()
                try:
                    result = self.vlm.review(path, job['snapshot'])
                except Exception as exc:
                    result = {'verdict': 'error', 'evidence': str(exc)[:300]}
                with self.studio.lock, self._lock:
                    self._review_record(round_, job, result['verdict'], result['evidence'])
                    if round_['status'] == 'human_accepted':
                        pass
                    elif self.studio.paused:
                        round_['status'] = 'needs_attention'
                        round_['error'] = 'Review paused by user; start a new round when ready.'
                    elif result['verdict'] == 'error':
                        round_['technical_errors'] += 1
                        round_['status'] = (
                            'needs_attention'
                            if round_['technical_errors'] >= 3
                            else 'pending_review'
                        )
                    elif result['verdict'] == 'pass':
                        round_['status'] = 'awaiting_human'
                    elif result['verdict'] == 'uncertain':
                        round_['status'] = 'needs_attention'
                    else:
                        round_['status'] = 'failed_review'
                    self.persist()
            gpu.update('validation', 'unloading_vlm')
            self.vlm.unload()
            unloaded = True
            with self.studio.lock, self._lock:
                for round_ in ready:
                    if round_['status'] != 'failed_review':
                        continue
                    if self.studio.paused:
                        round_['status'] = 'needs_attention'
                        round_['error'] = 'Review paused by user; start a new round when ready.'
                    elif self._human_accepted(round_):
                        round_['status'] = 'human_accepted'
                    elif round_['regenerations'] >= round_['max_auto_regenerations']:
                        round_['status'] = 'limit_reached'
                    else:
                        original = self._source_job(round_['attempts'][-1]['path'])
                        round_['status'] = 'queueing'
                        self.persist()
                        fresh = self._fresh_job(original, round_['id'], round_['regenerations'] + 1)
                        self.studio.jobs.append(fresh)
                        self.studio.persist()
                        round_['current_job_id'] = fresh['id']
                        round_['regenerations'] += 1
                        round_['status'] = 'waiting_generation'
                    self.persist()
            return True
        except Exception as exc:
            error = str(exc)[:300]
            with self._lock:
                for round_ in ready:
                    if round_['status'] in ('switching', 'reviewing', 'failed_review'):
                        round_['status'] = 'needs_attention'
                        round_['error'] = error
                self.persist()
            raise
        finally:
            blocked = None
            if not unloaded:
                try:
                    if self.vlm.owned:
                        self.vlm.unload()
                    elif load_started and self.vlm._loaded_instances():
                        raise VLMError('VLM instance loaded with uncertain ownership')
                    unloaded = True
                except Exception as exc:
                    blocked = 'VLM unload not confirmed: ' + str(exc)[:250]
            # Generation may only resume once the VLM is known to be off the GPU.
            if unloaded:
                self.studio.gpu.release('validation')
            else:
                self.studio.gpu.block('validation', blocked or 'VLM unload not confirmed')

    def _human_accepted(self, round_):
        store = getattr(self.studio, 'review_store', None)
        if store is None:
            return False
        # A prior accepted image remains selected, but only a new approval stops
        # a round deliberately started after that earlier decision.
        revision = store.human_acceptance_revision(round_['combo'])
        return bool(revision and revision > round_.get('human_baseline_revision', 0))

    def human_review_changed(self):
        with self.studio.lock, self._lock:
            changed = False
            for round_ in self.rounds:
                if round_['status'] in (
                    'waiting_generation',
                    'pending_review',
                    'switching',
                    'reviewing',
                    'failed_review',
                    'needs_attention',
                    'awaiting_human',
                ) and self._human_accepted(round_):
                    round_['status'] = 'human_accepted'
                    for job in self.studio.jobs:
                        if (
                            job['id'] == round_['current_job_id']
                            and job.get('review_round_id') == round_['id']
                        ):
                            if job['status'] == 'queued':
                                job['status'] = 'cancelled'
                            elif job['status'] == 'running':
                                job['status'] = 'cancelling'
                    changed = True
            if changed:
                self.persist()
                self.studio.persist()
