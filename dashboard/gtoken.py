# One-time Google sign-in for Ten-Four HQ. Prints a refresh token. Contains no secrets.
import http.server, threading, urllib.parse as U, urllib.request, webbrowser, json, time
def ask(label, check):
    v = ""
    print(label, end="", flush=True)
    while True:
        v += input().strip().strip('"').strip("'").replace(" ", "")
        if check(v):
            return v
        if len(v) > 120:
            v = ""
            print("  That doesn't look right - copy it from your note and paste again: ", end="", flush=True)
cid = ask("Paste Client ID (ends in .apps.googleusercontent.com) + Return: ", lambda v: v.endswith(".apps.googleusercontent.com"))
sec = ask("Paste Client secret (starts with GOCSPX-) + Return: ", lambda v: v.startswith("GOCSPX-") and len(v) >= 30)
S = " ".join("https://www.googleapis.com/auth/" + s for s in
             ["gmail.send", "gmail.readonly", "youtube.upload", "youtube.readonly", "yt-analytics.readonly"])
R = "http://127.0.0.1:8765/"
box = {}
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(s):
        box["c"] = U.parse_qs(U.urlparse(s.path).query).get("code", [""])[0]
        s.send_response(200); s.end_headers(); s.wfile.write(b"Done - go back to Terminal")
    def log_message(s, *a): pass
threading.Thread(target=http.server.HTTPServer(("127.0.0.1", 8765), H).handle_request, daemon=True).start()
webbrowser.open("https://accounts.google.com/o/oauth2/v2/auth?" + U.urlencode(dict(
    client_id=cid, redirect_uri=R, response_type="code", scope=S, access_type="offline", prompt="select_account consent", login_hint="bobbybands888@gmail.com")))
print("Finish signing in in your browser...")
while "c" not in box:
    time.sleep(0.5)
d = U.urlencode(dict(code=box["c"], client_id=cid, client_secret=sec, redirect_uri=R,
                     grant_type="authorization_code")).encode()
r = json.load(urllib.request.urlopen("https://oauth2.googleapis.com/token", d))
print("\nREFRESH TOKEN (copy into your note):\n" + r.get("refresh_token", "FAILED " + str(r)))
