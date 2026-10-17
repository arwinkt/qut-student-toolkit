"""Offline platform smoke: owned Chromium, synthetic cookies and loopback only.

Run after installing Playwright and its Chromium binary. Never opens a user profile
or contacts Canvas. This is not proof of institutional sign-in or MFA behavior.
"""
import json
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from qut_toolkit.browser import BrowserSession
from qut_toolkit.storage import atomic_write


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Deliberately public synthetic marker, not a credential.
        body = json.dumps({'synthetic': True, 'cookie_received':
                           'toolkit_smoke=synthetic' in self.headers.get('Cookie', '')}).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    try:
        with tempfile.TemporaryDirectory(prefix='qut-platform-') as temporary:
            root = Path(temporary) / 'Study files café'
            profile = root / 'private browser'
            profile.mkdir(parents=True)
            note = root / 'notes' / 'lecture.md'
            atomic_write(note, 'Synthetic lecture café\n'.encode('utf-8'))
            assert note.read_text(encoding='utf-8') == 'Synthetic lecture café\n'
            with BrowserSession(profile=profile) as session:
                assert session.context is not None
                session.context.add_cookies([{
                    'name': 'toolkit_smoke', 'value': 'synthetic', 'url': base,
                    'expires': time.time() + 3600,
                }])
                page = session.context.new_page()
                page.goto(base)
                assert json.loads(page.inner_text('body'))['synthetic']
                data, _ = session.transport(base, {}, 10)
                assert json.loads(data)['cookie_received']
            # A second actual process launch checks persistent-profile reuse.
            with BrowserSession(profile=profile) as session:
                data, _ = session.transport(base, {}, 10)
                assert json.loads(data)['cookie_received']
        print('PASS: Unicode/spaced paths, atomic write, Chromium launch, local page, '
              'cookie-scoped transport, persistent-profile reopen and cleanup.')
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=10)


if __name__ == '__main__':
    main()
