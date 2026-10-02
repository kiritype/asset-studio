"""Pick training images from the gallery and turn them into a dataset."""

from ..i18n import Msg
from ..util import code
from . import records
from .captions import caption, default_triggers

MIN_IMAGES = 1


def candidates(studio, work_id, character_id, outfit_set_id):
    """Every image of one work/character/outfit set, marking the adopted (human-passed) ones."""
    params = {
        key: [value]
        for key, value in (
            ('work', work_id),
            ('character', character_id),
            ('outfit', outfit_set_id),
            ('sort', 'code'),
            ('page_size', '192'),
        )
    }
    items, page = [], 1
    while True:
        result = studio.gallery.list({**params, 'page': [str(page)]})
        items += result['results']
        if page >= result['pages']:
            break
        page += 1
    return [
        {
            'path': item['relative_path'],
            'sha256': item.get('sha256', ''),
            'expression_id': item.get('expression_id'),
            'rating': item.get('category'),
            'human_status': item.get('human_status', 'unreviewed'),
            'selected': bool(item.get('selected')),
            'thumbnail_url': item.get('thumbnail_url'),
        }
        for item in items
    ]


def _metadata(studio, path):
    meta = studio.gallery.metadata(path)
    if not isinstance(meta, dict) or meta.get('error'):
        raise ValueError(
            Msg(
                'server.datasets.images_without_a_record_cannot_be',
                'Images without a record cannot be used for training: {path}',
                path=path,
            )
        )
    return meta


def build(studio, body):
    """Create or replace a dataset. Without ``paths`` it takes the adopted images."""
    work_id, character_id = code(body.get('work_id')), code(body.get('character_id'))
    outfit_set_id = code(body.get('outfit_set_id'))
    existing = records.list_datasets(studio.store, work_id, character_id)
    ident = body.get('id') or records.next_id(existing, 'D')
    previous = next((item for item in existing if item['id'] == ident), None)
    triggers = (
        body.get('triggers')
        or (previous or {}).get('triggers')
        or default_triggers(work_id, character_id, outfit_set_id)
    )
    pool = candidates(studio, work_id, character_id, outfit_set_id)
    by_path = {item['path']: item for item in pool}
    paths = body.get('paths')
    if paths is None:
        paths = [item['path'] for item in pool if item['selected']]
    if not isinstance(paths, list) or len(paths) < MIN_IMAGES:
        raise ValueError(
            Msg(
                'server.datasets.choose_images_for_the_dataset_without',
                'Choose images for the dataset. Without adopted images, pick them yourself.',
            )
        )
    old_items = {item['path']: item for item in (previous or {}).get('items', [])}
    items = []
    for path in paths:
        found = by_path.get(path)
        if not found:
            raise ValueError(
                Msg(
                    'server.datasets.not_an_image_of_this_outfit',
                    'Not an image of this outfit set: {path}',
                    path=path,
                )
            )
        meta = _metadata(studio, path)
        kept = old_items.get(path)
        # A caption someone edited by hand survives a rebuild.
        text = kept['caption'] if kept and kept.get('caption_edited') else caption(meta, triggers)
        items.append(
            {
                'path': path,
                'sha256': found['sha256'] or studio.review_store.sha256(path),
                'expression_id': meta.get('expression_id'),
                'rating': meta.get('category'),
                'caption': text,
                'caption_edited': bool(kept and kept.get('caption_edited')),
            }
        )
    payload = {
        'id': ident,
        'name': body.get('name')
        or (previous or {}).get('name')
        or Msg('server.datasets.dataset', '{outfit_set_id} dataset', outfit_set_id=outfit_set_id),
        'outfit_set_id': outfit_set_id,
        'triggers': triggers,
        'items': items,
    }
    expected = studio.library.revision(
        records.dataset_file(studio.store, work_id, character_id, ident), 'dataset'
    )
    return studio.library.save(
        {
            'kind': 'dataset',
            'work_id': work_id,
            'character_id': character_id,
            'payload': payload,
            'expected_revision': body.get('expected_revision', expected),
        }
    )


def recaption(studio, body):
    """Rebuild automatic captions (e.g. after changing triggers); hand edits stay."""
    work_id, character_id = code(body.get('work_id')), code(body.get('character_id'))
    path = records.dataset_file(studio.store, work_id, character_id, body.get('id'))
    dataset = studio.store.read(path)
    triggers = body.get('triggers') or dataset.get('triggers', {})
    for item in dataset['items']:
        if not item.get('caption_edited'):
            item['caption'] = caption(_metadata(studio, item['path']), triggers)
    dataset['triggers'] = triggers
    return studio.library.save(
        {
            'kind': 'dataset',
            'work_id': work_id,
            'character_id': character_id,
            'payload': dataset,
            'expected_revision': body.get('expected_revision'),
        }
    )
