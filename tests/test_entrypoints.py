import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import canvas
import qut_sync
from qut_toolkit.browser import validate_cdp
from qut_toolkit.client import CanvasError


class EntrypointTests(unittest.TestCase):
    def test_legacy_pull_forwards_to_safe_sync(self):
        with patch.object(qut_sync,'main',return_value=0) as main:
            self.assertEqual(canvas.main(['pull','7','--root','synthetic-output']),0)
        self.assertEqual(main.call_args.args[0],['sync','7','--root','synthetic-output'])

    def test_legacy_check_is_real_not_cache_presence(self):
        class Client:
            closed=False
            def get(self,path):
                raise CanvasError('auth','synthetic rejected')
            def close(self):self.closed=True
        c=Client()
        with patch.object(canvas.CanvasClient,'from_config',return_value=c),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(canvas.main(['check']),1)
        self.assertTrue(c.closed)

    def test_loopback_only_browser_attachment(self):
        self.assertEqual(validate_cdp('http://127.0.0.1:9222'),'http://127.0.0.1:9222')
        for url in ('http://example.test:9222','http://localhost','file:///a','http://user:secret@127.0.0.1:9222','http://localhost:9222/?token=x'):
            with self.subTest(url=url),self.assertRaises(ValueError):validate_cdp(url)

    def test_cli_help_without_optional_dependencies(self):
        root=Path(__file__).parents[1]
        for name in ('qut_sync.py','qut_transcripts.py','canvas.py','scan_school.py'):
            r=subprocess.run([sys.executable,'-B',str(root/'scripts'/name),'--help'],capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertIn('usage:',r.stdout)

if __name__=='__main__':unittest.main()
