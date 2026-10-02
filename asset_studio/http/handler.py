"""HTTP layer: maps API paths to Studio operations and serves static files."""

import io
import json
import logging
import mimetypes
import secrets
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, unquote, urlparse

from .. import comfy_locate, samples, settings_api
from ..compose import compose
from ..gallery.reviews import ExportIncomplete
from ..generation.workflow import build_ui_workflow, build_workflow, validate_settings
from ..i18n import Msg, message_of, wire
from ..library.layout import Location
from ..library.service import ConflictError
from ..lora import datasets as lora_datasets
from ..lora import records as lora_records
from ..lora import trainer as lora_trainer
from ..util import code
from .access import allowed_origin

APP_VERSION = '2.0.0'
MAX_BODY_BYTES = 2_000_000
MAX_UPLOAD_BYTES = 2 * 1024**3 + 1024**2
PAGE_ROUTES = (
    '/',
    '/prompts',
    '/jobs',
    '/lab',
    '/tools',
    '/lora',
    '/gallery',
    '/settings',
    '/studio',
)
# A preview server shows copied data; it must not touch the queue or ComfyUI.
PREVIEW_BLOCKED_PREFIXES = ('/api/jobs', '/api/queue', '/api/lora/runs', '/api/tools/')
PREVIEW_BLOCKED_PATHS = (
    '/api/connection/control',
    '/api/connection/settings',
    '/api/review/settings',
    '/api/gallery/regenerate',
    '/api/gallery/review',
    '/api/vlm/test',
    '/api/review/retry-validation',
    '/api/review/rounds/dismiss',
    '/api/gpu/reserve',
    '/api/gpu/release',
    '/api/settings/save',
)


def _first(params, key, default=None):
    return params.get(key, [default])[0]


def _address(params):
    """Library address from query parameters; a character always comes with its work."""
    return {
        'kind': _first(params, 'kind'),
        'scope': _first(params, 'scope'),
        'work_id': _first(params, 'work'),
        'character_id': _first(params, 'character'),
        'category': _first(params, 'category'),
        'preset_type': _first(params, 'preset_type'),
        'id': _first(params, 'id'),
    }


def _catalog(studio, params):
    work = _first(params, 'work')
    return studio.store.catalog(code(work)) if work else studio.store.global_catalog()


def _pieces(studio, params):
    address = _address(params)
    prefix = address['category']
    pieces = studio.store.list_pieces(
        Location.of({**address, 'scope': address['scope'] or 'global'})
    )
    if prefix:
        pieces = [
            p for p in pieces if p['category'] == prefix or p['category'].startswith(prefix + '/')
        ]
    return {'pieces': pieces}


def _comfy_catalog(studio, params):
    """ComfyUI's model lists plus the family (anima / sdxl) of every file."""
    catalog = studio.comfy.catalog()
    if catalog.get('connected'):
        catalog['families'] = studio.models.classify(catalog)
    return catalog


def _character(params):
    return code(_first(params, 'work')), code(_first(params, 'character'))


def _lora_candidates(studio, params):
    work_id, character_id = _character(params)
    outfit = code(_first(params, 'outfit'))
    return {'items': lora_datasets.candidates(studio, work_id, character_id, outfit)}


def _outfit_sets(studio, params):
    address = _address(params)
    location = Location.of({**address, 'scope': address['scope'] or 'global'})
    return {'outfit_sets': studio.store.list_outfit_sets(location)}


GET_ROUTES = {
    '/api/health': lambda studio, params: {
        'ok': True,
        'app': 'Asset Studio',
        'version': APP_VERSION,
    },
    '/api/app': lambda studio, params: {'version': APP_VERSION, 'preview': studio.preview},
    '/api/works': lambda studio, params: {'works': studio.store.list_works()},
    '/api/catalog': _catalog,
    '/api/comfy': _comfy_catalog,
    '/api/comfy/locate': lambda studio, params: {
        'candidates': comfy_locate.candidates(studio.comfy.url),
        'lora_dir': comfy_locate.suggest_lora_dir(comfy_locate.model_folders(studio.comfy.url)),
    },
    '/api/jobs': lambda studio, params: studio.public_jobs(),
    '/api/review/settings': lambda studio, params: studio.validation.public_settings(),
    '/api/review/rounds': lambda studio, params: studio.validation.public_rounds(),
    '/api/vlm/status': lambda studio, params: studio.validation.status(),
    '/api/gallery': lambda studio, params: studio.gallery.list(params),
    '/api/gallery/review/status': lambda studio, params: studio.review_store.status(
        params.get('path')
    ),
    '/api/gallery/tree': lambda studio, params: studio.gallery.tree(),
    '/api/gallery/metadata': lambda studio, params: studio.gallery.metadata(
        _first(params, 'path', '')
    ),
    '/api/library/version': lambda studio, params: studio.library.version(),
    '/api/library/trash': lambda studio, params: studio.library.list_trash(),
    '/api/library/entity': lambda studio, params: studio.library.get(_address(params)),
    '/api/pieces': _pieces,
    '/api/outfit-sets': _outfit_sets,
    '/api/connection/status': lambda studio, params: studio.control.status(),
    '/api/gpu': lambda studio, params: studio.gpu.status(),
    '/api/settings': lambda studio, params: settings_api.get_all(studio),
    '/api/samples': lambda studio, params: samples.list_samples(),
    '/api/tools/items': lambda studio, params: studio.tools.public(),
    '/api/tools/analyze': lambda studio, params: studio.tools.analyze(_first(params, 'id', '')),
    '/api/tools/tagger': lambda studio, params: studio.tagger_info(),
    '/api/tools/postprocess': lambda studio, params: studio.postprocess_info(),
    '/api/tools/convert/task': lambda studio, params: studio.converter.get(
        _first(params, 'id', '')
    ),
    '/api/tags/complete': lambda studio, params: studio.tags.complete(
        _first(params, 'q') or '', min(int(_first(params, 'limit') or 15), 50)
    ),
    '/api/lora/candidates': _lora_candidates,
    '/api/lora/datasets': lambda studio, params: {
        'datasets': lora_records.list_datasets(studio.store, *_character(params))
    },
    '/api/lora/runs': lambda studio, params: studio.lora.list(*_character(params)),
    '/api/lora/run': lambda studio, params: studio.lora.get(
        *_character(params), code(_first(params, 'id'))
    ),
    '/api/lora/options': lambda studio, params: lora_trainer.options(studio.root),
    '/api/loras': lambda studio, params: {'loras': lora_records.list_loras(studio.store)},
    '/api/connection/settings': lambda studio, params: {
        'config': studio.control.config,
        'preview': studio.preview,
    },
}


def _review(studio, body):
    result = studio.review_store.review(body)
    studio.validation.human_review_changed()
    return result


def _workflow(studio, body):
    snapshot = compose(studio.store, body)
    settings = validate_settings(body['settings'], studio.comfy.catalog())
    seed = secrets.randbits(32) if settings.get('seed', -1) == -1 else settings['seed']
    builder = build_ui_workflow if body.get('format', 'ui') == 'ui' else build_workflow
    return builder(settings, snapshot['positive'], snapshot['negative'], seed)


def _preview(studio, body):
    return compose(studio.store, body, single=len(body.get('expressions', [])) == 1)


POST_ROUTES = {
    '/api/review/settings': lambda studio, body: studio.validation.save_settings(body),
    '/api/review/retry-validation': lambda studio, body: studio.validation.retry_validation(
        body.get('round_ids')
    ),
    '/api/review/rounds/dismiss': lambda studio, body: studio.validation.dismiss_rounds(),
    '/api/vlm/test': lambda studio, body: studio.validation.test_connection(),
    '/api/gallery/regenerate': lambda studio, body: studio.validation.manual_regenerate(
        body.get('items')
    ),
    '/api/gallery/review': _review,
    '/api/library/save': lambda studio, body: studio.library.save(body),
    '/api/library/delete': lambda studio, body: studio.library.delete(body),
    '/api/library/move': lambda studio, body: studio.library.move(body),
    '/api/library/restore': lambda studio, body: studio.library.restore(body['trash_id']),
    '/api/pieces/save': lambda studio, body: studio.library.save({**body, 'kind': 'piece'}),
    '/api/pieces/delete': lambda studio, body: studio.library.delete({**body, 'kind': 'piece'}),
    '/api/pieces/move': lambda studio, body: studio.library.move({**body, 'kind': 'piece'}),
    '/api/outfit-sets/save': lambda studio, body: studio.library.save(
        {**body, 'kind': 'outfit_set'}
    ),
    '/api/outfit-sets/delete': lambda studio, body: studio.library.delete(
        {**body, 'kind': 'outfit_set'}
    ),
    '/api/outfit-sets/move': lambda studio, body: studio.library.move(
        {**body, 'kind': 'outfit_set'}
    ),
    '/api/connection/settings': lambda studio, body: studio.control.save(body),
    '/api/gpu/reserve': lambda studio, body: studio.gpu.reserve(body),
    '/api/models/family': lambda studio, body: studio.models.set_family(
        body.get('kind'), body.get('name'), body.get('family')
    ),
    '/api/lora/datasets/save': lambda studio, body: lora_datasets.build(studio, body),
    '/api/lora/datasets/captions': lambda studio, body: lora_datasets.recaption(studio, body),
    '/api/lora/datasets/delete': lambda studio, body: studio.library.delete(
        {**body, 'kind': 'dataset'}
    ),
    '/api/lora/runs/start': lambda studio, body: studio.lora.start(body),
    '/api/lora/runs/cancel': lambda studio, body: studio.lora.cancel(body),
    '/api/loras/register': lambda studio, body: studio.lora.register(body),
    '/api/loras/save': lambda studio, body: studio.library.save({**body, 'kind': 'lora'}),
    '/api/loras/delete': lambda studio, body: studio.library.delete({**body, 'kind': 'lora'}),
    '/api/gpu/release': lambda studio, body: studio.gpu.release_reservation(body),
    '/api/connection/control': lambda studio, body: studio.control.control(body['action']),
    '/api/compose/preview': _preview,
    '/api/workflow': _workflow,
    '/api/jobs': lambda studio, body: studio.enqueue(body),
    '/api/jobs/batch': lambda studio, body: studio.enqueue_batch(body),
    '/api/jobs/lab': lambda studio, body: studio.enqueue_lab(body),
    '/api/settings/save': lambda studio, body: settings_api.save(studio, body),
    '/api/samples/import': lambda studio, body: samples.import_sample(studio, body.get('id')),
    '/api/jobs/tags': lambda studio, body: studio.enqueue_tags(body),
    '/api/jobs/postprocess': lambda studio, body: studio.enqueue_postprocess(body),
    '/api/tools/gallery': lambda studio, body: studio.tools.add_gallery(body.get('paths')),
    '/api/tools/remove': lambda studio, body: studio.tools.remove(body.get('ids')),
    '/api/tools/convert': lambda studio, body: studio.converter.start(body),
    '/api/tools/censor': lambda studio, body: studio.apply_censor(body),
    '/api/tools/alpha': lambda studio, body: studio.apply_alpha(body),
    '/api/tags/check': lambda studio, body: studio.tags.check(list(body.get('tags') or [])[:300]),
    '/api/queue/clear-finished': lambda studio, body: studio.remove_finished(),
    '/api/queue/pause': lambda studio, body: studio.set_paused(True),
    '/api/queue/resume': lambda studio, body: studio.set_paused(False),
    '/api/queue/clear': lambda studio, body: studio.cancel_queued(),
}
JOB_ACTIONS = {
    'cancel': lambda studio, job_id: studio.cancel(job_id),
    'retry': lambda studio, job_id: studio.retry(job_id),
    'remove': lambda studio, job_id: studio.remove_finished(job_id),
}


def handler_class(studio):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logging.info(fmt, *args)

        def reply(self, status, data):
            raw = json.dumps(wire(data), ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(raw)

        def send_bytes(self, content, content_type, headers=()):
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            for name, value in headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(content)

        def do_GET(self):
            try:
                parsed = urlparse(self.path)
                path, params = parsed.path, parse_qs(parsed.query)
                if path in GET_ROUTES:
                    return self.reply(200, GET_ROUTES[path](studio, params))
                if path == '/api/tools/thumbnail':
                    raw = studio.tools.thumbnail(_first(params, 'id', ''))
                    return self.send_bytes(
                        raw, 'image/webp', [('Cache-Control', 'private, max-age=300')]
                    )
                if path == '/api/tools/mask':
                    kind = _first(params, 'kind', 'censor')
                    mask = studio.tools.mask(_first(params, 'id', ''), kind)
                    if mask is None:
                        return self.reply(404, {'error': Msg('server.handler.no_mask', 'No mask.')})
                    out = io.BytesIO()
                    mask.save(out, 'PNG')
                    return self.send_bytes(
                        out.getvalue(), 'image/png', [('Cache-Control', 'no-store')]
                    )
                if path == '/api/tools/image':
                    raw, kind = studio.tools.image(_first(params, 'id', ''))
                    return self.send_bytes(raw, 'image/' + kind.lower())
                if path == '/api/tools/tags/export':
                    ids = _first(params, 'ids', '').split(',')
                    raw, name, kind = studio.export_tags(ids, _first(params, 'format', 'txt'))
                    return self.send_bytes(
                        raw, kind, [('Content-Disposition', f'attachment; filename="{name}"')]
                    )
                if path == '/api/tools/zip':
                    ids = _first(params, 'ids', '').split(',')
                    raw, name = studio.tools.zip(ids)
                    return self.send_bytes(
                        raw,
                        'application/zip',
                        [('Content-Disposition', f'attachment; filename="{name}"')],
                    )
                if path == '/api/tools/convert/zip':
                    raw, name = studio.converter.zip(_first(params, 'id', ''))
                    return self.send_bytes(
                        raw,
                        'application/zip',
                        [('Content-Disposition', f'attachment; filename="{name}"')],
                    )
                if path == '/api/gallery/thumbnail':
                    raw = studio.gallery.thumbnail(_first(params, 'path', ''))
                    return self.send_bytes(
                        raw, 'image/webp', [('Cache-Control', 'private, max-age=60')]
                    )
                self.send_file(path)
            except Exception as error:
                self.reply(400, {'error': message_of(error)})

        def send_file(self, path):
            is_output = path.startswith('/outputs/')
            if is_output:
                base, relative = studio.root / 'outputs', unquote(path[len('/outputs/') :])
            else:
                base = getattr(studio, 'static_root', None) or studio.root / 'static'
                relative = 'studio.html' if path in PAGE_ROUTES else unquote(path.lstrip('/'))
            target = (base / relative).resolve()
            if not target.is_relative_to(base.resolve()) or not target.is_file():
                return self.reply(
                    404, {'error': Msg('server.handler.file_not_found', 'File not found.')}
                )
            headers = [('X-Content-Type-Options', 'nosniff')]
            if not is_output:
                headers.append(('Cache-Control', 'no-store'))
            content_type = mimetypes.guess_type(target.name)[0] or 'application/octet-stream'
            self.send_bytes(target.read_bytes(), content_type, headers)

        def do_POST(self):
            try:
                if not allowed_origin(
                    studio.root, self.headers.get('Origin'), self.server.server_port
                ):
                    return self.reply(
                        403,
                        {
                            'error': Msg(
                                'server.handler.requests_from_other_websites_are_not',
                                'Requests from other websites are not allowed.',
                            )
                        },
                    )
                if urlparse(self.path).path in ('/api/tools/upload', '/api/tools/mask'):
                    if studio.preview:
                        return self.reply(
                            403,
                            {
                                'error': Msg(
                                    'server.handler.uploads_are_off_on_the_preview',
                                    'Uploads are off on the preview server.',
                                )
                            },
                        )
                    return self.receive_upload()
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.reply(
                        415,
                        {
                            'error': Msg(
                                'server.handler.a_json_request_is_required',
                                'A JSON request is required.',
                            )
                        },
                    )
                size = int(self.headers.get('Content-Length', 0))
                if size < 0 or size > MAX_BODY_BYTES:
                    raise ValueError(
                        Msg('server.handler.the_request_is_too_large', 'The request is too large.')
                    )
                body = json.loads(self.rfile.read(size) or b'{}')
                path = urlparse(self.path).path
                if studio.preview and (
                    path.startswith(PREVIEW_BLOCKED_PREFIXES) or path in PREVIEW_BLOCKED_PATHS
                ):
                    return self.reply(
                        403,
                        {
                            'error': Msg(
                                'server.handler.the_preview_server_does_not_change',
                                'The preview server does not change the queue or ComfyUI.',
                            )
                        },
                    )
                if path in POST_ROUTES:
                    return self.reply(200, POST_ROUTES[path](studio, body))
                if path == '/api/gallery/export':
                    return self.send_export(body)
                if path.startswith('/api/jobs/'):
                    _, _, _, job_id, action = path.split('/')
                    if action in JOB_ACTIONS:
                        return self.reply(200, JOB_ACTIONS[action](studio, job_id))
                self.reply(
                    404, {'error': Msg('server.handler.request_not_found', 'Request not found.')}
                )
            except ConflictError as error:
                self.reply(409, {'error': message_of(error), 'conflict': True})
            except ExportIncomplete as error:
                self.reply(409, {'error': message_of(error), **error.summary})
            except Exception as error:
                logging.exception('API error')
                self.reply(400, {'error': message_of(error)})

        def receive_upload(self):
            """One file per request as the raw body; the name comes in ``X-File-Name``."""
            size = int(self.headers.get('Content-Length', 0))
            if size <= 0 or size > MAX_UPLOAD_BYTES:
                raise ValueError(
                    Msg(
                        'server.handler.the_file_is_empty_or_too', 'The file is empty or too large.'
                    )
                )
            raw = self.rfile.read(size)
            if urlparse(self.path).path == '/api/tools/mask':
                item_id = self.headers.get('X-Item-Id', '')
                kind = self.headers.get('X-Mask-Kind', 'censor')
                studio.tools.set_mask(item_id, raw, 'edited', kind)
                return self.reply(200, {'ok': True, 'item': studio.tools.get(item_id)})
            name = unquote(self.headers.get('X-File-Name', '') or 'upload')
            return self.reply(200, studio.tools.upload(name, raw))

        def send_export(self, body):
            archive, filename, summary = studio.review_store.plan_and_zip(body)
            try:
                self.send_response(200)
                self.send_header('Content-Type', 'application/zip')
                self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
                self.send_header('Content-Length', str(archive.stat().st_size))
                self.send_header(
                    'X-Export-Count', str(summary.get('count', summary.get('exported', 0)))
                )
                self.send_header(
                    'X-Export-Complete', 'true' if summary.get('complete') else 'false'
                )
                self.send_header('X-Export-Missing-Count', str(len(summary.get('missing', []))))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                with archive.open('rb') as source:
                    for chunk in iter(lambda: source.read(1024 * 1024), b''):
                        self.wfile.write(chunk)
            finally:
                archive.unlink(missing_ok=True)

    return Handler
