"""Optional browser identity attachment. Never copy a login or close the user's browser."""
from urllib.parse import urlsplit
from .client import CanvasError, origin


def validate_cdp(url):
    try:
        p=urlsplit(url)
        if p.scheme not in ('http','https') or p.hostname not in ('127.0.0.1','localhost','::1') or p.username or p.password or p.query or p.fragment:
            raise ValueError
        if p.port is None:
            raise ValueError
    except (ValueError,TypeError):
        raise ValueError('CDP URL must be an explicit loopback address and port') from None
    return url


class BrowserSession:
    def __init__(self, cdp_url=None, base_url='https://canvas.qut.edu.au', timeout=30, profile=None):
        if cdp_url:
            validate_cdp(cdp_url)
        self.owned = not bool(cdp_url)
        self.base_url=base_url.rstrip('/')
        self.canvas_origin=origin(base_url)
        self.timeout=timeout
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise CanvasError('dependency','Install Playwright to use browser attachment') from None
        self.manager=sync_playwright().start()
        try:
            if cdp_url:
                self.browser=self.manager.chromium.connect_over_cdp(cdp_url,timeout=15000)
                self.context=next((c for c in self.browser.contexts if any(urlsplit(p.url).hostname==self.canvas_origin[1] for p in c.pages)),None)
                if self.context is None:
                    raise CanvasError('auth','Open an authenticated Canvas tab in the selected browser first')
            else:
                from pathlib import Path
                directory=Path(profile) if profile else Path(__file__).resolve().parents[1]/'.playwright_canvas_profile'
                if not directory.is_dir():
                    raise CanvasError('auth','No browser login profile; run scripts/canvas_auth.py first')
                self.context=self.manager.chromium.launch_persistent_context(str(directory),headless=True)
        except Exception:
            self.manager.stop()
            raise CanvasError('browser','Could not open the authenticated browser; verify login/profile and close concurrent profile users') from None

    def transport(self,url,headers,timeout):
        # APIRequestContext scopes stored browser cookies by target URL; never supply
        # Canvas Cookie/Authorization headers. CanvasClient handles redirect boundaries.
        clean={k:v for k,v in headers.items() if k.lower() not in ('cookie','authorization','x-csrf-token')}
        try:
            r=self.context.request.get(url,headers=clean,timeout=timeout*1000,max_redirects=0)
            try:
                status=r.status
                response_headers=dict(r.headers)
                if status in (301,302,303,307,308):
                    return b'',response_headers
                if not r.ok:
                    kind='auth' if status==401 else 'access' if status==403 else 'http'
                    raise CanvasError(kind,'Browser request rejected',status)
                return r.body(),response_headers
            finally:
                r.dispose()
        except CanvasError:
            raise
        except Exception:
            raise CanvasError('network','Browser request failed or timed out') from None

    def close(self):
        # Stop the client connection only; never browser.close() on an attached browser.
        if self.owned:
            self.context.close()
        self.manager.stop()

    def __enter__(self):
        return self

    def __exit__(self,*args):
        self.close()
