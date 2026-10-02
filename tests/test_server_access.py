import json
import tempfile
import unittest
from pathlib import Path

from asset_studio.http.access import allowed_origin


class AllowedOriginTests(unittest.TestCase):
    def test_exact_configured_origin_and_local_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data' / 'settings'
            data.mkdir(parents=True)
            (data / 'server_access.json').write_text(
                json.dumps({'allowed_origins': ['http://192.0.2.10:8195']}), encoding='utf-8'
            )

            for origin in (
                None,
                'http://127.0.0.1:8195',
                'http://localhost:8195',
                'http://192.0.2.10:8195',
            ):
                with self.subTest(origin=origin):
                    self.assertTrue(allowed_origin(temp, origin, 8195))
            for origin in (
                'http://192.0.2.10:8196',
                'http://192.0.2.10.evil:8195',
                'null',
                'http://192.0.2.10:8195.evil',
                'http://localhost:8196',
                'http://192.0.2.10:8195/path',
            ):
                with self.subTest(origin=origin):
                    self.assertFalse(allowed_origin(temp, origin, 8195))

    def test_malformed_config_never_broadens_access(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / 'data' / 'settings'
            data.mkdir(parents=True)
            config = data / 'server_access.json'
            config.write_text('{broken', encoding='utf-8')
            self.assertFalse(allowed_origin(temp, 'http://192.0.2.10:8195', 8195))
            config.write_text(
                json.dumps(
                    {
                        'allowed_origins': [
                            'http://192.0.2.10:8195.evil',
                            'http://192.0.2.10:8195/path',
                            'http://user@192.0.2.10:8195',
                            'http://*.example.com:8195',
                            None,
                        ]
                    }
                ),
                encoding='utf-8',
            )
            self.assertFalse(allowed_origin(temp, 'http://192.0.2.10:8195', 8195))
            self.assertTrue(allowed_origin(temp, 'http://localhost:8195', 8195))
