"""MAC RUNNER — the hands on Bobby's Mac (runs every 30 min via launchd).
  1. downloads fulfilled records-request footage
  2. renders approved plans with the existing Ten-Four Tapes build tools (RENDER_CMD)
  3. PUBLISHER: uploads finished videos to YouTube and Facebook Reels — only items that passed
     Compliance and (during the approval window) that Bobby approved. Never replies to comments.
"""
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import requests  # noqa: E402
from agents.lib import config  # noqa: E402
from agents.lib.google import access_token  # noqa: E402
from agents.lib.runner import run_agent  # noqa: E402

HOME = Path(os.environ.get("TENFOUR_HOME", Path.home() / "TenFourTapes"))
FOOTAGE, QUEUE, OUT = HOME / "footage", HOME / "queue", HOME / "rendered"
RENDER_CMD = os.environ.get("RENDER_CMD")  # e.g. python3 ~/ten-four-tapes-tools/build.py --plan {plan} --footage {footage} --out {out}
FB = "https://graph.facebook.com/v21.0/"

def _now():
    return datetime.now(timezone.utc)

# ---------------- 1. footage ----------------
def download_footage(db):
    got = 0
    reqs = db.select("records_requests", {"status": "eq.fulfilled", "download_links": "not.is.null"})
    for r in reqs:
        dest = FOOTAGE / str(r["lead_id"])
        if dest.exists() and any(dest.iterdir()):
            continue
        dest.mkdir(parents=True, exist_ok=True)
        for i, url in enumerate(r["download_links"]):
            try:
                with requests.get(url, stream=True, timeout=60, allow_redirects=True) as resp:
                    ctype = resp.headers.get("content-type", "")
                    if resp.status_code >= 300 or "text/html" in ctype:
                        continue  # portal page, needs a click — flagged below
                    name = re.sub(r"[^\w.-]", "_", url.split("?")[0].rsplit("/", 1)[-1]) or f"file{i}"
                    with open(dest / name, "wb") as f:
                        for chunk in resp.iter_content(1 << 20):
                            f.write(chunk)
                    got += 1
            except Exception:
                continue
        if not any(dest.iterdir()):
            db.alert("mac_runner", f"Couldn't auto-download footage for '{r['subject'][:60]}' — portal link needs a "
                     f"manual download into {dest}", "warn")
    return got

# ---------------- 2. render ----------------
def render(db):
    items = db.select("content", {"status": "eq.scripted", "compliance_status": "eq.pass",
                                  "approval_status": "in.(approved,not_required)", "limit": 6})
    done = 0
    for it in items:
        src = FOOTAGE / str(it["lead_id"])
        if not src.exists() or not any(src.iterdir()):
            continue
        QUEUE.mkdir(parents=True, exist_ok=True)
        OUT.mkdir(parents=True, exist_ok=True)
        plan_path = QUEUE / f"{it['id']}.json"
        plan_path.write_text(json.dumps(it, indent=2, default=str))
        if not RENDER_CMD:
            continue
        out = OUT / f"{it['kind']}_{it['id']}.mp4"
        cmd = RENDER_CMD.format(plan=shlex.quote(str(plan_path)), footage=shlex.quote(str(src)), out=shlex.quote(str(out)))
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3600)
        if res.returncode == 0 and out.exists():
            db.update("content", {"id": f"eq.{it['id']}"}, {"status": "rendered", "media_path": str(out)})
            done += 1
        else:
            db.alert("mac_runner", f"Render failed for {it['case_name']} {it['kind']}: {res.stderr[-300:]}", "warn")
    if items and not RENDER_CMD:
        db.alert("mac_runner", f"{len(items)} plan(s) queued in {QUEUE} — RENDER_CMD not set yet", "info")
    return done

# ---------------- 3. publish ----------------
def youtube_upload(path, title, description, tags, short=False):
    meta = {"snippet": {"title": title[:100], "description": description[:4900], "tags": (tags or [])[:15],
                        "categoryId": "25"},  # News & Politics
            "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False}}
    if short and "#shorts" not in meta["snippet"]["description"].lower():
        meta["snippet"]["description"] += "\n#shorts"
    h = {"Authorization": f"Bearer {access_token('youtube')}", "Content-Type": "application/json",
         "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(os.path.getsize(path))}
    r = requests.post("https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
                      headers=h, json=meta, timeout=60)
    if r.status_code >= 300:
        raise RuntimeError(f"YouTube init {r.status_code}: {r.text[:300]}")
    with open(path, "rb") as f:
        up = requests.put(r.headers["Location"], data=f, headers={"Content-Type": "video/mp4"}, timeout=3600)
    if up.status_code >= 300:
        raise RuntimeError(f"YouTube upload {up.status_code}: {up.text[:300]}")
    v = up.json()
    locked = v.get("status", {}).get("privacyStatus") != "public"
    return v["id"], locked

def facebook_reel(path, caption):
    tok = config.FB_PAGE_TOKEN
    start = requests.post(FB + f"{config.FB_PAGE_ID}/video_reels",
                          params={"upload_phase": "start", "access_token": tok}, timeout=60).json()
    vid = start.get("video_id")
    if not vid:
        raise RuntimeError(f"FB start failed: {start}")
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        up = requests.post(start["upload_url"], data=f, timeout=1800,
                           headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    if up.status_code >= 300:
        raise RuntimeError(f"FB upload {up.status_code}: {up.text[:300]}")
    fin = requests.post(FB + f"{config.FB_PAGE_ID}/video_reels", params={
        "upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED",
        "description": caption[:2000], "access_token": tok}, timeout=60).json()
    if not fin.get("success"):
        raise RuntimeError(f"FB finish failed: {fin}")
    return vid

def posted_since(db, kind, hours):
    since = (_now() - timedelta(hours=hours)).isoformat()
    return len(db.select("content", {"kind": f"eq.{kind}", "posted_at": f"gte.{since}", "select": "id"}))

def publish(db):
    if db.setting("posting_paused", False):
        return "posting paused"
    room = {
        "episode": int(db.setting("episodes_per_week", 2)) - posted_since(db, "episode", 24 * 7),
        "short": 1 - posted_since(db, "short", 24),
        "reel": int(db.setting("reels_per_day", 3)) - posted_since(db, "reel", 24),
    }
    ready = db.select("content", {"status": "eq.rendered", "compliance_status": "eq.pass",
                                  "approval_status": "in.(approved,not_required)", "order": "kind.asc,part.asc,created_at.asc"})
    out = []
    for it in ready:
        k = it["kind"]
        if room.get(k, 0) <= 0 or not it.get("media_path") or not os.path.exists(it["media_path"]):
            continue
        if config.DRY_RUN:
            out.append(f"[dry] {k} {it['case_name']}")
            room[k] -= 1
            continue
        try:
            upd = {"status": "posted", "posted_at": _now()}
            if k in ("episode", "short"):
                desc = it.get("description") or ""
                if k == "short" and it.get("parent_id"):
                    ep = db.select("content", {"id": f"eq.{it['parent_id']}", "select": "youtube_id"})
                    if ep and ep[0].get("youtube_id"):
                        desc = f"Full episode: https://youtu.be/{ep[0]['youtube_id']}\n" + desc
                vid, locked = youtube_upload(it["media_path"], it["title"], desc, it.get("tags"), short=(k == "short"))
                upd["youtube_id"] = vid
                if locked:
                    upd["publish_note"] = "Uploaded but locked private until Google audits the API app — publish in YouTube Studio"
                    db.alert("publisher", f"'{it['title']}' uploaded as PRIVATE (API audit pending) — set Public in Studio", "warn")
            else:
                cap = it.get("description") or it["case_name"]
                if it.get("parent_id"):
                    ep = db.select("content", {"id": f"eq.{it['parent_id']}", "select": "youtube_id"})
                    if ep and ep[0].get("youtube_id"):
                        cap = cap.replace("Full episode on YouTube: Ten-Four Tapes",
                                          f"Full episode: https://youtu.be/{ep[0]['youtube_id']}")
                upd["facebook_id"] = facebook_reel(it["media_path"], cap)
            db.update("content", {"id": f"eq.{it['id']}"}, upd)
            room[k] -= 1
            out.append(f"{k}: {it['title']}")
        except Exception as e:
            db.update("content", {"id": f"eq.{it['id']}"}, {"publish_note": str(e)[:500]})
            db.alert("publisher", f"Post failed for {it['title']}: {e}", "warn")
    return f"posted {len(out)}" + (f": {out}" if out else "")

def main(db):
    d = download_footage(db)
    r = render(db)
    p = publish(db)
    return f"downloaded {d} files, rendered {r}, {p}"

if __name__ == "__main__":
    ok = run_agent("mac_runner", main)
    sys.exit(0 if ok else 1)
