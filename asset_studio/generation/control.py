"""Manage only ComfyUI processes started by this Studio instance."""

import copy
import json
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from ..i18n import Msg, message_of
from ..library.service import Library
from ..util import settings_file


class ComfyControl:
    def __init__(self, studio, preview=False):
        self.studio, self.preview = studio, preview
        self.path = settings_file(studio.root, 'connection.json')
        self.config = {
            'url': studio.comfy.url,
            # Machine paths live in data/settings/connection.json.
            'python_path': '',
            'comfy_path': '',
            'arguments': ['--preview-method', 'auto'],
        }
        if self.path.exists():
            self.config.update(json.loads(self.path.read_text(encoding='utf-8')))
            studio.comfy.url = self.config['url'].rstrip('/')
        self.process = None
        self.operation = None
        self.error = None
        self.lock = threading.RLock()

    def status(self):
        # Status checks never refresh catalog choices or reset the generation form.
        try:
            stats = self.studio.comfy.request('/system_stats', timeout=2)
            queue = self.studio.comfy.request('/queue', timeout=2)
            connected = True
            error = None
        except Exception as exc:
            stats, queue, connected, error = {}, {}, False, message_of(exc)
        owned = self.process is not None and self.process.poll() is None
        return {
            'connected': connected,
            'owned': owned,
            'preview': self.preview,
            'operation': self.operation,
            'error': self.error or error,
            'url': self.config['url'],
            'running': len(queue.get('queue_running', [])),
            'pending': len(queue.get('queue_pending', [])),
            'system': stats.get('system', {}),
            'devices': stats.get('devices', []),
            'can_start': not self.preview and not connected and not owned and not self.operation,
            'can_stop': not self.preview and owned and not self.operation,
            'can_restart': not self.preview and owned and not self.operation,
        }

    def save(self, body):
        if self.preview:
            raise ValueError(
                Msg(
                    'server.control.the_preview_server_does_not_change',
                    'The preview server does not change the ComfyUI connection.',
                )
            )
        with self.lock, self.studio.lock:
            if self.studio.gpu.busy_except('comfy_control'):
                raise ValueError(
                    Msg(
                        'server.control.the_gpu_is_in_use_by',
                        'The GPU is in use by {name}. Change this after it finishes.',
                        name=self.studio.gpu.label(),
                    )
                )
            if self.operation or self.process is not None and self.process.poll() is None:
                raise ValueError(
                    Msg(
                        'server.control.stop_the_comfyui_this_app_started',
                        'Stop the ComfyUI this app started before changing the connection.',
                    )
                )
            if any(j['status'] in ('running', 'cancelling') for j in self.studio.jobs) or (
                not self.studio.paused and any(j['status'] == 'queued' for j in self.studio.jobs)
            ):
                raise ValueError(
                    Msg(
                        'server.control.the_queue_is_running_change_the',
                        'The queue is running. Change the connection after it finishes.',
                    )
                )
            config = copy.deepcopy(self.config)
            config.update({k: body[k] for k in config if k in body})
            parsed = urlparse(config['url'])
            if (
                parsed.scheme != 'http'
                or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
                or parsed.username
                or parsed.password
                or parsed.path not in ('', '/')
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError(
                    Msg(
                        'server.control.enter_the_http_address_of_your',
                        'Enter the http address of your local ComfyUI.',
                    )
                )
            if not parsed.port:
                raise ValueError(
                    Msg('server.control.set_the_comfyui_port', 'Set the ComfyUI port.')
                )
            if not isinstance(config['arguments'], list) or not all(
                isinstance(x, str) and len(x) < 1000 for x in config['arguments']
            ):
                raise ValueError(
                    Msg(
                        'server.control.launch_arguments_must_be_an_array',
                        'Launch arguments must be an array of text.',
                    )
                )
            if (
                not Path(config['python_path']).is_file()
                or not (Path(config['comfy_path']) / 'main.py').is_file()
            ):
                raise ValueError(
                    Msg(
                        'server.control.check_the_python_or_comfyui_main',
                        'Check the Python or ComfyUI main.py path.',
                    )
                )
            if self.path.exists():
                Library.write(
                    self.studio.root
                    / 'data/backups'
                    / ('connection-' + str(time.time_ns()) + '.json'),
                    self.config,
                )
            Library.write(self.path, config)
            self.config = config
            self.studio.comfy.url = config['url'].rstrip('/')
            return {'ok': True, 'config': config}

    def control(self, action):
        if self.preview:
            raise ValueError(
                Msg(
                    'server.control.the_preview_does_not_control_a',
                    'The preview does not control a running ComfyUI.',
                )
            )
        if action not in ('start', 'stop', 'restart'):
            raise ValueError(
                Msg('server.control.unsupported_control_command', 'Unsupported control command.')
            )
        with self.lock:
            if self.operation:
                raise ValueError(
                    Msg(
                        'server.control.a_control_action_is_already_running',
                        'A control action is already running.',
                    )
                )
            if self.studio.gpu.busy_except('comfy_control'):
                raise ValueError(
                    Msg(
                        'server.control.the_gpu_is_in_use_by_2',
                        'The GPU is in use by {name}. Try again after it finishes.',
                        name=self.studio.gpu.label(),
                    )
                )
            status = self.status()
            if not status['can_' + action]:
                raise ValueError(
                    Msg(
                        'server.control.this_process_cannot_be_controlled_manage',
                        'This process cannot be controlled. Manage a ComfyUI started elsewhere '
                        '(for example Stability Matrix) from that app.',
                    )
                )
            self.operation = action
            self.error = None
            # Holding the GPU stops new jobs without touching the user's paused setting.
            if not self.studio.gpu.acquire('comfy_control', action):
                self.operation = None
                raise ValueError(
                    Msg(
                        'server.control.the_gpu_is_in_use_by_2',
                        'The GPU is in use by {name}. Try again after it finishes.',
                        name=self.studio.gpu.label(),
                    )
                )
            threading.Thread(target=self._run, args=(action,), daemon=True).start()
        return {'ok': True, 'operation': action}

    def _start(self):
        config = self.config
        python = Path(config['python_path'])
        folder = Path(config['comfy_path'])
        if not python.is_file() or not (folder / 'main.py').is_file():
            raise ValueError(
                Msg(
                    'server.control.the_python_or_comfyui_path_is',
                    'The Python or ComfyUI path is missing.',
                )
            )
        # Probe again immediately before spawning; never launch over an external server.
        if self.status()['connected']:
            raise ValueError(
                Msg(
                    'server.control.another_comfyui_is_already_connected',
                    'Another ComfyUI is already connected.',
                )
            )
        args = list(config['arguments'])
        if '--port' not in args:
            args += ['--port', str(urlparse(config['url']).port)]
        if '--listen' not in args:
            args += ['--listen', '127.0.0.1']
        logs = self.studio.root / 'logs'
        logs.mkdir(exist_ok=True)
        with (logs / 'comfy-managed.log').open('ab') as log:
            self.process = subprocess.Popen(
                [str(python), str(folder / 'main.py'), *args],
                cwd=folder,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        for _ in range(180):
            if self.process.poll() is not None:
                raise RuntimeError(
                    Msg(
                        'server.control.comfyui_failed_to_start_check_logs',
                        'ComfyUI failed to start: check logs/comfy-managed.log.',
                    )
                )
            if self.status()['connected']:
                return
            time.sleep(1)
        raise RuntimeError(
            Msg(
                'server.control.timed_out_waiting_for_comfyui_check',
                'Timed out waiting for ComfyUI. Check the log.',
            )
        )

    def _run(self, action):
        succeeded = False
        try:
            if action != 'start':
                deadline = time.monotonic() + 1800
                while time.monotonic() < deadline:
                    with self.studio.lock:
                        busy = any(
                            j['status'] in ('running', 'cancelling') for j in self.studio.jobs
                        )
                    status = self.status()
                    if (
                        not busy
                        and status['connected']
                        and not status['running']
                        and not status['pending']
                    ):
                        break
                    time.sleep(1)
                else:
                    raise RuntimeError(
                        Msg(
                            'server.control.timed_out_waiting_for_the_current',
                            'Timed out waiting for the current image, so the control action was '
                            'cancelled.',
                        )
                    )
                if self.process is not None and self.process.poll() is None:
                    self.process.terminate()
                    self.process.wait(timeout=30)
                if action == 'restart':
                    self._start()
            else:
                self._start()
            succeeded = True
        except Exception as exc:
            self.error = message_of(exc)
        finally:
            # A deliberate stop must not make the next queued job fail against an
            # offline server, so the GPU stays held until a start succeeds.
            offline = (action == 'stop' and succeeded) or (
                action in ('start', 'restart') and not succeeded
            )
            if offline:
                self.studio.gpu.update('comfy_control', 'comfy_offline')
            else:
                self.studio.gpu.release('comfy_control')
            self.operation = None
