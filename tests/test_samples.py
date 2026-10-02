import tempfile
import unittest
from pathlib import Path

from asset_studio import samples
from asset_studio.app import Studio


class SampleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.studio = Studio(Path(temporary.name), 'http://127.0.0.1:1', start_worker=False)
        self.addCleanup(self.studio.stop.set)

    def test_sample_imports_as_a_new_work_that_composes(self):
        listed = samples.list_samples()['samples']
        self.assertEqual(listed[0]['id'], 'starlight_academy')
        first = samples.import_sample(self.studio, 'starlight_academy')
        second = samples.import_sample(self.studio, 'starlight_academy')
        self.assertEqual((first['work_id'], second['work_id']), ('W900', 'W901'))
        request = {
            'work_id': 'W900',
            'character_id': 'C001',
            'outfit_id': '001',
            'expressions': [{'id': '002'}],
            'common_positive_ids': ['Q001'],
            'common_negative_ids': ['Q001'],
        }
        result = self.studio.compose(request)
        for tag in ('fantasy', 'grey hair', 'blue necktie', 'smile', 'upper body', 'masterpiece'):
            self.assertIn(tag, result['positive'])
        self.assertIn('worst quality', result['negative'])
        catalog = self.studio.store.catalog('W900')
        lyra = next(c for c in catalog['characters'] if c['id'] == 'C001')
        self.assertEqual(lyra['default_outfit'], '001')
        # Nothing was added outside the new works.
        self.assertEqual(self.studio.store.global_catalog()['global_pieces'], [])
        with self.assertRaises(ValueError):
            samples.import_sample(self.studio, 'nope')


if __name__ == '__main__':
    unittest.main()
