"""ANALYTICS agent — pulls our own YouTube + Facebook numbers daily and turns them into playbook
insights that Research and Maker read. (Research looks outward; this looks at us.)"""
import json
from datetime import date, timedelta
import requests
from .lib import config, llm
from .lib.google import yt_get, access_token

FB = "https://graph.facebook.com/v21.0/"

def youtube(db):
    rows = []
    me = yt_get("channels", {"part": "statistics,contentDetails", "mine": "true"}, oauth=True).get("items", [])
    if not me:
        return rows
    st = me[0]["statistics"]
    rows.append({"platform": "youtube", "external_id": "channel", "views": int(st.get("viewCount", 0)),
                 "followers": int(st.get("subscriberCount", 0) or 0), "raw": st})
    uploads = me[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = [i["contentDetails"]["videoId"] for i in
           yt_get("playlistItems", {"part": "contentDetails", "playlistId": uploads, "maxResults": 50}).get("items", [])]
    watch = {}
    try:
        end = date.today()
        r = requests.get("https://youtubeanalytics.googleapis.com/v2/reports", headers={"Authorization": f"Bearer {access_token('youtube')}"},
                         params={"ids": "channel==MINE", "startDate": (end - timedelta(days=90)).isoformat(), "endDate": end.isoformat(),
                                 "metrics": "views,estimatedMinutesWatched,averageViewPercentage,subscribersGained",
                                 "dimensions": "video", "sort": "-views", "maxResults": 200}, timeout=30)
        if r.status_code < 300:
            for row in r.json().get("rows", []):
                watch[row[0]] = {"minutes": row[2], "avg_pct": row[3], "subs": row[4]}
    except Exception:
        pass
    content_by_yt = {c["youtube_id"]: c["id"] for c in db.select("content", {"select": "id,youtube_id", "youtube_id": "not.is.null"})}
    for i in range(0, len(ids), 50):
        for v in yt_get("videos", {"part": "snippet,statistics,contentDetails", "id": ",".join(ids[i:i + 50])}).get("items", []):
            s = v.get("statistics", {})
            w = watch.get(v["id"], {})
            rows.append({"platform": "youtube", "external_id": v["id"], "content_id": content_by_yt.get(v["id"]),
                         "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0) or 0),
                         "comments": int(s.get("commentCount", 0) or 0), "watch_minutes": w.get("minutes"),
                         "raw": {"title": v["snippet"]["title"], "published": v["snippet"]["publishedAt"],
                                 "duration": v["contentDetails"]["duration"], **w}})
    return rows

def facebook(db):
    if not (config.FB_PAGE_ID and config.FB_PAGE_TOKEN):
        return []
    tok = {"access_token": config.FB_PAGE_TOKEN}
    rows = []
    page = requests.get(FB + config.FB_PAGE_ID, params={**tok, "fields": "followers_count,fan_count"}, timeout=30).json()
    rows.append({"platform": "facebook", "external_id": "page", "followers": page.get("followers_count"), "raw": page})
    reels = requests.get(FB + f"{config.FB_PAGE_ID}/video_reels",
                         params={**tok, "fields": "id,description,created_time", "limit": 50}, timeout=30).json().get("data", [])
    content_by_fb = {c["facebook_id"]: c["id"] for c in db.select("content", {"select": "id,facebook_id", "facebook_id": "not.is.null"})}
    for rl in reels:
        ins = requests.get(FB + f"{rl['id']}/video_insights", params=tok, timeout=30).json().get("data", [])
        vals = {m["name"]: (m.get("values") or [{}])[0].get("value") for m in ins}
        plays = next((v for k, v in vals.items() if "play" in k and isinstance(v, (int, float))), None)
        rows.append({"platform": "facebook", "external_id": rl["id"], "content_id": content_by_fb.get(rl["id"]),
                     "views": plays, "raw": {"caption": (rl.get("description") or "")[:200],
                                             "created": rl.get("created_time"), "insights": vals}})
    return rows

def insights(db, rows):
    vids = [r for r in rows if r["external_id"] not in ("channel", "page") and r.get("views") is not None]
    if len(vids) < 6:
        return 0
    vids.sort(key=lambda r: -(r["views"] or 0))
    brief = lambda r: {"platform": r["platform"], "views": r["views"], "watch_min": r.get("watch_minutes"),
                       "title": r["raw"].get("title") or r["raw"].get("caption"), "duration": r["raw"].get("duration"),
                       "avg_view_pct": r["raw"].get("avg_pct")}
    out = llm.ask("You analyze our own channel numbers for Ten-Four Tapes. Say what is working for US and what to "
                  "do more or less of. Specific, evidence-based, no fluff.",
                  "Top:\n" + json.dumps([brief(r) for r in vids[:12]]) + "\nBottom:\n" + json.dumps([brief(r) for r in vids[-8:]]) +
                  '\nReturn JSON {"insights":[{"category":"title|length|hook|topic|format|cadence|other","insight":"","evidence":""}]} — 3 to 6.',
                  max_tokens=900)
    ins = out.get("insights", [])[:6]
    if ins:
        for o in db.select("playbook", {"source": "eq.analytics", "active": "is.true", "select": "id"}):
            db.update("playbook", {"id": f"eq.{o['id']}"}, {"active": False})
        db.insert("playbook", [{"source": "analytics", "category": i.get("category", "other"), "insight": i["insight"],
                                "evidence": {"note": i.get("evidence")}} for i in ins if i.get("insight")])
    return len(ins)

def main(db):
    rows, errs = [], []
    for name, fn in (("youtube", youtube), ("facebook", facebook)):
        try:
            rows += fn(db)
        except Exception as e:
            errs.append(f"{name}: {e}")
            db.alert("analytics", f"{name} pull failed: {e}", "warn")
    today = date.today().isoformat()
    for r in rows:
        r["captured_on"] = today
    # PostgREST bulk inserts need every row to have the same keys
    keys = {k for r in rows for k in r}
    rows = [{k: r.get(k) for k in keys} for r in rows]
    db.insert("metrics", rows, upsert=True, on_conflict="captured_on,platform,external_id")
    n = insights(db, rows)
    return f"saved {len(rows)} metric rows, {n} new insights" + (f"; errors: {errs}" if errs else "")
