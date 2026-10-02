"""Check the translation catalogs against the code.

    python tools/i18n_check.py            # report missing and unused keys

Keys are the Korean source text: every t('…') in static/js and every Korean message in
asset_studio/ (f-string and "+" parts become {0}, {1}…). Each catalog in static/i18n must
have every key with the same placeholders.
"""

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HANGUL = re.compile('[가-힣]')
LANGUAGES = ('en', 'ja', 'zh-CN')
JS_KEY = re.compile(r"""\bt\(\s*'((?:[^'\\]|\\.)*)'""")
# Keys only used in markup (data-i18n attributes).
HTML_KEY = re.compile(r'data-i18n(?:-title|-label)?="([^"]+)"')


def _cook(raw):
    return re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), raw)


def frontend_keys():
    keys = set()
    for path in (ROOT / 'static' / 'js').rglob('*.js'):
        keys |= {_cook(m) for m in JS_KEY.findall(path.read_text(encoding='utf-8'))}
    keys |= set(HTML_KEY.findall((ROOT / 'static' / 'studio.html').read_text(encoding='utf-8')))
    return keys


def _template(node):
    counter = [0]

    def walk(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            return n.value
        if isinstance(n, ast.JoinedStr):
            out = ''
            for value in n.values:
                if isinstance(value, ast.Constant):
                    out += value.value
                else:
                    out += '{%d}' % counter[0]
                    counter[0] += 1
            return out
        if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
            return walk(n.left) + walk(n.right)
        out = '{%d}' % counter[0]
        counter[0] += 1
        return out

    return walk(node)


def server_keys():
    keys = set()

    class Visitor(ast.NodeVisitor):
        def visit_BinOp(self, node):
            if isinstance(node.op, ast.Add):
                text = _template(node)
                if HANGUL.search(re.sub(r'\{\d+\}', '', text)):
                    keys.add(text)
                    return
            self.generic_visit(node)

        def visit_JoinedStr(self, node):
            text = _template(node)
            if HANGUL.search(re.sub(r'\{\d+\}', '', text)):
                keys.add(text)

        def visit_Constant(self, node):
            if isinstance(node.value, str) and HANGUL.search(node.value):
                keys.add(node.value)

    for path in (ROOT / 'asset_studio').rglob('*.py'):
        Visitor().visit(ast.parse(path.read_text(encoding='utf-8')))
    # Docstrings are not messages.
    return {k for k in keys if '\n' not in k.strip() or len(k) < 300}


def check():
    """{language: {'missing': [...], 'placeholders': [...], 'unused': [...]}}."""
    wanted = frontend_keys() | server_keys()
    report = {}
    for language in LANGUAGES:
        catalog = json.loads((ROOT / 'static' / 'i18n' / f'{language}.json').read_text('utf-8'))
        placeholders = [
            key
            for key in wanted & set(catalog)
            if sorted(re.findall(r'\{\w+\}', key)) != sorted(re.findall(r'\{\w+\}', catalog[key]))
        ]
        report[language] = {
            'missing': sorted(wanted - set(catalog)),
            'placeholders': sorted(placeholders),
            'unused': sorted(set(catalog) - wanted),
        }
    return report


if __name__ == '__main__':
    report = check()
    failed = False
    for language, result in report.items():
        print(
            f'{language}: missing {len(result["missing"])}, placeholder mismatch '
            f'{len(result["placeholders"])}, unused {len(result["unused"])}'
        )
        for key in result['missing'][:30]:
            print('  missing:', key)
        for key in result['placeholders'][:30]:
            print('  placeholders:', key)
        failed |= bool(result['missing'] or result['placeholders'])
    sys.exit(1 if failed else 0)
