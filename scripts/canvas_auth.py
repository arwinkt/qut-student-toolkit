"""
canvas_auth.py — One-time Canvas login via Playwright
======================================================
Opens a Chromium window → you log into Canvas once →
cookies are saved for the canvas.py CLI to use forever.

Usage:
    python scripts/canvas_auth.py

After running this once, canvas.py will work without any manual cookie copying.
Re-run whenever your Canvas session expires (every few weeks).
"""

import json
import sys
from pathlib import Path
from datetime import datetime

SCRIPT_DIR = Path(__file__).parent
COOKIE_FILE = SCRIPT_DIR / ".canvas_cookies.json"


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ Playwright not installed.")
        print("   pip install playwright && python -m playwright install chromium")
        sys.exit(1)
    
    print("""
╔══════════════════════════════════════════════════════════════╗
║  🔐 Canvas Authentication — One-Time Setup                  ║
║                                                              ║
║  A Chromium window will open.                               ║
║  → Log into Canvas with your QUT credentials                ║
║  → Wait for your course dashboard to load                   ║
║  → Close the browser window when done                       ║
║                                                              ║
║  Cookies will be saved for all future canvas.py usage.      ║
╚══════════════════════════════════════════════════════════════╝
""")
    
    print("🚀 Launching browser directly...")
    
    with sync_playwright() as p:
        # Launch persistent browser (cookies survive restarts)
        user_data_dir = SCRIPT_DIR / ".playwright_canvas_profile"
        user_data_dir.mkdir(exist_ok=True)
        
        print("\n🚀 Launching browser...")
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=False,
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
        
        page = context.new_page()
        
        # Navigate to Canvas
        print("📂 Opening Canvas...")
        page.goto("https://canvas.qut.edu.au/", wait_until="domcontentloaded")
        
        # Wait for login to complete
        print("⏳ Waiting for you to log in...")
        print("   → Use your QUT Microsoft account to sign in")
        print("   → Complete MFA if prompted")
        print()
        
        # Wait until we see the Canvas dashboard (not the login page)
        try:
            # Wait for either the dashboard or course list to appear
            page.wait_for_selector(
                "body.dashboard-is-plain, #dashboard, .ic-Dashboard-header, "
                "ul[aria-label='Global Navigation'], #course_list",
                timeout=300_000  # 5 minutes to log in
            )
            print("✅ Canvas dashboard loaded!")
        except Exception:
            # Fallback: check if we're on canvas and not on microsoft login
            current_url = page.url
            if "canvas.qut.edu.au" in current_url and "login" not in current_url.lower():
                print("✅ Detected Canvas (non-login page)")
            else:
                print("\n⚠️  Timed out waiting for dashboard. Checking current state...")
                print(f"   Current URL: {current_url}")
                
                # Maybe already logged in from previous session
                if "canvas.qut.edu.au" in current_url:
                    print("   On Canvas domain — proceeding to save whatever cookies exist.")
                else:
                    print("   Not on Canvas yet. Close the browser and try again.")
                    input("Press Enter to close browser...")
                    context.close()
                    sys.exit(1)
        
        # Wait a moment for all cookies to be set
        page.wait_for_timeout(3000)
        
        # Extract cookies
        cookies = context.cookies()
        
        # Filter to Canvas domain
        canvas_cookies = [c for c in cookies if "canvas" in c.get("domain", "") or "qut" in c.get("domain", "")]
        
        if not canvas_cookies:
            print("⚠️  No Canvas cookies found. Using all cookies from browser.")
            canvas_cookies = cookies
        
        # Build cookie string for API requests
        cookie_str = "; ".join(
            f"{c['name']}={c['value']}" 
            for c in canvas_cookies 
            if c.get("name") and c.get("value")
        )
        
        if not cookie_str:
            print("❌ No cookies captured. Something went wrong.")
            context.close()
            sys.exit(1)
        
        # Save to cache file
        cache = {
            "headers": {
                "Cookie": cookie_str,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest",
            },
            "base_url": "https://canvas.qut.edu.au",
            "expires": datetime.now().timestamp() + 86400 * 7,  # 7 days
        }
        
        COOKIE_FILE.write_text(json.dumps(cache, indent=2))
        
        print(f"\n✅ Cookies saved! ({len(canvas_cookies)} cookies)")
        print(f"   Valid for Canvas API requests for ~7 days")
        print(f"   File: {COOKIE_FILE}")
        
        print("\n💡 Browser will close in 10 seconds...")
        print("   Run: python scripts/canvas.py courses")
        
        page.wait_for_timeout(10_000)
        context.close()
    
    print("✅ Setup complete!")


if __name__ == "__main__":
    main()
