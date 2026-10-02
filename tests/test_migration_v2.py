"""v1 -> v2 data conversion, checked against a small before/after example."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import GLOBAL

from asset_studio.app import Studio
from asset_studio.library.layout import Location
from asset_studio.library.store import OutdatedLayoutError
from tools.migrations import v2

V1_FILES = {
    'works/W001/work.json': {'id': 'W001', 'name': 'Work', 'schema_version': 1},
    'works/W001/characters/C001/character.json': {
        'id': 'C001',
        'name': 'Hero',
        'prompt': ['1girl, blue eyes'],
        'schema_version': 1,
    },
    'works/W001/characters/C001/outfits/001.json': {
        'id': '001',
        'character_id': 'C001',
        'name': '평상복',
        'is_default': True,
        'prompt': ['white gloves', 'blue jacket', 'white shirt', 'black skirt, boots'],
        'parts': {
            'hands': ['white gloves'],
            'top': ['blue jacket', 'white shirt'],
            'bottom': ['black skirt, boots'],
        },
        'negative_prompt': ['necklace'],
        'props_for_action_scenes': 'violin case',
    },
    'works/W001/characters/C001/outfits/002.json': {
        'id': '002',
        'character_id': 'C001',
        'name': '사복',
        'prompt': ['bare hands', 'knit dress', 'black flats'],
    },
    'works/W001/characters/C001/outfits/099.json': {
        'id': '099',
        'character_id': 'C001',
        'name': '누드',
        'prompt': ['completely nude'],
    },
    'works/W001/characters/C002/character.json': {
        'id': 'C002',
        'name': 'Other',
        'prompt': ['1girl, red eyes'],
        'default_outfit': '002',
        'negative_prompt': ['hair down'],
    },
    'works/W001/characters/C002/outfits/002.json': {
        'id': '002',
        'character_id': 'C002',
        'name': '잠옷',
        'design_notes': 'keep',
        'prompt': ['one', 'two', 'three', 'four', 'five'],
        'negative': ['hair bow'],
    },
    'works/W001/characters/C002/outfits/099.json': {
        'id': '099',
        'character_id': 'C002',
        'name': '누드',
        'prompt': ['completely nude'],
    },
    'works/W001/expressions/sfw/001.json': {
        'id': '001',
        'name': '무표정',
        'category': 'sfw',
        'prompt': ['expressionless'],
        'composition': ['upper body', 'straight-on'],
        'negative_prompt': ['head tilt'],
        'source_no': '1',
    },
    'works/W001/expressions/sfw/002.json': {
        'id': '002',
        'name': '미소',
        'category': 'sfw',
        'prompt': ['smile'],
        'composition': ['upper body', 'straight-on'],
        'negative': ['frown'],
    },
    'works/W001/expressions/nsfw/101.json': {
        'id': '101',
        'name': '샤워',
        'category': 'nsfw',
        'prompt': ['showering'],
        'composition': ['cowboy shot', 'straight-on'],
        'adult_only': True,
    },
    'works/W001/chains/daily.json': {
        'id': 'daily',
        'name': 'Daily',
        'generation_id': 'global:G001',
        'expressions': [{'id': '001', 'category': 'sfw'}, {'id': '002', 'category': 'sfw'}],
    },
    'presets/quality/Q001.json': {
        'id': 'Q001',
        'name': 'Safe',
        'scope': 'global',
        'prompt': ['masterpiece'],
        'negative_prompt': ['extra arms'],
    },
    'presets/quality/Q004.json': {
        'id': 'Q004',
        'name': 'General',
        'scope': 'global',
        'prompt': ['newest'],
    },
    'presets/artist/A001.json': {'id': 'A001', 'name': 'my1', 'prompt': ['(@artist:1.2)']},
    'presets/generation/G001.json': {
        'id': 'G001',
        'name': 'my',
        'repeat': 1,
        'settings': {
            'steps': 32,
            'quality_id': 'global:Q001',
            'anima_artist_preset': 'my1',
            'anima_quality_preset': 'Safe',
        },
    },
    'queue.json': {'schema_version': 1, 'paused': False, 'jobs': []},
    'reviews.json': {'version': 1, 'records': {}, 'selected': {}, 'history': []},
    'review_settings.json': {'enabled': False, 'max_auto_regenerations': 3},
    'studio_settings.json': {'url': 'http://127.0.0.1:8188'},
    'trash/20260101T000000-abc/manifest.json': {'id': '20260101T000000-abc', 'kind': 'expression'},
}


class MigrationV2Tests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name) / 'app'
        self.data = self.root / 'data'
        for relative, content in V1_FILES.items():
            path = self.data / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(content, ensure_ascii=False), encoding='utf-8')
        self.build_root = Path(temp.name) / 'build'

    def build(self):
        return v2.build(self.data, self.build_root)

    def test_new_server_code_refuses_the_v1_folder(self):
        with self.assertRaises(OutdatedLayoutError):
            Studio(self.root, 'http://127.0.0.1:1', start_worker=False)

    def test_outfits_become_sets_with_slot_pieces(self):
        _, store, report, checked, mismatches = self.build()
        self.assertEqual(mismatches, [])
        self.assertGreater(checked, 0)
        hero, other = Location('character', 'W001', 'C001'), Location('character', 'W001', 'C002')
        outfit_set = store.read(store.set_file(hero, '001'))
        self.assertEqual(
            outfit_set['slots'],
            {slot: {'scope': 'character', 'id': '001'} for slot in ('hands', 'top', 'bottom')},
        )
        self.assertEqual(outfit_set['negative_prompt'], ['necklace'])
        self.assertEqual(outfit_set['props'], {'note': 'violin case', 'pieces': []})
        for dropped in ('prompt', 'parts', 'is_default', 'character_id', 'props_for_action_scenes'):
            self.assertNotIn(dropped, outfit_set)
        top = store.resolve_piece(hero, 'outfit/top', '001')
        self.assertEqual(
            (top['prompt'], top['name'], top['scope']),
            (['blue jacket', 'white shirt'], '평상복 상의', 'character'),
        )
        three_lines = store.read(store.set_file(hero, '002'))
        self.assertEqual(list(three_lines['slots']), ['hands', 'top', 'bottom'])
        self.assertEqual(
            store.resolve_piece(hero, 'outfit/bottom', '002')['prompt'], ['black flats']
        )
        whole = store.read(store.set_file(other, '002'))
        self.assertEqual(
            (whole['slots'], whole['negative_prompt'], whole['notes']),
            ({'full': {'scope': 'character', 'id': '002'}}, ['hair bow'], 'keep'),
        )
        self.assertEqual(store.read(store.character_file('W001', 'C001'))['default_outfit'], '001')
        self.assertEqual(
            store.read(store.character_file('W001', 'C002'))['negative_prompt'], ['hair down']
        )
        # The identical per-character nude outfit is stored once, globally.
        self.assertFalse(store.set_file(hero, '099').exists())
        self.assertEqual(
            store.read(store.set_file(GLOBAL, '099'))['slots'],
            {'full': {'scope': 'global', 'id': '099'}},
        )
        self.assertEqual(report['counts']['outfit sets'], 4)

    def test_expressions_compositions_and_presets(self):
        _, store, report, _, _ = self.build()
        smile = store.resolve_piece(GLOBAL, 'expression', '002')
        self.assertEqual(
            (smile['rating'], smile['composition_id'], smile['negative_prompt']),
            ('sfw', 'P001', ['frown']),
        )
        for dropped in ('composition', 'negative'):
            self.assertNotIn(dropped, store.read(store.piece_file(GLOBAL, 'expression/sfw', '002')))
        shower = store.resolve_piece(GLOBAL, 'expression', '101')
        self.assertEqual(
            (shower['rating'], shower['composition_id'], shower['adult_only']),
            ('nsfw', 'P002', True),
        )
        upper = store.resolve_piece(GLOBAL, 'composition', 'P001')
        self.assertEqual(
            (upper['prompt'], upper['suggest_slots']),
            (['upper body', 'straight-on'], ['hands', 'top']),
        )
        self.assertNotIn('suggest_slots', store.resolve_piece(GLOBAL, 'composition', 'P002'))
        self.assertEqual(
            store.resolve_piece(GLOBAL, 'common/positive', 'Q001')['prompt'], ['masterpiece']
        )
        self.assertEqual(
            store.resolve_piece(GLOBAL, 'common/negative', 'Q001')['prompt'], ['extra arms']
        )
        self.assertIsNone(store.resolve_piece(GLOBAL, 'common/negative', 'Q004'))
        self.assertNotIn('scope', store.read(store.piece_file(GLOBAL, 'common/positive', 'Q001')))
        preset = store.list_presets('generation')[0]
        self.assertEqual(
            preset['settings'],
            {
                'steps': 32,
                'common_positive_ids': ['Q001'],
                'common_negative_ids': ['Q001'],
                'artist_ids': ['A001'],
            },
        )
        expression_set = store.list_presets('expression_set')[0]
        self.assertEqual(
            (expression_set['expressions'], expression_set['generation_preset_id']),
            ([{'id': '001'}, {'id': '002'}], 'G001'),
        )
        self.assertEqual(report['warnings'], [])

    def test_a_different_prompt_after_conversion_is_reported(self):
        v1, store, report, _, _ = self.build()
        path = store.piece_file(Location('character', 'W001', 'C001'), 'outfit/top', '001')
        path.write_text(json.dumps({'id': '001', 'prompt': ['red jacket']}), encoding='utf-8')
        _, mismatches = v2.verify(v1, store, report)
        self.assertTrue(mismatches)
        self.assertTrue(all('C001/001' in item['target'] for item in mismatches))

    def test_apply_backs_up_everything_and_rollback_restores_it(self):
        before = {
            path.relative_to(self.data).as_posix(): path.read_bytes()
            for path in self.data.rglob('*')
            if path.is_file()
        }
        _, store, _, _, _ = self.build()
        backup = v2.apply(self.root, store.root, 'STAMP')
        saved = {
            path.relative_to(backup / 'data').as_posix(): path.read_bytes()
            for path in (backup / 'data').rglob('*')
            if path.is_file()
        }
        self.assertEqual(saved, before)
        for moved in (
            'state/queue.json',
            'state/reviews.json',
            'settings/review_settings.json',
            'settings/connection.json',
            'trash-v1/20260101T000000-abc/manifest.json',
            'pieces/_categories.json',
            'pieces/expression/sfw/001.json',
            'outfit_sets/099.json',
        ):
            self.assertTrue((self.data / moved).is_file(), moved)
        for gone in (
            'queue.json',
            'works/W001/expressions',
            'works/W001/characters/C001/outfits',
            'presets/quality',
            'trash',
        ):
            self.assertFalse((self.data / gone).exists(), gone)
        studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        result = studio.compose(
            {
                'work_id': 'W001',
                'character_id': 'C001',
                'outfit_id': '001',
                'outfit_slots': ['hands', 'top'],
                'expressions': [{'id': '001'}],
                'common_positive_ids': ['Q001'],
                'common_negative_ids': ['Q001'],
                'artist_ids': ['A001'],
            }
        )
        self.assertEqual(
            result['positive'],
            'masterpiece, (@artist:1.2), upper body, straight-on, '
            '1girl, blue eyes, expressionless, white gloves, blue jacket, white shirt',
        )
        self.assertEqual(result['negative'], 'extra arms, necklace, head tilt')
        self.assertEqual(studio.validation.settings['max_auto_regenerations'], 3)
        self.assertEqual(studio.library.list_trash()['items'], [])
        with self.assertRaises(SystemExit):
            v2.build(self.data, self.build_root)  # Already converted.
        v2.rollback(self.root, backup, 'STAMP2')
        restored = {
            path.relative_to(self.data).as_posix(): path.read_bytes()
            for path in self.data.rglob('*')
            if path.is_file()
        }
        self.assertEqual(restored, before)


if __name__ == '__main__':
    unittest.main()
