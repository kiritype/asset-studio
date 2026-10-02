"""Model family detection: folder, manual choice, Stability Matrix info, file header."""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from asset_studio.models import ModelProfiles, family_from_folder, sidecars

BACKSLASH = chr(92)  # ComfyUI reports sub-folders with a backslash on Windows.


def safetensors(path, keys, metadata=None):
    header = {key: {'dtype': 'F16', 'shape': [1], 'data_offsets': [0, 2]} for key in keys}
    if metadata:
        header['__metadata__'] = metadata
    raw = json.dumps(header).encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<Q', len(raw)) + raw + bytes(2))


class ModelProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.models = self.root / 'Models'
        settings = self.root / 'data/settings/models.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(json.dumps({'models_dir': str(self.models)}), encoding='utf-8')
        self.profiles = ModelProfiles(self.root)

    def test_folder_wins_and_windows_separators_work(self):
        self.assertEqual(family_from_folder(f'anima{BACKSLASH}x.safetensors'), 'anima')
        self.assertEqual(family_from_folder('sdxl/x.safetensors'), 'sdxl')
        self.assertIsNone(family_from_folder('x.safetensors'))
        self.assertIsNone(family_from_folder(f'styles{BACKSLASH}x.safetensors'))
        self.assertEqual(
            self.profiles.detect('loras', f'sdxl{BACKSLASH}gone.safetensors'), ('sdxl', 'folder')
        )

    def test_cm_info_then_header(self):
        checkpoint = self.models / 'StableDiffusion' / 'mix.safetensors'
        safetensors(checkpoint, ['conditioner.embedders.0.x'])
        (checkpoint.parent / 'mix.cm-info.json').write_text(
            json.dumps({'BaseModel': 'Illustrious'})
        )
        (checkpoint.parent / 'mix.preview.jpeg').write_bytes(b'jpg')
        self.assertEqual(
            self.profiles.detect('checkpoints', 'mix.safetensors'), ('sdxl', 'cm-info')
        )
        self.assertEqual(
            sorted(p.name for p in sidecars(checkpoint)), ['mix.cm-info.json', 'mix.preview.jpeg']
        )
        unet = self.models / 'DiffusionModels' / 'base.safetensors'
        safetensors(unet, ['net.blocks.0.adaln_modulation_cross_attn.1.weight'])
        self.assertEqual(
            self.profiles.detect('diffusion_models', 'base.safetensors'), ('anima', 'header')
        )
        lora = self.models / 'Lora' / 'style.safetensors'
        safetensors(lora, ['lora_unet_x.alpha'], {'ss_base_model_version': 'sdxl_base_v1-0'})
        self.assertEqual(self.profiles.detect('loras', 'style.safetensors'), ('sdxl', 'header'))
        odd = self.models / 'Lora' / 'odd.safetensors'
        safetensors(odd, ['something.weight'])
        self.assertEqual(self.profiles.detect('loras', 'odd.safetensors'), (None, 'unknown'))
        self.assertEqual(self.profiles.detect('loras', 'absent.safetensors'), (None, 'missing'))

    def test_manual_choice_and_catalog(self):
        odd = self.models / 'Lora' / 'odd.safetensors'
        safetensors(odd, ['something.weight'])
        self.profiles.set_family('loras', 'odd.safetensors', 'anima')
        self.assertEqual(self.profiles.detect('loras', 'odd.safetensors'), ('anima', 'manual'))
        with self.assertRaises(ValueError):
            self.profiles.set_family('loras', 'odd.safetensors', 'sd15')
        name = f'sdxl{BACKSLASH}a.safetensors'
        catalog = {
            'model_entries': {
                f'checkpoint::{name}': {'filename': name, 'loader': 'CheckpointLoaderSimple'}
            },
            'loras': ['odd.safetensors'],
            'text_encoders': [],
            'vaes': [],
        }
        self.assertEqual(
            self.profiles.classify(catalog),
            {
                'models': {f'checkpoint::{name}': 'sdxl'},
                'loras': {'odd.safetensors': 'anima'},
                'text_encoders': {},
                'vaes': {},
            },
        )
        self.profiles.set_family('loras', 'odd.safetensors', None)
        self.assertEqual(self.profiles.detect('loras', 'odd.safetensors'), (None, 'unknown'))


if __name__ == '__main__':
    unittest.main()
