"""One-time: sign in as bobbybands888@gmail.com and print the refresh token the agents use.
Run:  python3 mac/get_google_token.py CLIENT_ID CLIENT_SECRET
A browser opens; pick bobbybands888 and the Ten-Four Tapes channel, click Allow (you'll see an
'unverified app' screen — that's your own app; click Advanced > Go to app)."""
import http.server
import sys
import threading
import time
import urllib.parse
import webbrowser
import requests

SCOPES = " ".join([
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
])
PORT = 8765
REDIRECT = f"http://127.0.0.1:{PORT}/"
code_box = {}

class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code_box["code"] = (q.get("code") or [None])[0]
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Done - you can close this tab and go back to Terminal.")
    def log_message(self, *a):
        pass

def main():
    cid, secret = sys.argv[1], sys.argv[2]
    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": REDIRECT, "response_type": "code", "scope": SCOPES,
        "access_type": "offline", "prompt": "consent"})
    srv = http.server.HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.handle_request, daemon=True).start()
    webbrowser.open(url)
    print("Browser opened. Finish sign-in there...")
    while "code" not in code_box:
        time.sleep(0.5)
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "code": code_box["code"], "client_id": cid, "client_secret": secret,
        "redirect_uri": REDIRECT, "grant_type": "authorization_code"}).json()
    if "refresh_token" not in r:
        sys.exit(f"Failed: {r}")
    print("\nGOOGLE_REFRESH_TOKEN=" + r["refresh_token"])

if __name__ == "__main__":
    main()
