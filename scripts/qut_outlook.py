     1|#!/usr/bin/env python3
     2|"""
     3|QUT Outlook access via Exchange Web Services (EWS) + device code OAuth2.
     4|
     5|One-time auth, then persistent token cache.
     6|Usage:
     7|  python qut_outlook.py auth            # One-time auth
     8|  python qut_outlook.py inbox [N]       # Recent inbox
     9|  python qut_outlook.py sent [N]        # Recent sent
    10|  python qut_outlook.py search "term"   # Search inbox
    11|  python qut_outlook.py unread [N]      # Unread only
    12|"""
    13|
    14|import msal
    15|import json
    16|import sys
    17|import re
    18|import requests
    19|from pathlib import Path
    20|
    21|sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
    22|
    23|CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"
    24|AUTHORITY = "https://login.microsoftonline.com/organizations"
    25|SCOPES = ["https://outlook.office365.com/.default"]
    26|EWS_ENDPOINT = "https://outlook.office365.com/EWS/Exchange.asmx"
    27|TOKEN_CACHE = Path(__file__).parent / ".qut_outlook_cache.json"
    28|CODE_FILE = Path(__file__).parent / ".qut_device_code.txt"
    29|USER_EMAIL = "your.email@connect.qut.edu.au"  # Replace with your student email
    30|
    31|_token = None
    32|
    33|
    34|def get_app():
    35|    cache = msal.SerializableTokenCache()
    36|    if TOKEN_CACHE.exists():
    37|        with open(TOKEN_CACHE) as f:
    38|            cache.deserialize(f.read())
    39|    return msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    40|
    41|
    42|def save_cache(app):
    43|    if app.token_cache.has_state_changed:
    44|        with open(TOKEN_CACHE, "w") as f:
    45|            f.write(app.token_cache.serialize())
    46|
    47|
    48|def auth():
    49|    app = get_app()
    50|    flow = app.initiate_device_flow(scopes=SCOPES)
    51|    if "user_code" not in flow:
    52|        print("ERROR: Device code flow not available.")
    53|        print(json.dumps(flow, indent=2))
    54|        return False
    55|
    56|    print("=" * 55)
    57|    print("  OPEN THIS URL ON YOUR PHONE OR LAPTOP:")
    58|    print(f"  {flow['verification_uri']}")
    59|    print()
    60|    print(f"  ENTER THIS CODE:  {flow['user_code']}")
    61|    print("=" * 55)
    62|    print()
    63|    print(f"Sign in with: {USER_EMAIL}")
    64|    print("Approve the MFA prompt on your phone.")
    65|    print()
    66|    sys.stdout.flush()
    67|
    68|    with open(CODE_FILE, "w") as f:
    69|        f.write(f"{flow['verification_uri']}\n{flow['user_code']}\n")
    70|
    71|    result = app.acquire_token_by_device_flow(flow)
    72|    if "access_token" in result:
    73|        save_cache(app)
    74|        print("✅ Authenticated! Token cached.")
    75|        return True
    76|    else:
    77|        print(f"❌ Auth failed: {result.get('error_description', result.get('error', 'unknown'))}")
    78|        return False
    79|
    80|
    81|def _get_token(app):
    82|    for acct in app.get_accounts():
    83|        result = app.acquire_token_silent(SCOPES, account=acct)
    84|        if result and "access_token" in result:
    85|            save_cache(app)
    86|            return result["access_token"]
    87|    return None
    88|
    89|
    90|def _ensure_token():
    91|    global _token
    92|    if _token:
    93|        return True
    94|    app = get_app()
    95|    _token = _get_token(app)
    96|    if not _token:
    97|        print("❌ No valid token. Run 'auth' first.")
    98|        return False
    99|    return True
   100|
   101|
   102|def _ews_post(body):
   103|    headers = {"Authorization": f"Bearer {_token}", "Content-Type": "text/xml"}
   104|    r = requests.post(EWS_ENDPOINT, headers=headers, data=body, timeout=30)
   105|    return r.status_code, r.text
   106|
   107|
   108|def _fetch_folder(folder_id, limit):
   109|    if not _ensure_token():
   110|        return None
   111|
   112|    body = (
   113|        '<?xml version="1.0" encoding="utf-8"?>\n'
   114|        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
   115|        '  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"\n'
   116|        '  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">\n'
   117|        '  <soap:Header>\n'
   118|        '    <t:RequestServerVersion Version="Exchange2016"/>\n'
   119|        '  </soap:Header>\n'
   120|        '  <soap:Body>\n'
   121|        '    <m:FindItem Traversal="Shallow">\n'
   122|        '      <m:ItemShape>\n'
   123|        '        <t:BaseShape>IdOnly</t:BaseShape>\n'
   124|        '        <t:AdditionalProperties>\n'
   125|        '          <t:FieldURI FieldURI="item:Subject"/>\n'
   126|        '          <t:FieldURI FieldURI="item:DateTimeReceived"/>\n'
   127|        '          <t:FieldURI FieldURI="message:IsRead"/>\n'
   128|        '        </t:AdditionalProperties>\n'
   129|        '      </m:ItemShape>\n'
   130|        '      <m:ParentFolderIds>\n'
   131|        f'        <t:DistinguishedFolderId Id="{folder_id}"/>\n'
   132|        '      </m:ParentFolderIds>\n'
   133|        '    </m:FindItem>\n'
   134|        '  </soap:Body>\n'
   135|        '</soap:Envelope>'
   136|    )
   137|
   138|    status, text = _ews_post(body)
   139|    if status != 200:
   140|        msg = re.search(r'<m:MessageText>(.*?)</m:MessageText>', text)
   141|        code = re.search(r'<m:ResponseCode>(.*?)</m:ResponseCode>', text)
   142|        print(f"❌ EWS error ({status}): {code.group(1) if code else '?'} - {msg.group(1) if msg else text[:200]}")
   143|        return None
   144|
   145|    items = []
   146|    for block in re.findall(r'<t:Message>(.*?)</t:Message>', text, re.DOTALL)[:limit]:
   147|        items.append({
   148|            "id": (re.search(r'<t:ItemId Id="([^"]+)"', block) or [None, ""])[1],
   149|            "subject": _unescape((re.search(r'<t:Subject>(.*?)</t:Subject>', block) or [None, "(no subject)"])[1]),
   150|            "date": (re.search(r'<t:DateTimeReceived>(.*?)</t:DateTimeReceived>', block) or [None, ""])[1],
   151|            "is_read": (re.search(r'<(?:t|message):IsRead>(true|false)</(?:t|message):IsRead>', block) or [None, "true"])[1] == "true",
   152|        })
   153|    return items
   154|
   155|
   156|def _unescape(s):
   157|    return s.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
   158|
   159|
   160|def _display(items):
   161|    print("-" * 70)
   162|    for i, msg in enumerate(items, 1):
   163|        flag = "🔵" if not msg["is_read"] else " "
   164|        date = msg["date"][:16].replace("T", " ") if msg["date"] else ""
   165|        print(f"{flag} {i:2d}. [{date}] {msg['subject']}")
   166|    print("-" * 70)
   167|
   168|
   169|def inbox(limit=20):
   170|    items = _fetch_folder("inbox", limit)
   171|    if items is None:
   172|        return
   173|    print(f"\n📬 QUT Inbox — last {len(items)} messages\n")
   174|    _display(items)
   175|
   176|
   177|def sent(limit=10):
   178|    items = _fetch_folder("sentitems", limit)
   179|    if items is None:
   180|        return
   181|    print(f"\n📤 QUT Sent Items — last {len(items)} messages\n")
   182|    _display(items)
   183|
   184|
   185|def unread(limit=20):
   186|    items = _fetch_folder("inbox", limit)
   187|    if items is None:
   188|        return
   189|    unread_items = [m for m in items if not m["is_read"]]
   190|    print(f"\n🔵 Unread — {len(unread_items)} of last {len(items)}\n")
   191|    _display(unread_items)
   192|
   193|
   194|def search(query, limit=20):
   195|    if not _ensure_token():
   196|        return
   197|    # Build a search filter SOAP body
   198|    body = (
   199|        '<?xml version="1.0" encoding="utf-8"?>\n'
   200|        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
   201|        '  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"\n'
   202|        '  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">\n'
   203|        '  <soap:Header>\n'
   204|        '    <t:RequestServerVersion Version="Exchange2016"/>\n'
   205|        '  </soap:Header>\n'
   206|        '  <soap:Body>\n'
   207|        '    <m:FindItem Traversal="Shallow">\n'
   208|        '      <m:ItemShape>\n'
   209|        '        <t:BaseShape>IdOnly</t:BaseShape>\n'
   210|        '        <t:AdditionalProperties>\n'
   211|        '          <t:FieldURI FieldURI="item:Subject"/>\n'
   212|        '          <t:FieldURI FieldURI="item:DateTimeReceived"/>\n'
   213|        '          <t:FieldURI FieldURI="message:IsRead"/>\n'
   214|        '        </t:AdditionalProperties>\n'
   215|        '      </m:ItemShape>\n'
   216|        '      <m:ParentFolderIds>\n'
   217|        '        <t:DistinguishedFolderId Id="inbox"/>\n'
   218|        '      </m:ParentFolderIds>\n'
   219|        '    </m:FindItem>\n'
   220|        '  </soap:Body>\n'
   221|        '</soap:Envelope>'
   222|    )
   223|
   224|    status, text = _ews_post(body)
   225|    if status != 200:
   226|        print(f"❌ EWS error ({status})")
   227|        return
   228|
   229|    # Filter results by query
   230|    all_items = []
   231|    for block in re.findall(r'<t:Message>(.*?)</t:Message>', text, re.DOTALL):
   232|        item = {
   233|            "id": (re.search(r'<t:ItemId Id="([^"]+)"', block) or [None, ""])[1],
   234|            "subject": _unescape((re.search(r'<t:Subject>(.*?)</t:Subject>', block) or [None, "(no subject)"])[1]),
   235|            "date": (re.search(r'<t:DateTimeReceived>(.*?)</t:DateTimeReceived>', block) or [None, ""])[1],
   236|            "is_read": (re.search(r'<(?:t|message):IsRead>(true|false)</(?:t|message):IsRead>', block) or [None, "true"])[1] == "true",
   237|        }
   238|        if query.lower() in item["subject"].lower():
   239|            all_items.append(item)
   240|
   241|    results = all_items[-limit:] if len(all_items) > limit else all_items
   242|    results.reverse()
   243|    print(f"\n🔍 Search: '{query}' — {len(results)} results\n")
   244|    _display(results)
   245|
   246|
   247|def send_email(subject, body, to=None):
   248|    """Send an email via EWS CreateItem."""
   249|    if not _ensure_token():
   250|        return False
   251|    if not to:
   252|        print("❌ Need --to email@address.com")
   253|        return False
   254|
   255|    # Escape XML
   256|    def esc(s):
   257|        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
   258|
   259|    soap = (
   260|        '<?xml version="1.0" encoding="utf-8"?>\n'
   261|        '<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/"\n'
   262|        '  xmlns:t="http://schemas.microsoft.com/exchange/services/2006/types"\n'
   263|        '  xmlns:m="http://schemas.microsoft.com/exchange/services/2006/messages">\n'
   264|        '  <soap:Header>\n'
   265|        '    <t:RequestServerVersion Version="Exchange2016"/>\n'
   266|        '  </soap:Header>\n'
   267|        '  <soap:Body>\n'
   268|        '    <m:CreateItem MessageDisposition="SendOnly">\n'
   269|        '      <m:Items>\n'
   270|        '        <t:Message>\n'
   271|        f'          <t:Subject>{esc(subject)}</t:Subject>\n'
   272|        f'          <t:Body BodyType="Text">{esc(body)}</t:Body>\n'
   273|        '          <t:ToRecipients>\n'
   274|        '            <t:Mailbox>\n'
   275|        f'              <t:EmailAddress>{esc(to)}</t:EmailAddress>\n'
   276|        '            </t:Mailbox>\n'
   277|        '          </t:ToRecipients>\n'
   278|        '        </t:Message>\n'
   279|        '      </m:Items>\n'
   280|        '    </m:CreateItem>\n'
   281|        '  </soap:Body>\n'
   282|        '</soap:Envelope>'
   283|    )
   284|
   285|    status, text = _ews_post(soap)
   286|    if status == 200 and "NoError" in text:
   287|        print(f"✅ Sent to {to}")
   288|        return True
   289|    else:
   290|        msg = re.search(r'<m:MessageText>(.*?)</m:MessageText>', text)
   291|        print(f"❌ Send failed ({status}): {msg.group(1) if msg else text[:200]}")
   292|        return False
   293|
   294|
   295|if __name__ == "__main__":
   296|    cmd = sys.argv[1] if len(sys.argv) > 1 else "inbox"
   297|    if cmd in ("inbox", "sent", "search", "unread"):
   298|        n = None
   299|        query = None
   300|        if cmd == "search":
   301|            query = sys.argv[2] if len(sys.argv) > 2 else ""
   302|        else:
   303|            n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
   304|
   305|    if cmd == "auth":
   306|        auth()
   307|    elif cmd == "inbox":
   308|        inbox(n or 10)
   309|    elif cmd == "sent":
   310|        sent(n or 10)
   311|    elif cmd == "search":
   312|        search(query or "", n or 20)
   313|    elif cmd == "unread":
   314|        unread(n or 20)
   315|    elif cmd == "send":
   316|        subj = sys.argv[2] if len(sys.argv) > 2 else ""
   317|        to_addr = sys.argv[3] if len(sys.argv) > 3 else ""
   318|        send_email(subj, "Sent via Hermes", to=to_addr)
   319|    else:
   320|        print(f"Unknown: {cmd}")
   321|        print("Usage: python qut_outlook.py [auth|inbox|sent|search|unread|send] [N/query]")
   322|