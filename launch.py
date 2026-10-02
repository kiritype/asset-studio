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

# Message boxes follow the Studio language setting, or Windows' language when it is "auto".
TEXT = {
    'running': {
        'ko': '생성 중인 작업 {n}개 (중단됨으로 남습니다)',
        'en': '{n} job(s) generating (they will be marked as stopped)',
        'ja': '生成中のジョブ {n} 件(中断として残ります)',
        'zh-CN': '正在生成的任务 {n} 个(将记为已中断)',
    },
    'queued': {
        'ko': '대기 중인 작업 {n}개 (다음 실행 때 일시정지 상태로 남습니다)',
        'en': '{n} queued job(s) (the queue stays paused at the next start)',
        'ja': '待機中のジョブ {n} 件(次回起動時は一時停止のまま残ります)',
        'zh-CN': '排队中的任务 {n} 个(下次启动时保持暂停)',
    },
    'unknown_jobs': {
        'ko': '작업 상태를 확인하지 못했습니다',
        'en': 'The job status could not be checked',
        'ja': 'ジョブの状態を確認できませんでした',
        'zh-CN': '无法确认任务状态',
    },
    'training': {
        'ko': 'LoRA 학습 중 (학습이 중단됩니다)',
        'en': 'A LoRA is training (training will stop)',
        'ja': 'LoRA 学習中(学習が中断されます)',
        'zh-CN': 'LoRA 训练中(训练将中断)',
    },
    'confirm_stop': {
        'ko': '지금 멈추면 다음이 중단됩니다.\n\n- {reasons}\n\n그래도 멈출까요?',
        'en': 'Stopping now will cut off:\n\n- {reasons}\n\nStop anyway?',
        'ja': '今止めると次のものが中断されます。\n\n- {reasons}\n\nそれでも止めますか?',
        'zh-CN': '现在停止会中断以下内容:\n\n- {reasons}\n\n仍要停止吗?',
    },
    'no_process': {
        'ko': 'Asset Studio 프로세스를 찾지 못했습니다.',
        'en': 'The Asset Studio process was not found.',
        'ja': 'Asset Studio のプロセスが見つかりませんでした。',
        'zh-CN': '未找到 Asset Studio 进程。',
    },
    'not_stopped': {
        'ko': 'Asset Studio를 멈추지 못했습니다.',
        'en': 'Asset Studio could not be stopped.',
        'ja': 'Asset Studio を停止できませんでした。',
        'zh-CN': '无法停止 Asset Studio。',
    },
    'not_started': {
        'ko': 'Asset Studio를 실행하지 못했습니다. logs/launcher.log를 확인하세요.',
        'en': 'Asset Studio could not start. See logs/launcher.log.',
        'ja': 'Asset Studio を起動できませんでした。logs/launcher.log を確認してください。',
        'zh-CN': '无法启动 Asset Studio。请查看 logs/launcher.log。',
    },
    'stopped': {
        'ko': 'Asset Studio를 멈췄습니다.',
        'en': 'Asset Studio has stopped.',
        'ja': 'Asset Studio を停止しました。',
        'zh-CN': 'Asset Studio 已停止。',
    },
    'not_running': {
        'ko': 'Asset Studio가 실행 중이 아닙니다.',
        'en': 'Asset Studio is not running.',
        'ja': 'Asset Studio は実行されていません。',
        'zh-CN': 'Asset Studio 未在运行。',
    },
    'restarted': {
        'ko': 'Asset Studio를 다시 시작했습니다. 열려 있는 탭은 새로고침하세요.',
        'en': 'Asset Studio has restarted. Reload any open tabs.',
        'ja': 'Asset Studio を再起動しました。開いているタブは再読み込みしてください。',
        'zh-CN': 'Asset Studio 已重新启动。请刷新已打开的标签页。',
    },
}


def language():
    try:
        settings = json.loads((ROOT / 'data' / 'settings' / 'ui.json').read_text(encoding='utf-8'))
        chosen = settings.get('language', 'auto')
    except (OSError, ValueError):
        chosen = 'auto'
    if chosen in ('ko', 'en', 'ja', 'zh-CN'):
        return chosen
    if sys.platform == 'win32':
        import ctypes

        primary = ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF
        return {0x12: 'ko', 0x11: 'ja', 0x04: 'zh-CN'}.get(primary, 'en')
    return 'en'


def say(key, **values):
    return TEXT[key][language()].format(**values)


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
            reasons.append(say('running', n=running))
        if queued:
            reasons.append(say('queued', n=queued))
    except Exception:
        reasons.append(say('unknown_jobs'))
    try:
        gpu = get('/api/gpu')
        if gpu.get('holder') == 'training':
            reasons.append(say('training'))
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
    if reasons and not ask(say('confirm_stop', reasons='\n- '.join(reasons))):
        return False
    pid = server_pid()
    if pid is None:
        message(say('no_process'), icon=16)
        return False
    # The queue is saved on every change, so a forced stop loses nothing that was saved.
    subprocess.run(['taskkill', '/PID', str(pid), '/T', '/F'], capture_output=True, check=False)
    for _ in range(40):
        if not healthy() and server_pid() is None:
            return True
        time.sleep(0.25)
    message(say('not_stopped'), icon=16)
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
        message(say('not_started'), icon=16)
        raise SystemExit(1)
    if open_browser:
        webbrowser.open(URL)


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'start'
    if action == 'stop':
        was_running = healthy()
        if stop() and was_running:
            message(say('stopped'))
        elif not was_running:
            message(say('not_running'))
    elif action == 'restart':
        if stop():
            # Open tabs only need a reload; a new tab is opened when none was running.
            start(open_browser=False)
            message(say('restarted'))
    else:
        start()
