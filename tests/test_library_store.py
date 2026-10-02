import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import GLOBAL, character, seed_library

from asset_studio.library.layout import Categories, Location
from asset_studio.library.resolve import (
    character_of,
    find_outfit_set,
    find_piece,
    slot_piece,
    visible_outfit_sets,
    visible_pieces,
)
from asset_studio.library.store import LibraryStore, OutdatedLayoutError, check_layout


class LibraryStoreTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = LibraryStore(self.root)

    def test_pieces_take_category_and_scope_from_their_location(self):
        seed_library(self.store)
        path = self.root / 'data/works/W001/characters/C001/pieces/outfit/top/001.json'
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['schema_version'], 2)
        for derived in ('category', 'role', 'bucket', 'scope', 'slot', 'work_id', 'character_id'):
            self.assertNotIn(derived, saved)
        piece = self.store.list_pieces(character('W001', 'C001'))[-1]
        self.assertEqual(
            (piece['category'], piece['role'], piece['slot'], piece['bucket']),
            ('outfit/top', 'outfit', 'top', 'outfit/top'),
        )
        self.assertEqual(
            (piece['scope'], piece['work_id'], piece['character_id']), ('character', 'W001', 'C001')
        )
        expression = self.store.resolve_piece(GLOBAL, 'expression', '001')
        self.assertEqual((expression['rating'], expression['bucket']), ('sfw', 'expression'))

    def test_folders_below_the_role_level_are_free_but_ids_stay_unique(self):
        seed_library(self.store)
        deep = self.store.save_piece(
            GLOBAL, 'expression/sfw/daily/morning', {'id': '010', 'name': 'Yawn'}
        )
        self.assertEqual(
            (deep['category'], deep['rating'], deep['bucket']),
            ('expression/sfw/daily/morning', 'sfw', 'expression'),
        )
        self.assertEqual(self.store.resolve_piece(GLOBAL, 'expression', '010')['name'], 'Yawn')
        # The image file name is the expression id, so it cannot repeat in another folder or rating.
        with self.assertRaises(ValueError):
            self.store.save_piece(GLOBAL, 'expression/nsfw', {'id': '010', 'name': 'Duplicate'})
        with self.assertRaises(ValueError):
            self.store.save_piece(GLOBAL, 'expression/sfw', {'id': '010', 'name': 'Duplicate'})
        # Outfit ids are unique per slot, not across slots.
        self.store.save_piece(GLOBAL, 'outfit/top/winter', {'id': 'coat', 'name': 'Coat'})
        self.store.save_piece(GLOBAL, 'outfit/bottom', {'id': 'coat', 'name': 'Coat skirt'})
        with self.assertRaises(ValueError):
            self.store.save_piece(GLOBAL, 'outfit/top', {'id': 'coat', 'name': 'Duplicate'})

    def test_category_rules(self):
        seed_library(self.store)
        for category in ('unknown', 'outfit', 'expression/teen', 'common/other', 'artist/../x', ''):
            with self.subTest(category=category), self.assertRaises(ValueError):
                self.store.save_piece(GLOBAL, category, {'id': 'X1', 'name': 'Bad'})
        self.store.save_piece(GLOBAL, 'outfit/accessory', {'id': 'X1', 'name': 'New slot'})
        # Image files are named after the expression id, so its shape is fixed.
        for ident in ('smile', '01', '000', '001_2'):
            with self.subTest(expression_id=ident), self.assertRaises(ValueError):
                self.store.save_piece(GLOBAL, 'expression/sfw', {'id': ident, 'name': 'Bad id'})
        self.assertEqual(
            Categories().ordered('outfit', ['accessory', 'shoes', 'top', 'full']),
            ['full', 'top', 'shoes', 'accessory'],
        )

    def test_owner_must_exist_and_unknown_fields_survive(self):
        with self.assertRaises(ValueError):
            self.store.save_character('W001', {'id': 'C001', 'name': 'Before work'})
        seed_library(self.store)
        with self.assertRaises(ValueError):
            self.store.save_piece(character('W001', 'C404'), 'outfit/top', {'id': '001'})
        with self.assertRaises(ValueError):
            self.store.save_character('W001', {'id': '../bad', 'name': 'Bad'})
        with self.assertRaises(ValueError):
            self.store.save_character('W001', {'id': 'C001', 'negative_prompt': [1]})
        with self.assertRaises(ValueError):
            self.store.save_character('W001', {'id': 'C001', 'model_family': 'sd15'})
        path = self.store.character_file('W001', 'C001')
        current = json.loads(path.read_text(encoding='utf-8'))
        current['future_field'] = {'kept': True}
        path.write_text(json.dumps(current), encoding='utf-8')
        self.store.save_character(
            'W001', {'id': 'C001', 'name': 'Renamed', 'pieces': ['transient']}
        )
        saved = json.loads(path.read_text(encoding='utf-8'))
        self.assertEqual(saved['future_field'], {'kept': True})
        self.assertEqual(saved['prompt'], ['character positive'])
        self.assertNotIn('pieces', saved)
        backups = [p.name for p in (self.root / 'data/backups').glob('*.json')]
        self.assertTrue(any('C001_character' in name for name in backups))

    def test_outfit_set_slots_must_point_at_visible_pieces(self):
        seed_library(self.store)
        hero = character('W001', 'C001')
        with self.assertRaises(ValueError):
            self.store.save_outfit_set(
                hero, {'id': '002', 'slots': {'top': {'scope': 'character', 'id': '404'}}}
            )
        with self.assertRaises(ValueError):
            self.store.save_outfit_set(
                GLOBAL, {'id': '099', 'slots': {'top': {'scope': 'character', 'id': '001'}}}
            )
        self.store.save_piece(
            GLOBAL, 'outfit/full', {'id': 'nude', 'name': 'Nude', 'prompt': ['completely nude']}
        )
        self.store.save_outfit_set(
            GLOBAL,
            {'id': '099', 'name': 'Nude', 'slots': {'full': {'scope': 'global', 'id': 'nude'}}},
        )
        mixed = self.store.save_outfit_set(
            hero,
            {
                'id': '002',
                'name': 'Mixed',
                'slots': {
                    'top': {'scope': 'character', 'id': '001'},
                    'full': {'scope': 'global', 'id': 'nude'},
                },
            },
        )
        self.assertEqual(mixed['scope'], 'character')

    def test_catalog_and_scope_precedence(self):
        seed_library(self.store)
        hero = character('W001', 'C001')
        self.store.save_piece(GLOBAL, 'outfit/full', {'id': 'nude', 'prompt': ['completely nude']})
        self.store.save_outfit_set(
            GLOBAL,
            {'id': '099', 'name': 'Nude', 'slots': {'full': {'scope': 'global', 'id': 'nude'}}},
        )
        self.store.save_piece(
            Location('work', 'W001'),
            'expression/sfw',
            {'id': '001', 'name': 'Work smile', 'composition_id': 'P001'},
        )
        self.store.save_piece(hero, 'expression/sfw', {'id': '001', 'name': 'Hero smile'})
        catalog = self.store.catalog('W001')
        self.assertEqual([w['id'] for w in self.store.list_works()], ['W001'])
        self.assertEqual(catalog['work']['name'], 'Work')
        first, second = (character_of(catalog, ident) for ident in ('C001', 'C002'))
        self.assertEqual(find_piece(catalog, first, 'expression', '001')['name'], 'Hero smile')
        self.assertEqual(find_piece(catalog, second, 'expression', '001')['name'], 'Work smile')
        self.assertEqual(
            find_piece(catalog, None, 'expression', '001', scope='global')['name'], 'Smile'
        )
        self.assertEqual(
            [p['name'] for p in visible_pieces(catalog, first, 'expression')],
            ['Hero smile', 'Serious'],
        )
        self.assertEqual([s['id'] for s in visible_outfit_sets(catalog, first)], ['001', '099'])
        self.assertEqual([s['id'] for s in visible_outfit_sets(catalog, second)], ['099'])
        self.assertIsNone(find_outfit_set(catalog, second, '001'))
        nude = find_outfit_set(catalog, second, '099')
        self.assertEqual(slot_piece(catalog, second, nude, 'full')['prompt'], ['completely nude'])
        self.assertEqual(self.store.global_catalog()['presets']['generation'], [])

    def test_presets_and_custom_categories(self):
        self.store.save_preset(
            'generation', {'id': 'G001', 'name': 'Base', 'settings': {'steps': 20}}
        )
        self.store.save_preset('expression_set', {'id': 'daily', 'expressions': [{'id': '001'}]})
        with self.assertRaises(ValueError):
            self.store.save_preset('chain', {'id': 'X'})
        with self.assertRaises(ValueError):
            self.store.save_preset('expression_set', {'id': 'bad', 'expressions': ['001']})
        definition = Categories().definition
        definition['roles']['lighting'] = {'label': '조명'}
        with self.assertRaises(ValueError):
            self.store.save_categories(definition)  # Missing from compose_order.
        definition['compose_order'].append('lighting')
        self.store.save_categories(definition)
        piece = self.store.save_piece(
            GLOBAL, 'lighting/night', {'id': 'L1', 'prompt': ['moonlight']}
        )
        self.assertEqual((piece['role'], piece['bucket']), ('lighting', 'lighting'))

    def test_v1_data_folder_is_refused(self):
        data = self.root / 'data'
        check_layout(data)  # A fresh folder is fine.
        (data / 'works/W001/expressions/sfw').mkdir(parents=True)
        with self.assertRaises(OutdatedLayoutError):
            check_layout(data)
        (data / 'layout.json').write_text('{"layout_version": 2}', encoding='utf-8')
        check_layout(data)


if __name__ == '__main__':
    unittest.main()
