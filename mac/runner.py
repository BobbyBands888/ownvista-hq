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
from agents import footage  # noqa: E402

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
            db.alert_once("mac_runner", f"Couldn't auto-download footage for '{r['subject'][:60]}' — portal link needs a "
                          f"manual download into {dest}", "warn", key=f"Couldn't auto-download footage for '{r['subject'][:60]}'")
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
        from urllib.parse import urljoin, urlparse
        if CLOUD and restore_mirror(it["lead_id"], dest):
            return True                             # kept copy: works after the agency's link expires
        for r in db.select("records_requests", {"lead_id": f"eq.{it['lead_id']}", "status": "eq.fulfilled"}):
            links = repair_links(r.get("download_links") or [])
            # some share emails (Evidence.com) give the download button as a site-relative link: rebuild it
            # from the share's own host so it doesn't fail with "No scheme supplied"
            hosts = [f"{u.scheme}://{u.netloc}" for u in map(urlparse, links) if u.scheme and "evidence.com" in u.netloc] \
                or [f"{u.scheme}://{u.netloc}" for u in map(urlparse, links) if u.scheme]
            links = [urljoin(hosts[0] + "/", l) if l.startswith("/") and hosts else l for l in links]
            links = [l for l in links if not l.startswith("/")]
            errs = []
            for url in links:
                if re.search(r"\.(png|jpe?g|gif|svg|ico)(\?|$)", url, re.I):
                    continue
                if any(p for p in dest.iterdir() if not p.name.startswith(".")):
                    break                           # got the package from the first good link
                try:
                    _fetch(url, dest)
                except Exception as e:
                    errs.append(str(e)[:200])
            if not any(p for p in dest.iterdir() if not p.name.startswith(".")) and r.get("gmail_thread_id"):
                # stored links were the wrong ones (e.g. the Evidence.com landing page): re-read the agency's own
                # email for the real /axon/download/ button and try that
                try:
                    from agents.lib.google import get_thread, message_links
                    fresh = [l for m in get_thread(r["gmail_thread_id"]).get("messages", []) for l in message_links(m)
                             if "/axon/download/" in l or MEDIA_RX.search(l)]
                    for url in dict.fromkeys(fresh):
                        if url in links:
                            continue
                        try:
                            if _fetch(url, dest):
                                db.update("records_requests", {"id": f"eq.{r['id']}"},
                                          {"download_links": [url] + [l for l in links if l != url][:9]})
                                break
                        except Exception as e:
                            errs.append(str(e)[:200])
                except Exception as e:
                    errs.append(f"re-reading the email: {str(e)[:120]}")
            if errs and not any(p for p in dest.iterdir() if not p.name.startswith(".")):
                first = next((l for l in links if "evidence.com" in l), links[0] if links else "")
                db.alert_once("publisher", f"Footage download for {it.get('case_name')} needs you: the agency's share "
                              f"page has no direct file ({errs[0][:140]}). Open {first[:200]} and download it; the "
                              "agents keep retrying on their own.", "warn",
                              key=f"Footage download for {it.get('case_name')}")
            elif any(p for p in dest.iterdir() if not p.name.startswith(".")):
                db.resolve_alerts("publisher", f"Footage download for {it.get('case_name')}")
        if CLOUD and any(p for p in dest.iterdir() if not p.name.startswith(".")):
            try:
                n = save_mirror(it["lead_id"], dest)
                db.alert("publisher", f"Footage for {it.get('case_name')} is in HQ: kept {n} files, so renders keep "
                         "working after the agency's link expires", "info")
            except Exception as e:
                db.alert("publisher", f"Couldn't keep a copy of {it.get('case_name')} footage ({str(e)[:160]}). "
                         "Renders work until the agency's link expires", "warn")
    return any(p for p in dest.iterdir() if not p.name.startswith("."))


def repair_links(links):
    """Axon packages sometimes get stored as the site-relative segment link ('/?class=Evidence&proc=PackagePublic...')
    with no host, which fails with 'Invalid URL'. Find the Evidence.com email carrying the same token and put its
    full /axon/download/ link first (the Axon API path rebuilds the segments from it)."""
    from urllib.parse import urlparse, parse_qs
    rel = [l for l in links if l.startswith("/") and "token=" in l]
    if not rel or any("/axon/download/" in l for l in links):
        return links
    tok = (parse_qs(urlparse(rel[0]).query).get("token") or [None])[0]
    if not tok:
        return links
    try:
        from agents.lib.google import search, get_thread, message_links
        for h in search("newer_than:60d from:evidence.com", 25):
            for m in get_thread(h["threadId"]).get("messages", []):
                for l in message_links(m):
                    if "/axon/download/" in l and (parse_qs(urlparse(l).query).get("token") or [None])[0] == tok:
                        print(f"repaired relative Axon link from Gmail thread {h['threadId']}", flush=True)
                        return [l] + [x for x in links if x not in rel]
    except Exception as e:
        print(f"link repair: {str(e)[:160]}", flush=True)
    return links

# ---------------- footage mirror (cloud): agency links expire, a kept copy doesn't ----------------
PART = 1_900_000_000            # GitHub release assets max out at 2 GB: bigger files are stored in parts
MEDIA_FILES = re.compile(r"\.(mp4|mov|m4v|avi|wmv|mkv|ts|mts|asf|mpg|wav|mp3|m4a)$", re.I)

def _find_release(tag):
    """The repo is public, so every release is a DRAFT: drafts are visible only to people with write access
    (raw agency footage and unreviewed renders must never be public). A draft can't be looked up by tag, so list
    them; a release found published is switched back to draft. Assets are fetched in full (lists cap them)."""
    for page in range(1, 20):
        r = _gh("GET", f"{GH_API}/releases", params={"per_page": 100, "page": page})
        r.raise_for_status()
        rows = r.json()
        for rel in rows:
            if rel.get("tag_name") != tag:
                continue
            if not rel.get("draft"):
                p = _gh("PATCH", f"{GH_API}/releases/{rel['id']}", json={"draft": True})
                p.raise_for_status()
                rel = p.json()
            assets = []
            for ap in range(1, 50):
                a = _gh("GET", f"{GH_API}/releases/{rel['id']}/assets", params={"per_page": 100, "page": ap})
                a.raise_for_status()
                assets += a.json()
                if len(a.json()) < 100:
                    break
            rel["assets"] = assets
            return rel
        if len(rows) < 100:
            return None
    return None

def _new_release(tag, name, body):
    r = _gh("POST", f"{GH_API}/releases", json={"tag_name": tag, "name": name, "body": body, "draft": True})
    r.raise_for_status()
    return {**r.json(), "assets": []}

def _mirror_release(lead_id, create=False):
    tag = f"footage-{lead_id}"
    rel = _find_release(tag)
    if rel is None and create:
        rel = _new_release(tag, f"Footage {lead_id}", "Kept copy of agency footage for this lead. Managed by the publisher.")
    return rel

def save_mirror(lead_id, folder):
    """Upload the case's footage files (zips unpacked first) to the footage-<lead_id> release."""
    sys.path.insert(0, str(REPO / "mac"))
    import picker
    picker.unpack_zips(folder)
    rel = _mirror_release(lead_id, create=True)
    have = {a["name"] for a in rel.get("assets", [])}
    up = rel["upload_url"].split("{")[0]
    n = 0
    for f in sorted(Path(folder).rglob("*")):
        if not f.is_file() or not MEDIA_FILES.search(f.name):
            continue
        base = re.sub(r"[^\w.-]", "_", str(f.relative_to(folder)))
        size = f.stat().st_size
        parts = [(base, 0, size)] if size <= PART else \
            [(f"{base}.part{i:02d}", o, min(PART, size - o)) for i, o in enumerate(range(0, size, PART))]
        for name, off, ln in parts:
            if name in have:
                continue
            with open(f, "rb") as fh:
                fh.seek(off)
                data = fh.read(ln)
            r = _gh("POST", up, params={"name": name}, data=data, timeout=3600,
                    headers={"Content-Type": "application/octet-stream", "Accept": "application/vnd.github+json"})
            r.raise_for_status()
        n += 1
    return n

def restore_mirror(lead_id, dest):
    """Download a kept copy (rejoining .partNN files). True if anything came back."""
    try:
        rel = _mirror_release(lead_id)
    except Exception:
        return False
    if not rel or not rel.get("assets"):
        return False
    for a in sorted(rel["assets"], key=lambda a: a["name"]):
        name = re.sub(r"\.part\d\d$", "", a["name"])
        mode = "ab" if a["name"] != name and not a["name"].endswith(".part00") else "wb"
        with _gh("GET", a["url"], headers={"Accept": "application/octet-stream"}, stream=True, timeout=3600) as r:
            r.raise_for_status()
            with open(Path(dest) / name, mode) as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    print(f"restored {len(rel['assets'])} kept footage files for lead {lead_id}", flush=True)
    return any(p for p in Path(dest).iterdir() if not p.name.startswith("."))

# ---------------- release storage (cloud) ----------------
GH_API = "https://api.github.com/repos/" + os.environ.get("GITHUB_REPOSITORY", "")
RELEASE_TAG = "renders"

def _gh(method, url, **kw):
    h = kw.pop("headers", {})
    h.update({"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}", "Accept": h.get("Accept", "application/vnd.github+json")})
    return requests.request(method, url, headers=h, timeout=kw.pop("timeout", 120), **kw)

def _release():
    return _find_release(RELEASE_TAG) or _new_release(RELEASE_TAG, "Rendered videos (review copies)",
                                                      "Ten-Four Tapes renders for review. Managed by the publisher.")

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

def _free_footage(folder):
    """Delete a case's downloaded video files but keep the .tft_*.json transcripts/picks (they're cached)."""
    try:
        for f in Path(folder).rglob("*"):
            if f.is_file() and not f.name.startswith(".tft_"):
                f.unlink(missing_ok=True)
    except Exception as e:
        print(f"cleanup: {e}", flush=True)


def footage_seconds(folder):
    """Total seconds of video in a case's footage folder (zips unpacked first; quick header reads, no vision)."""
    sys.path.insert(0, str(REPO / "mac"))
    import media
    import picker
    picker.unpack_zips(folder)
    total = 0.0
    for p in Path(folder).rglob("*"):
        if p.suffix.lower() in media.VIDEO_EXT and not p.name.startswith("."):
            try:
                total += media.probe(p)["duration"]
            except Exception:
                pass
    return total


def run_autocheck(db, it, out):
    """Read the finished video (see mac/autocheck.py). Never raises: a check that can't run is a hold."""
    try:
        sys.path.insert(0, str(REPO / "mac"))
        import autocheck
        lead = (db.select("leads", {"id": f"eq.{it['lead_id']}"}) or [{}])[0] if it.get("lead_id") else {}
        side = Path(str(out) + ".script.json")
        w = json.loads(side.read_text()) if side.exists() else {}
        script = w.get("script") if w.get("written") else it.get("script")
        ac = autocheck.check(out, it, lead, it.get("case_facts"), script=script,
                             log=lambda m: print(m, flush=True))
    except Exception as e:
        ac = {"verdict": "hold", "problems": [f"auto-check couldn't run ({str(e)[:200]})"], "read": 0, "sampled": 0}
    ac["checked_at"] = _now().isoformat()
    sheets = ac.pop("_sheets", None) or []
    if sheets:                                  # the frames it looked at, for the dashboard / a remote frame check
        try:
            db.insert("settings", {"key": f"review_sheets:{it['id']}", "updated_at": _now().isoformat(),
                                   "value": {"checked_at": ac["checked_at"], "sheets": [
                                       {"times": s["times"], "jpg": autocheck.small_jpeg_b64(s["jpeg"])} for s in sheets]}},
                      upsert=True, on_conflict="key")
        except Exception as e:
            print(f"review sheets not saved: {e}", flush=True)
    print(f"autocheck {it['case_name']} {it['kind']}{it.get('part') or ''}: {ac['verdict']} "
          f"({ac['read']}/{ac['sampled']} frames) {ac['problems'][:4]}", flush=True)
    return ac


def recheck(db, limit=4):
    """Renders waiting for review that were made before the auto-check existed: pull the stored file back down and
    check it, so the review queue says what the machine saw (and keeps frames for a remote frame-by-frame check)."""
    items = db.select("content", {"status": "eq.rendered", "approval_status": "eq.pending",
                                  "media_path": "like.http*", "order": "created_at.asc", "limit": 40})
    items = [it for it in items if not (isinstance(it.get("script"), dict) and it["script"].get("autocheck"))][:limit]
    done = 0
    for it in items:
        try:
            path = local_media(it)
        except Exception as e:
            print(f"recheck {it['case_name']}: download failed {e}", flush=True)
            continue
        if not path:
            continue
        try:
            from agents import casefacts
            it["case_facts"] = casefacts.get(db, it["lead_id"]) if it.get("lead_id") else None
        except Exception:
            it["case_facts"] = None
        ac = run_autocheck(db, it, Path(path))
        sc = it["script"] if isinstance(it.get("script"), dict) else {}
        note = it.get("publish_note") or ""
        note = (f"AUTO-CHECK HELD THIS: {'; '.join(ac['problems'][:4])} — " if ac["verdict"] != "pass"
                else f"Auto-check passed ({ac['read']}/{ac['sampled']} frames read) — ") + note
        db.update("content", {"id": f"eq.{it['id']}"}, {"script": {**sc, "autocheck": ac}, "publish_note": note[:1500]})
        if CLOUD:
            Path(path).unlink(missing_ok=True)
        done += 1
    return done


def render(db):
    items = db.select("content", {"status": "eq.scripted", "compliance_status": "eq.pass",
                                  "approval_status": "in.(approved,not_required)",
                                  "order": "lead_id.asc,kind.desc,created_at.asc", "limit": 40})
    # migrant / human-smuggling cases are never made (minors can't be ruled out): Maker skips new ones, and plans
    # made before that rule (Coastal Interdiction re-rendered 4 videos on Nov 18) are rejected here, not rendered
    try:
        from agents.lib import sources
        ids = sorted({str(it["lead_id"]) for it in items if it.get("lead_id")})
        bad = {str(l["id"]) for l in (db.select("leads", {"id": f"in.({','.join(ids)})",
                                                          "select": "id,title,summary,notes"}) if ids else [])
               if sources.is_people_smuggling(l)}
    except Exception as e:
        print(f"smuggling check failed: {e}", flush=True)
        bad = set()
    for it in [it for it in items if str(it.get("lead_id")) in bad]:
        db.update("content", {"id": f"eq.{it['id']}"}, {"approval_status": "rejected", "status": "failed",
                  "publish_note": "Rejected: migrant / human-smuggling case (minors can't be ruled out); not rendered"})
        print(f"skip {it['case_name']} {it['kind']}{it.get('part') or ''}: people-smuggling case", flush=True)
    items = [it for it in items if str(it.get("lead_id")) not in bad]
    waiting = {k.split(":")[1] for k in (json.loads(FAILS.read_text()) if FAILS.exists() else {}) if k.startswith("vision_wait:")}
    items = sorted(items, key=lambda it: str(it.get("lead_id")) in waiting)[:12]   # stable: case order kept
    # all of a case's videos in one run, so its footage is downloaded once
    fails = json.loads(FAILS.read_text()) if FAILS.exists() else {}
    done = 0
    prev = None
    vision_down = set()
    secs_of = {}
    for it in items:
        src = FOOTAGE / str(it["lead_id"])
        if it["lead_id"] in vision_down:
            continue                                # vision already failed for this case this run: don't burn ~10 min per item
        if CLOUD and sys.platform != "darwin" and prev and prev != src:
            _free_footage(prev)                     # cloud runner disk is small: one case's footage at a time
        prev = src
        try:
            have = ensure_footage(db, it)
        except Exception as e:
            have = False
            db.alert_once("publisher", f"Footage download failed for {it['case_name']}: {e}", "warn",
                          key=f"Footage download failed for {it['case_name']}")
        if not have:
            print(f"no footage yet for {it['case_name']} {it['kind']}{it.get('part') or ''}", flush=True)
            # one open alert per case, not one per item per run (Pole Crash filled 'Needs you' 9 times)
            db.alert_once("publisher", f"No footage on disk for {it['case_name']} yet (download not ready or failed)",
                          "warn", key=f"No footage on disk for {it['case_name']}")
            continue
        db.resolve_alerts("publisher", f"No footage on disk for {it['case_name']}")
        db.resolve_alerts("publisher", f"Footage download failed for {it['case_name']}")
        # trim the plan to what the footage can carry BEFORE any vision time is spent (28s clip != episode + 6 items)
        if it["lead_id"] not in secs_of:
            secs_of[it["lead_id"]] = footage_seconds(src)
        ok, why = footage.fits(it, footage.budget(secs_of[it["lead_id"]]))
        if not ok:
            db.update("content", {"id": f"eq.{it['id']}"}, {"status": "failed",
                      "publish_note": f"Skipped: only {secs_of[it['lead_id']]:.0f}s of footage; {why}"})
            print(f"skip {it['case_name']} {it['kind']}{it.get('part') or ''}: {why}", flush=True)
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
        if it["kind"] == "short" and it.get("parent_id"):
            ep = db.select("content", {"id": f"eq.{it['parent_id']}", "select": "status,approval_status"})
            it["episode_planned"] = bool(ep) and ep[0].get("status") != "failed" and ep[0].get("approval_status") != "rejected"
        if it["kind"] == "reel" and it.get("lead_id"):
            # the agency's own statement: the only source for the Reel's captions and narrator lines
            ld = db.select("leads", {"id": f"eq.{it['lead_id']}",
                                     "select": "title,agency_name,state,incident_date,summary,source_type,notes"})
            it["lead"] = ld[0] if ld else None
        try:                                        # who / why / how it ended, for the narrator lines
            from agents import casefacts
            it["case_facts"] = casefacts.get(db, it["lead_id"]) if it.get("lead_id") else None
        except Exception:
            it["case_facts"] = None
        # plans made before the fact check have no camera type: work it out from the lead (aerial != bodycam)
        if isinstance(it.get("script"), dict) and not it["script"].get("camera") and it.get("lead_id"):
            try:
                from agents import factcheck
                lead = (db.select("leads", {"id": f"eq.{it['lead_id']}", "select": "title,summary,notes,source_type"})
                        or [{}])[0]
                it["script"]["camera"] = factcheck.camera_kind(lead)
            except Exception:
                pass
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
            ac = run_autocheck(db, it, out)          # before the file is moved/deleted
            link = store_render(out) if CLOUD else str(out)
            if CLOUD:
                for big in OUT.glob("*.mp4"):           # stored on the release; free the runner disk
                    big.unlink(missing_ok=True)
            upd = {"status": "rendered", "media_path": link}
            side = Path(str(out) + ".script.json")
            if side.exists():                       # the Writer's final on-screen text, so the queue shows what's in the video
                try:
                    w = json.loads(side.read_text())
                    thumbs = [t for t in (w.get("thumbs") or [w.get("thumb")]) if t and Path(t).exists()]
                    if thumbs:
                        tls = [store_render(t, "image/jpeg") if CLOUD else t for t in thumbs]
                        base = upd.get("script") or (it.get("script") if isinstance(it.get("script"), dict) else {})
                        upd["script"] = {**base, "thumbnail": tls[0], "thumbnails": tls}
                    if w.get("cut"):
                        base = upd.get("script") or (it.get("script") if isinstance(it.get("script"), dict) else {})
                        upd["script"] = {**base, "cut": w["cut"]}
                    if w.get("written"):
                        keep = {k: upd["script"][k] for k in ("thumbnail", "thumbnails") if k in (upd.get("script") or {})}
                        upd["script"] = {**w["script"], **keep, **({"cut": w["cut"]} if w.get("cut") else {})}
                        ws = w["script"]
                        if it["kind"] == "episode" and ws.get("title"):
                            upd["title"] = ws["title"]          # formula title written from the locked cut
                            tags = ws.get("analysis_tags") if isinstance(ws.get("analysis_tags"), dict) else {}
                            if ws.get("title_formula"):
                                upd["script"]["analysis_tags"] = {**tags, "title_formula": ws["title_formula"]}
                        if it["kind"] == "reel" and ws.get("caption"):
                            # Facebook caption from the locked cut: place + stakes, one question, credit, tags
                            upd["description"] = "\n".join(x for x in [
                                (ws["caption"] + " " + (ws.get("question") or "")).strip(),
                                "Full episode on YouTube: Ten-Four Tapes", it.get("source_credit") or "",
                                " ".join(ws.get("hashtags") or [])] if x)
                except Exception:
                    pass
                side.unlink(missing_ok=True)
            where = link if CLOUD else f"TenFourTapes/rendered/{out.name}"
            if it["approval_status"] == "approved":
                # Approval window: the plan was OK'd, now Bobby OKs the exact video before it goes public.
                check = (it.get("script") or {}).get("blur_notes") if isinstance(it.get("script"), dict) else None
                upd["approval_status"] = "pending"
                upd["publish_note"] = (f"Video ready — watch it: {where} — then Approve to post it"
                                       + (f". Check: {check}" if check else ""))
                _notify("Ten-Four Tapes", f"Ready to review: {out.name}")
            # Post-render auto-check: anything doubtful waits for Bobby, even if it was cleared to auto-post
            base = upd.get("script") or (it.get("script") if isinstance(it.get("script"), dict) else {}) or {}
            upd["script"] = {**base, "autocheck": ac}
            if ac["verdict"] != "pass":
                upd["approval_status"] = "pending"
                upd["publish_note"] = (f"AUTO-CHECK HELD THIS: {'; '.join(ac['problems'][:4])} — watch it: {where}"
                                       " — fix it or Approve if it's fine")
                db.alert("autocheck", f"Held {it['case_name']} {it['kind']}{it.get('part') or ''}: "
                         + "; ".join(ac["problems"][:3]), "warn")
            elif upd.get("approval_status") == "pending":
                upd["publish_note"] += f" · Auto-check passed ({ac['read']}/{ac['sampled']} frames read)"
            db.update("content", {"id": f"eq.{it['id']}"}, upd)
            fails.pop(str(it["id"]), None)
            db.resolve_alerts("mac_runner", f"Waiting to render {it['case_name']}")
            done += 1
        elif res.returncode == 4:
            vision_down.add(it["lead_id"])
            # vision down (free-tier cap / provider error): keep it queued, say so once per case per day
            key = f"vision_wait:{it['lead_id']}:{_now():%Y-%m-%d}"
            if not fails.get(key):
                fails[key] = 1
                db.alert("mac_runner", f"Waiting to render {it['case_name']}: the frame-reading AI is down or capped "
                         "right now. It retries automatically every run; nothing renders blind.", "info")
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

YT_UPLOADS_PER_DAY = 6     # YouTube API: 10,000 units/day, an upload costs 1,600

def reel_to_youtube(db, it, cap, ep_yt):
    """Cross-post a standalone Reel as a YouTube Short, inside the API's daily upload budget."""
    since = (_now() - timedelta(hours=24)).isoformat()
    used = len(db.select("content", {"youtube_id": "not.is.null", "posted_at": f"gte.{since}", "select": "id"}))
    if used >= YT_UPLOADS_PER_DAY:
        return None
    sc = it.get("script") if isinstance(it.get("script"), dict) else {}
    first = (cap.splitlines() or [""])[0]
    title = (sc.get("hook_text") or first or it["case_name"]).strip()
    title = (title[:88].rstrip() + " #shorts")[:100]
    lines = [l for l in cap.splitlines() if "full episode" not in l.lower()]
    desc = "\n".join(([f"Full episode: https://youtu.be/{ep_yt}"] if ep_yt else []) + lines)
    try:
        vid, _ = youtube_upload(it["media_path"], title, desc, it.get("tags"), short=True)
        return vid
    except Exception as e:
        db.alert("publisher", f"Reel posted to Facebook but not YouTube ('{it['title']}'): {str(e)[:200]}", "info")
        return None

_FB_TOKEN = None

def fb_token_info(tok, page_id):
    """What the stored FB token actually is (never prints the token). (#200 'no permission to post videos on this
    target' is what Facebook says when a person's token is used where the Page's own token is needed.)"""
    me = requests.get(FB + "me", params={"fields": "id,name", "access_token": tok}, timeout=30).json()
    if "error" in me:
        return {"ok": False, "kind": "invalid", "detail": me["error"].get("message", "")[:200]}
    if str(me.get("id")) == str(page_id):
        return {"ok": True, "kind": "page", "detail": f"Page token for {me.get('name')} ({me.get('id')})"}
    return {"ok": False, "kind": "user", "detail": f"Token belongs to {me.get('name')} ({me.get('id')}), not Page {page_id}"}

def fb_page_token():
    """The Page's own token. If the secret holds a personal token instead, swap it for the Page token it can get."""
    global _FB_TOKEN
    if _FB_TOKEN:
        return _FB_TOKEN
    tok, page = (config.FB_PAGE_TOKEN or "").strip(), (config.FB_PAGE_ID or "").strip()
    info = fb_token_info(tok, page)
    if info["kind"] == "user":
        r = requests.get(FB + page, params={"fields": "access_token", "access_token": tok}, timeout=30).json()
        if r.get("access_token"):
            tok = r["access_token"]
        else:
            raise RuntimeError(f"FB token problem: {info['detail']}, and it can't get the Page's token: {r}")
    elif info["kind"] == "invalid":
        raise RuntimeError(f"FB token problem: {info['detail']}")
    _FB_TOKEN = tok
    return tok

def facebook_reel(path, caption):
    tok = fb_page_token()
    start = requests.post(FB + f"{config.FB_PAGE_ID.strip()}/video_reels",
                          params={"upload_phase": "start", "access_token": tok}, timeout=60).json()
    vid = start.get("video_id")
    if not vid:
        raise RuntimeError(f"FB start failed ({fb_token_info(tok, config.FB_PAGE_ID.strip())['detail']}): {start}")
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        up = requests.post(start["upload_url"], data=f, timeout=1800,
                           headers={"Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(size)})
    if up.status_code >= 300:
        raise RuntimeError(f"FB upload {up.status_code}: {up.text[:300]}")
    fin = requests.post(FB + f"{config.FB_PAGE_ID.strip()}/video_reels", params={
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
                    ab = (it.get("script") or {}).get("thumbnails") if isinstance(it.get("script"), dict) else None
                    if ab and len(ab) > 1:
                        # The YouTube API can't start a Test & Compare; Studio can. Thumbnail A is already set.
                        db.alert("publisher", f"'{it['title']}' is live with thumbnail A. Start Test & Compare in "
                                 f"Studio (https://studio.youtube.com/video/{vid}/edit → Thumbnail → Test & compare) "
                                 f"with these {len(ab)}: " + " | ".join(ab), "warn")
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
                # same standalone moment also goes up as a YouTube Short (a failure here never undoes the FB post)
                yt = reel_to_youtube(db, it, cap, ep[0].get("youtube_id") if ep else None)
                if yt:
                    upd["youtube_id"] = yt
            db.update("content", {"id": f"eq.{it['id']}"}, upd)
            room[k] -= 1
            out.append(f"{k}: {it['title']}")
        except Exception as e:
            db.update("content", {"id": f"eq.{it['id']}"}, {"publish_note": str(e)[:500]})
            db.alert("publisher", f"Post failed for {it['title']}: {e}", "warn")
    return f"posted {len(out)}" + (f": {out}" if out else "")

KEEP_DAYS = 14   # agency links usually expire 7-14 days after delivery

def keep_copies(db):
    """Keep a copy of each newly delivered footage package as soon as it arrives, not only when something from it
    renders: Highlands (17 files) was delivered Nov 6, rendered from once, and was never kept, so it would have been
    lost when its link expired. One package per run (disk and time on the runner)."""
    since = (_now() - timedelta(days=KEEP_DAYS)).isoformat()
    reqs = db.select("records_requests", {"status": "eq.fulfilled", "download_links": "not.is.null",
                                          "last_activity_at": f"gte.{since}", "select": "lead_id,subject",
                                          "order": "last_activity_at.asc"})
    failed = []
    # packages whose link keeps failing (expired, view-only share page) were retried every run, ~40 min each time;
    # give up after KEEP_TRIES and tell Bobby once
    tries = db.setting("keep_copies_failed", {}) or {}
    for r in reqs:
        if not r.get("lead_id"):
            continue
        lid = str(r["lead_id"])
        if tries.get(lid, 0) >= KEEP_TRIES:
            continue
        try:
            rel = _mirror_release(r["lead_id"])
        except Exception:
            continue
        if rel and rel.get("assets"):
            continue
        dest = FOOTAGE / str(r["lead_id"])
        ok = ensure_footage(db, {"lead_id": r["lead_id"], "case_name": (r.get("subject") or "")[:80]})
        _free_footage(dest)
        if ok:
            tries.pop(lid, None)
            _save_tries(db, tries)
            return f"kept {r['lead_id']}"
        failed.append(lid[:8])                      # expired link etc.: try the next package instead of stopping
        tries[lid] = tries.get(lid, 0) + 1
        if tries[lid] >= KEEP_TRIES:
            name = (r.get("subject") or lid)[:80]
            db.alert_once("publisher", f"Gave up keeping a copy of footage for '{name}' after {KEEP_TRIES} tries — "
                                       "the link may have expired or be view-only. Save it by hand if it matters.",
                          "warn", key=f"Gave up keeping a copy of footage for '{name}'")
    _save_tries(db, tries)
    return f"couldn't fetch {', '.join(failed)}" if failed else "nothing new to keep"


KEEP_TRIES = 3


def _save_tries(db, tries):
    try:
        db.insert("settings", {"key": "keep_copies_failed", "value": tries, "updated_at": _now().isoformat()},
                  upsert=True, on_conflict="key")
    except Exception:
        pass

def main(db):
    d = 0 if CLOUD else download_footage(db)
    r = render(db)
    try:
        rc = recheck(db)
    except Exception as e:
        rc = f"error {e}"
    p = publish(db)
    k = keep_copies(db) if CLOUD else "-"
    return f"downloaded {d} files, rendered {r}, auto-checked {rc} older renders, {p}; footage copies: {k}"

if __name__ == "__main__":
    ok = run_agent("publisher" if CLOUD else "mac_runner", main)
    sys.exit(0 if ok else 1)
