"""Convert QUT Study documents to local notes; paid image vision is opt-in."""

import os
import re
import sys
import json
import base64
import argparse
import hashlib
import tempfile
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

def resolve_paths(source=None, output=None, vault=None):
    """Explicit CLI paths win over legacy environment configuration."""
    source = Path(source or os.environ.get("QUT_STUDY_ROOT") or
                  os.environ.get("SCHOOL_DIR") or Path.home() / "QUT Study").expanduser()
    if output is not None and vault is not None:
        raise ValueError("Choose --output or --vault, not both")
    if output is not None:
        destination = Path(output)
    elif vault is not None:
        destination = Path(vault) / "education"
    elif os.environ.get("NOTES_DIR"):
        destination = Path(os.environ["NOTES_DIR"])
    elif os.environ.get("VAULT_DIR"):
        destination = Path(os.environ["VAULT_DIR"]) / "education"
    else:
        destination = source / "notes"
    return source, destination.expanduser()


# Backward-compatible path constants; per-call configuration is resolved at runtime.
SCHOOL_DIR, OUTPUT_DIR = resolve_paths()
VAULT_DIR = Path(os.environ["VAULT_DIR"]).expanduser() if os.environ.get("VAULT_DIR") else None

# ── File type groups ───────────────────────────────────────────────────────
DOCUMENT_EXTS  = {".pdf", ".docx", ".doc", ".txt", ".md"}
SLIDE_EXTS     = {".pptx", ".pptm", ".ppsx", ".ppt"}
SHEET_EXTS     = {".xlsx", ".xls", ".csv"}
IMAGE_EXTS     = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
DIAGRAM_EXTS   = {".drawio"}
CODE_EXTS      = {".py", ".js", ".html", ".css", ".json", ".xml", ".yaml", ".yml"}
ALL_SUPPORTED  = DOCUMENT_EXTS | SLIDE_EXTS | SHEET_EXTS | IMAGE_EXTS | DIAGRAM_EXTS | CODE_EXTS

SKIP_DIRS  = {".obsidian", ".smart-env", ".claude", "node_modules", "__pycache__", "state", "venv", "env", "notes"}
SKIP_FILES = {"thumbs.db", ".ds_store"}

# ── Utility ────────────────────────────────────────────────────────────────

def safe_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    return re.sub(r"\s+", " ", name).strip()


def file_to_base64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


# ── Extractors ─────────────────────────────────────────────────────────────

def extract_pdf(path: Path) -> str:
    try:
        import pdfplumber
        parts = []
        with pdfplumber.open(path) as pdf:
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text()
                if text and text.strip():
                    parts.append(f"<!-- Page {i} -->\n{text.strip()}")
        return "\n\n".join(parts) or "[No extractable text found in PDF]"
    except ImportError:
        return "[ERROR: pdfplumber not installed — pip install pdfplumber]"
    except Exception as e:
        return f"[ERROR reading PDF: {e}]"


def extract_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(path)
        parts = []
        for para in doc.paragraphs:
            if not para.text.strip():
                continue
            style = para.style.name if para.style else ""
            if   "Heading 1" in style: parts.append(f"# {para.text.strip()}")
            elif "Heading 2" in style: parts.append(f"## {para.text.strip()}")
            elif "Heading 3" in style: parts.append(f"### {para.text.strip()}")
            else:                      parts.append(para.text.strip())
        for table in doc.tables:
            rows = []
            for row in table.rows:
                cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                rows.append("| " + " | ".join(cells) + " |")
            if rows:
                sep = "| " + " | ".join(["---"] * len(table.rows[0].cells)) + " |"
                rows.insert(1, sep)
                parts.append("\n".join(rows))
        return "\n\n".join(parts) or "[No extractable text found in DOCX]"
    except ImportError:
        return "[ERROR: python-docx not installed — pip install python-docx]"
    except Exception as e:
        return f"[ERROR reading DOCX: {e}]"


def extract_pptx(path: Path) -> str:
    try:
        from pptx import Presentation
        prs = Presentation(path)
        slides = []
        for i, slide in enumerate(prs.slides, 1):
            texts = []
            # Slide title first if available
            if slide.shapes.title and slide.shapes.title.text.strip():
                texts.append(f"**{slide.shapes.title.text.strip()}**")
            for shape in slide.shapes:
                if shape == slide.shapes.title:
                    continue
                if hasattr(shape, "text") and shape.text.strip():
                    texts.append(shape.text.strip())
                # Extract table content from slides
                if shape.has_table:
                    rows = []
                    for row in shape.table.rows:
                        cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                        rows.append("| " + " | ".join(cells) + " |")
                    if rows:
                        sep = "| " + " | ".join(["---"] * len(shape.table.rows[0].cells)) + " |"
                        rows.insert(1, sep)
                        texts.append("\n".join(rows))
            if texts:
                slides.append(f"### Slide {i}\n\n" + "\n\n".join(texts))
        return "\n\n---\n\n".join(slides) or "[No extractable text found in PPTX]"
    except ImportError:
        return "[ERROR: python-pptx not installed — pip install python-pptx]"
    except Exception as e:
        return f"[ERROR reading PPTX: {e}]"


def extract_xlsx(path: Path) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(path, data_only=True)
        parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                continue
            md_rows = []
            for row in rows:
                if any(c is not None for c in row):
                    md_rows.append("| " + " | ".join(str(c) if c is not None else "" for c in row) + " |")
            if md_rows:
                sep = "| " + " | ".join(["---"] * len(rows[0])) + " |"
                md_rows.insert(1, sep)
                parts.append(f"## Sheet: {sheet_name}\n\n" + "\n".join(md_rows))
        return "\n\n".join(parts) or "[No data found in XLSX]"
    except ImportError:
        return "[ERROR: openpyxl not installed — pip install openpyxl]"
    except Exception as e:
        return f"[ERROR reading XLSX: {e}]"


def extract_csv(path: Path) -> str:
    try:
        import csv
        rows = []
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            reader = csv.reader(f)
            for row in reader:
                rows.append("| " + " | ".join(row) + " |")
        if rows:
            sep = "| " + " | ".join(["---"] * len(rows[0].split("|")[1:-1])) + " |"
            rows.insert(1, sep)
        return "\n".join(rows) or "[Empty CSV]"
    except Exception as e:
        return f"[ERROR reading CSV: {e}]"


def extract_drawio(path: Path) -> str:
    """
    draw.io files are XML. We extract:
    - Shape labels (the text on nodes)
    - Edge labels (connections between nodes)
    - A plain-English description of the diagram structure
    """
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
        # draw.io files are sometimes compressed — check for mxGraphModel
        if "<mxGraphModel" not in raw:
            return f"[draw.io file appears compressed or empty — raw size: {len(raw)} bytes]\n\nRaw content:\n```\n{raw[:2000]}\n```"

        root = ET.fromstring(raw)
        nodes = {}   # id -> label
        edges = []   # (source_label, target_label, edge_label)

        for cell in root.iter("mxCell"):
            cell_id    = cell.get("id", "")
            value      = cell.get("value", "").strip()
            style      = cell.get("style", "")
            source     = cell.get("source", "")
            target     = cell.get("target", "")
            is_edge    = cell.get("edge", "0") == "1"
            is_vertex  = cell.get("vertex", "0") == "1"

            if is_vertex and value:
                # Strip HTML tags from labels
                clean_value = re.sub(r"<[^>]+>", " ", value).strip()
                nodes[cell_id] = clean_value

            if is_edge:
                edges.append((source, target, value))

        parts = []

        if nodes:
            parts.append("## Shapes / Nodes\n")
            for node_id, label in nodes.items():
                parts.append(f"- {label}")

        if edges:
            parts.append("\n## Connections\n")
            for src, tgt, label in edges:
                src_label = nodes.get(src, src or "?")
                tgt_label = nodes.get(tgt, tgt or "?")
                edge_label = f' ("{label}")' if label else ""
                parts.append(f"- {src_label} → {tgt_label}{edge_label}")

        if not parts:
            return "[draw.io file parsed but no shapes or connections found]"

        return "\n".join(parts)

    except ET.ParseError as e:
        return f"[ERROR parsing draw.io XML: {e}]\n\nRaw (first 1000 chars):\n```\n{raw[:1000]}\n```"
    except Exception as e:
        return f"[ERROR reading draw.io: {e}]"


def extract_image_vision(path: Path, anthropic_client) -> str:
    """
    Send image to Claude Vision for description.
    Returns a detailed description useful for notes.
    """
    try:
        from PIL import Image
        img = Image.open(path)
        width, height = img.size
        mode = img.mode
        size_kb = path.stat().st_size // 1024

        # Resize if very large to save API tokens
        max_dim = 1568
        if max(width, height) > max_dim:
            ratio = max_dim / max(width, height)
            img = img.resize((int(width * ratio), int(height * ratio)), Image.LANCZOS)

        # Convert to RGB if needed (for JPEG encoding)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")

        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        img_b64 = base64.standard_b64encode(buf.getvalue()).decode("utf-8")

        response = anthropic_client.messages.create(
            model="claude-opus-4-5",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": img_b64
                        }
                    },
                    {
                        "type": "text",
                        "text": (
                            "This image is from a university student's school folder. "
                            "Describe what you see in detail, focusing on any text, diagrams, "
                            "charts, tables, formulas, or academic content visible. "
                            "If it's a diagram or flowchart, describe the structure and relationships. "
                            "If it contains text, transcribe the key parts. "
                            "Be thorough — this will be used as a study note."
                        )
                    }
                ]
            }]
        )

        description = response.content[0].text
        meta = f"> Image dimensions: {width}×{height}px | Size: {size_kb}KB | Mode: {mode}\n\n"
        return meta + description

    except ImportError:
        return "[ERROR: Pillow not installed — pip install Pillow]\n[Skipping vision analysis]"
    except Exception as e:
        return f"[ERROR analysing image with Claude Vision: {e}]"


def extract_code_or_text(path: Path) -> str:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        ext = path.suffix.lower().lstrip(".")
        return f"```{ext}\n{content}\n```"
    except Exception as e:
        return f"[ERROR reading file: {e}]"


def extract_file(path: Path, use_vision: bool = False, anthropic_client=None,
                 use_ocr: bool = False, ocr_backend='tesseract') -> str:
    ext = path.suffix.lower()
    if use_ocr:
        from qut_toolkit.local_ocr import SUPPORTED, extract_local_ocr
        if ext in SUPPORTED:
            # OCR is independent of paid vision and never enables it implicitly.
            native = extract_file(path, use_vision=use_vision, anthropic_client=anthropic_client)
            supplement = extract_local_ocr(path, native_text=native, backend=ocr_backend)
            return native + "\n\n" + supplement

    if ext == ".pdf":             return extract_pdf(path)
    if ext in (".docx", ".doc"): return extract_docx(path)
    if ext in SLIDE_EXTS:        return extract_pptx(path)
    if ext in (".xlsx", ".xls"): return extract_xlsx(path)
    if ext == ".csv":             return extract_csv(path)
    if ext == ".drawio":          return extract_drawio(path)
    if ext in CODE_EXTS:          return extract_code_or_text(path)
    if ext in (".txt", ".md"):    return extract_code_or_text(path)

    if ext in IMAGE_EXTS:
        if use_vision and anthropic_client:
            return extract_image_vision(path, anthropic_client)
        else:
            size_kb = path.stat().st_size // 1024
            return f"[Image file: {path.name} | {size_kb}KB]\n[Vision analysis skipped — run with --vision to analyse (paid Anthropic API)]"

    return f"[Unsupported file type: {ext}]"


def build_note(file_path: Path, content: str, source=None) -> str:
    try:
        rel = file_path.relative_to(source or SCHOOL_DIR)
    except ValueError:
        rel = Path(file_path.name)

    parts = list(rel.parts)
    subject  = parts[0] if len(parts) > 1 else "general"
    subfolder = " > ".join(parts[:-1]) if len(parts) > 2 else subject
    now = datetime.now().strftime("%Y-%m-%d")

    return f"""---
title: {json.dumps(file_path.stem)}
source: {json.dumps(str(file_path))}
subject: {json.dumps(subject)}
path: {json.dumps(subfolder)}
type: "{file_path.suffix.lower().lstrip('.')}"
scanned: "{now}"
tags: [education, {json.dumps(subject.lower().replace(' ', '-'))}]
---

# {file_path.stem}

> **Source:** `{rel}`
> **Type:** {file_path.suffix.upper()} | **Subject:** {subject}

---

{content}
"""


# ── Safe traversal and incremental conversion ──────────────────────────────
MANIFEST_NAME = ".scan_school_manifest.json"


def _linked(path):
    # Junctions are directory links on Windows, but are not always symlinks.
    if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
        return True
    try:
        return bool(getattr(path.lstat(), "st_file_attributes", 0) &
                    getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
    except FileNotFoundError:
        return False


def _safe_target(path):
    try:
        linked = any(_linked(p) for p in (path, *path.parents))
    except NotADirectoryError:
        raise ValueError(f"Path has a non-directory parent: {path}") from None
    if linked:
        raise ValueError(f"Refusing linked path: {path}")
    if any(parent.exists() and not parent.is_dir() for parent in path.parents):
        raise ValueError(f"Path has a non-directory parent: {path}")


def _walk(source, output):
    """Prune before descending, including nested generated output trees."""
    for root, dirs, files in os.walk(source, followlinks=False):
        parent = Path(root)
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "$"))
                         and d.lower() not in SKIP_DIRS
                         and not _linked(parent / d)
                         and not (parent / d / MANIFEST_NAME).exists()
                         and (parent / d).resolve() != output)
        yield parent, [name for name in sorted(files)
                       if not name.startswith((".", "$"))
                       and name.lower() not in SKIP_FILES
                       and not _linked(parent / name)]


def _hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_write(path, text):
    _safe_target(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="",
                                         dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _valid_content(content):
    if not isinstance(content, str) or not content.strip():
        return False
    return not content.lstrip().startswith(("[ERROR", "[No extractable", "[No data",
        "[Empty CSV]", "[Unsupported", "[draw.io file appears", "[draw.io file parsed"))


def scan_and_convert(subject_filter=None, use_vision=False, *, source=None,
                     output=None, vault=None, use_ocr=False, ocr_backend='tesseract'):
    """Scan locally, preserving user edits; return processed/skipped/errors/conflicts."""
    source, output = resolve_paths(source, output, vault)
    _safe_target(source)
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Source must be an existing directory: {source}")
    _safe_target(output)
    output = output.resolve()
    if output == source:
        raise ValueError("Output must not equal source")
    if output.exists() and not output.is_dir():
        raise ValueError("Output must be a directory")
    scan_root = source
    if subject_filter:
        matches = []
        for parent, _ in _walk(source, output):
            if parent != source and subject_filter.casefold() in parent.name.casefold():
                matches.append(parent)
        exact = [p for p in matches if p.name.casefold() == subject_filter.casefold()]
        matches = exact or matches
        if len(matches) != 1:
            raise ValueError(f"Subject must match exactly one visible directory: {subject_filter!r} ({len(matches)} matches)")
        scan_root = matches[0]

    from qut_toolkit.locking import writer_lock
    with writer_lock(output):
        return _scan_locked(source, output, scan_root, use_vision, use_ocr, ocr_backend)


def _scan_locked(source, output, scan_root, use_vision, use_ocr, ocr_backend):
    manifest_path = output / MANIFEST_NAME
    _safe_target(manifest_path)
    manifest = {"version": 1, "source": str(source), "files": {}}
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if (manifest.get("version") != 1 or manifest.get("source") != str(source)
                    or not isinstance(manifest.get("files"), dict)
                    or any(not isinstance(v, dict) for v in manifest["files"].values())):
                raise ValueError("Manifest schema or source mismatch")
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"Invalid manifest; preserve it and resolve manually: {manifest_path}") from exc

    client = None
    if use_vision:
        # Explicit opt-in only. A failed setup must not silently claim vision success.
        try:
            import anthropic
            client = anthropic.Anthropic()
        except Exception as exc:
            raise ValueError(f"Cannot enable paid Anthropic vision: {exc}") from exc

    print(f"Source : {scan_root}\nOutput : {output}\nVision : {'ON (paid Anthropic)' if use_vision else 'OFF'}")
    result = dict(processed=0, skipped=0, errors=0, conflicts=0)
    for parent, names in _walk(scan_root, output):
        for name in names:
            path = parent / name
            if not path.is_file() or path.suffix.lower() not in ALL_SUPPORTED:
                result["skipped"] += 1
                continue
            rel = path.relative_to(source)
            key = rel.as_posix()
            # Include the original extension: a.pdf and a.txt cannot collide.
            note_path = output / rel.parent / (path.name + ".md")
            try:
                _safe_target(note_path)
                source_hash = _hash(path)
                mode = bool(use_vision and path.suffix.lower() in IMAGE_EXTS)
                ocr_mode = bool(use_ocr and path.suffix.lower() in
                    (IMAGE_EXTS | {".pdf", ".docx", ".pptx", ".pptm", ".ppsx"}))
                entry = manifest["files"].get(key, {})
                if (entry.get("source_hash") == source_hash
                        and entry.get("vision") == mode
                        and entry.get("ocr", False) == ocr_mode
                        and entry.get("ocr_backend") == (ocr_backend if ocr_mode else None)
                        and entry.get("complete", True) and note_path.is_file()):
                    # Never overwrite local edits merely because the source is unchanged.
                    result["skipped"] += 1
                    continue
                pending = entry.get("conflict", {})
                if (pending.get("source_hash") == source_hash and pending.get("vision") == mode
                        and pending.get("ocr", False) == ocr_mode
                        and pending.get("ocr_backend") == (ocr_backend if ocr_mode else None)
                        and pending.get("complete", True)):
                    conflict_path = output / pending.get("output", "")
                    _safe_target(conflict_path)
                    if conflict_path.is_relative_to(output) and conflict_path.is_file():
                        # Preserve edits to the conflict copy too; no repeated duplicates.
                        result["skipped"] += 1
                        continue
                options = dict(use_vision=use_vision, anthropic_client=client)
                if ocr_mode:
                    options["use_ocr"] = True
                    options["ocr_backend"] = ocr_backend
                content = extract_file(path, **options)
                incomplete = ocr_mode and "[OCR INCOMPLETE:" in content
                # Preserve native text and honest OCR diagnostics even on partial failure.
                if not _valid_content(content) and not (ocr_mode and
                        ("## Supplemental local OCR" in content or incomplete)):
                    raise ValueError(f"Extraction failed: {str(content)[:200]}")
                if _hash(path) != source_hash:
                    raise ValueError("Source changed during extraction; retry")
                note = build_note(path, content, source=source)
                edited = note_path.exists() and (
                    not entry.get("note_hash") or _hash(note_path) != entry["note_hash"])
                if edited:
                    target = note_path.with_name(f"{path.name}.conflict-{source_hash[:12]}.md")
                    counter = 1
                    while target.exists() or _linked(target):
                        target = note_path.with_name(f"{path.name}.conflict-{source_hash[:12]}-{counter}.md")
                        counter += 1
                    _atomic_write(target, note)
                    entry["conflict"] = dict(source_hash=source_hash, vision=mode,
                        ocr=ocr_mode, ocr_backend=ocr_backend if ocr_mode else None, complete=not incomplete,
                        output=target.relative_to(output).as_posix(), note_hash=_hash(target))
                    manifest["files"][key] = entry
                    result["conflicts"] += 1
                    print(f"Conflict (local edits preserved): {target}")
                else:
                    _atomic_write(note_path, note)
                    manifest["files"][key] = dict(source_hash=source_hash,
                        note_hash=_hash(note_path), output=note_path.relative_to(output).as_posix(),
                        vision=mode, ocr=ocr_mode, ocr_backend=ocr_backend if ocr_mode else None, complete=not incomplete)
                    if not incomplete:
                        result["processed"] += 1
                if incomplete:
                    result["errors"] += 1
                    print(f"Incomplete local OCR: {rel}; see note for diagnostics")
            except Exception as exc:
                result["errors"] += 1
                print(f"Error: {rel}: {exc}")
    _atomic_write(manifest_path, json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")
    print("Done! " + " | ".join(f"{k}: {v}" for k, v in result.items()))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description="Convert school files to local Markdown notes (vision off by default)")
    parser.add_argument("--source", type=Path, help="Source (default: QUT_STUDY_ROOT or ~/QUT Study)")
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--output", type=Path, help="Notes destination (default: source/notes)")
    destination.add_argument("--vault", type=Path, help="Explicit vault; writes to vault/education")
    parser.add_argument("--subject", help="One matching visible subject directory; no fallback")
    vision = parser.add_mutually_exclusive_group()
    vision.add_argument("--vision", action="store_true", help="Opt in to paid Anthropic API image uploads")
    vision.add_argument("--no-vision", action="store_true", help="Compatibility flag: vision is already off")
    parser.add_argument("--ocr", action="store_true",
                        help="Opt in to local Tesseract OCR (Pillow/pytesseract; PDF rendering needs PyMuPDF)")
    parser.add_argument("--ocr-backend", choices=("tesseract","rapidocr"), default="tesseract",
                        help="Local OCR engine; rapidocr uses bundled ONNX models without a system Tesseract install")
    args = parser.parse_args(argv)
    try:
        from qut_toolkit.locking import WriterLockError
        result = scan_and_convert(args.subject, args.vision, source=args.source,
                                  output=args.output, vault=args.vault, use_ocr=args.ocr, ocr_backend=args.ocr_backend)
        return 1 if result["errors"] else 0
    except (ValueError, OSError, WriterLockError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
