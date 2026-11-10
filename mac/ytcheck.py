"""YouTube end-to-end check: token refresh -> channel -> unlisted test upload -> lock check -> delete.
Run by .github/workflows/ytcheck.yml. Prints one PASS/FAIL line per step."""
import os
import sys
import time
import requests

cid, secret = os.environ.get("GOOGLE_CLIENT_ID"), os.environ.get("GOOGLE_CLIENT_SECRET")
refresh = os.environ.get("YOUTUBE_REFRESH_TOKEN") or os.environ.get("GOOGLE_REFRESH_TOKEN")
path = sys.argv[1]


def fail(step, msg):
    print(f"FAIL {step}: {msg}")
    sys.exit(1)


print("token source:", "YOUTUBE_REFRESH_TOKEN" if os.environ.get("YOUTUBE_REFRESH_TOKEN") else "GOOGLE_REFRESH_TOKEN")
r = requests.post("https://oauth2.googleapis.com/token", data={
    "client_id": cid, "client_secret": secret, "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=30)
if r.status_code >= 300:
    fail("token", r.text[:300])
tok = r.json()["access_token"]
print("PASS token refresh")

info = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"access_token": tok}, timeout=30).json()
print("scopes:", info.get("scope"))
H = {"Authorization": f"Bearer {tok}"}

ch = requests.get("https://www.googleapis.com/youtube/v3/channels",
                  params={"part": "snippet,status", "mine": "true"}, headers=H, timeout=30)
if ch.status_code >= 300:
    fail("channel", ch.text[:300])
items = ch.json().get("items", [])
if not items:
    fail("channel", "token has no YouTube channel")
c = items[0]
print(f"PASS channel: {c['snippet']['title']} ({c['id']}) longUploads={c.get('status', {}).get('longUploadsStatus')}")

meta = {"snippet": {"title": "HQ upload test - deleting", "description": "Automated test", "categoryId": "25"},
        "status": {"privacyStatus": "unlisted", "selfDeclaredMadeForKids": False}}
init = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                     headers={**H, "Content-Type": "application/json", "X-Upload-Content-Type": "video/mp4",
                              "X-Upload-Content-Length": str(os.path.getsize(path))}, json=meta, timeout=60)
if init.status_code >= 300:
    fail("upload init", init.text[:400])
with open(path, "rb") as f:
    up = requests.put(init.headers["Location"], data=f, headers={"Content-Type": "video/mp4"}, timeout=600)
if up.status_code >= 300:
    fail("upload", up.text[:400])
vid = up.json()["id"]
print(f"PASS upload: video {vid}")

time.sleep(15)
v = requests.get("https://www.googleapis.com/youtube/v3/videos", params={"part": "status", "id": vid},
                 headers=H, timeout=30).json().get("items", [{}])[0].get("status", {})
print("status:", v)
locked = v.get("privacyStatus") != "unlisted"
print(("FAIL lock: YouTube forced the video to " + str(v.get("privacyStatus")) +
       " - the Google Cloud project needs a YouTube API audit before public posts work")
      if locked else "PASS not locked: uploads keep the privacy we ask for")

d = requests.delete("https://www.googleapis.com/youtube/v3/videos", params={"id": vid}, headers=H, timeout=30)
print("PASS deleted test video" if d.status_code < 300 else f"WARN delete {d.status_code}: {d.text[:200]}")
sys.exit(1 if locked else 0)
