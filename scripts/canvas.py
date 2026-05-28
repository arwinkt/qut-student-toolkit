"""
canvas.py — QUT Canvas CLI (no admin token needed)
====================================================
Uses your existing Chrome session cookies to authenticate.
Pull course content, files, pages — all formats.

COMMANDS:
    python scripts/canvas.py courses              # List your courses
    python scripts/canvas.py files COURSE_ID       # List files for a course
    python scripts/canvas.py modules COURSE_ID      # List modules + items
    python scripts/canvas.py pull COURSE_ID         # Download ALL course files
    python scripts/canvas.py pull-all               # Pull ALL courses
    python scripts/canvas.py pages COURSE_ID        # List pages
    python scripts/canvas.py page COURSE_ID URL     # Get page content
    python scripts/canvas.py scan                   # Run scan_school.py after pull

SETUP (one-time):
    pip install browser-cookie3 canvasapi pdfplumber python-docx python-pptx openpyxl Pillow

HOW IT WORKS:
    Extracts your canvas.qut.edu.au session cookie from Chrome.
    Uses it to auth Canvas API calls. No admin token needed.
    Files download to: Desktop/school/<Course Name>/
    Then run `canvas.py scan` to convert to Obsidian notes via scan_school.py
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
from urllib.parse import urljoin, urlparse

# ── Paths ──────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
VAULT_DIR = SCRIPT_DIR.parent
SCHOOL_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Desktop\school"))
CANVAS_DOMAIN = "canvas.qut.edu.au"
CANVAS_BASE = f"https://{CANVAS_DOMAIN}"
COOKIE_CACHE = SCRIPT_DIR / ".canvas_cookies.json"

# ── Cookie Extraction ──────────────────────────────────────────────────────

def get_chrome_cookies(domain: str) -> dict:
    """Extract cookies for domain from Chrome's cookie DB."""
    chrome_db = Path(os.path.expandvars(
        r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies"
    ))
    
    if not chrome_db.exists():
        return {}
    
    # Copy DB (Chrome locks it while running)
    tmp_db = SCRIPT_DIR / ".chrome_cookies_tmp.db"
    shutil.copy2(chrome_db, tmp_db)
    
    try:
        conn = sqlite3.connect(str(tmp_db))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name, value, host_key FROM cookies WHERE host_key LIKE ?",
            (f"%{domain}%",)
        )
        cookies = {}
        for row in cursor.fetchall():
            cookies[row["name"]] = row["value"]
        conn.close()
    except Exception as e:
        print(f"  ⚠️  Cookie extraction warning: {e}")
        cookies = {}
    finally:
        if tmp_db.exists():
            tmp_db.unlink()
    
    return cookies


def get_canvas_auth():
    """Get authentication for Canvas API calls. Returns (headers, base_url).
    
    First checks cached cookies (valid 12h for Canvas sessions).
    If expired, prompts user to paste a fresh cookie header from Chrome DevTools.
    """
    
    # Try Playwright-persisted cookies first (from canvas_auth.py setup)
    playwright_cache = SCRIPT_DIR / ".canvas_cookies.json"
    if playwright_cache.exists():
        cache = json.loads(playwright_cache.read_text())
        if cache.get("expires", 0) > datetime.now().timestamp():
            return cache["headers"], cache["base_url"]
    
    # Try old COOKIE_CACHE
    if COOKIE_CACHE.exists():
        cache = json.loads(COOKIE_CACHE.read_text())
        if cache.get("expires", 0) > datetime.now().timestamp():
            return cache["headers"], cache["base_url"]
    
    # Try auto-extract from Chrome (may fail due to encryption)
    cookies = get_chrome_cookies(CANVAS_DOMAIN)
    if cookies:
        return _build_auth(cookies)
    
    # Try environment variable (non-interactive fallback)
    env_cookie = os.environ.get("CANVAS_COOKIE", "")
    if env_cookie:
        return _build_auth_from_string(env_cookie)
    
    # Manual cookie input (interactive only)
    if not sys.stdin.isatty():
        print("❌ Not a terminal and no CANVAS_COOKIE env var set.")
        print("   Set CANVAS_COOKIE env var or run interactively.")
        print("   canvas.qut.edu.au → F12 → Console → document.cookie")
        sys.exit(1)
    print("""
╔══════════════════════════════════════════════════════════════╗
║  🔐 Canvas Authentication Setup                             ║
║                                                              ║
║  1. Open Chrome → go to canvas.qut.edu.au                    ║
║  2. Make sure you're logged in (courses should be visible)   ║
║  3. Press F12 → Application tab → Cookies → canvas.qut.edu.au║
║  4. Copy ALL cookie names and values                         ║
║                                                              ║
║  Quick method (paste as one line):                           ║
║    In DevTools Console, run this and copy the output:        ║
║    document.cookie                                           ║
║                                                              ║
║  Or paste in format: name1=val1; name2=val2; ...             ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    try:
        cookie_str = input("Paste cookie string: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n❌ No input. Can't auth without cookies.")
        sys.exit(1)
    
    if not cookie_str:
        print("❌ Empty cookie string.")
        sys.exit(1)
    
    return _build_auth_from_string(cookie_str)


def _build_auth_from_string(cookie_str: str):
    """Build auth headers from a raw cookie string."""
    headers = {
        "Cookie": cookie_str,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
        "X-Requested-With": "XMLHttpRequest",
    }
    
    # Cache for 12 hours (Canvas sessions are long-lived)
    COOKIE_CACHE.write_text(json.dumps({
        "headers": headers,
        "base_url": CANVAS_BASE,
        "expires": datetime.now().timestamp() + 43200
    }))
    
    return headers, CANVAS_BASE


def _build_auth(cookies: dict):
    """Build auth headers from a dict of cookies."""
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    return _build_auth_from_string(cookie_str)


def canvas_request(endpoint: str, params: dict = None) -> dict | list:
    """Make an authenticated request to the Canvas API."""
    import urllib.request
    import urllib.parse
    
    headers, base_url = get_canvas_auth()
    
    url = f"{base_url}/api/v1/{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("❌ Session expired. Re-login to Canvas in Chrome and try again.")
            COOKIE_CACHE.unlink(missing_ok=True)
            sys.exit(1)
        elif e.code == 403:
            print(f"❌ Access denied to: {endpoint}")
            return []
        elif e.code == 404:
            print(f"❌ Not found: {endpoint}")
            return []
        else:
            print(f"❌ HTTP {e.code} for: {endpoint}")
            return []
    except Exception as e:
        print(f"❌ Request failed: {e}")
        return []


def canvas_get_paginated(endpoint: str, params: dict = None) -> list:
    """Get all pages of a paginated Canvas API endpoint."""
    if params is None:
        params = {}
    params["per_page"] = 100
    
    all_items = []
    url_path = endpoint
    
    while url_path:
        headers, base_url = get_canvas_auth()
        
        import urllib.request, urllib.parse
        full_url = f"{base_url}/api/v1/{url_path}"
        if "?" not in full_url and params:
            full_url += "?" + urllib.parse.urlencode(params)
        
        req = urllib.request.Request(full_url, headers=headers)
        
        try:
            with urllib.request.urlopen(req) as resp:
                all_items.extend(json.loads(resp.read().decode()))
                
                # Check Link header for next page
                link = resp.headers.get("Link", "")
                next_match = re.search(r'<https://[^>]+/api/v1/([^>]+)>;\s*rel="next"', link)
                if next_match:
                    url_path = next_match.group(1)
                    params = {}  # URL already has params
                else:
                    url_path = None
        except Exception as e:
            print(f"  ⚠️  Pagination error: {e}")
            break
    
    return all_items


# ── Commands ────────────────────────────────────────────────────────────────

def cmd_courses():
    """List all courses."""
    print("\n📚 Your QUT Canvas Courses\n")
    print(f"{'ID':<8} {'Name':<50} {'Code':<20}")
    print("-" * 78)
    
    courses = canvas_get_paginated("courses", {"enrollment_state": "active"})
    
    for c in courses:
        cid = c.get("id", "?")
        name = c.get("name", "Unknown")[:50]
        code = c.get("course_code", "")[:20]
        print(f"{cid:<8} {name:<50} {code:<20}")
    
    print(f"\n{courses and len(courses) or 0} active courses")
    return courses


def cmd_files(course_id: int):
    """List files for a course."""
    course = _get_course(course_id)
    print(f"\n📁 Files: {course.get('name', 'Unknown')}\n")
    
    files = canvas_get_paginated(f"courses/{course_id}/files")
    
    for f in files:
        size_kb = (f.get("size", 0) or 0) // 1024
        name = f.get("display_name", f.get("filename", "?"))
        print(f"  {name:<50} {size_kb:>6}KB  ({f.get('content-type', '?')})")
    
    print(f"\n{files and len(files) or 0} files")
    return files


def cmd_modules(course_id: int):
    """List modules and their items."""
    course = _get_course(course_id)
    print(f"\n📦 Modules: {course.get('name', 'Unknown')}\n")
    
    modules = canvas_get_paginated(f"courses/{course_id}/modules",
                                    {"include": "items"})
    
    for mod in modules:
        name = mod.get("name", "Unnamed")
        items = mod.get("items", [])
        print(f"  📂 {name} ({len(items)} items)")
        for item in items:
            itype = item.get("type", "?")
            ititle = item.get("title", "Untitled")[:60]
            print(f"      [{itype:<12}] {ititle}")
    
    print(f"\n{modules and len(modules) or 0} modules")
    return modules


def cmd_pull(course_id: int):
    """Download all files for a course to Desktop/school/"""
    course = _get_course(course_id)
    course_name = _safe_name(course.get("name", f"course_{course_id}"))
    course_dir = SCHOOL_DIR / course_name
    course_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"\n⬇️  Pulling: {course.get('name', 'Unknown')}")
    print(f"   → {course_dir}\n")
    
    files = canvas_get_paginated(f"courses/{course_id}/files")
    
    downloaded = skipped = 0
    for f in files:
        fname = f.get("display_name", f.get("filename", "unknown"))
        file_path = course_dir / fname
        
        if file_path.exists() and file_path.stat().st_size == (f.get("size", 0) or 0):
            skipped += 1
            continue
        
        # Download file
        file_url = f.get("url", "")
        if not file_url:
            print(f"  ⚠️  No URL for: {fname}")
            continue
        
        print(f"  ⬇ {fname} ({f.get('size', 0)//1024}KB)", end=" ")
        try:
            headers, _ = get_canvas_auth()
            headers.pop("Accept", None)  # Don't want JSON for file download
            
            import urllib.request
            req = urllib.request.Request(file_url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                file_path.write_bytes(resp.read())
            
            downloaded += 1
            print("✅")
        except Exception as e:
            print(f"❌ {e}")
    
    print(f"\n  Downloaded: {downloaded} | Skipped: {skipped} | Total: {len(files)}")
    print(f"  📂 {course_dir}")
    
    # Also pull pages as markdown
    _pull_pages(course_id, course_dir)
    
    return course_dir


def _pull_pages(course_id: int, course_dir: Path):
    """Pull Canvas pages as markdown files."""
    pages = canvas_get_paginated(f"courses/{course_id}/pages")
    if not pages:
        return
    
    pages_dir = course_dir / "_pages"
    pages_dir.mkdir(exist_ok=True)
    
    print(f"\n  📄 Pulling {len(pages)} pages...")
    pulled = 0
    for page in pages:
        title = page.get("title", "Untitled")
        safe_title = _safe_name(title)
        page_path = pages_dir / f"{safe_title}.md"
        
        if page_path.exists():
            continue
        
        # Get full page body
        page_url = page.get("url", "")
        if not page_url:
            continue
        
        try:
            headers, _ = get_canvas_auth()
            import urllib.request
            req = urllib.request.Request(page_url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                data = json.loads(resp.read().decode())
            
            body = data.get("body", "")
            # Strip HTML tags for markdown
            body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL)
            body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL)
            body = re.sub(r'<br\s*/?>', '\n', body)
            body = re.sub(r'</p>', '\n\n', body)
            body = re.sub(r'</h[1-6]>', '\n\n', body)
            body = re.sub(r'<li>', '- ', body)
            body = re.sub(r'</li>', '\n', body)
            body = re.sub(r'<[^>]+>', '', body)
            body = re.sub(r'\n{3,}', '\n\n', body)
            body = re.sub(r'&amp;', '&', body)
            body = re.sub(r'&lt;', '<', body)
            body = re.sub(r'&gt;', '>', body)
            
            content = f"---\ntitle: \"{title}\"\nsource: \"{page.get('html_url', '')}\"\npulled: \"{datetime.now().strftime('%Y-%m-%d')}\"\ncourse_id: {course_id}\n---\n\n# {title}\n\n{body}"
            
            page_path.write_text(content, encoding="utf-8")
            pulled += 1
        except Exception as e:
            print(f"    ⚠️  {title}: {e}")
    
    if pulled:
        print(f"    ✅ {pulled} pages → {pages_dir}")


def cmd_pull_all():
    """Pull all active courses."""
    courses = canvas_get_paginated("courses", {"enrollment_state": "active"})
    
    print(f"\n⬇️  Pulling ALL {len(courses)} courses...\n")
    
    for c in courses:
        cid = c.get("id")
        try:
            cmd_pull(cid)
        except Exception as e:
            print(f"  ❌ Failed: {c.get('name', '?')} — {e}")


def cmd_scan():
    """Run scan_school.py to convert downloaded files to Obsidian notes."""
    scan_script = SCRIPT_DIR / "scan_school.py"
    if not scan_script.exists():
        print(f"❌ scan_school.py not found at {scan_script}")
        sys.exit(1)
    
    print("\n🔍 Running scan_school.py...\n")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(scan_script)],
        cwd=str(VAULT_DIR),
        capture_output=False
    )


def cmd_pages(course_id: int):
    """List pages for a course."""
    course = _get_course(course_id)
    print(f"\n📄 Pages: {course.get('name', 'Unknown')}\n")
    
    pages = canvas_get_paginated(f"courses/{course_id}/pages")
    
    for p in pages:
        title = p.get("title", "Untitled")[:70]
        updated = p.get("updated_at", "")[:10]
        url = p.get("html_url", "")
        print(f"  {title:<70} {updated}")
    
    print(f"\n{pages and len(pages) or 0} pages")


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_course(course_id: int) -> dict:
    """Get a single course by ID."""
    courses = canvas_get_paginated("courses", {"enrollment_state": "active"})
    for c in courses:
        if c.get("id") == course_id:
            return c
    print(f"❌ Course {course_id} not found in your active courses.")
    print("   Run: python scripts/canvas.py courses")
    sys.exit(1)


def _safe_name(name: str) -> str:
    """Make a safe directory/file name."""
    name = re.sub(r'[\\/:*?"<>|]', "", name)
    return re.sub(r"\s+", " ", name).strip()


def _check_auth():
    """Quick check that we can reach Canvas."""
    headers, _ = get_canvas_auth()
    print(f"✅ Canvas session OK ({CANVAS_BASE})")
    return True


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="QUT Canvas CLI — pull course content without admin token"
    )
    parser.add_argument("command", 
                       choices=["courses", "files", "modules", "pull", "pull-all", 
                               "pages", "page", "scan", "auth", "check"],
                       help="What to do")
    parser.add_argument("args", nargs="*", help="Extra args (course_id, etc.)")
    
    args = parser.parse_args()
    
    if args.command in ("auth", "check"):
        _check_auth()
        return
