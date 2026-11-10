"""Guided key setup for the Mac publisher. Asks for one thing at a time, opens the right page,
checks each value works, then writes .env (only readable by you, never uploaded anywhere).
Run:  ~/TenFourTapes/venv/bin/python mac/setup_env.py          (or --check to just test .env)"""
import getpass
import http.server
import os
import sys
import threading
import time
import urllib.parse
import webbrowser
from pathlib import Path

import requests

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / ".env"
SUPABASE_URL = "https://qerualjzbtenfpylblvc.supabase.co"
FBV = "https://graph.facebook.com/v21.0/"

def say(*lines):
    print()
    for l in lines:
        print(l)

def step(n, title, link=None):
    print("\n" + "=" * 64)
    print(f"STEP {n}: {title}")
    if link:
        print(f"Opening: {link}")
        webbrowser.open(link)

def ask_secret(prompt):
    while True:
        v = getpass.getpass(prompt + " (paste, then Enter — it stays hidden): ").strip().strip('"')
        if v:
            return v

def load():
    vals = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"')
    return vals

def save(vals):
    body = "# Ten-Four Tapes Mac publisher — made by mac/setup_env.py. Never commit or share this file.\n"
    body += "".join(f"{k}={v}\n" for k, v in vals.items() if v)
    ENV.write_text(body)
    os.chmod(ENV, 0o600)

# ---------------- checks ----------------
def check_supabase(url, key):
    r = requests.get(url.rstrip("/") + "/rest/v1/settings", params={"select": "key", "limit": 1},
                     headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=20)
    return r.status_code < 300, f"{r.status_code} {r.text[:120]}"

def check_groq(key):
    r = requests.get("https://api.groq.com/openai/v1/models", headers={"Authorization": f"Bearer {key}"}, timeout=20)
    return r.status_code < 300, f"{r.status_code} {r.text[:120]}"

def google_access(cid, secret, refresh):
    r = requests.post("https://oauth2.googleapis.com/token", data={"client_id": cid, "client_secret": secret,
                      "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=20)
    return r.json().get("access_token"), r.text[:160]

def check_youtube(cid, secret, refresh):
    tok, err = google_access(cid, secret, refresh)
    if not tok:
        return False, err
    r = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {tok}"}, timeout=20)
    items = r.json().get("items", []) if r.status_code < 300 else []
    if not items:
        return False, f"signed in, but no YouTube channel on that login ({r.status_code})"
    return True, items[0]["snippet"]["title"]

def check_facebook(page_id, token):
    r = requests.get(FBV + page_id, params={"fields": "name", "access_token": token}, timeout=20).json()
    return ("name" in r), r.get("name") or str(r.get("error", r))[:160]

# ---------------- google sign-in ----------------
def google_refresh_token(cid, secret):
    port, box = 8765, {}
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            box["code"] = (q.get("code") or [None])[0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Done - go back to Terminal.")
        def log_message(self, *a):
            pass
    redirect = f"http://127.0.0.1:{port}/"
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "access_type": "offline",
        "prompt": "consent", "scope": "https://www.googleapis.com/auth/youtube.upload "
                                      "https://www.googleapis.com/auth/youtube.readonly"})
    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    webbrowser.open(url)
    say("A Google sign-in page just opened.",
        "  Pick bobbybands888@gmail.com, then the Ten-Four Tapes channel, then Allow.",
        "  If it says 'Google hasn't verified this app': that's your own app — click Advanced, then Go to app.")
    while "code" not in box:
        time.sleep(0.5)
    r = requests.post("https://oauth2.googleapis.com/token", data={"code": box["code"], "client_id": cid,
                      "client_secret": secret, "redirect_uri": redirect, "grant_type": "authorization_code"}).json()
    return r.get("refresh_token")

# ---------------- facebook page token ----------------
def facebook_page_token():
    say("Option A: if you already have a never-expiring Page token for Ten-Four Tapes, paste it.",
        "Option B: just press Enter and I'll walk you through getting one.")
    direct = getpass.getpass("Page token (or Enter for Option B): ").strip()
    if direct:
        me = requests.get(FBV + "me", params={"fields": "id,name", "access_token": direct}, timeout=20).json()
        if "id" in me:
            return me["id"], direct
        say(f"That token didn't work: {str(me.get('error', me))[:160]}", "Let's do Option B.")
    step("5a", "Your Meta app's ID and secret", "https://developers.facebook.com/apps/")
    say("Click your app → App settings → Basic. Copy the App ID and click Show on App secret.")
    app_id = input("App ID: ").strip()
    app_secret = ask_secret("App secret")
    step("5b", "A user token with Page permissions", "https://developers.facebook.com/tools/explorer/")
    say("In Graph API Explorer:",
        "  1) Meta App (top right): pick your app.",
        "  2) User or Page: 'Get User Access Token'.",
        "  3) Add permissions: pages_manage_posts, pages_read_engagement, pages_show_list, read_insights.",
        "  4) Click Generate Access Token, allow it for the Ten-Four Tapes page, then copy the token box.")
    user_tok = ask_secret("User token")
    long = requests.get(FBV + "oauth/access_token", params={"grant_type": "fb_exchange_token", "client_id": app_id,
                        "client_secret": app_secret, "fb_exchange_token": user_tok}, timeout=20).json()
    if "access_token" not in long:
        sys.exit(f"Facebook said: {str(long.get('error', long))[:200]}")
    pages = requests.get(FBV + "me/accounts", params={"access_token": long["access_token"], "limit": 100},
                         timeout=20).json().get("data", [])
    page = next((p for p in pages if "ten-four" in p["name"].lower() or "ten four" in p["name"].lower()), None)
    if not page:
        sys.exit("Couldn't find the Ten-Four Tapes page on that login. Pages found: " + ", ".join(p["name"] for p in pages))
    return page["id"], page["access_token"]   # page tokens from a long-lived user token don't expire

# ---------------- main ----------------
def safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"

def check_all(v):
    ok = True
    for name, (good, info) in {
        "Supabase": safe(check_supabase, v.get("SUPABASE_URL") or SUPABASE_URL, v.get("SUPABASE_SERVICE_KEY", "")),
        "Groq": safe(check_groq, v.get("GROQ_API_KEY", "")),
        "YouTube": safe(check_youtube, v.get("GOOGLE_CLIENT_ID", ""), v.get("GOOGLE_CLIENT_SECRET", ""),
                        v.get("YOUTUBE_REFRESH_TOKEN", "")),
        "Facebook": safe(check_facebook, v.get("FB_PAGE_ID", ""), v.get("FB_PAGE_TOKEN", "")),
    }.items():
        print(f"  {'OK ' if good else 'BAD'}  {name}: {info if good else 'not working — ' + info}")
        ok &= good
    return ok

def main():
    v = load()
    if "--check" in sys.argv:
        sys.exit(0 if check_all(v) else 1)
    say("Ten-Four Tapes — Mac publisher keys. 5 short steps. Nothing here costs money.")

    v["SUPABASE_URL"] = SUPABASE_URL
    while True:
        step(1, "Supabase secret key", "https://supabase.com/dashboard/project/qerualjzbtenfpylblvc/settings/api-keys")
        say("Click the 'Legacy API keys' tab, then Reveal + Copy on 'service_role'. Same key GitHub uses.")
        v["SUPABASE_SERVICE_KEY"] = ask_secret("service_role key")
        good, info = safe(check_supabase, SUPABASE_URL, v["SUPABASE_SERVICE_KEY"])
        if good:
            print("  OK — Supabase connected.")
            break
        print(f"  That didn't work ({info}). Try again.")

    while True:
        step(2, "Groq key (free) — used for transcripts and picking the best moments", "https://console.groq.com/keys")
        say("Click 'Create API Key', name it 'mac', copy it.")
        v["GROQ_API_KEY"] = ask_secret("Groq key")
        good, info = safe(check_groq, v["GROQ_API_KEY"])
        if good:
            print("  OK — Groq connected.")
            break
        print(f"  That didn't work ({info}). Try again.")

    step(3, "Google OAuth client (bobbybands888)", "https://console.cloud.google.com/apis/credentials")
    say("Under 'OAuth 2.0 Client IDs' click your Desktop client.",
        "Copy the Client ID. For the secret: copy it, or click 'Add secret' and copy the new one.")
    v["GOOGLE_CLIENT_ID"] = input("Client ID: ").strip()
    v["GOOGLE_CLIENT_SECRET"] = ask_secret("Client secret")

    while True:
        step(4, "Connect the Ten-Four Tapes YouTube channel")
        rt = google_refresh_token(v["GOOGLE_CLIENT_ID"], v["GOOGLE_CLIENT_SECRET"])
        good, info = safe(check_youtube, v["GOOGLE_CLIENT_ID"], v["GOOGLE_CLIENT_SECRET"], rt or "")
        if good:
            v["YOUTUBE_REFRESH_TOKEN"] = rt
            print(f"  OK — connected to YouTube channel: {info}")
            if "ten" not in info.lower():
                print("  Heads up: that isn't Ten-Four Tapes. Press Enter to redo this step, or type 'keep'.")
                if input().strip().lower() != "keep":
                    continue
            break
        print(f"  That didn't work ({info}). Let's retry.")

    step(5, "Facebook Page (Ten-Four Tapes)")
    v["FB_PAGE_ID"], v["FB_PAGE_TOKEN"] = facebook_page_token()
    good, info = safe(check_facebook, v["FB_PAGE_ID"], v["FB_PAGE_TOKEN"])
    print(f"  {'OK — connected to page: ' + info if good else 'Problem: ' + info}")

    save(v)
    say("Saved. Final check:")
    check_all(v)

if __name__ == "__main__":
    main()
