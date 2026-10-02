import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from asset_studio.gallery.listing import Gallery
from asset_studio.gallery.reviews import ReviewStore


class ReviewStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gallery = Gallery(self.root)
        self.store = ReviewStore(self.root, self.gallery)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, expression='001', version='', category='sfw', content=b'image'):
        relative = f'W001/C001/001/{expression}{version}.webp'
        path = self.root / 'outputs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        path.with_suffix('.json').write_text(
            json.dumps({'category': category, 'expression_id': expression}), encoding='utf-8'
        )
        self.gallery._last_scan = 0
        return relative

    def pass_one(self, path):
        return self.store.review(
            {'items': [{'path': path, 'sha256': self.store.sha256(path)}], 'verdict': 'pass'}
        )

    def test_reversible_one_selected_per_combo_and_human_priority(self):
        first = self.add(content=b'first')
        second = self.add(version='_002', content=b'second')
        baseline = self.store.human_revision()
        self.pass_one(first)
        first_revision = self.store.human_acceptance_revision(('W001', 'C001', '001', 'sfw', '001'))
        self.assertGreater(first_revision, baseline)
        self.store.record_auto(first, 'fail', 'model disagrees')
        self.assertTrue(self.store.get_review(first)['selected'])
        self.assertEqual(self.store.get_review(first)['human_status'], 'pass')
        self.assertTrue(self.store.is_human_accepted(('W001', 'C001', '001', 'sfw', '001')))
        accepted_at = self.store.human_acceptance_time(('W001', 'C001', '001', 'sfw', '001'))
        self.assertIsInstance(accepted_at, str)
        state = json.loads((self.root / 'data/state/reviews.json').read_text())
        self.assertEqual(
            accepted_at, state['records'][first + '\0' + self.store.sha256(first)]['reviewed_at']
        )
        self.pass_one(second)
        self.assertEqual(self.store.get_review(first)['human_status'], 'pass')
        self.assertFalse(self.store.get_review(first)['selected'])
        self.assertTrue(self.store.get_review(second)['selected'])
        self.assertIsInstance(
            self.store.human_acceptance_time(('W001', 'C001', '001', 'sfw', '001')), str
        )
        self.assertGreater(
            self.store.human_acceptance_revision(('W001', 'C001', '001', 'sfw', '001')),
            first_revision,
        )
        self.store.review({'items': [{'path': second}], 'verdict': 'unreviewed'})
        self.assertFalse(self.store.get_review(second)['selected'])
        self.assertEqual(self.store.get_review(second)['human_status'], 'unreviewed')
        self.assertFalse(self.store.is_human_accepted(('W001', 'C001', '001', 'sfw', '001')))
        self.assertIsNone(self.store.human_acceptance_time(('W001', 'C001', '001', 'sfw', '001')))
        self.assertIsNone(
            self.store.human_acceptance_revision(('W001', 'C001', '001', 'sfw', '001'))
        )
        self.assertGreaterEqual(
            len(json.loads((self.root / 'data/state/reviews.json').read_text())['history']), 3
        )
        reopened = ReviewStore(self.root, self.gallery)
        self.assertEqual(reopened.get_review(first)['human_status'], 'pass')

    def test_bulk_is_atomic_and_uses_expected_hash(self):
        first = self.add('001')
        second = self.add('002')
        before = self.store.sha256(first)
        (self.root / 'outputs' / second).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Image changed'):
            self.store.review(
                {
                    'items': [
                        {'path': first, 'sha256': before},
                        {'path': second, 'sha256': '0' * 64},
                    ],
                    'verdict': 'pass',
                }
            )
        self.assertEqual(self.store.get_review(first)['human_status'], 'unreviewed')
        self.assertFalse((self.root / 'data/state/reviews.json').exists())
        self.store.review({'items': [{'path': first}, {'path': second}], 'verdict': 'fail'})
        self.assertEqual(self.gallery.list({'human_status': ['fail']})['total'], 2)

    def test_identity_changes_with_file_and_invalid_paths(self):
        first = self.add()
        self.pass_one(first)
        (self.root / 'outputs' / first).write_bytes(b'replacement')
        self.assertEqual(self.store.get_review(first)['human_status'], 'unreviewed')
        self.assertFalse(self.store.get_review(first)['selected'])
        self.assertIsNone(self.store.human_acceptance_time(('W001', 'C001', '001', 'sfw', '001')))
        self.assertIsNone(
            self.store.human_acceptance_revision(('W001', 'C001', '001', 'sfw', '001'))
        )
        with self.assertRaisesRegex(ValueError, 'Selected image changed'):
            self.store.plan_and_zip({'filters': {'category': 'sfw'}, 'allow_partial': True})
        for bad in (
            '../outside.webp',
            'W001/C001/001/../../outside.webp',
            'W001/C001/001/001.json',
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.store.review({'items': [{'path': bad}], 'verdict': 'pass'})
        outside = self.root / 'outside.webp'
        outside.write_bytes(b'outside')
        link = self.root / 'outputs/W001/C001/001/002.webp'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            return
        with self.assertRaises(ValueError):
            self.store.review({'items': [{'path': 'W001/C001/001/002.webp'}], 'verdict': 'pass'})

    def test_selected_filter_and_latest_are_separate(self):
        first = self.add(content=b'one')
        second = self.add(version='_002', content=b'two')
        self.pass_one(first)
        self.assertEqual(
            self.gallery.list({'selected_only': ['1']})['results'][0]['relative_path'], first
        )
        self.assertEqual(
            self.gallery.list({'latest': ['1']})['results'][0]['relative_path'], second
        )
        self.assertEqual(
            self.gallery.list({'selected_only': ['1'], 'latest': ['1']})['results'][0][
                'relative_path'
            ],
            first,
        )

    def test_export_partial_full_and_collision(self):
        first = self.add(content=b'accepted')
        self.pass_one(first)
        with self.assertRaisesRegex(ValueError, 'missing:'):
            self.store.plan_and_zip(
                {'filters': {'work': 'W001', 'character': 'C001', 'outfit': '001'}}
            )
        path, name, summary = self.store.plan_and_zip(
            {'filters': {'category': 'sfw'}, 'allow_partial': True}
        )
        try:
            self.assertEqual(summary['count'], 1)
            self.assertEqual(len(summary['missing']), 48)
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ['W001/C001/001/001.webp'])
                self.assertEqual(archive.read(archive.namelist()[0]), b'accepted')
        finally:
            path.unlink()
        for n in range(2, 50):
            self.pass_one(self.add(f'{n:03d}', content=str(n).encode()))
        path, _, summary = self.store.plan_and_zip({'filters': {'work': 'W001'}})
        try:
            self.assertTrue(summary['complete'])
            self.assertEqual(summary['count'], 49)
        finally:
            path.unlink()
        other = self.add('001', '_003', 'nsfw', b'other')
        self.pass_one(other)
        with self.assertRaisesRegex(ValueError, 'collision'):
            self.store.plan_and_zip({'filters': {'category': 'all'}, 'allow_partial': True})


if __name__ == '__main__':
    unittest.main()
