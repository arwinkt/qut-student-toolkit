"""
canvas.py — QUT Canvas CLI (no admin token needed)
====================================================
Uses your existing browser session cookies to authenticate.

Scrubbed Version — Shared for educational purposes.
"""

import os
import sys
import json
import sqlite3
import shutil
import re
import argparse
from pathlib import Path
from datetime import datetime

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
SCHOOL_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Desktop\school"))
CANVAS_DOMAIN = "canvas.qut.edu.au"
CANVAS_BASE = f"https://{CANVAS_DOMAIN}"
COOKIE_CACHE = SCRIPT_DIR / ".canvas_cookies.json"

def get_canvas_auth():
    if COOKIE_CACHE.exists():
        cache = json.loads(COOKIE_CACHE.read_text())
        if cache.get("expires", 0) > datetime.now().timestamp():
            return cache["headers"], cache["base_url"]
    
    # Non-interactive fallback
    env_cookie = os.environ.get("CANVAS_COOKIE", "")
    if env_cookie:
        return _build_auth_from_string(env_cookie)
    
    print("❌ No authentication found. Please set CANVAS_COOKIE env var or provide .canvas_cookies.json.")
    sys.exit(1)

def _build_auth_from_string(cookie_str: str):
    headers = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    return headers, CANVAS_BASE

def canvas_request(endpoint: str):
    import urllib.request
    headers, base_url = get_canvas_auth()
    url = f"{base_url}/api/v1/{endpoint}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode())

def cmd_courses():
    courses = canvas_request("courses")
    for c in courses:
        print(f"{c.get('id')} - {c.get('name')}")

if __name__ == "__main__":
    cmd_courses()
