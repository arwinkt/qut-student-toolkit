     1|"""
     2|canvas.py — QUT Canvas CLI (no admin token needed)
     3|====================================================
     4|Uses your existing Chrome session cookies to authenticate.
     5|Pull course content, files, pages — all formats.
     6|
     7|COMMANDS:
     8|    python scripts/canvas.py courses              # List your courses
     9|    python scripts/canvas.py files COURSE_ID       # List files for a course
    10|    python scripts/canvas.py modules COURSE_ID      # List modules + items
    11|    python scripts/canvas.py pull COURSE_ID         # Download ALL course files
    12|    python scripts/canvas.py pull-all               # Pull ALL courses
    13|    python scripts/canvas.py pages COURSE_ID        # List pages
    14|    python scripts/canvas.py page COURSE_ID URL     # Get page content
    15|    python scripts/canvas.py scan                   # Run scan_school.py after pull
    16|
    17|SETUP (one-time):
    18|    pip install browser-cookie3 canvasapi pdfplumber python-docx python-pptx openpyxl Pillow
    19|
    20|HOW IT WORKS:
    21|    Extracts your canvas.qut.edu.au session cookie from Chrome.
    22|    Uses it to auth Canvas API calls. No admin token needed.
    23|    Files download to: Desktop/school/<Course Name>/
    24|    Then run `canvas.py scan` to convert to Obsidian notes via scan_school.py
    25|"""
    26|
    27|import os
    28|import sys
    29|import json
    30|import sqlite3
    31|import shutil
    32|import re
    33|import argparse
    34|from pathlib import Path
    35|from datetime import datetime
    36|from urllib.parse import urljoin, urlparse
    37|
    38|# ── Paths ──────────────────────────────────────────────────────────────────
    39|SCRIPT_DIR = Path(__file__).parent
    40|VAULT_DIR = SCRIPT_DIR.parent
    41|SCHOOL_DIR = Path(os.path.expandvars(r"%USERPROFILE%\Desktop\school"))
    42|CANVAS_DOMAIN = "canvas.qut.edu.au"
    43|CANVAS_BASE = f"https://{CANVAS_DOMAIN}"
    44|COOKIE_CACHE = SCRIPT_DIR / ".canvas_cookies.json"
    45|
    46|# ── Cookie Extraction ──────────────────────────────────────────────────────
    47|
    48|def get_chrome_cookies(domain: str) -> dict:
    49|    """Extract cookies for domain from Chrome's cookie DB."""
    50|    chrome_db = Path(os.path.expandvars(
    51|        r"%LOCALAPPDATA%\Google\Chrome\User Data\Default\Network\Cookies"
    52|    ))
    53|    
    54|    if not chrome_db.exists():
    55|        return {}
    56|    
    57|    # Copy DB (Chrome locks it while running)
    58|    tmp_db = SCRIPT_DIR / ".chrome_cookies_tmp.db"
    59|    shutil.copy2(chrome_db, tmp_db)
    60|    
    61|    try:
    62|        conn = sqlite3.connect(str(tmp_db))
    63|        conn.row_factory = sqlite3.Row
    64|        cursor = conn.cursor()
    65|        cursor.execute(
    66|            "SELECT name, value, host_key FROM cookies WHERE host_key LIKE ?",
    67|            (f"%{domain}%",)
    68|        )
    69|        cookies = {}
    70|        for row in cursor.fetchall():
    71|            cookies[row["name"]] = row["value"]
    72|        conn.close()
    73|    except Exception as e:
    74|        print(f"  ⚠️  Cookie extraction warning: {e}")
    75|        cookies = {}
    76|    finally:
    77|        if tmp_db.exists():
    78|            tmp_db.unlink()
    79|    
    80|    return cookies
    81|
    82|
    83|def get_canvas_auth():
    84|    """Get authentication for Canvas API calls. Returns (headers, base_url).
    85|    
    86|    First checks cached cookies (valid 12h for Canvas sessions).
    87|    If expired, prompts user to paste a fresh cookie header from Chrome DevTools.
    88|    """
    89|    
    90|    # Try Playwright-persisted cookies first (from canvas_auth.py setup)
    91|    playwright_cache = SCRIPT_DIR / ".canvas_cookies.json"
    92|    if playwright_cache.exists():
    93|        cache = json.loads(playwright_cache.read_text())
    94|        if cache.get("expires", 0) > datetime.now().timestamp():
    95|            return cache["headers"], cache["base_url"]
    96|    
    97|    # Try old COOKIE_CACHE
    98|    if COOKIE_CACHE.exists():
    99|        cache = json.loads(COOKIE_CACHE.read_text())
   100|        if cache.get("expires", 0) > datetime.now().timestamp():
   101|            return cache["headers"], cache["base_url"]
   102|    
   103|    # Try auto-extract from Chrome (may fail due to encryption)
   104|    cookies = get_chrome_cookies(CANVAS_DOMAIN)
   105|    if cookies:
   106|        return _build_auth(cookies)
   107|    
   108|    # Try environment variable (non-interactive fallback)
   109|    env_cookie = os.environ.get("CANVAS_COOKIE", "")
   110|    if env_cookie:
   111|        return _build_auth_from_string(env_cookie)
   112|    
   113|    # Manual cookie input (interactive only)
   114|    if not sys.stdin.isatty():
   115|        print("❌ Not a terminal and no CANVAS_COOKIE env var set.")
   116|        print("   Set CANVAS_COOKIE env var or run interactively.")
   117|        print("   canvas.qut.edu.au → F12 → Console → document.cookie")
   118|        sys.exit(1)
   119|    print("""
   120|╔══════════════════════════════════════════════════════════════╗
   121|║  🔐 Canvas Authentication Setup                             ║
   122|║                                                              ║
   123|║  1. Open Chrome → go to canvas.qut.edu.au                    ║
   124|║  2. Make sure you're logged in (courses should be visible)   ║
   125|║  3. Press F12 → Application tab → Cookies → canvas.qut.edu.au║
   126|║  4. Copy ALL cookie names and values                         ║
   127|║                                                              ║
   128|║  Quick method (paste as one line):                           ║
   129|║    In DevTools Console, run this and copy the output:        ║
   130|║    document.cookie                                           ║
   131|║                                                              ║
   132|║  Or paste in format: name1=val1; name2=val2; ...             ║
   133|╚══════════════════════════════════════════════════════════════╝
   134|""")
   135|    
   136|    try:
   137|        cookie_str = input("Paste cookie string: ").strip()
   138|    except (EOFError, KeyboardInterrupt):
   139|        print("\n❌ No input. Can't auth without cookies.")
   140|        sys.exit(1)
   141|    
   142|    if not cookie_str:
   143|        print("❌ Empty cookie string.")
   144|        sys.exit(1)
   145|    
   146|    return _build_auth_from_string(cookie_str)
   147|
   148|
   149|def _build_auth_from_string(cookie_str: str):
   150|    """Build auth headers from a raw cookie string."""
   151|    headers = {
   152|        "Cookie": cookie_str,
   153|        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
   154|        "Accept": "application/json",
   155|        "X-Requested-With": "XMLHttpRequest",
   156|    }
   157|    
   158|    # Cache for 12 hours (Canvas sessions are long-lived)
   159|    COOKIE_CACHE.write_text(json.dumps({
   160|        "headers": headers,
   161|        "base_url": CANVAS_BASE,
   162|        "expires": datetime.now().timestamp() + 43200
   163|    }))
   164|    
   165|    return headers, CANVAS_BASE
   166|
   167|
   168|def _build_auth(cookies: dict):
   169|    """Build auth headers from a dict of cookies."""
   170|    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
   171|    return _build_auth_from_string(cookie_str)
   172|
   173|
   174|def canvas_request(endpoint: str, params: dict = None) -> dict | list:
   175|    """Make an authenticated request to the Canvas API."""
   176|    import urllib.request
   177|    import urllib.parse
   178|    
   179|    headers, base_url = get_canvas_auth()
   180|    
   181|    url = f"{base_url}/api/v1/{endpoint}"
   182|    if params:
   183|        url += "?" + urllib.parse.urlencode(params)
   184|    
   185|    req = urllib.request.Request(url, headers=headers)
   186|    
   187|    try:
   188|        with urllib.request.urlopen(req) as resp:
   189|            return json.loads(resp.read().decode())
   190|    except urllib.error.HTTPError as e:
   191|        if e.code == 401:
   192|            print("❌ Session expired. Re-login to Canvas in Chrome and try again.")
   193|            COOKIE_CACHE.unlink(missing_ok=True)
   194|            sys.exit(1)
   195|        elif e.code == 403:
   196|            print(f"❌ Access denied to: {endpoint}")
   197|            return []
   198|        elif e.code == 404:
   199|            print(f"❌ Not found: {endpoint}")
   200|            return []
   201|        else:
   202|            print(f"❌ HTTP {e.code} for: {endpoint}")
   203|            return []
   204|    except Exception as e:
   205|        print(f"❌ Request failed: {e}")
   206|        return []
   207|
   208|
   209|def canvas_get_paginated(endpoint: str, params: dict = None) -> list:
   210|    """Get all pages of a paginated Canvas API endpoint."""
   211|    if params is None:
   212|        params = {}
   213|    params["per_page"] = 100
   214|    
   215|    all_items = []
   216|    url_path = endpoint
   217|    
   218|    while url_path:
   219|        headers, base_url = get_canvas_auth()
   220|        
   221|        import urllib.request, urllib.parse
   222|        full_url = f"{base_url}/api/v1/{url_path}"
   223|        if "?" not in full_url and params:
   224|            full_url += "?" + urllib.parse.urlencode(params)
   225|        
   226|        req = urllib.request.Request(full_url, headers=headers)
   227|        
   228|        try:
   229|            with urllib.request.urlopen(req) as resp:
   230|                all_items.extend(json.loads(resp.read().decode()))
   231|                
   232|                # Check Link header for next page
   233|                link = resp.headers.get("Link", "")
   234|                next_match = re.search(r'<https://[^>]+/api/v1/([^>]+)>;\s*rel="next"', link)
   235|                if next_match:
   236|                    url_path = next_match.group(1)
   237|                    params = {}  # URL already has params
   238|                else:
   239|                    url_path = None
   240|        except Exception as e:
   241|            print(f"  ⚠️  Pagination error: {e}")
   242|            break
   243|    
   244|    return all_items
   245|
   246|
   247|# ── Commands ────────────────────────────────────────────────────────────────
   248|
   249|def cmd_courses():
   250|    """List all courses."""
   251|    print("\n📚 Your QUT Canvas Courses\n")
   252|    print(f"{'ID':<8} {'Name':<50} {'Code':<20}")
   253|    print("-" * 78)
   254|    
   255|    courses = canvas_get_paginated("courses", {"enrollment_state": "active"})
   256|    
   257|    for c in courses:
   258|        cid = c.get("id", "?")
   259|        name = c.get("name", "Unknown")[:50]
   260|        code = c.get("course_code", "")[:20]
   261|        print(f"{cid:<8} {name:<50} {code:<20}")
   262|    
   263|    print(f"\n{courses and len(courses) or 0} active courses")
   264|    return courses
   265|
   266|
   267|def cmd_files(course_id: int):
   268|    """List files for a course."""
   269|    course = _get_course(course_id)
   270|    print(f"\n📁 Files: {course.get('name', 'Unknown')}\n")
   271|    
   272|    files = canvas_get_paginated(f"courses/{course_id}/files")
   273|    
   274|    for f in files:
   275|        size_kb = (f.get("size", 0) or 0) // 1024
   276|        name = f.get("display_name", f.get("filename", "?"))
   277|        print(f"  {name:<50} {size_kb:>6}KB  ({f.get('content-type', '?')})")
   278|    
   279|    print(f"\n{files and len(files) or 0} files")
   280|    return files
   281|
   282|
   283|def cmd_modules(course_id: int):
   284|    """List modules and their items."""
   285|    course = _get_course(course_id)
   286|    print(f"\n📦 Modules: {course.get('name', 'Unknown')}\n")
   287|    
   288|    modules = canvas_get_paginated(f"courses/{course_id}/modules",
   289|                                    {"include": "items"})
   290|    
   291|    for mod in modules:
   292|        name = mod.get("name", "Unnamed")
   293|        items = mod.get("items", [])
   294|        print(f"  📂 {name} ({len(items)} items)")
   295|        for item in items:
   296|            itype = item.get("type", "?")
   297|            ititle = item.get("title", "Untitled")[:60]
   298|            print(f"      [{itype:<12}] {ititle}")
   299|    
   300|    print(f"\n{modules and len(modules) or 0} modules")
   301|    return modules
   302|
   303|
   304|def cmd_pull(course_id: int):
   305|    """Download all files for a course to Desktop/school/"""
   306|    course = _get_course(course_id)
   307|    course_name = _safe_name(course.get("name", f"course_{course_id}"))
   308|    course_dir = SCHOOL_DIR / course_name
   309|    course_dir.mkdir(parents=True, exist_ok=True)
   310|    
   311|    print(f"\n⬇️  Pulling: {course.get('name', 'Unknown')}")
   312|    print(f"   → {course_dir}\n")
   313|    
   314|    files = canvas_get_paginated(f"courses/{course_id}/files")
   315|    
   316|    downloaded = skipped = 0
   317|    for f in files:
   318|        fname = f.get("display_name", f.get("filename", "unknown"))
   319|        file_path = course_dir / fname
   320|        
   321|        if file_path.exists() and file_path.stat().st_size == (f.get("size", 0) or 0):
   322|            skipped += 1
   323|            continue
   324|        
   325|        # Download file
   326|        file_url = f.get("url", "")
   327|        if not file_url:
   328|            print(f"  ⚠️  No URL for: {fname}")
   329|            continue
   330|        
   331|        print(f"  ⬇ {fname} ({f.get('size', 0)//1024}KB)", end=" ")
   332|        try:
   333|            headers, _ = get_canvas_auth()
   334|            headers.pop("Accept", None)  # Don't want JSON for file download
   335|            
   336|            import urllib.request
   337|            req = urllib.request.Request(file_url, headers=headers)
   338|            with urllib.request.urlopen(req) as resp:
   339|                file_path.write_bytes(resp.read())
   340|            
   341|            downloaded += 1
   342|            print("✅")
   343|        except Exception as e:
   344|            print(f"❌ {e}")
   345|    
   346|    print(f"\n  Downloaded: {downloaded} | Skipped: {skipped} | Total: {len(files)}")
   347|    print(f"  📂 {course_dir}")
   348|    
   349|    # Also pull pages as markdown
   350|    _pull_pages(course_id, course_dir)
   351|    
   352|    return course_dir
   353|
   354|
   355|def _pull_pages(course_id: int, course_dir: Path):
   356|    """Pull Canvas pages as markdown files."""
   357|    pages = canvas_get_paginated(f"courses/{course_id}/pages")
   358|    if not pages:
   359|        return
   360|    
   361|    pages_dir = course_dir / "_pages"
   362|    pages_dir.mkdir(exist_ok=True)
   363|    
   364|    print(f"\n  📄 Pulling {len(pages)} pages...")
   365|    pulled = 0
   366|    for page in pages:
   367|        title = page.get("title", "Untitled")
   368|        safe_title = _safe_name(title)
   369|        page_path = pages_dir / f"{safe_title}.md"
   370|        
   371|        if page_path.exists():
   372|            continue
   373|        
   374|        # Get full page body
   375|        page_url = page.get("url", "")
   376|        if not page_url:
   377|            continue
   378|        
   379|        try:
   380|            headers, _ = get_canvas_auth()
   381|            import urllib.request
   382|            req = urllib.request.Request(page_url, headers=headers)
   383|            with urllib.request.urlopen(req) as resp:
   384|                data = json.loads(resp.read().decode())
   385|            
   386|            body = data.get("body", "")
   387|            # Strip HTML tags for markdown
   388|            body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL)
   389|            body = re.sub(r'<style[^>]*>.*?</style>', '', body, flags=re.DOTALL)
   390|            body = re.sub(r'<br\s*/?>', '\n', body)
   391|            body = re.sub(r'</p>', '\n\n', body)
   392|            body = re.sub(r'</h[1-6]>', '\n\n', body)
   393|            body = re.sub(r'<li>', '- ', body)
   394|            body = re.sub(r'</li>', '\n', body)
   395|            body = re.sub(r'<[^>]+>', '', body)
   396|            body = re.sub(r'\n{3,}', '\n\n', body)
   397|            body = re.sub(r'&amp;', '&', body)
   398|            body = re.sub(r'&lt;', '<', body)
   399|            body = re.sub(r'&gt;', '>', body)
   400|            
   401|            content = f"---\ntitle: \"{title}\"\nsource: \"{page.get('html_url', '')}\"\npulled: \"{datetime.now().strftime('%Y-%m-%d')}\"\ncourse_id: {course_id}\n---\n\n# {title}\n\n{body}"
   402|            
   403|            page_path.write_text(content, encoding="utf-8")
   404|            pulled += 1
   405|        except Exception as e:
   406|            print(f"    ⚠️  {title}: {e}")
   407|    
   408|    if pulled:
   409|        print(f"    ✅ {pulled} pages → {pages_dir}")
   410|
   411|
   412|def cmd_pull_all():
   413|    """Pull all active courses."""
   414|    courses = canvas_get_paginated("courses", {"enrollment_state": "active"})
   415|    
   416|    print(f"\n⬇️  Pulling ALL {len(courses)} courses...\n")
   417|    
   418|    for c in courses:
   419|        cid = c.get("id")
   420|        try:
   421|            cmd_pull(cid)
   422|        except Exception as e:
   423|            print(f"  ❌ Failed: {c.get('name', '?')} — {e}")
   424|
   425|
   426|def cmd_scan():
   427|    """Run scan_school.py to convert downloaded files to Obsidian notes."""
   428|    scan_script = SCRIPT_DIR / "scan_school.py"
   429|    if not scan_script.exists():
   430|        print(f"❌ scan_school.py not found at {scan_script}")
   431|        sys.exit(1)
   432|    
   433|    print("\n🔍 Running scan_school.py...\n")
   434|    import subprocess
   435|    result = subprocess.run(
   436|        [sys.executable, str(scan_script)],
   437|        cwd=str(VAULT_DIR),
   438|        capture_output=False
   439|    )
   440|
   441|
   442|def cmd_pages(course_id: int):
   443|    """List pages for a course."""
   444|    course = _get_course(course_id)
   445|    print(f"\n📄 Pages: {course.get('name', 'Unknown')}\n")
   446|    
   447|    pages = canvas_get_paginated(f"courses/{course_id}/pages")
   448|    
   449|    for p in pages:
   450|        title = p.get("title", "Untitled")[:70]
   451|        updated = p.get("updated_at", "")[:10]
   452|        url = p.get("html_url", "")
   453|        print(f"  {title:<70} {updated}")
   454|    
   455|    print(f"\n{pages and len(pages) or 0} pages")
   456|
   457|
   458|# ── Helpers ─────────────────────────────────────────────────────────────────
   459|
   460|def _get_course(course_id: int) -> dict:
   461|    """Get a single course by ID."""
   462|    courses = canvas_get_paginated("courses", {"enrollment_state": "active"})
   463|    for c in courses:
   464|        if c.get("id") == course_id:
   465|            return c
   466|    print(f"❌ Course {course_id} not found in your active courses.")
   467|    print("   Run: python scripts/canvas.py courses")
   468|    sys.exit(1)
   469|
   470|
   471|def _safe_name(name: str) -> str:
   472|    """Make a safe directory/file name."""
   473|    name = re.sub(r'[\\/:*?"<>|]', "", name)
   474|    return re.sub(r"\s+", " ", name).strip()
   475|
   476|
   477|def _check_auth():
   478|    """Quick check that we can reach Canvas."""
   479|    headers, _ = get_canvas_auth()
   480|    print(f"✅ Canvas session OK ({CANVAS_BASE})")
   481|    return True
   482|
   483|
   484|# ── Main ────────────────────────────────────────────────────────────────────
   485|
   486|def main():
   487|    parser = argparse.ArgumentParser(
   488|        description="QUT Canvas CLI — pull course content without admin token"
   489|    )
   490|    parser.add_argument("command", 
   491|                       choices=["courses", "files", "modules", "pull", "pull-all", 
   492|                               "pages", "page", "scan", "auth", "check"],
   493|                       help="What to do")
   494|    parser.add_argument("args", nargs="*", help="Extra args (course_id, etc.)")
   495|    
   496|    args = parser.parse_args()
   497|    
   498|    if args.command in ("auth", "check"):
   499|        _check_auth()
   500|        return
   501|