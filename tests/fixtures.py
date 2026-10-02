"""A small v2 library used by several test modules."""

from asset_studio.library.layout import Location

GLOBAL = Location('global')


def character(work_id, character_id):
    return Location('character', work_id, character_id)


def seed_library(store):
    """W001 with C001 (outfit set 001: hands/top/bottom) and C002 (no outfit)."""
    store.save_work(
        {
            'id': 'W001',
            'name': 'Work',
            'prompt': ['work positive'],
            'negative_prompt': ['work negative'],
        }
    )
    store.save_character(
        'W001',
        {
            'id': 'C001',
            'name': 'Hero',
            'prompt': ['character positive'],
            'negative_prompt': ['character negative'],
            'default_outfit': '001',
        },
    )
    store.save_character('W001', {'id': 'C002', 'name': 'Other', 'prompt': ['other positive']})
    hero = character('W001', 'C001')
    for slot, prompt in (('hands', 'gloves'), ('top', 'jacket'), ('bottom', 'skirt, boots')):
        store.save_piece(hero, f'outfit/{slot}', {'id': '001', 'name': slot, 'prompt': [prompt]})
    store.save_outfit_set(
        hero,
        {
            'id': '001',
            'name': 'Coat',
            'negative_prompt': ['outfit negative'],
            'slots': {
                slot: {'scope': 'character', 'id': '001'} for slot in ('hands', 'top', 'bottom')
            },
        },
    )
    store.save_piece(
        GLOBAL,
        'composition',
        {
            'id': 'P001',
            'name': 'Upper body',
            'prompt': ['composition positive'],
            'suggest_slots': ['hands', 'top'],
        },
    )
    store.save_piece(
        GLOBAL,
        'expression/sfw',
        {
            'id': '001',
            'name': 'Smile',
            'prompt': ['expression positive'],
            'negative_prompt': ['expression negative'],
            'composition_id': 'P001',
        },
    )
    store.save_piece(
        GLOBAL, 'expression/sfw', {'id': '002', 'name': 'Serious', 'prompt': ['serious']}
    )
    store.save_piece(
        GLOBAL, 'common/positive', {'id': 'Q001', 'name': 'Quality', 'prompt': ['quality positive']}
    )
    store.save_piece(
        GLOBAL, 'common/negative', {'id': 'Q001', 'name': 'Quality', 'prompt': ['quality negative']}
    )
    store.save_piece(
        GLOBAL,
        'artist',
        {
            'id': 'A001',
            'name': 'Artist',
            'prompt': ['artist positive'],
            'negative_prompt': ['artist negative'],
        },
    )


def request(**changes):
    """A generation request for C001 that selects every seeded piece."""
    body = {
        'work_id': 'W001',
        'character_id': 'C001',
        'outfit_id': '001',
        'expressions': [{'id': '001'}],
        'artist_ids': ['A001'],
        'common_positive_ids': ['Q001'],
        'common_negative_ids': ['Q001'],
    }
    body.update(changes)
    return body
