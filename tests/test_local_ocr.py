"""Offline OCR tests: only synthetic local documents and mocked recognizers."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from qut_toolkit import local_ocr as ocr
import scan_school as scanner


class LocalOCRTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        from PIL import Image
        self.image = self.root / 'scan.png'
        Image.new('RGB', (120, 50), 'white').save(self.image)

    def test_backend_options_and_uncertainty(self):
        backend = types.SimpleNamespace(image_to_string=mock.Mock(return_value='Actual words'))
        with mock.patch.dict(sys.modules, pytesseract=backend):
            text = ocr.extract_local_ocr(self.image, timeout=3, language='eng')
        self.assertIn('Actual words', text)
        self.assertIn('Image 1', text)
        self.assertIn('uncertain', text)
        options = backend.image_to_string.call_args.kwargs
        self.assertLessEqual(options['timeout'], 3)
        self.assertEqual(options['lang'], 'eng')
        self.assertEqual(options['config'], '--psm 3')

    def test_missing_backend_and_empty_are_incomplete(self):
        with mock.patch.dict(sys.modules, pytesseract=None):
            self.assertIn('[OCR INCOMPLETE:', ocr.extract_local_ocr(self.image))
        backend = types.SimpleNamespace(image_to_string=mock.Mock(return_value='   '))
        with mock.patch.dict(sys.modules, pytesseract=backend):
            self.assertIn('empty OCR', ocr.extract_local_ocr(self.image))
        backend.image_to_string.side_effect = RuntimeError('timeout')
        with mock.patch.dict(sys.modules, pytesseract=backend):
            self.assertIn('[OCR INCOMPLETE:', ocr.extract_local_ocr(self.image))

    def test_pixel_limit_prevents_backend_call(self):
        backend = types.SimpleNamespace(image_to_string=mock.Mock())
        with mock.patch.dict(sys.modules, pytesseract=backend):
            self.assertIn('pixel limit', ocr.extract_local_ocr(self.image, max_pixels=10))
        backend.image_to_string.assert_not_called()

    def test_embedded_office_images_and_native_duplicates(self):
        for ext, folder in [('docx', 'word'), ('pptx', 'ppt')]:
            path = self.root / ('slides.' + ext)
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(folder + '/media/image1.png', self.image.read_bytes())
                archive.writestr(folder + '/media/image2.png', self.image.read_bytes())
            backend = types.SimpleNamespace(image_to_string=mock.Mock(return_value='Native body'))
            with mock.patch.dict(sys.modules, pytesseract=backend):
                text = ocr.extract_local_ocr(path, native_text='Native body', max_pages=1)
            self.assertIn('already present', text)
            self.assertNotIn('\nNative body\n', text)
            self.assertIn('limit', text)
            self.assertEqual(backend.image_to_string.call_count, 1)

    @unittest.skipUnless(importlib.util.find_spec('fitz'), 'optional PyMuPDF not installed')
    def test_pdf_native_text_retained_with_page_ocr(self):
        import fitz
        pdf = self.root / 'scan.pdf'
        with fitz.open() as doc:
            page = doc.new_page()
            page.insert_text((72, 72), 'Native PDF text')
            doc.save(pdf)
        backend = types.SimpleNamespace(image_to_string=mock.Mock(return_value='Supplemental words'))
        with mock.patch.dict(sys.modules, pytesseract=backend):
            text = scanner.extract_file(pdf, use_ocr=True)
        self.assertIn('Native PDF text', text)
        self.assertIn('Page 1', text)
        self.assertIn('Supplemental words', text)

    def scan(self, **kwargs):
        with contextlib.redirect_stdout(io.StringIO()):
            return scanner.scan_and_convert(source=self.root, **kwargs)

    def test_default_off_mode_rerun_and_user_conflict(self):
        with mock.patch.object(ocr, 'extract_local_ocr', return_value='## Supplemental local OCR\nWords') as run:
            self.assertEqual(self.scan()['processed'], 1)
            run.assert_not_called()
            note = self.root / 'notes/scan.png.md'
            note.write_text('USER EDIT', encoding='utf-8')
            result = self.scan(use_ocr=True)
            self.assertEqual(result['conflicts'], 1)
            self.assertEqual(note.read_text(), 'USER EDIT')
            self.assertEqual(self.scan(use_ocr=True)['skipped'], 1)
            self.assertEqual(run.call_count, 1)
            data = json.loads((self.root / 'notes' / scanner.MANIFEST_NAME).read_text())
            self.assertTrue(data['files']['scan.png']['conflict']['ocr'])

    def test_incomplete_is_error_and_retried(self):
        with mock.patch.object(ocr, 'extract_local_ocr', return_value='[OCR INCOMPLETE: empty OCR]') as run:
            self.assertEqual(self.scan(use_ocr=True)['errors'], 1)
            self.assertEqual(self.scan(use_ocr=True)['errors'], 1)
            self.assertEqual(run.call_count, 2)

    def test_time_budget_missing_pdf_renderer_and_no_network(self):
        backend = types.SimpleNamespace(image_to_string=mock.Mock(return_value='Words'))
        with mock.patch.dict(sys.modules, pytesseract=backend), \
                mock.patch.object(ocr.time, 'monotonic', side_effect=[0, 100]), \
                mock.patch('socket.create_connection', side_effect=AssertionError('no network')):
            self.assertIn('time limit', ocr.extract_local_ocr(self.image, timeout=1))
        backend.image_to_string.assert_not_called()
        with mock.patch.dict(sys.modules, pytesseract=backend, fitz=None):
            result = ocr.extract_local_ocr(self.root / 'scan.pdf')
            self.assertIn('[OCR INCOMPLETE:', result)
            self.assertIn('PyMuPDF', result)

    @unittest.skipUnless(importlib.util.find_spec('fitz'), 'optional PyMuPDF not installed')
    def test_scanned_pdf_is_rendered_and_page_limit_reported(self):
        import fitz
        path = self.root / 'scanned.pdf'
        with fitz.open() as doc:
            for _ in range(2):
                page = doc.new_page()
                page.insert_image(page.rect, filename=str(self.image))
            doc.save(path)
        backend = types.SimpleNamespace(image_to_string=mock.Mock(return_value='Scanned text'))
        with mock.patch.dict(sys.modules, pytesseract=backend):
            text = ocr.extract_local_ocr(path, max_pages=1, max_pixels=10_000)
        self.assertIn('Scanned text', text)
        self.assertIn('Page 1', text)
        self.assertIn('[OCR INCOMPLETE:', text)
        self.assertIn('page limit', text)
        image = backend.image_to_string.call_args.args[0]
        self.assertLessEqual(image.width * image.height, 10_000)

    def test_office_native_bodies_preserved(self):
        for ext, extractor in [('docx', 'extract_docx'), ('pptx', 'extract_pptx')]:
            path = self.root / ('native.' + ext)
            with mock.patch.object(scanner, extractor, return_value='Native body'), \
                    mock.patch.object(ocr, 'extract_local_ocr', return_value='## Supplemental local OCR\nSupplement'):
                result = scanner.extract_file(path, use_ocr=True)
            self.assertTrue(result.startswith('Native body'))
            self.assertIn('Supplement', result)

    @unittest.skipUnless(importlib.util.find_spec('pytesseract'), 'optional pytesseract not installed')
    def test_real_local_smoke_if_installed(self):
        import shutil
        if not shutil.which('tesseract'):
            self.skipTest('Tesseract executable not on PATH')
        from PIL import Image, ImageDraw, ImageFont
        with Image.new('RGB', (1000, 180), 'white') as image:
            try:
                font = ImageFont.truetype('DejaVuSans.ttf', 48)
            except OSError:
                font = ImageFont.truetype('arial.ttf', 48)
            ImageDraw.Draw(image).text((20, 40), 'LOCAL OCR TEST 12345', font=font, fill='black')
            image.save(self.image)
        with mock.patch('socket.create_connection', side_effect=AssertionError('no network')):
            text = ocr.extract_local_ocr(self.image)
        self.assertNotIn('[OCR INCOMPLETE:', text)
        self.assertIn('LOCAL OCR TEST 12345', text)

    def test_cli_flag(self):
        with mock.patch.object(scanner, 'scan_and_convert', return_value={'errors': 0}) as run:
            self.assertEqual(scanner.main(['--ocr']), 0)
            self.assertTrue(run.call_args.kwargs['use_ocr'])


if __name__ == '__main__':
    unittest.main()
