import copy
import io
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from PIL import Image

from asset_studio.app import Studio
from asset_studio.library.layout import Location

SETTINGS = dict(
    model='model',
    text_encoder='encoder',
    vae='vae',
    clip_type='stable_diffusion',
    sampler='euler',
    scheduler='simple',
    steps=2,
    cfg=5,
    width=256,
    height=256,
    seed=42,
    loras=[],
)
CATALOG = dict(
    connected=True,
    models=['model'],
    text_encoders=['encoder'],
    vaes=['vae'],
    clip_types=['stable_diffusion'],
    samplers=['euler'],
    schedulers=['simple'],
    loras=[],
)


def picture(color):
    result = io.BytesIO()
    Image.new('RGB', (32, 32), color).save(result, 'PNG')
    return result.getvalue()


class FakeComfy:
    def __init__(self, color):
        self.color = color
        self.calls = []

    def catalog(self):
        return CATALOG

    def request(self, path, body=None, raw=False):
        self.calls.append((path, body))
        if path == '/queue':
            return {'queue_running': [], 'queue_pending': []}
        if path == '/prompt':
            return {'prompt_id': 'own-prompt'}
        if path.startswith('/history/'):
            return {
                'own-prompt': {
                    'status': {'status_str': 'success'},
                    'outputs': {'output': {'images': [{'filename': 'test.png', 'type': 'temp'}]}},
                }
            }
        if path.startswith('/view?'):
            return picture(self.color)
        raise AssertionError(path)


class ServerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.app = Studio(self.temp.name, 'http://unused', start_worker=False)
        self.app.comfy = FakeComfy('white')
        s = self.app.store
        hero = Location('character', 'W001', 'C001')
        s.save_work(dict(id='W001', name='Work'))
        s.save_character('W001', dict(id='C001', name='One', prompt=['person']))
        s.save_character('W001', dict(id='C002', name='Two', prompt=['other']))
        s.save_piece(hero, 'outfit/full', dict(id='001', name='Uniform', prompt=['coat']))
        s.save_outfit_set(
            hero, dict(id='001', name='Uniform', slots=dict(full=dict(scope='character', id='001')))
        )
        s.save_piece(
            Location('global'),
            'composition',
            dict(id='P001', name='Upper body', prompt=['upper body']),
        )
        for ident, prompt in [('001', 'expressionless'), ('002', 'smile')]:
            s.save_piece(
                Location('global'),
                'expression/sfw',
                dict(
                    id=ident,
                    name=ident,
                    prompt=[prompt],
                    composition_id='P001',
                    negative_prompt=['blur'],
                ),
            )
        self.request = dict(
            work_id='W001',
            character_id='C001',
            outfit_id='001',
            expressions=[dict(id='001')],
            count=1,
            settings=SETTINGS,
        )

    def tearDown(self):
        self.app.stop.set()
        self.temp.cleanup()

    def test_outfit_relation_is_enforced(self):
        with self.assertRaises(ValueError):
            self.app.compose({**self.request, 'character_id': 'C002'})

    def test_snapshot_and_multiselect_overrides(self):
        req = copy.deepcopy(self.request)
        req['expressions'].append(dict(id='002'))
        req['overrides'] = dict(outfit='blue coat', expression='wrong override')
        self.app.enqueue(req)
        self.app.store.save_character('W001', dict(id='C001', prompt=['changed']))
        snaps = [j['snapshot'] for j in self.app.jobs]
        self.assertEqual([s['parts']['expression'] for s in snaps], ['expressionless', 'smile'])
        self.assertTrue(
            all(
                s['parts']['appearance'] == 'person' and s['parts']['outfit'] == 'blue coat'
                for s in snaps
            )
        )

    def test_collision_safe_names_and_metadata(self):
        self.app.enqueue(self.request)
        job = self.app.jobs[0]
        a = self.app.save_result(job, picture('white'), {'node': {}}, 'p')
        b = self.app.save_result(job, picture('red'), {'node': {}}, 'p2')
        self.assertEqual(a, '/outputs/W001/C001/001/001.png')
        self.assertEqual(b, '/outputs/W001/C001/001/001_002.png')
        meta = json.loads((Path(self.temp.name) / 'outputs/W001/C001/001/001.json').read_text())
        self.assertEqual(meta['settings']['seed'], 42)
        self.assertEqual(meta['positive'], 'upper body, person, expressionless, coat')
        # The PNG carries ComfyUI's prompt/workflow chunks and the Studio record.
        with Image.open(Path(self.temp.name) / 'outputs/W001/C001/001/001.png') as saved:
            self.assertEqual(json.loads(saved.info['prompt']), {'node': {}})
            self.assertIn('nodes', json.loads(saved.info['workflow']))
            self.assertEqual(json.loads(saved.info['asset_studio'])['job_id'], job['id'])
        # An older WebP with the next stem keeps its name; the new PNG skips past it.
        (Path(self.temp.name) / 'outputs/W001/C001/001/001_003.webp').write_bytes(b'old')
        c = self.app.save_result(job, picture('blue'), {'node': {}}, 'p3')
        self.assertEqual(c, '/outputs/W001/C001/001/001_004.png')

    def test_black_result_stops_queue(self):
        self.app.comfy = FakeComfy('black')
        self.app.enqueue({**self.request, 'count': 2})
        thread = threading.Thread(target=self.app.worker)
        thread.start()
        try:
            deadline = time.monotonic() + 5
            while (
                self.app.jobs[0]['status'] not in ('failed', 'completed')
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)
        finally:
            self.app.stop.set()
            thread.join(3)
        self.assertEqual(self.app.jobs[0]['status'], 'failed')
        self.assertEqual(self.app.jobs[1]['status'], 'queued')
        self.assertTrue(self.app.paused)
        self.assertFalse(list(Path(self.temp.name).rglob('*.webp')))

    def test_restart_does_not_resubmit_running_job(self):
        self.app.enqueue(self.request)
        self.app.jobs[0]['status'] = 'running'
        self.app.persist()
        restarted = Studio(self.temp.name, 'http://unused', start_worker=False)
        self.assertEqual(restarted.jobs[0]['status'], 'interrupted')
        self.assertTrue(restarted.paused)

    def test_cancel_pending_does_not_touch_comfy(self):
        self.app.enqueue(self.request)
        self.app.cancel(self.app.jobs[0]['id'])
        self.assertEqual(self.app.jobs[0]['status'], 'cancelled')
        self.assertEqual(self.app.comfy.calls, [])

    def test_clear_finished_preserves_active_jobs_files_and_pause(self):
        self.app.enqueue({**self.request, 'count': 7})
        statuses = [
            'completed',
            'failed',
            'cancelled',
            'interrupted',
            'queued',
            'running',
            'cancelling',
        ]
        for job, status in zip(self.app.jobs, statuses):
            job['status'] = status
        self.app.save_result(self.app.jobs[0], picture('white'), {}, 'done')
        self.app.paused = True
        result = self.app.remove_finished()
        self.assertEqual(result['removed'], 4)
        self.assertEqual([j['status'] for j in self.app.jobs], statuses[4:])
        self.assertTrue(self.app.paused)
        folder = Path(self.temp.name) / 'outputs/W001/C001/001'
        self.assertTrue((folder / '001.png').exists())
        self.assertTrue((folder / '001.json').exists())
        saved = json.loads(self.app.state_path.read_text())
        self.assertEqual(len(saved['jobs']), 3)
        self.assertEqual(self.app.remove_finished()['removed'], 0)

    def test_remove_single_rejects_active_and_keeps_other_finished(self):
        self.app.enqueue({**self.request, 'count': 3})
        self.app.jobs[0]['status'] = 'cancelled'
        self.app.jobs[1]['status'] = 'interrupted'
        active_id = self.app.jobs[2]['id']
        with self.assertRaises(ValueError):
            self.app.remove_finished(active_id)
        self.assertEqual(self.app.remove_finished(self.app.jobs[0]['id'])['removed'], 1)
        self.assertEqual([j['status'] for j in self.app.jobs], ['interrupted', 'queued'])
        self.assertEqual(self.app.comfy.calls, [])


if __name__ == '__main__':
    unittest.main()
