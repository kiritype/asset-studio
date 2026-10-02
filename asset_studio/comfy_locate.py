"""Find ComfyUI installs: the running one first, then the usual places on Windows.

Works for git clones with a venv, the portable build (``python_embeded``), Stability
Matrix packages and the ComfyUI desktop app. Nothing here changes settings; callers show
the candidates and let the person confirm. Standard library only, so the node installer
can use it with any Python.
"""

from __future__ import annotations

import json
import os
import string
import urllib.request
from pathlib import Path

from .i18n import Msg

KINDS = {
    'portable': Msg('server.comfy_locate.comfyui_portable', 'ComfyUI portable'),
    'stability_matrix': 'Stability Matrix',
    'desktop': Msg('server.comfy_locate.comfyui_desktop_app', 'ComfyUI desktop app'),
    'venv': Msg('server.comfy_locate.git_install_venv', 'git install (venv)'),
    'unknown': Msg('server.comfy_locate.unknown', 'Unknown'),
}


def is_comfy_dir(path: Path) -> bool:
    return (
        (path / 'main.py').is_file() and (path / 'comfy').is_dir() and (path / 'nodes.py').is_file()
    )


def python_for(comfy: Path) -> Path | None:
    """The Python that runs this ComfyUI, when it can be told from the folders."""
    for candidate in (
        comfy.parent / 'python_embeded' / 'python.exe',  # portable build
        comfy / 'venv' / 'Scripts' / 'python.exe',
        comfy / '.venv' / 'Scripts' / 'python.exe',
        comfy.parent / '.venv' / 'Scripts' / 'python.exe',  # desktop app base folder
    ):
        if candidate.is_file():
            return candidate
    return None


def kind_of(comfy: Path) -> str:
    if (comfy.parent / 'python_embeded').is_dir():
        return 'portable'
    if comfy.parent.name == 'Packages' and (comfy.parent.parent / 'Models').is_dir():
        return 'stability_matrix'
    if (comfy.parent / '.venv').is_dir() and not (comfy / '.git').exists():
        return 'desktop'
    if (comfy / 'venv').is_dir() or (comfy / '.venv').is_dir():
        return 'venv'
    return 'unknown'


def describe(comfy: Path, source: str) -> dict:
    python = python_for(comfy)
    return {
        'comfy_path': str(comfy),
        'python_path': str(python) if python else '',
        'kind': kind_of(comfy),
        'source': source,
    }


def running(url: str = 'http://127.0.0.1:8188', timeout: float = 2.0) -> dict | None:
    """The install behind a running ComfyUI (``/system_stats`` names its ``main.py``)."""
    try:
        with urllib.request.urlopen(url.rstrip('/') + '/system_stats', timeout=timeout) as reply:
            system = json.load(reply).get('system', {})
    except (OSError, ValueError):
        return None
    argv = system.get('argv') or []
    if not argv:
        return None
    main = Path(argv[0])
    comfy = main.parent if main.name == 'main.py' else None
    if not comfy or not is_comfy_dir(comfy):
        return None
    found = describe(comfy, 'running')
    found['version'] = system.get('comfyui_version', '')
    found['arguments'] = [a for a in argv[1:]]
    return found


def model_folders(url: str = 'http://127.0.0.1:8188', timeout: float = 2.0) -> dict | None:
    """Model folders of the running ComfyUI, including extra_model_paths.yaml entries."""
    try:
        with urllib.request.urlopen(
            url.rstrip('/') + '/internal/folder_paths', timeout=timeout
        ) as r:
            data = json.load(r)
    except (OSError, ValueError):
        return None
    return {key: [str(p) for p in value] for key, value in data.items() if isinstance(value, list)}


def suggest_lora_dir(folders: dict | None) -> str:
    """A LoRA folder to save trained LoRAs in: never ComfyUI's output folder, and one with
    an ``anima`` subfolder (kept for Anima LoRAs) when there is one."""
    usable = []
    for folder in (folders or {}).get('loras', []):
        path = Path(folder)
        if 'output' not in (part.lower() for part in path.parts[-2:]) and path.is_dir():
            usable.append(path)
    for path in usable:
        if (path / 'anima').is_dir():
            return str(path / 'anima')
    return str(usable[0]) if usable else ''


def _stability_matrix() -> list[Path]:
    found = []
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return found
    library = Path(appdata) / 'StabilityMatrix' / 'library.json'
    try:
        root = Path(json.loads(library.read_text(encoding='utf-8'))['LibraryPath'])
    except (OSError, ValueError, KeyError, TypeError):
        return found
    packages = root / 'Packages'
    if packages.is_dir():
        found += [p for p in packages.iterdir() if p.is_dir() and is_comfy_dir(p)]
    return found


def _desktop() -> list[Path]:
    appdata = os.environ.get('APPDATA')
    if not appdata:
        return []
    try:
        config = json.loads((Path(appdata) / 'ComfyUI' / 'config.json').read_text(encoding='utf-8'))
        base = Path(config['basePath'])
    except (OSError, ValueError, KeyError, TypeError):
        return []
    # The desktop app keeps ComfyUI inside its install; the base folder holds models and .venv.
    local = os.environ.get('LOCALAPPDATA', '')
    candidates = [
        base / 'ComfyUI',
        Path(local) / 'Programs' / '@comfyorgcomfyui-electron' / 'resources' / 'ComfyUI',
    ]
    return [p for p in candidates if is_comfy_dir(p)]


def _common_places() -> list[Path]:
    """Shallow look in drive roots and the user's usual folders (two levels deep)."""
    roots = [Path(f'{d}:\\') for d in string.ascii_uppercase if Path(f'{d}:\\').exists()]
    home = Path.home()
    roots += [home, home / 'Desktop', home / 'Documents', home / 'Downloads']
    found = []
    for root in roots:
        try:
            level1 = [p for p in root.iterdir() if p.is_dir() and 'comfy' in p.name.lower()]
        except OSError:
            continue
        for folder in level1:
            if is_comfy_dir(folder):
                found.append(folder)
                continue
            try:
                found += [p for p in folder.iterdir() if p.is_dir() and is_comfy_dir(p)]
            except OSError:
                pass
    return found


def candidates(url: str = 'http://127.0.0.1:8188') -> list[dict]:
    """Every install found, the running one first, without duplicates."""
    result = []
    seen = set()
    live = running(url)
    if live:
        result.append(live)
        seen.add(Path(live['comfy_path']).resolve())
    for source, finder in (
        ('stability_matrix', _stability_matrix),
        ('desktop', _desktop),
        ('search', _common_places),
    ):
        for comfy in finder():
            key = comfy.resolve()
            if key not in seen:
                seen.add(key)
                result.append(describe(comfy, source))
    return result
