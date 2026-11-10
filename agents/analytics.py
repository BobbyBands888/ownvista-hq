"""ANALYTICS agent — pulls our own YouTube + Facebook numbers daily and turns them into playbook
insights that Research and Maker read. (Research looks outward; this looks at us.)"""
import json
from datetime import date, datetime, timedelta, timezone
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

# ---------------- Scorecard: every post graded once at 48h ----------------
GRADE_AT_H = 48
MIN_HISTORY = 8          # graded posts of a format needed before grading against our own history
# floors from our page/channel so far, used until there's enough history (views at 48h)
FLOORS = {"reel": (30000, 10000, 1000), "short": (5000, 1000, 200), "episode": (2000, 500, 100)}
SC_FIELDS = "id,kind,case_name,title,description,script,part,posted_at,score_grade,score_views,leads(category,action_score)"

def _age_h(ts):
    t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    return (datetime.now(timezone.utc) - t).total_seconds() / 3600

def grade_of(v, kind, history):
    """A top 20% / B next 30% / C next 30% / D bottom 20% of this format's graded posts; floors until enough."""
    if len(history) >= MIN_HISTORY:
        below = sum(1 for h in history if h < v) / len(history)
        return "A" if below >= 0.8 else "B" if below >= 0.5 else "C" if below >= 0.2 else "D"
    a, b, c = FLOORS.get(kind, FLOORS["short"])
    return "A" if v >= a else "B" if v >= b else "C" if v >= c else "D"

def _post_brief(c):
    sc = c.get("script") if isinstance(c.get("script"), dict) else {}
    lead = c.get("leads") or {}
    cap = (c.get("description") or "").splitlines()[0][:160] if c["kind"] == "reel" else c.get("title")
    et = datetime.fromisoformat(str(c["posted_at"]).replace("Z", "+00:00")).astimezone(
        __import__("zoneinfo").ZoneInfo("America/New_York"))
    return {"grade": c.get("score_grade"), "views_48h": c.get("score_views"), "kind": c["kind"],
            "case": c.get("case_name"), "category": lead.get("category"), "caption_or_title": cap,
            "hook": sc.get("hook_text") or sc.get("on_screen_text"), "moment": sc.get("moment"),
            "posted_et": et.strftime("%a %-I%p")}

def scorecard(db, rows):
    views = {}
    for r in rows:
        if r.get("content_id") and r.get("views") is not None:
            views[r["content_id"]] = max(views.get(r["content_id"], 0), int(r["views"]))
    cut = (datetime.now(timezone.utc) - timedelta(hours=GRADE_AT_H)).isoformat()
    due = db.select("content", {"status": "eq.posted", "scored_at": "is.null", "posted_at": f"lte.{cut}",
                                "select": "id,kind,posted_at", "limit": 100})
    graded = []
    for c in due:
        age = _age_h(c["posted_at"])
        if c["id"] not in views:
            if age > 24 * 7:                    # deleted / never matched: stop waiting on it
                db.update("content", {"id": f"eq.{c['id']}"}, {"scored_at": datetime.now(timezone.utc).isoformat(),
                                                              "score_grade": "?", "score_note": "no metrics found"})
            continue
        v = views[c["id"]]
        # Analytics runs daily, so a post is read at 48-72h; scale late reads back toward 48h (conservative)
        v48 = int(v * GRADE_AT_H / age) if age > 60 else v
        hist = [h["score_views"] for h in db.select("content", {"kind": f"eq.{c['kind']}", "scored_at": "not.is.null",
                "score_grade": "neq.?", "select": "score_views", "order": "scored_at.desc", "limit": 50})
                if h.get("score_views") is not None]
        g = grade_of(v48, c["kind"], hist)
        db.update("content", {"id": f"eq.{c['id']}"}, {"score_grade": g, "score_views": v48,
                  "scored_at": datetime.now(timezone.utc).isoformat(),
                  "score_note": f"{v} views at {age:.0f}h" + (f", ~{v48} at 48h" if v48 != v else "")
                                + ("" if len(hist) >= MIN_HISTORY else " (graded on floors: little history yet)")})
        graded.append(g)
    if graded:
        lessons(db)
        db.alert("analytics", "Scorecard: graded " + ", ".join(f"{graded.count(x)} {x}" for x in "ABCD" if x in graded))
    return graded

def recent_graded(db, days=45, limit=40):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    return db.select("content", {"scored_at": "not.is.null", "score_grade": "in.(A,B,C,D)", "posted_at": f"gte.{since}",
                                 "select": SC_FIELDS, "order": "scored_at.desc", "limit": limit})

def lessons(db):
    """What our A posts share that our D posts don't -> scorecard playbook lines the Maker reads."""
    posts = recent_graded(db)
    win = [_post_brief(c) for c in posts if c["score_grade"] == "A"][:10]
    lose = [_post_brief(c) for c in posts if c["score_grade"] == "D"][:10]
    if len(win) + len(lose) < 3 or not (win and lose):
        return 0
    out = llm.ask("You grade Ten-Four Tapes' own posts. Compare our A posts with our D posts (views at 48h, graded "
                  "against the same format) and say what the winners do that the losers don't: caption/title wording, "
                  "hook, the moment chosen, case type, posting time. Only claims the examples support; name the "
                  "example in the evidence. No generic advice.",
                  "WINNERS (A):\n" + json.dumps(win) + "\n\nLOSERS (D):\n" + json.dumps(lose) +
                  '\n\nReturn JSON {"lessons":[{"category":"title|hook|topic|format|cadence|other","do":"what to do more of",'
                  '"avoid":"what to stop","evidence":"which posts show it"}]} — 2 to 5.', max_tokens=900)
    ls = [l for l in out.get("lessons", [])[:5] if l.get("do") or l.get("avoid")]
    if not ls:
        return 0
    for o in db.select("playbook", {"source": "eq.scorecard", "active": "is.true", "select": "id"}):
        db.update("playbook", {"id": f"eq.{o['id']}"}, {"active": False})
    db.insert("playbook", [{"source": "scorecard", "category": l.get("category") or "other",
                            "insight": "SCORECARD: " + " ".join(x for x in (
                                f"Do: {l['do']}." if l.get("do") else "", f"Avoid: {l['avoid']}." if l.get("avoid") else "") if x),
                            "evidence": {"note": l.get("evidence"), "winners": len(win), "losers": len(lose)}} for l in ls])
    return len(ls)

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
    try:
        g = scorecard(db, rows)
        sc = f", scorecard graded {len(g)}"
    except RuntimeError as e:
        if "score_" in str(e) or "column" in str(e):
            db.alert("analytics", "Scorecard needs its 4 new content columns — run the scorecard SQL in Supabase", "warn")
            sc = ", scorecard waiting on SQL"
        else:
            raise
    return f"saved {len(rows)} metric rows, {n} new insights{sc}" + (f"; errors: {errs}" if errs else "")
