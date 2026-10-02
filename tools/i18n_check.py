"""Check the translation catalogs against the code.

    python tools/i18n_check.py

Keys look like ``jobs.queue_n``: every t('key') in static/js, every data-i18n key in
static/studio.html and every Msg('server.…', 'English', …) in asset_studio/. Each catalog
in static/i18n (ko, en, ja, zh-CN) must have every key with the same placeholders, en.json
must match the English text written in the code, and no Korean may be left in the code
outside the few places listed in ALLOWED_HANGUL.
"""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANGUL = re.compile('[가-힣]')
LANGUAGES = ('ko', 'en', 'ja', 'zh-CN')
JS_KEY = re.compile(r"""\bt\(\s*'([\w.]+)'""")
HTML_KEY = re.compile(r'data-i18n(?:-title|-label)?="([^"]+)"')
PLACEHOLDER = re.compile(r'\{\w+\}')
# Korean that is data, not interface text.
ALLOWED_HANGUL = {
    'asset_studio/library/layout.py',  # labels data/ stored before translation (LEGACY_LABELS)
    'static/js/lib/prompt_format.js',  # Korean words in a prompt-splitting pattern
    'static/js/lib/job_requests.js',  # a comment naming the Korean UI label
}


def catalogs():
    folder = ROOT / 'static' / 'i18n'
    return {lang: json.loads((folder / f'{lang}.json').read_text('utf-8')) for lang in LANGUAGES}


def frontend_keys():
    keys = set()
    for path in (ROOT / 'static' / 'js').rglob('*.js'):
        keys |= set(JS_KEY.findall(path.read_text(encoding='utf-8')))
    keys |= set(HTML_KEY.findall((ROOT / 'static' / 'studio.html').read_text(encoding='utf-8')))
    return keys


def server_messages():
    """{key: English text} from Msg('key', 'text', ...) calls."""
    found = {}
    for path in (ROOT / 'asset_studio').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, 'id', None) == 'Msg'
                and len(node.args) >= 2
                and all(isinstance(a, ast.Constant) for a in node.args[:2])
            ):
                found[node.args[0].value] = node.args[1].value
    return found


def hangul_in_code():
    """Korean outside comments in code that should only hold keys."""
    places = []
    files = [*(ROOT / 'asset_studio').rglob('*.py'), *(ROOT / 'static' / 'js').rglob('*.js')]
    files.append(ROOT / 'static' / 'studio.html')
    for path in files:
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOWED_HANGUL:
            continue
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            code = re.split(r'\s#\s|^\s*#|//', line)[0]
            if HANGUL.search(code):
                places.append(f'{rel}:{number}')
    return places


def check():
    """{'missing': {lang: [...]}, 'placeholders': [...], 'english': [...], 'unused': [...],
    'hangul': [...]}"""
    cats = catalogs()
    server = server_messages()
    wanted = frontend_keys() | set(server)
    missing = {lang: sorted(wanted - set(cat)) for lang, cat in cats.items()}
    placeholders = sorted(
        key
        for key in wanted & set(cats['ko'])
        if any(
            key in cats[lang]
            and sorted(PLACEHOLDER.findall(cats[lang][key]))
            != sorted(PLACEHOLDER.findall(cats['ko'][key]))
            for lang in LANGUAGES
        )
    )
    english = sorted(key for key, text in server.items() if cats['en'].get(key) != text)
    unused = sorted(set(cats['ko']) - wanted)
    return {
        'missing': missing,
        'placeholders': placeholders,
        'english': english,
        'unused': unused,
        'hangul': hangul_in_code(),
    }


def problems(report):
    return bool(
        any(report['missing'].values())
        or report['placeholders']
        or report['english']
        or report['hangul']
    )


if __name__ == '__main__':
    report = check()
    for lang, keys in report['missing'].items():
        print(f'{lang}: missing {len(keys)}')
        for key in keys[:30]:
            print('  missing:', key)
    for name in ('placeholders', 'english', 'unused', 'hangul'):
        print(f'{name}: {len(report[name])}')
        for item in report[name][:30]:
            print('  ', item)
    sys.exit(1 if problems(report) else 0)
