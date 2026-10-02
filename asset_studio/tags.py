"""Offline Danbooru tag lookup: existence, aliases, post counts and descriptions.

The data are two CSV snapshots shipped with the ComfyUI "easyuse-anima" nodes:
``danbooru_2025-09-01.csv`` (name, category, post count, aliases) and the optional
``danbooru_tags_classified.csv`` (descriptions). Their folder comes from the
``DANBOORU_TAGS_DIR`` environment variable, ``data/settings/tags.json`` or the
ComfyUI folder in the connection settings.
"""

import csv
import difflib
import json
import os
import threading
from pathlib import Path

from .i18n import Msg
from .util import settings_file

CATEGORIES = {'0': 'general', '1': 'artist', '3': 'copyright', '4': 'character', '5': 'meta'}
TAGS_FILE = 'danbooru_2025-09-01.csv'
DESCRIPTIONS_FILE = 'danbooru_tags_classified.csv'
EASYUSE_DATA = '__easyuse_anima__'


def norm(tag):
    """Danbooru spelling: lower case with underscores."""
    return tag.strip().lower().replace(' ', '_')


def easyuse_dir(comfy_path):
    """The tag data of ComfyUI-EasyUseAnima under any folder name (manager or git clone)."""
    nodes = comfy_path / 'custom_nodes'
    found = sorted(nodes.glob(f'*/{EASYUSE_DATA}')) if nodes.is_dir() else []
    return found[0] if found else nodes / 'comfyui-easyuse-anima' / EASYUSE_DATA


def data_dir(root):
    if os.environ.get('DANBOORU_TAGS_DIR'):
        return Path(os.environ['DANBOORU_TAGS_DIR'])
    for name, key in (('tags.json', 'danbooru_dir'), ('connection.json', 'comfy_path')):
        path = settings_file(root, name)
        if path.is_file():
            value = json.loads(path.read_text(encoding='utf-8')).get(key)
            if value:
                return Path(value) if key == 'danbooru_dir' else easyuse_dir(Path(value))
    return None


class TagIndex:
    """All tags in memory (a few hundred thousand rows; loaded once)."""

    def __init__(self, folder):
        self.tags, self.aliases, self.descriptions = {}, {}, {}
        folder = Path(folder)
        with open(folder / TAGS_FILE, encoding='utf-8') as stream:
            for row in csv.reader(stream):
                if len(row) < 3:
                    continue
                name, category, count = row[0], row[1], int(row[2] or 0)
                self.tags[name] = (category, count)
                for alias in row[3].split(',') if len(row) > 3 and row[3] else []:
                    self.aliases.setdefault(alias.strip(), name)
        classified = folder / DESCRIPTIONS_FILE
        if classified.exists():
            with open(classified, encoding='utf-8-sig') as stream:
                for row in csv.DictReader(stream):
                    self.descriptions[row['name']] = row.get('description', '')
                    if row['name'] not in self.tags:
                        self.tags[row['name']] = (
                            row.get('category', '0'),
                            int(row.get('post_count') or 0),
                        )
        self._by_count = sorted(self.tags, key=lambda name: -self.tags[name][1])

    def entry(self, name):
        category, count = self.tags[name]
        return {
            'tag': name.replace('_', ' '),
            'category': CATEGORIES.get(category, category),
            'count': count,
            'description': self.descriptions.get(name, ''),
        }

    def check(self, tag):
        """OK / ALIAS / UNKNOWN for one tag, with near matches for unknown ones."""
        key = norm(tag)
        if key in self.tags:
            return {'status': 'ok', **self.entry(key)}
        if key in self.aliases:
            return {'status': 'alias', 'alias_of': self.entry(self.aliases[key])}
        near = difflib.get_close_matches(key, self.tags, n=5, cutoff=0.75)
        return {'status': 'unknown', 'tag': tag.strip(), 'near': [self.entry(n) for n in near]}

    def complete(self, prefix, limit=15):
        """Tags (and aliases) starting with ``prefix``, most used first."""
        key = norm(prefix)
        if not key:
            return []
        result, seen = [], set()
        for name in self._by_count:
            if name.startswith(key):
                result.append(self.entry(name))
                seen.add(name)
                if len(result) >= limit:
                    return result
        for alias, name in self.aliases.items():
            if alias.startswith(key) and name not in seen:
                result.append({**self.entry(name), 'alias': alias.replace('_', ' ')})
                seen.add(name)
                if len(result) >= limit:
                    break
        return result

    def search(self, text, limit=20):
        """Tags whose name or description contains ``text``, most used first."""
        needle = text.strip().lower()
        hits = [
            name
            for name in self._by_count
            if needle in name or needle in self.descriptions.get(name, '').lower()
        ]
        return [self.entry(name) for name in hits[:limit]]


class TagLookup:
    """The tag index for the server, loaded on first use; empty answers without the data."""

    def __init__(self, root):
        self.root = root
        self._index = None
        self._error = ''
        self._lock = threading.Lock()

    def index(self):
        with self._lock:
            if self._index is None and not self._error:
                folder = data_dir(self.root)
                if folder is None or not (Path(folder) / TAGS_FILE).is_file():
                    self._error = Msg(
                        'server.tags.danbooru_tag_data_not_found', 'Danbooru tag data not found.'
                    )
                else:
                    self._index = TagIndex(folder)
            return self._index

    def complete(self, prefix, limit=15):
        index = self.index()
        if index is None:
            return {'available': False, 'error': self._error, 'tags': []}
        return {'available': True, 'tags': index.complete(prefix, limit)}

    def check(self, tags):
        index = self.index()
        if index is None:
            return {'available': False, 'error': self._error, 'tags': []}
        return {'available': True, 'tags': [index.check(tag) for tag in tags if tag.strip()]}
