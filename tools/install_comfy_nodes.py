"""Install the ComfyUI custom nodes Asset Studio uses, at the tested versions.

    python tools/install_comfy_nodes.py                 # show the plan for the found ComfyUI
    python tools/install_comfy_nodes.py --yes           # carry it out
    python tools/install_comfy_nodes.py --only tagger,alpha --yes
    python tools/install_comfy_nodes.py --comfy D:\\ComfyUI --python D:\\python_embeded\\python.exe

The node list and pinned commits are in comfy_nodes/nodes.json. Nodes that are already
installed are left alone (only their version is reported); missing ones are cloned at the
pinned commit and their requirements are installed with ComfyUI's own Python. The Asset
Studio node pack (comfy_nodes/asset_studio_nodes) is linked into custom_nodes.
Restart ComfyUI afterwards.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from asset_studio import comfy_locate  # noqa: E402

MANIFEST = ROOT / 'comfy_nodes' / 'nodes.json'
PACK = ROOT / 'comfy_nodes' / 'asset_studio_nodes'


def load_manifest(path=MANIFEST):
    import json

    return json.loads(Path(path).read_text(encoding='utf-8'))


def norm_repo(url: str) -> str:
    url = (url or '').strip().lower().removesuffix('/').removesuffix('.git')
    return re.sub(r'^git@github\.com:', 'https://github.com/', url)


def _git(folder: Path, *args) -> str:
    try:
        done = subprocess.run(
            ['git', '-C', str(folder), *args], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return ''
    return done.stdout.strip() if done.returncode == 0 else ''


def inspect(folder: Path) -> dict:
    """Repository, commit and version of an installed node folder."""
    info = {'folder': folder.name, 'repo': '', 'commit': '', 'version': ''}
    toml = folder / 'pyproject.toml'
    if toml.is_file():
        text = toml.read_text(encoding='utf-8', errors='replace')
        if m := re.search(r'^version\s*=\s*"([^"]+)"', text, re.M):
            info['version'] = m.group(1)
        if m := re.search(r'^Repository\s*=\s*"([^"]+)"', text, re.M):
            info['repo'] = m.group(1)
    if (folder / '.git').exists():
        remote = _git(folder, 'config', '--get', 'remote.origin.url')
        # A registry install inside a git checkout reports the outer repository; ignore it.
        if remote and 'comfyanonymous/comfyui' not in remote.lower():
            info['repo'] = remote
            info['commit'] = _git(folder, 'rev-parse', 'HEAD')
    return info


def installed_nodes(custom_nodes: Path) -> dict:
    """Installed nodes by normalised repository URL."""
    found = {}
    if not custom_nodes.is_dir():
        return found
    for folder in custom_nodes.iterdir():
        if folder.is_dir() and not folder.name.startswith(('.', '__')):
            info = inspect(folder)
            if info['repo']:
                found[norm_repo(info['repo'])] = info
    return found


def plan(manifest: dict, custom_nodes: Path, features=None) -> list[dict]:
    """What to do for each node: ``install``, ``ok``, ``differs`` or ``skip``."""
    installed = installed_nodes(custom_nodes)
    steps = []
    for node in manifest['nodes']:
        wanted = not features or set(node['features']) & set(features)
        have = installed.get(norm_repo(node['repo']))
        step = {'node': node, 'have': have}
        if not wanted:
            step['action'] = 'skip'
        elif not have:
            target = custom_nodes / node['folder']
            step['action'] = 'blocked' if target.exists() else 'install'
        elif have['commit'] == node['commit'] or (
            not have['commit'] and have['version'] == node['version']
        ):
            step['action'] = 'ok'
        else:
            step['action'] = 'differs'
        steps.append(step)
    return steps


def describe_step(step: dict) -> str:
    node, have = step['node'], step['have']
    name = f'{node["folder"]} {node["version"]} ({node["license"]})'
    if step['action'] == 'skip':
        return f'  -  {name}: 고르지 않음'
    if step['action'] == 'install':
        return f'  +  {name}: 설치 ({node["commit"][:7]})'
    if step['action'] == 'blocked':
        return f'  !  {name}: 같은 이름의 다른 폴더가 있어 건너뜀'
    current = have['version'] or have['commit'][:7] or '?'
    if step['action'] == 'ok':
        return f'  =  {name}: 설치됨 ({have["folder"]})'
    return f'  ~  {name}: 다른 버전 설치됨 ({have["folder"]}, {current}) — 그대로 둠'


def run(cmd, cwd=None):
    print('     $', ' '.join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], cwd=cwd, check=True)


def install(step: dict, custom_nodes: Path, python: Path):
    node = step['node']
    target = custom_nodes / node['folder']
    run(['git', 'clone', node['repo'], target])
    run(['git', '-C', target, 'checkout', '--quiet', node['commit']])
    requirements = target / 'requirements.txt'
    if requirements.is_file():
        run([python, '-m', 'pip', 'install', '-r', requirements])
    if (target / 'install.py').is_file():
        # Some packs (Impact) fetch extra parts here, as ComfyUI-Manager does.
        run([python, 'install.py'], cwd=target)


def link_pack(custom_nodes: Path) -> str:
    link = custom_nodes / 'asset_studio_nodes'
    if link.exists():
        return 'ok'
    run(['cmd', '/c', 'mklink', '/J', link, PACK])
    return 'linked'


def main(argv=None):
    parser = argparse.ArgumentParser(description='Install the ComfyUI nodes Asset Studio uses.')
    parser.add_argument('--comfy', help='ComfyUI folder (the one with main.py)')
    parser.add_argument('--python', help="ComfyUI's Python (default: found next to ComfyUI)")
    parser.add_argument('--only', help='Features to install, comma separated')
    parser.add_argument('--yes', action='store_true', help='Carry out the plan')
    args = parser.parse_args(argv)
    manifest = load_manifest()
    features = [f.strip() for f in args.only.split(',')] if args.only else None
    if features and (unknown := set(features) - set(manifest['features'])):
        parser.error(
            '없는 기능: '
            + ', '.join(sorted(unknown))
            + ' (가능: '
            + ', '.join(manifest['features'])
            + ')'
        )

    if args.comfy:
        comfy = Path(args.comfy)
        if not comfy_locate.is_comfy_dir(comfy):
            parser.error(f'ComfyUI 폴더가 아닙니다(main.py 없음): {comfy}')
    else:
        found = comfy_locate.candidates()
        if not found:
            parser.error('ComfyUI를 찾지 못했습니다. --comfy로 폴더를 알려 주세요.')
        if len(found) > 1 and not found[0]['source'] == 'running':
            print('ComfyUI가 여러 개 있습니다. --comfy로 하나를 고르세요:')
            for item in found:
                print('  ', item['comfy_path'], f'({comfy_locate.KINDS[item["kind"]]})')
            return 2
        comfy = Path(found[0]['comfy_path'])
    python = Path(args.python) if args.python else comfy_locate.python_for(comfy)
    if not python or not python.is_file():
        parser.error('ComfyUI의 Python을 찾지 못했습니다. --python으로 알려 주세요.')
    custom_nodes = comfy / 'custom_nodes'

    print(f'ComfyUI: {comfy} ({comfy_locate.KINDS[comfy_locate.kind_of(comfy)]})')
    print(f'Python:  {python}')
    print(f'확인한 ComfyUI 버전: {manifest["comfyui"]["version"]}')
    steps = plan(manifest, custom_nodes, features)
    for step in steps:
        print(describe_step(step))
    pack = 'ok' if (custom_nodes / 'asset_studio_nodes').exists() else 'link'
    print('  =  asset_studio_nodes: 연결됨' if pack == 'ok' else '  +  asset_studio_nodes: 연결')
    todo = [s for s in steps if s['action'] == 'install']
    if not todo and pack == 'ok':
        print('할 일이 없습니다.')
        return 0
    if not args.yes:
        print('\n실행하려면 --yes를 붙여 다시 실행하세요.')
        return 0
    for step in todo:
        print(f'\n[{step["node"]["folder"]}]')
        install(step, custom_nodes, python)
    if pack != 'ok':
        link_pack(custom_nodes)
    print('\n끝났습니다. ComfyUI를 재시작하세요.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
