# School folder scanner

`scan_school.py` converts school documents into local Markdown notes. It does not
require an Obsidian vault or an API key for its default, offline operation.

## Paths and commands

The default source is `~/QUT Study` (Windows: `%USERPROFILE%\QUT Study`).
Set `QUT_STUDY_ROOT` or pass `--source` to choose another existing directory.
The default output is `<source>/notes`; the repository is never an implicit vault.

```sh
python scripts/scan_school.py
python scripts/scan_school.py --source "C:/Study" --output "C:/Study/notes"
python scripts/scan_school.py --source "C:/Study" --subject "Database Management"
python scripts/scan_school.py --source "C:/Study" --vault "C:/My Obsidian Vault"
```

`--vault` explicitly writes to `<vault>/education`. `--output` and `--vault` are
mutually exclusive. Relative paths are relative to the current working directory.
Home-directory (`~`) expansion is supported.

Configuration precedence:

- Source: `--source` → `QUT_STUDY_ROOT` → legacy `SCHOOL_DIR` → `~/QUT Study`.
- Output: `--output` or `--vault` → legacy `NOTES_DIR` → legacy
  `VAULT_DIR/education` → `<source>/notes`.

`NOTES_DIR` is already the complete destination; `VAULT_DIR` is a vault root.
An explicit CLI destination wins over either legacy environment variable.
Missing/non-directory sources and output equal to source are rejected before scanning.
A subject must match exactly one visible directory, case-insensitively (exact name
preferred over substring). Missing or ambiguous subjects fail rather than scanning everything.

## Offline first; paid vision requires opt-in

Vision is **off by default**, including calls to `scan_and_convert()`.
Images receive a local metadata note without opening the image or contacting an API.
`--no-vision` remains accepted for compatibility and is equivalent to the default.

```sh
# Explicit permission to upload supported images to Anthropic and incur API charges:
python scripts/scan_school.py --source "C:/Study" --vision
```

Vision needs the `anthropic` and `Pillow` packages and an `ANTHROPIC_API_KEY`
configured in your environment. Never commit the key. Client setup failures are
reported, not silently downgraded to successful image analysis. An unchanged image
previously converted offline is reprocessed when vision is explicitly enabled.
No tests in this repository make real paid vision calls.

## Supported formats and optional dependencies

| Type | Extensions | Dependency / limitations |
|---|---|---|
| Plain text / code | `.txt`, `.md`, `.py`, `.js`, `.html`, `.css`, `.json`, `.xml`, `.yaml`, `.yml` | Standard library |
| PDF | `.pdf` | `pdfplumber`; text extraction only, no OCR |
| Word | `.docx` | `python-docx` |
| PowerPoint | `.pptx`, `.pptm`, `.ppsx` | `python-pptx` |
| Spreadsheet | `.xlsx` | `openpyxl` |
| CSV | `.csv` | Standard library |
| Diagram | `.drawio` | Uncompressed XML nodes and edges; compressed/empty diagrams fail clearly |
| Images | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp` | Metadata offline; paid description only with `--vision` |

Legacy `.doc`, `.ppt`, and `.xls` files are attempted by the existing modern-format
extractors; genuine binary Office formats are not supported. Convert them to modern
Office formats first. Missing dependencies, corrupt documents, and documents with no
extractable content are counted as errors and do not create fake successful notes.

Install only what you need, for example:

```sh
python -m pip install pdfplumber python-docx python-pptx openpyxl
# Optional, only for explicitly enabled paid image analysis:
python -m pip install anthropic Pillow
```

## Incremental scans and preserving edits

Folder structure is mirrored below the destination. Original extensions are retained:
`Unit/a.pdf` becomes `Unit/a.pdf.md`, while `Unit/a.txt` becomes `Unit/a.txt.md`.

The destination's `.scan_school_manifest.json` records SHA-256 hashes of source
content and generated notes. Timestamps are not used to decide whether a source
changed. Keep this manifest with its notes; a malformed manifest or one belonging
to a different source root causes an explicit error rather than unsafe overwrites.

- Unchanged source: skip the existing note, preserving any local edits.
- Changed source with an unedited generated note: replace that note atomically.
- Changed source with local edits, or an existing unmanaged note: preserve the
  original and write `a.txt.conflict-<source-hash>.md` alongside it. Additional
  suffixes prevent overwriting an existing conflict copy.
- Repeating the same scan does not duplicate the same unresolved conflict. Edits to
  conflict copies are preserved too. Review/merge conflicts manually. Once the
  source changes again, another conflict copy can be created.
- Extraction failure: preserve any existing note and previous manifest record so a
  later successful run can retry. Removed sources do not delete notes.

There is no automatic migration or deletion of older stem-only notes (`a.md`).
Back them up and reconcile them manually when adopting the extension-preserving layout.
Do not run multiple scanner writers against the same destination concurrently.

Traversal prunes the active output subtree, `notes` directories, previously generated
subtrees containing a scanner manifest, hidden/dollar-prefixed entries, state directories
(`state`, `.git`, `.obsidian`, etc.), `node_modules`, `__pycache__`, and virtual environments.
Symlinked files/directories and Windows reparse points are not followed. Linked source,
output, and destination paths are refused. Generated notes are never recursively converted.
The scanner is intended for trusted local folders, not adversarial concurrently mutated trees.

## Programmatic use and exit status

```python
from scripts.scan_school import scan_and_convert
result = scan_and_convert(source="C:/Study", output="C:/Study/notes")
# result: processed, skipped, errors, conflicts counters
```

CLI exit status: `0` completed without extraction errors (conflicts are reported but
are not errors); `1` one or more file conversions failed; `2` invalid configuration,
subject selection, manifest, or filesystem-level failure.

## Offline regression tests

From the repository root:

```sh
python -B -m unittest discover -s tests -p test_legacy_scanner.py -v
```

Tests use `TemporaryDirectory` fixtures and synthetic documents only. They do not
scan live school folders, and Anthropic vision is mocked. Actual symlink creation
is skipped when the host lacks privileges; link-pruning logic is also tested using
a mocked link predicate without requiring those privileges.
