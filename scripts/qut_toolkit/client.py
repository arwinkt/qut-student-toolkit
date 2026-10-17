"""Timeout-bounded Canvas transport. Never forward auth across origin boundaries."""
import json
from http.client import HTTPException
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from .retry import MAX_ATTEMPTS, retry_delay


def origin(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise CanvasError('unsafe_url', 'Only HTTPS URLs without embedded credentials are allowed')
    try: port = p.port or 443
    except ValueError as exc: raise CanvasError('unsafe_url', 'Invalid port') from exc
    return p.scheme, p.hostname.lower(), port


def public_url(url):
    """Stable source reference, never retain query signatures or credentials."""
    p = urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        return ''
    return urlunsplit((p.scheme, p.netloc, p.path, '', ''))


class CanvasError(Exception):
    def __init__(self, kind, message, status=None, retry_after=None):
        super().__init__(message)
        self.kind, self.status = kind, status
        self.retry_after = retry_after
    def as_dict(self):
        return {'kind': self.kind, 'message': str(self), 'status': self.status}


def validate_download(data, expected_type=None, headers=None):
    """Reject successful sign-in/error HTML masquerading as a course resource."""
    if not isinstance(data,bytes):
        raise CanvasError('response','Expected binary resource content')
    sample=data[:16384].decode('utf-8',errors='ignore').lstrip('\ufeff \t\r\n').lower()
    content_type=str((headers or {}).get('content-type','')).lower()
    looks_html='text/html' in content_type or sample.startswith(('<!doctype html','<html'))
    if looks_html:
        # A password field alone is not a login page: teaching HTML can contain
        # password generators, form exercises or Wi-Fi configuration tools.
        auth=re.search(r'login\.microsoftonline\.com|<title>\s*(?:sign[ -]?in|log[ -]?in)|id\s*=\s*[\"\']login_form',sample)
        if auth:
            raise CanvasError('auth','Received a sign-in page instead of a course resource')
        if expected_type and str(expected_type).split(';')[0].lower() not in ('text/html','application/xhtml+xml'):
            raise CanvasError('response','Unexpected HTML instead of the advertised resource type')
    return data


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CanvasClient:
    def __init__(self, base_url='https://canvas.qut.edu.au', headers=None, timeout=30, transport=None):
        self.base_url = base_url.rstrip('/')
        self.origin = origin(self.base_url)
        self.headers = {k:v for k,v in (headers or {}).items() if k.lower() in ('cookie','authorization','x-csrf-token')}
        self.timeout = timeout
        self.transport = transport or self._transport
        self.opener = build_opener(NoRedirect())

    @classmethod
    def from_config(cls, config):
        try:
            cache = json.loads(config.cookie_cache.read_text(encoding='utf-8'))
        except (OSError, ValueError) as exc:
            raise CanvasError('auth', 'Cookie cache missing or invalid; run scripts/canvas_auth.py') from exc
        if not isinstance(cache, dict):
            raise CanvasError('auth', 'Invalid cookie cache')
        if cache.get('expires') and float(cache['expires']) <= time.time():
            raise CanvasError('auth', 'Cached session expired; refresh Canvas authentication')
        if origin(cache.get('base_url', config.base_url)) != origin(config.base_url):
            raise CanvasError('auth', 'Cookie cache origin does not match configured Canvas origin')
        headers = cache.get('headers', {})
        if not isinstance(headers,dict) or not any(k.lower() in ('cookie','authorization') for k in headers):
            raise CanvasError('auth', 'Cookie cache contains no Canvas credentials')
        return cls(config.base_url, headers, config.timeout)

    @classmethod
    def from_cdp(cls, config, cdp_url='http://127.0.0.1:9222'):
        from .browser import BrowserSession
        session = BrowserSession(cdp_url, config.base_url, config.timeout)
        client = cls(config.base_url, timeout=config.timeout, transport=session.transport)
        client.browser_session = session
        return client

    def close(self):
        session = getattr(self, 'browser_session', None)
        if session:
            session.close()
            self.browser_session = None

    def _transport(self, url, headers, timeout):
        try:
            with self.opener.open(Request(url, headers=headers), timeout=timeout) as r:
                return r.read(), dict(r.headers)
        except HTTPError as exc:
            try:
                if exc.code in (301,302,303,307,308):
                    return b'', {'Location': exc.headers.get('Location',''), '_status':exc.code}
                kind = 'auth' if exc.code == 401 else 'access' if exc.code == 403 else 'http'
                raise CanvasError(kind, 'Canvas request rejected', exc.code,
                                  (exc.headers or {}).get('Retry-After')) from None
            finally:
                exc.close()
        except (URLError, TimeoutError, OSError, HTTPException) as exc:
            raise CanvasError('network', 'Network request failed or timed out') from None

    def _request(self, url, api=False):
        url = urljoin(self.base_url + '/', url)
        initial = origin(url)
        if api and initial != self.origin:
            raise CanvasError('unsafe_url','API URL must have exact Canvas origin')
        # Once a redirect leaves Canvas, credentials stay stripped on the entire chain.
        auth_allowed = initial == self.origin
        # A shared budget across the entire redirect chain: two extra GETs maximum.
        failures = 0
        for _ in range(11):
            target = origin(url)
            if api and target != self.origin:
                raise CanvasError('auth', 'API redirected away from Canvas; session may have expired')
            auth_allowed = auth_allowed and target == self.origin
            headers = {'Accept':'application/json' if api else '*/*', 'User-Agent':'qut-toolkit/0.1'}
            if auth_allowed: headers.update(self.headers)
            while True:
                try:
                    try:
                        body, response_headers = self.transport(url, headers, self.timeout)
                    except HTTPError as exc:
                        # HTTPError is also URLError/OSError: classify auth first.
                        try:
                            kind = 'auth' if exc.code == 401 else 'access' if exc.code == 403 else 'http'
                            raise CanvasError(kind, 'Canvas request rejected', exc.code,
                                              (exc.headers or {}).get('Retry-After')) from None
                        finally:
                            exc.close()
                    except (URLError, OSError, TimeoutError, HTTPException):
                        raise CanvasError('network','Network request failed or timed out') from None
                    response_headers = {k.lower():v for k,v in response_headers.items()}
                    status = int(response_headers.get('_status', 200))
                    if status >= 400:
                        kind = 'auth' if status == 401 else 'access' if status == 403 else 'http'
                        raise CanvasError(kind, 'Canvas request rejected', status,
                                          response_headers.get('retry-after'))
                    break
                except CanvasError as exc:
                    retryable = (exc.status not in (401, 403) and
                                 (exc.kind == 'network' or
                                  (exc.kind == 'http' and exc.status is not None and
                                   (exc.status == 429 or 500 <= exc.status <= 599))))
                    if not retryable or failures >= MAX_ATTEMPTS - 1:
                        raise
                    time.sleep(retry_delay(failures, exc.retry_after))
                    failures += 1
            if 'location' not in response_headers:
                return body, response_headers
            url = urljoin(url, response_headers['location'])
        raise CanvasError('redirect', 'Too many redirects')

    def get(self, path):
        body, _ = self._request(path, api=True)
        try: result = json.loads(body)
        except (ValueError, UnicodeError):
            raise CanvasError('auth' if body.lstrip().startswith(b'<') else 'response', 'Expected JSON; check authentication') from None
        if not isinstance(result,dict): raise CanvasError('response','Expected a JSON object')
        return result

    def list(self, path):
        url = urljoin(self.base_url+'/',path)
        seen, result = set(), []
        while url:
            if url in seen: raise CanvasError('pagination','Pagination loop detected')
            if len(seen) >= 10000: raise CanvasError('pagination','Pagination limit exceeded')
            seen.add(url)
            body, headers = self._request(url, api=True)
            try: page=json.loads(body)
            except (ValueError, UnicodeError): raise CanvasError('response','Expected a JSON collection; check authentication') from None
            if not isinstance(page,list): raise CanvasError('response','Expected a JSON collection')
            result.extend(page)
            next_links = re.findall(r'<([^>]+)>\s*;\s*rel=["\']?next["\']?', str(headers.get('link','')), re.I)
            if len(next_links)>1: raise CanvasError('pagination','Multiple next links')
            url=urljoin(url,next_links[0]) if next_links else ''
            if url and origin(url)!=self.origin: raise CanvasError('pagination','Off-origin pagination rejected')
        return result

    def download(self, url):
        data,headers=self._request(url)
        return validate_download(data,headers=headers)
