"""Model families (Anima / SDXL) of the files ComfyUI offers.

A file's family is decided in this order:

1. its folder: ``anima/...`` or ``sdxl/...`` below the model folder,
2. a manual choice saved in ``data/settings/models.json``,
3. the ``BaseModel`` of a Stability Matrix ``.cm-info.json`` next to it,
4. the safetensors header (tensor names and training metadata).

Files that match none stay ``unknown`` and can be set by hand.
"""

import json
import re
import struct
import threading
from pathlib import Path, PureWindowsPath

from .util import atomic_json, settings_file

FAMILIES = ('anima', 'sdxl')
FAMILY_LABELS = {'anima': 'Anima', 'sdxl': 'SDXL·IL', 'unknown': '미분류'}
# ComfyUI catalog key -> folder under the shared model folder (Stability Matrix layout).
KIND_FOLDERS = {
    'checkpoints': ('StableDiffusion', 'checkpoints'),
    'diffusion_models': ('DiffusionModels', 'diffusion_models', 'unet'),
    'loras': ('Lora', 'loras'),
    'text_encoders': ('TextEncoders', 'text_encoders', 'clip'),
    'vaes': ('VAE', 'vae'),
}
BASE_MODEL_FAMILIES = {
    'anima': 'anima',
    'sdxl': 'sdxl',
    'illustrious': 'sdxl',
    'pony': 'sdxl',
    'noobai': 'sdxl',
}
HEADER_LIMIT = 64 * 1024 * 1024


def family_from_folder(name):
    """``anima/x.safetensors`` -> anima. ComfyUI reports sub-folders with \\ on Windows."""
    first = PureWindowsPath(name).parts[0].lower() if name else ''
    return first if first in FAMILIES and len(PureWindowsPath(name).parts) > 1 else None


def family_from_base_model(base):
    text = str(base or '').lower()
    for marker, family in BASE_MODEL_FAMILIES.items():
        if marker in text:
            return family
    return None


def read_header(path):
    with open(path, 'rb') as stream:
        size = struct.unpack('<Q', stream.read(8))[0]
        if size > HEADER_LIMIT:
            raise ValueError('safetensors header too large')
        return json.loads(stream.read(size))


def family_from_header(header):
    meta = header.get('__metadata__') or {}
    hints = ' '.join(
        str(meta.get(key, ''))
        for key in ('ss_base_model_version', 'modelspec.architecture', 'ss_network_module')
    )
    by_meta = family_from_base_model(hints)
    if by_meta:
        return by_meta
    keys = [key for key in header if key != '__metadata__']
    if any(
        'conditioner.embedders' in key
        or key.startswith(('lora_te1_', 'lora_te2_'))
        or 'input_blocks' in key
        for key in keys[:4000]
    ):
        return 'sdxl'
    if any('adaln_modulation' in key for key in keys[:4000]):
        return 'anima'
    return None


class ModelProfiles:
    """Family of every model file; results are cached per file size and change time."""

    def __init__(self, root):
        self.root = Path(root)
        self.path = settings_file(root, 'models.json')
        self._cache = {}
        self._lock = threading.Lock()

    def settings(self):
        if self.path.is_file():
            return json.loads(self.path.read_text(encoding='utf-8'))
        return {}

    def models_dir(self):
        """The shared model folder (Stability Matrix ``Models``) or ComfyUI's ``models``."""
        configured = self.settings().get('models_dir')
        if configured:
            return Path(configured)
        connection = settings_file(self.root, 'connection.json')
        if connection.is_file():
            comfy = json.loads(connection.read_text(encoding='utf-8')).get('comfy_path')
            if comfy:
                shared = Path(comfy).parent.parent / 'Models'
                return shared if shared.is_dir() else Path(comfy) / 'models'
        return None

    def locate(self, kind, name):
        base = self.models_dir()
        if base is None:
            return None
        for folder in KIND_FOLDERS.get(kind, ()):
            candidate = base / folder / PureWindowsPath(name)
            if candidate.is_file():
                return candidate
        return None

    def detect(self, kind, name):
        """(family or None, how it was decided)."""
        by_folder = family_from_folder(name)
        if by_folder:
            return by_folder, 'folder'
        manual = self.settings().get('families', {}).get(f'{kind}/{name}')
        if manual in FAMILIES:
            return manual, 'manual'
        path = self.locate(kind, name)
        if path is None:
            return None, 'missing'
        stat = path.stat()
        key = (str(path), stat.st_size, stat.st_mtime_ns)
        with self._lock:
            if key in self._cache:
                return self._cache[key]
        result = None, 'unknown'
        info = path.with_name(path.stem + '.cm-info.json')
        if info.is_file():
            family = family_from_base_model(
                json.loads(info.read_text(encoding='utf-8')).get('BaseModel')
            )
            if family:
                result = family, 'cm-info'
        if result[0] is None and path.suffix == '.safetensors':
            try:
                family = family_from_header(read_header(path))
            except (OSError, ValueError, struct.error):
                family = None
            if family:
                result = family, 'header'
        with self._lock:
            self._cache[key] = result
        return result

    def classify(self, catalog):
        """Family per catalog entry: {'models': {id: family}, 'loras': {...}, ...}."""
        result = {}
        for entry_id, entry in (catalog.get('model_entries') or {}).items():
            kind = (
                'checkpoints' if entry['loader'] == 'CheckpointLoaderSimple' else 'diffusion_models'
            )
            result.setdefault('models', {})[entry_id] = self.detect(kind, entry['filename'])[0]
        for key, kind in (('loras', 'loras'), ('text_encoders', 'text_encoders'), ('vaes', 'vaes')):
            result[key] = {name: self.detect(kind, name)[0] for name in catalog.get(key, [])}
        return result

    def set_family(self, kind, name, family):
        """Remember a family chosen by hand (``None`` forgets it)."""
        if kind not in KIND_FOLDERS or not isinstance(name, str) or not name:
            raise ValueError('모델 종류와 이름이 필요합니다.')
        if family not in (*FAMILIES, None):
            raise ValueError('계열은 anima 또는 sdxl이어야 합니다.')
        settings = self.settings()
        families = settings.setdefault('families', {})
        if family:
            families[f'{kind}/{name}'] = family
        else:
            families.pop(f'{kind}/{name}', None)
        atomic_json(self.path, settings)
        return {'ok': True, 'family': family}


def sidecars(path):
    """Files Stability Matrix keeps next to a model: ``<stem>.cm-info.json``, previews, ..."""
    pattern = re.compile(re.escape(path.stem) + r'\.(cm-info\.json|preview\.\w+|json|txt|yaml)$')
    return [item for item in path.parent.iterdir() if item != path and pattern.match(item.name)]
