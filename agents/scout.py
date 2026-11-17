"""SCOUT agent — finds new footage leads. Sources (all free):
  1. Agency watchlist (daily): the uploads of sheriff/police/prosecutor YouTube channels that publish their own
     bodycam. When the post links a copy the AGENCY hosts itself (its own site, Dropbox, Drive, Box, Axon share),
     that file is usable with no records request -> lead goes straight to "obtained". Otherwise it's a request
     that cites the video they already released. We never download from YouTube or Facebook (channel rule).
  2. YouTube search (finds new agency channels; they join the watchlist automatically)
  3. DVIDS public-domain federal video (direct-use)
  4. Google News RSS (tips that point to an agency to request from)
Then the LLM scores every new lead: one clear enforcement moment + place + stakes ranks highest; minors screened out."""
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus, urljoin, urlparse
import feedparser
import requests
from .lib import config, llm
from . import casescout
from . import footage
from .lib.google import yt_get
from .lib.runner import RULES

AGENCY_RX = re.compile(r"sheriff|police|\bpd\b|state attorney|district attorney|prosecutor|highway patrol|"
                       r"state police|public safety|marshal|department of corrections|constable|trooper", re.I)
YT_QUERIES = ["bodycam", "body worn camera video", "critical incident video", "officer involved shooting video",
              "pursuit dash cam video", "deputy body camera arrest", "DUI arrest body camera",
              "sovereign citizen traffic stop bodycam", "interrogation video released"]
# Agencies known to post their own bodycam/dashcam releases on YouTube. Resolved to channel IDs once and kept in
# settings["scout_channels"]; channels found by the search pass are added there automatically.
SEED_HANDLES = ["LAPDHQ", "LVMPD", "PhoenixPolice", "SanDiegoPolice", "SeattlePD", "DenverPolice", "FortWorthPD",
                "TucsonPolice", "AlbuquerquePolice", "PolkCountySheriff", "VolusiaSheriff", "MarionSO",
                "OrangeCountySheriffFL", "HCSOSheriff", "PCSOFlorida", "LASDHQ", "SanBernardinoSheriff",
                "RiversideSheriff", "SacSheriff", "HoustonPolice", "DallasPolice", "SanAntonioPolice",
                "AustinPolice", "MiamiDadePD", "MetroNashvillePD", "MemphisPolice", "AtlantaPolice",
                "ColumbusPolice", "IndyPolice", "LouisvilleMetroPD", "MinneapolisPolice", "MesaPD",
                "ScottsdalePD", "ChandlerPolice", "GilbertPolice", "AuroraPD", "ColoradoStatePatrol",
                "OklahomaCityPolice", "TulsaPolice", "FloridaHighwayPatrol", "ChicagoCOPA", "BaltimorePolice"]
# Hosts where an agency keeps its own copy of a release (a link to one of these from the agency's own post
# counts as an agency release). Third-party video sites are deliberately absent.
SELF_HOST_RX = re.compile(r"\.(gov|us)$|(^|\.)(dropbox\.com|drive\.google\.com|box\.com|evidence\.com|"
                          r"sharepoint\.com|onedrive\.live\.com|1drv\.ms|nextrequest\.com|govqa\.us|justfoia\.com)$", re.I)
AGENCY_DOMAIN_RX = re.compile(r"sheriff|police|pd|patrol|copa", re.I)   # lapdonline.org, polksheriff.org, lvmpd.com
NEVER_HOST_RX = re.compile(r"(^|\.)(youtube\.com|youtu\.be|facebook\.com|fb\.watch|instagram\.com|tiktok\.com|"
                           r"x\.com|twitter\.com|vimeo\.com)$", re.I)
MEDIA_RX = re.compile(r"\.(mp4|mov|m4v|avi|zip|wmv|mkv|mts|mpg)(\?|$)", re.I)
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
WATCH_EVERY_H = 20          # agency watchlist runs about once a day
WATCH_LOOKBACK_DAYS = 7
# only uploads that look like incident footage go to the scorer (agency channels also post recruiting, PSAs, pressers)
FOOTAGE_RX = re.compile(r"body ?cam|body[- ]worn|\bbwc\b|dash ?cam|critical incident|officer[- ]involved|\bois\b|"
                        r"pursuit|chase|video release|released video|footage|surveillance video|911 call|arrest|shots fired|"
                        r"traffic stop|smuggl|standoff|carjack", re.I)
NEWS_QUERIES = ["bodycam video released", "body camera footage released sheriff",
                "police release body camera video arrest", "911 call and bodycam released",
                "sheriff releases body camera video", "dash cam video released chase",
                "deputies body camera footage shows", "police release video of arrest",
                # the genres the biggest bodycam channels live on: DUI stops, sovereign citizens, meltdowns, interrogations
                "DUI arrest bodycam video", "sovereign citizen arrest bodycam", "bodycam shows woman arrested after crash",
                "bodycam video shows man refuses", "interrogation video released police", "shoplifting arrest bodycam"]
LOOKBACK_DAYS = 7

def _now():
    return datetime.now(timezone.utc)

FOUND_CHANNELS = {}
STATS = {}          # channelId -> title, collected by the search pass for the watchlist

def from_youtube():
    if _now().hour % 6 >= 3:                 # about every 6h: 6 searches x 100 units stays well inside free quota
        return []
    after = (_now() - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    leads = []
    for q in YT_QUERIES:
        res = yt_get("search", {"part": "snippet", "type": "video", "q": q, "order": "date",
                                "publishedAfter": after, "maxResults": 50, "regionCode": "US"})
        for it in res.get("items", []):
            sn = it["snippet"]
            if not AGENCY_RX.search(sn["channelTitle"]):
                continue
            FOUND_CHANNELS[sn["channelId"]] = sn["channelTitle"]
            leads.append({"title": sn["title"], "agency_name": sn["channelTitle"], "_cid": sn["channelId"],
                          "summary": sn.get("description", "")[:600],
                          "source_url": f"https://www.youtube.com/watch?v={it['id']['videoId']}",
                          "source_type": "agency_release"})
    return leads

# ---------------- agency watchlist ----------------
def _self_hosted(url):
    host = (urlparse(url).hostname or "").lower()
    if not host or NEVER_HOST_RX.search(host):
        return False
    return bool(SELF_HOST_RX.search(host) or AGENCY_DOMAIN_RX.search(host.split(".")[-2] if "." in host else host))

def _direct_url(url):
    """Share links that hand over the file itself when asked the right way."""
    if "dropbox.com" in url:
        return re.sub(r"([?&])dl=0", r"\1dl=1", url) if "dl=" in url else url + ("&" if "?" in url else "?") + "dl=1"
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", url)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m[1]}"
    return url

def agency_files(text):
    """Find video files the agency hosts itself, from the links in its own post. Returns direct file URLs
    (checked live) or share links the publisher already knows how to open (Axon)."""
    links = re.findall(r"https?://[^\s\"'<>)\]]+", text or "")
    found = []
    for raw in dict.fromkeys(l.rstrip(".,;") for l in links):
        if not _self_hosted(raw):
            continue
        url = _direct_url(raw)
        if "/axon/" in url or "evidence.com" in url:
            found.append(url)                        # publisher's _axon() opens these
            continue
        try:
            with requests.get(url, stream=True, timeout=25, allow_redirects=True, headers=UA) as r:
                ctype = r.headers.get("content-type", "")
                if r.status_code >= 300:
                    continue
                if ctype.startswith("video/") or "zip" in ctype or "octet-stream" in ctype or MEDIA_RX.search(r.url):
                    if _self_hosted(r.url):
                        found.append(r.url)
                    continue
                if "text/html" not in ctype:
                    continue
                page = r.raw.read(600_000, decode_content=True).decode("utf-8", "ignore")
                base = r.url
            for c in re.findall(r'(?:href|src|data-url|"url"|"downloadUrl")\s*[=:]\s*"([^"]+)"', page):
                c = urljoin(base, c.replace("&amp;", "&"))
                if MEDIA_RX.search(c) and _self_hosted(c):
                    found.append(c)
        except Exception:
            continue
        if len(found) >= 6:
            break
    return list(dict.fromkeys(found))[:6]

def _watchlist(db):
    """Channel IDs to pull daily: seed handles resolved once, plus every agency channel the search pass finds."""
    chans = db.setting("scout_channels", {}) or {}
    resolved = set(chans.get("_handles_tried", []))
    changed = False
    for h in SEED_HANDLES:
        if h in resolved:
            continue
        try:
            items = yt_get("channels", {"part": "snippet", "forHandle": "@" + h}).get("items", [])
        except Exception:
            items = []
        if items and AGENCY_RX.search(items[0]["snippet"]["title"] + " " + h):
            chans[items[0]["id"]] = items[0]["snippet"]["title"]
        resolved.add(h)
        changed = True
    if not chans.get("_bootstrapped"):
        # one time: every agency channel that posted bodycam in the last year (12 searches x 100 units)
        after = (_now() - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
        for q in YT_QUERIES:
            token = None
            for _ in range(2):
                p = {"part": "snippet", "type": "video", "q": q, "publishedAfter": after, "maxResults": 50,
                     "regionCode": "US"}
                if token:
                    p["pageToken"] = token
                try:
                    res = yt_get("search", p)
                except Exception:
                    break
                for it in res.get("items", []):
                    sn = it["snippet"]
                    if AGENCY_RX.search(sn["channelTitle"]):
                        FOUND_CHANNELS[sn["channelId"]] = sn["channelTitle"]
                token = res.get("nextPageToken")
                if not token:
                    break
        chans["_bootstrapped"] = _now().isoformat()
        changed = True
    if not chans.get("_bootstrapped_agencies"):
        # one time: agency channels by name (search ranks re-uploaders above agencies for "bodycam" queries)
        for q in ["sheriff's office", "police department", "highway patrol", "state police", "state attorney's office",
                  "district attorney", "county sheriff body camera", "police department critical incident"]:
            token = None
            for _ in range(2):
                p = {"part": "snippet", "type": "channel", "q": q, "maxResults": 50, "regionCode": "US"}
                if token:
                    p["pageToken"] = token
                try:
                    res = yt_get("search", p)
                except Exception:
                    break
                for it in res.get("items", []):
                    sn = it["snippet"]
                    cid = sn.get("channelId") or it["id"].get("channelId")
                    if cid and AGENCY_RX.search(sn["channelTitle"]):
                        FOUND_CHANNELS[cid] = sn["channelTitle"]
                token = res.get("nextPageToken")
                if not token:
                    break
        chans["_bootstrapped_agencies"] = _now().isoformat()
        changed = True
    for cid, title in FOUND_CHANNELS.items():
        if cid not in chans:
            chans[cid] = title
            changed = True
    for cid, v in list(chans.items()):
        if not cid.startswith("_") and isinstance(v, str):
            chans[cid] = {"t": v}
    changed |= _classify(chans)
    chans["_handles_tried"] = sorted(resolved)
    if changed:
        db.insert("settings", {"key": "scout_channels", "value": chans, "updated_at": _now().isoformat()},
                  upsert=True, on_conflict="key")
    return {k: v for k, v in chans.items() if not k.startswith("_") and v.get("official")}

def _classify(chans):
    """Official agency channel or a re-uploader? Re-uploads ('Police Activity'-style channels) break the channel rule."""
    todo = [k for k, v in chans.items() if not k.startswith("_") and "official" not in v]
    for i in range(0, len(todo), 40):
        ids = todo[i:i + 40]
        info = {c["id"]: c["snippet"] for c in yt_get("channels", {"part": "snippet", "id": ",".join(ids)}).get("items", [])}
        res = llm.ask(
            "Decide which YouTube channels are run by a U.S. government law-enforcement or prosecutor agency itself "
            "(a sheriff's office, police department, state patrol, district/state attorney, federal agency). Channels "
            "that collect or re-upload other agencies' footage, news outlets, unions, foundations, fan pages and "
            "commentary channels are NOT official, even with 'police' in the name. When unsure, say false.",
            json.dumps([{"id": c, "title": chans[c]["t"], "handle": (info.get(c) or {}).get("customUrl"),
                         "about": ((info.get(c) or {}).get("description") or "")[:300]} for c in ids]) +
            '\n\nReturn JSON {"channels":[{"id":"...","official":true|false}]}', max_tokens=1500, temperature=0)
        got = {x.get("id"): bool(x.get("official")) for x in res.get("channels", [])}
        for c in ids:
            chans[c]["official"] = got.get(c, False) if c in info else False
    return bool(todo)

def drop_reuploads(db, chans_all):
    """Open leads that came from a non-agency channel get skipped (we only request what the agency itself released)."""
    rows = db.select("leads", {"select": "id,source_url", "source_type": "eq.agency_release",
                               "status": "in.(new,queued_request)", "source_url": "like.*youtube.com/watch*", "limit": 300})
    vids = {re.search(r"v=([\w-]+)", r["source_url"])[1]: r["id"] for r in rows if re.search(r"v=([\w-]+)", r["source_url"])}
    ids, dropped = list(vids), 0
    for i in range(0, len(ids), 50):
        for v in yt_get("videos", {"part": "snippet", "id": ",".join(ids[i:i + 50])}).get("items", []):
            cid = v["snippet"]["channelId"]
            if cid not in chans_all:
                chans_all[cid] = {"t": v["snippet"]["channelTitle"]}
                _classify({cid: chans_all[cid]})
            if not chans_all[cid].get("official"):
                db.update("leads", {"id": f"eq.{vids[v['id']]}"},
                          {"status": "skipped", "notes": f"re-upload channel ({v['snippet']['channelTitle']}), not the agency"})
                dropped += 1
    return dropped

def from_watchlist(db):
    forced = len(sys.argv) > 1 and sys.argv[1] == "scout"       # a manual "scout" run always checks the watchlist
    last = db.setting("scout_watch_last")
    if not forced and last and (_now() - datetime.fromisoformat(last)).total_seconds() < WATCH_EVERY_H * 3600:
        return []
    chans = _watchlist(db)
    after = _now() - timedelta(days=WATCH_LOOKBACK_DAYS)
    leads = []
    ids = list(chans)
    for i in range(0, len(ids), 50):                         # 1 unit per 50 channels
        for c in yt_get("channels", {"part": "contentDetails", "id": ",".join(ids[i:i + 50])}).get("items", []):
            uploads = c["contentDetails"]["relatedPlaylists"]["uploads"]
            try:
                items = yt_get("playlistItems", {"part": "snippet", "playlistId": uploads, "maxResults": 15}).get("items", [])
            except Exception:
                continue
            for it in items:
                sn = it["snippet"]
                if datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")) < after:
                    continue
                vid = sn.get("resourceId", {}).get("videoId")
                if not vid or not FOOTAGE_RX.search(sn["title"] + " " + sn.get("description", "")[:500]):
                    continue
                leads.append({"title": sn["title"][:300], "agency_name": chans[c["id"]]["t"], "_cid": c["id"],
                              "summary": sn.get("description", "")[:600], "_desc": sn.get("description", ""),
                              "source_url": f"https://www.youtube.com/watch?v={vid}",
                              "source_type": "agency_release"})
    STATS["channels"] = len(chans)        # official channels only
    db.insert("settings", {"key": "scout_watch_last", "value": _now().isoformat(), "updated_at": _now().isoformat()},
              upsert=True, on_conflict="key")
    return leads

DVIDS_QUERIES = ["body worn camera", "bodycam", "body camera", "dash cam", "military police response",
                 "security forces response", "border patrol apprehension",
                 # our top Facebook Reels (drug sub 106K, Venezuela warning shots 47K, Black Hawk vs. smugglers 1.4K)
                 # are all at-sea interdictions: Coast Guard / CBP Air and Marine boardings, chases and disabling fire
                 "coast guard interdiction", "drug interdiction boarding", "semi-submersible", "narco sub",
                 "warning shots", "disabling fire", "go-fast vessel", "law enforcement detachment boarding",
                 "air and marine operations interdiction", "smuggling vessel"]

def from_dvids():
    if not config.DVIDS_API_KEY:
        return []
    leads, seen = [], set()
    for q in DVIDS_QUERIES:
        r = requests.get("https://api.dvidshub.net/search", params={
            "api_key": config.DVIDS_API_KEY, "q": q, "type": "video", "sort": "date", "max_results": 25}, timeout=30)
        if r.status_code >= 300:
            raise RuntimeError(f"DVIDS {r.status_code}: {r.text[:200]}")
        for it in r.json().get("results", []):
            if it.get("url") in seen:
                continue
            seen.add(it.get("url"))
            try:
                secs = float(it.get("duration") or 0) or None
            except (TypeError, ValueError):
                secs = None
            leads.append({"title": it.get("title", "")[:300], "agency_name": it.get("unit_name") or "DVIDS",
                          "summary": (it.get("description") or "")[:600], "source_url": it.get("url"),
                          "source_type": "dvids_public_domain", "_len": secs})
    return leads

def add_lengths(leads):
    """Video length for YouTube leads (1 quota unit per 50 videos), so Maker plans only what the footage can carry.
    DVIDS leads already carry it from search. Unknown stays unknown (the publisher re-checks real files)."""
    ids = {}
    for l in leads:
        m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", l.get("source_url") or "")
        if m and not l.get("_len"):
            ids[m[1]] = l
    keys = list(ids)
    for i in range(0, len(keys), 50):
        for v in yt_get("videos", {"part": "contentDetails", "id": ",".join(keys[i:i + 50])}).get("items", []):
            secs = footage.iso_seconds(v.get("contentDetails", {}).get("duration"))
            if secs and v.get("id") in ids:
                ids[v["id"]]["_len"] = secs

def from_news():
    leads = []
    for q in NEWS_QUERIES:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:20]:
            leads.append({"title": e.title[:300], "summary": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:600],
                          "source_url": e.link, "source_type": "news_tip"})
    return leads

def _final_score(s, category):
    """Rank by the Quemado/Laredo/Narco Sub pattern: ONE clear enforcement moment + a real place + real stakes."""
    sc = int(s.get("action_score") or 0)
    full = all((s.get(k) or "").strip() for k in ("moment", "place", "stakes"))
    if category == "enforcement" and full:
        sc = min(10, sc + 1)
    elif not full:
        sc = min(sc, 7)
    if category == "rescue":
        sc = min(sc, 6)                       # rescues capped at 6 (and Maker gives them no Reels)
    return sc

def score(db, leads):
    """LLM fills agency, state, date, moment/place/stakes, category, minors flag; code sets the final rank."""
    out_rows = []
    for i in range(0, len(leads), 15):
        batch = leads[i:i + 15]
        res = llm.ask(
            "You screen footage leads for Ten-Four Tapes. Bobby only wants real action on screen "
            "(arrests, fights, chases, shootouts, dramatic rescues, strong case stories with 911 + interrogation). "
            "Our audience wants ENFORCEMENT action (chases, fights, arrests, shots fired, use of force) AND the "
            "character-driven stops the biggest bodycam channels live on: DUI stops where the driver argues or "
            "melts down, sovereign citizens, entitled or absurd arrests, someone who crashes and lies, a funny or "
            "bizarre arrest, and released interrogations of a known case (category case_story). Score those as "
            "enforcement when the conflict or the absurdity is on camera; a calm, routine stop with no conflict "
            "still scores 5 at most. Never score on someone's looks or body, or frame a lead around them. "
            "Rescues and other routine calls score 6 at most unless officers face real danger on camera. "
            "Our winners all had ONE clear enforcement moment (e.g. a smuggling stop that turns into a foot chase, "
            "a narco sub boarding), a named place, and obvious stakes (drugs, guns, a fleeing felon, lives at risk). "
            "Fill moment/place/stakes only from the lead text; leave a field empty if the text doesn't say it. "
            "'Ok' isn't enough. Score honestly. Keep any real incident with likely on-camera action and an "
            "identifiable U.S. agency — the footage itself is judged again before anything is made. "
            "Skip opinion pieces, policy stories, press conferences with no incident video, lawsuits with no incident "
            "video, recruiting/community videos, and non-U.S. incidents.\n" + RULES,
            "Leads:\n" + json.dumps([{"i": n, "title": l["title"], "summary": l.get("summary", "")[:400],
                                       "agency": l.get("agency_name")} for n, l in enumerate(batch)]) +
            '\n\nReturn JSON {"leads":[{"i":0,"agency_name":"official agency that holds the footage or null",'
            '"state":"2-letter or null","incident_date":"YYYY-MM-DD or null","action_score":1-10,'
            '"category":"enforcement|case_story|rescue|other","involves_minor":true|false|null,'
            '"moment":"the one on-camera enforcement moment, or empty","place":"city/county, state, or empty",'
            '"stakes":"what is at risk, or empty","keep":true|false,"why":"short"}]}')
        by_i = {x.get("i"): x for x in res.get("leads", [])}
        for n, l in enumerate(batch):
            s = by_i.get(n, {})
            row = dict(l)
            row["agency_name"] = s.get("agency_name") or l.get("agency_name")
            row["state"] = s.get("state")
            row["incident_date"] = s.get("incident_date")
            row["category"] = s.get("category") or "other"
            row["action_score"] = _final_score(s, row["category"])
            row["involves_minor"] = s.get("involves_minor")
            # 5+ is enough to REQUEST footage; Maker only builds from footage that actually delivers
            keep = row["involves_minor"] is not True and (row["action_score"] >= 6 or
                                                          (s.get("keep") and row["action_score"] >= 5))
            if keep and l["source_type"] != "dvids_public_domain" and not row["agency_name"]:
                keep = False
            if not keep:
                row["status"] = "skipped"
            elif l["source_type"] == "dvids_public_domain":
                row["status"] = "obtained"      # public domain: no request needed
            else:
                row["status"] = "new"
            mps = " | ".join(f"{k}: {s.get(k)}" for k in ("moment", "place", "stakes") if (s.get(k) or "").strip())
            row["notes"] = " — ".join(x for x in (mps, s.get("why")) if x)
            out_rows.append(row)
    return out_rows

def take_direct(rows):
    """Kept agency posts that link a file the agency hosts itself: no records request needed."""
    direct = {}
    for r in rows:
        desc = r.pop("_desc", None)
        if r["status"] != "new" or r["source_type"] != "agency_release" or not desc:
            continue
        files = agency_files(desc)
        if files:
            r["status"] = "obtained"
            r["notes"] = f"direct: agency-hosted file {files[0]} (posted by {r['agency_name']} at {r['source_url']})" + \
                         (f" — {r['notes']}" if r.get("notes") else "")
            direct[r["source_url"]] = files
        else:
            r["summary"] = (f"The agency already published this video ({r['source_url']}); requesting the original "
                            f"file. " + (r.get("summary") or ""))[:900]
    for r in rows:
        r.pop("_desc", None)
    return direct

def main(db):
    raw, errors = [], []
    for name, fn in (("youtube", from_youtube), ("watchlist", lambda: from_watchlist(db)),
                     ("dvids", from_dvids), ("news", from_news)):
        try:
            got = fn()
            for l in got:
                l["_src"] = name
            raw += got
        except Exception as e:
            errors.append(f"{name}: {e}")
            db.alert("scout", f"source {name} failed: {e}", "warn")
    try:
        official = set(_watchlist(db))          # also classifies channels the search pass just found
        before = len(raw)
        raw = [l for l in raw if not l.get("_cid") or l["_cid"] in official]
        STATS["reuploads"] = before - len(raw)
        if STATS.get("channels"):              # once a day, with the watchlist pass
            chans_all = {k: v for k, v in (db.setting("scout_channels", {}) or {}).items()}
            STATS["dropped"] = drop_reuploads(db, chans_all)
            db.insert("settings", {"key": "scout_channels", "value": chans_all, "updated_at": _now().isoformat()},
                      upsert=True, on_conflict="key")
    except Exception as e:
        errors.append(f"channel check: {e}")
        raw = [l for l in raw if not l.get("_cid")]      # can't verify the channel -> don't use YouTube leads this run
    # de-dupe against what we already have
    urls = [l["source_url"] for l in raw if l.get("source_url")]
    seen = set()
    for i in range(0, len(urls), 40):
        chunk = urls[i:i + 40]
        q = ",".join('"' + u.replace('"', "") + '"' for u in chunk)
        seen |= {r["source_url"] for r in db.select("leads", {"select": "source_url", "source_url": f"in.({q})"})}
    # the same incident shows up from many outlets — collapse by normalized headline
    def norm(t):
        t = re.sub(r"\s+[-|–]\s+[^-|–]+$", "", t or "")          # drop " - Outlet Name"
        return re.sub(r"[^a-z0-9 ]", "", t.lower())[:70]
    since = (_now() - timedelta(days=14)).isoformat()
    recent_titles = {norm(r["title"]) for r in db.select("leads", {"select": "title", "created_at": f"gte.{since}", "limit": 2000})}
    fresh, dedupe = [], set()
    for l in raw:
        u, k = l.get("source_url"), norm(l["title"])
        if u and u not in seen and u not in dedupe and k not in recent_titles:
            dedupe.add(u)
            recent_titles.add(k)
            fresh.append(l)
    try:
        add_lengths(fresh[:90])
    except Exception as e:
        errors.append(f"lengths: {e}")
    rows = score(db, fresh[:90]) if fresh else []
    src = {k: f"{v}" for k, v in Counter(l["_src"] for l in raw).items()}
    kept_src = Counter(r["_src"] for r in rows if r["status"] != "skipped")
    short = 0
    for r in rows:
        r.pop("_src", None)
        r.pop("_cid", None)
        secs = r.pop("_len", None)
        if secs:
            r["notes"] = footage.tag(r.get("notes"), secs)
            if secs < footage.REEL_MIN and r["status"] != "skipped":
                r["status"] = "skipped"            # nothing to cut from a clip this short
                r["notes"] = f"too short: {int(secs)}s of video — " + r["notes"]
                short += 1
    direct = take_direct(rows)
    # big closed cases whose police interviews can be requested (once a day, own scoring; see casescout.py)
    case_note = ""
    try:
        case_rows, case_note = casescout.find(db, forced=len(sys.argv) > 1 and sys.argv[1] == "scout")
        rows += case_rows
    except Exception as e:
        errors.append(f"cases: {e}")
        db.alert("scout", f"case scout failed: {e}", "warn")
    if rows:
        db.insert("leads", rows, upsert=True, on_conflict="source_url")
    # agency-hosted files: record them the way a fulfilled request is recorded so the publisher fetches them
    for url, files in direct.items():
        lead = (db.select("leads", {"source_url": f"eq.{url}", "select": "id,title,agency_name"}) or [None])[0]
        if not lead:
            continue
        db.insert("records_requests", {
            "lead_id": lead["id"], "subject": f"Agency release: {lead['title'][:120]}", "status": "fulfilled",
            "last_activity_at": _now().isoformat(), "download_links": files,
            "notes": f"[{_now():%Y-%m-%d}] no request needed — {lead['agency_name']} hosts the file itself ({url})"})
        db.alert("scout", f"Footage in (agency release, no request): {lead['title'][:90]} — {lead['agency_name']}", "info")
    # make sure each kept agency exists in the directory (email filled only once verified)
    known = {a["name"].lower() for a in db.select("agencies", {"select": "name"})}
    for r in rows:
        a = (r.get("agency_name") or "").strip()
        if r["status"] in ("new", "obtained") and r["source_type"] != "dvids_public_domain" and a and a.lower() not in known:
            db.insert("agencies", {"name": a, "state": r.get("state"),
                                   "releases_bodycam": True if r["source_type"] == "agency_release" else None},
                      upsert=True, on_conflict="name")
            known.add(a.lower())
    kept = sum(1 for r in rows if r["status"] in ("new", "obtained"))
    top = sorted((r for r in rows if r["status"] in ("new", "obtained")), key=lambda r: -r["action_score"])[:3]
    return ((f"watching {STATS['channels']} agency channels; " if STATS.get("channels") else "") + (f"{STATS['reuploads']} re-upload items ignored, " if STATS.get("reuploads") else "")
            + (f"{STATS['dropped']} old re-upload leads skipped; " if STATS.get("dropped") else "") + f"{len(raw)} found ({', '.join(f'{k} {v}/{kept_src.get(k, 0)} kept' for k, v in src.items())}), {len(fresh)} new, {kept} kept, {len(direct)} agency-hosted (no request)"
            + (f"; top: " + "; ".join(f"{r['action_score']} {r['title'][:50]}" for r in top) if top else "")
            + (f"; {short} skipped as too short (<{footage.REEL_MIN}s)" if short else "")
            + (f"; {case_note}" if case_note else "")
            + (f"; errors: {errors}" if errors else ""))
