"""Synthetic offline fixtures only; no student data."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from qut_toolkit.config import load_config
from qut_toolkit.storage import Store, safe_component
from qut_toolkit.client import CanvasClient, CanvasError

class CoreTests(unittest.TestCase):
    def test_precedence(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'config.json'
            p.write_text(json.dumps({'root': d+'/config'}))
            with patch.dict(os.environ, {'QUT_STUDY_ROOT': d+'/env'}):
                # Windows runner temp paths can use an 8.3 alias; configuration
                # deliberately canonicalizes paths, so compare resolved targets.
                self.assertEqual(load_config(p).root, Path(d+'/config').resolve())
                self.assertEqual(load_config(p, root=d+'/cli').root, Path(d+'/cli').resolve())
                self.assertEqual(load_config(Path(d)/'missing.json').root, Path(d+'/env').resolve())
    def test_safe_names_and_ids(self):
        for name in ['../CON', 'NUL', 'a/b:c*?', '..', 'aux.txt']:
            result = safe_component(name)
            self.assertNotIn('/', result)
            self.assertNotIn('\\', result)
            self.assertNotIn(result.split('.')[0].upper(), ['CON','NUL','AUX'])
    def test_content_hash_local_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            s = Store(Path(d).resolve())
            self.assertEqual(s.put('page:1', 'pages/1.md', b'one'), 'added')
            s.save()
            s = Store(Path(d).resolve())
            self.assertEqual(s.put('page:1', 'pages/1.md', b'one'), 'unchanged')
            (Path(d)/'pages/1.md').write_bytes(b'edit')
            self.assertEqual(s.put('page:1', 'pages/1.md', b'two'), 'conflict')
            self.assertEqual((Path(d)/'pages/1.md').read_bytes(), b'edit')
            s.save()
            s = Store(Path(d).resolve())
            s.put('page:1', 'pages/1.md', b'two')
            self.assertEqual(len(list((Path(d)/'conflicts').glob('*'))), 1)
            self.assertTrue(any(p.read_bytes() == b'one' for p in (Path(d)/'originals').rglob('*') if p.is_file()))
    def test_storage_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(ValueError): Store(Path(d).resolve()).put('x', '../bad', b'x')
    def test_client_pagination_and_late_error(self):
        seen=[]
        def transport(url, headers, timeout):
            seen.append((url,headers,timeout))
            if 'page=2' in url: raise CanvasError('network', 'synthetic timeout')
            return b'[{"id":1}]', {'Link':'<https://canvas.qut.edu.au/api/v1/courses?page=2>; rel="next"'}
        c=CanvasClient(headers={'Cookie':'synthetic'}, transport=transport)
        with self.assertRaises(CanvasError): c.list('/api/v1/courses')
        # Supersedes immediate network-failure behavior: one first-page GET,
        # then the shared budget of three bounded attempts for page two.
        self.assertEqual(len(seen),4)
        self.assertTrue(all('page=2' in x[0] for x in seen[1:]))
    def test_off_origin_pagination_rejected(self):
        c=CanvasClient(transport=lambda *a:(b'[]',{'Link':'<https://evil.invalid/x>; rel="next"'}))
        with self.assertRaises(CanvasError): c.list('/api/v1/courses')
    def test_download_no_credentials_off_origin(self):
        seen=[]
        c=CanvasClient(headers={'Cookie':'synthetic','Authorization':'secret'},transport=lambda u,h,t:(seen.append(h) or b'data',{}))
        c.download('https://cdn.invalid/file?signature=secret')
        self.assertNotIn('Cookie', seen[0])
        self.assertNotIn('Authorization', seen[0])

if __name__ == '__main__': unittest.main()
