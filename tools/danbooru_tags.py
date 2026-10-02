"""Check and look up Danbooru tags offline.

    python tools/danbooru_tags.py check "smile, open mouth, extreme blush"
    python tools/danbooru_tags.py search 하트 --limit 20
    python tools/danbooru_tags.py check-json path/to/piece.json   # checks the first prompt line

The tag data folder is set by DANBOORU_TAGS_DIR, data/settings/tags.json
({"danbooru_dir": "..."}) or the ComfyUI folder in the connection settings.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from asset_studio.tags import TagIndex, data_dir


def show(result):
    if result['status'] == 'ok':
        return f'OK       {result["tag"]} ({result["category"]}, {result["count"]:,})'
    if result['status'] == 'alias':
        return f'ALIAS    → {result["alias_of"]["tag"]} ({result["alias_of"]["count"]:,})'
    near = ', '.join(f'{n["tag"]} ({n["count"]:,})' for n in result['near']) or '-'
    return f'UNKNOWN  {result["tag"]}  near: {near}'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument('command', choices=('check', 'search', 'check-json'))
    parser.add_argument('text')
    parser.add_argument('--limit', type=int, default=20)
    args = parser.parse_args()
    folder = data_dir(ROOT)
    if folder is None:
        raise SystemExit('Set DANBOORU_TAGS_DIR or data/settings/tags.json (danbooru_dir).')
    index = TagIndex(folder)
    if args.command == 'search':
        for entry in index.search(args.text, args.limit):
            print(
                f'{entry["tag"]} ({entry["category"]}, {entry["count"]:,}) {entry["description"]}'
            )
        return
    text = args.text
    if args.command == 'check-json':
        prompt = json.loads(Path(args.text).read_text(encoding='utf-8')).get('prompt', [''])
        text = prompt[0] if isinstance(prompt, list) else prompt
    for tag in (t for t in text.split(',') if t.strip()):
        print(show(index.check(tag)))


if __name__ == '__main__':
    main()
