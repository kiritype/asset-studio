"""Filesystem-backed history for generated images.

The output directory is authoritative. Library records can be edited or removed
without changing the historical gallery.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from PIL import Image

from ..util import replace_file

IMAGE_SUFFIXES = ('.png', '.webp')
MAX_DEPTH = 8  # Folders below outputs/ that are still scanned.


def is_asset_path(parts):
    """``work/character/outfit set/file``: an image made by the job queue.

    Other images (single generations under ``_lab/``, imported files, ...) live in
    any folder and have no work, character or outfit set.
    """
    return len(parts) == 4 and not parts[0].startswith('_')


class Gallery:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.outputs = self.root / 'outputs'
        self.cache = self.root / 'data' / 'cache' / 'thumbnails'
        self._lock = threading.RLock()
        self._items: list[dict] = []
        self._signature: tuple = ()
        self._metadata_cache: dict[str, tuple[tuple | None, dict | None]] = {}
        self._last_scan = 0.0
        self._revision = 0
        self.review_store = None

    @staticmethod
    def _param(params: dict[str, list[str]], key: str, default: str = '') -> str:
        value = params.get(key, [default])
        return str(value[0]) if value else default

    @staticmethod
    def _number(value: str, default: int, maximum: int) -> int:
        try:
            return min(max(int(value), 1), maximum)
        except (TypeError, ValueError):
            return default

    def _safe_path(self, relative: str, suffix: str | None = None) -> Path:
        """An image under outputs/ (PNG or WebP unless ``suffix`` is given), never outside it."""
        if not isinstance(relative, str) or not relative or '\\' in relative or '\x00' in relative:
            raise ValueError('Invalid gallery path')
        parts = PurePosixPath(relative).parts
        if not 1 <= len(parts) <= MAX_DEPTH + 1 or any(part in ('', '.', '..') for part in parts):
            raise ValueError('Invalid gallery path')
        if any(':' in part for part in parts):
            raise ValueError('Invalid gallery path')
        path = self.outputs.joinpath(*parts)
        if path.suffix.lower() not in ((suffix,) if suffix else IMAGE_SUFFIXES):
            raise ValueError('Invalid gallery file type')
        base = self.outputs.resolve()
        if not path.resolve().is_relative_to(base):
            raise ValueError('Gallery path escapes outputs')
        # Reject all symlinks, including an output ancestor or the file itself.
        current = self.outputs
        if current.is_symlink():
            raise ValueError('Gallery symlink is forbidden')
        for part in parts:
            current /= part
            if current.is_symlink():
                raise ValueError('Gallery symlink is forbidden')
        return path

    def _read_metadata(self, path: Path) -> dict | None:
        key = path.as_posix()
        try:
            if path.is_symlink():
                raise OSError('Symlink metadata')
            stat = path.stat()
            signature = (stat.st_mtime_ns, stat.st_size)
            if stat.st_size > 16 * 1024 * 1024:
                signature = ('oversize', *signature)
        except OSError:
            signature = None
        cached = self._metadata_cache.get(key)
        if cached and cached[0] == signature:
            return cached[1]
        value = None
        if signature is not None and signature[0] != 'oversize':
            try:
                parsed = json.loads(path.read_text(encoding='utf-8'))
                if isinstance(parsed, dict):
                    value = parsed
            except (OSError, UnicodeError, ValueError):
                pass
        self._metadata_cache[key] = (signature, value)
        return value

    @staticmethod
    def _version(stem: str) -> int:
        tail = stem.rsplit('_', 1)
        return int(tail[1]) if len(tail) == 2 and tail[1].isdigit() else 1

    def _scan(self) -> None:
        now = time.monotonic()
        if now - self._last_scan < 0.75:
            return
        self._last_scan = now
        if not self.outputs.exists() or self.outputs.is_symlink():
            if self._items:
                self._items = []
                self._signature = ()
                self._revision += 1
            return
        deadline = now + 3.0
        discovered: list[tuple[Path, os.stat_result]] = []
        stack = [(self.outputs, 0)]
        try:
            while stack:
                if time.monotonic() > deadline:
                    self._last_scan = time.monotonic() + 4
                    return  # Preserve the last complete index; try again later.
                directory, depth = stack.pop()
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if time.monotonic() > deadline:
                            self._last_scan = time.monotonic() + 4
                            return
                        if entry.is_symlink():
                            continue
                        if entry.is_dir(follow_symlinks=False):
                            if depth < MAX_DEPTH:
                                stack.append((Path(entry.path), depth + 1))
                        elif entry.name.lower().endswith(IMAGE_SUFFIXES) and entry.is_file(
                            follow_symlinks=False
                        ):
                            discovered.append((Path(entry.path), entry.stat(follow_symlinks=False)))
        except OSError:
            self._last_scan = time.monotonic() + 4
            return
        signature_parts = []
        for path, stat in discovered:
            if time.monotonic() > deadline:
                self._last_scan = time.monotonic() + 4
                return
            signature_parts.append(
                (
                    str(path.relative_to(self.outputs)),
                    stat.st_mtime_ns,
                    stat.st_size,
                    self._sidecar_signature(path),
                )
            )
        signature = tuple(sorted(signature_parts))
        if signature == self._signature:
            return
        items = []
        seen_metadata = set()
        for path, stat in discovered:
            if time.monotonic() > deadline:
                self._last_scan = time.monotonic() + 4
                return
            relative = path.relative_to(self.outputs).as_posix()
            parts = PurePosixPath(relative).parts
            asset = is_asset_path(parts)
            sidecar = path.with_suffix('.json')
            seen_metadata.add(sidecar.as_posix())
            meta = self._read_metadata(sidecar)
            image_url = '/outputs/' + quote(relative, safe='/')
            created = meta.get('created_at') if meta else None
            if not isinstance(created, str):
                created = datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat()
            expression_id = (
                str(meta.get('expression_id') or path.stem.split('_')[0])
                if meta
                else path.stem.split('_')[0]
            )
            expression_name = meta.get('expression_name') if meta else None
            has_expression_name = isinstance(expression_name, str) and bool(expression_name.strip())
            if not has_expression_name:
                expression_name = expression_id
            items.append(
                dict(
                    filename=path.name,
                    relative_path=relative,
                    image_url=image_url,
                    metadata_url='/outputs/'
                    + quote(PurePosixPath(relative).with_suffix('.json').as_posix(), safe='/'),
                    thumbnail_url='/api/gallery/thumbnail?path=' + quote(relative, safe=''),
                    folder='/'.join(parts[:-1]),
                    work_id=parts[0] if asset else '',
                    character_id=parts[1] if asset else '',
                    outfit_id=parts[2] if asset else '',
                    expression_id=expression_id,
                    category=str(meta.get('category') or '') if meta else '',
                    # Records from before SDXL support were all made with Anima.
                    model_family=(
                        str((meta.get('settings') or {}).get('family') or 'anima')
                        if meta and isinstance(meta.get('settings'), dict)
                        else 'unknown'
                    ),
                    created_at=created,
                    metadata_available=meta is not None,
                    _mtime_ns=stat.st_mtime_ns,
                    _version=self._version(path.stem),
                    _expression_name=expression_name,
                    _has_expression_name=has_expression_name,
                )
            )
        self._metadata_cache = {
            key: value for key, value in self._metadata_cache.items() if key in seen_metadata
        }
        self._signature = signature
        self._items = items
        self._revision += 1

    @staticmethod
    def _sidecar_signature(path: Path) -> tuple | None:
        try:
            sidecar = path.with_suffix('.json')
            if sidecar.is_symlink():
                return None
            stat = sidecar.stat()
            return (stat.st_mtime_ns, stat.st_size)
        except OSError:
            return None

    @staticmethod
    def _public(item: dict) -> dict:
        return {key: value for key, value in item.items() if not key.startswith('_')}

    def list(self, params: dict[str, list[str]]) -> dict:
        with self._lock:
            self._scan()
            page = self._number(self._param(params, 'page', '1'), 1, 1_000_000)
            page_size = self._number(self._param(params, 'page_size', '48'), 48, 192)
            snapshot = self._param(params, 'snapshot')
            try:
                cutoff = int(snapshot) if snapshot else time.time_ns()
                if cutoff < 0:
                    raise ValueError
            except ValueError:
                raise ValueError('Invalid gallery snapshot')
            filtered = [item for item in self._items if item['_mtime_ns'] <= cutoff]
            for query_key, item_key in (
                ('work', 'work_id'),
                ('character', 'character_id'),
                ('outfit', 'outfit_id'),
                ('expression', 'expression_id'),
                ('category', 'category'),
                ('family', 'model_family'),
            ):
                selected = self._param(params, query_key)
                if selected:
                    filtered = [item for item in filtered if item[item_key] == selected]
            folder = self._param(params, 'folder')
            if folder:
                filtered = [
                    item
                    for item in filtered
                    if item['folder'] == folder or item['folder'].startswith(folder + '/')
                ]
            review_filters = {
                key: self._param(params, key) for key in ('human_status', 'auto_status')
            }
            selected_only = self._param(params, 'selected_only').lower() in ('true', '1', 'yes')
            if self.review_store is not None and (selected_only or any(review_filters.values())):
                annotated = [self.review_store.annotate(item) for item in filtered]
                filtered = [
                    item
                    for item in annotated
                    if (not selected_only or item['selected'])
                    and all(
                        not value or item[key] == value for key, value in review_filters.items()
                    )
                ]
            if self._param(params, 'latest').lower() in ('true', '1', 'yes'):
                latest = {}
                for item in filtered:
                    key = tuple(
                        item[field]
                        for field in (
                            'work_id',
                            'character_id',
                            'outfit_id',
                            'category',
                            'expression_id',
                        )
                    )
                    previous = latest.get(key)
                    if previous is None or (
                        item['_version'],
                        item['_mtime_ns'],
                        item['relative_path'],
                    ) > (previous['_version'], previous['_mtime_ns'], previous['relative_path']):
                        latest[key] = item
                filtered = list(latest.values())
            sort = self._param(params, 'sort', 'newest')
            if sort == 'code':
                filtered.sort(
                    key=lambda item: (
                        item['work_id'],
                        item['character_id'],
                        item['outfit_id'],
                        item['category'],
                        item['expression_id'],
                        item['_version'],
                        item['relative_path'],
                    )
                )
            elif sort == 'oldest':
                filtered.sort(key=lambda item: (item['_mtime_ns'], item['relative_path']))
            elif sort == 'newest':
                filtered.sort(
                    key=lambda item: (item['_mtime_ns'], item['relative_path']), reverse=True
                )
            else:
                raise ValueError('Invalid gallery sort')
            total = len(filtered)
            start = (page - 1) * page_size
            results = [self._public(item) for item in filtered[start : start + page_size]]
            if self.review_store is not None:
                results = [self.review_store.annotate(item) for item in results]
            return dict(
                results=results,
                total=total,
                page=page,
                page_size=page_size,
                pages=(total + page_size - 1) // page_size,
                revision=self._revision,
                snapshot=str(cutoff),
            )

    def tree(self) -> dict:
        with self._lock:
            self._scan()
            works = {}
            expressions = {}
            folders = {}
            for item in self._items:
                if not item['work_id']:
                    # Every enclosing folder counts the image, so the tree can show totals.
                    segments = item['folder'].split('/') if item['folder'] else []
                    for depth in range(1, len(segments) + 1):
                        key = '/'.join(segments[:depth])
                        folders[key] = folders.get(key, 0) + 1
                    continue
                work = works.setdefault(
                    item['work_id'], {'id': item['work_id'], 'count': 0, 'characters': {}}
                )
                work['count'] += 1
                character = work['characters'].setdefault(
                    item['character_id'], {'id': item['character_id'], 'count': 0, 'outfits': {}}
                )
                character['count'] += 1
                outfit = character['outfits'].setdefault(
                    item['outfit_id'], {'id': item['outfit_id'], 'count': 0}
                )
                outfit['count'] += 1
                expression_key = (item['category'], item['expression_id'])
                expression = expressions.setdefault(
                    expression_key,
                    {
                        'id': item['expression_id'],
                        'name': item['_expression_name'],
                        'category': item['category'],
                        'count': 0,
                        '_mtime_ns': -1,
                        '_has_name': False,
                    },
                )
                expression['count'] += 1
                if (item['_has_expression_name'], item['_mtime_ns']) > (
                    expression['_has_name'],
                    expression['_mtime_ns'],
                ):
                    expression['name'] = item['_expression_name']
                    expression['_mtime_ns'] = item['_mtime_ns']
                    expression['_has_name'] = item['_has_expression_name']
            result = []
            for work in sorted(works.values(), key=lambda entry: entry['id']):
                characters = []
                for character in sorted(work['characters'].values(), key=lambda entry: entry['id']):
                    character['outfits'] = sorted(
                        character['outfits'].values(), key=lambda entry: entry['id']
                    )
                    characters.append(character)
                work['characters'] = characters
                result.append(work)
            return {
                'works': result,
                'folders': [
                    {'path': key, 'count': count} for key, count in sorted(folders.items())
                ],
                'expressions': [
                    {key: value for key, value in entry.items() if not key.startswith('_')}
                    for entry in sorted(
                        expressions.values(), key=lambda x: (x['category'], x['id'])
                    )
                ],
                'revision': self._revision,
            }

    def metadata(self, relative: str) -> dict:
        image = self._safe_path(relative)
        if not image.is_file():
            return {'error': 'Image not found'}
        with self._lock:
            meta = self._read_metadata(image.with_suffix('.json'))
        return meta if meta is not None else {'error': 'Metadata unavailable'}

    def thumbnail(self, relative: str) -> bytes:
        image = self._safe_path(relative)
        if not image.is_file():
            raise FileNotFoundError(relative)
        stat = image.stat()
        digest = hashlib.sha256(
            f'{relative}\0{stat.st_mtime_ns}\0{stat.st_size}'.encode()
        ).hexdigest()
        target = self.cache / (digest + '.webp')
        with self._lock:
            current = self.root
            for part in ('data', 'cache', 'thumbnails'):
                current /= part
                if current.is_symlink():
                    raise ValueError('Gallery thumbnail cache symlink is forbidden')
            self.cache.mkdir(parents=True, exist_ok=True)
            if self.cache.is_symlink() or target.is_symlink():
                raise ValueError('Gallery thumbnail cache symlink is forbidden')
            if target.is_file():
                return target.read_bytes()
            with Image.open(image) as source:
                source.thumbnail((320, 320))
                picture = source.convert('RGBA')
                # Transparent images get a white backdrop instead of black.
                backdrop = Image.new('RGBA', picture.size, 'white')
                output = io.BytesIO()
                Image.alpha_composite(backdrop, picture).convert('RGB').save(
                    output, format='WEBP', quality=78
                )
            data = output.getvalue()
            temp = self.cache / (digest + '.' + uuid.uuid4().hex + '.tmp')
            try:
                temp.write_bytes(data)
                replace_file(temp, target)
            finally:
                temp.unlink(missing_ok=True)
            return data
