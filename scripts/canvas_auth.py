     1|"""
     2|canvas_auth.py — One-time Canvas login via Playwright
     3|======================================================
     4|Opens a Chromium window → you log into Canvas once →
     5|cookies are saved for the canvas.py CLI to use forever.
     6|
     7|Usage:
     8|    python scripts/canvas_auth.py
     9|
    10|After running this once, canvas.py will work without any manual cookie copying.
    11|Re-run whenever your Canvas session expires (every few weeks).
    12|"""
    13|
    14|import json
    15|import sys
    16|from pathlib import Path
    17|from datetime import datetime
    18|
    19|SCRIPT_DIR = Path(__file__).parent
    20|COOKIE_FILE = SCRIPT_DIR / ".canvas_cookies.json"
    21|
    22|
    23|def main():
    24|    try:
    25|        from playwright.sync_api import sync_playwright
    26|    except ImportError:
    27|        print("❌ Playwright not installed.")
    28|        print("   pip install playwright && python -m playwright install chromium")
    29|        sys.exit(1)
    30|    
    31|    print("""
    32|╔══════════════════════════════════════════════════════════════╗
    33|║  🔐 Canvas Authentication — One-Time Setup                  ║
    34|║                                                              ║
    35|║  A Chromium window will open.                               ║
    36|║  → Log into Canvas with your QUT credentials                ║
    37|║  → Wait for your course dashboard to load                   ║
    38|║  → Close the browser window when done                       ║
    39|║                                                              ║
    40|║  Cookies will be saved for all future canvas.py usage.      ║
    41|╚══════════════════════════════════════════════════════════════╝
    42|""")
    43|    
    44|    print("🚀 Launching browser directly...")
    45|    
    46|    with sync_playwright() as p:
    47|        # Launch persistent browser (cookies survive restarts)
    48|        user_data_dir = SCRIPT_DIR / ".playwright_canvas_profile"
    49|        user_data_dir.mkdir(exist_ok=True)
    50|        
    51|        print("\n🚀 Launching browser...")
    52|        context = p.chromium.launch_persistent_context(
    53|            user_data_dir=str(user_data_dir),
    54|            headless=False,
    55|            viewport={"width": 1280, "height": 900},
    56|            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    57|        )
    58|        
    59|        page = context.new_page()
    60|        
    61|        # Navigate to Canvas
    62|        print("📂 Opening Canvas...")
    63|        page.goto("https://canvas.qut.edu.au/", wait_until="domcontentloaded")
    64|        
    65|        # Wait for login to complete
    66|        print("⏳ Waiting for you to log in...")
    67|        print("   → Use your QUT Microsoft account to sign in")
    68|        print("   → Complete MFA if prompted")
    69|        print()
    70|        
    71|        # Wait until we see the Canvas dashboard (not the login page)
    72|        try:
    73|            # Wait for either the dashboard or course list to appear
    74|            page.wait_for_selector(
    75|                "body.dashboard-is-plain, #dashboard, .ic-Dashboard-header, "
    76|                "ul[aria-label='Global Navigation'], #course_list",
    77|                timeout=300_000  # 5 minutes to log in
    78|            )
    79|            print("✅ Canvas dashboard loaded!")
    80|        except Exception:
    81|            # Fallback: check if we're on canvas and not on microsoft login
    82|            current_url = page.url
    83|            if "canvas.qut.edu.au" in current_url and "login" not in current_url.lower():
    84|                print("✅ Detected Canvas (non-login page)")
    85|            else:
    86|                print("\n⚠️  Timed out waiting for dashboard. Checking current state...")
    87|                print(f"   Current URL: {current_url}")
    88|                
    89|                # Maybe already logged in from previous session
    90|                if "canvas.qut.edu.au" in current_url:
    91|                    print("   On Canvas domain — proceeding to save whatever cookies exist.")
    92|                else:
    93|                    print("   Not on Canvas yet. Close the browser and try again.")
    94|                    input("Press Enter to close browser...")
    95|                    context.close()
    96|                    sys.exit(1)
    97|        
    98|        # Wait a moment for all cookies to be set
    99|        page.wait_for_timeout(3000)
   100|        
   101|        # Extract cookies
   102|        cookies = context.cookies()
   103|        
   104|        # Filter to Canvas domain
   105|        canvas_cookies = [c for c in cookies if "canvas" in c.get("domain", "") or "qut" in c.get("domain", "")]
   106|        
   107|        if not canvas_cookies:
   108|            print("⚠️  No Canvas cookies found. Using all cookies from browser.")
   109|            canvas_cookies = cookies
   110|        
   111|        # Build cookie string for API requests
   112|        cookie_str = "; ".join(
   113|            f"{c['name']}={c['value']}" 
   114|            for c in canvas_cookies 
   115|            if c.get("name") and c.get("value")
   116|        )
   117|        
   118|        if not cookie_str:
   119|            print("❌ No cookies captured. Something went wrong.")
   120|            context.close()
   121|            sys.exit(1)
   122|        
   123|        # Save to cache file
   124|        cache = {
   125|            "headers": {
   126|                "Cookie": cookie_str,
   127|                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
   128|                "Accept": "application/json",
   129|                "X-Requested-With": "XMLHttpRequest",
   130|            },
   131|            "base_url": "https://canvas.qut.edu.au",
   132|            "expires": datetime.now().timestamp() + 86400 * 7,  # 7 days
   133|        }
   134|        
   135|        COOKIE_FILE.write_text(json.dumps(cache, indent=2))
   136|        
   137|        print(f"\n✅ Cookies saved! ({len(canvas_cookies)} cookies)")
   138|        print(f"   Valid for Canvas API requests for ~7 days")
   139|        print(f"   File: {COOKIE_FILE}")
   140|        
   141|        print("\n💡 Browser will close in 10 seconds...")
   142|        print("   Run: python scripts/canvas.py courses")
   143|        
   144|        page.wait_for_timeout(10_000)
   145|        context.close()
   146|    
   147|    print("✅ Setup complete!")
   148|
   149|
   150|if __name__ == "__main__":
   151|    main()
   152|