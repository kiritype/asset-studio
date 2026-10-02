import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from test_server import SETTINGS, FakeComfy, picture

from asset_studio.app import Studio


class LabTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = Studio(self.root, 'http://unused', start_worker=False)
        self.addCleanup(self.app.stop.set)
        self.app.comfy = FakeComfy('white')
        self.body = dict(positive='1girl, smile', negative='blur', settings=SETTINGS)

    def test_seed_rows_share_the_seed_across_a_sweep(self):
        result = self.app.enqueue_lab(
            {**self.body, 'count': 2, 'sweep': {'key': 'cfg', 'values': [3, 5, 7]}}
        )
        self.assertEqual(result['variants'], ['CFG 3.0', 'CFG 5.0', 'CFG 7.0'])
        self.assertEqual(result['seeds'], [42, 43])
        jobs = self.app.jobs
        self.assertEqual(len(jobs), 6)
        self.assertEqual([j['seed'] for j in jobs], [42, 42, 42, 43, 43, 43])
        self.assertEqual([j['snapshot']['settings']['cfg'] for j in jobs[:3]], [3, 5, 7])
        self.assertTrue(all(j['kind'] == 'lab' and not j['review_requested'] for j in jobs))
        self.assertEqual({j['lab_group'] for j in jobs}, {result['lab_group']})

    def test_lora_strength_sweep_changes_only_that_lora(self):
        catalog = dict(FakeComfy('white').catalog(), loras=['a.safetensors', 'b.safetensors'])
        self.app.comfy.catalog = lambda: catalog
        loras = [
            {'name': 'a.safetensors', 'strength_model': 1, 'strength_clip': 1},
            {'name': 'b.safetensors', 'strength_model': 0.5, 'strength_clip': 0.5},
        ]
        self.app.enqueue_lab(
            {
                **self.body,
                'settings': {**SETTINGS, 'loras': loras},
                'sweep': {'key': 'lora_strength', 'lora_index': 1, 'values': [0.2, 0.8]},
            }
        )
        used = [j['snapshot']['settings']['loras'] for j in self.app.jobs]
        self.assertEqual([u[1]['strength_model'] for u in used], [0.2, 0.8])
        self.assertTrue(all(u[0]['strength_model'] == 1 for u in used))

    def test_bad_requests(self):
        for body in (
            {**self.body, 'positive': ' '},
            {**self.body, 'count': 17},
            {**self.body, 'sweep': {'key': 'width', 'values': [512, 768]}},
            {**self.body, 'sweep': {'key': 'cfg', 'values': [5]}},
            {**self.body, 'sweep': {'key': 'lora_strength', 'values': [0.5, 1]}},
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                self.app.enqueue_lab(body)
        self.assertEqual(self.app.jobs, [])

    def test_results_go_to_the_lab_folder_with_metadata(self):
        self.app.enqueue_lab(self.body)
        job = self.app.jobs[0]
        url = self.app.save_result(job, picture('white'), {'node': {}}, 'p')
        self.assertTrue(url.startswith('/outputs/_lab/'))
        path = self.root / url.removeprefix('/')
        with Image.open(path) as saved:
            self.assertEqual(json.loads(saved.info['asset_studio'])['kind'], 'lab')
            self.assertIn('nodes', json.loads(saved.info['workflow']))
        listing = self.app.gallery.list({})
        item = next(i for i in listing['results'] if i['relative_path'].startswith('_lab/'))
        self.assertEqual(item['work_id'], '')

    def test_retry_keeps_the_lab_fields(self):
        self.app.enqueue_lab(self.body)
        self.app.jobs[0]['status'] = 'failed'
        self.app.retry(self.app.jobs[0]['id'])
        self.assertEqual(self.app.jobs[1]['kind'], 'lab')
        self.assertEqual(self.app.jobs[1]['lab_group'], self.app.jobs[0]['lab_group'])


if __name__ == '__main__':
    unittest.main()
