"""GPU ownership: generation runs only while nobody else holds the GPU."""

import json
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_studio.app import Studio
from asset_studio.gpu_monitor import GpuMonitor


class GpuBrokerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.gpu = self.studio.gpu
        self.studio.jobs.append({'id': 'q1', 'status': 'queued'})

    def test_one_holder_at_a_time_and_generation_waits(self):
        self.assertTrue(self.gpu.generation_allowed())
        self.assertEqual(self.gpu.status()['label'], 'Image generation')
        self.assertTrue(self.gpu.acquire('validation', 'loading_vlm'))
        self.assertFalse(self.gpu.generation_allowed())
        self.assertFalse(self.gpu.acquire('comfy_control', 'stop'))
        self.assertTrue(self.gpu.acquire('validation', 'reviewing'))
        status = self.gpu.status()
        self.assertEqual((status['holder'], status['state_label']), ('validation', 'Reviewing'))
        self.gpu.release('comfy_control')  # Not the holder: no effect.
        self.assertFalse(self.gpu.generation_allowed())
        self.gpu.block('validation', 'unload not confirmed')
        self.assertEqual((self.gpu.state, self.gpu.error), ('blocked', 'unload not confirmed'))
        self.gpu.release('validation')
        self.assertTrue(self.gpu.generation_allowed())
        self.assertIsNone(self.gpu.error)

    def test_outside_reservation_needs_an_idle_queue_and_survives_restart(self):
        with self.assertRaises(ValueError):
            self.gpu.reserve({})
        self.studio.jobs.append({'id': 'r1', 'status': 'running'})
        with self.assertRaises(ValueError):
            self.gpu.reserve({'owner': 'LoRA training'})
        self.studio.jobs[-1]['status'] = 'completed'
        token = self.gpu.reserve({'owner': 'LoRA training'})['token']
        self.assertEqual(self.gpu.status()['label'], 'External work (LoRA training)')
        with self.assertRaises(ValueError):
            self.gpu.reserve({'owner': 'second tool'})
        self.assertFalse(self.studio.validation.process_ready())

        restarted = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.assertFalse(restarted.gpu.generation_allowed())
        with self.assertRaises(ValueError):
            restarted.gpu.release_reservation({'token': 'wrong'})
        restarted.gpu.release_reservation({'token': token})
        self.assertTrue(restarted.gpu.generation_allowed())
        again = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.assertTrue(again.gpu.generation_allowed())

    def test_stuck_reservation_can_be_forced_free(self):
        self.gpu.reserve({'owner': 'crashed tool'})
        self.gpu.release_reservation({'force': True})
        self.assertTrue(self.gpu.generation_allowed())
        self.assertEqual(self.gpu.release_reservation({})['holder'], None)

    def test_worker_starts_no_job_while_the_gpu_is_held(self):
        self.gpu.acquire('comfy_control', 'comfy_offline')
        calls = []
        self.studio.comfy.request = lambda *args, **kwargs: calls.append(args) or {}
        worker = threading.Thread(target=self.studio.worker)
        worker.start()
        time.sleep(1.3)
        self.studio.stop.set()
        worker.join(3)
        self.assertEqual(self.studio.jobs[0]['status'], 'queued')
        self.assertEqual(calls, [])


class GpuMonitorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.vram = (20000, 24564)
        self.programs = {'explorer.exe'}
        self.monitor = GpuMonitor(self.root, vram=lambda: self.vram, programs=lambda: self.programs)

    def configure(self, **settings):
        path = self.root / 'data/settings/gpu.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(settings), encoding='utf-8')
        self.monitor._cache = (0.0, None, set())

    def test_checks_are_off_without_a_settings_file(self):
        self.vram = (10, 24564)
        self.assertIsNone(self.monitor.check('generation'))
        self.assertEqual(self.monitor.snapshot(), {})

    def test_low_free_memory_and_watched_programs_hold_work_back(self):
        self.configure(min_free_vram_mb={'training': 18000}, watch_processes=['Game.exe'])
        self.assertIsNone(self.monitor.check('generation'))
        self.vram = (12000, 24564)
        self.monitor._cache = (0.0, None, set())
        self.assertIn('12,000 MB', self.monitor.check('training'))
        self.assertIsNone(self.monitor.check('generation'))
        self.programs = {'game.exe'}
        self.monitor._cache = (0.0, None, set())
        self.assertIn('Game.exe', self.monitor.check('generation'))
        self.assertEqual(self.monitor.snapshot(), {'vram_free_mb': 12000, 'vram_total_mb': 24564})

    def test_broker_reports_why_work_waits(self):
        self.configure(watch_processes=['Game.exe'])
        self.programs = {'game.exe'}
        studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        studio.gpu.monitor = self.monitor
        self.assertIsNotNone(studio.gpu.admit('generation'))
        self.assertEqual(studio.gpu.status()['waiting']['kind'], 'generation')
        self.programs = set()
        self.monitor._cache = (0.0, None, set())
        self.assertIsNone(studio.gpu.admit('generation'))
        self.assertIsNone(studio.gpu.status()['waiting'])


if __name__ == '__main__':
    unittest.main()
