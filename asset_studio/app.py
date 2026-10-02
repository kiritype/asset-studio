"""Asset Studio server: a local front end for ComfyUI."""

import argparse
import json
import logging
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

from .compose import compose
from .gallery.listing import Gallery
from .gallery.reviews import ReviewStore
from .generation.comfy import Comfy
from .generation.control import ComfyControl
from .generation.lab import LabMixin
from .generation.queue import JobQueueMixin
from .generation.worker import WorkerMixin
from .gpu import GpuBroker
from .http.handler import handler_class
from .i18n import Msg
from .library.service import Library
from .library.store import LibraryStore, check_layout
from .lora.trainer import LoraTrainer
from .models import ModelProfiles
from .tags import TagLookup
from .tools.convert import ConvertTasks
from .tools.postprocess import PostprocessMixin
from .tools.tagger import TaggerMixin
from .tools.workspace import ToolWorkspace
from .util import state_file
from .validation.pipeline import ValidationPipeline

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
INTERRUPTED_MESSAGE = Msg(
    'server.app.the_app_stopped_before_the_result',
    'The app stopped before the result was collected. Check ComfyUI, then retry.',
)


class Studio(JobQueueMixin, LabMixin, TaggerMixin, PostprocessMixin, WorkerMixin):
    """Holds the services and the generation queue of one running server."""

    def __init__(self, root, comfy_url, start_worker=True, preview=False):
        self.root = Path(root).resolve()
        check_layout(self.root / 'data')
        self.store = LibraryStore(self.root)
        self.comfy = Comfy(comfy_url)
        self.lock = threading.RLock()
        self.preview = preview
        self.gallery = Gallery(self.root)
        self.models = ModelProfiles(self.root)
        self.review_store = ReviewStore(self.root, self.gallery)
        self.library = Library(self.store, self.lock)
        self.control = ComfyControl(self, preview=preview)
        self.stop = threading.Event()
        self.state_path = state_file(self.root, 'queue.json')
        self.jobs = []
        self.paused = False
        self._load_queue()
        self.gpu = GpuBroker(self.root, self.lock, lambda: self.jobs)
        self.validation = ValidationPipeline(self)
        self.lora = LoraTrainer(self)
        self.tags = TagLookup(self.root)
        self.tools = ToolWorkspace(self.root, self.gallery)
        self.converter = ConvertTasks(self.root, self.tools)
        if start_worker:
            threading.Thread(target=self.worker, daemon=True, name='asset-studio-worker').start()

    def compose(self, request, expression_ref=None, single=True, catalog=None):
        return compose(self.store, request, expression_ref, single, catalog)

    def _load_queue(self):
        if not self.state_path.exists():
            return
        saved = json.loads(self.state_path.read_text(encoding='utf-8'))
        self.jobs = saved.get('jobs', [])
        self.paused = bool(saved.get('paused', False))
        # A restart must never resume generation on its own.
        for job in self.jobs:
            if job['status'] in ('running', 'cancelling'):
                job.update(status='interrupted', error=INTERRUPTED_MESSAGE)
                self.paused = True
        if any(job['status'] == 'queued' for job in self.jobs):
            self.paused = True


def main():
    parser = argparse.ArgumentParser(description='Asset Studio server')
    parser.add_argument(
        '--root', default=str(DEFAULT_ROOT), help='folder that holds data/, outputs/ and static/'
    )
    parser.add_argument('--port', type=int, default=8195)
    parser.add_argument('--comfy-url', default='http://127.0.0.1:8188')
    parser.add_argument(
        '--preview',
        action='store_true',
        help='read-only server: no worker, no queue or ComfyUI changes',
    )
    parser.add_argument(
        '--static-root', help='serve the UI from another folder (isolated UI previews)'
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    (root / 'logs').mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        handlers=[
            logging.FileHandler(root / 'logs' / 'studio.log', encoding='utf-8'),
            logging.StreamHandler(),
        ],
    )
    app = Studio(root, args.comfy_url, start_worker=False, preview=args.preview)
    if args.static_root:
        app.static_root = Path(args.static_root).resolve()
    # Bind before starting the worker so a second launch cannot create a second queue worker.
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_class(app))
    if not args.preview:
        threading.Thread(target=app.worker, daemon=True).start()
    logging.info('Asset Studio: http://127.0.0.1:%s', args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop.set()
        server.server_close()
        # A preview server shares the real data/; only the real server owns the queue file.
        if not args.preview:
            with app.lock:
                app.persist()


if __name__ == '__main__':
    main()
