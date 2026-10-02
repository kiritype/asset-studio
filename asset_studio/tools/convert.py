"""WebP conversion and resizing, on the CPU in a background thread.

Results go to ``outputs/_tools/<date>/`` so the gallery shows them. Metadata is
stripped unless asked for; when kept, ComfyUI's WebP convention is used (EXIF Model =
``prompt:{...}``, Make = ``workflow:{...}``) so ComfyUI can still open the file.
"""

import io
import threading
import time
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

from PIL import Image, ImageOps

from ..i18n import Msg, message_of
from ..util import now
from .metadata import EXIF_MAKE, EXIF_MODEL, read_raw

MAX_TASKS = 20
MAX_SIDE = 8192


def options_of(body):
    quality = body.get('quality', 95)
    if isinstance(quality, bool) or not isinstance(quality, int) or not 1 <= quality <= 100:
        raise ValueError(
            Msg(
                'server.convert.quality_must_be_a_whole_number',
                'Quality must be a whole number from 1 to 100.',
            )
        )
    long_side = body.get('long_side') or 0
    if (
        isinstance(long_side, bool)
        or not isinstance(long_side, int)
        or not 0 <= long_side <= MAX_SIDE
    ):
        raise ValueError(
            Msg(
                'server.convert.the_long_side_must_be_from',
                'The long side must be from 0 (unchanged) to {max_side}.',
                max_side=MAX_SIDE,
            )
        )
    suffix = str(body.get('suffix', ''))
    if len(suffix) > 40 or any(c in suffix for c in '/\\:*?"<>|'):
        raise ValueError(
            Msg(
                'server.convert.the_file_name_suffix_has_characters',
                'The file name suffix has characters that are not allowed.',
            )
        )
    return {
        'quality': quality,
        'lossless': bool(body.get('lossless')),
        'keep_metadata': bool(body.get('keep_metadata')),
        'long_side': long_side,
        'suffix': suffix,
    }


def convert(source, options):
    """WebP bytes of ``source`` (a path) under ``options``."""
    with Image.open(source) as image:
        text, _ = read_raw(image)
        image = ImageOps.exif_transpose(image)
        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert(
                'RGBA' if 'A' in image.getbands() or 'transparency' in image.info else 'RGB'
            )
        if options['long_side'] and max(image.size) != options['long_side']:
            ratio = options['long_side'] / max(image.size)
            size = (max(1, round(image.width * ratio)), max(1, round(image.height * ratio)))
            image = image.resize(size, Image.Resampling.LANCZOS)
        save = {'quality': options['quality'], 'lossless': options['lossless'], 'method': 6}
        if options['keep_metadata']:
            exif = Image.Exif()
            if text.get('prompt'):
                exif[EXIF_MODEL] = 'prompt:' + text['prompt']
            if text.get('workflow'):
                exif[EXIF_MAKE] = 'workflow:' + text['workflow']
            if len(exif):
                save['exif'] = exif.tobytes()
        out = io.BytesIO()
        image.save(out, 'WEBP', **save)
        return out.getvalue(), image.size


class ConvertTasks:
    def __init__(self, root, workspace):
        self.root = Path(root)
        self.workspace = workspace
        self.lock = threading.Lock()
        self.tasks = {}

    def start(self, body):
        options = options_of(body)
        ids = body.get('ids')
        if not isinstance(ids, list) or not 1 <= len(ids) <= 500:
            raise ValueError(
                Msg(
                    'server.convert.choose_1_to_500_images_to', 'Choose 1 to 500 images to convert.'
                )
            )
        items = [self.workspace.get(i) for i in ids]
        task = dict(
            id=uuid.uuid4().hex[:12],
            status='running',
            created_at=now(),
            total=len(items),
            done=0,
            options=options,
            results=[],
            errors=[],
        )
        with self.lock:
            finished = [k for k, t in self.tasks.items() if t['status'] != 'running']
            for key in finished[: max(0, len(self.tasks) - MAX_TASKS + 1)]:
                del self.tasks[key]
            self.tasks[task['id']] = task
        threading.Thread(target=self._run, args=(task, items), daemon=True).start()
        return {'ok': True, 'task': task}

    def _target(self, item, suffix, folder):
        stem = PurePosixPath(item['name']).stem or item['id']
        stem = ''.join(c if c not in '/\\:*?"<>|' else '_' for c in stem)[:120] + suffix
        index = 1
        while True:
            name = stem if index == 1 else f'{stem}_{index:03d}'
            path = folder / (name + '.webp')
            if not path.exists():
                return path
            index += 1

    def _run(self, task, items):
        folder = self.root / 'outputs' / '_tools' / time.strftime('%Y-%m-%d')
        folder.mkdir(parents=True, exist_ok=True)
        for item in items:
            try:
                raw, size = convert(self.workspace.file(item), task['options'])
                with self.lock:
                    path = self._target(item, task['options']['suffix'], folder)
                    path.write_bytes(raw)
                relative = path.relative_to(self.root / 'outputs').as_posix()
                result = dict(
                    item_id=item['id'],
                    name=item['name'],
                    relative_path=relative,
                    url='/outputs/' + quote(relative, safe='/'),
                    bytes=len(raw),
                    source_bytes=item.get('bytes'),
                    width=size[0],
                    height=size[1],
                )
                with self.lock:
                    task['results'].append(result)
            except Exception as error:
                with self.lock:
                    task['errors'].append(
                        {'item_id': item['id'], 'name': item['name'], 'error': message_of(error)}
                    )
            with self.lock:
                task['done'] += 1
        with self.lock:
            task['status'] = 'completed'
            task['finished_at'] = now()

    def get(self, task_id):
        with self.lock:
            task = self.tasks.get(task_id)
            if task is None:
                raise ValueError(
                    Msg(
                        'server.convert.conversion_task_not_found_the_server',
                        'Conversion task not found. The server may have restarted.',
                    )
                )
            return {**task, 'results': list(task['results']), 'errors': list(task['errors'])}

    def zip(self, task_id):
        """The task's results as one ZIP: (bytes, file name)."""
        task = self.get(task_id)
        out = io.BytesIO()
        used = set()
        with zipfile.ZipFile(out, 'w', zipfile.ZIP_STORED) as archive:
            for result in task['results']:
                path = self.root / 'outputs' / result['relative_path']
                name = path.name
                while name in used:
                    name = f'{path.stem}_{len(used)}{path.suffix}'
                used.add(name)
                archive.write(path, name)
        return out.getvalue(), f'webp-{task_id}.zip'
