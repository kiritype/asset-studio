import json
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from asset_studio.gallery.listing import Gallery


class GalleryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.gallery = Gallery(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def add(self, relative, metadata=None, mtime=100):
        path = self.root / 'outputs' / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        image_format = 'PNG' if path.suffix == '.png' else 'WEBP'
        Image.new('RGBA', (640, 400), (255, 0, 0, 0)).save(path, format=image_format)
        os.utime(path, ns=(mtime, mtime))
        if metadata is not None:
            path.with_suffix('.json').write_text(json.dumps(metadata), encoding='utf-8')
        return path

    def test_pagination_beyond_legacy_limit_and_snapshot(self):
        for n in range(530):
            self.add(f'W001/C001/001/{n:03d}.webp', {'category': 'sfw'}, 1_000_000_000 + n)
        page = self.gallery.list({'page': ['11']})
        self.assertEqual((page['total'], page['pages'], len(page['results'])), (530, 12, 48))
        self.assertEqual(len({x['relative_path'] for x in page['results']}), 48)
        self.add(
            'W001/C001/001/new.webp', {'category': 'sfw'}, int(page['snapshot']) + 1_000_000_000
        )
        # Refresh is throttled, so force the next stat pass without a sleep.
        self.gallery._last_scan = 0
        stable = self.gallery.list({'page': ['11'], 'snapshot': [page['snapshot']]})
        self.assertEqual(stable['total'], 530)
        self.assertEqual(stable['results'], page['results'])
        self.assertEqual(self.gallery.list({'page_size': ['999']})['page_size'], 192)

    def test_filters_latest_suffix_tree_and_missing_library(self):
        self.add(
            'Wold/Cold/001/001.webp',
            {'category': 'sfw', 'expression_id': '001', 'expression_name': 'Smile'},
            200,
        )
        self.add(
            'Wold/Cold/001/001_002.webp',
            {'category': 'sfw', 'expression_id': '001', 'expression_name': 'Smile'},
            100,
        )
        self.add(
            'Wold/Cold/001/002.webp',
            {'category': 'nsfw', 'expression_id': '002', 'expression_name': 'Pose'},
            300,
        )
        self.add('Wold/Ctwo/099/001.webp', {'category': 'sfw', 'expression_id': '001'}, 400)
        found = self.gallery.list(
            {
                'work': ['Wold'],
                'character': ['Cold'],
                'outfit': ['001'],
                'expression': ['001'],
                'category': ['sfw'],
                'latest': ['true'],
            }
        )
        self.assertEqual(found['total'], 1)
        self.assertEqual(found['results'][0]['filename'], '001_002.webp')
        tree = self.gallery.tree()
        self.assertEqual(tree['works'][0]['count'], 4)
        self.assertEqual(tree['works'][0]['characters'][0]['count'], 3)
        self.assertEqual(tree['works'][0]['characters'][0]['outfits'][0]['count'], 3)
        self.assertEqual(
            tree['expressions'],
            [
                {'id': '002', 'name': 'Pose', 'category': 'nsfw', 'count': 1},
                {'id': '001', 'name': 'Smile', 'category': 'sfw', 'count': 3},
            ],
        )

    def test_metadata_missing_corrupt_and_thumbnail(self):
        good = self.add(
            'W001/C001/001/001.webp', {'category': 'sfw', 'created_at': '2020-01-01T00:00:00Z'}
        )
        bad = self.add('W001/C001/001/002.webp')
        bad.with_suffix('.json').write_text('{bad', encoding='utf-8')
        self.add('W001/C001/001/003.webp')
        self.add('W001/C001/001/004.webp', {'category': {'bad': True}, 'expression_name': ['bad']})
        items = {x['filename']: x for x in self.gallery.list({})['results']}
        self.assertTrue(items['001.webp']['metadata_available'])
        self.assertFalse(items['002.webp']['metadata_available'])
        self.assertFalse(items['003.webp']['metadata_available'])
        self.assertTrue(items['004.webp']['metadata_available'])
        self.assertEqual(items['001.webp']['created_at'], '2020-01-01T00:00:00Z')
        self.assertEqual(self.gallery.metadata('W001/C001/001/001.webp')['category'], 'sfw')
        self.assertEqual(
            self.gallery.metadata('W001/C001/001/002.webp')['error'], 'Metadata unavailable'
        )
        thumb = self.gallery.thumbnail('W001/C001/001/001.webp')
        self.assertEqual(thumb[:4], b'RIFF')
        self.assertEqual(thumb, self.gallery.thumbnail('W001/C001/001/001.webp'))
        self.assertTrue(list((self.root / 'data/cache/thumbnails').glob('*.webp')))
        self.assertTrue(good.exists())

    def test_path_traversal_and_symlinks(self):
        self.add('W001/C001/001/001.webp')
        for bad in (
            '../outside.webp',
            '/W001/C001/001/001.webp',
            'W001/C001/001/../../outside.webp',
            'W001\\C001\\001\\001.webp',
            'W001/C001/001/001.json',
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.gallery.thumbnail(bad)
        outside = self.root / 'outside.webp'
        Image.new('RGB', (2, 2)).save(outside, format='WEBP')
        link = self.root / 'outputs/W001/C001/001/link.webp'
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError):
            return
        self.gallery._last_scan = 0
        self.assertEqual(self.gallery.list({})['total'], 1)
        with self.assertRaises(ValueError):
            self.gallery.thumbnail('W001/C001/001/link.webp')

    def test_png_and_any_folder_depth(self):
        self.add('W001/C001/001/001.png', {'category': 'sfw', 'expression_id': '001'}, 100)
        self.add('_lab/2026-10-01/0001.png', {'positive': 'smile'}, 200)
        self.add('_lab/2026-10-01/compare/0002.webp', None, 300)
        self.add('loose.png', None, 400)
        everything = self.gallery.list({})
        self.assertEqual(everything['total'], 4)
        lab = self.gallery.list({'folder': ['_lab']})
        self.assertEqual(
            sorted(item['relative_path'] for item in lab['results']),
            ['_lab/2026-10-01/0001.png', '_lab/2026-10-01/compare/0002.webp'],
        )
        lab_item = lab['results'][-1]
        self.assertEqual((lab_item['work_id'], lab_item['folder']), ('', '_lab/2026-10-01'))
        tree = self.gallery.tree()
        self.assertEqual([w['id'] for w in tree['works']], ['W001'])
        self.assertEqual(
            tree['folders'],
            [
                {'path': '_lab', 'count': 2},
                {'path': '_lab/2026-10-01', 'count': 2},
                {'path': '_lab/2026-10-01/compare', 'count': 1},
            ],
        )
        self.assertEqual(self.gallery.metadata('_lab/2026-10-01/0001.png'), {'positive': 'smile'})
        self.assertTrue(self.gallery.thumbnail('loose.png').startswith(b'RIFF'))
        for bad in ('../x.png', 'W001/C001/001/001.json', 'a/' * 10 + 'x.png'):
            with self.subTest(path=bad), self.assertRaises(ValueError):
                self.gallery._safe_path(bad)

    def test_model_family_filter(self):
        self.add('W001/C001/001/001.png', {'settings': {'model': 'm'}})
        self.add('_lab/2026-10-01/a.png', {'settings': {'family': 'sdxl'}})
        self.add('_tools/2026-10-01/b.webp')
        families = {
            name: [i['relative_path'] for i in self.gallery.list({'family': [name]})['results']]
            for name in ('anima', 'sdxl', 'unknown')
        }
        self.assertEqual(families['anima'], ['W001/C001/001/001.png'])
        self.assertEqual(families['sdxl'], ['_lab/2026-10-01/a.png'])
        self.assertEqual(families['unknown'], ['_tools/2026-10-01/b.webp'])


if __name__ == '__main__':
    unittest.main()
