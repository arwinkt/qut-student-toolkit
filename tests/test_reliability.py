"""Offline reliability regressions: synthetic responses and real OS locks only."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from qut_toolkit.client import CanvasClient, CanvasError
from qut_toolkit.storage import Store, atomic_write


def sharing_error(code=32):
    error = PermissionError('synthetic sharing violation')
    error.winerror = code
    return error


class AtomicReliabilityTests(unittest.TestCase):
    def test_replace_sharing_errors_retry_same_complete_temp(self):
        for code in (32, 33):
            with self.subTest(code=code), tempfile.TemporaryDirectory() as d:
                target = Path(d) / 'file'
                target.write_bytes(b'old')
                real_replace = os.replace
                calls = []
                def replace(src, dst):
                    calls.append(Path(src))
                    self.assertEqual(Path(src).read_bytes(), b'new')
                    if len(calls) < 3:
                        raise sharing_error(code)
                    real_replace(src, dst)
                with patch('qut_toolkit.storage.os.replace', side_effect=replace), patch('time.sleep') as sleep:
                    atomic_write(target, b'new')
                self.assertEqual(target.read_bytes(), b'new')
                self.assertEqual(len(set(calls)), 1)
                self.assertEqual(sleep.call_count, 2)
                self.assertEqual(list(Path(d).glob('.qut-*')), [])

    def test_exhausted_save_keeps_disk_and_memory_checkpoint(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            store.save(complete=True)
            old = json.loads(json.dumps(store.manifest))
            disk = store.manifest_path.read_bytes()
            with patch('qut_toolkit.storage.os.replace', side_effect=sharing_error()), patch('time.sleep') as sleep:
                with self.assertRaises(OSError): store.save(complete=True)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(store.manifest, old)
            self.assertEqual(store.manifest_path.read_bytes(), disk)
            self.assertEqual(list(Path(d).glob('.qut-*')), [])

    def test_failed_put_does_not_publish_entry_or_partial_target(self):
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            real_replace = os.replace
            def replace(src, dst):
                if Path(dst).name == 'target': raise sharing_error()
                return real_replace(src, dst)
            with patch('qut_toolkit.storage.os.replace', side_effect=replace), patch('time.sleep'):
                with self.assertRaises(OSError): store.put('key', 'target', b'complete original')
            self.assertEqual(store.manifest['entries'], {})
            self.assertEqual(store.events, [])
            self.assertFalse((Path(d)/'target').exists())
            self.assertEqual(list(Path(d).rglob('.qut-*')), [])

    def test_nonsharing_permission_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            with patch('qut_toolkit.storage.os.replace', side_effect=PermissionError('denied')) as replace, patch('time.sleep') as sleep:
                with self.assertRaises(PermissionError): atomic_write(Path(d)/'file', b'x')
            self.assertEqual(replace.call_count, 1)
            sleep.assert_not_called()
            self.assertEqual(list(Path(d).glob('.qut-*')), [])


class RequestReliabilityTests(unittest.TestCase):
    def test_incomplete_read_retried_and_raw_http_auth_not_retried(self):
        from http.client import IncompleteRead
        transport = Mock(side_effect=[IncompleteRead(b'partial'), (b'{}', {})])
        with patch('time.sleep'):
            self.assertEqual(CanvasClient(transport=transport).get('/api/test'), {})
        for status in (401, 403):
            error = HTTPError('https://canvas.qut.edu.au/api/test', status, 'synthetic', {}, io.BytesIO())
            transport = Mock(side_effect=error)
            with patch('time.sleep') as sleep:
                with self.assertRaises(CanvasError): CanvasClient(transport=transport).get('/api/test')
            self.assertEqual(transport.call_count, 1)
            sleep.assert_not_called()

    def test_retry_budget_shared_between_redirect_hops(self):
        transport = Mock(side_effect=[CanvasError('network', 'synthetic'),
            (b'', {'Location':'/hop'}), CanvasError('network', 'synthetic'),
            (b'', {'Location':'/last'}), CanvasError('network', 'synthetic')])
        with patch('time.sleep') as sleep:
            with self.assertRaises(CanvasError): CanvasClient(transport=transport).get('/api/test')
        self.assertEqual(transport.call_count, 5)
        self.assertEqual(sleep.call_count, 2)

    def test_network_and_browser_canvaserror_retry_bounded(self):
        for error in (URLError('offline'), TimeoutError(), CanvasError('network', 'Browser request failed')):
            with self.subTest(error=error):
                transport = Mock(side_effect=[error, error, (b'{"ok":true}', {})])
                with patch('time.sleep') as sleep:
                    self.assertEqual(CanvasClient(transport=transport).get('/api/test'), {'ok': True})
                self.assertEqual(transport.call_count, 3)
                self.assertEqual(sleep.call_count, 2)
                self.assertLessEqual(sum(c.args[0] for c in sleep.call_args_list), 4)

    def test_native_429_honors_clamped_retry_after(self):
        client = CanvasClient()
        response = Mock()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'{}'
        response.headers = {}
        error = HTTPError('https://canvas.qut.edu.au/api/test', 429, 'rate', {'Retry-After': '999999'}, io.BytesIO())
        with patch.object(client.opener, 'open', side_effect=[error, response]) as opened, patch('time.sleep') as sleep:
            self.assertEqual(client.get('/api/test'), {})
        self.assertEqual(opened.call_count, 2)
        sleep.assert_called_once_with(2.0)
        self.assertTrue(error.fp is None or error.fp.closed)

    def test_transient_statuses_retry_and_auth_never_retries(self):
        for status in (429, 500, 502, 503, 504, 401, 403):
            with self.subTest(status=status):
                transport = Mock(side_effect=CanvasError('http', 'synthetic', status))
                with patch('time.sleep'):
                    with self.assertRaises(CanvasError): CanvasClient(transport=transport).get('/api/test')
                self.assertEqual(transport.call_count, 1 if status in (401, 403) else 3)

    def test_returned_browser_status_not_accepted_as_success(self):
        transport = Mock(side_effect=[(b'busy', {'_status': 503, 'Retry-After':'0'}), (b'{}', {})])
        with patch('time.sleep'):
            self.assertEqual(CanvasClient(transport=transport).get('/api/test'), {})
        self.assertEqual(transport.call_count, 2)

    def test_unsafe_redirect_login_html_and_http_fail_without_retry(self):
        for headers, body in (({'Location':'http://evil.invalid'}, b''), ({}, b'<html><title>Sign in</title></html>')):
            transport = Mock(return_value=(body, headers))
            with patch('time.sleep') as sleep:
                with self.assertRaises(CanvasError): CanvasClient(transport=transport).get('/api/test')
            self.assertEqual(transport.call_count, 1)
            sleep.assert_not_called()

    def test_off_origin_retry_does_not_restore_credentials(self):
        seen = []
        def transport(url, headers, timeout):
            seen.append((url, headers))
            if len(seen) == 1: return b'', {'Location':'https://cdn.invalid/file'}
            if len(seen) == 2: raise CanvasError('network', 'synthetic')
            return b'data', {}
        with patch('time.sleep'):
            self.assertEqual(CanvasClient(headers={'Cookie':'synthetic'}, transport=transport).download('/file'), b'data')
        for _, headers in seen[1:]: self.assertNotIn('Cookie', headers)

    def test_retry_delay_parser(self):
        from qut_toolkit.retry import retry_delay
        self.assertEqual(retry_delay(0, '1'), 1)
        self.assertEqual(retry_delay(0, '-1'), 0.25)
        self.assertEqual(retry_delay(0, 'NaN'), 0.25)
        self.assertEqual(retry_delay(0, 'Infinity'), 0.25)
        self.assertEqual(retry_delay(0, 'Thu, 01 Jan 1970 00:01:40 GMT', now=99), 1)
        self.assertEqual(retry_delay(0, '999999999'), 2)


class WriterLockTests(unittest.TestCase):
    def test_reparse_root_guard_without_symlink_privileges(self):
        from qut_toolkit.locking import writer_lock
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)/'linked'
            with patch('qut_toolkit.locking._is_link', side_effect=lambda p: p == root):
                with self.assertRaises(ValueError):
                    with writer_lock(root): pass
                with self.assertRaises(ValueError): Store(root)
            self.assertFalse(root.exists())

    def test_exception_releases_and_nested_lock_refused(self):
        from qut_toolkit.locking import writer_lock, WriterLockError
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(RuntimeError, 'synthetic'):
                with writer_lock(d):
                    with self.assertRaises(WriterLockError):
                        with writer_lock(d): pass
                    raise RuntimeError('synthetic')
            with writer_lock(d): pass

    def test_real_process_contention_and_death_release(self):
        from qut_toolkit.locking import writer_lock, WriterLockError
        code = "import sys;sys.path.insert(0,sys.argv[1]);from qut_toolkit.locking import writer_lock;\nwith writer_lock(sys.argv[2]):\n print('LOCKED',flush=True);sys.stdin.read()"
        with tempfile.TemporaryDirectory() as d:
            child = subprocess.Popen([sys.executable, '-u', '-c', code, str(SCRIPTS), d], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                # communicate(timeout) bounds readiness and keeps the child alive via inherited input.
                import threading
                ready = []
                reader = threading.Thread(target=lambda: ready.append(child.stdout.readline()), daemon=True)
                reader.start(); reader.join(10)
                self.assertFalse(reader.is_alive(), 'child lock acquisition timed out')
                self.assertEqual(ready, ['LOCKED\n'])
                with self.assertRaises(WriterLockError):
                    with writer_lock(d): pass
                child.kill(); child.wait(timeout=10)
                with writer_lock(d): pass
            finally:
                if child.poll() is None: child.kill()
                child.communicate(timeout=10)

    def test_linked_root_and_linked_lock_rejected(self):
        from qut_toolkit.locking import writer_lock
        with tempfile.TemporaryDirectory() as d:
            base = Path(d); real = base/'real'; real.mkdir()
            alias = base/'alias'
            try: alias.symlink_to(real, target_is_directory=True)
            except OSError: self.skipTest('symlink privilege unavailable')
            for root in (alias, alias/'nested'):
                with self.assertRaises(ValueError):
                    with writer_lock(root): pass
                with self.assertRaises(ValueError): Store(root)
            lock = real/'.qut-writer.lock'
            victim = base/'victim'; victim.write_bytes(b'untouched')
            lock.symlink_to(victim)
            with self.assertRaises(ValueError):
                with writer_lock(real): pass
            self.assertEqual(victim.read_bytes(), b'untouched')


if __name__ == '__main__': unittest.main()
