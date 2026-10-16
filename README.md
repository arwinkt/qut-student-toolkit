# QUT Student Toolkit

An organised local copy of your Canvas courses: module indexes, readable pages,
resources, assessment/mark reports, and timestamped lecture captions.
**No Obsidian, Second Brain, AI subscription or admin token required.**

Built for a student's own authorised course access. This is not an official QUT product.

## Quick start

Python **3.11+**. Run commands from the cloned repository folder.

```sh
# Browser login/caption support; the core sync itself uses Python's standard library.
python -m pip install playwright
python -m playwright install chromium

# Pick ONE study folder. No vault setup is assumed.
python scripts/qut_sync.py setup --root "~/QUT Study"

# A private browser opens. Sign in yourself and complete MFA.
python scripts/canvas_auth.py

python scripts/qut_sync.py courses
python scripts/qut_sync.py sync COURSE_ID
python scripts/qut_transcripts.py --course-id COURSE_ID
python scripts/qut_sync.py report
```

Replace `COURSE_ID` with the numeric ID shown by `courses`, without angle brackets.
Start with one unit: a first sync can download large slide decks. Multiple IDs and
`sync --all` are available, but are not recommended as your first run.

The session can expire **at any time**. Re-run `canvas_auth.py` when rejected. The
cache's expiry is a local refresh hint, not a promise of a seven-day login.

## Where are the files?

By default, in **`QUT Study` inside your home folder**, not inside this repository:

```text
QUT Study/
  units/
    course-COURSE_ID/
      INDEX.md                     # Unit navigation + coverage
      findings.md                  # Source-linked assessments, marks, announcements
      recordings.json              # Discovered recording sources (not credentials)
      pages/page-PAGE_ID.md
      assignments/assignment-ASSIGNMENT_ID.md
      resources/file-FILE_ID.pdf   # Actual extension retained
      modules/module-MODULE_ID/INDEX.md
      lectures/
        INDEX.md
        latest-transcripts.json
        lecture-STABLE_ID/
          transcript.md            # Full timestamped caption text
          captions.vtt             # Derived VTT, explicitly labelled
          cues.json
          metadata.json
          original.json            # Normalized Echo cues; not raw browser traffic
          manifest.json
          originals/               # Content-hashed versions
          conflicts/               # Incoming versions when you edited a file
      manifest.json
      originals/
      conflicts/
  reports/
    latest-sync.md
    latest-sync.json
  notes/                           # Only created if you run the document scanner
```

Stable Canvas IDs prevent duplicate names and renamed units from colliding. Open
`INDEX.md` in any Markdown editor. You can read all files without an AI assistant.

### Configuration

`setup` saves non-secret configuration to `~/.qut-toolkit.json`:

```json
{
  "root": "D:/Study/QUT",
  "timezone": "Australia/Brisbane"
}
```

Precedence: **explicit CLI option → JSON config → environment → default**.
Use `--config PATH` to select a different config and `--root PATH` to override output.
`QUT_STUDY_ROOT` is the corresponding environment variable. Dates show both UTC and
the configured timezone; Brisbane works without an extra timezone package. Other
IANA timezones may require `tzdata` on Windows.

Credentials are separate. Use `--cookie-cache PATH` for an existing private Canvas
cache; the setup command never copies credentials into config. Custom cache paths
must be supplied on subsequent commands, or set via `QUT_COOKIE_CACHE`.

### Optional Obsidian / Second Brain export

Keep the standalone library as the primary output. If you want a course mirror in
an existing notes/vault folder:

```sh
python scripts/qut_sync.py sync COURSE_ID --notes-root "D:/My Vault"
```

This writes into **`D:/My Vault/qut-toolkit/course-COURSE_ID/`**, preserving local
edits and incoming conflicts. It does not restructure the vault. The mirror includes
managed course pages, indexes, findings and referenced resources; the separately
exported lecture library stays in the primary study folder. This option can consume
extra disk space. It is never enabled merely because Obsidian is installed.

## Lecture transcripts

```sh
# Discover sources only; no player extraction yet.
python scripts/qut_transcripts.py --course-id COURSE_ID --discover-only

# Export existing captions for every discovered supported source.
python scripts/qut_transcripts.py --course-id COURSE_ID

# Test one durable Canvas recording page or Echo course-navigation tool.
python scripts/qut_transcripts.py --page-url "https://canvas.qut.edu.au/courses/COURSE_ID/pages/PAGE_SLUG"

# Bound a trial run; output explicitly records that coverage is bounded.
python scripts/qut_transcripts.py --course-id COURSE_ID --limit 2 --lesson-limit 1
```

The exporter uses the private browser profile created by `canvas_auth.py`. Advanced
users can instead attach an already authenticated Chromium browser using
`--cdp-url http://127.0.0.1:9222`. CDP is accepted on **loopback only**; never expose
this port publicly. The toolkit does not restart or close an attached browser.
`--profile PATH` selects a different existing Playwright profile; it cannot share a
profile that another process has locked.

### Supported and verified

| Source | Support |
|---|---|
| QUT Canvas pages with Echo360 embedded players | Authenticated browser capture of existing transcript JSON; live-tested |
| Echo360 course library via Canvas course-navigation tool | Section syllabus discovery and available lesson captions; live-tested |
| WebVTT / SRT | Strict offline parsing; browser capture when the player requests the track |
| HTML5 captions not requested by the browser | Discovered, but not guaranteed to be fetched |
| Panopto / Kaltura / other recording providers | May be detected; provider-specific extraction is not implemented |
| Recordings without accessible captions | Explicit unavailable/unsupported/auth status; no invented text |

Automatic captions are labelled and can mishear technical terms. Unknown language
stays unknown. `captions.vtt` is generated from the original cue timings, **not an
original provider VTT**. For Echo, `original.json` contains normalized source cues
only, without private user/institution/session response fields. A captured VTT/SRT
also retains `original.vtt` / `original.srt`.

This feature does **not** download lecture audio/video, purchase transcription,
bypass permissions, or generate AI summaries. The ordinary course resource sync
also excludes audio/video by default, including MP4s linked as Canvas files. Opt in
with `qut_sync.py sync COURSE_ID --include-media` only if you intend to download
large recordings. Resources above the advertised **100 MiB per-file** default are
skipped and reported incomplete; change `--max-file-bytes` deliberately if needed.
The size check depends on Canvas-provided metadata, not a hard network byte quota.

## Findings, assessments and sync status

- Module indexes link to pages, resources and assessment instructions, rather than
  copying lecture text into several summaries.
- `findings.md` shows the current student's Canvas-provided submission state,
  official due date, released numerical scores (including zero), and source links.
- Grade/posting visibility is handled conservatively; unknown/unreleased is not zero.
- Deadline, newly observed mark and announcement changes are tracked. The findings
  retain the **last observed changes**; per-run JSON distinguishes fresh changes.
- Announcements are cohort information, **not automatically your personal obligation**.
- No inferred grace periods, attendance requirements, predicted GPA or AI summaries.

QUT often disables the **Pages** and **Files** listing APIs for students while still
allowing module-linked pages/files. The toolkit falls back to module references and
attempts referenced downloads. It cannot prove that hidden/unlinked content does
not exist, so the report remains **INCOMPLETE**, with the failed sections listed.
A separately successful assessment check still appears with its own verified status.

Exit codes: `qut_sync.py` returns **0** for a complete operation, **1** for failed or
incomplete checks, **2** for configuration/argument errors. `qut_transcripts.py`
returns **2** on discovery/extraction errors or incomplete/bounded coverage.
Intentional bounded exports still save their successful files, but exit nonzero
because they do not establish full-course completion. `--discover-only` reports
sources without claiming any extraction. Never treat lack of a transcript or a
failed API as “nothing new”.

### Incremental safety

Content hashes—not filenames or file sizes alone—govern working-copy changes.
Original versions are retained. Locally edited files are never silently overwritten;
incoming versions are preserved in `conflicts/` and reported. Successful checkpoints
do not advance after incomplete checks. Intermediate provenance is saved so an
interrupted sync can resume safely.

Resources with unchanged Canvas `updated_at` **and** size can reuse a hash-verified
cached original. If metadata is missing or changes, bytes are fetched and hashed
again. Provider metadata can be wrong; this is not an immutable remote audit.

There is currently no simultaneous-writer locking: **do not run two syncs against
the same output folder at once**. Originals plus working copies, conflicts and an
optional vault mirror can use more than twice the raw course download size.

## Convert documents to searchable notes

```sh
python -m pip install pdfplumber python-docx python-pptx openpyxl Pillow
python scripts/scan_school.py --source "~/QUT Study"
python scripts/scan_school.py --source "~/QUT Study" --output "D:/Study Notes"
python scripts/scan_school.py --source "~/QUT Study" --vault "D:/My Vault"
```

The scanner is **included**, works without Obsidian, and makes no paid calls by
default. Default notes: `<source>/notes/`; explicit `--vault` uses `<vault>/education/`.
It skips generated output, state/original/conflict directories, hidden entries and
links; extension-preserving names avoid `slides.pdf` / `slides.pptx` collisions.
Content hashes preserve local edits. Missing dependencies and failed extraction
are reported, not converted into successful notes.

Image analysis is optional and paid: install `anthropic` and explicitly choose
`--vision` only if you intend to send those images to Anthropic and incur charges.
Do not share keys. See [scanner reference](scripts/scan_school_README.md) for formats,
legacy environment variables, dependency limits and subject filtering.

The scanner has its own path configuration; it does not read `~/.qut-toolkit.json`.
Pass `--source` when the library uses a custom root, or set `QUT_STUDY_ROOT` for both.

## Existing command names

`canvas.py courses`, `pull COURSE_ID`, `pull-all`, `modules COURSE_ID`, `pages COURSE_ID`,
`page COURSE_ID PAGE_SLUG`, `files COURSE_ID`, `scan`, `auth`, and `check` remain CLI
entrypoints. Pull commands now use the new library layout. Existing Desktop/school
files are **not moved or deleted**. `SCHOOL_DIR` still overrides the legacy wrapper's
root when explicitly set. Raw listing commands can fail where QUT blocks listings;
use the sync command for module fallbacks.

The separate `qut_outlook.py` email utility remains unchanged. Its Microsoft EWS
access depends on current tenant policy; no Outlook capability was retested in this
upgrade. Course syncing and captions do not require email access.

## Privacy and tests

Never commit or share cookie caches, browser profiles, email token caches, API keys,
grades, downloaded teaching materials or lecture transcripts. Keep your output folder
**outside this repo**. `.gitignore` covers common generated names, but cannot protect
arbitrarily named sensitive files or files already tracked by Git. Session files on
Windows rely on your user account permissions; POSIX chmod is not a Windows ACL.

Only use your own authorised access and respect teaching-material copyright and
academic integrity rules. Sharing this tool is not permission to publish course content.

```sh
python -B -m unittest discover -s tests -v
python -m compileall -q scripts tests
```

Tests use synthetic content and no live accounts. Live browser/caption checks were
performed on Windows 11; macOS/Linux execution is not yet verified. No credentials
or actual lecture text belong in test fixtures.
