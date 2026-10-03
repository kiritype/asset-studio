import io
import json
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path

from PIL import Image, PngImagePlugin
from test_server import CATALOG, SETTINGS, FakeComfy

from asset_studio.app import Studio
from asset_studio.tools import metadata, tagger
from asset_studio.tools.convert import convert, options_of


def png(color='white', size=(64, 48), text=None, mode='RGB'):
    info = PngImagePlugin.PngInfo()
    for key, value in (text or {}).items():
        info.add_text(key, value)
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, 'PNG', pnginfo=info)
    return out.getvalue()


COMFY_PROMPT = {
    '1': {
        'class_type': 'CheckpointLoaderSimple',
        'inputs': {'ckpt_name': 'sdxl/model.safetensors'},
    },
    '2': {'class_type': 'CLIPTextEncode', 'inputs': {'text': '1girl, smile', 'clip': ['1', 1]}},
    '3': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'blur', 'clip': ['1', 1]}},
    '4': {
        'class_type': 'KSampler',
        'inputs': {
            'positive': ['2', 0],
            'negative': ['3', 0],
            'seed': 7,
            'steps': 20,
            'cfg': 5.5,
            'sampler_name': 'euler',
            'scheduler': 'normal',
        },
    },
}


class MetadataTest(unittest.TestCase):
    def describe(self, raw):
        with tempfile.NamedTemporaryFile(suffix='.img', delete=False) as handle:
            handle.write(raw)
        self.addCleanup(Path(handle.name).unlink)
        return metadata.describe(handle.name)

    def test_comfy_graph_gives_prompt_and_settings(self):
        found = self.describe(png(text={'prompt': json.dumps(COMFY_PROMPT), 'workflow': '{}'}))
        self.assertEqual(found['prompt']['source'], 'comfyui')
        self.assertEqual(found['prompt']['positive'], '1girl, smile')
        self.assertEqual(found['prompt']['negative'], 'blur')
        self.assertEqual(found['prompt']['settings']['seed'], 7)
        self.assertTrue(found['has_workflow'])
        self.assertEqual(found['comfy']['models'][0]['ckpt_name'], 'sdxl/model.safetensors')

    def test_a1111_parameters(self):
        text = 'masterpiece, 1girl\nNegative prompt: lowres, bad hands\nSteps: 28, Sampler: Euler a, CFG scale: 7, Seed: 12, Model: "x, y"'  # noqa: E501
        found = self.describe(png(text={'parameters': text}))
        self.assertEqual(found['prompt']['source'], 'parameters')
        self.assertEqual(found['prompt']['positive'], 'masterpiece, 1girl')
        self.assertEqual(found['prompt']['negative'], 'lowres, bad hands')
        self.assertEqual(found['prompt']['settings']['Seed'], '12')
        self.assertEqual(found['prompt']['settings']['Model'], 'x, y')

    def test_studio_record_wins(self):
        studio = {'positive': 'studio prompt', 'negative': 'n', 'settings': {'seed': 1}}
        found = self.describe(
            png(text={'asset_studio': json.dumps(studio), 'prompt': json.dumps(COMFY_PROMPT)})
        )
        self.assertEqual(found['prompt']['source'], 'asset_studio')
        self.assertEqual(found['prompt']['positive'], 'studio prompt')


class ConvertTest(unittest.TestCase):
    def source(self, raw):
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as handle:
            handle.write(raw)
        self.addCleanup(Path(handle.name).unlink)
        return handle.name

    def test_strips_metadata_by_default_and_keeps_it_on_request(self):
        path = self.source(png(text={'prompt': json.dumps(COMFY_PROMPT), 'workflow': '{"a": 1}'}))
        raw, _ = convert(path, options_of({}))
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertEqual(len(image.getexif()), 0)
        raw, _ = convert(path, options_of({'keep_metadata': True}))
        with Image.open(io.BytesIO(raw)) as image:
            text, _ = metadata.read_raw(image)
        self.assertEqual(json.loads(text['prompt']), COMFY_PROMPT)
        self.assertEqual(json.loads(text['workflow']), {'a': 1})

    def test_alpha_and_resize(self):
        path = self.source(png((10, 20, 30, 0), size=(400, 200), mode='RGBA'))
        raw, size = convert(path, options_of({'long_side': 100, 'lossless': True}))
        self.assertEqual(size, (100, 50))
        with Image.open(io.BytesIO(raw)) as image:
            self.assertEqual(image.mode, 'RGBA')

    def test_bad_options(self):
        for body in ({'quality': 0}, {'long_side': 99999}, {'suffix': '../x'}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                options_of(body)


class DetailGraphTest(unittest.TestCase):
    def test_uses_the_images_own_loaders_loras_and_prompts(self):
        from asset_studio.generation.workflow import validate_settings
        from asset_studio.tools.postprocess import check_options, detail_graph

        catalog = {**CATALOG, 'loras': ['style.safetensors']}
        lora = {'name': 'style.safetensors', 'strength_model': 0.7, 'strength_clip': 0.7}
        settings = validate_settings({**SETTINGS, 'loras': [lora]}, catalog)
        options = check_options('detail', {'hand': False}, {})
        source = {'settings': settings, 'positive': 'p', 'negative': 'n', 'seed': 9}
        nodes = detail_graph('in.png', options, source, 'AssetStudio')
        kinds = sorted(n['class_type'] for n in nodes.values())
        self.assertNotIn('KSampler', kinds)
        self.assertNotIn('EmptyLatentImage', kinds)
        self.assertNotIn('VAEDecode', kinds)
        detail = nodes['detail']['inputs']
        self.assertEqual(nodes[detail['model'][0]]['class_type'], 'LoraLoader')
        self.assertEqual(nodes[detail['positive'][0]]['inputs']['text'], 'p')
        self.assertEqual((detail['face_enabled'], detail['mouth_enabled']), (True, False))
        self.assertFalse(detail['hand_enabled'])
        self.assertEqual((detail['seed'], detail['cfg']), (9, settings['cfg']))
        with self.assertRaises(ValueError):
            check_options('detail', {s: False for s in ('face', 'eye', 'mouth', 'hand')}, {})


class InpaintGraphTest(unittest.TestCase):
    def test_redraws_only_the_mask_with_the_images_own_model(self):
        from asset_studio.generation.workflow import validate_settings
        from asset_studio.tools.postprocess import check_options, inpaint_graph

        catalog = {**CATALOG, 'loras': ['style.safetensors']}
        lora = {'name': 'style.safetensors', 'strength_model': 0.7, 'strength_clip': 0.7}
        settings = validate_settings({**SETTINGS, 'loras': [lora]}, catalog)
        options = check_options('inpaint', {'denoise': 0.5}, {})
        self.assertEqual((options['steps'], options['grow'], options['feather']), (0, 8, 8))
        source = {'settings': settings, 'positive': 'p', 'negative': 'n', 'seed': 9}
        nodes = inpaint_graph('in.png', 'mask.png', options, source)
        kinds = [n['class_type'] for n in nodes.values()]
        self.assertNotIn('EmptyLatentImage', kinds)
        sampler = next(n['inputs'] for n in nodes.values() if n['class_type'] == 'KSampler')
        self.assertEqual(sampler['latent_image'], ['noise_mask', 0])
        self.assertEqual((sampler['denoise'], sampler['steps']), (0.5, settings['steps']))
        self.assertEqual(nodes[sampler['model'][0]]['class_type'], 'LoraLoader')
        self.assertEqual(nodes['mask']['inputs'], {'image': 'mask.png', 'channel': 'red'})
        composite = nodes['composite']['inputs']
        self.assertEqual((composite['destination'], composite['mask']), (['image', 0], ['mask', 0]))
        self.assertEqual(nodes['output']['inputs']['images'], ['composite', 0])
        stepped = inpaint_graph('in.png', 'm.png', {**options, 'steps': 12}, source)
        sampler = next(n['inputs'] for n in stepped.values() if n['class_type'] == 'KSampler')
        self.assertEqual(sampler['steps'], 12)
        for bad in ({'denoise': 0}, {'positive': 1}, {'grow': 99}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                check_options('inpaint', bad, {})


class WorkspaceTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.app = Studio(self.root, 'http://unused', start_worker=False)
        self.addCleanup(self.app.stop.set)
        self.tools = self.app.tools

    def test_upload_zip_and_gallery(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as archive:
            archive.writestr('../../evil/a.png', png('red'))
            archive.writestr('notes.txt', 'hello')
            archive.writestr('broken.png', b'not an image')
        result = self.tools.upload('set.zip', out.getvalue())
        self.assertEqual([i['name'] for i in result['added']], ['a.png'])
        self.assertEqual(len(result['skipped']), 2)
        stored = list((self.root / 'data/tools/uploads').iterdir())
        self.assertEqual(len(stored), 1)
        with self.assertRaises(ValueError):
            self.tools.upload('x.gif', b'GIF89a')

        folder = self.root / 'outputs/_lab/2026-10-01'
        folder.mkdir(parents=True)
        (folder / 'a.png').write_bytes(png())
        added = self.tools.add_gallery(['_lab/2026-10-01/a.png'])['added']
        self.assertEqual(added[0]['source'], 'gallery')
        self.assertEqual(self.tools.add_gallery(['_lab/2026-10-01/a.png'])['added'], [])
        with self.assertRaises(ValueError):
            self.tools.add_gallery(['../data/state/tools.json'])

        ids = [i['id'] for i in self.tools.public()['items']]
        self.tools.remove(ids)
        self.assertEqual(list((self.root / 'data/tools/uploads').iterdir()), [])
        self.assertTrue((folder / 'a.png').exists())

    def test_convert_task_writes_to_the_tools_folder(self):
        item = self.tools.upload('pic.png', png())['added'][0]
        task = self.app.converter.start({'ids': [item['id']], 'suffix': '_web'})['task']
        for _ in range(100):
            current = self.app.converter.get(task['id'])
            if current['status'] == 'completed':
                break
            time.sleep(0.05)
        self.assertEqual(current['errors'], [])
        self.assertTrue(current['results'][0]['relative_path'].endswith('/pic_web.webp'))
        raw, name = self.app.converter.zip(task['id'])
        self.assertEqual(zipfile.ZipFile(io.BytesIO(raw)).namelist(), ['pic_web.webp'])

    def test_tag_job_runs_through_the_worker(self):
        item = self.tools.upload('pic.png', png())['added'][0]
        comfy = FakeComfy('white')
        base = comfy.request

        def request(path, body=None, raw=False):
            if path.startswith('/object_info/'):
                return {
                    tagger.NODE: {'input': {'required': {'model': [['wd-eva02-large-tagger-v3']]}}}
                }
            if path.startswith('/history/'):
                return {
                    'own-prompt': {
                        'status': {'status_str': 'success'},
                        'outputs': {
                            '2': {'tags': ['1girl, solo, smile, kaname madoka \\(magical girl\\)']}
                        },
                    }
                }
            return base(path, body, raw)

        comfy.request = request
        comfy.upload = lambda name, raw: {
            'name': name,
            'subfolder': 'asset_studio',
            'type': 'input',
        }
        self.app.comfy = comfy
        self.app.enqueue_tags({'ids': [item['id']], 'threshold': 0.5})
        with self.assertRaises(ValueError):
            self.app.enqueue_tags({'ids': [item['id']], 'model': 'nope'})
        import threading

        thread = threading.Thread(target=self.app.worker)
        thread.start()
        for _ in range(100):
            if self.app.jobs[0]['status'] == 'completed':
                break
            time.sleep(0.05)
        self.app.stop.set()
        thread.join(5)
        self.assertEqual(self.app.jobs[0]['status'], 'completed', self.app.jobs[0].get('error'))
        sent = next(body for path, body in comfy.calls if path == '/prompt')['prompt']
        self.assertEqual(
            sent['1']['inputs']['image'], f'asset_studio/asset_studio_tag_{item["id"]}.png'
        )
        self.assertEqual(sent['2']['inputs']['threshold'], 0.5)
        saved = self.tools.get(item['id'])['tags']
        self.assertEqual(saved['tags'], ['1girl', 'solo', 'smile', 'kaname madoka (magical girl)'])

    def run_worker(self, job_index=0):
        thread = threading.Thread(target=self.app.worker)
        thread.start()
        for _ in range(100):
            if self.app.jobs[job_index]['status'] in ('completed', 'failed'):
                break
            time.sleep(0.05)
        self.app.stop.set()
        thread.join(5)
        return self.app.jobs[job_index]

    def test_detection_gives_an_editable_mask_and_studio_applies_the_censor(self):
        item = self.tools.upload('pic.png', png('blue', size=(32, 32)))['added'][0]
        comfy = FakeComfy('white')  # The detector "finds" the whole image.
        base = comfy.request
        info = {'AtelierXUpscale': {}, 'AtelierXDetectNsfwMask': {}}

        def request(path, body=None, raw=False):
            return info if path == '/object_info' else base(path, body, raw)

        comfy.request = request
        comfy.upload = lambda name, raw: {'name': name, 'subfolder': '', 'type': 'input'}
        self.app.comfy = comfy
        self.app.enqueue_postprocess({'ids': [item['id']], 'op': 'detect'})
        job = self.run_worker()
        self.assertEqual(job['status'], 'completed', job.get('error'))
        sent = next(body for path, body in comfy.calls if path == '/prompt')['prompt']
        self.assertEqual(sent['3']['class_type'], 'MaskToImage')
        self.assertEqual(self.tools.get(item['id'])['mask']['source'], 'detected')

        # An edited mask replaces it; only the left half stays covered.
        edited = Image.new('L', (32, 32), 0)
        edited.paste(255, (0, 0, 16, 32))
        out = io.BytesIO()
        edited.save(out, 'PNG')
        self.tools.set_mask(item['id'], out.getvalue(), 'edited')
        with self.assertRaises(ValueError):
            small = io.BytesIO()
            Image.new('L', (8, 8)).save(small, 'PNG')
            self.tools.set_mask(item['id'], small.getvalue(), 'edited')

        url = self.app.apply_censor({'id': item['id'], 'treatment': 'white_solid'})['url']
        result = Image.open(self.root / url.removeprefix('/')).convert('RGB')
        self.assertEqual(result.getpixel((4, 4)), (255, 255, 255))
        self.assertEqual(result.getpixel((28, 4)), (0, 0, 255))
        listed = [i for i in self.tools.public()['items'] if i.get('parent') == item['id']]
        self.assertEqual(listed[0]['op'], 'censor')

    def test_censor_needs_a_mask(self):
        item = self.tools.upload('pic.png', png())['added'][0]
        with self.assertRaises(ValueError):
            self.app.apply_censor({'id': item['id']})

    def test_background_split_gives_an_editable_alpha_mask(self):
        # The fake ComfyUI answers with a white 32x32 image: "keep everything".
        item = self.tools.upload('pic.png', png('blue', size=(32, 32)))['added'][0]
        comfy = FakeComfy('white')
        base = comfy.request
        info = {
            'AtelierXUpscale': {},
            'RemBGSession+': {},
            'UpscaleModelLoader': {'input': {'required': {'model_name': [['4x.safetensors']]}}},
        }

        def request(path, body=None, raw=False):
            if path == '/object_info':
                return info
            return base(path, body, raw)

        comfy.request = request
        comfy.upload = lambda name, raw: {'name': name, 'subfolder': '', 'type': 'input'}
        self.app.comfy = comfy
        with self.assertRaises(ValueError):
            body = {'ids': [item['id']], 'op': 'upscale', 'options': {'model': 'x'}}
            self.app.enqueue_postprocess(body)
        with self.assertRaises(ValueError):
            self.app.enqueue_postprocess(
                {'ids': [item['id']], 'op': 'censor', 'options': {'labels': 'face'}}
            )
        self.app.enqueue_postprocess({'ids': [item['id']], 'op': 'alpha'})
        job = self.run_worker()
        self.assertEqual(job['status'], 'completed', job.get('error'))
        sent = next(body for path, body in comfy.calls if path == '/prompt')['prompt']
        self.assertEqual(sent['4']['class_type'], 'MaskToImage')
        self.assertEqual(sent['4']['inputs']['mask'], ['3', 1])
        self.assertEqual(self.tools.get(item['id'])['alpha_mask']['source'], 'detected')
        self.assertIsNone(self.tools.mask(item['id']))  # The censor mask is separate.

        # Edit: keep only the left half, then apply with a soft edge.
        edited = Image.new('L', (32, 32), 0)
        edited.paste(255, (0, 0, 16, 32))
        out = io.BytesIO()
        edited.save(out, 'PNG')
        self.tools.set_mask(item['id'], out.getvalue(), 'edited', 'alpha')
        url = self.app.apply_alpha({'id': item['id'], 'feather': 0})['url']
        result = Image.open(self.root / url.removeprefix('/'))
        self.assertEqual(result.mode, 'RGBA')
        self.assertEqual(result.getpixel((4, 4)), (0, 0, 255, 255))
        self.assertEqual(result.getpixel((28, 4))[3], 0)
        listed = [i for i in self.tools.public()['items'] if i.get('parent') == item['id']]
        self.assertEqual(listed[0]['op'], 'alpha')
        record = json.loads(
            (self.root / 'outputs' / listed[0]['path']).with_suffix('.json').read_text()
        )
        self.assertEqual(record['source']['tool_item'], item['id'])
        self.tools.remove([item['id']])
        self.assertFalse(list((self.root / 'data/tools/masks').glob(f'{item["id"]}*')))

    def test_result_of_a_gallery_asset_is_saved_beside_it_for_adoption(self):
        folder = self.root / 'outputs/W001/C001/001'
        folder.mkdir(parents=True)
        (folder / '005.png').write_bytes(png('red', size=(32, 32)))
        source = {
            'work_id': 'W001',
            'character_id': 'C001',
            'outfit_id': '001',
            'expression_id': '005',
            'category': 'nsfw',
            'expression_name': 'smile',
            'job_id': 'gen-1',
            'workflow': {'1': {}},
            'postprocessing': {'applied': False, 'source_image': None},
        }
        (folder / '005.json').write_text(json.dumps(source), encoding='utf-8')
        item = self.tools.add_gallery(['W001/C001/001/005.png'])['added'][0]
        mask = Image.new('L', (32, 32), 255)
        self.tools.set_mask(item['id'], mask, 'edited')
        url = self.app.apply_censor({'id': item['id'], 'treatment': 'color', 'color': '#000000'})[
            'url'
        ]
        self.assertEqual(url, '/outputs/W001/C001/001/005_censor.png')
        record = json.loads((folder / '005_censor.json').read_text(encoding='utf-8'))
        self.assertEqual(record['category'], 'nsfw')
        self.assertEqual(record['job_id'], 'gen-1')  # Still points at the generation.
        post = record['postprocessing']
        self.assertTrue(post['applied'])
        self.assertEqual((post['op'], post['source_image']), ('censor', 'W001/C001/001/005.png'))

        # The result is a new, unreviewed candidate for the same expression; a pass adopts it.
        reviews = self.app.review_store
        result = reviews.get_review('W001/C001/001/005_censor.png')
        self.assertEqual(result['expression_id'], '005')
        self.assertEqual(result['human_status'], 'unreviewed')
        reviews.review({'verdict': 'pass', 'items': [{'path': 'W001/C001/001/005_censor.png'}]})
        self.assertTrue(reviews.get_review('W001/C001/001/005_censor.png')['selected'])
        self.assertIsNotNone(reviews.human_acceptance_time(source))

        # A second pass on the result chains the history; uploads stay under _tools.
        child = [i for i in self.tools.public()['items'] if i.get('parent') == item['id']][0]
        self.tools.set_mask(child['id'], mask, 'edited', 'alpha')
        self.app.apply_alpha({'id': child['id']})
        chained = json.loads((folder / '005_censor_alpha.json').read_text(encoding='utf-8'))
        self.assertEqual(chained['postprocessing']['previous']['op'], 'censor')
        upload = self.tools.upload('u.png', png('blue', size=(32, 32)))['added'][0]
        self.tools.set_mask(upload['id'], mask, 'edited')
        url = self.app.apply_censor({'id': upload['id']})['url']
        self.assertTrue(url.startswith('/outputs/_tools/'), url)

    def test_zip_of_chosen_images_keeps_gallery_folders(self):
        for character in ('C001', 'C002'):
            folder = self.root / 'outputs/W001' / character / '001'
            folder.mkdir(parents=True)
            (folder / '005.png').write_bytes(png('red'))
        gallery = self.tools.add_gallery(['W001/C001/001/005.png', 'W001/C002/001/005.png'])
        first = self.tools.upload('a.png', png('blue'))['added'][0]
        second = self.tools.upload('a.png', png('green'))['added'][0]
        ids = [i['id'] for i in gallery['added']] + [first['id'], second['id'], first['id']]
        raw, name = self.tools.zip(ids)
        self.assertEqual(name, 'images-4.zip')
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(
                archive.namelist(),
                ['W001/C001/001/005.png', 'W001/C002/001/005.png', 'a.png', 'a_2.png'],
            )
            self.assertEqual(archive.read('a.png'), self.tools.image(first['id'])[0])
        with self.assertRaises(ValueError):
            self.tools.zip([])

    def test_tool_status_without_comfyui_is_still_json(self):
        from asset_studio.i18n import wire

        def offline(path, body=None, raw=False):
            raise RuntimeError('connection refused')

        self.app.comfy.request = offline
        for info in (self.app.tagger_info(), self.app.postprocess_info()):
            self.assertFalse(info['available'])
            self.assertIn('connection refused', info['error'])
            self.assertEqual(
                json.loads(json.dumps(wire(info)))['error']['params'],
                {'error': 'connection refused'},
            )

    def test_tag_export_drops_excluded_tags(self):
        from asset_studio import settings_api

        first = self.tools.upload('a.png', png('blue'))['added'][0]
        second = self.tools.upload('b.png', png('red'))['added'][0]
        untagged = self.tools.upload('c.png', png('green'))['added'][0]
        for item in (first, second):
            self.tools.set_tags(
                item['id'], {'tags': ['1girl', 'White_Background', 'smile'], 'model': 'm'}
            )
        with self.assertRaises(ValueError):
            settings_api.save(self.app, {'section': 'tags', 'values': {'exclude': 'solo'}})
        saved = settings_api.save(
            self.app, {'section': 'tags', 'values': {'exclude': [' white background ', '']}}
        )
        self.assertEqual(saved['values']['exclude'], ['white background'])
        self.assertEqual(self.app.tagger_info()['exclude'], ['white background'])

        ids = [first['id'], second['id'], untagged['id']]
        raw, name, kind = self.app.export_tags(ids, 'txt')
        self.assertEqual((name, kind), ('tags-2.zip', 'application/zip'))
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.namelist(), ['a.txt', 'b.txt'])
            self.assertEqual(archive.read('a.txt').decode(), '1girl, smile')
        raw, name, kind = self.app.export_tags(ids, 'json')
        data = json.loads(raw)
        self.assertEqual([row['file'] for row in data], ['a.png', 'b.png'])
        self.assertEqual(data[0]['tags'], ['1girl', 'smile'])
        with self.assertRaises(ValueError):
            self.app.export_tags([untagged['id']], 'txt')
        with self.assertRaises(ValueError):
            self.app.export_tags(ids, 'csv')

    def test_inpaint_redraws_an_enlarged_crop_and_pastes_it_back(self):
        from asset_studio.generation.workflow import validate_settings
        from asset_studio.tools.postprocess import check_options, crop_region

        # The region is the box plus padding, enlarged toward the generation area.
        self.assertEqual(
            crop_region((100, 100, 140, 120), (512, 512), 10, 256 * 256)[0], (90, 90, 150, 130)
        )
        region, size = crop_region((100, 100, 140, 120), (512, 512), 10, 1024 * 1024)
        self.assertEqual(size, (240, 160))  # Capped at 4x, multiples of 16.
        self.assertEqual(crop_region((0, 0, 512, 512), (512, 512), 0, 256 * 256)[1], (512, 512))

        item = self.tools.upload('pic.png', png('blue', size=(256, 256)))['added'][0]
        mask = Image.new('L', (256, 256), 0)
        mask.paste(255, (100, 100, 140, 140))
        self.tools.set_mask(item['id'], mask, 'edited', 'inpaint')
        comfy = FakeComfy('white')
        uploads = {}
        comfy.upload = lambda name, raw: uploads.setdefault(name, raw) and {'name': name}
        self.app.comfy = comfy
        settings = validate_settings(SETTINGS, CATALOG)
        job = {
            'id': 'j1',
            'tool_item': item['id'],
            'post_op': 'inpaint',
            'post_options': check_options('inpaint', {'grow': 0, 'feather': 0, 'padding': 20}, {}),
            'post_source': {'settings': settings, 'positive': 'p', 'negative': 'n', 'seed': 1},
            'post_prefix': 'AssetStudio',
        }
        nodes = self.app.post_graph(job)
        self.assertEqual(job['post_crop']['region'], [80, 80, 160, 160])
        crop_name = f'asset_studio_inpaint_{item["id"]}_crop.png'
        self.assertEqual(nodes['image']['inputs']['image'], crop_name)
        with Image.open(io.BytesIO(uploads[crop_name])) as crop:
            self.assertEqual(list(crop.size), job['post_crop']['size'])
            self.assertGreater(crop.width, 80)

        out = io.BytesIO()
        Image.new('RGB', tuple(job['post_crop']['size']), 'white').save(out, 'PNG')
        url, _ = self.app.save_post(job, out.getvalue(), nodes)
        result = Image.open(self.root / url.removeprefix('/'))
        self.assertEqual(result.size, (256, 256))
        self.assertEqual(result.getpixel((120, 120))[:3], (255, 255, 255))
        self.assertEqual(result.getpixel((90, 90))[:3], (0, 0, 255))  # Padding, not masked.
        self.assertEqual(result.getpixel((10, 10))[:3], (0, 0, 255))

        job['post_options'] = {**job['post_options'], 'area': 'full'}
        self.app.post_graph(job)
        self.assertNotIn('post_crop', job)


    def test_inpaint_keeps_the_mask_it_was_queued_with(self):
        from asset_studio.generation.workflow import validate_settings
        from asset_studio.tools.postprocess import check_options

        item = self.tools.upload('pic.png', png('blue', size=(256, 256)))['added'][0]
        chosen = Image.new('L', (256, 256), 0)
        chosen.paste(255, (100, 100, 140, 140))
        self.tools.set_mask(item['id'], chosen, 'edited', 'inpaint')
        self.app.comfy = FakeComfy('white')
        self.app.comfy.upload = lambda name, raw: {'name': name}
        job = {
            'id': 'j1',
            'kind': 'post',
            'status': 'running',
            'tool_item': item['id'],
            'post_op': 'inpaint',
            'post_options': check_options('inpaint', {'grow': 0, 'feather': 0, 'padding': 20}, {}),
            'post_source': {
                'settings': validate_settings(SETTINGS, CATALOG),
                'positive': 'p',
                'negative': 'n',
                'seed': 1,
            },
            'post_prefix': 'AssetStudio',
            'post_mask': self.tools.freeze_mask(item['id'], 'inpaint'),
        }
        nodes = self.app.post_graph(job)

        # The mask is moved elsewhere while ComfyUI works: the result still lands on the
        # area that was chosen, and the newly marked area is left alone.
        moved = Image.new('L', (256, 256), 0)
        moved.paste(255, (10, 10, 60, 60))
        self.tools.set_mask(item['id'], moved, 'edited', 'inpaint')
        out = io.BytesIO()
        Image.new('RGB', tuple(job['post_crop']['size']), 'white').save(out, 'PNG')
        url, _ = self.app.save_post(job, out.getvalue(), nodes)
        with Image.open(self.root / url.removeprefix('/')) as result:
            self.assertEqual(result.getpixel((120, 120))[:3], (255, 255, 255))
            self.assertEqual(result.getpixel((30, 30))[:3], (0, 0, 255))

        # Even with the image's mask deleted, the job's copy is still there.
        self.tools.mask_path(item['id'], 'inpaint').unlink()
        self.app.save_post(job, out.getvalue(), nodes)

        # A retry shares the copy; clearing the queue deletes it with the last user.
        job['status'] = 'failed'
        self.app.jobs = [job]
        self.app.retry('j1')
        retried = self.app.jobs[-1]
        self.assertEqual(retried['post_mask'], job['post_mask'])
        copy = self.tools.job_mask_path(job['post_mask'])
        self.app.remove_finished('j1')
        self.assertTrue(copy.is_file())
        retried['status'] = 'cancelled'
        self.app.remove_finished()
        self.assertFalse(copy.exists())


if __name__ == '__main__':
    unittest.main()
