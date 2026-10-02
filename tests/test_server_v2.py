import json
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import request as library_request
from fixtures import seed_library

from asset_studio.app import Studio
from asset_studio.http.handler import handler_class

CATALOG = {
    'connected': True,
    'models': ['model'],
    'text_encoders': ['clip'],
    'vaes': ['vae'],
    'clip_types': ['stable_diffusion'],
    'samplers': ['sampler'],
    'schedulers': ['scheduler'],
    'loras': [],
    'defaults': {
        'model': 'model',
        'text_encoder': 'clip',
        'vae': 'vae',
        'clip_type': 'stable_diffusion',
        'sampler': 'sampler',
        'scheduler': 'scheduler',
    },
}


class ServerV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False, preview=True)
        self.static = self.root / 'preview-static'
        self.static.mkdir()
        (self.static / 'studio.html').write_text('V2 STUDIO ROUTE', encoding='utf-8')
        self.studio.static_root = self.static
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler_class(self.studio))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def request(self, path, body=None):
        data = None if body is None else json.dumps(body).encode('utf-8')
        req = Request(
            f'http://127.0.0.1:{self.server.server_port}{path}',
            data=data,
            headers={'Content-Type': 'application/json'} if data is not None else {},
        )
        try:
            response = urlopen(req, timeout=3)
        except HTTPError as exc:
            response = exc
        with response:
            raw = response.read()
            content_type = response.headers.get('Content-Type', '')
            return response.status, json.loads(raw) if 'application/json' in content_type else raw

    def test_preview_blocks_every_queue_and_connection_mutation(self):
        routes = [
            '/api/jobs',
            '/api/jobs/batch',
            '/api/jobs/x/cancel',
            '/api/jobs/x/retry',
            '/api/jobs/x/remove',
            '/api/queue',
            '/api/queue/pause',
            '/api/queue/resume',
            '/api/queue/clear',
            '/api/queue/clear-finished',
            '/api/connection/control',
            '/api/connection/settings',
            '/api/review/settings',
            '/api/review/rounds/dismiss',
            '/api/gallery/regenerate',
            '/api/gallery/review',
            '/api/vlm/test',
        ]
        for route in routes:
            with self.subTest(route=route):
                status, _ = self.request(route, {})
                self.assertEqual(status, 403)
        self.assertEqual(self.studio.jobs, [])
        self.assertFalse((self.root / 'data/state/queue.json').exists())
        self.assertEqual(self.request('/api/review/settings')[1]['max_auto_regenerations'], 10)
        self.assertEqual(self.request('/api/vlm/status')[1]['configured'], False)

    def test_preview_allows_revision_checked_library_gallery_and_studio_route(self):
        status, page = self.request('/')
        self.assertEqual((status, page), (200, b'V2 STUDIO ROUTE'))
        self.assertEqual(self.request('/studio')[0], 200)
        self.assertEqual(self.request('/gallery')[0], 200)
        status, initial = self.request(
            '/api/library/save',
            {
                'kind': 'work',
                'payload': {'id': 'W001', 'name': 'Original'},
                'expected_revision': None,
            },
        )
        self.assertEqual(status, 200)
        status, changed = self.request(
            '/api/library/save',
            {
                'kind': 'work',
                'payload': {'id': 'W001', 'name': 'Changed'},
                'expected_revision': initial['revision'],
            },
        )
        self.assertEqual(status, 200)
        status, conflict = self.request(
            '/api/library/save',
            {
                'kind': 'work',
                'payload': {'id': 'W001', 'name': 'Stale'},
                'expected_revision': initial['revision'],
            },
        )
        self.assertEqual(status, 409)
        self.assertTrue(conflict['conflict'])
        image = self.root / 'outputs/W001/C001/001/001.webp'
        image.parent.mkdir(parents=True)
        image.write_bytes(b'output')
        status, gallery = self.request('/api/gallery')
        self.assertEqual(status, 200)
        self.assertEqual(gallery['results'][0]['relative_path'], 'W001/C001/001/001.webp')
        self.assertEqual(self.request('/api/gallery/tree')[1]['works'][0]['count'], 1)
        self.assertNotEqual(initial['revision'], changed['revision'])

    def test_piece_and_outfit_set_routes(self):
        seed_library(self.studio.store)
        hero = 'scope=character&work=W001&character=C001'
        status, listed = self.request(f'/api/pieces?{hero}&category=outfit')
        self.assertEqual(
            (status, [p['category'] for p in listed['pieces']]),
            (200, ['outfit/bottom', 'outfit/hands', 'outfit/top']),
        )
        self.assertEqual(len(self.request('/api/pieces?category=expression/sfw')[1]['pieces']), 2)
        self.assertEqual(
            [s['id'] for s in self.request(f'/api/outfit-sets?{hero}')[1]['outfit_sets']], ['001']
        )
        status, catalog = self.request('/api/catalog?work=W001')
        self.assertEqual(
            (status, [c['id'] for c in catalog['characters']]), (200, ['C001', 'C002'])
        )
        self.assertIn('roles', self.request('/api/catalog')[1]['categories'])

        address = {
            'scope': 'character',
            'work_id': 'W001',
            'character_id': 'C001',
            'category': 'outfit/shoes',
        }
        status, saved = self.request(
            '/api/pieces/save',
            {
                **address,
                'payload': {'id': '001', 'name': 'Boots', 'prompt': ['boots']},
                'expected_revision': None,
            },
        )
        self.assertEqual((status, saved['entity']['slot']), (200, 'shoes'))
        status, fetched = self.request(
            f'/api/library/entity?kind=piece&{hero}&category=outfit/shoes&id=001'
        )
        self.assertEqual((status, fetched['revision']), (200, saved['revision']))
        status, stale = self.request(
            '/api/pieces/save',
            {**address, 'payload': {'id': '001', 'name': 'Stale'}, 'expected_revision': 'old'},
        )
        self.assertEqual((status, stale['conflict']), (409, True))
        status, moved = self.request(
            '/api/pieces/move',
            {
                **address,
                'id': '001',
                'expected_revision': saved['revision'],
                'to': {'scope': 'global'},
            },
        )
        self.assertEqual((status, moved['address']['scope']), (200, 'global'))
        status, outfit_set = self.request(
            '/api/outfit-sets/save',
            {
                'scope': 'character',
                'work_id': 'W001',
                'character_id': 'C001',
                'expected_revision': None,
                'payload': {
                    'id': '002',
                    'name': 'Boots only',
                    'slots': {'shoes': {'scope': 'global', 'id': '001'}},
                },
            },
        )
        self.assertEqual((status, outfit_set['entity']['scope']), (200, 'character'))
        status, blocked = self.request(
            '/api/pieces/delete',
            {
                'scope': 'global',
                'category': 'outfit/shoes',
                'id': '001',
                'expected_revision': moved['revision'],
            },
        )
        self.assertEqual(status, 400)
        self.assertIn('의상 세트', blocked['error'])

        status, preview = self.request('/api/compose/preview', library_request(outfit_id='002'))
        self.assertEqual(
            (status, preview['parts']['outfit'], preview['outfit_slots']), (200, 'boots', ['shoes'])
        )
        self.assertEqual(self.request('/api/preview', library_request())[0], 404)

    def test_batch_is_atomic_and_preserves_paused_and_snapshot_choices(self):
        seed_library(self.studio.store)
        self.studio.paused = True
        self.studio.comfy.catalog = lambda: CATALOG
        good = library_request(count=1, settings={'seed': 42})
        bad = {**good, 'expressions': [{'id': '404'}]}
        with self.assertRaises(ValueError):
            self.studio.enqueue_batch({'requests': [good, bad]})
        self.assertEqual(self.studio.jobs, [])
        self.assertFalse(self.studio.state_path.exists())
        result = self.studio.enqueue_batch(
            {'requests': [good, {**good, 'expressions': [{'id': '002'}]}]}
        )
        self.assertEqual(result['count'], 2)
        self.assertTrue(self.studio.paused)
        self.assertTrue(all(job['batch_id'] == result['batch_id'] for job in self.studio.jobs))
        self.assertTrue(
            all(job['snapshot']['batch_id'] == result['batch_id'] for job in self.studio.jobs)
        )
        self.assertEqual(
            [job['snapshot']['expression_id'] for job in self.studio.jobs], ['001', '002']
        )
        self.assertTrue(
            all(
                job['snapshot']['parts']['common'] == 'quality positive' for job in self.studio.jobs
            )
        )
        self.assertTrue(
            all(job['snapshot']['parts']['artist'] == 'artist positive' for job in self.studio.jobs)
        )

    def test_batch_execution_group_is_opt_in_and_persisted(self):
        seed_library(self.studio.store)
        self.studio.comfy.catalog = lambda: CATALOG
        request = library_request(settings={'seed': 42}, execution_group='production:C001')
        result = self.studio.enqueue_batch({'requests': [request]})
        self.assertEqual(result['jobs'][0]['execution_group'], 'production:C001')
        self.assertEqual(self.studio.jobs[0]['snapshot']['execution_group'], 'production:C001')
        reloaded = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.assertEqual(reloaded.jobs[0]['execution_group'], 'production:C001')
        with self.assertRaises(ValueError):
            self.studio.enqueue_batch({'requests': [{**request, 'execution_group': '../bad'}]})


if __name__ == '__main__':
    unittest.main()
