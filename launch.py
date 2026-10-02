"""Start, stop or restart the local server without a terminal window.

``launch.py`` starts the server once and opens its UI; ``launch.py stop`` and
``launch.py restart`` stop it first. Stopping asks before cutting off running or
queued images and LoRA training.
"""

import json
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parent
PORT = 8195
URL = f'http://127.0.0.1:{PORT}'
opener = build_opener(ProxyHandler({}))
TITLE = 'Asset Studio'


def message(text, icon=64, buttons=0):
    """A message box on Windows (pythonw has no console); prints elsewhere. Returns the answer."""
    if sys.platform == 'win32':
        import ctypes

        return ctypes.windll.user32.MessageBoxW(0, text, TITLE, icon | buttons)
    print(text)
    return 6


def ask(text):
    return message(text, icon=48, buttons=4) == 6  # Yes/No, warning icon; 6 = Yes.


def get(path):
    with opener.open(URL + path, timeout=3) as response:
        return json.load(response)


def healthy():
    try:
        return get('/api/health').get('app') == 'Asset Studio'
    except Exception:
        return False


def busy_reasons():
    """What a stop would cut off: running or queued images, and LoRA training."""
    reasons = []
    try:
        jobs = get('/api/jobs').get('jobs', [])
        running = sum(job['status'] in ('running', 'cancelling') for job in jobs)
        queued = sum(job['status'] == 'queued' for job in jobs)
        if running:
            reasons.append(f'생성 중인 작업 {running}개 (중단됨으로 남습니다)')
        if queued:
            reasons.append(f'대기 중인 작업 {queued}개 (다음 실행 때 일시정지 상태로 남습니다)')
    except Exception:
        reasons.append('작업 상태를 확인하지 못했습니다')
    try:
        gpu = get('/api/gpu')
        if gpu.get('holder') == 'training':
            reasons.append('LoRA 학습 중 (학습이 중단됩니다)')
    except Exception:
        pass
    return reasons


def is_studio(pid):
    """True when ``pid`` runs Asset Studio (``-m asset_studio``), never anything else."""
    output = subprocess.run(
        [
            'powershell',
            '-NoProfile',
            '-Command',
            f'(Get-CimInstance Win32_Process -Filter "ProcessId={int(pid)}").CommandLine',
        ],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    return '-m asset_studio' in output


def server_pid():
    """Process id of the Studio server: the one listening on 127.0.0.1:PORT.

    Other programs may listen on the same port at another address (for example a
    remote-access proxy on a VPN address); those are never touched.
    """
    output = subprocess.run(
        ['netstat', '-ano', '-p', 'tcp'], capture_output=True, text=True, check=False
    ).stdout
    for line in output.splitlines():
        parts = line.split()
        # Columns: protocol, local address, remote address, state (localized), pid.
        if len(parts) >= 5 and parts[1] == f'127.0.0.1:{PORT}' and parts[2].endswith(':0'):
            pid = int(parts[-1])
            return pid if is_studio(pid) else None
    return None


def stop():
    """True when the server is no longer running."""
    if not healthy():
        return True
    reasons = busy_reasons()
    if reasons and not ask(
        '지금 멈추면 다음이 중단됩니다.\n\n- ' + '\n- '.join(reasons) + '\n\n그래도 멈출까요?'
    ):
        return False
    pid = server_pid()
    if pid is None:
        message('Asset Studio 프로세스를 찾지 못했습니다.', icon=16)
        return False
    # The queue is saved on every change, so a forced stop loses nothing that was saved.
    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, check=False)
    for _ in range(40):
        if not healthy() and server_pid() is None:
            return True
        time.sleep(0.25)
    message('Asset Studio를 멈추지 못했습니다.', icon=16)
    return False


def start(open_browser=True):
    if not healthy():
        (ROOT / 'logs').mkdir(parents=True, exist_ok=True)
        with (ROOT / 'logs' / 'launcher.log').open('a', encoding='utf-8') as log:
            process = subprocess.Popen(
                [sys.executable, '-m', 'asset_studio'],
                cwd=ROOT,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
            )
        for _ in range(40):
            if healthy() or process.poll() is not None:
                break
            time.sleep(0.25)
    if not healthy():
        message('Asset Studio를 실행하지 못했습니다. logs/launcher.log를 확인하세요.', icon=16)
        raise SystemExit(1)
    if open_browser:
        webbrowser.open(URL)


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'start'
    if action == 'stop':
        was_running = healthy()
        if stop() and was_running:
            message('Asset Studio를 멈췄습니다.')
        elif not was_running:
            message('Asset Studio가 실행 중이 아닙니다.')
    elif action == 'restart':
        if stop():
            # Open tabs only need a reload; a new tab is opened when none was running.
            start(open_browser=False)
            message('Asset Studio를 다시 시작했습니다. 열려 있는 탭은 새로고침하세요.')
    else:
        start()
