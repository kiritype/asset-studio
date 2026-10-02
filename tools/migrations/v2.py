"""Convert a v1 ``data/`` folder to the v2 piece layout.

    python tools/migrations/v2.py                  # dry run: build, verify, report
    python tools/migrations/v2.py --apply          # back up data/, then convert in place
    python tools/migrations/v2.py --rollback backups/pre-v2-<stamp>

A dry run builds the v2 library in a temporary folder, checks that every
character x outfit x expression composes to exactly the same prompt as before, and
writes a report. Nothing under ``data/`` changes without ``--apply``.

``--apply`` first copies the whole ``data/`` folder to ``backups/pre-v2-<stamp>/data``.
Generated images and their metadata are never touched.
"""

import argparse
import json
import shutil
import sys
import tempfile
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asset_studio.library.layout import LAYOUT_FILE, LAYOUT_VERSION
from tools.migrations.v2_convert import V1, Converter, read, verify
from tools.migrations.v2_report import render, sample, v1_counts

STATE_FILES = ('queue.json', 'reviews.json', 'review_rounds.json')

SETTINGS_FILES = {
    'vlm.json': 'vlm.json',
    'review_settings.json': 'review_settings.json',
    'server_access.json': 'server_access.json',
    'lora_pipeline.json': 'lora_pipeline.json',
    'studio_settings.json': 'connection.json',
}

LIBRARY_FOLDERS = ('works', 'presets', 'retired')


def planned_moves(data):
    moves = [(name, f'state/{name}') for name in STATE_FILES if (data / name).is_file()]
    moves += [
        (name, f'settings/{target}')
        for name, target in SETTINGS_FILES.items()
        if (data / name).is_file()
    ]
    if (data / 'trash').is_dir():
        moves.append(('trash/', 'trash-v1/'))
    return moves


def build(data, build_root, global_outfits=('099',)):
    """Build the v2 library under ``build_root`` and verify it. Returns the report pieces."""
    data = Path(data)
    if (data / LAYOUT_FILE).is_file():
        raise SystemExit(
            f'{data}은(는) 이미 v{read(data / LAYOUT_FILE).get("layout_version")} 형식입니다.'
        )
    v1 = V1(data)
    if not v1.works:
        raise SystemExit(f'{data}에서 v1 작품을 찾지 못했습니다.')
    converter = Converter(v1, build_root, global_outfits)
    report = converter.run()
    report['moved'] = planned_moves(data)
    checked, mismatches = verify(v1, converter.store, report)
    return v1, converter.store, report, checked, mismatches


def server_running(url):
    try:
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            url + '/api/health', timeout=2
        ) as response:
            return json.load(response).get('app') == 'Asset Studio'
    except Exception:
        return False


def apply(root, built, stamp):
    """Back up ``data/`` completely, then swap the v2 library in."""
    data = root / 'data'
    backup = root / 'backups' / f'pre-v2-{stamp}'
    shutil.copytree(data, backup / 'data')
    copied = sum(1 for path in (backup / 'data').rglob('*') if path.is_file())
    original = sum(1 for path in data.rglob('*') if path.is_file())
    if copied != original:
        raise SystemExit(f'백업 파일 수가 다릅니다 ({copied} / {original}). 변환을 중단합니다.')
    replaced = backup / 'replaced'
    replaced.mkdir()
    for name in LIBRARY_FOLDERS:
        if (data / name).exists():
            shutil.move(str(data / name), str(replaced / name))
    for name in ('works', 'pieces', 'outfit_sets', 'presets', 'retired'):
        if (built / name).exists():
            shutil.move(str(built / name), str(data / name))
    for source, target in planned_moves(data):
        destination = data / target.rstrip('/')
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(data / source.rstrip('/')), str(destination))
    (data / LAYOUT_FILE).write_text(
        json.dumps({'layout_version': LAYOUT_VERSION, 'converted_at': stamp}, indent=2) + '\n',
        encoding='utf-8',
    )
    return backup


def rollback(root, backup, stamp):
    source = (root / backup if not Path(backup).is_absolute() else Path(backup)) / 'data'
    if not source.is_dir():
        raise SystemExit(f'백업을 찾지 못했습니다: {source}')
    data = root / 'data'
    aside = root / 'backups' / f'rolled-back-{stamp}'
    aside.parent.mkdir(parents=True, exist_ok=True)
    if data.exists():
        shutil.move(str(data), str(aside))
    shutil.copytree(source, data)
    print(f'되돌렸습니다. 되돌리기 전 data/는 {aside}에 있습니다.')


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('--root', type=Path, default=ROOT, help='folder that holds data/')
    parser.add_argument('--apply', action='store_true', help='back up data/ and convert it')
    parser.add_argument(
        '--rollback', metavar='BACKUP', help='restore data/ from a backup made by --apply'
    )
    parser.add_argument(
        '--report', type=Path, help='where to write the report (default: reports/migration-v2/)'
    )
    parser.add_argument(
        '--global-outfit',
        action='append',
        metavar='ID',
        help='outfit id to store once as a global outfit set (default: 099)',
    )
    parser.add_argument('--server-url', default='http://127.0.0.1:8195')
    parser.add_argument('--sample', action='append', metavar='WORK/CHARACTER/OUTFIT', default=[])
    args = parser.parse_args()
    root = args.root.resolve()
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    if (args.apply or args.rollback) and server_running(args.server_url):
        raise SystemExit(
            f'Asset Studio 서버({args.server_url})가 실행 중입니다. '
            '서버를 종료한 뒤 다시 실행하세요.'
        )
    if args.rollback:
        return rollback(root, args.rollback, stamp)

    with tempfile.TemporaryDirectory(prefix='asset-studio-v2-') as temp:
        v1, store, report, checked, mismatches = build(
            root / 'data', temp, args.global_outfit or ('099',)
        )
        before = v1_counts(v1, root / 'data')
        samples = [(target, sample(v1, store, *target.split('/'))) for target in args.sample]
        body = render(report, before, checked, mismatches, samples)
        report_path = args.report or root / 'reports' / 'migration-v2' / f'report-{stamp}.md'
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(body, encoding='utf-8')
        print(
            f'조합 대조 {checked:,}건, 불일치 {len(mismatches)}건, 경고 {len(report["warnings"])}건'
        )
        for key, value in sorted(report['counts'].items()):
            print(f'  {key}: {value}')
        print(f'보고서: {report_path}')
        if mismatches:
            raise SystemExit(
                '조합 결과가 달라지는 항목이 있어 변환하지 않습니다. 보고서를 확인하세요.'
            )
        if not args.apply:
            print('확인만 했습니다. 실제 변환은 --apply 를 붙여 실행하세요.')
            return None
        backup = apply(root, store.root, stamp)
        print(f'변환했습니다. 전체 백업: {backup / "data"}')
        relative = backup.relative_to(root).as_posix()
        print(f'되돌리기: python tools/migrations/v2.py --rollback {relative}')
    return None


if __name__ == '__main__':
    main()
