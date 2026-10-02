import sys
import tempfile
import unittest
from pathlib import Path

from asset_studio import comfy_locate

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import install_comfy_nodes as installer  # noqa: E402


def comfy_at(root: Path) -> Path:
    (root / 'comfy').mkdir(parents=True)
    (root / 'main.py').write_text('')
    (root / 'nodes.py').write_text('')
    (root / 'custom_nodes').mkdir()
    return root


class LocateTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_kinds_and_their_python(self):
        portable = comfy_at(self.root / 'ComfyUI_windows_portable' / 'ComfyUI')
        embedded = portable.parent / 'python_embeded' / 'python.exe'
        embedded.parent.mkdir()
        embedded.write_text('')
        self.assertEqual(comfy_locate.kind_of(portable), 'portable')
        self.assertEqual(comfy_locate.python_for(portable), embedded)

        clone = comfy_at(self.root / 'ComfyUI')
        venv = clone / 'venv' / 'Scripts' / 'python.exe'
        venv.parent.mkdir(parents=True)
        venv.write_text('')
        self.assertEqual(comfy_locate.kind_of(clone), 'venv')
        self.assertEqual(comfy_locate.describe(clone, 'search')['python_path'], str(venv))

        matrix = comfy_at(self.root / 'SM' / 'Packages' / 'ComfyUI')
        (self.root / 'SM' / 'Models').mkdir()
        self.assertEqual(comfy_locate.kind_of(matrix), 'stability_matrix')
        self.assertFalse(comfy_locate.is_comfy_dir(self.root / 'SM'))


class SuggestLoraDirTest(unittest.TestCase):
    def test_prefers_an_anima_subfolder_and_skips_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for folder in ('comfy/models/loras', 'comfy/output/loras', 'shared/Lora/anima'):
                (root / folder).mkdir(parents=True)
            folders = {
                'loras': [
                    str(root / 'comfy/output/loras'),
                    str(root / 'comfy/models/loras'),
                    str(root / 'shared/Lora'),
                    str(root / 'missing'),
                ]
            }
            self.assertEqual(
                comfy_locate.suggest_lora_dir(folders), str(root / 'shared/Lora/anima')
            )
            folders['loras'].pop(2)
            self.assertEqual(
                comfy_locate.suggest_lora_dir(folders), str(root / 'comfy/models/loras')
            )
            self.assertEqual(comfy_locate.suggest_lora_dir(None), '')


class InstallPlanTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.custom = comfy_at(Path(temporary.name) / 'ComfyUI') / 'custom_nodes'
        self.manifest = installer.load_manifest()

    def node(self, node_id):
        return next(n for n in self.manifest['nodes'] if n['id'] == node_id)

    def test_manifest_pins_every_node(self):
        for node in self.manifest['nodes']:
            self.assertRegex(node['commit'], r'^[0-9a-f]{40}$', node['id'])
            self.assertTrue(set(node['features']) <= set(self.manifest['features']))

    def test_registry_install_under_another_folder_name_counts_as_installed(self):
        # ComfyUI-Manager's registry uses lower-case folders and leaves no .git.
        folder = self.custom / 'comfyui-easyuse-anima'
        folder.mkdir()
        node = self.node('easyuse-anima')
        (folder / 'pyproject.toml').write_text(
            f'[project]\nname = "x"\nversion = "{node["version"]}"\n'
            f'[project.urls]\nRepository = "{node["repo"]}.git"\n'
        )
        older = self.custom / 'whatever'
        older.mkdir()
        tagger = self.node('wd14-tagger')
        (older / 'pyproject.toml').write_text(
            f'version = "0.9"\nRepository = "{tagger["repo"].upper()}"\n'
        )
        steps = {s['node']['id']: s['action'] for s in installer.plan(self.manifest, self.custom)}
        self.assertEqual(steps['easyuse-anima'], 'ok')
        self.assertEqual(steps['wd14-tagger'], 'differs')  # Left alone, only reported.
        self.assertEqual(steps['essentials'], 'install')

        (self.custom / self.node('impact-pack')['folder']).mkdir()  # Same name, not the node.
        only = installer.plan(self.manifest, self.custom, ['detailer'])
        actions = {s['node']['id']: s['action'] for s in only}
        self.assertEqual(actions['essentials'], 'skip')
        self.assertEqual(actions['impact-pack'], 'blocked')
        self.assertEqual(actions['impact-subpack'], 'install')

    def test_readme_lists_the_pinned_versions(self):
        readme = (Path(__file__).resolve().parents[1] / 'README.md').read_text(encoding='utf-8')
        for node in self.manifest['nodes']:
            self.assertIn(node['version'], readme, node['id'])
        self.assertIn(self.manifest['comfyui']['version'], readme)


if __name__ == '__main__':
    unittest.main()
