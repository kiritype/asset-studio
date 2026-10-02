"""Persistent, reversible human and automated review state for gallery images."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from ..util import replace_file, state_file

_VERDICTS = {'pass', 'fail', 'unreviewed'}
_AUTO = {'pending', 'pass', 'fail', 'uncertain', 'error'}
_CODE = re.compile(r'^[A-Za-z0-9_-]+$')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _identity(path: str, sha256: str) -> str:
    return path + '\0' + sha256


def _combo(item: dict) -> str:
    return json.dumps(
        [item[k] for k in ('work_id', 'character_id', 'outfit_id', 'category', 'expression_id')],
        ensure_ascii=False,
        separators=(',', ':'),
    )


class ExportIncomplete(ValueError):
    def __init__(self, missing: list[str]):
        self.missing = missing
        self.summary = {'missing': missing, 'complete': False}
        super().__init__('SFW export incomplete; missing: ' + ', '.join(missing))


class ReviewStore:
    def __init__(self, root: str | Path, gallery):
        self.root = Path(root).resolve()
        self.gallery = gallery
        self.path = state_file(self.root, 'reviews.json')
        self._lock = threading.RLock()
        self._hash_cache: dict[str, tuple[tuple[int, int, int], str]] = {}
        self._state = self._load()
        gallery.review_store = self

    def _load(self) -> dict:
        if self.path.is_symlink():
            raise ValueError('Review store symlink is forbidden')
        if not self.path.exists():
            return {'version': 1, 'records': {}, 'selected': {}, 'history': []}
        state = json.loads(self.path.read_text(encoding='utf-8'))
        if (
            state.get('version') != 1
            or not isinstance(state.get('records'), dict)
            or not isinstance(state.get('selected'), dict)
        ):
            raise ValueError('Invalid review store')
        state.setdefault('history', [])
        return state

    def _save(self, state: dict) -> None:
        data = self.path.parent
        if data.is_symlink() or data.parent.is_symlink() or self.path.is_symlink():
            raise ValueError('Review store symlink is forbidden')
        data.mkdir(parents=True, exist_ok=True)
        temporary = data / ('reviews.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + '\n', encoding='utf-8'
            )
            replace_file(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self._state = state

    def sha256(self, relative: str, *, fresh: bool = False) -> str:
        path = self.gallery._safe_path(relative)
        if not path.is_file():
            raise FileNotFoundError(relative)
        stat = path.stat()
        signature = (stat.st_mtime_ns, stat.st_size, getattr(stat, 'st_ino', 0))
        cached = self._hash_cache.get(relative)
        if not fresh and cached and cached[0] == signature:
            return cached[1]
        digest = hashlib.sha256()
        with path.open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        value = digest.hexdigest()
        self._hash_cache[relative] = (signature, value)
        return value

    def _item(self, relative: str) -> dict:
        self.gallery._safe_path(relative)
        with self.gallery._lock:
            self.gallery._scan()
            for item in self.gallery._items:
                if item['relative_path'] == relative:
                    return item.copy()
        raise FileNotFoundError(relative)

    def annotate(self, item: dict) -> dict:
        result = item.copy()
        relative = result['relative_path']
        try:
            sha = self.sha256(relative)
        except (FileNotFoundError, OSError, ValueError):
            sha = ''
        with self._lock:
            record = self._state['records'].get(_identity(relative, sha), {})
            selected = self._state['selected'].get(_combo(result))
            result.update(
                sha256=sha,
                human_status=record.get('human', 'unreviewed'),
                auto_status=record.get('auto', 'pending'),
                auto_reason=record.get('auto_reason', ''),
                selected=bool(
                    sha
                    and selected == {'path': relative, 'sha256': sha}
                    and record.get('human') == 'pass'
                ),
            )
        return result

    def get_review(self, path: str) -> dict:
        return self.annotate(self.gallery._public(self._item(path)))

    def status(self, paths=None) -> dict:
        if paths is None:
            with self.gallery._lock:
                self.gallery._scan()
                paths = [item['relative_path'] for item in self.gallery._items]
        return {'results': [self.get_review(path) for path in paths]}

    def review(self, body: dict) -> dict:
        verdict = body.get('verdict')
        items = body.get('items')
        if verdict not in _VERDICTS or not isinstance(items, list) or not items:
            raise ValueError('Expected nonempty items and pass, fail, or unreviewed verdict')
        if len(items) > 10000:
            raise ValueError('Too many review items')
        reason, note = body.get('reason', ''), body.get('note', '')
        if (
            not isinstance(reason, str)
            or not isinstance(note, str)
            or len(reason) > 100
            or len(note) > 2000
        ):
            raise ValueError('Invalid review reason or note')
        snapshot = []
        seen = set()
        for requested in items:
            if not isinstance(requested, dict) or not isinstance(requested.get('path'), str):
                raise ValueError('Each item needs a path')
            relative = requested['path']
            if relative in seen:
                continue
            seen.add(relative)
            item = self._item(relative)
            sha = self.sha256(relative, fresh=True)
            expected = requested.get('sha256')
            if expected is not None and expected != sha:
                raise ValueError('Image changed: ' + relative)
            snapshot.append((item, sha))
        # Guard a batch against a replacement between its first and last item.
        for item, sha in snapshot:
            if self.sha256(item['relative_path'], fresh=True) != sha:
                raise ValueError('Image changed: ' + item['relative_path'])
        with self._lock:
            state = copy.deepcopy(self._state)
            when = _now()
            for item, sha in snapshot:
                relative = item['relative_path']
                identity = _identity(relative, sha)
                record = state['records'].setdefault(identity, {'path': relative, 'sha256': sha})
                old = record.get('human', 'unreviewed')
                combo = _combo(item)
                # Only queue images belong to a work/character/expression to adopt.
                if verdict == 'pass' and item['work_id']:
                    state['selected'][combo] = {'path': relative, 'sha256': sha}
                elif state['selected'].get(combo) == {'path': relative, 'sha256': sha}:
                    del state['selected'][combo]
                record.update(human=verdict, reason=reason, note=note, reviewed_at=when)
                state['history'].append(
                    {
                        'at': when,
                        'path': relative,
                        'sha256': sha,
                        'from': old,
                        'to': verdict,
                        'reason': reason,
                        'note': note,
                    }
                )
                record['human_revision'] = len(state['history'])
            self._save(state)
        return {
            'results': [self.get_review(item['relative_path']) for item, _ in snapshot],
            'updated': len(snapshot),
        }

    def record_auto(self, path: str, verdict: str, reason: str = '', details=None) -> dict:
        if verdict not in _AUTO or not isinstance(reason, str):
            raise ValueError('Invalid automated verdict')
        self._item(path)
        sha = self.sha256(path, fresh=True)
        with self._lock:
            state = copy.deepcopy(self._state)
            record = state['records'].setdefault(
                _identity(path, sha), {'path': path, 'sha256': sha}
            )
            when = _now()
            state['history'].append(
                {
                    'at': when,
                    'path': path,
                    'sha256': sha,
                    'source': 'auto',
                    'from': record.get('auto', 'pending'),
                    'to': verdict,
                    'reason': reason,
                }
            )
            record.update(auto=verdict, auto_reason=reason, auto_details=details, auto_at=when)
            self._save(state)
        return self.get_review(path)

    def is_human_accepted(self, combo) -> bool:
        return self.human_acceptance_time(combo) is not None

    def human_acceptance_time(self, combo) -> str | None:
        """Return the current selected pass time, or None if its image changed."""
        if isinstance(combo, dict):
            key = _combo(combo)
        elif isinstance(combo, (tuple, list)) and len(combo) == 5:
            key = json.dumps(list(combo), ensure_ascii=False, separators=(',', ':'))
        else:
            raise ValueError('Expected five-part review combo')
        with self._lock:
            pointer = self._state['selected'].get(key)
            if not pointer:
                return None
            record = self._state['records'].get(_identity(pointer['path'], pointer['sha256']), {})
            if record.get('human') != 'pass':
                return None
            reviewed_at = record.get('reviewed_at')
            if not isinstance(reviewed_at, str) or not reviewed_at:
                return None
        try:
            return (
                reviewed_at
                if self.sha256(pointer['path'], fresh=True) == pointer['sha256']
                else None
            )
        except (OSError, ValueError):
            return None

    def human_acceptance_revision(self, combo) -> int | None:
        """Return a selected pass revision only while its image hash still matches."""
        if isinstance(combo, dict):
            key = _combo(combo)
        elif isinstance(combo, (tuple, list)) and len(combo) == 5:
            key = json.dumps(list(combo), ensure_ascii=False, separators=(',', ':'))
        else:
            raise ValueError('Expected five-part review combo')
        with self._lock:
            pointer = self._state['selected'].get(key)
            if not pointer:
                return None
            record = self._state['records'].get(_identity(pointer['path'], pointer['sha256']), {})
            revision = record.get('human_revision')
            if record.get('human') != 'pass' or not isinstance(revision, int) or revision < 1:
                return None
        try:
            return (
                revision if self.sha256(pointer['path'], fresh=True) == pointer['sha256'] else None
            )
        except (OSError, ValueError):
            return None

    def human_revision(self) -> int:
        """Current persisted review sequence for a new pipeline round baseline."""
        with self._lock:
            return len(self._state['history'])

    def plan_and_zip(self, body: dict) -> tuple[Path, str, dict]:
        filters = body.get('filters') or {}
        if not isinstance(filters, dict):
            raise ValueError('Invalid export filters')
        for key in ('work', 'character', 'outfit', 'category'):
            value = filters.get(key, '')
            if not isinstance(value, str) or (value and not _CODE.fullmatch(value)):
                raise ValueError('Invalid export filter: ' + key)
        category = filters.get('category') or 'sfw'
        allow_partial = body.get('allow_partial', False)
        if not isinstance(allow_partial, bool):
            raise ValueError('Invalid allow_partial')
        with self.gallery._lock:
            self.gallery._scan()
            gallery_items = [item.copy() for item in self.gallery._items]
        with self._lock:
            selected = copy.deepcopy(self._state['selected'])
            records = copy.deepcopy(self._state['records'])
        by_path = {item['relative_path']: item for item in gallery_items}
        scoped = [
            item
            for item in gallery_items
            if all(
                not filters.get(k) or item[field] == filters[k]
                for k, field in (
                    ('work', 'work_id'),
                    ('character', 'character_id'),
                    ('outfit', 'outfit_id'),
                )
            )
            and (category == 'all' or item['category'] == category)
        ]
        scopes = {(item['work_id'], item['character_id'], item['outfit_id']) for item in scoped}
        plan = []
        for key, pointer in selected.items():
            item = by_path.get(pointer.get('path', ''))
            if item not in scoped or not item or _combo(item) != key:
                continue
            sha = pointer.get('sha256')
            if records.get(_identity(pointer['path'], sha), {}).get('human') != 'pass':
                continue
            relative = pointer['path']
            if self.sha256(relative, fresh=True) != sha:
                raise ValueError('Selected image changed: ' + relative)
            plan.append((item, sha))
        missing = []
        if category == 'sfw':
            selected_codes = {
                (item['work_id'], item['character_id'], item['outfit_id'], item['expression_id'])
                for item, _ in plan
            }
            for scope in sorted(scopes):
                for number in range(1, 50):
                    expression = f'{number:03d}'
                    if (*scope, expression) not in selected_codes:
                        missing.append('/'.join((*scope, expression)))
        if missing and not allow_partial:
            raise ExportIncomplete(missing)
        if not plan:
            raise ValueError('No manually accepted images in export scope')
        names = {}
        for item, sha in plan:
            parts = (
                item['work_id'],
                item['character_id'],
                item['outfit_id'],
                item['expression_id'] + Path(item['relative_path']).suffix.lower(),
            )
            if not all(_CODE.fullmatch(part) for part in parts[:-1]) or not _CODE.fullmatch(
                item['expression_id']
            ):
                raise ValueError('Invalid export filename')
            name = '/'.join(parts)
            if name in names:
                raise ValueError('Export filename collision across categories; filter one category')
            names[name] = (item['relative_path'], sha)
        descriptor, temp_name = tempfile.mkstemp(prefix='asset-studio-accepted-', suffix='.zip')
        os.close(descriptor)
        target = Path(temp_name)
        try:
            with zipfile.ZipFile(
                target, 'w', compression=zipfile.ZIP_STORED, allowZip64=True
            ) as archive:
                for name, (relative, expected) in sorted(names.items()):
                    source = self.gallery._safe_path(relative)
                    if self.sha256(relative, fresh=True) != expected:
                        raise ValueError('Selected image changed: ' + relative)
                    digest = hashlib.sha256()
                    with source.open('rb') as inp, archive.open(name, 'w', force_zip64=True) as out:
                        for chunk in iter(lambda: inp.read(1024 * 1024), b''):
                            digest.update(chunk)
                            out.write(chunk)
                    if (
                        digest.hexdigest() != expected
                        or self.sha256(relative, fresh=True) != expected
                    ):
                        raise ValueError('Selected image changed: ' + relative)
            filename = (
                'accepted-'
                + (filters.get('work') or 'all')
                + '-'
                + (filters.get('character') or 'all')
                + '-'
                + category
                + '.zip'
            )
            return (
                target,
                filename,
                {
                    'count': len(names),
                    'missing': missing,
                    'complete': not missing,
                    'category': category,
                    'paths': sorted(names),
                },
            )
        except BaseException:
            target.unlink(missing_ok=True)
            raise
