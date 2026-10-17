"""Scanner publication uses the shared bounded atomic-replacement policy."""
from pathlib import Path
import os,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import scan_school

class ScannerAtomicTests(unittest.TestCase):
    def test_scanner_retries_sharing_failure_without_partial_publication(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d).resolve()/'note.md';target.write_text('old')
            original=os.replace;calls=[]
            def replace(source,dest):
                calls.append(source)
                self.assertEqual(target.read_text(),'old')
                self.assertEqual(Path(source).read_text(),'new')
                if len(calls)<3:
                    error=PermissionError('synthetic sharing violation');error.winerror=32;raise error
                original(source,dest)
            with patch('qut_toolkit.storage.os.replace',side_effect=replace),patch('time.sleep') as sleep:
                scan_school._atomic_write(target,'new')
            self.assertEqual(target.read_text(),'new')
            self.assertEqual(len(calls),3);self.assertEqual(sleep.call_count,2)
            self.assertEqual(list(target.parent.iterdir()),[target])

    def test_scanner_permission_denial_never_retried(self):
        with tempfile.TemporaryDirectory() as d:
            target=Path(d).resolve()/'note.md';target.write_text('old')
            with patch('qut_toolkit.storage.os.replace',side_effect=PermissionError('synthetic denied')) as replace,patch('time.sleep') as sleep:
                with self.assertRaises(PermissionError):scan_school._atomic_write(target,'new')
            self.assertEqual(target.read_text(),'old');self.assertEqual(replace.call_count,1);sleep.assert_not_called()
            self.assertEqual(list(target.parent.iterdir()),[target])
