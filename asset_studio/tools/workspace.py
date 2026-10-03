"""Image-tool workspace: uploaded files and gallery images the tools work on.

Uploads are copied to ``data/tools/uploads/``; gallery images are referenced by their
path in ``outputs/`` and never copied. The list lives in ``data/state/tools.json``.
"""

import hashlib
import io
import json
import re
import shutil
import threading
import uuid
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageOps

from ..i18n import Msg, message_of
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
            raise ValueError(
                Msg('server.workspace.not_in_the_image_tools_list', 'Not in the image tools list.')
            )
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
            raise ValueError(
                Msg(
                    'server.workspace.the_file_is_too_large_max',
                    '{name}: the file is too large (max 100 MB).',
                    name=name,
                )
            )
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in FORMATS:
                    raise ValueError(
                        Msg(
                            'server.workspace.only_png_webp_and_jpeg_can',
                            '{name}: only PNG, WebP and JPEG can be uploaded.',
                            name=name,
                        )
                    )
                if getattr(image, 'is_animated', False):
                    raise ValueError(
                        Msg(
                            'server.workspace.animated_images_are_not_supported',
                            '{name}: animated images are not supported.',
                            name=name,
                        )
                    )
                if image.width * image.height > MAX_PIXELS:
                    raise ValueError(
                        Msg(
                            'server.workspace.the_image_is_too_large',
                            '{name}: the image is too large.',
                            name=name,
                        )
                    )
                image.verify()
                return image.format, image.width, image.height
        except (OSError, SyntaxError, Image.DecompressionBombError) as error:
            raise ValueError(
                Msg(
                    'server.workspace.cannot_be_read_as_an_image',
                    '{name}: cannot be read as an image.',
                    name=name,
                )
            ) from error

    def _add(self, record):
        with self.lock:
            if len(self.items) >= MAX_ITEMS:
                raise ValueError(
                    Msg(
                        'server.workspace.the_image_tools_list_holds_up',
                        'The image tools list holds up to {max_items} images. Remove some first.',
                        max_items=MAX_ITEMS,
                    )
                )
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
                raise ValueError(
                    Msg('server.workspace.cannot_open_the_zip_file', 'Cannot open the ZIP file.')
                ) from error
            entries = [e for e in archive.infolist() if not e.is_dir()]
            if len(entries) > MAX_ZIP_FILES:
                raise ValueError(
                    Msg(
                        'server.workspace.a_zip_may_hold_up_to',
                        'A ZIP may hold up to {max_zip_files} files.',
                        max_zip_files=MAX_ZIP_FILES,
                    )
                )
            if sum(e.file_size for e in entries) > MAX_ZIP_BYTES:
                raise ValueError(
                    Msg(
                        'server.workspace.the_zip_unpacks_to_more_than',
                        'The ZIP unpacks to more than 2 GB.',
                    )
                )
            for entry in entries:
                # Names are only shown; files are stored under new ids, so paths cannot escape.
                if PurePosixPath(entry.filename).suffix.lower() not in (
                    '.png',
                    '.webp',
                    '.jpg',
                    '.jpeg',
                ):
                    skipped.append(
                        {
                            'name': entry.filename,
                            'error': Msg('server.workspace.not_an_image', 'Not an image.'),
                        }
                    )
                    continue
                try:
                    added.append(self._store(entry.filename, archive.read(entry)))
                except ValueError as error:
                    skipped.append({'name': entry.filename, 'error': message_of(error)})
        else:
            added.append(self._store(name, raw))
        with self.lock:
            self._persist()
        return {'ok': True, 'added': added, 'skipped': skipped}

    def add_gallery(self, paths):
        if not isinstance(paths, list) or not 1 <= len(paths) <= 500:
            raise ValueError(
                Msg(
                    'server.workspace.choose_1_to_500_gallery_images',
                    'Choose 1 to 500 gallery images.',
                )
            )
        added = []
        with self.lock:
            known = {i['path'] for i in self.items if i['source'] == 'gallery'}
            for relative in paths:
                if relative in known:
                    continue
                path = self.gallery._safe_path(relative)
                if not path.is_file():
                    raise ValueError(
                        Msg(
                            'server.workspace.not_in_the_gallery',
                            'Not in the gallery: {relative}',
                            relative=relative,
                        )
                    )
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
            raise ValueError(
                Msg(
                    'server.workspace.choose_1_to_500_images_to',
                    'Choose 1 to 500 images to download.',
                )
            )
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
            raise ValueError(Msg('server.workspace.unknown_mask_type', 'Unknown mask type.'))
        suffix = self.MASK_KINDS[kind][0]
        return self.root / 'data' / 'tools' / 'masks' / f'{self.get(item_id)["id"]}{suffix}.png'

    def mask(self, item_id, kind='censor'):
        """A mask (grayscale image) of an item, or None."""
        path = self.mask_path(item_id, kind)
        if not path.is_file():
            return None
        with Image.open(path) as mask:
            return mask.convert('L')

    def freeze_mask(self, item_id, kind):
        """Copy the current mask for one job, so editing it later leaves the job alone.

        Returns the copy's token (``job_mask`` reads it back).
        """
        token = uuid.uuid4().hex
        path = self.job_mask_path(token)
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.mask_path(item_id, kind), path)
        return token

    def job_mask_path(self, token):
        if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{32}', token):
            raise ValueError(Msg('server.workspace.unknown_mask_type', 'Unknown mask type.'))
        return self.root / 'data' / 'tools' / 'masks' / 'jobs' / f'{token}.png'

    def job_mask(self, token):
        """The mask copied for a job, or None."""
        path = self.job_mask_path(token)
        if not path.is_file():
            return None
        with Image.open(path) as mask:
            return mask.convert('L')

    def prune_job_masks(self, keep):
        """Delete the job mask copies whose token is not in ``keep``."""
        folder = self.root / 'data' / 'tools' / 'masks' / 'jobs'
        for path in folder.glob('*.png') if folder.is_dir() else ():
            if path.stem not in keep:
                path.unlink(missing_ok=True)

    def set_mask(self, item_id, mask, source, kind='censor'):
        """Store a mask (PIL image or PNG bytes) for an item; its size must match the image."""
        item = self.get(item_id)
        size = (item['width'], item['height'])
        if isinstance(mask, (bytes, bytearray)):
            mask = censor.load_mask(bytes(mask), size)
        elif mask.size != size:
            raise ValueError(
                Msg(
                    'server.workspace.the_mask_size_differs_from_the',
                    'The mask size {size} differs from the image size {size2}.',
                    size=mask.size,
                    size2=size,
                )
            )
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
