# QUT Student Toolkit

Automate your QUT student workflows — pull Canvas content, read your Outlook email,
and convert everything into searchable notes. No admin tokens needed.

Built by a QUT student, for QUT students.

---

## What's In Here

| Script | What it does |
|---|---|
| `scripts/canvas_auth.py` | One-time Canvas login via Playwright (saves cookies) |
| `scripts/canvas.py` | Canvas CLI — list courses, download files, pull pages as markdown |
| `scripts/qut_outlook.py` | QUT Outlook via EWS + device code OAuth — inbox, sent, search, send |
| `scripts/scan_school.py` | Convert ALL downloaded files to searchable markdown notes (PDF, PPTX, DOCX, XLSX, images via Claude Vision, draw.io diagrams) |
| `scripts/scan_school_README.md` | Quick reference for scan_school.py |

---

## Why This Exists

QUT blocks personal access tokens on Canvas (the "Add New Access Token" button is
greyed out for students). They also block most Microsoft Graph API access for student
accounts. Standard automation tools don't work.

These scripts use the auth methods that **actually work** on QUT's systems:

- **Canvas**: Playwright browser automation to capture your session cookies once.
  After that, `canvas.py` makes API calls using those cookies — no token needed.
- **Outlook**: Device code flow against the Microsoft Office native app client ID
  (`d3590ed6-52b3-4102-aeff-aad2292ab01c`), then Exchange Web Services (EWS) SOAP
  for email access. Graph API is blocked; EWS works.

---

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

### 2. Canvas setup (one-time, ~2 minutes)

```bash
python scripts/canvas_auth.py
```

A browser opens. Log into Canvas with your QUT Microsoft account. Complete MFA.
Wait for your course dashboard to load. Browser closes automatically and saves your session.

Then use the CLI:

```bash
python scripts/canvas.py courses              # List your courses
python scripts/canvas.py pull <COURSE_ID>     # Download all files for a course
python scripts/canvas.py pull-all             # Download everything
python scripts/canvas.py modules <COURSE_ID>  # Browse module structure
python scripts/canvas.py pages <COURSE_ID>    # List Canvas pages
```

Session stays valid for ~7 days. Re-run `canvas_auth.py` when it expires.

### 4. Convert all downloaded files to notes (the full pipeline)

This is the part that makes everything LLM-usable. After pulling from Canvas:

```bash
# Basic usage — scan everything
python scripts/scan_school.py

# One subject only (faster)
python scripts/scan_school.py --subject "Database Management"

# Skip image analysis (no API calls, much faster)
python scripts/scan_school.py --no-vision
```

**What it does:** Recursively scans your `~/Desktop/school/` folder and converts
every supported file into a clean markdown note, saved to your vault's `education/` folder.

**Supported formats:**

| Type | Extensions |
|---|---|
| Documents | `.pdf` `.docx` `.doc` `.txt` `.md` |
| Slides | `.pptx` `.pptm` `.ppsx` `.ppt` |
| Spreadsheets | `.xlsx` `.xls` `.csv` |
| Images | `.png` `.jpg` `.jpeg` `.gif` `.webp` `.bmp` |
| Diagrams | `.drawio` |
| Code / Data | `.py` `.js` `.html` `.json` `.xml` `.yaml` `.csv` |

For images, it uses Claude Vision (requires `ANTHROPIC_API_KEY`) to describe
what's in the image — text, diagrams, charts, tables. Skip with `--no-vision`
if you don't have an API key or want a faster run.

**Configure paths** via environment variables (or edit the top of the script):

```bash
# Windows
set SCHOOL_DIR=C:\path\to\your\school\folder
set VAULT_DIR=C:\path\to\your\obsidian\vault
python scripts/scan_school.py

# macOS / Linux
SCHOOL_DIR=~/Downloads/school VAULT_DIR=~/vault python scripts/scan_school.py
```

Defaults: `SCHOOL_DIR` = `~/Desktop/school` (where `canvas.py pull-all` saves to),
`VAULT_DIR` = the parent directory of the `scripts/` folder (assumes you cloned this
repo inside your vault).

**After running:** Your notes are in `<vault>/education/`. If you use an AI assistant
with file access to your vault, say "load my [subject] context" and it can read
everything — PDFs, slides, spreadsheets, diagrams, all converted to plain text.

### Full end-to-end workflow

```bash
# 1. Auth Canvas (first time only)
python scripts/canvas_auth.py

# 2. Pull all course files
python scripts/canvas.py pull-all

# 3. Convert everything to searchable notes
python scripts/scan_school.py

# 4. (Optional) Sync email
python scripts/qut_outlook.py inbox 20
```

After step 3, every PDF, PPTX, DOCX, spreadsheet, diagram, and image from your
Canvas courses is a readable markdown file your AI assistant can search and use.



Edit `scripts/qut_outlook.py` and set your student email:

```python
USER_EMAIL = "your.email@connect.qut.edu.au"  # line ~16
```

Then authenticate:

```bash
python scripts/qut_outlook.py auth
```

A URL and code appear. Open the URL on your phone, enter the code, approve the MFA prompt.
Token is cached — you only do this once (re-auth weekly).

Then use the CLI:

```bash
python scripts/qut_outlook.py inbox 20      # Last 20 emails
python scripts/qut_outlook.py unread        # Unread only
python scripts/qut_outlook.py search "AT3"  # Search by subject
python scripts/qut_outlook.py sent 10       # Sent items
python scripts/qut_outlook.py send "Subject" "recipient@email.com"
```

---

## Auth Files — Keep These Secret

After setup, these files are created locally and **must never be committed**:

| File | What it contains |
|---|---|
| `scripts/.canvas_cookies.json` | Your active Canvas session (treat like a password) |
| `scripts/.qut_outlook_cache.json` | Your MSAL token cache (treat like a password) |
| `scripts/.playwright_canvas_profile/` | Browser profile with saved login |

All three are in `.gitignore` already.

---

## How It Works — Technical Notes

### Canvas

QUT disables Canvas personal access tokens for students. This toolkit uses your
existing browser session instead:

1. `canvas_auth.py` launches a Playwright Chromium browser in persistent mode
2. You log in once via QUT's Microsoft SSO
3. Playwright captures all cookies after the dashboard loads
4. `canvas.py` uses those cookies for API calls to `canvas.qut.edu.au/api/v1/`
5. Cookies are cached for 7 days

### Outlook / Exchange

QUT's Microsoft 365 tenant blocks Microsoft Graph API (`Mail.Read` scope) for student
accounts — you get `AADSTS65002` consent errors. However, Exchange Web Services (EWS)
still works with the right client ID:

- **Client ID**: `d3590ed6-52b3-4102-aeff-aad2292ab01c` (Microsoft Office native app)
- **Authority**: `https://login.microsoftonline.com/organizations`
- **Scope**: `https://outlook.office365.com/.default` (NOT `Mail.Read` — that's blocked)
- **Protocol**: EWS SOAP, NOT IMAP/POP3 (both fail even with a valid token)

Device code flow + EWS = the only reliable path for QUT student Outlook automation.

---

## Tested On

- Windows 11 with Python 3.11+
- QUT Diploma of IT student account (2026)
- QUT Canvas instance: `canvas.qut.edu.au`
- QUT Outlook via Microsoft 365 (Exchange Online)

Should work for any QUT student account. Not tested on macOS/Linux but should work —
the Playwright auth is cross-platform.

---

## Limitations

- Canvas session expires every ~7 days — re-run `canvas_auth.py`
- Outlook token expires weekly — re-run `auth` when prompted
- `scan_school.py` (for converting files to notes) is not included here — it's
  tightly coupled to a specific vault structure. See `scripts/scan_school_README.md`
  for what it does and how to adapt it
- Quiz endpoints (`/api/v1/courses/{id}/quizzes`) are sometimes blocked during active
  quiz windows — workaround is to manually download files from Canvas

---

## Contributing

Found a bug or a better auth method? Open an issue or PR.

---

## License

MIT — use freely for personal academic automation.

**Do not use these tools to submit work that isn't yours, access other students' data,
or violate QUT's academic integrity policy. This is for automating your own workflow only.**
