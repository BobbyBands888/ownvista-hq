"""RESEARCH agent — studies the top bodycam/case-story channels and writes playbook insights.
Runs daily. Uses only the free YouTube Data API (about 1,500 of the 10,000 daily quota units)."""
import json
from datetime import datetime, timedelta, timezone
from .lib import llm
from .lib.google import yt_get, iso_duration_to_s
from .lib.runner import RULES

DISCOVERY_QUERIES = [
    "police bodycam footage", "body camera arrest", "bodycam interrogation case",
    "911 call bodycam full story", "police chase dashcam", "sheriff bodycam released",
]
MAX_CHANNELS = 25
LOOKBACK_DAYS = 120

def _now():
    return datetime.now(timezone.utc)

def resolve_seeds(db):
    seeds = db.select("competitor_channels", {"channel_id": "like.seed:*"})
    for s in seeds:
        res = yt_get("search", {"part": "snippet", "type": "channel", "q": s["title"], "maxResults": 1})
        items = res.get("items", [])
        if items:
            cid = items[0]["snippet"]["channelId"]
            db.insert("competitor_channels", {"channel_id": cid, "title": items[0]["snippet"]["title"],
                                              "is_seed": True}, upsert=True, on_conflict="channel_id")
        db.delete("competitor_channels", {"channel_id": f"eq.{s['channel_id']}"})
    return len(seeds)

def discover(db):
    after = (_now() - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts = {}
    for q in DISCOVERY_QUERIES:
        res = yt_get("search", {"part": "snippet", "type": "video", "q": q, "order": "viewCount",
                                "publishedAfter": after, "maxResults": 25, "relevanceLanguage": "en"})
        for it in res.get("items", []):
            cid = it["snippet"]["channelId"]
            counts[cid] = counts.get(cid, 0) + 1
    existing = {c["channel_id"] for c in db.select("competitor_channels", {"select": "channel_id"})}
    room = MAX_CHANNELS - len(existing)
    new = [c for c, n in sorted(counts.items(), key=lambda x: -x[1]) if c not in existing and n >= 2][:max(room, 0)]
    for cid in new:
        db.insert("competitor_channels", {"channel_id": cid}, upsert=True, on_conflict="channel_id")
    return len(new)

def refresh_channels(db):
    stale = (_now() - timedelta(days=6)).isoformat()
    chans = db.select("competitor_channels", {"or": f"(last_checked.is.null,last_checked.lt.{stale})", "limit": 12})
    vids_saved = 0
    since = _now() - timedelta(days=LOOKBACK_DAYS)
    for ch in chans:
        cid = ch["channel_id"]
        info = yt_get("channels", {"part": "snippet,statistics,contentDetails", "id": cid}).get("items", [])
        if not info:
            continue
        info = info[0]
        st = info.get("statistics", {})
        db.update("competitor_channels", {"channel_id": f"eq.{cid}"}, {
            "title": info["snippet"]["title"], "handle": info["snippet"].get("customUrl"),
            "subscribers": int(st.get("subscriberCount", 0) or 0), "total_views": int(st.get("viewCount", 0) or 0),
            "video_count": int(st.get("videoCount", 0) or 0), "last_checked": _now(),
        })
        uploads = info["contentDetails"]["relatedPlaylists"]["uploads"]
        pl = yt_get("playlistItems", {"part": "contentDetails", "playlistId": uploads, "maxResults": 50})
        ids = [i["contentDetails"]["videoId"] for i in pl.get("items", [])]
        if not ids:
            continue
        vids = yt_get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids)}).get("items", [])
        rows = []
        for v in vids:
            pub = datetime.fromisoformat(v["snippet"]["publishedAt"].replace("Z", "+00:00"))
            if pub < since:
                continue
            s = v.get("statistics", {})
            views = int(s.get("viewCount", 0) or 0)
            age_days = max((_now() - pub).total_seconds() / 86400, 1)
            rows.append({
                "video_id": v["id"], "channel_id": cid, "title": v["snippet"]["title"], "published_at": pub,
                "duration_s": iso_duration_to_s(v["contentDetails"]["duration"]), "views": views,
                "likes": int(s.get("likeCount", 0) or 0), "comments": int(s.get("commentCount", 0) or 0),
                "views_per_day": round(views / age_days, 1), "checked_at": _now(),
            })
        db.insert("competitor_videos", rows, upsert=True, on_conflict="video_id")
        vids_saved += len(rows)
    return len(chans), vids_saved

def write_insights(db):
    top = db.select("competitor_videos", {"select": "title,duration_s,views,views_per_day,channel_id,published_at",
                                          "order": "views_per_day.desc", "limit": 60})
    if len(top) < 10:
        return 0
    chans = {c["channel_id"]: c["title"] for c in db.select("competitor_channels", {"select": "channel_id,title"})}
    sample = [{"channel": chans.get(v["channel_id"]), "title": v["title"], "minutes": round((v["duration_s"] or 0) / 60, 1),
               "views_per_day": float(v["views_per_day"] or 0)} for v in top]
    bottom = db.select("competitor_videos", {"select": "title,duration_s,views_per_day",
                                             "order": "views_per_day.asc", "limit": 20})
    ours = db.select("playbook", {"source": "eq.analytics", "active": "is.true", "order": "created_at.desc", "limit": 10})
    out = llm.ask(
        "You are the research lead for Ten-Four Tapes, a faceless police bodycam channel on YouTube and Facebook. "
        "Find concrete, copyable patterns in what top channels in the niche do. Be specific (exact title formulas, "
        "lengths in minutes, hook structures, topic types). No generic advice.\n" + RULES,
        "Top videos by views/day:\n" + json.dumps(sample) +
        "\n\nWorst performers:\n" + json.dumps(bottom) +
        "\n\nOur own analytics insights so far:\n" + json.dumps([o["insight"] for o in ours]) +
        '\n\nReturn JSON: {"insights":[{"category":"title|length|hook|topic|format|thumbnail|cadence|other",'
        '"insight":"one specific actionable sentence","evidence":"short pointer to the examples"}]} — 6 to 10 insights.')
    ins = out.get("insights", [])[:10]
    if ins:
        old = db.select("playbook", {"source": "eq.research", "active": "is.true", "select": "id"})
        for o in old:
            db.update("playbook", {"id": f"eq.{o['id']}"}, {"active": False})
        db.insert("playbook", [{"source": "research", "category": i.get("category", "other"),
                                "insight": i["insight"], "evidence": {"note": i.get("evidence")}} for i in ins if i.get("insight")])
    return len(ins)

def main(db):
    seeds = resolve_seeds(db)
    found = discover(db)
    chans, vids = refresh_channels(db)
    n = write_insights(db)
    return f"seeds resolved {seeds}, new channels {found}, refreshed {chans} channels / {vids} videos, {n} insights"
