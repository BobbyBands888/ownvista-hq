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

# ---------------- deeper YouTube numbers (packaging, traffic, retention, money) ----------------
YTA = "https://youtubeanalytics.googleapis.com/v2/reports"
DEEP_DAYS = 60            # traffic + retention are pulled for videos published in the last 60 days
RETENTION_MIN_S = 120     # long-form only; Shorts curves are too short to read

def _yta(params):
    """One YouTube Analytics report. Returns (columns, rows) or raises with YouTube's own message."""
    end = date.today()
    base = {"ids": "channel==MINE", "startDate": (end - timedelta(days=365)).isoformat(), "endDate": end.isoformat()}
    r = requests.get(YTA, headers={"Authorization": f"Bearer {access_token('youtube')}"}, params={**base, **params}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"YouTube Analytics {r.status_code}: {r.text[:200]}")
    j = r.json()
    return [c["name"] for c in j.get("columnHeaders", [])], j.get("rows", [])

def _by_video(metrics):
    cols, rows = _yta({"metrics": metrics, "dimensions": "video", "sort": "-views" if "views" in metrics else None,
                       "maxResults": 200})
    return {row[0]: dict(zip(cols[1:], row[1:])) for row in rows}

def packaging(ids):
    """Impressions + click-through rate per video. YouTube only exposes these for some channels; if it refuses,
    the weekly review reads them from Studio instead (the doc's fallback)."""
    try:
        return _by_video("views,videoThumbnailImpressions,videoThumbnailImpressionsClickRate"), None
    except Exception as e:
        return {}, str(e)[:160]

def money():
    """Revenue, RPM and monetized playbacks — only works after the channel is in the Partner Program."""
    try:
        return _by_video("views,estimatedRevenue,rpm,monetizedPlaybacks"), None
    except Exception as e:
        return {}, str(e)[:160]

def traffic(vid):
    cols, rows = _yta({"metrics": "views", "dimensions": "insightTrafficSourceType", "filters": f"video=={vid}",
                       "sort": "-views"})
    total = sum(r[1] for r in rows) or 0
    return {r[0]: {"views": r[1], "share": round(r[1] / total, 3) if total else 0} for r in rows}

def retention(vid, duration_s):
    """Audience retention curve (100 points). Finds the biggest drop and biggest spike and the second they happen."""
    cols, rows = _yta({"metrics": "audienceWatchRatio,relativeRetentionPerformance",
                       "dimensions": "elapsedVideoTimeRatio", "filters": f"video=={vid};audienceType==ORGANIC"})
    pts = sorted((r[0], r[1], r[2] if len(r) > 2 else None) for r in rows)
    if len(pts) < 10:
        return None
    sec = lambda ratio: int(ratio * duration_s)
    # skip the first 3% — every video loses people in the opening seconds, that's not a "cliff"
    steps = [(pts[i][0], pts[i][1] - pts[i - 1][1]) for i in range(1, len(pts)) if pts[i][0] > 0.03]
    drop = min(steps, key=lambda s: s[1]) if steps else None
    spike = max(steps, key=lambda s: s[1]) if steps else None
    at30 = next((p[1] for p in pts if sec(p[0]) >= 30), None)
    rel = [p[2] for p in pts if p[2] is not None]
    return {"retention_at_30s": round(at30, 3) if at30 is not None else None,
            "biggest_drop": {"second": sec(drop[0]), "change": round(drop[1], 3)} if drop and drop[1] < 0 else None,
            "biggest_spike": {"second": sec(spike[0]), "change": round(spike[1], 3)} if spike and spike[1] > 0 else None,
            "relative_retention": round(sum(rel) / len(rel), 3) if rel else None}

def deepen(db, rows):
    """Adds packaging, traffic, retention, subs/1K and money to the YouTube rows (stored in metrics.raw)."""
    from .lib.google import iso_duration_to_s
    vids = [r for r in rows if r["platform"] == "youtube" and r["external_id"] != "channel"]
    if not vids:
        return []
    notes = []
    pack, perr = packaging([r["external_id"] for r in vids])
    cash, _ = money()
    if perr:
        notes.append("impressions/CTR not exposed by YouTube for us yet — read them from Studio in the weekly review")
    cutoff = datetime.now(timezone.utc) - timedelta(days=DEEP_DAYS)
    log = db.setting("retention_log", []) or []
    logged = {e["video"] for e in log}
    deep_calls = 0
    for r in vids:
        raw, vid = r["raw"], r["external_id"]
        p = pack.get(vid, {})
        if p:
            raw["impressions"] = p.get("videoThumbnailImpressions")
            ctr = p.get("videoThumbnailImpressionsClickRate")
            raw["ctr"] = round(ctr / 100, 4) if ctr is not None else None   # API gives a percent (4.5 = 4.5%)
        c = cash.get(vid, {})
        if c:
            raw.update({"revenue": c.get("estimatedRevenue"), "rpm": c.get("rpm"), "monetized_playbacks": c.get("monetizedPlaybacks")})
        if r.get("views"):
            raw["subs_per_1k"] = round(1000 * (raw.get("subs") or 0) / r["views"], 2)
        published = datetime.fromisoformat(raw["published"].replace("Z", "+00:00"))
        dur = iso_duration_to_s(raw.get("duration") or "PT0S")
        raw["duration_s"] = dur
        if published < cutoff or deep_calls >= 30:          # keep within the free API quota
            continue
        try:
            raw["traffic"] = traffic(vid)
            deep_calls += 1
            if dur >= RETENTION_MIN_S and (r.get("views") or 0) >= 50:
                ret = retention(vid, dur)
                deep_calls += 1
                if ret:
                    raw["retention"] = ret
                    age_d = (datetime.now(timezone.utc) - published).days
                    if vid not in logged and age_d >= 2:     # one log line per episode, once it has 48h of data
                        log.insert(0, {"video": vid, "title": raw.get("title"), "logged_on": date.today().isoformat(), **ret})
                        logged.add(vid)
        except Exception as e:
            notes.append(f"{vid}: {str(e)[:100]}")
    db.insert("settings", {"key": "retention_log", "value": log[:100], "updated_at": datetime.now(timezone.utc).isoformat()},
              upsert=True, on_conflict="key")
    return notes

def _fb_page_token():
    """The Page's own token. The FB_PAGE_TOKEN secret has held Bobby's personal token since Nov 16; with that, every
    Page call errors and the Facebook half of analytics went silently empty. Swap it like the publisher does."""
    tok, page = (config.FB_PAGE_TOKEN or "").strip(), (config.FB_PAGE_ID or "").strip()
    me = requests.get(FB + "me", params={"fields": "id", "access_token": tok}, timeout=30).json()
    if "error" in me:
        raise RuntimeError(f"Facebook token: {me['error'].get('message', '')[:200]}")
    if str(me.get("id")) != page:
        r = requests.get(FB + page, params={"fields": "access_token", "access_token": tok}, timeout=30).json()
        if not r.get("access_token"):
            raise RuntimeError(f"Facebook token is not the Page's and can't get the Page's token: {str(r)[:200]}")
        tok = r["access_token"]
    return tok


def _fb_get(path, params):
    j = requests.get(FB + path, params=params, timeout=30).json()
    if isinstance(j, dict) and "error" in j:
        raise RuntimeError(f"Facebook {path}: {j['error'].get('message', '')[:200]}")
    return j


def facebook(db):
    if not (config.FB_PAGE_ID and config.FB_PAGE_TOKEN):
        return []
    pid = config.FB_PAGE_ID.strip()
    tok = {"access_token": _fb_page_token()}
    rows = []
    page = _fb_get(pid, {**tok, "fields": "followers_count,fan_count"})
    rows.append({"platform": "facebook", "external_id": "page", "followers": page.get("followers_count"), "raw": page})
    reels = _fb_get(f"{pid}/video_reels", {**tok, "fields": "id,description,created_time", "limit": 50}).get("data", [])
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
                       "avg_view_pct": r["raw"].get("avg_pct"), "ctr": r["raw"].get("ctr"),
                       "subs_per_1k": r["raw"].get("subs_per_1k"),
                       "top_traffic": max((r["raw"].get("traffic") or {"?": {"share": 0}}).items(), key=lambda t: t[1]["share"])[0]}
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
    deep = []
    try:
        deep = deepen(db, rows)
    except Exception as e:
        errs.append(f"deep youtube: {e}")
    today = date.today().isoformat()
    for r in rows:
        r["captured_on"] = today
    # PostgREST bulk inserts need every row to have the same keys
    keys = {k for r in rows for k in r}
    rows = [{k: r.get(k) for k in keys} for r in rows]
    db.insert("metrics", rows, upsert=True, on_conflict="captured_on,platform,external_id")
    n = insights(db, rows)
    from . import reports
    try:
        fired = reports.alerts(db, rows)
    except Exception as e:
        fired, errs = 0, errs + [f"alerts: {e}"]
    try:
        g = scorecard(db, rows)
        sc = f", scorecard graded {len(g)}"
    except RuntimeError as e:
        if "score_" in str(e) or "column" in str(e):
            db.alert("analytics", "Scorecard needs its 4 new content columns — run the scorecard SQL in Supabase", "warn")
            sc = ", scorecard waiting on SQL"
        else:
            raise
    return (f"saved {len(rows)} metric rows, {n} new insights{sc}, {fired} alerts"
            + (f"; notes: {deep[:3]}" if deep else "") + (f"; errors: {errs}" if errs else ""))
