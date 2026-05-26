#!/usr/bin/env python3
"""
QUT Outlook access via Microsoft Graph API + device code flow.

Scrubbed Version — Replace placeholders before use.
"""

import msal
import json
import sys
import os
from pathlib import Path

# --- Config ---
CLIENT_ID = "d3590ed6-52b3-4102-aeff-aad2292ab01c"  # Microsoft Office (native app)
AUTHORITY = "https://login.microsoftonline.com/organizations"
SCOPES = ["Mail.Read"]
GRAPH_ENDPOINT = "https://graph.microsoft.com/v1.0"
TOKEN_CACHE = Path(__file__).parent / ".qut_outlook_cache.json"

# REPLACE THIS WITH YOUR STUDENT EMAIL
USER_EMAIL = "your.email@connect.qut.edu.au"


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
        return False

    print("=" * 55)
    print(f"  OPEN THIS URL: {flow['verification_uri']}")
    print(f"  ENTER THIS CODE: {flow['user_code']}")
    print("=" * 55)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        save_cache(app)
        print("Authenticated!")
        return True
    return False


def inbox(limit=20):
    app = get_app()
    accounts = app.get_accounts(username=USER_EMAIL)
    token = None
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            token = result["access_token"]
    
    if not token:
        print("No valid token. Run 'auth' first.")
        return

    import requests
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    r = requests.get(f"{GRAPH_ENDPOINT}/me/mailFolders/inbox/messages", headers=headers, params={"$top": limit})
    data = r.json()

    for msg in data.get("value", []):
        print(f"[{msg['receivedDateTime']}] {msg['subject']}")

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "auth":
        auth()
    else:
        inbox()
