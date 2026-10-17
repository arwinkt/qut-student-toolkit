import sys,unittest,subprocess
from pathlib import Path
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from qut_toolkit import local_ocr

class Image:
    def save(self, stream, format):stream.write(b'synthetic-png')

class RapidOCRTests(unittest.TestCase):
    def test_local_worker_has_bounded_timeout_and_no_document_path(self):
        result=subprocess.CompletedProcess([],0,b'{"text":"Local words","low_confidence":true}',b'')
        with mock.patch('subprocess.run',return_value=result) as run:
            text=local_ocr._rapid_text(Image(),3)
        self.assertIn('Local words',text);self.assertIn('confidence',text)
        self.assertEqual(run.call_args.kwargs['timeout'],3)
        self.assertEqual(run.call_args.kwargs['input'],b'synthetic-png')
        self.assertTrue(run.call_args.args[0][1].endswith('rapid_ocr_worker.py'))

    def test_worker_failure_is_not_exposed_as_fake_text(self):
        result=subprocess.CompletedProcess([],1,b'',b'private error text')
        with mock.patch('subprocess.run',return_value=result):
            with self.assertRaisesRegex(RuntimeError,'RapidOCR'):
                local_ocr._rapid_text(Image(),1)

    def test_invalid_backend_is_rejected(self):
        with self.assertRaises(ValueError):local_ocr.extract_local_ocr('synthetic.png',backend='network')
