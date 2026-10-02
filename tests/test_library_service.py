import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import GLOBAL, character, seed_library

from asset_studio.library.service import ConflictError, Library
from asset_studio.library.store import LibraryStore

HERO = {'scope': 'character', 'work_id': 'W001', 'character_id': 'C001'}
TOP = {'kind': 'piece', **HERO, 'category': 'outfit/top'}
SET = {'kind': 'outfit_set', **HERO}


class LibraryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.store = LibraryStore(self.root)
        self.library = Library(self.store, threading.RLock())
        seed_library(self.store)

    def revision(self, address, ident):
        return self.library.get({**address, 'id': ident})['revision']

    def create(self, address, payload):
        return self.library.save({**address, 'payload': payload, 'expected_revision': None})

    def delete(self, address, ident):
        return self.library.delete(
            {**address, 'id': ident, 'expected_revision': self.revision(address, ident)}
        )['trash_id']

    def slots(self, ident='001', location=None):
        path = self.store.set_file(location or character('W001', 'C001'), ident)
        return json.loads(path.read_text(encoding='utf-8'))['slots']

    def test_compare_and_swap_rejects_stale_and_existing_create(self):
        work = {'kind': 'work'}
        original = self.library.get({**work, 'id': 'W001'})
        self.library.save(
            {
                **work,
                'payload': {'id': 'W001', 'name': 'Updated'},
                'expected_revision': original['revision'],
            }
        )
        with self.assertRaises(ConflictError):
            self.library.save(
                {
                    **work,
                    'payload': {'id': 'W001', 'name': 'Stale'},
                    'expected_revision': original['revision'],
                }
            )
        self.assertEqual(self.library.get({**work, 'id': 'W001'})['entity']['name'], 'Updated')
        with self.assertRaises(ConflictError):
            self.create(TOP, {'id': '001', 'name': 'Accidental overwrite'})
        with self.assertRaises(ConflictError):
            self.library.save({**TOP, 'payload': {'id': '009', 'name': 'No revision given'}})
        created = self.create(TOP, {'id': '009', 'name': 'New top'})
        self.assertEqual(created['entity']['slot'], 'top')

    def test_trash_restore_hierarchy_retired_codes_and_outputs_preserved(self):
        self.create(SET, {'id': '002', 'name': 'Spare', 'slots': {}})
        output = self.root / 'outputs/W001/C001/002/001.webp'
        output.parent.mkdir(parents=True)
        output.write_bytes(b'historical output')
        set_trash = self.delete(SET, '002')
        with self.assertRaises(ConflictError):
            self.create(SET, {'id': '002', 'name': 'Reuse'})
        character_trash = self.delete({'kind': 'character', 'work_id': 'W001'}, 'C001')
        work_trash = self.delete({'kind': 'work'}, 'W001')
        self.assertEqual(len(self.library.list_trash()['items']), 3)
        with self.assertRaises(ValueError):
            self.library.restore(character_trash)
        self.library.restore(work_trash)
        with self.assertRaises(ValueError):
            self.library.restore(set_trash)
        self.library.restore(character_trash)
        self.library.restore(set_trash)
        hero = self.store.catalog('W001')['characters'][0]
        self.assertEqual([s['id'] for s in hero['outfit_sets']], ['001', '002'])
        self.assertEqual(len(hero['pieces']), 3)
        self.assertEqual(output.read_bytes(), b'historical output')
        self.assertEqual(self.library.list_trash()['items'], [])

    def test_restore_never_overwrites(self):
        trash_id = self.delete({'kind': 'character', 'work_id': 'W001'}, 'C002')
        replacement = self.store.character_file('W001', 'C002')
        replacement.parent.mkdir(parents=True)
        replacement.write_text(json.dumps({'id': 'C002', 'name': 'Replacement'}), encoding='utf-8')
        with self.assertRaises(ConflictError):
            self.library.restore(trash_id)
        self.assertEqual(json.loads(replacement.read_text(encoding='utf-8'))['name'], 'Replacement')

    def test_references_block_deletion(self):
        with self.assertRaises(ValueError):
            self.delete(TOP, '001')  # Used by outfit set 001.
        with self.assertRaises(ValueError):
            self.delete(SET, '001')  # The character's default outfit.
        composition = {'kind': 'piece', 'scope': 'global', 'category': 'composition'}
        with self.assertRaises(ValueError):
            self.delete(composition, 'P001')  # Expression 001 uses it.
        expression = {'kind': 'piece', 'scope': 'global', 'category': 'expression/sfw'}
        self.store.save_preset('expression_set', {'id': 'daily', 'expressions': [{'id': '001'}]})
        with self.assertRaises(ValueError):
            self.delete(expression, '001')
        self.delete({'kind': 'preset', 'preset_type': 'expression_set'}, 'daily')
        self.delete(expression, '001')
        self.delete(composition, 'P001')
        self.store.save_preset('generation', {'id': 'G001', 'settings': {'artist_ids': ['A001']}})
        with self.assertRaises(ValueError):
            self.delete({'kind': 'piece', 'scope': 'global', 'category': 'artist'}, 'A001')

    def test_override_can_be_deleted_because_the_wider_piece_takes_over(self):
        override = {'kind': 'piece', **HERO, 'category': 'composition'}
        self.create(override, {'id': 'P001', 'name': 'Hero framing'})
        hero_expression = {'kind': 'piece', **HERO, 'category': 'expression/sfw'}
        self.create(hero_expression, {'id': '001', 'name': 'Hero smile', 'composition_id': 'P001'})
        self.delete(override, 'P001')
        self.assertEqual(
            self.store.resolve_piece(character('W001', 'C001'), 'composition', 'P001')['scope'],
            'global',
        )

    def test_move_piece_between_scopes_rewrites_set_references(self):
        moved = self.library.move(
            {
                **TOP,
                'id': '001',
                'expected_revision': self.revision(TOP, '001'),
                'to': {'scope': 'global'},
            }
        )
        self.assertEqual(
            moved['address'],
            {'kind': 'piece', 'scope': 'global', 'category': 'outfit/top', 'id': '001'},
        )
        self.assertEqual(moved['entity']['scope'], 'global')
        self.assertEqual(self.slots()['top'], {'scope': 'global', 'id': '001'})
        self.assertTrue((self.root / 'data/pieces/outfit/top/001.json').is_file())
        # A second character starts using the now-global piece; it can no longer become private.
        self.store.save_outfit_set(
            character('W001', 'C002'),
            {'id': '001', 'name': 'Borrowed', 'slots': {'top': {'scope': 'global', 'id': '001'}}},
        )
        top = {'kind': 'piece', 'scope': 'global', 'category': 'outfit/top'}
        with self.assertRaises(ValueError):
            self.library.move(
                {**top, 'id': '001', 'expected_revision': self.revision(top, '001'), 'to': HERO}
            )
        shared = self.library.move(
            {
                **top,
                'id': '001',
                'expected_revision': self.revision(top, '001'),
                'to': {'scope': 'work', 'work_id': 'W001', 'category': 'outfit/top/shared'},
            }
        )
        self.assertEqual(shared['entity']['category'], 'outfit/top/shared')
        self.assertEqual(self.slots()['top'], {'scope': 'work', 'id': '001'})
        self.assertEqual(
            self.slots(location=character('W001', 'C002'))['top'], {'scope': 'work', 'id': '001'}
        )
        with self.assertRaises(ConflictError):
            self.library.move(
                {
                    'kind': 'piece',
                    'scope': 'work',
                    'work_id': 'W001',
                    'category': 'outfit/top/shared',
                    'id': '001',
                    'expected_revision': 'stale',
                    'to': {'scope': 'global'},
                }
            )

    def test_move_outfit_set_needs_its_pieces_and_default_users_to_stay_in_reach(self):
        with self.assertRaises(ValueError):
            self.library.move(
                {
                    **SET,
                    'id': '001',
                    'expected_revision': self.revision(SET, '001'),
                    'to': {'scope': 'global'},
                }
            )  # Slots still point at character pieces.
        self.store.save_piece(GLOBAL, 'outfit/full', {'id': 'nude', 'prompt': ['completely nude']})
        self.create(
            SET, {'id': '099', 'name': 'Nude', 'slots': {'full': {'scope': 'global', 'id': 'nude'}}}
        )
        moved = self.library.move(
            {
                **SET,
                'id': '099',
                'expected_revision': self.revision(SET, '099'),
                'to': {'scope': 'global'},
            }
        )
        self.assertEqual(moved['entity']['scope'], 'global')
        self.assertTrue((self.root / 'data/outfit_sets/099.json').is_file())
        other = {
            'kind': 'outfit_set',
            'scope': 'character',
            'work_id': 'W001',
            'character_id': 'C002',
        }
        nude = {'kind': 'outfit_set', 'scope': 'global'}
        self.store.save_character('W001', {'id': 'C001', 'default_outfit': '099'})
        with self.assertRaises(ValueError):
            self.library.move(
                {**nude, 'id': '099', 'expected_revision': self.revision(nude, '099'), 'to': other}
            )  # C001's default outfit would disappear.

    def test_rename_outfit_set_updates_default_and_reserves_old_code(self):
        historical = self.root / 'outputs/W001/C001/001/001.webp'
        historical.parent.mkdir(parents=True)
        historical.write_bytes(b'historical')
        self.library.save(
            {
                **SET,
                'original_id': '001',
                'payload': {'id': '002', 'name': 'New coat'},
                'expected_revision': self.revision(SET, '001'),
            }
        )
        hero = self.store.catalog('W001')['characters'][0]
        self.assertEqual(hero['default_outfit'], '002')
        self.assertEqual([(s['id'], s['name']) for s in hero['outfit_sets']], [('002', 'New coat')])
        with self.assertRaises(ConflictError):
            self.create(SET, {'id': '001', 'name': 'Reuse'})
        self.library.save(
            {
                'kind': 'character',
                'work_id': 'W001',
                'original_id': 'C001',
                'payload': {'id': 'C009', 'name': 'Hero'},
                'expected_revision': self.revision(
                    {'kind': 'character', 'work_id': 'W001'}, 'C001'
                ),
            }
        )
        renamed = self.store.catalog('W001')['characters'][1]
        self.assertEqual((renamed['id'], renamed['pieces'][0]['character_id']), ('C009', 'C009'))
        self.assertEqual(
            self.slots('002', character('W001', 'C009'))['top'], {'scope': 'character', 'id': '001'}
        )
        self.library.save(
            {
                'kind': 'work',
                'original_id': 'W001',
                'payload': {'id': 'W002', 'name': 'Renamed'},
                'expected_revision': self.revision({'kind': 'work'}, 'W001'),
            }
        )
        self.assertEqual(self.store.catalog('W002')['work']['id'], 'W002')
        self.assertEqual(historical.read_bytes(), b'historical')
        with self.assertRaises(ConflictError):
            self.create({'kind': 'work'}, {'id': 'W001'})
        with self.assertRaises(ValueError):
            self.library.save(
                {**TOP, 'original_id': '001', 'payload': {'id': '002'}, 'expected_revision': None}
            )

    def test_rename_rolls_back_when_a_reference_write_fails(self):
        before = self.store.catalog('W001')
        original_write = self.store.write

        def broken_write(path, data):
            if path.name == 'character.json':
                raise OSError('injected write failure')
            return original_write(path, data)

        self.store.write = broken_write
        try:
            with self.assertRaises(OSError):
                self.library.save(
                    {
                        **SET,
                        'original_id': '001',
                        'payload': {'id': '002', 'name': 'New'},
                        'expected_revision': self.revision(SET, '001'),
                    }
                )
        finally:
            self.store.write = original_write
        self.assertEqual(self.store.catalog('W001'), before)
        self.assertFalse(list((self.root / 'data/retired').rglob('*.json')))

    def test_presets_are_revision_checked_and_trashed(self):
        preset = {'kind': 'preset', 'preset_type': 'generation'}
        saved = self.create(preset, {'id': 'G001', 'name': 'Base', 'settings': {'steps': 20}})
        self.library.save(
            {
                **preset,
                'payload': {'id': 'G001', 'settings': {'steps': 32}},
                'expected_revision': saved['revision'],
            }
        )
        self.store.save_preset('combination', {'id': 'K001', 'generation_preset_id': 'G001'})
        with self.assertRaises(ValueError):
            self.delete(preset, 'G001')
        self.delete({'kind': 'preset', 'preset_type': 'combination'}, 'K001')
        trash_id = self.delete(preset, 'G001')
        self.assertEqual(self.store.list_presets('generation'), [])
        backups = [
            json.loads(p.read_text(encoding='utf-8'))
            for p in (self.root / 'data/backups').glob('presets_generation_*.json')
        ]
        self.assertEqual([b['settings']['steps'] for b in backups], [20])
        self.library.restore(trash_id)
        self.assertEqual(self.store.list_presets('generation')[0]['settings'], {'steps': 32})
        with self.assertRaises(ValueError):
            self.library.get({**preset, 'id': '../G001'})

    def test_version_changes_with_any_library_file(self):
        before = self.library.version()['revision']
        self.assertEqual(before, self.library.version()['revision'])
        self.create(TOP, {'id': '002', 'name': 'Another top'})
        self.assertNotEqual(before, self.library.version()['revision'])


if __name__ == '__main__':
    unittest.main()
