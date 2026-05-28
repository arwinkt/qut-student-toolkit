#!/usr/bin/env python3
"""
QUT Outlook access via Exchange Web Services (EWS) + device code OAuth2.

One-time auth, then persistent token cache.
Usage:
  python qut_outlook.py auth            # One-time auth
  python qut_outlook.py inbox [N]       # Recent inbox
  python qut_outlook.py sent [N]        # Recent sent
  python qut_outlook.py search "term"   # Search inbox
  python qut_outlook.py unread [N]      # Unread only
"""

import msal
import json
import sys
import re
import requests
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None

CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
AUTHORITY = "https://login.microsoftonline.com/organizations"
SCOPES = ["https://outlook.office365.com/.default"]
EWS_ENDPOINT = "https://outlook.office365.com/EWS/Exchange.asmx"
TOKEN_CACHE = Path(__file__).parent / ".qut_outlook_cache.json"
CODE_FILE = Path(__file__).parent / ".qut_device_code.txt"
USER_EMAIL = "your.email@connect.qut.edu.au"  # Replace with your student email

_token = None


def get_app():
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        with open(TOKEN_CACHE) as f:
            cache.deserialize(f.read())
    return msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)


def save_cache(app):
    if app.token_cache.has_state_changed:
        with open(TOKEN_CACHE, "w") as f:
            f.write(app.token_cache.serialize())


def auth():
    app = get_app()
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        print("ERROR: Device code flow not available.")
        print(json.dumps(flow, indent=2))
        return False

    print("=" * 55)
    print("  OPEN THIS URL ON YOUR PHONE OR LAPTOP:")
    print(f"  {flow['verification_uri']}")
    print()
    print(f"  ENTER THIS CODE:  {flow['user_code']}")
    print("=" * 55)
    print()
    print(f"Sign in with: {USER_EMAIL}")
    print("Approve the MFA prompt on your phone.")
    print()
    sys.stdout.flush()

    with open(CODE_FILE, "w") as f:
        f.write(f"{flow['verification_uri']}\n{flow['user_code']}\n")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        save_cache(app)
        print("✅ Authenticated! Token cached.")
        return True
    else:
        print(f"❌ Auth failed: {result.get('error_description', result.get('error', 'unknown'))}")
        return False


def _get_token(app):
    for acct in app.get_accounts():
        result = app.acquire_token_silent(SCOPES, account=acct)
        if result and "access_token" in result:
            save_cache(app)
            return result["access_token"]
    return None


def _ensure_token():
    global _token
    if _token:
        return True
    app = get_app()
    _token = _get_token(app)
    if not _token:
        print("❌ No valid token. Run 'auth' first.")
        return False
    return True


def _ews_post(body):
    headers = {"Authorization": f"Bearer {_token}", "Content-Type": "text/xml"}
    r = requests.post(EWS_ENDPOINT, headers=headers, data=body, timeout=30)
    return r.status_code, r.text


def _fetch_folder(folder_id, limit):
    if not _ensure_token():
        return None

    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
        '  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"\n'
        '  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">\n'
        '  <soap:Header>\n'
        '    <t:RequestServerVersion Version="Exchange2016"/>\n'
        '  </soap:Header>\n'
        '  <soap:Body>\n'
        '    <m:FindItem Traversal="Shallow">\n'
        '      <m:ItemShape>\n'
        '        <t:BaseShape>IdOnly</t:BaseShape>\n'
        '        <t:AdditionalProperties>\n'
        '          <t:FieldURI FieldURI="item:Subject"/>\n'
        '          <t:FieldURI FieldURI="item:DateTimeReceived"/>\n'
        '          <t:FieldURI FieldURI="message:IsRead"/>\n'
        '        </t:AdditionalProperties>\n'
        '      </m:ItemShape>\n'
        '      <m:ParentFolderIds>\n'
        f'        <t:DistinguishedFolderId Id="{folder_id}"/>\n'
        '      </m:ParentFolderIds>\n'
        '    </m:FindItem>\n'
        '  </soap:Body>\n'
        '</soap:Envelope>'
    )

    status, text = _ews_post(body)
    if status != 200:
        msg = re.search(r'<m:MessageText>(.*?)</m:MessageText>', text)
        code = re.search(r'<m:ResponseCode>(.*?)</m:ResponseCode>', text)
        print(f"❌ EWS error ({status}): {code.group(1) if code else '?'} - {msg.group(1) if msg else text[:200]}")
        return None

    items = []
    for block in re.findall(r'<t:Message>(.*?)</t:Message>', text, re.DOTALL)[:limit]:
        items.append({
            "id": (re.search(r'<t:ItemId Id="([^"]+)"', block) or [None, ""])[1],
            "subject": _unescape((re.search(r'<t:Subject>(.*?)</t:Subject>', block) or [None, "(no subject)"])[1]),
            "date": (re.search(r'<t:DateTimeReceived>(.*?)</t:DateTimeReceived>', block) or [None, ""])[1],
            "is_read": (re.search(r'<(?:t|message):IsRead>(true|false)</(?:t|message):IsRead>', block) or [None, "true"])[1] == "true",
        })
    return items


def _unescape(s):
    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')


def _display(items):
    print("-" * 70)
    for i, msg in enumerate(items, 1):
        flag = "🔵" if not msg["is_read"] else " "
        date = msg["date"][:16].replace("T", " ") if msg["date"] else ""
        print(f"{flag} {i:2d}. [{date}] {msg['subject']}")
    print("-" * 70)


def inbox(limit=20):
    items = _fetch_folder("inbox", limit)
    if items is None:
        return
    print(f"\n📬 QUT Inbox — last {len(items)} messages\n")
    _display(items)


def sent(limit=10):
    items = _fetch_folder("sentitems", limit)
    if items is None:
        return
    print(f"\n📤 QUT Sent Items — last {len(items)} messages\n")
    _display(items)


def unread(limit=20):
    items = _fetch_folder("inbox", limit)
    if items is None:
        return
    unread_items = [m for m in items if not m["is_read"]]
    print(f"\n🔵 Unread — {len(unread_items)} of last {len(items)}\n")
    _display(unread_items)


def search(query, limit=20):
    if not _ensure_token():
        return
    # Build a search filter SOAP body
    body = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
        '  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"\n'
        '  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">\n'
        '  <soap:Header>\n'
        '    <t:RequestServerVersion Version="Exchange2016"/>\n'
        '  </soap:Header>\n'
        '  <soap:Body>\n'
        '    <m:FindItem Traversal="Shallow">\n'
        '      <m:ItemShape>\n'
        '        <t:BaseShape>IdOnly</t:BaseShape>\n'
        '        <t:AdditionalProperties>\n'
        '          <t:FieldURI FieldURI="item:Subject"/>\n'
        '          <t:FieldURI FieldURI="item:DateTimeReceived"/>\n'
        '          <t:FieldURI FieldURI="message:IsRead"/>\n'
        '        </t:AdditionalProperties>\n'
        '      </m:ItemShape>\n'
        '      <m:ParentFolderIds>\n'
        '        <t:DistinguishedFolderId Id="inbox"/>\n'
        '      </m:ParentFolderIds>\n'
        '    </m:FindItem>\n'
        '  </soap:Body>\n'
        '</soap:Envelope>'
    )

    status, text = _ews_post(body)
    if status != 200:
        print(f"❌ EWS error ({status})")
        return

    # Filter results by query
    all_items = []
    for block in re.findall(r'<t:Message>(.*?)</t:Message>', text, re.DOTALL):
        item = {
            "id": (re.search(r'<t:ItemId Id="([^"]+)"', block) or [None, ""])[1],
            "subject": _unescape((re.search(r'<t:Subject>(.*?)</t:Subject>', block) or [None, "(no subject)"])[1]),
            "date": (re.search(r'<t:DateTimeReceived>(.*?)</t:DateTimeReceived>', block) or [None, ""])[1],
            "is_read": (re.search(r'<(?:t|message):IsRead>(true|false)</(?:t|message):IsRead>', block) or [None, "true"])[1] == "true",
        }
        if query.lower() in item["subject"].lower():
            all_items.append(item)

    results = all_items[-limit:] if len(all_items) > limit else all_items
    results.reverse()
    print(f"\n🔍 Search: '{query}' — {len(results)} results\n")
    _display(results)


def send_email(subject, body, to=None):
    """Send an email via EWS CreateItem."""
    if not _ensure_token():
        return False
    if not to:
        print("❌ Need --to email@address.com")
        return False

    # Escape XML
    def esc(s):
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    soap = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
        '  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"\n'
        '  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">\n'
        '  <soap:Header>\n'
        '    <t:RequestServerVersion Version="Exchange2016"/>\n'
        '  </soap:Header>\n'
        '  <soap:Body>\n'
        '    <m:CreateItem MessageDisposition="SendOnly">\n'
        '      <m:Items>\n'
        '        <t:Message>\n'
        f'          <t:Subject>{esc(subject)}</t:Subject>\n'
        f'          <t:Body BodyType="Text">{esc(body)}</t:Body>\n'
        '          <t:ToRecipients>\n'
        '            <t:Mailbox>\n'
        f'              <t:EmailAddress>{esc(to)}</t:EmailAddress>\n'
        '            </t:Mailbox>\n'
        '          </t:ToRecipients>\n'
        '        </t:Message>\n'
        '      </m:Items>\n'
        '    </m:CreateItem>\n'
        '  </soap:Body>\n'
        '</soap:Envelope>'
    )

    status, text = _ews_post(soap)
    if status == 200 and "NoError" in text:
        print(f"✅ Sent to {to}")
        return True
    else:
        msg = re.search(r'<m:MessageText>(.*?)</m:MessageText>', text)
        print(f"❌ Send failed ({status}): {msg.group(1) if msg else text[:200]}")
        return False


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "inbox"
    if cmd in ("inbox", "sent", "search", "unread"):
        n = None
        query = None
        if cmd == "search":
            query = sys.argv[2] if len(sys.argv) > 2 else ""
        else:
            n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None

    if cmd == "auth":
        auth()
    elif cmd == "inbox":
        inbox(n or 10)
    elif cmd == "sent":
        sent(n or 10)
    elif cmd == "search":
        search(query or "", n or 20)
    elif cmd == "unread":
        unread(n or 20)
    elif cmd == "send":
        subj = sys.argv[2] if len(sys.argv) > 2 else ""
        to_addr = sys.argv[3] if len(sys.argv) > 3 else ""
        send_email(subj, "Sent via Hermes", to=to_addr)
    else:
        print(f"Unknown: {cmd}")
        print("Usage: python qut_outlook.py [auth|inbox|sent|search|unread|send] [N/query]")
