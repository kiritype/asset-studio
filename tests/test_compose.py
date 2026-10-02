"""Prompt assembly contracts using a temporary library and no ComfyUI calls."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import GLOBAL, character, request, seed_library

from asset_studio.app import Studio
from asset_studio.library.layout import Categories, Location

CATALOG = {
    'connected': True,
    'models': ['model'],
    'text_encoders': ['clip'],
    'vaes': ['vae'],
    'clip_types': ['stable_diffusion'],
    'samplers': ['euler'],
    'schedulers': ['simple'],
    'loras': [],
    'defaults': {
        'model': 'model',
        'text_encoder': 'clip',
        'vae': 'vae',
        'clip_type': 'stable_diffusion',
        'sampler': 'euler',
        'scheduler': 'simple',
    },
}


class ComposeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.studio = Studio(Path(temporary.name), 'http://127.0.0.1:1', start_worker=False)
        self.store = self.studio.store
        seed_library(self.store)

    def test_composes_all_positive_and_negative_layers_in_order(self):
        result = self.studio.compose(request())
        self.assertEqual(
            result['positive'],
            ', '.join(
                [
                    'work positive',
                    'quality positive',
                    'artist positive',
                    'composition positive',
                    'character positive',
                    'expression positive',
                    'gloves',
                    'jacket',
                    'skirt, boots',
                ]
            ),
        )
        self.assertEqual(
            result['negative'],
            ', '.join(
                [
                    'work negative',
                    'quality negative',
                    'artist negative',
                    'character negative',
                    'outfit negative',
                    'expression negative',
                ]
            ),
        )
        self.assertEqual(result['parts']['common'], 'quality positive')
        self.assertEqual(result['negative_parts']['common'], 'quality negative')
        self.assertEqual((result['category'], result['expression_name']), ('sfw', 'Smile'))
        self.assertEqual(result['outfit_set'], {'scope': 'character', 'id': '001', 'name': 'Coat'})
        self.assertIn(
            {
                'role': 'outfit',
                'category': 'outfit/top',
                'scope': 'character',
                'id': '001',
                'name': 'top',
            },
            result['pieces'],
        )

    def test_nothing_is_added_unless_selected(self):
        result = self.studio.compose(
            request(artist_ids=[], common_positive_ids=None, common_negative_ids=[])
        )
        self.assertEqual(result['parts']['artist'], '')
        self.assertEqual(result['parts']['common'], '')
        self.assertNotIn('quality', result['positive'] + result['negative'])
        with self.assertRaises(ValueError):
            self.studio.compose(request(artist_ids=['A404']))

    def test_prompts_written_for_another_model_family_warn(self):
        self.assertEqual(self.studio.compose(request())['warnings'], [])
        result = self.studio.compose(request(settings={'family': 'sdxl'}))
        self.assertEqual(result['model_family'], 'sdxl')
        self.assertTrue(any(w.startswith('Work') for w in result['warnings']))
        self.store.save_work({'id': 'W001', 'name': 'Work', 'model_family': 'shared'})
        result = self.studio.compose(request(settings={'family': 'sdxl'}))
        self.assertFalse(any(w.startswith('Work') for w in result['warnings']))

    def test_selected_outfit_slots_only(self):
        result = self.studio.compose(request(outfit_slots=['top', 'hands']))
        self.assertEqual(result['parts']['outfit'], 'gloves, jacket')
        self.assertEqual(result['outfit_slots'], ['hands', 'top'])
        self.assertNotIn('boots', result['positive'])
        self.assertIn('outfit negative', result['negative'])
        everything = self.studio.compose(request())
        self.assertEqual(everything['outfit_slots'], ['hands', 'top', 'bottom'])
        for bad in (['top', 'shoes'], [], 'top'):
            with self.subTest(slots=bad), self.assertRaises(ValueError):
                self.studio.compose(request(outfit_slots=bad))

    def test_composition_comes_from_the_expression_unless_chosen(self):
        self.store.save_piece(
            GLOBAL,
            'composition',
            {'id': 'P002', 'prompt': ['cowboy shot'], 'negative_prompt': ['close-up']},
        )
        self.assertEqual(self.studio.compose(request())['composition_id'], 'P001')
        chosen = self.studio.compose(request(composition_id='P002'))
        self.assertEqual(chosen['parts']['composition'], 'cowboy shot')
        self.assertTrue(chosen['negative'].endswith('expression negative, close-up'))
        bare = self.studio.compose(request(expressions=[{'id': '002'}]))
        self.assertEqual((bare['composition_id'], bare['parts']['composition']), (None, ''))
        with self.assertRaises(ValueError):
            self.studio.compose(request(composition_id='P404'))

    def test_character_piece_overrides_work_and_global(self):
        self.store.save_piece(
            Location('work', 'W001'),
            'expression/sfw',
            {'id': '001', 'name': 'Work smile', 'prompt': ['work smile']},
        )
        self.store.save_piece(
            character('W001', 'C001'),
            'expression/nsfw',
            {'id': '001', 'name': 'Hero only', 'prompt': ['hero smile']},
        )
        result = self.studio.compose(request())
        self.assertEqual(
            (result['parts']['expression'], result['category']), ('hero smile', 'nsfw')
        )
        self.store.save_piece(GLOBAL, 'outfit/full', {'id': 'nude', 'prompt': ['completely nude']})
        self.store.save_outfit_set(
            GLOBAL,
            {'id': '099', 'name': 'Nude', 'slots': {'full': {'scope': 'global', 'id': 'nude'}}},
        )
        other = self.studio.compose(request(character_id='C002', outfit_id='099'))
        self.assertEqual(other['parts']['expression'], 'work smile')
        self.assertEqual(other['parts']['outfit'], 'completely nude')

    def test_outfit_set_must_be_visible_to_the_character(self):
        with self.assertRaises(ValueError):
            self.studio.compose(request(character_id='C002'))
        with self.assertRaises(ValueError):
            self.studio.compose(request(character_id='C404'))
        with self.assertRaises(ValueError):
            self.studio.compose(request(expressions=[{'id': '404'}]))

    def test_new_role_takes_its_position_from_the_category_definition(self):
        definition = Categories().definition
        definition['roles']['lighting'] = {'label': '조명'}
        definition['compose_order'].insert(
            definition['compose_order'].index('appearance'), 'lighting'
        )
        self.store.save_categories(definition)
        self.store.save_piece(
            GLOBAL,
            'lighting',
            {'id': 'L1', 'prompt': ['moonlight'], 'negative_prompt': ['sunlight']},
        )
        result = self.studio.compose(request(extras={'lighting': ['L1']}))
        self.assertIn('composition positive, moonlight, character positive', result['positive'])
        self.assertTrue(result['negative'].endswith('sunlight'))
        with self.assertRaises(ValueError):
            self.studio.compose(request(extras={'artist': ['A001']}))

    def test_prepared_generation_snapshot_keeps_the_selection(self):
        jobs = self.studio.enqueue(
            request(settings={'seed': 123}, outfit_slots=['top']),
            _catalog=CATALOG,
            _prepare_only=True,
        )
        self.assertEqual(len(jobs), 1)
        self.assertEqual(self.studio.jobs, [])
        self.assertFalse(self.studio.state_path.exists())
        snapshot = jobs[0]['snapshot']
        self.assertIn('quality positive', snapshot['positive'])
        self.assertIn('quality negative', snapshot['negative'])
        self.assertEqual(snapshot['outfit_slots'], ['top'])
        self.assertEqual(snapshot['settings']['seed'], 123)
        self.assertEqual((jobs[0]['outfit_id'], jobs[0]['category']), ('001', 'sfw'))


if __name__ == '__main__':
    unittest.main()
