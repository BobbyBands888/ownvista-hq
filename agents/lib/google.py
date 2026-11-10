"""Gmail + YouTube helpers. Public YouTube data uses the API key; anything on Bobby's
accounts uses the bobbybands888 OAuth refresh token."""
import base64
import re
import time
from email.mime.text import MIMEText
import requests
from . import config

_tokens = {}

def access_token(kind="gmail"):
    """kind: gmail (bobbybands888) or youtube (Ten-Four Tapes channel)."""
    refresh = config.YOUTUBE_REFRESH_TOKEN if kind == "youtube" else config.GOOGLE_REFRESH_TOKEN
    _token = _tokens.setdefault(kind, {"value": None, "exp": 0})
    if _token["value"] and time.time() < _token["exp"] - 60:
        return _token["value"]
    if not (config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET and refresh):
        raise RuntimeError("Google OAuth not configured (GOOGLE_CLIENT_ID/SECRET/REFRESH_TOKEN)")
    r = requests.post("https://oauth2.googleapis.com/token", data={
        "client_id": config.GOOGLE_CLIENT_ID,
        "client_secret": config.GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    }, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Google token refresh failed: {r.text[:200]}")
    j = r.json()
    _token.update(value=j["access_token"], exp=time.time() + j.get("expires_in", 3600))
    return _token["value"]

def _auth():
    return {"Authorization": f"Bearer {access_token()}"}

# ---------------- Gmail ----------------
GM = "https://gmail.googleapis.com/gmail/v1/users/me/"

def send_email(to, subject, body, thread_id=None, in_reply_to=None):
    if config.DRY_RUN:
        print(f"[DRY_RUN] email to {to}: {subject}")
        return {"id": "dry", "threadId": thread_id or "dry"}
    msg = MIMEText(body, "plain", "utf-8")
    msg["To"] = to
    msg["From"] = config.SENDER_EMAIL
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    r = requests.post(GM + "messages/send", headers=_auth(), json=payload, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Gmail send failed: {r.text[:200]}")
    return r.json()

def get_thread(thread_id):
    import time
    for attempt in range(4):   # Gmail's per-minute quota: back off and retry
        r = requests.get(GM + f"threads/{thread_id}", headers=_auth(), params={"format": "full"}, timeout=30)
        if r.status_code in (403, 429) and "uota" in r.text or r.status_code == 429:
            time.sleep(20 * (attempt + 1))
            continue
        break
    if r.status_code >= 300:
        raise RuntimeError(f"Gmail thread failed: {r.text[:200]}")
    return r.json()

def message_text(msg):
    """Best-effort plain text from a Gmail message payload."""
    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", "ignore")
        for p in part.get("parts", []) or []:
            t = walk(p)
            if t:
                return t
        if mime == "text/html" and data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", "ignore")
            return re.sub(r"<[^>]+>", " ", html)
        return ""
    return walk(msg.get("payload", {}))

def header(msg, name):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return None

def search(query, max_results=50):
    r = requests.get(GM + "messages", headers=_auth(), params={"q": query, "maxResults": max_results}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Gmail search failed: {r.text[:200]}")
    return r.json().get("messages", [])

# ---------------- YouTube (public data, API key) ----------------
YT = "https://www.googleapis.com/youtube/v3/"

def yt_get(path, params, oauth=False):
    p = dict(params)
    headers = {}
    if oauth:
        headers = {"Authorization": f"Bearer {access_token('youtube')}"}
    else:
        if not config.YOUTUBE_API_KEY:
            raise RuntimeError("YOUTUBE_API_KEY not set")
        p["key"] = config.YOUTUBE_API_KEY
    r = requests.get(YT + path, params=p, headers=headers, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"YouTube {path} {r.status_code}: {r.text[:200]}")
    return r.json()

def iso_duration_to_s(d):
    m = re.match(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return 0
    days, h, mi, s = (int(x or 0) for x in m.groups())
    return days * 86400 + h * 3600 + mi * 60 + s
