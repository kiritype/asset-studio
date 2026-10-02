import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from asset_studio.generation.comfy import Comfy


class ComfyResponseTests(unittest.TestCase):
    def test_real_empty_http_response_and_json(self):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length', 0)))
                self.send_response(200)
                self.end_headers()
                if self.path == '/json':
                    self.wfile.write(b'{"ok":true}')
                if self.path == '/bad':
                    self.wfile.write(b'not json')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            client = Comfy('http://127.0.0.1:' + str(server.server_port))
            self.assertIsNone(client.request('/free', {'unload_models': True}))
            self.assertEqual(client.request('/free', {}, raw=True), b'')
            self.assertEqual(client.request('/json', {}), {'ok': True})
            with self.assertRaises(json.JSONDecodeError):
                client.request('/bad', {})
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
