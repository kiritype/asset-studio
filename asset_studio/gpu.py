"""Who may use the GPU right now.

Generation uses the GPU whenever nobody else holds it. VLM review, ComfyUI process
control and outside tools (LoRA training) take the GPU exclusively; while they hold
it the generation worker starts no new job.
"""

import json
import secrets

from .gpu_monitor import GpuMonitor
from .i18n import Msg, message_of
from .util import atomic_json, now, state_file

HOLDER_LABELS = {
    'validation': Msg('server.gpu.vlm_review', 'VLM review'),
    'comfy_control': Msg('server.gpu.comfyui_control', 'ComfyUI control'),
    'external': Msg('server.gpu.external_work', 'External work'),
    'training': Msg('server.gpu.lora_training', 'LoRA training'),
}
STATE_LABELS = {
    'waiting_comfy_idle': Msg(
        'server.gpu.waiting_for_comfyui_to_finish_its', 'Waiting for ComfyUI to finish its work'
    ),
    'freeing_comfy': Msg('server.gpu.freeing_comfyui_memory', 'Freeing ComfyUI memory'),
    'loading_vlm': Msg('server.gpu.loading_the_vlm', 'Loading the VLM'),
    'reviewing': Msg('server.gpu.reviewing', 'Reviewing'),
    'unloading_vlm': Msg('server.gpu.unloading_the_vlm', 'Unloading the VLM'),
    'blocked': Msg('server.gpu.check_needed', 'Check needed'),
    'start': Msg('server.gpu.starting', 'Starting'),
    'stop': Msg('server.gpu.waiting_to_stop', 'Waiting to stop'),
    'restart': Msg('server.gpu.waiting_to_restart', 'Waiting to restart'),
    'comfy_offline': Msg('server.gpu.comfyui_stopped', 'ComfyUI stopped'),
    'reserved': Msg('server.gpu.in_use', 'In use'),
    'preparing': Msg('server.gpu.preparing_training', 'Preparing training'),
    'preprocessing': Msg('server.gpu.preprocessing_for_training', 'Preprocessing for training'),
    'training': Msg('server.gpu.training', 'Training'),
}
ACTIVE_JOB_STATES = ('running', 'cancelling')


class GpuBroker:
    """Exclusive GPU ownership. ``lock`` is the Studio lock that also guards the queue."""

    def __init__(self, root, lock, jobs, monitor=None):
        self.lock = lock
        self.monitor = monitor or GpuMonitor(root)
        self.waiting = None  # {'kind', 'reason', 'since'} while work is held back.
        self._jobs = jobs  # Callable returning the current queue list.
        self.path = state_file(root, 'gpu.json')
        self.holder = None
        self.state = 'idle'
        self.owner = ''
        self.error = None
        self.since = None
        self.token = None
        self._load()

    def _load(self):
        """An outside reservation survives a restart: the tool may still be using the GPU."""
        if not self.path.is_file():
            return
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        if saved.get('holder') == 'external' and saved.get('token'):
            self.holder, self.state = 'external', 'reserved'
            self.owner = saved.get('owner', '')
            self.since = saved.get('since')
            self.token = saved['token']

    def _persist(self):
        reservation = (
            {'holder': self.holder, 'owner': self.owner, 'since': self.since, 'token': self.token}
            if self.holder == 'external'
            else {}
        )
        if reservation or self.path.exists():
            atomic_json(self.path, {'schema_version': 1, **reservation})

    # ---- in-process holders ------------------------------------------------------

    def acquire(self, holder, state, owner=''):
        """Take the GPU; True when it was free or already held by ``holder``."""
        with self.lock:
            if self.holder not in (None, holder):
                return False
            if self.holder is None:
                self.since = now()
                self.error = None
            self.holder, self.state, self.owner = holder, state, owner
            return True

    def update(self, holder, state):
        with self.lock:
            if self.holder == holder:
                self.state = state

    def block(self, holder, error):
        """Keep holding after a failure whose GPU effect is unknown; a person must clear it."""
        with self.lock:
            if self.holder == holder:
                self.state, self.error = 'blocked', message_of(error)

    def release(self, holder):
        with self.lock:
            if self.holder != holder:
                return
            self.holder, self.state, self.owner, self.error = None, 'idle', '', None
            self.since = self.token = None
            self._persist()

    def held_by(self, holder):
        return self.holder == holder

    def generation_allowed(self):
        return self.holder is None

    def admit(self, kind):
        """Outside-program check before starting ``kind`` of work; returns the reason to wait.

        Runs ``nvidia-smi`` / ``tasklist``, so callers must not hold the Studio lock.
        """
        reason = self.monitor.check(kind)
        with self.lock:
            if reason is None:
                self.waiting = None
            elif not self.waiting or self.waiting['reason'] != reason:
                self.waiting = {'kind': kind, 'reason': reason, 'since': now()}
        return reason

    def busy_except(self, holder):
        """True when someone other than ``holder`` has the GPU."""
        return self.holder not in (None, holder)

    # ---- outside tools (LoRA training) ------------------------------------------------

    def reserve(self, body):
        """Hand the GPU to an outside tool once no image is being generated."""
        owner = body.get('owner') if isinstance(body, dict) else None
        if not isinstance(owner, str) or not owner.strip() or len(owner) > 200:
            raise ValueError(
                Msg('server.gpu.owner_say_what_is_using_the', 'owner: say what is using the GPU.')
            )
        with self.lock:
            if self.holder is not None:
                raise ValueError(
                    Msg(
                        'server.gpu.the_gpu_is_in_use_by',
                        'The GPU is in use by {name}.',
                        name=self.label(),
                    )
                )
            if any(job['status'] in ACTIVE_JOB_STATES for job in self._jobs()):
                raise ValueError(
                    Msg(
                        'server.gpu.you_can_reserve_after_the_current',
                        'You can reserve after the current image finishes.',
                    )
                )
            self.acquire('external', 'reserved', owner.strip())
            self.token = secrets.token_hex(16)
            self._persist()
            return {'ok': True, 'token': self.token, **self.status()}

    def release_reservation(self, body):
        """End an outside reservation. ``force`` clears one whose tool has gone away."""
        body = body if isinstance(body, dict) else {}
        with self.lock:
            if self.holder != 'external':
                return {'ok': True, **self.status()}
            if not body.get('force') and body.get('token') != self.token:
                raise ValueError(
                    Msg(
                        'server.gpu.the_reservation_token_does_not_match',
                        'The reservation token does not match.',
                    )
                )
            self.release('external')
            return {'ok': True, **self.status()}

    # ---- reporting ----------------------------------------------------------------------

    def label(self):
        if self.holder is None:
            return Msg('server.gpu.image_generation', 'Image generation')
        name = HOLDER_LABELS.get(self.holder, self.holder)
        return f'{name} ({self.owner})' if self.owner else name

    def status(self):
        with self.lock:
            running = sum(job['status'] in ACTIVE_JOB_STATES for job in self._jobs())
            return {
                'holder': self.holder,
                'state': self.state,
                'state_label': STATE_LABELS.get(self.state, '') if self.holder else '',
                'label': self.label(),
                'owner': self.owner,
                'since': self.since,
                'error': self.error,
                'generation_allowed': self.holder is None,
                'running_jobs': running,
                'waiting': self.waiting,
                **self.monitor.snapshot(),
            }
