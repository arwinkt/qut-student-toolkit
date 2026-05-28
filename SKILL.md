---
name: qut-student-toolkit
category: productivity
description: Prepare and maintain the scrubbed public toolkit for QUT students to automate Canvas and Outlook.
---

# QUT Student Toolkit Lifecycle

This skill governs the maintenance and deployment of the `qut-student-toolkit` repository.

## Safety & Scrubbing Protocol (MANDATORY)

Before any code is moved to the public folder or pushed to GitHub:

1. **Email Removal:** Replace all instances of `your.email@connect.qut.edu.au`
   and `your.personal@email.com` with `your.email@connect.qut.edu.au`.
2. **Student ID Removal:** Replace `[STUDENT_ID]` with `[STUDENT_ID]` or remove entirely.
3. **Path Removal:** Replace hardcoded paths like `C:\Users\arwin\` with generic
   `%USERPROFILE%` or relative paths.
4. **Token Block:** NEVER copy `.canvas_cookies.json`, `.qut_outlook_cache.json`,
   or `.qut_device_code.txt` into the public folder.
5. **Playwright Profile Block:** NEVER copy `.playwright_canvas_profile/` — it
   contains your browser session data.
6. **Git Verification:** Ensure `git config user.email` is set to the no-reply
   address (`arwinkt@users.noreply.github.com`) before committing.

## Credential Audit Command

Run before every push:

```bash
cd /c/Users/arwin/Desktop/qut-student-toolkit
grep -rn "student\|[STUDENT_ID]\|your.personal" . \
  --exclude-dir=.git --include="*.py" --include="*.md" --include="*.txt"
# Should return zero results
```

## Deployment Workflow

### 1. Sync Master Scripts

When a master script changes (`second_brain/scripts/`), sync to toolkit:

```python
# Read master, scrub, write to toolkit
# Key replacements:
# your.email@connect.qut.edu.au → your.email@connect.qut.edu.au
# your.personal@email.com → your.email@connect.qut.edu.au
# [STUDENT_ID] → [STUDENT_ID]
# C:\\Users\\arwin\\ → %USERPROFILE%\\
```

### 2. Push to GitHub

```bash
cd /c/Users/arwin/Desktop/qut-student-toolkit
git config user.email "arwinkt@users.noreply.github.com"
git add .
git commit -m "Update message"
git push origin master
```

## Relevant Paths

- **Public Folder:** `C:\Users\arwin\Desktop\qut-student-toolkit\`
- **GitHub Repo:** `https://github.com/arwinkt/qut-student-toolkit`
- **Master Scripts:** `C:\Users\arwin\second_brain\scripts\`

## What NOT to Include

- `.canvas_cookies.json` — active Canvas session
- `.qut_outlook_cache.json` — MSAL token cache
- `.qut_device_code.txt` — device code state
- `.playwright_canvas_profile/` — browser profile (massive, personal)
- `scan_school.py` — tightly coupled to personal vault structure
- `compile.py`, `flush.py`, `inject_context.py` — personal vault management tools
