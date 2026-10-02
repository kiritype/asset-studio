"""Sample libraries in samples/*.json that can be imported as a new work.

A sample is a whole work: its own pieces (compositions, expressions, common tags) and its
characters with their outfits. Everything is written inside the new work, so importing a
sample never touches global pieces. The work gets the first free code from W900.
"""

import json
from pathlib import Path

from .i18n import Msg
from .library.layout import Location

SAMPLES = Path(__file__).resolve().parents[1] / 'samples'
FIRST_CODE = 900


def list_samples():
    result = []
    for path in sorted(SAMPLES.glob('*.json')):
        data = json.loads(path.read_text(encoding='utf-8'))
        result.append(
            {'id': data['id'], 'name': data['name'], 'description': data.get('description', '')}
        )
    return {'samples': result}


def _load(sample_id):
    for path in SAMPLES.glob('*.json'):
        data = json.loads(path.read_text(encoding='utf-8'))
        if data.get('id') == sample_id:
            return data
    raise ValueError(Msg('server.samples.sample_not_found', 'Sample not found.'))


def import_sample(studio, sample_id):
    data = _load(sample_id)
    store = studio.store
    with studio.lock:
        used = {work['id'] for work in store.list_works()}
        work_id = next(
            (f'W{n:03d}' for n in range(FIRST_CODE, 1000) if f'W{n:03d}' not in used), None
        )
        if work_id is None:
            raise ValueError(
                Msg(
                    'server.samples.no_free_work_code_w900_w999',
                    'No free work code (W900–W999) is left for samples.',
                )
            )
        store.save_work({'id': work_id, **data['work'], 'sample': data['id']})
        work = Location('work', work_id)
        for entry in data.get('work_pieces', []):
            store.save_piece(work, entry['bucket'], entry['piece'])
        for character in data.get('characters', []):
            fields = {
                k: v for k, v in character.items() if k not in ('outfit_pieces', 'outfit_sets')
            }
            # The default outfit must exist before it is named; set it after the sets.
            default = fields.pop('default_outfit', None)
            store.save_character(work_id, fields)
            owner = Location('character', work_id, character['id'])
            for entry in character.get('outfit_pieces', []):
                store.save_piece(owner, entry['bucket'], entry['piece'])
            for outfit_set in character.get('outfit_sets', []):
                store.save_outfit_set(owner, outfit_set)
            if default:
                store.save_character(work_id, {'id': character['id'], 'default_outfit': default})
    return {'ok': True, 'work_id': work_id, 'name': data['work']['name']}
