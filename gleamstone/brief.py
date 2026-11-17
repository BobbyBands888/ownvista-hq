"""DAILY BRIEF (8am ET) and CLEANER RECRUITING (weekly)."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from agents.lib import llm
from . import common as c

ET = ZoneInfo("America/New_York")
AGENTS = ["gs_scout", "gs_map", "gs_enrich", "gs_writer", "gs_sender", "gs_recruit"]


def _n(db, table, filt):
    return len(db.select(table, {**filt, "select": "id", "limit": 2000}))


def build(db):
    since = (c.now() - timedelta(hours=24)).isoformat()
    week = (c.now() - timedelta(days=7)).isoformat()
    lines = [f"Gleamstone — {datetime.now(ET):%A, %b %d}", ""]
    waiting = _n(db, "gs_emails", {"approval_status": "eq.pending", "status": "eq.draft"})
    hot = db.select("gs_prospects", {"status": "in.(interested,replied)", "select": "name,town,status", "limit": 10})
    lines += [f"Emails waiting for your OK: {waiting}",
              f"Sent yesterday: {_n(db, 'gs_emails', {'status': 'eq.sent', 'sent_at': f'gte.{since}'})} · "
              f"this week: {_n(db, 'gs_emails', {'status': 'eq.sent', 'sent_at': f'gte.{week}'})}",
              f"New prospects yesterday: {_n(db, 'gs_prospects', {'created_at': f'gte.{since}'})} · "
              f"ready to email: {_n(db, 'gs_prospects', {'status': 'eq.new', 'email': 'not.is.null'})}",
              f"Open quotes: {_n(db, 'gs_quotes', {'status': 'in.(draft,sent)'})} · "
              f"Clients: {_n(db, 'gs_prospects', {'status': 'eq.won'})}",
              f"Cleaners ready or active: {_n(db, 'gs_cleaners', {'status': 'in.(ready,active)'})}"]
    if hot:
        lines += ["", "Talk to these first:"] + [f"- {h['name']} ({h['town'] or ''}) — {h['status']}" for h in hot]
    broken = []
    for a in AGENTS:
        r = db.select("agent_runs", {"agent": f"eq.{a}", "order": "started_at.desc", "limit": 1})
        if r and r[0]["status"] == "error":
            broken.append(a.replace("gs_", ""))
    if broken:
        lines += ["", "Agents with errors: " + ", ".join(broken)]
    lines += ["", "Dashboard: https://levelingclips.com/gleamstone"]
    return "\n".join(lines)


def main(db):
    now_et = datetime.now(ET)
    last = db.setting("gs_brief", {}) or {}
    if now_et.hour < 8 or (last.get("date") == now_et.date().isoformat()):
        return "not time yet"
    text = build(db)
    db.insert("settings", {"key": "gs_brief", "value": {"date": now_et.date().isoformat(), "text": text,
                                                        "generated_at": c.now().isoformat()},
                           "updated_at": c.now()}, upsert=True, on_conflict="key")
    emailed = False
    if c.brevo_key():
        try:
            c.send(c.SENDER_EMAIL, f"Gleamstone brief — {now_et:%b %d}", text)
            emailed = True
        except Exception as e:
            db.alert("gs_brief", f"brief email failed: {str(e)[:150]}", "info")
    return "brief built" + (" and emailed" if emailed else "")


JOB = c.RULES + """

Write a short job post to find part-time commercial cleaners for Gleamstone Commercial Cleaning.
- Evening/early-morning shifts cleaning offices, medical suites and showrooms north of Boston
  (Woburn, Burlington, Winchester, Reading, Wakefield, Stoneham, Medford, Lexington and nearby).
- Ask for: reliable, has a car or a dependable ride, can pass a background check, experience a plus but will train.
- How to apply: email bobby@gleamstonecleaning.com with name, towns you can reach, which evenings you're free,
  and any cleaning experience. No phone calls, no phone number.
- Don't invent a pay rate, benefits or hours that aren't given. If a pay line is given, include it as written.
- Under 170 words. Plain text. A title line first.
Return JSON {"title":"...","body":"..."}"""


def recruit(db):
    pay = (db.setting("gs_pay_line", "") or "").strip()
    res = llm.ask(JOB, f"Pay line: {pay or '(none given — leave pay out)'}", max_tokens=800, temperature=0.5) or {}
    if not res.get("body"):
        raise RuntimeError("job post came back empty")
    db.insert("settings", {"key": "gs_job_post", "value": {"title": res.get("title", "Part-time evening commercial cleaner"),
                                                           "body": res["body"], "generated_at": c.now().isoformat()},
                           "updated_at": c.now()}, upsert=True, on_conflict="key")
    return "fresh job post written"
