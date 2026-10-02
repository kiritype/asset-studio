import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from asset_studio.app import Studio
from asset_studio.validation.vlm import LocalVLM, VLMError


class ValidationPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.studio = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.pipe = self.studio.validation
        self.pipe.settings = {'enabled': True, 'max_auto_regenerations': 10}
        self.pipe.vlm.config = {'enabled': True}
        self.studio.comfy.request = lambda path, body=None: (
            {'queue_running': [], 'queue_pending': []} if path == '/queue' else {}
        )
        self.pipe.vlm.load = lambda: None
        self.pipe.vlm.unload = lambda: None
        self.pipe.vlm._loaded_instances = lambda: []

    def source(self):
        relative = 'W001/C001/001/001.webp'
        path = self.root / 'outputs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (16, 16), 'white').save(path)
        snapshot = {
            'work_id': 'W001',
            'character_id': 'C001',
            'outfit_id': '001',
            'expression_id': '001',
            'expression_name': 'Pose',
            'category': 'sfw',
            'parts': {'appearance': 'blue eyes', 'outfit': 'white gloves'},
            'positive': 'blue eyes, white gloves',
            'negative': '',
            'settings': {'seed': 41, 'loras': [{'name': 'G001', 'strength': 0.8}]},
        }
        (path.with_suffix('.json')).write_text(
            json.dumps({**snapshot, 'job_id': 'original', 'postprocessing': {'applied': True}}),
            encoding='utf-8',
        )
        return relative

    def complete_job(self, job):
        # The generation worker has saved a distinct immutable output.
        relative = f'W001/C001/001/{job["id"]}.webp'
        path = self.root / 'outputs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (16, 16), 'white').save(path)
        (path.with_suffix('.json')).write_text(
            json.dumps({**job['snapshot'], 'job_id': job['id']}), encoding='utf-8'
        )
        self.studio.gallery._last_scan = 0
        job.update(status='completed', image_url='/outputs/' + relative)
        self.studio.persist()

    def grouped_job(self, ident, group):
        snapshot = {
            'work_id': 'W001',
            'character_id': group,
            'outfit_id': '001',
            'expression_id': ident,
            'expression_name': 'Pose',
            'category': 'sfw',
            'positive': 'white gloves',
            'negative': '',
            'settings': {'seed': 41},
            'execution_group': group,
        }
        return {
            'id': ident,
            'status': 'queued',
            'work_id': 'W001',
            'character_id': group,
            'outfit_id': '001',
            'expression_id': ident,
            'expression_name': 'Pose',
            'category': 'sfw',
            'seed': 41,
            'snapshot': snapshot,
            'execution_group': group,
            'review_requested': True,
        }

    def test_regenerate_without_vlm_review_queues_plain_jobs(self):
        self.pipe.settings = {'enabled': False, 'max_auto_regenerations': 10}
        path = self.source()
        result = self.pipe.manual_regenerate([{'path': path}])
        self.assertEqual((result['count'], result['reviewing'], result['rounds']), (1, False, []))
        self.assertEqual(self.pipe.rounds, [])
        job = self.studio.jobs[0]
        self.assertEqual(job['status'], 'queued')
        self.assertNotEqual(job['seed'], 41)
        self.assertNotIn('review_round_id', job)
        self.assertNotIn('review_round_id', job['snapshot'])
        self.assertEqual(job['snapshot']['source_generation_path'], path)
        self.assertEqual(
            self.pipe.public_settings(),
            {'enabled': False, 'max_auto_regenerations': 10, 'configured': True},
        )

    def test_dismiss_puts_away_rounds_without_live_work(self):
        live = self.grouped_job('live', 'C040')
        self.studio.jobs.append(live)
        self.pipe.register_jobs(self.studio.jobs)
        stale = [
            dict(self.pipe._round(self.grouped_job(name, 'C041')), status=status)
            for name, status in (
                ('a', 'needs_attention'),
                ('b', 'pending_review'),
                ('c', 'limit_reached'),
                ('d', 'awaiting_human'),
            )
        ]
        self.pipe.rounds.extend(stale)
        self.assertEqual(
            [r['stale'] for r in self.pipe.public_rounds()['rounds']],
            [False, False, True, False, False],
        )
        self.assertEqual(self.pipe.dismiss_rounds()['dismissed'], 4)
        self.assertEqual(
            [r['status'] for r in self.pipe.rounds], ['waiting_generation'] + ['dismissed'] * 4
        )
        self.assertEqual(self.pipe.rounds[1]['dismissed_from'], 'needs_attention')
        listed = self.pipe.public_rounds()
        self.assertEqual([r['source_job_id'] for r in listed['rounds']], ['live'])
        self.assertTrue(listed['enabled'])
        self.assertEqual(self.pipe.dismiss_rounds()['dismissed'], 0)
        self.assertIs(self.pipe.next_generation_job(), live)
        self.studio.gpu.acquire('validation', 'reviewing')
        with self.assertRaises(ValueError):
            self.pipe.dismiss_rounds()

    def test_group_validation_and_retry_finish_before_next_group(self):
        first = self.grouped_job('first', 'C040')
        second = self.grouped_job('second', 'C040')
        future = self.grouped_job('future', 'C041')
        self.studio.jobs.extend([first, second, future])
        self.pipe.register_jobs(self.studio.jobs)
        self.assertIs(self.pipe.next_generation_job(), first)
        self.complete_job(first)
        self.assertIs(self.pipe.next_generation_job(), second)
        self.complete_job(second)
        self.assertIsNone(self.pipe.next_generation_job())
        seen = []

        def review(path, snapshot):
            seen.append(snapshot['expression_id'])
            return {
                'verdict': 'fail'
                if snapshot['expression_id'] == 'first' and len(seen) == 1
                else 'pass',
                'evidence': 'visible evidence',
            }

        self.pipe.vlm.review = review
        self.assertTrue(self.pipe.process_ready())
        self.assertEqual(seen, ['first', 'second'])
        retry = self.studio.jobs[-1]
        self.assertEqual(retry['execution_group'], 'C040')
        self.assertEqual(retry['snapshot']['execution_group'], 'C040')
        self.assertIs(self.pipe.next_generation_job(), retry)
        self.complete_job(retry)
        self.assertTrue(self.pipe.process_ready())
        self.assertIs(self.pipe.next_generation_job(), future)

    def test_group_technical_attention_blocks_next_until_explicit_retry(self):
        first = self.grouped_job('first', 'C040')
        future = self.grouped_job('future', 'C041')
        self.studio.jobs.extend([first, future])
        self.pipe.register_jobs(self.studio.jobs)
        self.complete_job(first)
        self.pipe.vlm.review = lambda path, snapshot: {
            'verdict': 'error',
            'evidence': 'model failed',
        }
        for _ in range(3):
            self.assertTrue(self.pipe.process_ready())
        round_ = self.pipe.rounds[0]
        self.assertEqual(round_['status'], 'needs_attention')
        self.assertIsNone(self.pipe.next_generation_job())
        self.pipe.retry_validation([round_['id']])
        self.pipe.vlm.review = lambda path, snapshot: {
            'verdict': 'pass',
            'evidence': 'visible evidence',
        }
        self.assertTrue(self.pipe.process_ready())
        self.assertIs(self.pipe.next_generation_job(), future)

    def test_group_uncertain_quality_verdict_allows_next_group(self):
        first = self.grouped_job('first', 'C040')
        future = self.grouped_job('future', 'C041')
        self.studio.jobs.extend([first, future])
        self.pipe.register_jobs(self.studio.jobs)
        self.complete_job(first)
        self.pipe.vlm.review = lambda path, snapshot: {
            'verdict': 'uncertain',
            'evidence': 'occluded detail',
        }
        self.assertTrue(self.pipe.process_ready())
        self.assertEqual(self.pipe.rounds[0]['status'], 'needs_attention')
        self.assertIs(self.pipe.next_generation_job(), future)

    def test_older_ungrouped_attention_does_not_block_new_group(self):
        older = {
            'id': 'older',
            'status': 'needs_attention',
            'combo': ('W001', 'C002', '001', 'sfw', 'old'),
            'source_job_id': 'older',
            'current_job_id': 'older',
            'attempts': [],
            'error': 'old failure',
        }
        self.pipe.rounds.append(older)
        future = self.grouped_job('future', 'C040')
        self.studio.jobs.append(future)
        self.pipe.register_jobs([future])
        self.assertIs(self.pipe.next_generation_job(), future)

    def test_retry_validation_preserves_output_and_counters(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        job = self.studio.jobs[-1]
        self.complete_job(job)
        r = self.pipe.rounds[0]
        r.update(status='needs_attention', error='empty response', technical_errors=2)
        before = json.dumps(self.studio.jobs, sort_keys=True)
        with self.assertRaises(ValueError):
            self.pipe.retry_validation([r['id'], 'absent'])
        self.assertEqual(r['status'], 'needs_attention')
        self.studio.paused = True
        with self.assertRaises(ValueError):
            self.pipe.retry_validation([r['id']])
        self.studio.paused = False
        self.pipe.retry_validation([r['id']])
        self.assertEqual(r['status'], 'pending_review')
        self.assertEqual(r['technical_errors'], 2)
        self.assertEqual(r['regenerations'], 0)
        self.assertEqual(r['validation_retries'][0]['previous_error'], 'empty response')
        self.assertEqual(before, json.dumps(self.studio.jobs, sort_keys=True))
        with self.assertRaises(ValueError):
            self.pipe.retry_validation([r['id']])

    def test_manual_round_new_seed_snapshot_and_duplicate_guard(self):
        path = self.source()
        first = self.pipe.manual_regenerate([{'path': path}])['rounds'][0]
        job = self.studio.jobs[-1]
        self.assertEqual(first['round_number'], 1)
        self.assertEqual(first['regenerations'], 0)
        self.assertNotEqual(job['seed'], 41)
        self.assertEqual(job['snapshot']['settings']['loras'], [{'name': 'G001', 'strength': 0.8}])
        self.assertEqual(job['snapshot']['positive'], 'blue eyes, white gloves')
        self.assertEqual(job['snapshot']['source_generation_path'], path)
        with self.assertRaises(ValueError):
            self.pipe.manual_regenerate([{'path': path}])
        job['status'] = 'cancelled'
        self.pipe.reconcile()
        second = self.pipe.manual_regenerate([{'path': path}])['rounds'][0]
        self.assertEqual(second['round_number'], 2)
        self.assertEqual(second['regenerations'], 0)

    def test_old_human_pass_does_not_stop_fresh_manual_round(self):
        path = self.source()
        self.studio.review_store.review({'items': [{'path': path}], 'verdict': 'pass'})
        round_ = self.pipe.manual_regenerate([{'path': path}])['rounds'][0]
        self.assertFalse(
            self.pipe._human_accepted(round_),
            (self.studio.review_store.human_acceptance_time(round_['combo']), round_['created_at']),
        )
        self.assertEqual(self.pipe.rounds[0]['status'], 'waiting_generation')
        self.studio.review_store.review({'items': [{'path': path}], 'verdict': 'pass'})
        self.pipe.human_review_changed()
        self.assertEqual(self.pipe.rounds[0]['status'], 'human_accepted')
        self.assertEqual(self.studio.jobs[0]['status'], 'cancelled')

    def test_two_versions_of_same_combo_are_rejected_atomically(self):
        path = self.source()
        second = 'W001/C001/001/001_002.webp'
        second_file = self.root / 'outputs' / second
        Image.new('RGB', (16, 16), 'blue').save(second_file)
        second_file.with_suffix('.json').write_bytes(
            (self.root / 'outputs' / path).with_suffix('.json').read_bytes()
        )
        with self.assertRaises(ValueError):
            self.pipe.manual_regenerate([{'path': path}, {'path': second}])
        self.assertEqual(self.studio.jobs, [])
        self.assertEqual(self.pipe.rounds, [])

    def test_technical_retry_keeps_seed_and_quality_count(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        original = self.studio.jobs[-1]
        original['status'] = 'failed'
        self.pipe.reconcile()
        self.studio.retry(original['id'])
        retried = self.studio.jobs[-1]
        self.assertNotEqual(retried['id'], original['id'])
        self.assertEqual(retried['seed'], original['seed'])
        self.assertEqual(retried['snapshot'], original['snapshot'])
        self.assertEqual(self.pipe.rounds[0]['regenerations'], 0)
        self.assertEqual(self.pipe.rounds[0]['current_job_id'], retried['id'])

    def test_fresh_save_result_replaces_source_identity_fields(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        fresh = self.studio.jobs[-1]
        fresh['snapshot'].update(
            job_id='old',
            prompt_id='old-prompt',
            created_at='old-time',
            workflow={'old': True},
            image_size=[999, 999],
            postprocessing={'applied': True, 'source_image': path},
        )
        image = io.BytesIO()
        Image.new('RGB', (16, 16), 'white').save(image, format='PNG')
        url = self.studio.save_result(fresh, image.getvalue(), {'new': True}, 'new-prompt')
        metadata = self.studio.gallery.metadata(url.removeprefix('/outputs/'))
        self.assertEqual(metadata['job_id'], fresh['id'])
        self.assertEqual(metadata['prompt_id'], 'new-prompt')
        self.assertEqual(metadata['workflow'], {'new': True})
        self.assertEqual(metadata['image_size'], [16, 16])
        self.assertEqual(metadata['postprocessing'], {'applied': False, 'source_image': None})
        self.assertEqual(metadata['source_generation_path'], path)

    def test_fail_regenerates_ten_times_then_stops(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        self.pipe.vlm.review = lambda path, snap: {
            'verdict': 'fail',
            'evidence': 'Visible mismatch',
        }
        for attempt in range(11):
            current = self.studio.jobs[-1]
            self.complete_job(current)
            self.assertTrue(self.pipe.process_ready())
            round_ = self.pipe.rounds[0]
            self.assertEqual(round_['regenerations'], min(attempt + 1, 10))
        self.assertEqual(round_['status'], 'limit_reached')
        self.assertEqual(len(round_['attempts']), 11)
        self.assertEqual(len(self.studio.jobs), 11)
        self.assertEqual(self.pipe.rounds[0]['max_auto_regenerations'], 10)

    def test_uncertain_and_technical_errors_do_not_regenerate(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        self.complete_job(self.studio.jobs[-1])
        self.pipe.vlm.review = lambda path, snap: {
            'verdict': 'uncertain',
            'evidence': 'Cannot see gloves',
        }
        self.pipe.process_ready()
        self.assertEqual(self.pipe.rounds[0]['status'], 'needs_attention')
        self.assertEqual(self.pipe.rounds[0]['regenerations'], 0)
        self.assertEqual(len(self.studio.jobs), 1)

    def test_pause_during_review_does_not_enqueue_regeneration(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        self.complete_job(self.studio.jobs[-1])

        def review(image, snapshot):
            with self.studio.lock:
                self.studio.paused = True
                self.studio.persist()
            return {'verdict': 'fail', 'evidence': 'Visible mismatch'}

        self.pipe.vlm.review = review
        self.pipe.process_ready()
        self.assertEqual(self.pipe.rounds[0]['status'], 'needs_attention')
        self.assertEqual(len(self.studio.jobs), 1)

    def test_unload_failure_blocks_generation(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        self.complete_job(self.studio.jobs[-1])
        self.pipe.vlm.review = lambda image, snapshot: {
            'verdict': 'pass',
            'evidence': 'Visible match',
        }
        self.pipe.vlm.owned = True

        def fail_unload():
            raise VLMError('unload failed')

        self.pipe.vlm.unload = fail_unload
        with self.assertRaises(VLMError):
            self.pipe.process_ready()
        self.assertFalse(self.studio.gpu.generation_allowed())
        self.assertEqual((self.studio.gpu.holder, self.studio.gpu.state), ('validation', 'blocked'))
        self.assertIn('unload failed', self.studio.gpu.error)

    def test_verified_empty_gpu_recovers_blocked_unload(self):
        self.studio.gpu.acquire('validation', 'unloading_vlm')
        self.studio.gpu.block('validation', 'unload uncertain')
        self.pipe.vlm.owned = True
        self.pipe.vlm.test = lambda: {'ok': True, 'loaded': False}
        self.assertEqual(self.pipe.test_connection()['loaded'], False)
        self.assertIsNone(self.studio.gpu.holder)
        self.assertTrue(self.studio.gpu.generation_allowed())

    def test_human_pass_during_review_stops_auto_retry(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        self.complete_job(self.studio.jobs[-1])

        def review(image, snapshot):
            self.studio.review_store.review({'items': [{'path': path}], 'verdict': 'pass'})
            self.pipe.human_review_changed()
            return {'verdict': 'fail', 'evidence': 'Visible mismatch'}

        self.pipe.vlm.review = review
        self.pipe.process_ready()
        self.assertEqual(self.pipe.rounds[0]['status'], 'human_accepted')
        self.assertEqual(len(self.studio.jobs), 1)

    def test_restart_does_not_replay_uncertain_switch(self):
        path = self.source()
        self.pipe.manual_regenerate([{'path': path}])
        self.pipe.rounds[0]['status'] = 'switching'
        self.pipe.persist()
        restarted = Studio(self.root, 'http://127.0.0.1:1', start_worker=False)
        self.assertTrue(restarted.paused)
        self.assertEqual(restarted.validation.rounds[0]['status'], 'needs_attention')
        self.assertEqual(len(restarted.jobs), 1)

    def test_external_loaded_model_blocks_generation(self):
        self.pipe.vlm._loaded_instances = lambda: [{'identifier': 'someone-else'}]
        with self.assertRaises(VLMError):
            self.pipe.ensure_generation_safe()

    def test_initial_batch_49_rounds_snapshot_limit(self):
        jobs = []
        for number in range(1, 50):
            jobs.append(
                {
                    'id': f'initial-{number}',
                    'work_id': 'W001',
                    'character_id': 'C001',
                    'outfit_id': '001',
                    'category': 'sfw',
                    'expression_id': f'{number:03d}',
                    'review_requested': True,
                    'status': 'queued',
                }
            )
        self.pipe.register_jobs(jobs)
        self.assertEqual(len(self.pipe.rounds), 49)
        self.pipe.settings['max_auto_regenerations'] = 0
        self.assertTrue(all(r['max_auto_regenerations'] == 10 for r in self.pipe.rounds))

    def test_bad_model_output_never_passes(self):
        client = LocalVLM(self.root)
        client.config = {'enabled': True, 'loaded_marker': 'ours'}
        client.is_loaded = lambda: True
        relative = self.source()
        with patch('asset_studio.validation.vlm.build_opener') as build:
            from io import BytesIO

            response = BytesIO(
                json.dumps(
                    {
                        'choices': [
                            {
                                'finish_reason': 'stop',
                                'message': {
                                    'content': '{"verdict":"pass",'
                                    '"evidence":"Missing white gloves"}'
                                },
                            }
                        ]
                    }
                ).encode()
            )
            build.return_value.open.return_value = response
            client._value = lambda config, key: 'http://127.0.0.1:1' if key == 'url' else 'model'
            result = client.review(
                self.root / 'outputs' / relative,
                {'parts': {'outfit': 'white gloves'}, 'positive': 'white gloves'},
            )
        self.assertEqual(result['verdict'], 'uncertain')


if __name__ == '__main__':
    unittest.main()
