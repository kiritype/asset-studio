import json
import tempfile
import unittest
from pathlib import Path

from asset_studio import settings_api
from asset_studio.app import Studio


class SettingsApiTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.addCleanup(self.studio.stop.set)

    def saved(self, name):
        return json.loads((self.root / 'data/settings' / name).read_text(encoding='utf-8'))

    def test_defaults_without_files(self):
        everything = settings_api.get_all(self.studio)
        self.assertEqual(everything['ui']['values']['theme'], 'system')
        self.assertFalse(everything['gpu']['values']['enabled'])
        self.assertFalse(everything['vlm']['status']['configured'])

    def test_save_validates_and_keeps_unknown_keys(self):
        path = self.root / 'data/settings/lora_pipeline.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'trainer_method': 'custom', 'lora_dir': 'old'}))
        result = settings_api.save(
            self.studio,
            {
                'section': 'lora',
                'values': {
                    'lora_dir': 'C:/loras',
                    'bases': {'official': {'dit': 'a', 'text_encoder': 'b', 'vae': 'c'}},
                },
            },
        )
        self.assertFalse(result['status']['lora_dir_found'])
        saved = self.saved('lora_pipeline.json')
        self.assertEqual(saved['trainer_method'], 'custom')
        self.assertEqual(saved['lora_dir'], 'C:/loras')
        self.assertEqual(list(saved['bases']), ['official'])

        settings_api.save(self.studio, {'section': 'ui', 'values': {'theme': 'dark'}})
        self.assertEqual(self.saved('ui.json')['theme'], 'dark')
        settings_api.save(
            self.studio,
            {'section': 'gpu', 'values': {'enabled': True, 'watch_processes': 'a.exe\nb.exe\n'}},
        )
        self.assertEqual(self.saved('gpu.json')['watch_processes'], ['a.exe', 'b.exe'])
        self.assertTrue(self.studio.gpu.monitor.settings()['enabled'])
        for body in (
            {'section': 'ui', 'values': {'theme': 'pink'}},
            {'section': 'ui', 'values': {'language': 'fr'}},
            {'section': 'gpu', 'values': {'min_free_vram_mb': {'generation': -1}}},
            {'section': 'nope', 'values': {}},
        ):
            with self.subTest(body=body), self.assertRaises(ValueError):
                settings_api.save(self.studio, body)

    def test_vlm_and_tags_reload(self):
        result = settings_api.save(
            self.studio,
            {
                'section': 'vlm',
                'values': {
                    'enabled': True,
                    'url': 'http://127.0.0.1:1234',
                    'model': 'm',
                    'load_command': 'lms\nload\nm',
                    'unload_command': 'lms\nunload\nm',
                    'status_command': 'lms\nps',
                    'loaded_marker': 'm',
                },
            },
        )
        self.assertTrue(result['status']['configured'], result['status'])
        self.assertEqual(self.saved('vlm.json')['load_command'], ['lms', 'load', 'm'])
        before = self.studio.tags
        settings_api.save(self.studio, {'section': 'tags', 'values': {'danbooru_dir': ''}})
        self.assertIsNot(self.studio.tags, before)


if __name__ == '__main__':
    unittest.main()
