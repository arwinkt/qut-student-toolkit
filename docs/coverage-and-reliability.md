# Browser coverage, local OCR and reliability verification

## Scope

This follow-up adds optional browser-visible discovery and saved-file reconciliation,
explicit local OCR, safe transient GET/write retries, and cooperating writer locks.
It does not grant course permissions or establish that hidden/unpublished material
is absent. Byte-range partial-download resume remains unimplemented.

## Executed locally on Windows

- Python 3.11 and 3.12: `python -B -m unittest discover -s tests -q`:
  **142 tests; OK (skipped=3)** on each environment. Permission/optional-dependency
  skips remain explicit; no live credentials are required by the suite.
- `python -m compileall -q scripts tests` and `git diff --check`: passed.
- Real local RapidOCR smoke: generated PNG, scanned PDF, DOCX embedded image and
  PPTX embedded image all recognized known synthetic words. Bundled installed ONNX
  models only; no extraction-time model downloads or paid service.
- Real child-process CLI contention check: course sync, transcript exporter and
  document scanner refused a held output-root lock without changing the existing
  checkpoint. Lock release after errors/process death is separately tested.
- Regression checks cover module-item redirect resolution without off-course/LTI
  navigation, query stripping, retained-but-unobserved files, missing local files,
  bounded discovery, OCR backend/mode checkpoints, local edits/conflicts, and
  bounded Retry-After handling.

## Real acceptance boundary

An authenticated Windows browser observed real course modules through ordinary
Canvas pages. An individual failed-link check compared API access, the normal
browser file page, and direct download behavior; genuinely missing references are
reported rather than bypassed. Personal inventories, documents, extracted words,
marks and browser state stay outside Git. OCR output remains uncertain derived
text and keeps the original source document.

Cross-platform CI now installs the optional OCR packages and exercises generated
PNG/PDF/DOCX/PPTX OCR on Windows/macOS/Ubuntu alongside the Chromium smoke and
unit suite. **Check exact-head results before claiming this follow-up passes on
all platforms.** A configured job is not a passed job; real institutional Mac
login/MFA remains untested.

## Changed expectation

The older pagination test expected a transient network failure to stop after the
first request on page two. It now expects the deliberate shared three-attempt GET
budget, followed by the same failure. Access/auth failures still fail immediately.

## Remaining boundaries

- OS locks require cooperating writers and local filesystem semantics. Direct
  Python API users must acquire `writer_lock` around compound sync operations.
- Retried downloads restart the GET; the advertised file-size check is not a hard
  streaming-byte quota. Large media remain opt-in.
- Native PDF/image decoding has between-item limits, not full decoder process
  isolation. RapidOCR inference is in a deadline-bounded child; Tesseract uses its
  own bounded subprocess. Empty, limited or failed OCR is marked INCOMPLETE.
- Same-course browser expansion can fail or hit a budget; this remains explicit.
  Seeing a file link does not prove its download or every recording's captions.
