"""Optional, host-only OCR; never downloads models or calls a network service.

Install Pillow and pytesseract in the scanner's Python environment, and install
Tesseract separately with local language data (English by default). The executable
must be on PATH. PDFs additionally need PyMuPDF. Windows, macOS and Linux work
where these dependencies are available. Limits apply to OCR supplements only;
existing native text extraction is intentionally unchanged.
"""
from difflib import SequenceMatcher
from io import BytesIO
from pathlib import Path
import math
import re
import time
import zipfile
import subprocess
import sys
import json

INCOMPLETE = '[OCR INCOMPLETE:'
SUPPORTED = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp',
             '.pdf', '.docx', '.pptx', '.pptm', '.ppsx'}


def _images(path, max_pages, max_pixels, deadline):
    """Yield bounded decoded images. No external Office relationships are followed."""
    from PIL import Image
    ext = path.suffix.lower()
    if ext == '.pdf':
        try:
            import fitz
        except ImportError as exc:
            raise RuntimeError('PDF OCR requires PyMuPDF: python -m pip install PyMuPDF') from exc
        with fitz.open(path) as doc:
            for index in range(min(len(doc), max_pages)):
                if time.monotonic() >= deadline:
                    raise RuntimeError('time limit reached')
                page = doc[index]
                width, height = page.rect.width, page.rect.height
                if width <= 0 or height <= 0:
                    raise RuntimeError('invalid PDF page dimensions')
                scale = min(2.0, math.sqrt(max_pixels / (width * height)) * .99)
                pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False,
                                      colorspace=fitz.csRGB)
                if pix.width * pix.height > max_pixels:
                    raise RuntimeError('pixel limit exceeded')
                with Image.frombytes('RGB', (pix.width, pix.height), pix.samples) as image:
                    yield f'Page {index + 1}', image
            if len(doc) > max_pages:
                raise RuntimeError('page limit reached; remaining pages not OCRed')
    elif ext in {'.docx', '.pptx', '.pptm', '.ppsx'}:
        folder = 'word/media/' if ext == '.docx' else 'ppt/media/'
        with zipfile.ZipFile(path) as archive:
            count = 0
            for info in archive.infolist():
                if not info.filename.startswith(folder) or info.is_dir():
                    continue
                if count >= max_pages:
                    raise RuntimeError('image limit reached; remaining images not OCRed')
                count += 1
                if time.monotonic() >= deadline:
                    raise RuntimeError('time limit reached')
                # Bound decompression as well as decoded pixels (including zip bombs).
                if info.file_size > 32 * 1024 * 1024:
                    raise RuntimeError('embedded image byte limit exceeded')
                with archive.open(info) as stream:
                    with Image.open(BytesIO(stream.read(32 * 1024 * 1024 + 1))) as image:
                        yield f'Image {count} ({info.filename})', image
    else:
        with Image.open(path) as image:
            for index in range(min(getattr(image, 'n_frames', 1), max_pages)):
                if time.monotonic() >= deadline:
                    raise RuntimeError('time limit reached')
                image.seek(index)
                yield f'Image {index + 1}', image
            if getattr(image, 'n_frames', 1) > max_pages:
                raise RuntimeError('image frame limit reached')


def _normalized(text):
    return ' '.join(re.findall(r'\w+', text.casefold()))


def _rapid_text(image, timeout):
    stream=BytesIO(); image.save(stream, format='PNG')
    result=subprocess.run([sys.executable, str(Path(__file__).with_name('rapid_ocr_worker.py'))],
                          input=stream.getvalue(), capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Local RapidOCR failed; install rapidocr-onnxruntime with its bundled model files')
    data=json.loads(result.stdout)
    text=str(data.get('text') or '')
    if data.get('low_confidence'):
        text += '\n[Low OCR confidence: verify the original image]'
    return text


def extract_local_ocr(path, native_text='', *, max_pages=20, max_pixels=8_000_000,
                      timeout=60, language='eng', backend='tesseract'):
    """Return labeled supplemental text, or an explicit INCOMPLETE marker.

    timeout is a document OCR budget, also passed to each Tesseract subprocess
    (at most 15s per image). Local parsing/rendering is checked between items;
    it is not a hard process-level timeout for native image/PDF decoders.
    max_pages also bounds Office images and animated-image frames. Oversized
    raster images are rejected before decoding; PDF renders are scaled to fit.
    """
    if backend not in ('tesseract','rapidocr'):
        raise ValueError('Expected a local OCR backend: tesseract or rapidocr')
    path = Path(path)
    if path.suffix.lower() not in SUPPORTED:
        return ''
    if max_pages < 1 or max_pixels < 1 or timeout <= 0:
        raise ValueError('OCR limits must be positive')
    parts = ['## Supplemental local OCR',
             '> OCR is uncertain: verify against the original; layout, formulas and characters may be wrong.']
    deadline = time.monotonic() + timeout
    try:
        try:
            from PIL import Image
            if backend == 'tesseract':
                import pytesseract
        except ImportError as exc:
            raise RuntimeError('missing local OCR dependencies: python -m pip install Pillow pytesseract; '
                               'install Tesseract and eng language data locally and put tesseract on PATH') from exc
        count = 0
        images = _images(path, max_pages, max_pixels, deadline)
        try:
            for label, image in images:
                count += 1
                parts.append(f'### {label}')
                if image.width * image.height > max_pixels:
                    raise RuntimeError('pixel limit exceeded')
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RuntimeError('time limit reached')
                with image.convert('RGB') as rgb:
                    try:
                        if backend == 'rapidocr':
                            text = _rapid_text(rgb, min(15, remaining)).strip()
                        else:
                            text = pytesseract.image_to_string(rgb, lang=language, config='--psm 3',
                                                              timeout=min(15, remaining)).strip()
                    except Exception as exc:
                        raise RuntimeError('local OCR failed (ensure the selected backend and language data are '
                                           f'installed on PATH): {exc}') from exc
                if not text:
                    parts.append(f'{INCOMPLETE} empty OCR; no text recognized]')
                    continue
                normalized = _normalized(text)
                native = _normalized(native_text)
                if normalized and native and (normalized in native or
                        SequenceMatcher(None, normalized, native).ratio() >= .9):
                    parts.append('[OCR text already present in native text; duplicate omitted]')
                else:
                    parts.append(text)
            if count == 0:
                if not native_text.strip() or native_text.lstrip().startswith(('[No extractable','[ERROR')):
                    parts.append(f'{INCOMPLETE} no embedded images and no usable native text]')
                else:
                    parts.append('[No embedded images to OCR]')
        finally:
            images.close()
    except Exception as exc:
        parts.append(f'{INCOMPLETE} {exc}]')
    return '\n\n'.join(parts)
