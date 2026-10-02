"""Add or replace translations in every catalog.

python tools/i18n_add.py entries.json      # {"한국어 원문": ["English", "日本語", "简体中文"]}
python tools/i18n_add.py --remove "원문"   # drop a key that the code no longer uses
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ('en', 'ja', 'zh-CN')


def update(entries=None, remove=()):
    for index, language in enumerate(LANGUAGES):
        path = ROOT / 'static' / 'i18n' / f'{language}.json'
        catalog = json.loads(path.read_text(encoding='utf-8'))
        for key, values in (entries or {}).items():
            catalog[key] = values[index]
        for key in remove:
            catalog.pop(key, None)
        text = json.dumps(dict(sorted(catalog.items())), ensure_ascii=False, indent=1)
        path.write_text(text + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    if sys.argv[1] == '--remove':
        update(remove=sys.argv[2:])
    else:
        update(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
