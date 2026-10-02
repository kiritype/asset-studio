import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from asset_studio.validation.vlm import LocalVLM, VLMError


class RuntimeOptionsTests(unittest.TestCase):
    def test_external_instruction_and_token_budget(self):
        with tempfile.TemporaryDirectory() as d:
            image = Path(d) / 'image.png'
            Image.new('RGB', (16, 16), 'white').save(image)
            c = LocalVLM(d)
            c.config = {
                'url': 'http://127.0.0.1:1234',
                'model': 'test',
                'review_instruction': 'Test explicit visible rules',
                'max_output_tokens': 640,
            }
            c.is_loaded = lambda: True
            with patch('asset_studio.validation.vlm.build_opener') as factory:
                factory.return_value.open.return_value = io.BytesIO(
                    json.dumps(
                        {
                            'choices': [
                                {
                                    'finish_reason': 'stop',
                                    'message': {
                                        'content': json.dumps(
                                            {
                                                'verdict': 'fail',
                                                'evidence': 'Required jacket absent',
                                            }
                                        )
                                    },
                                }
                            ]
                        }
                    ).encode()
                )
                self.assertEqual(c.review(image, {'positive': 'jacket'})['verdict'], 'fail')
                request = factory.return_value.open.call_args.args[0]
                payload = json.loads(request.data)
                self.assertEqual(payload['max_tokens'], 640)
                self.assertEqual(
                    payload['messages'][1]['content'][0]['text'],
                    'Test explicit visible rules\njacket',
                )
            c.config['max_output_tokens'] = True
            with self.assertRaises(VLMError):
                c.review(image, {'positive': 'jacket'})
