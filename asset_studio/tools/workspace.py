"""Image-tool workspace: uploaded files and gallery images the tools work on.

Uploads are copied to ``data/tools/uploads/``; gallery images are referenced by their
path in ``outputs/`` and never copied. The list lives in ``data/state/tools.json``.
"""

import hashlib
import io
import json
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps

from ..util import atomic_json, now, state_file
from . import censor
from .metadata import describe

FORMATS = {'PNG': '.png', 'WEBP': '.webp', 'JPEG': '.jpg'}
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_ZIP_FILES = 500
MAX_ZIP_BYTES = 2 * 1024**3
MAX_PIXELS = 64_000_000
MAX_ITEMS = 2000
THUMBNAIL = 320


class ToolWorkspace:
    def __init__(self, root, gallery):
        self.root = Path(root)
        self.gallery = gallery
        self.folder = self.root / 'data' / 'tools' / 'uploads'
        self.path = state_file(self.root, 'tools.json')
        self.lock = threading.RLock()
        self.items = []
        if self.path.is_file():
            self.items = json.loads(self.path.read_text(encoding='utf-8')).get('items', [])

    def _persist(self):
        atomic_json(self.path, {'schema_version': 1, 'items': self.items})

    def public(self):
        with self.lock:
            return {'items': [dict(item) for item in self.items]}

    def get(self, item_id):
        with self.lock:
            item = next((i for i in self.items if i['id'] == item_id), None)
        if item is None:
            raise ValueError('이미지 도구 목록에 없는 이미지입니다.')
        return item

    def file(self, item):
        if item['source'] == 'gallery':
            return self.gallery._safe_path(item['path'])
        return self.folder / item['path']

    # ---- adding ---------------------------------------------------------------------

    @staticmethod
    def _check(raw, name):
        """Open and validate one image; returns (format, width, height)."""
        if len(raw) > MAX_FILE_BYTES:
            raise ValueError(f'{name}: 파일이 너무 큽니다 (최대 100MB).')
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in FORMATS:
                    raise ValueError(f'{name}: PNG, WebP, JPEG만 올릴 수 있습니다.')
                if getattr(image, 'is_animated', False):
                    raise ValueError(f'{name}: 움직이는 이미지는 지원하지 않습니다.')
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError(f'{name}: 이미지가 너무 큽니다.')
                image.verify()
                return image.format, image.width, image.height
        except (OSError, SyntaxError, Image.DecompressionBombError) as error:
            raise ValueError(f'{name}: 이미지로 읽을 수 없습니다.') from error

    def _add(self, record):
        with self.lock:
            if len(self.items) >= MAX_ITEMS:
                raise ValueError(f'이미지 도구 목록은 {MAX_ITEMS}장까지입니다. 정리 후 추가하세요.')
            self.items.append(record)

    def _store(self, name, raw):
        kind, width, height = self._check(raw, name)
        item_id = uuid.uuid4().hex[:16]
        self.folder.mkdir(parents=True, exist_ok=True)
        stored = item_id + FORMATS[kind]
        (self.folder / stored).write_bytes(raw)
        record = dict(
            id=item_id,
            source='upload',
            name=PurePosixPath(name.replace('\\', '/')).name[:200] or stored,
            path=stored,
            format=kind,
            width=width,
            height=height,
            bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
            added_at=now(),
        )
        self._add(record)
        return record

    def upload(self, name, raw):
        """One uploaded file; a ZIP adds every image inside it."""
        added, skipped = [], []
        if name.lower().endswith('.zip'):
            try:
                archive = zipfile.ZipFile(io.BytesIO(raw))
            except zipfile.BadZipFile as error:
                raise ValueError('ZIP 파일을 열 수 없습니다.') from error
            entries = [e for e in archive.infolist() if not e.is_dir()]
            if len(entries) > MAX_ZIP_FILES:
                raise ValueError(f'ZIP 안 파일은 {MAX_ZIP_FILES}개까지입니다.')
            if sum(e.file_size for e in entries) > MAX_ZIP_BYTES:
                raise ValueError('ZIP을 풀면 2GB를 넘습니다.')
            for entry in entries:
                # Names are only shown; files are stored under new ids, so paths cannot escape.
                if PurePosixPath(entry.filename).suffix.lower() not in (
                    '.png',
                    '.webp',
                    '.jpg',
                    '.jpeg',
                ):
                    skipped.append({'name': entry.filename, 'error': '이미지가 아닙니다.'})
                    continue
                try:
                    added.append(self._store(entry.filename, archive.read(entry)))
                except ValueError as error:
                    skipped.append({'name': entry.filename, 'error': str(error)})
        else:
            added.append(self._store(name, raw))
        with self.lock:
            self._persist()
        return {'ok': True, 'added': added, 'skipped': skipped}

    def add_gallery(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 500:
            raise ValueError('갤러리 이미지를 1~500장 고르세요.')
        added = []
        with self.lock:
            known = {i['path'] for i in self.items if i['source'] == 'gallery'}
            for relative in paths:
                if relative in known:
                    continue
                path = self.gallery._safe_path(relative)
                if not path.is_file():
                    raise ValueError(f'갤러리에 없는 이미지입니다: {relative}')
                with Image.open(path) as image:
                    kind, width, height = image.format, image.width, image.height
                record = dict(
                    id=uuid.uuid4().hex[:16],
                    source='gallery',
                    name=relative,
                    path=relative,
                    format=kind,
                    width=width,
                    height=height,
                    bytes=path.stat().st_size,
                    added_at=now(),
                )
                self._add(record)
                added.append(record)
                known.add(relative)
            self._persist()
        return {'ok': True, 'added': added}

    def remove(self, ids):
        """Take images off the list; uploaded copies are deleted, gallery files are kept."""
        wanted = set(ids or [])
        with self.lock:
            gone = [i for i in self.items if i['id'] in wanted]
            self.items = [i for i in self.items if i['id'] not in wanted]
            self._persist()
        for item in gone:
            if item['source'] == 'upload':
                (self.folder / item['path']).unlink(missing_ok=True)
            for suffix, _ in self.MASK_KINDS.values():
                masks = self.root / 'data' / 'tools' / 'masks'
                (masks / f'{item["id"]}{suffix}.png').unlink(missing_ok=True)
        return {'ok': True, 'removed': len(gone)}

    # ---- reading --------------------------------------------------------------------

    def thumbnail(self, item_id):
        path = self.file(self.get(item_id))
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            image.thumbnail((THUMBNAIL, THUMBNAIL))
            if image.mode in ('RGBA', 'LA', 'P'):
                image = image.convert('RGBA')
                backdrop = Image.new('RGBA', image.size, (255, 255, 255, 255))
                image = Image.alpha_composite(backdrop, image)
            out = io.BytesIO()
            image.convert('RGB').save(out, 'WEBP', quality=80)
        return out.getvalue()

    def image(self, item_id):
        item = self.get(item_id)
        return self.file(item).read_bytes(), item['format']

    def zip_names(self, ids):
        """(item, name in a ZIP) for chosen images. Gallery images keep their folders."""
        wanted = [i for i in dict.fromkeys(ids or []) if i]
        if not 1 <= len(wanted) <= 500:
            raise ValueError('내려받을 이미지를 1~500장 고르세요.')
        result = []
        used = set()
        for item in [self.get(item_id) for item_id in wanted]:
            name = PurePosixPath(item['path'] if item['source'] == 'gallery' else item['name'])
            candidate, index = name.as_posix(), 2
            while candidate.lower() in used:
                candidate = name.with_stem(f'{name.stem}_{index}').as_posix()
                index += 1
            used.add(candidate.lower())
            result.append((item, candidate))
        return result

    def zip(self, ids):
        """Chosen images as one ZIP: (bytes, file name)."""
        names = self.zip_names(ids)
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as archive:
            for item, name in names:
                archive.write(self.file(item), name)
        return out.getvalue(), f'images-{len(names)}.zip'

    def analyze(self, item_id):
        item = self.get(item_id)
        sidecar = None
        if item['source'] == 'gallery':
            meta = self.gallery.metadata(item['path'])
            sidecar = meta if isinstance(meta, dict) and 'error' not in meta else None
        return {'item': item, **describe(self.file(item), sidecar)}

    def set_parent(self, item_id, parent_id, op):
        """Remember which tool image a post-processing result was made from."""
        with self.lock:
            item = self.get(item_id)
            item.update(parent=parent_id, op=op)
            self._persist()

    # ---- censor masks ------------------------------------------------------------------

    # Masks per image: what to cover (censor), keep (alpha) and redraw (inpaint).
    MASK_KINDS = {
        'censor': ('', 'mask'),
        'alpha': ('.alpha', 'alpha_mask'),
        'inpaint': ('.inpaint', 'inpaint_mask'),
    }

    def mask_path(self, item_id, kind='censor'):
        if kind not in self.MASK_KINDS:
            raise ValueError('없는 마스크 종류입니다.')
        suffix = self.MASK_KINDS[kind][0]
        return self.root / 'data' / 'tools' / 'masks' / f'{self.get(item_id)["id"]}{suffix}.png'

    def mask(self, item_id, kind='censor'):
        """A mask (grayscale image) of an item, or None."""
        path = self.mask_path(item_id, kind)
        if not path.is_file():
            return None
        with Image.open(path) as mask:
            return mask.convert('L')

    def set_mask(self, item_id, mask, source, kind='censor'):
        """Store a mask (PIL image or PNG bytes) for an item; its size must match the image."""
        item = self.get(item_id)
        size = (item['width'], item['height'])
        if isinstance(mask, (bytes, bytearray)):
            mask = censor.load_mask(bytes(mask), size)
        elif mask.size != size:
            raise ValueError(f'마스크 크기 {mask.size}가 이미지 크기 {size}와 다릅니다.')
        path = self.mask_path(item_id, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        mask.convert('L').save(path, 'PNG')
        with self.lock:
            item[self.MASK_KINDS[kind][1]] = {'source': source, 'updated_at': now()}
            self._persist()

    def set_tags(self, item_id, tags):
        with self.lock:
            item = self.get(item_id)
            item['tags'] = tags
            self._persist()
