"""Where LoRA datasets, training runs and the LoRA registry are stored.

works/<W>/characters/<C>/datasets/<D>.json     images chosen for training + captions
works/<W>/characters/<C>/lora_runs/<R>.json    one training run
loras/<L>.json                                 trained or downloaded LoRA files
"""

import math
import re

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
        raise ValueError(f'{label}는 이름 → 문자열 객체여야 합니다.')


def save_dataset(store, work_id, character_id, payload):
    """Validate and write a dataset. Images are referenced by path + SHA-256, never copied."""
    store.require_owner(Location('character', work_id, character_id))
    path = dataset_file(store, work_id, character_id, payload.get('id'))
    data = store._merge(path, payload, drop=('work_id', 'character_id'))
    valid_id(data.get('outfit_set_id'), 'outfit_set_id')
    _strings(data.setdefault('triggers', {}), 'triggers')
    items = data.setdefault('items', [])
    if not isinstance(items, list):
        raise ValueError('items는 목록이어야 합니다.')
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get('path'), str):
            raise ValueError('데이터셋 항목에는 path가 필요합니다.')
        if item['path'] in seen:
            raise ValueError(f'같은 이미지가 두 번 들어 있습니다: {item["path"]}')
        seen.add(item['path'])
        if not re.fullmatch(r'[0-9a-f]{64}', str(item.get('sha256', ''))):
            raise ValueError(f'{item["path"]}: sha256이 필요합니다.')
        if not isinstance(item.get('caption', ''), str):
            raise ValueError(f'{item["path"]}: caption은 문자열이어야 합니다.')
    data = {'work_id': work_id, 'character_id': character_id, **data}
    store.write(path, data)
    return data


def save_lora(store, payload):
    """Validate and write a registry entry. ``origin`` is fixed once set."""
    path = lora_file(store, payload.get('id'))
    previous = store.read(path) if path.exists() else {}
    data = store._merge(path, payload)
    if previous.get('origin') and data.get('origin') != previous['origin']:
        raise ValueError('origin(어디서 학습됐는지)은 바꿀 수 없습니다.')
    if not isinstance(data.get('file'), str) or not data['file'].endswith('.safetensors'):
        raise ValueError('file은 .safetensors 파일 이름이어야 합니다.')
    if data.setdefault('scope', 'global') not in LORA_SCOPES:
        raise ValueError('scope는 character 또는 global이어야 합니다.')
    origin = data.get('origin')
    if data['scope'] == 'character' and not (
        isinstance(origin, dict) and origin.get('work_id') and origin.get('character_id')
    ):
        raise ValueError('캐릭터 전용 LoRA는 학습한 작품·캐릭터(origin)가 있어야 합니다.')
    strength = data.setdefault('strength', 1.0)
    if (
        isinstance(strength, bool)
        or not isinstance(strength, (int, float))
        or not math.isfinite(strength)
    ):
        raise ValueError('strength는 숫자여야 합니다.')
    if not isinstance(data.setdefault('auto_apply', False), bool):
        raise ValueError('auto_apply는 true 또는 false여야 합니다.')
    _strings(data.setdefault('triggers', {}), 'triggers')
    from .apply import APPLY_TO, key_of

    if data.setdefault('apply_to', 'character') not in APPLY_TO:
        raise ValueError('apply_to는 character 또는 outfit이어야 합니다.')
    if data.setdefault('model_family', 'anima') not in ('anima', 'sdxl', 'shared'):
        raise ValueError('model_family는 anima, sdxl, shared 중 하나여야 합니다.')
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
