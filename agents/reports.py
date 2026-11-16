"""REPORTS — the automated half of the weekly and monthly reviews in the operating-system doc.
  Friday 8am ET   -> weekly scoreboard + each new episode's 48-hour line (settings.report_weekly)
  First Monday    -> monthly trend table + top 3 / bottom 3 by watch hours, compared by tag (settings.report_monthly)
  Any day         -> alert when an episode beats 2x the median views in its first 48h, or looks ad-limited
The Overseer calls run_due() every hour; Analytics calls alerts() after its daily pull. Bobby makes the decisions."""
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from statistics import median
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
NOW = lambda: datetime.now(timezone.utc)

def _p(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

def _save(db, key, value):
    db.insert("settings", {"key": key, "value": value, "updated_at": NOW().isoformat()}, upsert=True, on_conflict="key")

def _snapshot(db, on_or_before):
    """Latest metric rows captured on or before a date, one per video."""
    rows = db.select("metrics", {"platform": "eq.youtube", "captured_on": f"lte.{on_or_before}",
                                 "order": "captured_on.desc", "limit": 1000})
    out = {}
    for r in rows:
        out.setdefault(r["external_id"], r)
    return out

def _pct(x):
    return "—" if x is None else f"{x * 100:.1f}%"

def _vs(v, med):
    if v is None or not med:
        return ""
    return " (above median)" if v >= med else " (below median)"

def _episodes(snap):
    return [r for k, r in snap.items() if k != "channel" and (r.get("raw") or {}).get("duration_s", 0) >= 120]

def _line(r):
    raw = r.get("raw") or {}
    ret = raw.get("retention") or {}
    return {"video": r["external_id"], "title": raw.get("title"), "views": r.get("views"), "ctr": raw.get("ctr"),
            "ret30": ret.get("retention_at_30s"), "avd_pct": (raw.get("avg_pct") or 0) / 100 if raw.get("avg_pct") is not None else None,
            "subs_per_1k": raw.get("subs_per_1k"), "watch_h": round((r.get("watch_minutes") or 0) / 60, 1),
            "published": raw.get("published"), "duration_s": raw.get("duration_s")}

def _med(lines, key):
    vals = [l[key] for l in lines if l.get(key) is not None]
    return median(vals) if vals else None

# ---------------- weekly (Fridays) ----------------
def weekly(db):
    today = date.today()
    now_snap, old_snap, older_snap = (_snapshot(db, today.isoformat()), _snapshot(db, (today - timedelta(days=7)).isoformat()),
                                      _snapshot(db, (today - timedelta(days=14)).isoformat()))
    ch, ch7, ch14 = now_snap.get("channel"), old_snap.get("channel"), older_snap.get("channel")
    views_wk = (ch["views"] - ch7["views"]) if ch and ch7 and ch.get("views") is not None and ch7.get("views") is not None else None
    views_prev = (ch7["views"] - ch14["views"]) if ch7 and ch14 and ch7.get("views") is not None and ch14.get("views") is not None else None
    try:
        from .analytics import _yta
        _, rows = _yta({"metrics": "estimatedMinutesWatched"})
        watch_h = round(rows[0][0] / 60) if rows else None
    except Exception:
        watch_h = None
    fb = db.select("metrics", {"platform": "eq.facebook", "external_id": "eq.page", "order": "captured_on.desc", "limit": 1})
    trend = ("up" if views_wk > views_prev * 1.1 else "down" if views_wk < views_prev * 0.9 else "flat") \
        if views_wk is not None and views_prev else "not enough history yet"
    eps = [_line(r) for r in _episodes(now_snap)]
    med = {k: _med(eps, k) for k in ("ctr", "ret30", "avd_pct", "subs_per_1k")}
    week_ago = NOW() - timedelta(days=7)
    new = [e for e in eps if e.get("published") and _p(e["published"]) >= week_ago - timedelta(days=2)]
    flags = []
    for e in new:
        if e["ctr"] is not None and e["ctr"] < 0.03:
            flags.append(f"{e['title']}: CTR {_pct(e['ctr'])} is under 3%. Swap the thumbnail today.")
        if e["ret30"] is not None and e["ret30"] < 0.55:
            flags.append(f"{e['title']}: 0:30 retention {_pct(e['ret30'])} is under 55%. Fix the next episode's open.")
    lines = ["Ten-Four Tapes — weekly scoreboard (" + f"{datetime.now(ET):%b %d}" + ")", "",
             f"YouTube subscribers: {ch.get('followers') if ch else '—'}",
             f"Watch hours, last 365 days: {watch_h if watch_h is not None else '—'} (Partner Program needs 4,000)",
             f"Views this week: {views_wk if views_wk is not None else '—'} vs last week: {views_prev if views_prev is not None else '—'} — {trend}",
             f"Facebook followers: {fb[0].get('followers') if fb else '—'}", "",
             "New episodes at 48 hours (vs our median):"]
    for e in new or []:
        lines.append(f"- {e['title']}: CTR {_pct(e['ctr'])}{_vs(e['ctr'], med['ctr'])}, 0:30 retention {_pct(e['ret30'])}"
                     f"{_vs(e['ret30'], med['ret30'])}, AVD {_pct(e['avd_pct'])}{_vs(e['avd_pct'], med['avd_pct'])}, "
                     f"{e['subs_per_1k'] if e['subs_per_1k'] is not None else '—'} subs per 1K views")
    if not new:
        lines.append("- none posted this week")
    if flags:
        lines += ["", "Act on today:"] + [f"- {f}" for f in flags]
    log = (db.setting("retention_log", []) or [])[:3]
    if log:
        lines += ["", "Retention log (newest):"] + [
            f"- {l['title']}: biggest drop at {(l.get('biggest_drop') or {}).get('second', '—')}s, "
            f"biggest spike at {(l.get('biggest_spike') or {}).get('second', '—')}s" for l in log]
    lines += ["", "Your 30 minutes starts at step 2 of the weekly review."]
    rep = {"period": today.isocalendar()[:2], "generated_at": NOW().isoformat(), "text": "\n".join(lines),
           "new_episodes": new, "medians": med, "flags": flags}
    _save(db, "report_weekly", rep)
    db.alert("reports", f"Weekly scoreboard ready — {len(new)} new episodes, {len(flags)} things to act on")
    return rep

# ---------------- monthly (first Monday) ----------------
def _month_bounds(today):
    first = today.replace(day=1)
    last_end = first - timedelta(days=1)
    return first, last_end.replace(day=1), last_end

def _tags_by_video(db):
    out = {}
    for c in db.select("content", {"kind": "eq.episode", "youtube_id": "not.is.null", "select": "youtube_id,script", "limit": 500}):
        sc = c.get("script") if isinstance(c.get("script"), dict) else {}
        if sc.get("analysis_tags"):
            out[c["youtube_id"]] = sc["analysis_tags"]
    return out

def _length_bucket(s):
    m = (s or 0) / 60
    return "under 15 min" if m < 15 else "15–25 min" if m <= 25 else "25+ min"

def monthly(db):
    today = date.today()
    first, prev_first, prev_end = _month_bounds(today)
    now_snap, prev_snap, prev2_snap = _snapshot(db, (first - timedelta(days=1)).isoformat()), \
        _snapshot(db, (prev_first - timedelta(days=1)).isoformat()), _snapshot(db, ((prev_first - timedelta(days=1)).replace(day=1) - timedelta(days=1)).isoformat())
    def ch(snap):
        return (snap.get("channel") or {}).get("followers")
    subs_gain = (ch(now_snap) - ch(prev_snap)) if ch(now_snap) is not None and ch(prev_snap) is not None else None
    subs_prev = (ch(prev_snap) - ch(prev2_snap)) if ch(prev_snap) is not None and ch(prev2_snap) is not None else None
    def month_eps(snap, start, end):
        return [_line(r) for r in _episodes(snap) if r.get("raw", {}).get("published")
                and start <= _p(r["raw"]["published"]).date() <= end]
    this_eps = month_eps(now_snap, prev_first, prev_end)
    last_start = (prev_first - timedelta(days=1)).replace(day=1)
    last_eps = month_eps(prev_snap, last_start, prev_first - timedelta(days=1))
    try:
        from .analytics import _yta
        def wh(a, b):
            _, rows = _yta({"metrics": "estimatedMinutesWatched", "startDate": a.isoformat(), "endDate": b.isoformat()})
            return round(rows[0][0] / 60) if rows else None
        wh_now, wh_prev = wh(prev_first, prev_end), wh(last_start, prev_first - timedelta(days=1))
    except Exception:
        wh_now = wh_prev = None
    money_rows = [r for r in now_snap.values() if (r.get("raw") or {}).get("rpm") is not None]
    rpm = median([r["raw"]["rpm"] for r in money_rows]) if money_rows else None
    chg = lambda a, b: "—" if a is None or b in (None, 0) else f"{(a - b) / abs(b) * 100:+.0f}%"
    trend = [
        ("Subscribers gained", subs_gain, subs_prev, "+25%/month"),
        ("Watch hours (month)", wh_now, wh_prev, "stage target"),
        ("Median CTR, new episodes", _med(this_eps, "ctr"), _med(last_eps, "ctr"), "4%+"),
        ("Median AVD %, new episodes", _med(this_eps, "avd_pct"), _med(last_eps, "avd_pct"), "35%+"),
        ("Returning viewers", None, None, "rising (read in Studio)"),
        ("RPM (once in YPP)", rpm, None, "$5+"),
    ]
    # pattern finding: top 3 vs bottom 3 by watch hours, by tag
    tags = _tags_by_video(db)
    ranked = sorted(this_eps, key=lambda e: -(e["watch_h"] or 0))
    for e in ranked:
        e["tags"] = {**tags.get(e["video"], {}), "length": _length_bucket(e["duration_s"])}
    top, bottom = ranked[:3], ranked[-3:] if len(ranked) >= 6 else []
    patterns = []
    if top and bottom:
        top_c = Counter((k, v) for e in top for k, v in e["tags"].items() if v)
        bot = {(k, v) for e in bottom for k, v in e["tags"].items() if v}
        patterns = [f"{k.replace('_', ' ')}: {v}" for (k, v), n in top_c.items() if n >= 2 and (k, v) not in bot]
    fmt = lambda name, v: "—" if v is None else (_pct(v) if "CTR" in name or "AVD" in name else f"${v:.2f}" if "RPM" in name else str(v))
    lines = [f"Ten-Four Tapes — monthly review for {prev_first:%B %Y}", "", "Trend check:"]
    lines += [f"- {n}: {fmt(n, a)} (last month {fmt(n, b)}, change {chg(a, b)}; target {t})" for n, a, b, t in trend]
    lines += ["", "Top 3 by watch hours:"] + [f"- {e['title']} — {e['watch_h']} h — " + ", ".join(f"{v}" for v in e["tags"].values() if v) for e in top]
    if bottom:
        lines += ["", "Bottom 3:"] + [f"- {e['title']} — {e['watch_h']} h — " + ", ".join(f"{v}" for v in e["tags"].values() if v) for e in bottom]
    lines += ["", "Patterns (in 2+ of the top 3, none of the bottom 3):"] + ([f"- {p}" for p in patterns] or
              ["- none yet" + ("" if len(ranked) >= 6 else f" (needs 6+ episodes in the month; had {len(ranked)})")])
    lines += ["", "You make the 3 decisions for next month."]
    rep = {"period": f"{prev_first:%Y-%m}", "generated_at": NOW().isoformat(), "text": "\n".join(lines),
           "trend": [{"metric": n, "this": a, "last": b, "target": t} for n, a, b, t in trend],
           "top": top, "bottom": bottom, "patterns": patterns}
    _save(db, "report_monthly", rep)
    db.alert("reports", f"Monthly review for {prev_first:%B} ready — {len(patterns)} patterns found")
    return rep

# ---------------- any-day alerts (called by Analytics after its daily pull) ----------------
def alerts(db, rows):
    done = set(db.setting("report_alerted", []) or [])
    yt = [r for r in rows if r["platform"] == "youtube" and r["external_id"] != "channel" and r.get("views") is not None]
    long_form = [r for r in yt if (r["raw"].get("duration_s") or 0) >= 120]
    graded = [h["score_views"] for h in db.select("content", {"kind": "eq.episode", "score_grade": "in.(A,B,C,D)",
              "select": "score_views", "limit": 50}) if h.get("score_views") is not None]
    med = median(graded) if len(graded) >= 3 else (median([r["views"] for r in long_form]) if len(long_form) >= 3 else None)
    fired = 0
    for r in long_form:
        age_h = (NOW() - _p(r["raw"]["published"])).total_seconds() / 3600
        key = f"hot:{r['external_id']}"
        if med and age_h <= 72 and key not in done and r["views"] >= 2 * med:
            db.alert("reports", f"\"{r['raw'].get('title')}\" has {r['views']} views in {age_h:.0f}h, over 2x our median "
                     f"({int(med)}). Make a Short and 2 Reels from its best moment now.", "urgent")
            done.add(key)
            fired += 1
        # ad-limited proxy: once monetized, a video whose ads run on under 30% of plays after 48h
        mp, key2 = r["raw"].get("monetized_playbacks"), f"ads:{r['external_id']}"
        if mp is not None and age_h >= 48 and r["views"] >= 200 and mp / r["views"] < 0.3 and key2 not in done:
            db.alert("reports", f"\"{r['raw'].get('title')}\" shows ads on only {mp / r['views']:.0%} of plays — check Studio "
                     "for a yellow icon and request human review if so.", "urgent")
            done.add(key2)
            fired += 1
    _save(db, "report_alerted", sorted(done)[-300:])
    return fired

# ---------------- schedule (Overseer calls this hourly) ----------------
def run_due(db):
    now = datetime.now(ET)
    out = []
    if now.weekday() == 4 and now.hour >= 8:
        last = db.setting("report_weekly") or {}
        if list(last.get("period") or []) != list(date.today().isocalendar()[:2]):
            weekly(db)
            out.append("weekly scoreboard")
    if now.weekday() == 0 and now.day <= 7 and now.hour >= 8:
        last = db.setting("report_monthly") or {}
        if last.get("period") != f"{_month_bounds(date.today())[1]:%Y-%m}":
            monthly(db)
            out.append("monthly review")
    return out
