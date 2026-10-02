"""Manage only ComfyUI processes started by this Studio instance."""

import copy
import json
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

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
            stats, queue, connected, error = {}, {}, False, str(exc)
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
            raise ValueError('미리보기 서버에서는 ComfyUI 연결 설정을 변경하지 않습니다.')
        with self.lock, self.studio.lock:
            if self.studio.gpu.busy_except('comfy_control'):
                raise ValueError(
                    f'GPU를 {self.studio.gpu.label()}이(가) 쓰고 있습니다. 끝난 뒤에 바꾸세요.'
                )
            if self.operation or self.process is not None and self.process.poll() is None:
                raise ValueError('관리 중인 ComfyUI를 종료한 다음 연결 설정을 변경하세요.')
            if any(j['status'] in ('running', 'cancelling') for j in self.studio.jobs) or (
                not self.studio.paused and any(j['status'] == 'queued' for j in self.studio.jobs)
            ):
                raise ValueError('큐가 실행 중입니다. 연결 설정은 작업이 끝난 후 변경하세요.')
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
                raise ValueError('로컬 ComfyUI의 http 주소를 입력하세요.')
            if not parsed.port:
                raise ValueError('ComfyUI 포트를 지정하세요.')
            if not isinstance(config['arguments'], list) or not all(
                isinstance(x, str) and len(x) < 1000 for x in config['arguments']
            ):
                raise ValueError('실행 인자는 문자열 배열이어야 합니다.')
            if (
                not Path(config['python_path']).is_file()
                or not (Path(config['comfy_path']) / 'main.py').is_file()
            ):
                raise ValueError('Python 또는 ComfyUI main.py 경로를 확인하세요.')
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
            raise ValueError('미리보기에서는 실행 중인 ComfyUI를 제어하지 않습니다.')
        if action not in ('start', 'stop', 'restart'):
            raise ValueError('지원하지 않는 실행 명령입니다.')
        with self.lock:
            if self.operation:
                raise ValueError('이미 실행 제어 작업이 진행 중입니다.')
            if self.studio.gpu.busy_except('comfy_control'):
                raise ValueError(
                    f'GPU를 {self.studio.gpu.label()}이(가) 쓰고 있습니다. 끝난 뒤에 하세요.'
                )
            status = self.status()
            if not status['can_' + action]:
                raise ValueError(
                    '현재 프로세스는 실행 제어할 수 없습니다. '
                    'Stability Matrix에서 시작한 ComfyUI는 해당 앱에서 관리하세요.'
                )
            self.operation = action
            self.error = None
            # Holding the GPU stops new jobs without touching the user's paused setting.
            if not self.studio.gpu.acquire('comfy_control', action):
                self.operation = None
                raise ValueError(
                    f'GPU를 {self.studio.gpu.label()}이(가) 쓰고 있습니다. 끝난 뒤에 하세요.'
                )
            threading.Thread(target=self._run, args=(action,), daemon=True).start()
        return {'ok': True, 'operation': action}

    def _start(self):
        config = self.config
        python = Path(config['python_path'])
        folder = Path(config['comfy_path'])
        if not python.is_file() or not (folder / 'main.py').is_file():
            raise ValueError('Python 또는 ComfyUI 경로가 없습니다.')
        # Probe again immediately before spawning; never launch over an external server.
        if self.status()['connected']:
            raise ValueError('다른 ComfyUI가 이미 연결되어 있습니다.')
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
                raise RuntimeError('ComfyUI 시작 실패: logs/comfy-managed.log를 확인하세요.')
            if self.status()['connected']:
                return
            time.sleep(1)
        raise RuntimeError('ComfyUI 연결 대기 시간이 초과되었습니다. 로그를 확인하세요.')

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
                        '현재 이미지 완료를 기다리는 시간이 초과되어 실행 제어를 취소했습니다.'
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
            self.error = str(exc)
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
