"""Checks that another program is not already using the GPU before Studio starts work.

Windows does not report per-process GPU memory, so the checks are coarse:
free VRAM on the device (``nvidia-smi``) against a minimum per kind of work, and a
list of programs that should make Studio wait while they run.
"""

import csv
import io
import json
import subprocess
import threading
import time

from .i18n import Msg
from .util import settings_file

DEFAULTS = {
    # MB of free VRAM needed right before starting. ComfyUI can offload, so the
    # generation minimum only catches a GPU that is almost full.
    'min_free_vram_mb': {'generation': 2048, 'tool': 1024, 'vlm': 16384, 'training': 16384},
    # Executable names (as in Task Manager) that make Studio wait while running.
    'watch_processes': [],
    'enabled': True,
}
CACHE_SECONDS = 3
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)


def _run(arguments):
    try:
        result = subprocess.run(
            arguments, capture_output=True, text=True, timeout=5, creationflags=NO_WINDOW
        )
        return result.stdout if result.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def read_vram():
    """(free MB, total MB) of the first GPU, or None when nvidia-smi is unavailable."""
    output = _run(
        ['nvidia-smi', '--query-gpu=memory.free,memory.total', '--format=csv,noheader,nounits']
    )
    if not output:
        return None
    try:
        free, total = (int(value) for value in output.splitlines()[0].split(','))
    except ValueError:
        return None
    return free, total


def running_programs():
    """Lower-case executable names of running processes (Windows ``tasklist``)."""
    output = _run(['tasklist', '/fo', 'csv', '/nh'])
    if not output:
        return set()
    return {row[0].lower() for row in csv.reader(io.StringIO(output)) if row}


class GpuMonitor:
    def __init__(self, root, vram=read_vram, programs=running_programs):
        self.path = settings_file(root, 'gpu.json')
        self._vram, self._programs = vram, programs
        self._cache = (0.0, None, set())
        self._lock = threading.Lock()

    def settings(self):
        """Checks are off until data/settings/gpu.json exists (see config/gpu.example.json)."""
        settings = json.loads(json.dumps(DEFAULTS))
        if not self.path.is_file():
            return {**settings, 'enabled': False}
        saved = json.loads(self.path.read_text(encoding='utf-8'))
        settings['min_free_vram_mb'].update(saved.get('min_free_vram_mb') or {})
        for key in ('watch_processes', 'enabled'):
            if key in saved:
                settings[key] = saved[key]
        return settings

    def _sample(self):
        with self._lock:
            stamp, vram, programs = self._cache
            if time.monotonic() - stamp > CACHE_SECONDS:
                vram, programs = self._vram(), self._programs()
                self._cache = (time.monotonic(), vram, programs)
            return vram, programs

    def check(self, kind):
        """None when ``kind`` of work may start, otherwise the reason to wait."""
        settings = self.settings()
        if not settings['enabled']:
            return None
        vram, programs = self._sample()
        watched = [name for name in settings['watch_processes'] if name.lower() in programs]
        if watched:
            return Msg(
                'server.gpu_monitor.a_program_using_the_gpu_is',
                'A program using the GPU is running: {watched}',
                watched=', '.join(watched),
            )
        need = settings['min_free_vram_mb'].get(kind, 0)
        if vram and vram[0] < need:
            return Msg(
                'server.gpu_monitor.not_enough_free_vram',
                'Free GPU memory is {free} MB, less than the {need} MB needed.',
                free=f'{vram[0]:,}',
                need=f'{need:,}',
            )
        return None

    def snapshot(self):
        if not self.settings()['enabled']:
            return {}
        vram, _ = self._sample()
        return {'vram_free_mb': vram[0], 'vram_total_mb': vram[1]} if vram else {}
