"""The before/after report of the v1 -> v2 conversion."""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from asset_studio.library.layout import Location
from tools.migrations.v2_convert import GLOBAL, read


def v1_counts(v1, data):
    counts = Counter()
    for entry in v1.works:
        counts['works'] += 1
        counts['characters'] += len(entry['characters'])
        counts['outfits'] += sum(len(c['outfits']) for c in entry['characters'])
        counts['expressions'] += len(entry['expressions'])
        counts['chains'] += len(entry['chains'])
        for kind in ('quality', 'artist', 'generation'):
            counts[f'{kind} presets'] += len(entry[kind])
    for kind in ('quality', 'artist', 'generation'):
        counts[f'{kind} presets'] += len(v1.presets[kind])
    trash = Path(data) / 'trash'
    counts['trash items'] = len(list(trash.glob('*/manifest.json'))) if trash.is_dir() else 0
    return counts


def sample(v1, store, work_id, character_id, outfit_id):
    """Before/after of one outfit, for the report."""
    entry = next((e for e in v1.works if e['work']['id'] == work_id), None)
    character = (
        next((c for c in entry['characters'] if c['id'] == character_id), None) if entry else None
    )
    outfit = (
        next((o for o in character['outfits'] if o['id'] == outfit_id), None) if character else None
    )
    if not outfit:
        return None
    lookup = Location('character', work_id, character_id)
    outfit_set = next(
        (
            read(store.set_file(place, outfit_id))
            for place in (lookup, GLOBAL)
            if store.set_file(place, outfit_id).is_file()
        ),
        None,
    )
    pieces = {
        slot: store.resolve_piece(lookup.widen(ref['scope']), f'outfit/{slot}', ref['id'])['prompt']
        for slot, ref in outfit_set['slots'].items()
    }
    return {'before': outfit, 'set': outfit_set, 'pieces': pieces}


def table(headers, rows):
    """Markdown table lines."""
    lines = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    lines += ['| ' + ' | '.join(str(cell) for cell in row) + ' |' for row in rows]
    return lines


def fenced(title, value):
    return [title, '```json', json.dumps(value, ensure_ascii=False, indent=2), '```']


COUNT_PAIRS = [
    ('works', 'works'),
    ('characters', 'characters'),
    ('outfits', 'outfit sets'),
    ('', 'outfit pieces'),
    ('expressions', 'expression pieces'),
    ('', 'composition pieces'),
    ('artist presets', 'artist pieces'),
    ('quality presets', 'common/positive pieces'),
    ('', 'common/negative pieces'),
    ('generation presets', 'generation presets'),
    ('chains', 'expression sets'),
    ('trash items', ''),
]


def render(report, before, checked, mismatches, samples):
    """The report as Markdown."""
    after = report['counts']
    same = checked - len(mismatches)
    lines = [
        '# 데이터 변환 v1 → v2 보고서',
        '',
        f'생성: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}',
        '',
        '## 1. 검증',
        '',
        f'- 조합 대조: **{checked:,}건 중 {same:,}건 일치**, 불일치 {len(mismatches)}건',
        '  (작품 × 캐릭터 × 의상 × 감정 × 품질·화풍 선택.',
        '  최종 긍정·제외 프롬프트를 글자 단위로 비교)',
        f'- 경고 {len(report["warnings"])}건',
        '',
    ]
    lines += [f'  - {warning}' for warning in report['warnings']]
    for item in mismatches[:10]:
        lines += [
            '',
            f'### 불일치: {item["target"]}',
            '```',
            'v1 긍정: ' + item['before'][0],
            'v2 긍정: ' + item['after'][0],
            'v1 제외: ' + item['before'][1],
            'v2 제외: ' + item['after'][1],
            '```',
        ]

    rows = []
    for old, new in COUNT_PAIRS:
        old_count = before.get(old, '') if old else ''
        new_count = after.get(new, 0) if new else '보관 (data/trash-v1)'
        rows.append((old, old_count, '→', new, new_count))
    lines += ['', '## 2. 개수', '', *table(('v1', '개수', '', 'v2', '개수'), rows)]

    how = Counter((item['how'], item['scope']) for item in report['outfits'])
    rows = [(name, scope, count) for (name, scope), count in sorted(how.items())]
    lines += ['', '## 3. 의상 → 의상 세트 + 부위 조각', '']
    lines += table(('나눈 방식', '범위', '의상 수'), rows)
    lines += ['', '3줄(손 / 상의 / 하의)이 아닌 의상:', '']
    special = []
    for item in report['outfits']:
        if item['how'] == '3줄':
            continue
        target = f'{item["character"]}/{item["id"]} {item["name"]}'
        slots = ', '.join(item['slots'])
        special.append(f'- {target}: {item["how"]} → {slots} ({item["scope"]})')
    lines += special or ['- 없음']

    rows = [
        (
            item['id'],
            f'`{item["prompt"]}`',
            item['uses'],
            ', '.join(item['suggest_slots'] or []) or '전체',
        )
        for item in report['compositions']
    ]
    lines += ['', '## 4. 구도 (감정에서 분리)', '']
    lines += table(('id', '프롬프트', '쓰는 감정 수', '기본 체크 제안'), rows)

    rows = []
    for item in report['common']:
        negative = 'common/negative/' + item['id'] if item['negative'] else '없음'
        rows.append((item['id'], item['name'], item['where'], negative))
    lines += ['', '## 5. 품질 프리셋 → 공통 긍정 / 공통 제외', '']
    lines += table(('id', '이름', '위치', '제외 조각'), rows)

    lines += ['', '## 6. 생성 설정 프리셋의 선택값', '']
    selections = []
    for item in report['generation']:
        negative = ', '.join(item['common_negative']) or '없음'
        selections.append(
            f'- {item["preset"]}: 공통 긍정 {item["quality"] or "없음"}, '
            f'공통 제외 {negative}, 화풍 {item["artist"] or "없음"}'
        )
    lines += selections or ['- 없음']

    lines += ['', '## 7. 파일 이동 (--apply 때)', '']
    lines += [f'- `{source}` → `{target}`' for source, target in report['moved']] or ['- 없음']
    for title, item in samples:
        if not item:
            continue
        lines += ['', f'## 예시: {title}', '']
        lines += fenced('변환 전 (v1 의상):', item['before'])
        lines += fenced('변환 후 (의상 세트):', item['set'])
        lines += fenced('변환 후 (부위 조각의 프롬프트):', item['pieces'])
    return '\n'.join(lines) + '\n'
