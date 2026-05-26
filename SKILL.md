---
name: qut-student-toolkit
category: productivity
description: Set of tools to bypass admin blocks and automate QUT student systems (Canvas + Outlook).
---

# QUT Student Toolkit

This toolkit contains automated workflows to help QUT students access their data programmatically without needing administrator-level API tokens.

## Included Tools

### 1. Outlook Access (`qut_outlook.py`)
Uses the "Office Native App" client ID to bypass Graph API blocks.
- One-time device code auth.
- Fetch inbox headers and search messages via Graph API.
- Persistent token caching (re-auth once a week).

### 2. Canvas Downloader (`canvas.py`)
Uses session cookies from your browser to pull course content.
- List active courses and file structures.
- Bulk download all course files, modules, and pages.
- Converts Canvas pages into Markdown for local search/Obsidian.

## Setup Instructions

### Pre-requisites
- Python 3.8+
- `pip install msal requests canvasapi pdfplumber python-docx python-pptx openpyxl Pillow`

### Running the Tools
1. **Outlook:** `python qut_outlook.py auth` to link your student account.
2. **Canvas:** `python canvas.py auth` to verify your session cookies.
3. **Pull All Content:** `python canvas.py pull-all`

## Safety Disclaimer
These tools are for personal academic use. They do not store passwords. They use official Microsoft and Canvas endpoints via your own active sessions. Never share your `.qut_outlook_cache.json` or `.canvas_cookies.json` files as they contain your active session tokens.
