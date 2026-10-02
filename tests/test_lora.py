"""LoRA datasets, training runs (with a fake trainer) and the LoRA registry."""

import io
import json
import sys
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixtures import request, seed_library

from asset_studio.app import Studio
from asset_studio.library.service import ConflictError
from asset_studio.lora import records

CATALOG = {
    'connected': True,
    'models': ['model'],
    'text_encoders': ['clip'],
    'vaes': ['vae'],
    'clip_types': ['stable_diffusion'],
    'samplers': ['euler'],
    'schedulers': ['simple'],
    'loras': [],
}
FAKE_TASKS = """
import os, pathlib, sys
pattern = os.environ['PREPROCESS_PATH_PATTERN']
images = list(pathlib.Path('image_dataset').glob(pattern.replace('/*', '/*.png')))
sys.exit(0 if images else 3)
"""
FAKE_TRAIN = """
import argparse, json, pathlib, sys, time
p = argparse.ArgumentParser()
for name in ('--method', '--preset', '--output_name', '--path_pattern', '--learning_rate',
             '--max_train_epochs', '--save_every_n_epochs', '--checkpointing_epochs',
             '--progress_jsonl'):
    p.add_argument(name)
a = p.parse_args()
behaviour = pathlib.Path('behaviour.txt').read_text().strip()
if behaviour == 'fail':
    sys.exit(1)
progress = pathlib.Path(a.progress_jsonl)
progress.parent.mkdir(parents=True, exist_ok=True)
epochs, every = int(a.max_train_epochs), int(a.save_every_n_epochs)
with progress.open('w') as out:
    start = {'ev': 'run_start', 'total_steps': epochs * 2, 'total_epochs': epochs}
    out.write(json.dumps(start) + '\\n')
    out.write(json.dumps({'ev': 'step', 'global_step': 2, 'epoch': 1, 'loss/average': 0.07}))
    out.write('\\n')
time.sleep(float(behaviour or 0))
folder = pathlib.Path('output/ckpt') / a.output_name
folder.mkdir(parents=True, exist_ok=True)
for epoch in range(every, epochs, every):
    (folder / f'{a.output_name}-{epoch:06d}.safetensors').write_bytes(b'lora')
(folder.parent / f'{a.output_name}.safetensors').write_bytes(b'final')
with progress.open('a') as out:
    out.write(json.dumps({'ev': 'run_end', 'status': 'ok', 'error': None}) + '\\n')
"""


def picture(color):
    data = io.BytesIO()
    Image.new('RGB', (32, 32), color).save(data, 'WEBP')
    return data.getvalue()


class LoraTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.trainer = self.root / 'trainer'
        self.trainer.mkdir()
        (self.trainer / 'tasks.py').write_text(textwrap.dedent(FAKE_TASKS), encoding='utf-8')
        (self.trainer / 'train.py').write_text(textwrap.dedent(FAKE_TRAIN), encoding='utf-8')
        self.behaviour('0')
        self.lora_dir = self.root / 'comfy-loras'
        self.lora_dir.mkdir()
        # A prepared trainer install: patched preprocess script and the base-model files.
        tasks = self.trainer / 'scripts' / 'tasks'
        tasks.mkdir(parents=True)
        (tasks / 'preprocess.py').write_text('x = 1  # asset-studio patch\n', encoding='utf-8')
        (self.trainer / 'configs').mkdir()
        (self.trainer / 'configs' / 'presets.toml').write_text(
            '[default]\ntorch_compile = true\n', encoding='utf-8'
        )
        models = self.root / 'models'
        models.mkdir()
        for name in ('base.safetensors', 'te.safetensors', 'vae.safetensors'):
            (models / name).write_bytes(b'weights')
        self.bases = {
            'official': {
                'dit': str(models / 'base.safetensors'),
                'text_encoder': str(models / 'te.safetensors'),
                'vae': str(models / 'vae.safetensors'),
            }
        }
        settings = self.root / 'data/settings/lora_pipeline.json'
        settings.parent.mkdir(parents=True)
        settings.write_text(
            json.dumps(
                {
                    'trainer_dir': str(self.trainer),
                    'trainer_python': sys.executable,
                    'lora_dir': str(self.lora_dir),
                    'bases': self.bases,
                }
            ),
            encoding='utf-8',
        )
        self.studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.studio.comfy.request = lambda *args, **kwargs: {}
        seed_library(self.studio.store)
        self.paths = [
            self.generate(expression, color)
            for expression, color in (('001', 'white'), ('002', 'red'), ('001', 'blue'))
        ]
        self.studio.gallery._last_scan = 0
        self.studio.review_store.review(
            {'items': [{'path': self.paths[0]}, {'path': self.paths[1]}], 'verdict': 'pass'}
        )
        self.who = {'work_id': 'W001', 'character_id': 'C001'}

    def behaviour(self, value):
        (self.trainer / 'behaviour.txt').write_text(value, encoding='utf-8')

    def generate(self, expression, color):
        job = self.studio.enqueue(
            request(expressions=[{'id': expression}], settings={'seed': 1}),
            _catalog=CATALOG,
            _prepare_only=True,
        )[0]
        url = self.studio.save_result(job, picture(color), {}, 'prompt')
        return url.removeprefix('/outputs/')

    def build(self, **changes):
        from asset_studio.lora import datasets

        return datasets.build(self.studio, {**self.who, 'outfit_set_id': '001', **changes})

    def wait_for(self, run_id, states=('done', 'failed', 'cancelled'), timeout=30):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            run = self.studio.lora.get('W001', 'C001', run_id)
            if run['status'] in states:
                return run
            time.sleep(0.1)
        self.fail(f'run stayed {run["status"]}')

    def test_dataset_takes_adopted_images_and_keeps_edited_captions(self):
        from asset_studio.lora import datasets

        pool = datasets.candidates(self.studio, 'W001', 'C001', '001')
        selected = {item['path']: item['selected'] for item in pool}
        self.assertEqual([selected[path] for path in self.paths], [True, True, False])
        saved = self.build()['entity']
        self.assertEqual(saved['id'], 'D001')
        self.assertEqual(saved['triggers'], {'character': 'w001_c001', 'outfit': 'w001_c001_001'})
        self.assertEqual([item['path'] for item in saved['items']], self.paths[:2])
        self.assertTrue(
            saved['items'][0]['caption'].startswith('safe, 1girl, w001_c001, w001_c001_001')
        )
        dataset_path = records.dataset_file(self.studio.store, 'W001', 'C001', 'D001')
        stored = json.loads(dataset_path.read_text(encoding='utf-8'))
        stored['items'][0].update(caption='hand written', caption_edited=True)
        dataset_path.write_text(json.dumps(stored), encoding='utf-8')
        rebuilt = self.build(id='D001', paths=self.paths)['entity']
        self.assertEqual(len(rebuilt['items']), 3)
        self.assertEqual(rebuilt['items'][0]['caption'], 'hand written')
        renamed = datasets.recaption(
            self.studio,
            {
                **self.who,
                'id': 'D001',
                'triggers': {'character': 'hero', 'outfit': 'hero_coat'},
                'expected_revision': self.studio.library.revision(dataset_path, 'dataset'),
            },
        )['entity']
        self.assertEqual(renamed['items'][0]['caption'], 'hand written')
        self.assertIn('hero_coat', renamed['items'][1]['caption'])
        with self.assertRaises(ValueError):
            self.build(paths=['W001/C001/001/404.webp'])
        with self.assertRaises(ConflictError):
            datasets.recaption(self.studio, {**self.who, 'id': 'D001', 'expected_revision': 'old'})

    def test_training_run_holds_the_gpu_and_registers_epochs(self):
        self.build()
        self.behaviour('1')
        run = self.studio.lora.start(
            {**self.who, 'dataset_id': 'D001', 'params': {'epochs': 30, 'save_every': 10}}
        )['run']
        self.assertEqual((run['id'], run['output_name']), ('R001', 'w001_c001_001_r001'))
        self.wait_for('R001', states=('training',))
        self.assertEqual(self.studio.gpu.holder, 'training')
        self.assertFalse(self.studio.gpu.generation_allowed())
        with self.assertRaises(ValueError):
            self.studio.lora.start({**self.who, 'dataset_id': 'D001'})
        finished = self.wait_for('R001')
        self.assertEqual(finished['status'], 'done', finished.get('error'))
        self.assertEqual([o['epoch'] for o in finished['outputs']], [10, 20, 30])
        self.assertTrue((self.lora_dir / 'w001_c001_001_r001-e30.safetensors').is_file())
        self.assertEqual(finished['progress']['finished'], 'ok')
        self.assertTrue(self.studio.gpu.generation_allowed())
        exported = sorted(
            p.name for p in (self.trainer / 'image_dataset/w001_c001_001_r001').iterdir()
        )
        self.assertEqual(len(exported), 4)  # Two images, each with a caption file.

        entry = self.studio.lora.register({**self.who, 'run_id': 'R001', 'epoch': 20})['entity']
        self.assertEqual(
            (entry['id'], entry['scope'], entry['auto_apply']),
            ('w001_c001_001_r001-e20', 'character', False),
        )
        self.assertEqual(entry['origin']['epoch'], 20)
        path = records.lora_file(self.studio.store, entry['id'])
        revision = self.studio.library.revision(path, 'lora')
        shared = self.studio.library.save(
            {
                'kind': 'lora',
                'expected_revision': revision,
                'payload': {**entry, 'scope': 'global', 'strength': 0.8},
            }
        )
        self.assertEqual(shared['entity']['scope'], 'global')
        with self.assertRaises(ValueError):
            self.studio.library.save(
                {
                    'kind': 'lora',
                    'expected_revision': shared['revision'],
                    'payload': {**entry, 'origin': {'work_id': 'W002'}},
                }
            )
        trash = self.studio.library.delete(
            {'kind': 'lora', 'id': entry['id'], 'expected_revision': shared['revision']}
        )['trash_id']
        self.assertEqual(records.list_loras(self.studio.store), [])
        self.studio.library.restore(trash)
        self.assertEqual(records.list_loras(self.studio.store)[0]['scope'], 'global')

    def save_lora(self, ident, **fields):
        payload = {
            'id': ident,
            'file': rf'anima\{ident}.safetensors',
            'origin': {'work_id': 'W001', 'character_id': 'C001', 'outfit_set_id': '001'},
            'scope': 'character',
            'triggers': {'character': f'{ident}_trigger'},
            **fields,
        }
        return records.save_lora(self.studio.store, payload)

    def test_automatic_loras_follow_character_outfit_and_family(self):
        self.save_lora('a', auto_apply=True, strength=0.8)
        self.save_lora('b', auto_apply=True)  # Same character: turns "a" off.
        auto = {r['id']: r['auto_apply'] for r in records.list_loras(self.studio.store)}
        self.assertEqual(auto, {'a': False, 'b': True})
        self.save_lora('c', auto_apply=True, apply_to='outfit')  # Its own slot.
        self.save_lora('s', auto_apply=True, model_family='sdxl', apply_to='outfit')
        with self.assertRaises(ValueError):
            self.save_lora('x', apply_to='everything')

        result = self.studio.compose(request())
        self.assertEqual([lora['id'] for lora in result['auto_loras']], ['b', 'c'])
        self.assertTrue(result['parts']['appearance'].startswith('b_trigger, c_trigger, '))
        self.assertEqual(self.studio.compose(request(auto_lora=False))['auto_loras'], [])
        auto = {r['id']: r['auto_apply'] for r in records.list_loras(self.studio.store)}
        self.assertEqual(auto, {'a': False, 'b': True, 'c': True, 's': True})
        sdxl = self.studio.compose(request(settings={'family': 'sdxl'}))
        self.assertEqual([lora['id'] for lora in sdxl['auto_loras']], ['s'])

        catalog = {**CATALOG, 'loras': [r'anima\b.safetensors']}
        with self.assertRaises(ValueError):  # c is not installed in ComfyUI.
            self.studio.enqueue(request(), _catalog=catalog, _prepare_only=True)
        catalog['loras'].append(r'anima\c.safetensors')
        job = self.studio.enqueue(request(), _catalog=catalog, _prepare_only=True)[0]
        loras = job['snapshot']['settings']['loras']
        self.assertEqual(
            [(lora['name'], lora['auto']) for lora in loras],
            [
                (r'anima\b.safetensors', 'b'),
                (r'anima\c.safetensors', 'c'),
            ],
        )

    def test_trainer_is_prepared_from_settings(self):
        from asset_studio.lora import trainer_setup

        self.build()
        self.studio.lora.start({**self.who, 'dataset_id': 'D001'})
        self.wait_for('R001')
        presets = (self.trainer / 'configs' / 'presets.toml').read_text(encoding='utf-8')
        self.assertIn('[default]', presets)
        self.assertIn('[asset_studio_base]', presets)
        self.assertIn('base.safetensors', presets)
        self.assertEqual(presets.count(trainer_setup.BLOCK_START), 1)
        methods = sorted(p.name for p in (self.trainer / 'configs' / 'methods').iterdir())
        self.assertEqual(methods, ['asset_studio_lora.toml', 'asset_studio_tlora.toml'])
        # Running again replaces the block instead of adding a second one.
        trainer_setup.write_presets(self.trainer / 'configs' / 'presets.toml', {})
        presets = (self.trainer / 'configs' / 'presets.toml').read_text(encoding='utf-8')
        self.assertNotIn('[asset_studio_base]', presets)
        self.assertIn('[default]', presets)

        from asset_studio.lora.trainer import options as lora_options

        options = lora_options(self.root)
        self.assertEqual([b['id'] for b in options['bases']], ['official'])

        (self.trainer / 'scripts' / 'tasks' / 'preprocess.py').write_text('x = 1\n')
        with self.assertRaises(ValueError):
            self.studio.lora.start({**self.who, 'dataset_id': 'D001'})

    def test_failed_and_cancelled_runs_give_the_gpu_back(self):
        self.build()
        self.behaviour('fail')
        self.studio.lora.start({**self.who, 'dataset_id': 'D001'})
        failed = self.wait_for('R001')
        self.assertEqual(failed['status'], 'failed')
        self.assertIn('exit code 1', failed['error'])
        self.assertTrue(self.studio.gpu.generation_allowed())
        self.behaviour('30')
        self.studio.lora.start({**self.who, 'dataset_id': 'D001'})
        self.wait_for('R002', states=('training',))
        time.sleep(0.5)
        self.studio.lora.cancel({**self.who, 'run_id': 'R002'})
        self.assertEqual(self.wait_for('R002')['status'], 'cancelled')
        self.assertTrue(self.studio.gpu.generation_allowed())

    def test_a_running_image_delays_training_and_restart_marks_runs_interrupted(self):
        self.build()
        self.studio.jobs.append({'id': 'busy', 'status': 'running'})
        self.studio.lora.start({**self.who, 'dataset_id': 'D001'})
        time.sleep(0.5)
        self.assertEqual(self.studio.lora.get('W001', 'C001', 'R001')['status'], 'waiting_gpu')
        self.assertTrue(self.studio.gpu.generation_allowed())
        restarted = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.assertEqual(restarted.lora.get('W001', 'C001', 'R001')['status'], 'interrupted')
        self.studio.lora.cancel({**self.who, 'run_id': 'R001'})
        self.assertEqual(self.wait_for('R001', states=('cancelled',))['status'], 'cancelled')


if __name__ == '__main__':
    unittest.main()
