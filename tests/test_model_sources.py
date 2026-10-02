import unittest

from asset_studio.generation.comfy import Comfy
from asset_studio.generation.workflow import build_ui_workflow, build_workflow, validate_settings


class ModelSourcesTest(unittest.TestCase):
    def catalog(self):
        info = {}
        for node, field, names in [
            ('UNETLoader', 'unet_name', ['same.safetensors']),
            ('CheckpointLoaderSimple', 'ckpt_name', ['same.safetensors', 'other.safetensors']),
            ('CLIPLoader', 'clip_name', ['encoder']),
            ('CLIPLoader', 'type', ['stable_diffusion']),
            ('VAELoader', 'vae_name', ['vae']),
            ('LoraLoader', 'lora_name', []),
            ('KSampler', 'sampler_name', ['euler']),
            ('KSampler', 'scheduler', ['simple']),
        ]:
            info.setdefault(node, {'input': {'required': {}}})['input']['required'][field] = [names]
        comfy = Comfy('http://unused')
        comfy.request = lambda path: info
        return comfy.catalog()

    def test_both_sources_and_duplicate_filenames_are_distinct(self):
        catalog = self.catalog()
        self.assertTrue(catalog['connected'])
        self.assertEqual(
            catalog['models'],
            ['same.safetensors', 'checkpoint::same.safetensors', 'checkpoint::other.safetensors'],
        )
        for model, loader in [
            ('same.safetensors', 'UNETLoader'),
            ('checkpoint::same.safetensors', 'CheckpointLoaderSimple'),
        ]:
            settings = validate_settings(
                {'model': model, 'model_loader': 'untrusted', 'model_filename': '../wrong'}, catalog
            )
            graph = build_workflow(settings, 'person', '', 1)
            self.assertEqual(graph['1']['class_type'], loader)
            self.assertIn('same.safetensors', graph['1']['inputs'].values())
            self.assertEqual(graph['2']['class_type'], 'CLIPLoader')
            self.assertEqual(graph['3']['class_type'], 'VAELoader')
            ui = build_ui_workflow(settings, 'person', '', 1)
            self.assertEqual(ui['nodes'][0]['type'], loader)


if __name__ == '__main__':
    unittest.main()
