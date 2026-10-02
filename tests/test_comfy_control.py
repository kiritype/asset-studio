import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_studio.app import Studio


class FakeProcess:
    def __init__(self, terminate_error=None):
        self.terminate_error = terminate_error
        self.terminated = False
        self.waited = False

    def poll(self):
        return 0 if self.terminated else None

    def terminate(self):
        if self.terminate_error:
            raise self.terminate_error
        self.terminated = True

    def wait(self, timeout=None):
        self.waited = True
        return 0


class ComfyControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root, 'http://127.0.0.1:8188', start_worker=False)
        self.control = self.studio.control

    def test_external_connection_cannot_be_started_stopped_or_restarted(self):
        self.studio.comfy.request = lambda path, **kwargs: (
            {'queue_running': [], 'queue_pending': []} if path == '/queue' else {'system': {}}
        )
        with patch('asset_studio.generation.control.subprocess.Popen') as launch:
            status = self.control.status()
            self.assertTrue(status['connected'])
            self.assertFalse(status['owned'])
            self.assertFalse(status['can_start'])
            self.assertFalse(status['can_stop'])
            self.assertFalse(status['can_restart'])
            for action in ('start', 'stop', 'restart'):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    self.control.control(action)
            launch.assert_not_called()
        self.assertTrue(self.studio.gpu.generation_allowed())

    def test_active_queue_refuses_setting_changes_without_touching_config(self):
        before = dict(self.control.config)
        self.studio.jobs = [{'status': 'running'}]
        with self.assertRaises(ValueError):
            self.control.save({'url': 'http://localhost:8189'})
        self.studio.jobs = [{'status': 'queued'}]
        with self.assertRaises(ValueError):
            self.control.save({'url': 'http://localhost:8189'})
        self.assertEqual(self.control.config, before)
        self.assertFalse(self.control.path.exists())

    def test_preview_disables_control_and_settings_even_with_valid_paths(self):
        preview = Studio(
            self.root / 'preview', 'http://127.0.0.1:8188', start_worker=False, preview=True
        )
        with patch('asset_studio.generation.control.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                preview.control.save({'url': 'http://localhost:8189'})
            for action in ('start', 'stop', 'restart'):
                with self.subTest(action=action), self.assertRaises(ValueError):
                    preview.control.control(action)
            launch.assert_not_called()
        self.assertFalse(preview.control.path.exists())

    def test_owned_stop_keeps_the_gpu_held_while_offline_and_user_pause(self):
        process = FakeProcess()
        self.control.process = process
        self.studio.paused = True
        self.studio.comfy.request = lambda path, **kwargs: (
            {'queue_running': [], 'queue_pending': []} if path == '/queue' else {'system': {}}
        )
        with (
            patch('asset_studio.generation.control.threading.Thread') as thread,
            patch('asset_studio.generation.control.subprocess.Popen') as launch,
        ):
            self.assertEqual(self.control.control('stop')['operation'], 'stop')
            self.assertFalse(self.studio.gpu.generation_allowed())
            self.assertTrue(self.studio.paused)
            thread.return_value.start.assert_called_once()
            self.control._run('stop')
            launch.assert_not_called()
        self.assertTrue(process.terminated)
        self.assertTrue(process.waited)
        self.assertFalse(self.studio.gpu.generation_allowed())
        self.assertTrue(self.studio.paused)
        self.assertIsNone(self.control.operation)
        self.assertIsNone(self.control.error)

    def test_failed_start_keeps_the_gpu_held_and_preserves_unpaused_queue_state(self):
        self.studio.paused = False
        self.control.config['python_path'] = str(self.root / 'missing-python.exe')
        self.control.config['comfy_path'] = str(self.root / 'missing-comfy')
        self.studio.comfy.request = lambda path, **kwargs: (_ for _ in ()).throw(
            RuntimeError('offline')
        )
        with (
            patch('asset_studio.generation.control.threading.Thread') as thread,
            patch('asset_studio.generation.control.subprocess.Popen') as launch,
        ):
            self.assertEqual(self.control.control('start')['operation'], 'start')
            self.assertFalse(self.studio.gpu.generation_allowed())
            thread.return_value.start.assert_called_once()
            self.control._run('start')
            launch.assert_not_called()
        self.assertFalse(self.studio.gpu.generation_allowed())
        self.assertFalse(self.studio.paused)
        self.assertIsNone(self.control.operation)
        self.assertIn('경로', self.control.error)

    def test_failed_owned_stop_releases_the_gpu_without_changing_pause(self):
        process = FakeProcess(terminate_error=RuntimeError('terminate failed'))
        self.control.process = process
        self.studio.paused = True
        self.studio.comfy.request = lambda path, **kwargs: (
            {'queue_running': [], 'queue_pending': []} if path == '/queue' else {'system': {}}
        )
        with (
            patch('asset_studio.generation.control.threading.Thread'),
            patch('asset_studio.generation.control.subprocess.Popen') as launch,
        ):
            self.control.control('stop')
            self.control._run('stop')
            launch.assert_not_called()
        self.assertTrue(self.studio.gpu.generation_allowed())
        self.assertTrue(self.studio.paused)
        self.assertEqual(self.control.error, 'terminate failed')
        self.assertIsNone(self.control.operation)


if __name__ == '__main__':
    unittest.main()
