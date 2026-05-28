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
| `scripts/scan_school_README.md` | How to use `scan_school.py` to convert files to vault notes |

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

### 3. Outlook setup (one-time, ~1 minute)

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
