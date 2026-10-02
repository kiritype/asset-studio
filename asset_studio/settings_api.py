"""Settings sections the Settings page edits. Each one is a JSON file in data/settings/.

Every section is validated here, merged into its file (keys this page does not know are
kept) and then the part of the server that uses it is told to reload. The connection
and review settings keep their own endpoints.
"""

import copy
import json
from pathlib import Path

from .i18n import Msg
from .lora.trainer import DEFAULT_SETTINGS as LORA_DEFAULTS
from .lora.trainer_setup import BASES, MODEL_KEYS
from .tags import TagLookup, data_dir
from .util import atomic_json, read_text, settings_file

LANGUAGES = ('auto', 'ko', 'en', 'ja', 'zh-CN')
THEMES = ('system', 'light', 'dark')
GPU_KINDS = ('generation', 'tool', 'vlm', 'training')
MAX_TEXT = 1000


def _text(value, name, allow_empty=True):
    if value is None:
        value = ''
    if not isinstance(value, str) or len(value) > MAX_TEXT or (not allow_empty and not value):
        raise ValueError(
            Msg('server.settings_api.check_the_text', '{name}: check the text.', name=name)
        )
    return value.strip()


def _integer(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(
            Msg(
                'server.settings_api.must_be_a_whole_number_from',
                '{name}: must be a whole number from {low} to {high}.',
                name=name,
                low=low,
                high=high,
            )
        )
    return value


def _argv(value, name):
    if value in (None, ''):
        return []
    if isinstance(value, str):
        value = [line.strip() for line in value.splitlines() if line.strip()]
    if not isinstance(value, list) or not all(isinstance(x, str) and x for x in value):
        raise ValueError(
            Msg(
                'server.settings_api.put_the_command_and_each_argument',
                '{name}: put the command and each argument on its own line.',
                name=name,
            )
        )
    return [_text(x, name) for x in value]


def _ui(values, current):
    result = {**current}
    if 'language' in values:
        if values['language'] not in LANGUAGES:
            raise ValueError(
                Msg('server.settings_api.unsupported_language', 'Unsupported language.')
            )
        result['language'] = values['language']
    if 'theme' in values:
        if values['theme'] not in THEMES:
            raise ValueError(
                Msg(
                    'server.settings_api.the_theme_must_be_system_light',
                    'The theme must be system, light or dark.',
                )
            )
        result['theme'] = values['theme']
    if 'autocomplete' in values:
        if not isinstance(values['autocomplete'], bool):
            raise ValueError(
                Msg(
                    'server.settings_api.autocomplete_must_be_true_or_false',
                    'Autocomplete must be true or false.',
                )
            )
        result['autocomplete'] = values['autocomplete']
    return result


def _lora(values, current):
    result = {**current}
    for key in ('trainer_dir', 'trainer_python', 'lora_dir'):
        if key in values:
            result[key] = _text(values[key], key)
    if 'bases' in values:
        bases = {}
        for ident in BASES:
            given = (values['bases'] or {}).get(ident) or {}
            paths = {key: _text(given.get(key), f'{ident}.{key}') for key in MODEL_KEYS}
            if any(paths.values()):
                bases[ident] = paths
        result['bases'] = bases
    return result


def _tags(values, current):
    result = {**current}
    if 'danbooru_dir' in values:
        folder = _text(values['danbooru_dir'], 'danbooru_dir')
        if folder:
            result['danbooru_dir'] = folder
        else:
            result.pop('danbooru_dir', None)
    if 'exclude' in values:
        exclude = values['exclude']
        if not isinstance(exclude, list) or len(exclude) > 500:
            raise ValueError(
                Msg(
                    'server.settings_api.send_excluded_tags_as_a_list',
                    'Send excluded tags as a list of up to 500.',
                )
            )
        if not all(isinstance(tag, str) and len(tag) <= 100 for tag in exclude):
            raise ValueError(
                Msg(
                    'server.settings_api.each_excluded_tag_must_be_text',
                    'Each excluded tag must be text of 100 characters or fewer.',
                )
            )
        result['exclude'] = list(dict.fromkeys(tag.strip() for tag in exclude if tag.strip()))
    return result


def _gpu(values, current):
    result = copy.deepcopy(current)
    if 'enabled' in values:
        if not isinstance(values['enabled'], bool):
            raise ValueError(
                Msg(
                    'server.settings_api.the_gpu_wait_switch_must_be',
                    'The GPU wait switch must be true or false.',
                )
            )
        result['enabled'] = values['enabled']
    if 'min_free_vram_mb' in values:
        limits = result.setdefault('min_free_vram_mb', {})
        for kind in GPU_KINDS:
            if kind in (values['min_free_vram_mb'] or {}):
                limits[kind] = _integer(values['min_free_vram_mb'][kind], kind, 0, 200000)
    if 'watch_processes' in values:
        result['watch_processes'] = _argv(values['watch_processes'], 'watch_processes')
    return result


def _vlm(values, current):
    result = {**current}
    if 'enabled' in values:
        if not isinstance(values['enabled'], bool):
            raise ValueError(
                Msg(
                    'server.settings_api.the_vlm_switch_must_be_true',
                    'The VLM switch must be true or false.',
                )
            )
        result['enabled'] = values['enabled']
    for key in ('url', 'model', 'api_key_env', 'loaded_marker'):
        if key in values:
            result[key] = _text(values[key], key)
    for key in ('load_command', 'unload_command', 'status_command'):
        if key in values:
            result[key] = _argv(values[key], key)
    for key, high in (('command_timeout_seconds', 3600), ('request_timeout_seconds', 3600)):
        if key in values:
            result[key] = _integer(values[key], key, 5, high)
    if 'max_output_tokens' in values:
        result['max_output_tokens'] = _integer(
            values['max_output_tokens'], 'max_output_tokens', 64, 65536
        )
    return result


SECTIONS = {
    'ui': ('ui.json', {'language': 'auto', 'theme': 'system', 'autocomplete': True}, _ui),
    'lora': (
        'lora_pipeline.json',
        {
            'trainer_dir': LORA_DEFAULTS['trainer_dir'],
            'trainer_python': LORA_DEFAULTS['trainer_python'],
            'lora_dir': '',
            'bases': {},
        },
        _lora,
    ),
    'tags': ('tags.json', {}, _tags),
    'gpu': (
        'gpu.json',
        {
            'enabled': False,
            'min_free_vram_mb': {'generation': 2048, 'tool': 1024, 'vlm': 16384, 'training': 16384},
            'watch_processes': [],
        },
        _gpu,
    ),
    'vlm': (
        'vlm.json',
        {
            'enabled': False,
            'url': '',
            'model': '',
            'api_key_env': '',
            'load_command': [],
            'unload_command': [],
            'status_command': [],
            'loaded_marker': '',
            'command_timeout_seconds': 120,
            'request_timeout_seconds': 180,
        },
        _vlm,
    ),
}


def _read(root, section):
    name, defaults, _ = SECTIONS[section]
    path = settings_file(root, name)
    saved = json.loads(read_text(path)) if path.is_file() else {}
    if not isinstance(saved, dict):
        saved = {}
    merged = copy.deepcopy(defaults)
    merged.update(saved)
    if section == 'gpu':
        # gpu.json exists only once the checks are wanted; an absent file means "off".
        merged['enabled'] = bool(saved.get('enabled', True)) if path.is_file() else False
        merged['min_free_vram_mb'] = {
            **defaults['min_free_vram_mb'],
            **(saved.get('min_free_vram_mb') or {}),
        }
    return merged, saved


def _status(studio, section, values):
    """What the page shows next to the fields: found / missing files and runtime errors."""
    exists = lambda value: bool(value) and Path(value).exists()  # noqa: E731
    if section == 'lora':
        root = Path(studio.root)
        trainer = Path(values['trainer_dir'])
        trainer = trainer if trainer.is_absolute() else root / trainer
        return {
            'trainer_found': (trainer / 'train.py').is_file(),
            'python_found': (trainer / values['trainer_python']).is_file(),
            'lora_dir_found': exists(values['lora_dir']),
            'paths_found': {
                ident: {key: exists(path) for key, path in paths.items()}
                for ident, paths in (values.get('bases') or {}).items()
            },
        }
    if section == 'tags':
        folder = data_dir(studio.root)
        return {
            'folder': str(folder) if folder else '',
            'available': bool(folder) and (Path(folder) / 'danbooru_2025-09-01.csv').is_file(),
        }
    if section == 'vlm':
        vlm = studio.validation.vlm
        return {'configured': bool(vlm.enabled), 'error': vlm.error}
    return {}


def get_all(studio):
    result = {}
    for section in SECTIONS:
        values, _ = _read(studio.root, section)
        result[section] = {'values': values, 'status': _status(studio, section, values)}
    return result


def save(studio, body):
    section = body.get('section')
    if section not in SECTIONS:
        raise ValueError(
            Msg('server.settings_api.unknown_settings_section', 'Unknown settings section.')
        )
    values = body.get('values')
    if not isinstance(values, dict):
        raise ValueError(
            Msg('server.settings_api.values_must_be_an_object', 'values must be an object.')
        )
    name, _, validate = SECTIONS[section]
    current, saved = _read(studio.root, section)
    updated = validate(values, current)
    # Keys the page does not edit stay as they were in the file.
    atomic_json(settings_file(studio.root, name), {**saved, **updated})
    if section == 'tags':
        studio.tags = TagLookup(studio.root)
    if section == 'vlm':
        studio.validation.vlm.reload()
    values, _ = _read(studio.root, section)
    return {'ok': True, 'values': values, 'status': _status(studio, section, values)}
