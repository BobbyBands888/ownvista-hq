"""SCOUT agent — finds new footage leads. Sources (all free):
  1. Official agency/prosecutor YouTube channels (lead only — we request the original files, never download from YouTube)
  2. DVIDS public-domain federal video (direct-use)
  3. Google News RSS (tips that point to an agency to request from)
Then the LLM scores every new lead for on-screen action and screens out minors."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import feedparser
import requests
from .lib import config, llm
from .lib.google import yt_get
from .lib.runner import RULES

AGENCY_RX = re.compile(r"sheriff|police|\bpd\b|state attorney|district attorney|prosecutor|highway patrol|"
                       r"state police|public safety|marshal|department of corrections", re.I)
YT_QUERIES = ["bodycam", "body worn camera video", "critical incident video", "officer involved shooting video",
              "pursuit dash cam video", "deputy body camera arrest"]
NEWS_QUERIES = ["bodycam video released", "body camera footage released sheriff",
                "police release body camera video arrest", "911 call and bodycam released",
                "sheriff releases body camera video", "dash cam video released chase",
                "deputies body camera footage shows", "police release video of arrest"]
LOOKBACK_DAYS = 7

def _now():
    return datetime.now(timezone.utc)

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
            leads.append({"title": sn["title"], "agency_name": sn["channelTitle"],
                          "summary": sn.get("description", "")[:600],
                          "source_url": f"https://www.youtube.com/watch?v={it['id']['videoId']}",
                          "source_type": "agency_release"})
    return leads

def from_dvids():
    if not config.DVIDS_API_KEY:
        return []
    r = requests.get("https://api.dvidshub.net/search", params={
        "api_key": config.DVIDS_API_KEY, "q": "body worn camera", "type": "video",
        "sort": "date", "max_results": 25}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"DVIDS {r.status_code}: {r.text[:200]}")
    leads = []
    for it in r.json().get("results", []):
        leads.append({"title": it.get("title", "")[:300], "agency_name": it.get("unit_name") or "DVIDS",
                      "summary": (it.get("description") or "")[:600], "source_url": it.get("url"),
                      "source_type": "dvids_public_domain"})
    return leads

def from_news():
    leads = []
    for q in NEWS_QUERIES:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote_plus(q)}+when:7d&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:20]:
            leads.append({"title": e.title[:300], "summary": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:600],
                          "source_url": e.link, "source_type": "news_tip"})
    return leads

def score(db, leads):
    """LLM fills agency, state, date, action score, category, minors flag."""
    out_rows = []
    for i in range(0, len(leads), 15):
        batch = leads[i:i + 15]
        res = llm.ask(
            "You screen footage leads for Ten-Four Tapes. Bobby only wants real action on screen "
            "(arrests, fights, chases, shootouts, dramatic rescues, strong case stories with 911 + interrogation). "
            "'Ok' isn't enough. Score honestly. A lead is only a records REQUEST (free) — the footage itself gets "
            "judged again before anything is made — so keep any real incident with likely on-camera action and an "
            "identifiable U.S. agency. Skip opinion pieces, policy stories, lawsuits with no incident video, "
            "and non-U.S. incidents.\n" + RULES,
            "Leads:\n" + json.dumps([{"i": n, "title": l["title"], "summary": l.get("summary", "")[:400],
                                       "agency": l.get("agency_name")} for n, l in enumerate(batch)]) +
            '\n\nReturn JSON {"leads":[{"i":0,"agency_name":"official agency that holds the footage or null",'
            '"state":"2-letter or null","incident_date":"YYYY-MM-DD or null","action_score":1-10,'
            '"category":"enforcement|case_story|rescue|other","involves_minor":true|false|null,'
            '"keep":true|false,"why":"short"}]}')
        by_i = {x.get("i"): x for x in res.get("leads", [])}
        for n, l in enumerate(batch):
            s = by_i.get(n, {})
            row = dict(l)
            row["agency_name"] = s.get("agency_name") or l.get("agency_name")
            row["state"] = s.get("state")
            row["incident_date"] = s.get("incident_date")
            row["action_score"] = int(s.get("action_score") or 0)
            row["category"] = s.get("category") or "other"
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
            row["notes"] = s.get("why")
            out_rows.append(row)
    return out_rows

def main(db):
    raw, errors = [], []
    for name, fn in (("youtube", from_youtube), ("dvids", from_dvids), ("news", from_news)):
        try:
            raw += fn()
        except Exception as e:
            errors.append(f"{name}: {e}")
            db.alert("scout", f"source {name} failed: {e}", "warn")
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
    rows = score(db, fresh[:60]) if fresh else []
    if rows:
        db.insert("leads", rows, upsert=True, on_conflict="source_url")
    # make sure each kept agency exists in the directory (email filled only once verified)
    known = {a["name"].lower() for a in db.select("agencies", {"select": "name"})}
    for r in rows:
        a = (r.get("agency_name") or "").strip()
        if r["status"] == "new" and r["source_type"] != "dvids_public_domain" and a and a.lower() not in known:
            db.insert("agencies", {"name": a, "state": r.get("state")}, upsert=True, on_conflict="name")
            known.add(a.lower())
    kept = sum(1 for r in rows if r["status"] in ("new", "obtained"))
    return f"{len(raw)} found, {len(fresh)} new, {kept} kept (score>=6, no minors)" + (f"; errors: {errors}" if errors else "")
