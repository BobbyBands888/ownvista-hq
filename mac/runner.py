"""MAC RUNNER — the hands on Bobby's Mac (runs every 30 min via launchd).
  1. downloads fulfilled records-request footage
  2. renders approved plans with mac/render.py (episode, Shorts, Reels) — during the approval window a
     fresh render goes back to "pending" so Bobby approves the exact video, not just the plan
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
REPO = Path(__file__).resolve().parent.parent
# Built-in renderer (mac/render.py) unless .env overrides it. {plan} {footage} {out} are filled in.
RENDER_CMD = os.environ.get("RENDER_CMD") or f"{shlex.quote(sys.executable)} {shlex.quote(str(REPO / 'mac' / 'render.py'))} {{plan}} {{footage}} {{out}}"
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

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
MEDIA_RX = re.compile(r"\.(mp4|mov|m4v|avi|zip|wmv|mkv|ts|mts|asf|mpg)(\?|$)", re.I)

def _save(resp, dest_dir, name):
    cd = resp.headers.get("content-disposition", "")
    m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
    name = name or (m and m[1]) or re.sub(r"[^\w.-]", "_", resp.url.split("?")[0].rsplit("/", 1)[-1]) or "file.mp4"
    name = re.sub(r"[^\w.-]", "_", name)
    with open(Path(dest_dir) / name, "wb") as f:
        for chunk in resp.iter_content(1 << 20):
            f.write(chunk)
    return name

def _axon(url, dest_dir):
    """Axon Evidence.com share links open a web app; the files come from its links API using the link's token."""
    from urllib.parse import urlparse, parse_qs
    u = urlparse(url)
    m = re.search(r"/axon/download/([0-9a-f]+)/([0-9a-f]+)", u.path)
    tok = (parse_qs(u.query).get("token") or [None])[0]
    if not (m and tok):
        return False
    api = f"{u.scheme}://{u.netloc}/api/v1/agencies/{m[1]}/evidence/download/{m[2]}/links"
    import time
    for n in range(40):                        # big packages take a while to be zipped (up to ~20 min)
        j = requests.get(api, params={"token": tok}, headers=UA, timeout=60).json()
        if j.get("meta", {}).get("ready"):
            break
        print(f"Axon package not ready yet ({n})", flush=True)
        time.sleep(30)
    got = False
    for seg in j.get("data", []):
        a = seg.get("attributes", {})
        if a.get("url") and not a.get("infected"):
            from urllib.parse import urljoin
            seg_url = urljoin(f"{u.scheme}://{u.netloc}/", a["url"])     # Axon gives a site-relative path
            with requests.get(seg_url, stream=True, timeout=600, headers=UA, params=None) as resp:
                if resp.status_code < 300:
                    nm = _save(resp, dest_dir, a.get("fileName"))
                    print(f"downloaded {nm} ({(Path(dest_dir) / re.sub(r'[^\w.-]', '_', nm)).stat().st_size // 1_000_000} MB)", flush=True)
                    got = True
                else:
                    print(f"Axon segment {resp.status_code}", flush=True)
    return got

def _fetch(url, dest_dir, name=None, depth=0):
    """Download a file. Share pages (Axon Evidence.com, portals) often return an HTML page first; look inside
    it for the real file / zip link and follow that (two levels deep at most)."""
    if "/axon/download/" in url:
        return _axon(url, dest_dir)
    s = requests.Session()
    with s.get(url, stream=True, timeout=120, allow_redirects=True, headers=UA) as resp:
        ctype = resp.headers.get("content-type", "")
        if "/axon/download/" in resp.url:          # email links can redirect through a tracker first
            final = resp.url
        else:
            final = None
        if final:
            pass
        elif resp.status_code >= 300:
            return False
        if final:
            return _axon(final, dest_dir)
        if "text/html" not in ctype and "json" not in ctype:
            _save(resp, dest_dir, name)
            return True
        page = resp.text
        base = resp.url
    if depth >= 2:
        return False
    from urllib.parse import urljoin
    cands = re.findall(r'(?:href|src|data-url|"url"|"downloadUrl"|"download_url")\s*[=:]\s*"([^"]+)"', page)
    cands = [urljoin(base, c.replace("\\u0026", "&").replace("&amp;", "&")) for c in cands]
    cands = [c for c in cands if MEDIA_RX.search(c) or re.search(r"download|export|zip|file", c, re.I)]
    for c in dict.fromkeys(cands):
        if c == base or re.search(r"\.(css|js|png|jpg|svg|ico)(\?|$)", c, re.I):
            continue
        try:
            if _fetch(c, dest_dir, name, depth + 1):
                return True
        except Exception:
            continue
    title = (re.search(r"<title>([^<]*)", page) or [None, ""])[1].strip()
    raise RuntimeError(f"share page didn't give a file (page title: '{title[:80]}', {len(cands)} candidate links)")

def ensure_footage(db, it):
    """Make sure the footage for this item's lead is on disk (cloud runs start empty unless cached)."""
    dest = FOOTAGE / str(it["lead_id"])
    if dest.exists() and any(p for p in dest.iterdir() if not p.name.startswith(".")):
        return True
    dest.mkdir(parents=True, exist_ok=True)
    lead = (db.select("leads", {"id": f"eq.{it['lead_id']}"}) or [{}])[0]
    if lead.get("source_type") == "dvids_public_domain" and config.DVIDS_API_KEY:
        m = re.search(r"/video/(\d+)", lead.get("source_url") or "")
        if m:
            a = requests.get("https://api.dvidshub.net/asset", params={"id": f"video:{m[1]}",
                             "api_key": config.DVIDS_API_KEY}, timeout=60).json().get("results", {})
            files = [f for f in a.get("files", []) if f.get("src") and (f.get("height") or 0) <= 1080]
            files.sort(key=lambda f: (f.get("height") or 0, f.get("bitrate") or 0))
            if files:
                _fetch(files[-1]["src"], dest, f"dvids_{m[1]}.mp4")
    else:
        for r in db.select("records_requests", {"lead_id": f"eq.{it['lead_id']}", "status": "eq.fulfilled"}):
            for url in r.get("download_links") or []:
                if re.search(r"\.(png|jpe?g|gif|svg|ico)(\?|$)", url, re.I):
                    continue
                if any(p for p in dest.iterdir() if not p.name.startswith(".")):
                    break                           # got the package from the first good link
                try:
                    _fetch(url, dest)
                except Exception as e:
                    db.alert("publisher", f"Footage download for {it.get('case_name')}: {e}", "warn")
    return any(p for p in dest.iterdir() if not p.name.startswith("."))

# ---------------- release storage (cloud) ----------------
GH_API = "https://api.github.com/repos/" + os.environ.get("GITHUB_REPOSITORY", "")
RELEASE_TAG = "renders"

def _gh(method, url, **kw):
    h = kw.pop("headers", {})
    h.update({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": h.get("Accept", "application/vnd.github+json")})
    return requests.request(method, url, headers=h, timeout=kw.pop("timeout", 120), **kw)

def _release():
    r = _gh("GET", f"{GH_API}/releases/tags/{RELEASE_TAG}")
    if r.status_code == 404:
        r = _gh("POST", f"{GH_API}/releases", json={"tag_name": RELEASE_TAG, "name": "Rendered videos (review copies)",
                                                     "body": "Ten-Four Tapes renders for review. Managed by the publisher.",
                                                     "prerelease": True})
    r.raise_for_status()
    return r.json()

def store_render(path, ctype="video/mp4"):
    """Upload the finished video (or its thumbnail) to the repo's 'renders' release; returns the link Bobby watches."""
    rel = _release()
    name = Path(path).name
    for a in rel.get("assets", []):
        if a["name"] == name:
            _gh("DELETE", a["url"])
    up = rel["upload_url"].split("{")[0]
    with open(path, "rb") as f:
        r = _gh("POST", up, params={"name": name}, data=f, timeout=1800,
                headers={"Content-Type": ctype, "Accept": "application/vnd.github+json"})
    r.raise_for_status()
    return r.json()["browser_download_url"]

def local_media(it, mp=None):
    """Path to the video (or a thumbnail link) on disk; in the cloud, pull the stored render back down."""
    mp = mp if mp is not None else (it.get("media_path") or "")
    if not mp.startswith("http"):
        return mp if mp and os.path.exists(mp) else None
    name = mp.rsplit("/", 1)[-1]
    dest = OUT / name
    if dest.exists():
        return str(dest)
    rel = _release()
    asset = next((a for a in rel.get("assets", []) if a["name"] == name), None)
    if not asset:
        return None
    OUT.mkdir(parents=True, exist_ok=True)
    with _gh("GET", asset["url"], headers={"Accept": "application/octet-stream"}, stream=True, timeout=1800) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                f.write(chunk)
    return str(dest)

CLOUD = bool(os.environ.get("GITHUB_ACTIONS"))

# ---------------- 2. render ----------------
FAILS = HOME / ".render_failures.json"
MAX_TRIES = 3

def _file_name(it):
    case = re.sub(r"[^\w]+", "_", it.get("case_name") or "case").strip("_")[:40] or "case"
    part = f"_Part{it['part']}" if it.get("part") else ""
    return f"{case}_{it['kind']}{part}_{str(it['id'])[:8]}.mp4"

def _notify(title, text):
    """Mac notification so a fresh render gets watched; harmless anywhere else."""
    if sys.platform == "darwin":
        t = text.replace('"', "'")[:200]
        subprocess.run(["osascript", "-e", f'display notification "{t}" with title "{title}"'], capture_output=True)

def render(db):
    items = db.select("content", {"status": "eq.scripted", "compliance_status": "eq.pass",
                                  "approval_status": "in.(approved,not_required)",
                                  "order": "lead_id.asc,kind.desc,created_at.asc", "limit": 12})
    # all of a case's videos in one run, so its footage is downloaded once
    fails = json.loads(FAILS.read_text()) if FAILS.exists() else {}
    done = 0
    for it in items:
        src = FOOTAGE / str(it["lead_id"])
        try:
            have = ensure_footage(db, it)
        except Exception as e:
            have = False
            db.alert("publisher", f"Footage download failed for {it['case_name']}: {e}", "warn")
        if not have:
            print(f"no footage yet for {it['case_name']} {it['kind']}{it.get('part') or ''}", flush=True)
            db.alert("publisher", f"No footage on disk for {it['case_name']} yet (download not ready or failed)", "warn")
            continue
        QUEUE.mkdir(parents=True, exist_ok=True)
        OUT.mkdir(parents=True, exist_ok=True)
        plan_path = QUEUE / f"{it['id']}.json"
        if it["kind"] == "reel" and it.get("parent_id"):
            # seconds this case's other Reels already use (their picks may be on another machine's cache)
            sib = db.select("content", {"parent_id": f"eq.{it['parent_id']}", "kind": "eq.reel",
                                        "id": f"neq.{it['id']}", "select": "script"})
            it["sibling_cuts"] = [s["script"]["cut"] for s in sib
                                  if isinstance(s.get("script"), dict) and (s["script"].get("cut") or {}).get("path")]
        plan_path.write_text(json.dumps(it, indent=2, default=str))
        out = OUT / _file_name(it)
        cmd = RENDER_CMD.format(plan=shlex.quote(str(plan_path)), footage=shlex.quote(str(src)), out=shlex.quote(str(out)))
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3600)
        lines = (res.stdout + res.stderr).strip().splitlines()
        keep = [l for l in lines[:-8] if l.lstrip("[0-9:] ").startswith(("vision", "writer"))][-30:]
        print(f"--- {it['case_name']} {it['kind']}{it.get('part') or ''}: exit {res.returncode}\n"
              + "\n".join(keep + lines[-8:]), flush=True)
        (HOME / "logs").mkdir(exist_ok=True)
        (HOME / "logs" / f"render_{str(it['id'])[:8]}.log").write_text(res.stdout[-20000:] + "\n" + res.stderr[-20000:])
        if res.returncode == 0 and out.exists():
            link = store_render(out) if CLOUD else str(out)
            upd = {"status": "rendered", "media_path": link}
            side = Path(str(out) + ".script.json")
            if side.exists():                       # the Writer's final on-screen text, so the queue shows what's in the video
                try:
                    w = json.loads(side.read_text())
                    if w.get("thumb") and Path(w["thumb"]).exists():
                        tl = store_render(w["thumb"], "image/jpeg") if CLOUD else w["thumb"]
                        base = upd.get("script") or (it.get("script") if isinstance(it.get("script"), dict) else {})
                        upd["script"] = {**base, "thumbnail": tl}
                    if w.get("cut"):
                        base = upd.get("script") or (it.get("script") if isinstance(it.get("script"), dict) else {})
                        upd["script"] = {**base, "cut": w["cut"]}
                    if w.get("written"):
                        keep = {k: upd["script"][k] for k in ("thumbnail",) if k in (upd.get("script") or {})}
                        upd["script"] = {**w["script"], **keep, **({"cut": w["cut"]} if w.get("cut") else {})}
                        ws = w["script"]
                        if it["kind"] == "reel" and ws.get("caption"):
                            # Facebook caption from the locked cut: place + stakes, one question, credit, tags
                            upd["description"] = "\n".join(x for x in [
                                (ws["caption"] + " " + (ws.get("question") or "")).strip(),
                                "Full episode on YouTube: Ten-Four Tapes", it.get("source_credit") or "",
                                " ".join(ws.get("hashtags") or [])] if x)
                except Exception:
                    pass
                side.unlink(missing_ok=True)
            if it["approval_status"] == "approved":
                # Approval window: the plan was OK'd, now Bobby OKs the exact video before it goes public.
                check = (it.get("script") or {}).get("blur_notes") if isinstance(it.get("script"), dict) else None
                where = link if CLOUD else f"TenFourTapes/rendered/{out.name}"
                upd["approval_status"] = "pending"
                upd["publish_note"] = (f"Video ready — watch it: {where} — then Approve to post it"
                                       + (f". Check: {check}" if check else ""))
                _notify("Ten-Four Tapes", f"Ready to review: {out.name}")
            db.update("content", {"id": f"eq.{it['id']}"}, upd)
            fails.pop(str(it["id"]), None)
            done += 1
        elif res.returncode == 3:
            db.update("content", {"id": f"eq.{it['id']}"}, {"status": "failed",
                      "publish_note": "Skipped: not enough footage for this format (avoids repeating the same clip)"})
        else:
            n = fails.get(str(it["id"]), 0) + 1
            fails[str(it["id"])] = n
            err = (res.stderr or res.stdout)[-300:]
            if n >= MAX_TRIES:
                db.update("content", {"id": f"eq.{it['id']}"}, {"status": "failed",
                          "publish_note": f"Render failed {n}x: {err}"})
            db.alert("mac_runner", f"Render failed ({n}/{MAX_TRIES}) for {it['case_name']} {it['kind']}: {err}", "warn")
    FAILS.parent.mkdir(parents=True, exist_ok=True)
    FAILS.write_text(json.dumps(fails))
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

def set_thumbnail(db, it, vid):
    """Custom thumbnail on an episode. Never fails the post: a refusal (e.g. the channel isn't phone-verified for
    custom thumbnails) becomes one alert with the fix, and the episode keeps YouTube's auto thumbnail."""
    sc = it.get("script") if isinstance(it.get("script"), dict) else {}
    link = sc.get("thumbnail")
    path = local_media(it, link) if link else None
    if not path:
        return
    try:
        with open(path, "rb") as f:
            r = requests.post(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                              headers={"Authorization": f"Bearer {access_token('youtube')}", "Content-Type": "image/jpeg"},
                              data=f, timeout=120)
        if r.status_code >= 300:
            fix = (" — verify the channel for custom thumbnails: https://www.youtube.com/verify"
                   if r.status_code == 403 else "")
            db.alert("publisher", f"Thumbnail not set on '{it['title']}' ({r.status_code}: {r.text[:160]}){fix}", "warn")
    except Exception as e:
        db.alert("publisher", f"Thumbnail not set on '{it['title']}': {str(e)[:200]}", "warn")

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

REEL_GAP_H = 3
SHORT_GAP_H = 4
CASE_REEL_GAP_H = 12   # a case's 2-3 Reels are spread out; another case's Reel goes in between when one is ready

def posted_since(db, kind, hours):
    since = (_now() - timedelta(hours=hours)).isoformat()
    return len(db.select("content", {"kind": f"eq.{kind}", "posted_at": f"gte.{since}", "select": "id"}))

def _case_reel_recent(db, parent_id):
    since = (_now() - timedelta(hours=CASE_REEL_GAP_H)).isoformat()
    return bool(db.select("content", {"parent_id": f"eq.{parent_id}", "kind": "eq.reel",
                                      "posted_at": f"gte.{since}", "select": "id"}))

def publish(db):
    if db.setting("posting_paused", False):
        return "posting paused"
    room = {
        "episode": int(db.setting("episodes_per_week", 2)) - posted_since(db, "episode", 24 * 7),
        "short": int(db.setting("shorts_per_day", 3)) - posted_since(db, "short", 24),
        "reel": int(db.setting("reels_per_day", 3)) - posted_since(db, "reel", 24),
    }
    # Reels go out one at a time, 3h+ apart, 11am-10pm ET: two in the same minute split each other's reach
    from zoneinfo import ZoneInfo
    et_hour = _now().astimezone(ZoneInfo("America/New_York")).hour
    if posted_since(db, "reel", REEL_GAP_H) or not (11 <= et_hour < 22):
        room["reel"] = 0
    else:
        room["reel"] = min(room["reel"], 1)
    # Shorts: up to shorts_per_day (default 3), one per run, 4h+ apart, 9am-11pm ET
    if posted_since(db, "short", SHORT_GAP_H) or not (9 <= et_hour < 23):
        room["short"] = 0
    else:
        room["short"] = min(room["short"], 1)
    ready = db.select("content", {"status": "eq.rendered", "compliance_status": "eq.pass",
                                  "approval_status": "in.(approved,not_required)", "order": "kind.asc,part.asc,created_at.asc"})
    out = []
    for it in ready:
        k = it["kind"]
        if room.get(k, 0) <= 0 or not it.get("media_path"):
            continue
        if k == "reel" and it.get("parent_id") and _case_reel_recent(db, it["parent_id"]):
            continue
        path = local_media(it)
        if not path:
            continue
        it["media_path"] = path
        if config.DRY_RUN:
            out.append(f"[dry] {k} {it['case_name']}")
            room[k] -= 1
            continue
        try:
            upd = {"status": "posted", "posted_at": _now()}
            if k in ("episode", "short"):
                desc = it.get("description") or ""
                if k == "short" and it.get("parent_id"):
                    ep = db.select("content", {"id": f"eq.{it['parent_id']}", "select": "youtube_id,approval_status,status"})
                    if ep and ep[0].get("youtube_id"):
                        desc = f"Full episode: https://youtu.be/{ep[0]['youtube_id']}\n" + desc
                    elif not ep or ep[0].get("approval_status") == "rejected" or ep[0].get("status") == "failed":
                        desc = "\n".join(l for l in desc.splitlines() if "full episode" not in l.lower())
                vid, locked = youtube_upload(it["media_path"], it["title"], desc, it.get("tags"), short=(k == "short"))
                upd["youtube_id"] = vid
                if k == "episode":
                    set_thumbnail(db, it, vid)
                if locked:
                    upd["publish_note"] = "Uploaded but locked private until Google audits the API app — publish in YouTube Studio"
                    db.alert("publisher", f"'{it['title']}' uploaded as PRIVATE (API audit pending) — set Public in Studio", "warn")
            else:
                cap = it.get("description") or it["case_name"]
                ep = db.select("content", {"id": f"eq.{it['parent_id']}", "select": "youtube_id,approval_status,status"}) \
                    if it.get("parent_id") else []
                if ep and ep[0].get("youtube_id"):
                    cap = cap.replace("Full episode on YouTube: Ten-Four Tapes",
                                      f"Full episode: https://youtu.be/{ep[0]['youtube_id']}")
                elif not ep or ep[0].get("approval_status") == "rejected" or ep[0].get("status") == "failed":
                    # no episode will ever exist for this case — never promise one
                    cap = "\n".join(l for l in cap.splitlines() if "full episode" not in l.lower())
                upd["facebook_id"] = facebook_reel(it["media_path"], cap)
            db.update("content", {"id": f"eq.{it['id']}"}, upd)
            room[k] -= 1
            out.append(f"{k}: {it['title']}")
        except Exception as e:
            db.update("content", {"id": f"eq.{it['id']}"}, {"publish_note": str(e)[:500]})
            db.alert("publisher", f"Post failed for {it['title']}: {e}", "warn")
    return f"posted {len(out)}" + (f": {out}" if out else "")

def main(db):
    d = 0 if CLOUD else download_footage(db)
    r = render(db)
    p = publish(db)
    return f"downloaded {d} files, rendered {r}, {p}"

if __name__ == "__main__":
    ok = run_agent("publisher" if CLOUD else "mac_runner", main)
    sys.exit(0 if ok else 1)
