"""Say what the FB_PAGE_TOKEN secret actually is and whether it can start a Reel upload. Never prints the token.
Run from GitHub: Actions -> "Facebook token check" -> Run workflow."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402

from agents.lib import config  # noqa: E402
from mac.runner import FB, fb_token_info  # noqa: E402

raw = config.FB_PAGE_TOKEN or ""
page = (config.FB_PAGE_ID or "").strip()
tok = raw.strip()
print(f"FB_PAGE_ID: {page!r}  (expected '1352255687974967')")
print(f"Token length {len(tok)}" + ("; had spaces/newlines around it" if raw != tok else ""))
info = fb_token_info(tok, page)
print("Token:", info["detail"])

if info["kind"] == "user":
    r = requests.get(FB + page, params={"fields": "access_token", "access_token": tok}, timeout=30).json()
    print("Can it get the Page's own token from it?", "yes" if r.get("access_token") else f"no: {r}")
    if r.get("access_token"):
        tok = r["access_token"]

dbg = requests.get(FB + "debug_token", params={"input_token": tok, "access_token": tok}, timeout=30).json().get("data", {})
if dbg:
    print("Type:", dbg.get("type"), "| app:", dbg.get("application"), "| expires:", dbg.get("expires_at") or "never")
    print("Permissions:", ", ".join(dbg.get("scopes") or []))

start = requests.post(FB + f"{page}/video_reels", params={"upload_phase": "start", "access_token": tok}, timeout=60).json()
if start.get("video_id"):
    print("Reel upload start: OK (test upload not finished, so nothing posts)")
else:
    print("Reel upload start: FAILED", start)
    sys.exit(1)
