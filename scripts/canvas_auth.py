"""Interactive Canvas login. Sessions expire; re-run when the server rejects them.

No manual cookie copying. The private cache must never be shared or committed.
"""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit

SCRIPT_DIR = Path(__file__).resolve().parent
COOKIE_FILE = SCRIPT_DIR / '.canvas_cookies.json'
CANVAS_BASE = 'https://canvas.qut.edu.au'


def canvas_api_cookies(cookies, base_url=CANVAS_BASE):
    """Select cookies applicable to the exact Canvas API host/path; never fallback."""
    host = urlsplit(base_url).hostname or ''
    path = '/api/v1/users/self/profile'
    selected = []
    for cookie in cookies:
        domain = cookie.get('domain', '').lstrip('.').lower()
        cpath = cookie.get('path', '/') or '/'
        domain_matches = bool(domain) and (host == domain or host.endswith('.' + domain))
        path_matches = path == cpath or (path.startswith(cpath) and (cpath.endswith('/') or path[len(cpath):].startswith('/')))
        if domain_matches and path_matches and cookie.get('name') and cookie.get('value'):
            if cookie.get('expires', -1) > 0 and cookie['expires'] <= time.time():
                continue
            selected.append(cookie)
    return selected


def main():
    from playwright.sync_api import sync_playwright
    from qut_toolkit.storage import atomic_write
    print('Opening private Canvas browser. Sign in yourself and complete MFA if asked.')
    print('Credentials and session caches stay local; never share the profile or cache.')
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            str(SCRIPT_DIR / '.playwright_canvas_profile'), headless=False)
        try:
            page = context.new_page()
            page.goto(CANVAS_BASE, wait_until='domcontentloaded')
            deadline = time.monotonic() + 300
            verified = False
            while time.monotonic() < deadline:
                if urlsplit(page.url).hostname == 'canvas.qut.edu.au':
                    try:
                        response = context.request.get(CANVAS_BASE + '/api/v1/users/self/profile', timeout=10000, max_redirects=0)
                        verified = response.ok and isinstance(response.json(), dict) and bool(response.json().get('id'))
                        response.dispose()
                        if verified:
                            break
                    except Exception:
                        pass
                page.wait_for_timeout(2000)
            if not verified:
                raise RuntimeError('Canvas profile could not be verified. No new cookie cache was saved.')
            cookies = canvas_api_cookies(context.cookies(CANVAS_BASE + '/api/v1/users/self/profile'))
            if not cookies:
                raise RuntimeError('No Canvas API cookies available. No cache saved.')
            expiry = min([time.time() + 43200] + [c['expires'] for c in cookies if c.get('expires', -1) > 0])
            cache = {'base_url': CANVAS_BASE, 'expires': expiry,
                     'headers': {'Cookie': '; '.join(f"{c['name']}={c['value']}" for c in cookies)}}
            atomic_write(COOKIE_FILE, json.dumps(cache, indent=2).encode('utf-8'))
            try:
                COOKIE_FILE.chmod(0o600)
            except OSError:
                pass
            print('Verified Canvas profile; private API cache saved. Server expiry can occur earlier.')
        finally:
            context.close()


if __name__ == '__main__':
    main()
