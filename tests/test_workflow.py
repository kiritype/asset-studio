import unittest

from asset_studio.generation.workflow import (
    build_ui_workflow,
    build_workflow,
    defaults,
    validate_settings,
)

CATALOG = {
    'models': ['anima_aestheticV11', 'anima_turboV11'],
    'text_encoders': ['qwen_3_06b_base'],
    'vaes': ['qwen_image_vae'],
    'loras': ['style.safetensors'],
    'samplers': ['er_sde', 'euler'],
    'schedulers': ['simple', 'normal'],
    'clip_types': ['stable_diffusion'],
}


class WorkflowTests(unittest.TestCase):
    def test_defaults_use_installed_defaults(self):
        self.assertEqual(defaults(CATALOG)['model'], 'anima_aestheticV11')
        catalog = {**CATALOG, 'models': ['custom']}
        self.assertEqual(defaults(catalog)['model'], 'custom')
        exact_catalog = {
            **CATALOG,
            'models': ['other.safetensors', 'anima_aestheticV11.safetensors'],
            'text_encoders': ['other.safetensors', 'qwen_3_06b_base.safetensors'],
            'vaes': ['other.safetensors', 'qwen_image_vae.safetensors'],
        }
        self.assertEqual(defaults(exact_catalog)['text_encoder'], 'qwen_3_06b_base.safetensors')
        self.assertEqual(
            validate_settings({}, exact_catalog)['text_encoder'], 'qwen_3_06b_base.safetensors'
        )

    def test_invalid_catalog_selection_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'available models'):
            validate_settings({'model': 'missing'}, CATALOG)

    def test_signed_lora_strengths_are_preserved(self):
        settings = validate_settings(
            {
                'loras': [
                    {
                        'name': 'style.safetensors',
                        'strength_model': -0.5,
                        'strength_clip': 0.25,
                    }
                ]
            },
            CATALOG,
        )
        self.assertEqual(settings['loras'][0]['strength_model'], -0.5)
        self.assertEqual(settings['loras'][0]['strength_clip'], 0.25)

    def test_lora_count_and_strength_ranges_match_ui(self):
        too_many = {'loras': ['style.safetensors'] * 17}
        with self.assertRaisesRegex(ValueError, '16'):
            validate_settings(too_many, CATALOG)
        too_strong = {'loras': [{'name': 'style.safetensors', 'strength_model': 10.01}]}
        with self.assertRaisesRegex(ValueError, '-10 and 10'):
            validate_settings(too_strong, CATALOG)

    def test_seed_is_safe_for_javascript_numbers(self):
        self.assertEqual(validate_settings({'seed': 2**53 - 1}, CATALOG)['seed'], 2**53 - 1)
        with self.assertRaisesRegex(ValueError, 'seed'):
            validate_settings({'seed': 2**53}, CATALOG)

    def test_graph_has_valid_links_and_no_unrequested_processing(self):
        settings = validate_settings({'loras': [{'name': 'style.safetensors'}]}, CATALOG)
        graph = build_workflow(settings, 'positive words', 'negative words', 42)
        self.assertEqual(graph['1']['class_type'], 'UNETLoader')
        self.assertEqual(graph['2']['class_type'], 'CLIPLoader')
        self.assertEqual(graph['4']['class_type'], 'LoraLoader')
        self.assertEqual(graph['4']['inputs']['lora_name'], 'style.safetensors')
        self.assertEqual(graph['output']['class_type'], 'PreviewImage')
        self.assertEqual(graph['output']['inputs']['images'], ['9', 0])
        self.assertEqual(graph['8']['class_type'], 'KSampler')
        self.assertEqual(graph['8']['inputs']['seed'], 42)
        self.assertEqual(graph['8']['inputs']['denoise'], 1.0)
        links = {
            node_id
            for node_id, node in graph.items()
            if node['class_type']
            in {
                'UNETLoader',
                'CLIPLoader',
                'VAELoader',
                'LoraLoader',
                'CLIPTextEncode',
                'EmptyLatentImage',
                'KSampler',
                'VAEDecode',
                'PreviewImage',
            }
        }
        for node in graph.values():
            for value in node['inputs'].values():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[0], str):
                    self.assertIn(value[0], links)
        self.assertFalse(
            {'SageAttention', 'LatentUpscale', 'FaceDetailer', 'ImageUpscaleWithModel'}
            & {node['class_type'] for node in graph.values()}
        )

    def test_ui_export_has_loadable_node_and_link_structure(self):
        settings = validate_settings({'loras': [{'name': 'style.safetensors'}]}, CATALOG)
        workflow = build_ui_workflow(settings, 'positive words', 'negative words', 42)
        nodes = {node['id']: node for node in workflow['nodes']}
        self.assertEqual(nodes[10]['type'], 'PreviewImage')
        self.assertEqual(nodes[10]['inputs'][0]['link'], 11)
        self.assertEqual(nodes[8]['type'], 'KSampler')
        self.assertEqual(nodes[8]['widgets_values'][0], 42)
        self.assertEqual(nodes[4]['widgets_values'], ['style.safetensors', 1.0, 1.0])
        prompt_nodes = [node for node in workflow['nodes'] if node['type'] == 'CLIPTextEncode']
        self.assertNotEqual(prompt_nodes[0]['pos'], prompt_nodes[1]['pos'])
        self.assertTrue(all(node['size'] == [340, 280] for node in prompt_nodes))
        self.assertEqual(nodes[8]['size'], [280, 280])
        self.assertEqual(nodes[10]['size'], [420, 420])
        link_ids = {link[0] for link in workflow['links']}
        self.assertTrue(
            all(
                link_id in link_ids
                for node in workflow['nodes']
                for output in node['outputs']
                for link_id in output['links']
            )
        )

    def test_sdxl_uses_the_checkpoint_clip_and_vae(self):
        catalog = {
            **CATALOG,
            'models': [*CATALOG['models'], 'checkpoint::sdxl/il.safetensors'],
            'model_entries': {
                'checkpoint::sdxl/il.safetensors': {
                    'filename': 'sdxl/il.safetensors',
                    'loader': 'CheckpointLoaderSimple',
                }
            },
            'vaes': [*CATALOG['vaes'], 'sdxl_vae.safetensors'],
        }
        settings = validate_settings(
            {
                'family': 'sdxl',
                'model': 'checkpoint::sdxl/il.safetensors',
                'loras': [{'name': 'style.safetensors'}],
            },
            catalog,
        )
        self.assertNotIn('text_encoder', settings)
        self.assertEqual((settings['vae'], settings['clip_skip']), ('', 2))
        graph = build_workflow(settings, 'tag', 'bad', 7)
        types = {node['class_type'] for node in graph.values()}
        self.assertNotIn('CLIPLoader', types)
        self.assertNotIn('VAELoader', types)
        self.assertEqual(graph['2']['inputs'], {'clip': ['1', 1], 'stop_at_clip_layer': -2})
        decode = next(node for node in graph.values() if node['class_type'] == 'VAEDecode')
        self.assertEqual(decode['inputs']['vae'], ['1', 2])
        lora = next(node for node in graph.values() if node['class_type'] == 'LoraLoader')
        self.assertEqual(lora['inputs']['clip'], ['2', 0])
        editor = build_ui_workflow(settings, 'tag', 'bad', 7)
        self.assertIn('CLIPSetLastLayer', {node['type'] for node in editor['nodes']})
        override = validate_settings(
            {
                'family': 'sdxl',
                'model': 'checkpoint::sdxl/il.safetensors',
                'vae': 'sdxl_vae.safetensors',
                'clip_skip': 1,
            },
            catalog,
        )
        graph = build_workflow(override, 'tag', 'bad', 7)
        self.assertEqual(graph['3']['inputs'], {'vae_name': 'sdxl_vae.safetensors'})
        self.assertEqual(graph['2']['inputs']['stop_at_clip_layer'], -1)
        with self.assertRaisesRegex(ValueError, '체크포인트'):
            validate_settings({'family': 'sdxl', 'model': 'anima_aestheticV11'}, catalog)
        with self.assertRaises(ValueError):
            validate_settings({'family': 'sd15'}, catalog)
        self.assertEqual(validate_settings({}, catalog)['family'], 'anima')


class MovedModelTests(unittest.TestCase):
    def test_names_from_before_a_folder_move_still_resolve(self):
        from asset_studio.generation.workflow import _resolve

        choices = [
            'anima\\a.safetensors',
            'checkpoint::anima\\b.safetensors',
            'sdxl\\c.safetensors',
        ]
        self.assertEqual(_resolve('a.safetensors', choices), 'anima\\a.safetensors')
        self.assertEqual(
            _resolve('checkpoint::b.safetensors', choices), 'checkpoint::anima\\b.safetensors'
        )
        self.assertEqual(_resolve('b.safetensors', choices), 'b.safetensors')  # Not a checkpoint.
        self.assertEqual(_resolve('missing.safetensors', choices), 'missing.safetensors')
        twice = choices + ['sdxl\\a.safetensors']
        self.assertEqual(_resolve('a.safetensors', twice), 'a.safetensors')  # Ambiguous.


if __name__ == '__main__':
    unittest.main()
