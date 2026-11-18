"""OVERSEER agent — makes sure every other agent is alive and working, retries failures once,
watches the pipeline for jams, and emails Bobby one daily report (8am ET)."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from .lib.google import send_email
from .lib import config

# agent -> max hours between successful runs before it's considered down
EXPECTED = {"research": 26, "scout": 4, "outreach": 74, "tracker": 3, "casefacts": 7, "maker": 13,
            "compliance": 2, "analytics": 26, "publisher": 6}
STUCK_H = {"publisher": 5}      # a publisher run renders for up to ~5h; other agents finish within minutes
ET = ZoneInfo("America/New_York")
DASH = "https://levelingclips.com"

def _now():
    return datetime.now(timezone.utc)

def _p(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))

def health(db, retry):
    problems = []
    for agent, hrs in EXPECTED.items():
        runs = db.select("agent_runs", {"agent": f"eq.{agent}", "order": "started_at.desc", "limit": 3})
        for r in runs:
            if r["status"] == "running" and _now() - _p(r["started_at"]) > timedelta(hours=STUCK_H.get(agent, 1)):
                db.update("agent_runs", {"id": f"eq.{r['id']}"}, {"status": "error", "error": "timed out / killed"})
                r["status"] = "error"
        ok = [r for r in runs if r["status"] == "ok"]
        last_ok = _p(ok[0]["started_at"]) if ok else None
        if runs and runs[0]["status"] == "error" and len(runs) > 1 and runs[1]["status"] == "error":
            problems.append(f"{agent}: failed twice in a row — {(runs[0].get('error') or '')[-160:]}")
            db.alert("overseer", f"{agent} failed twice in a row", "urgent")
        elif runs and runs[0]["status"] == "error" and agent in retry:
            retry[agent]()  # one immediate retry
        if last_ok is None or _now() - last_ok > timedelta(hours=hrs):
            if agent == "publisher":
                problems.append("publisher: no run in 6h — is the Mac awake and online with the GitHub runner on?")
                day = (_now() - timedelta(hours=24)).isoformat()
                if not db.select("alerts", {"agent": "eq.overseer", "message": "like.Publisher hasn*",
                                            "created_at": f"gte.{day}", "select": "id"}):   # once a day, not every tick
                    db.alert("overseer", "Publisher hasn't run in 6h: nothing renders or posts. Is the Mac awake and online?",
                             "urgent")
            elif runs or last_ok:
                problems.append(f"{agent}: no successful run in {hrs}h")
    return problems

def jams(db):
    j = []
    waiting = db.select("leads", {"status": "eq.new", "select": "agency_name", "limit": 500})
    if len(waiting) > 25:
        j.append(f"{len(waiting)} good leads waiting — most likely missing agency records emails (add on dashboard)")
    appr = db.select("content", {"approval_status": "eq.pending", "compliance_status": "eq.pass", "select": "id"})
    if appr:
        j.append(f"{len(appr)} item(s) waiting for your approval")
    fees = db.select("records_requests", {"status": "eq.fee_quoted", "select": "subject,fee_quote"})
    for f in fees[:5]:
        j.append(f"Fee quote (unpaid): {f['subject'][:60]} — {f['fee_quote']}")
    clar = db.select("records_requests", {"status": "eq.clarify", "select": "subject"})
    for c in clar[:5]:
        j.append(f"Agency asked a question: {c['subject'][:60]}")
    return j

def count(db, table, filt):
    return len(db.select(table, {**filt, "select": "id", "limit": 1000}))

def daily_report(db, problems, jam):
    since = (_now() - timedelta(hours=24)).isoformat()
    lines = [
        "Ten-Four Tapes HQ — daily report", "",
        f"New leads kept: {count(db, 'leads', {'created_at': f'gte.{since}', 'status': 'in.(new,obtained)'})}",
        f"Records requests sent: {count(db, 'records_requests', {'sent_at': f'gte.{since}'})}",
        f"Footage received (open): {count(db, 'leads', {'status': 'eq.obtained'})}",
        f"Videos planned: {count(db, 'content', {'created_at': f'gte.{since}'})}",
        f"Posted: {count(db, 'content', {'posted_at': f'gte.{since}'})}",
    ]
    try:
        from . import backlog
        lines.append(backlog.line(backlog.status(db)))
    except Exception:
        pass
    lines.append("")
    m = db.select("metrics", {"external_id": "in.(channel,page)", "order": "captured_on.desc", "limit": 4})
    for r in m[:2]:
        lines.append(f"{r['platform'].title()}: {r.get('followers') or 0} followers" +
                     (f", {r['views']} total views" if r.get("views") else ""))
    if jam:
        lines += ["", "Needs you:"] + [f"- {x}" for x in jam]
    if problems:
        lines += ["", "Agent problems:"] + [f"- {x}" for x in problems]
    alerts = db.select("alerts", {"resolved": "is.false", "level": "eq.urgent", "agent": "not.like.gs_*",
                                  "order": "created_at.desc", "limit": 8})
    if alerts:
        lines += ["", "Urgent:"] + [f"- [{a['agent']}] {a['message'][:200]}" for a in alerts]
    lines += ["", f"Dashboard: {DASH}"]
    send_email(config.REPORT_TO, f"Ten-Four Tapes daily report — {datetime.now(ET):%b %d}", "\n".join(lines))

def make_main(retry):
    def main(db):
        problems = health(db, retry)
        jam = jams(db)
        now_et = datetime.now(ET)
        sent = False
        if 7 <= now_et.hour <= 11:       # ticks don't land on a fixed minute; first one after 7am ET sends it
            already = db.select("agent_runs", {"agent": "eq.overseer", "summary": "like.*report sent*",
                                               "started_at": f"gte.{(_now() - timedelta(hours=20)).isoformat()}"})
            if not already:
                daily_report(db, problems, jam)
                sent = True
        from . import reports
        try:
            made = reports.run_due(db)
        except Exception as e:
            made = []
            db.alert("reports", f"weekly/monthly report failed: {str(e)[:200]}", "warn")
        return (f"{len(problems)} agent problems, {len(jam)} items need Bobby" + ("; report sent" if sent else "")
                + (f"; built {', '.join(made)}" if made else ""))
    return main
