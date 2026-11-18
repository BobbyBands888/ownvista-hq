"""Backlog: how many days of posts HQ has queued, per format, against the posting pace in Settings.

Queued = planned or rendered, not posted, not failed, not rejected, not failed by Compliance. Target is
settings.backlog_days (default 14). Maker reads this to decide how hard to plan and whether to re-cut winners;
the result is saved to settings.backlog for the dashboard and the daily report.
"""
from datetime import datetime, timezone

TARGET_DAYS = 14


def target(db):
    try:
        return max(1, int(db.setting("backlog_days", TARGET_DAYS)))
    except (TypeError, ValueError):
        return TARGET_DAYS


def pace(db):
    """Posts per day for each format, from the same settings the publisher uses."""
    def num(k, d):
        try:
            return float(db.setting(k, d))
        except (TypeError, ValueError):
            return float(d)
    return {"reel": num("reels_per_day", 3), "short": num("shorts_per_day", 3),
            "episode": num("episodes_per_week", 2) / 7}


def queued(db):
    rows = db.select("content", {"status": "in.(scripted,rendered)", "approval_status": "neq.rejected",
                                 "compliance_status": "neq.fail", "select": "kind", "limit": 2000})
    out = {"reel": 0, "short": 0, "episode": 0}
    for r in rows:
        if r["kind"] in out:
            out[r["kind"]] += 1
    return out


def status(db):
    t, p, q = target(db), pace(db), queued(db)
    st = {"target_days": t, "updated_at": datetime.now(timezone.utc).isoformat()}
    for k in ("reel", "short", "episode"):
        days = round(q[k] / p[k], 1) if p[k] > 0 else None
        st[k] = {"queued": q[k], "per_day": round(p[k], 2), "days": days,
                 "short_by": max(0, int(round(t * p[k])) - q[k])}
    return st


def save(db, st):
    try:
        db.insert("settings", {"key": "backlog", "value": st, "updated_at": st["updated_at"]},
                  upsert=True, on_conflict="key")
    except Exception:
        pass


def line(st):
    """One line for the daily report / run summary."""
    def d(k):
        v = st[k]["days"]
        return f"{v:g}" if v is not None else "–"
    return (f"Backlog (target {st['target_days']} days): Reels {d('reel')} days ({st['reel']['queued']}), "
            f"Shorts {d('short')} days ({st['short']['queued']}), episodes {d('episode')} days ({st['episode']['queued']})")
