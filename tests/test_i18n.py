import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import i18n_check

from asset_studio.i18n import Msg, message_of, wire


class CatalogTest(unittest.TestCase):
    def test_every_key_is_translated_with_the_same_placeholders(self):
        report = i18n_check.check()
        for language, missing in report['missing'].items():
            with self.subTest(language=language):
                self.assertEqual(missing, [], 'run tools/i18n_check.py')
        self.assertEqual(report['placeholders'], [])
        self.assertEqual(report['english'], [], 'en.json must match the English in Msg()')
        self.assertEqual(report['unused'], [])

    def test_no_korean_left_in_code(self):
        self.assertEqual(i18n_check.hangul_in_code(), [])


class MessageTest(unittest.TestCase):
    def test_a_message_is_english_text_that_keeps_its_key(self):
        holder = Msg('server.gpu.training', 'LoRA training')
        message = Msg('server.x.busy', 'The GPU is used by {name}.', name=holder)
        self.assertEqual(message, 'The GPU is used by LoRA training.')
        self.assertEqual(
            wire({'error': message}),
            {
                'error': {
                    'i18n': 'server.x.busy',
                    'params': {
                        'name': {
                            'i18n': 'server.gpu.training',
                            'params': {},
                            'text': 'LoRA training',
                        }
                    },
                    'text': 'The GPU is used by LoRA training.',
                }
            },
        )
        self.assertIs(message_of(ValueError(message)), message)
        self.assertEqual(message_of(ValueError('plain')), 'plain')

    def test_an_exception_value_is_kept_as_its_message(self):
        inner = Msg('server.x.offline', 'ComfyUI is offline.')
        message = Msg('server.x.failed', 'Failed: {error}', error=RuntimeError(inner))
        self.assertEqual(message, 'Failed: ComfyUI is offline.')
        self.assertIs(message.params['error'], inner)
        plain = Msg('server.x.failed', 'Failed: {error}', error=OSError('refused'))
        self.assertEqual(json.loads(json.dumps(wire(plain)))['params'], {'error': 'refused'})


if __name__ == '__main__':
    unittest.main()
