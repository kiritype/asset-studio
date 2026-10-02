"""Where LoRA datasets, training runs and the LoRA registry are stored.

works/<W>/characters/<C>/datasets/<D>.json     images chosen for training + captions
works/<W>/characters/<C>/lora_runs/<R>.json    one training run
loras/<L>.json                                 trained or downloaded LoRA files
"""

import math
import re

from ..i18n import Msg
from ..library.layout import Location, valid_id

LORA_SCOPES = ('character', 'global')
RUN_STATES = (
    'waiting_gpu',
    'preprocessing',
    'training',
    'done',
    'failed',
    'cancelled',
    'interrupted',
)
ACTIVE_RUN_STATES = ('waiting_gpu', 'preprocessing', 'training')


def character_dir(store, work_id, character_id):
    return Location('character', work_id, character_id).directory(store.root)


def dataset_file(store, work_id, character_id, ident):
    return character_dir(store, work_id, character_id) / 'datasets' / (valid_id(ident) + '.json')


def run_file(store, work_id, character_id, ident):
    return character_dir(store, work_id, character_id) / 'lora_runs' / (valid_id(ident) + '.json')


def lora_file(store, ident):
    return store.root / 'loras' / (valid_id(ident) + '.json')


def list_records(store, folder):
    return [store.read(path) for path in sorted(folder.glob('*.json'))] if folder.is_dir() else []


def list_datasets(store, work_id, character_id):
    return list_records(store, character_dir(store, work_id, character_id) / 'datasets')


def list_runs(store, work_id, character_id):
    return list_records(store, character_dir(store, work_id, character_id) / 'lora_runs')


def list_loras(store):
    return list_records(store, store.root / 'loras')


def next_id(existing, prefix):
    """The first free code like D001 / R001 among ``existing`` records."""
    used = {item.get('id') for item in existing}
    number = 1
    while f'{prefix}{number:03d}' in used:
        number += 1
    return f'{prefix}{number:03d}'


def _strings(value, label):
    if not isinstance(value, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in value.items()
    ):
        raise ValueError(
            Msg(
                'server.records.must_map_names_to_text',
                '{value} must map names to text.',
                value=label,
            )
        )


def save_dataset(store, work_id, character_id, payload):
    """Validate and write a dataset. Images are referenced by path + SHA-256, never copied."""
    store.require_owner(Location('character', work_id, character_id))
    path = dataset_file(store, work_id, character_id, payload.get('id'))
    data = store._merge(path, payload, drop=('work_id', 'character_id'))
    valid_id(data.get('outfit_set_id'), 'outfit_set_id')
    _strings(data.setdefault('triggers', {}), 'triggers')
    items = data.setdefault('items', [])
    if not isinstance(items, list):
        raise ValueError(Msg('server.records.items_must_be_a_list', 'items must be a list.'))
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError(
                Msg('server.records.dataset_items_need_a_path', 'Dataset items need a path.')
            )
        if item['path'] in seen:
            raise ValueError(
                Msg(
                    'server.records.the_same_image_is_in_twice',
                    'The same image is in twice: {path}',
                    path=item['path'],
                )
            )
        seen.add(item['path'])
        if not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256', ''))):
            raise ValueError(
                Msg(
                    'server.records.sha256_is_required',
                    '{path}: sha256 is required.',
                    path=item['path'],
                )
            )
        if not isinstance(item.get('caption', ''), str):
            raise ValueError(
                Msg(
                    'server.records.caption_must_be_text',
                    '{path}: caption must be text.',
                    path=item['path'],
                )
            )
    data = {'work_id': work_id, 'character_id': character_id, **data}
    store.write(path, data)
    return data


def save_lora(store, payload):
    """Validate and write a registry entry. ``origin`` is fixed once set."""
    path = lora_file(store, payload.get('id'))
    previous = store.read(path) if path.exists() else {}
    data = store._merge(path, payload)
    if previous.get('origin') and data.get('origin') != previous['origin']:
        raise ValueError(
            Msg(
                'server.records.origin_where_it_was_trained_cannot',
                'origin (where it was trained) cannot be changed.',
            )
        )
    if not isinstance(data.get('file'), str) or not data['file'].endswith('.safetensors'):
        raise ValueError(
            Msg(
                'server.records.file_must_be_a_safetensors_file',
                'file must be a .safetensors file name.',
            )
        )
    if data.setdefault('scope', 'global') not in LORA_SCOPES:
        raise ValueError(
            Msg(
                'server.records.scope_must_be_character_or_global',
                'scope must be character or global.',
            )
        )
    origin = data.get('origin')
    if data['scope'] == 'character' and not (
        isinstance(origin, dict) and origin.get('work_id') and origin.get('character_id')
    ):
        raise ValueError(
            Msg(
                'server.records.a_character_lora_needs_the_work',
                'A character LoRA needs the work and character it was trained for (origin).',
            )
        )
    strength = data.setdefault('strength', 1.0)
    if (
        isinstance(strength, bool)
        or not isinstance(strength, (int, float))
        or not math.isfinite(strength)
    ):
        raise ValueError(
            Msg('server.records.strength_must_be_a_number', 'strength must be a number.')
        )
    if not isinstance(data.setdefault('auto_apply', False), bool):
        raise ValueError(
            Msg('server.records.auto_apply_must_be_true_or', 'auto_apply must be true or false.')
        )
    _strings(data.setdefault('triggers', {}), 'triggers')
    from .apply import APPLY_TO, key_of

    if data.setdefault('apply_to', 'character') not in APPLY_TO:
        raise ValueError(
            Msg(
                'server.records.apply_to_must_be_character_or',
                'apply_to must be character or outfit.',
            )
        )
    if data.setdefault('model_family', 'anima') not in ('anima', 'sdxl', 'shared'):
        raise ValueError(
            Msg(
                'server.records.model_family_must_be_anima_sdxl',
                'model_family must be anima, sdxl or shared.',
            )
        )
    store.write(path, data)
    # Only one automatic LoRA per character (or per outfit set): turn the others off.
    if data['auto_apply'] and key_of(data) is not None:
        for other in list_loras(store):
            if (
                other['id'] != data['id']
                and other.get('auto_apply')
                and key_of(other) == key_of(data)
            ):
                store.write(lora_file(store, other['id']), {**other, 'auto_apply': False})
    return data
