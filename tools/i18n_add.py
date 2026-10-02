"""Add or replace translations in every catalog.

    python tools/i18n_add.py entries.json      # add or replace keys
    python tools/i18n_add.py --remove KEY …    # drop keys the code no longer uses

entries.json: {"jobs.queue_n": {"ko": "…", "en": "…", "ja": "…", "zh-CN": "…"}}

Every key needs all four languages. Server keys start with ``server.`` and their "en"
must be the English text written in the Msg() call.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = ('ko', 'en', 'ja', 'zh-CN')


def update(entries=None, remove=()):
    for key, texts in (entries or {}).items():
        missing = [lang for lang in LANGUAGES if not isinstance(texts.get(lang), str)]
        if missing:
            raise SystemExit(f'{key}: missing {", ".join(missing)}')
    for language in LANGUAGES:
        path = ROOT / 'static' / 'i18n' / f'{language}.json'
        catalog = json.loads(path.read_text(encoding='utf-8'))
        for key, texts in (entries or {}).items():
            catalog[key] = texts[language]
        for key in remove:
            catalog.pop(key, None)
        text = json.dumps(dict(sorted(catalog.items())), ensure_ascii=False, indent=1)
        path.write_text(text + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    if sys.argv[1] == '--remove':
        update(remove=sys.argv[2:])
    else:
        update(json.loads(Path(sys.argv[1]).read_text(encoding='utf-8')))
