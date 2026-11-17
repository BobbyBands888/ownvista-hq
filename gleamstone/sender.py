"""SENDER — sends approved Gleamstone emails from bobby@gleamstonecleaning.com (Brevo free tier).
- Weekdays 8am–5pm ET only, a few per hour so it looks like a person, never more than the daily cap.
- Approving an intro approves its two short follow-ups (day 4 and day 9). They stop the moment the prospect
  replies, bounces, or is marked do-not-contact.
- Won't send anything until a mailing address is set (US anti-spam law requires one in every cold email).
- Bounces and spam complaints from Brevo mark the prospect so they're never emailed again."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import common as c

ET = ZoneInfo("America/New_York")
PER_RUN = 4

FOLLOW = {
    1: "Hi{name},\n\nJust following up on my note about cleaning for {biz}. If you send me the rough square footage "
       "and how often you'd want service, I'll put together a flat monthly quote. Would that help?",
    2: "Hi{name},\n\nLast note from me on this. If cleaning comes up for {biz} down the road, this is the best "
       "address to reach me. Is there someone else there who handles it that I should email instead?",
}


def _sent_today(db):
    start = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
    return len(db.select("gs_emails", {"status": "eq.sent", "sent_at": f"gte.{start.isoformat()}", "select": "id",
                                       "limit": 1000}))


def _bounces(db):
    hit = 0
    for ev in ("hardBounces", "spam", "blocked", "unsubscribed"):
        for e in c.brevo_events(ev, days=3):
            addr = (e.get("email") or "").lower()
            if not addr:
                continue
            rows = db.select("gs_prospects", {"email": f"eq.{addr}",
                                              "status": "not.in.(do_not_contact,replied,interested,quoted,won)"})
            for p in rows:
                if ev == "hardBounces":
                    db.update("gs_prospects", {"id": f"eq.{p['id']}"},
                              {"email": None, "status": "no_email", "enrich_tries": 2, "notes": f"{addr} bounced"})
                else:
                    db.update("gs_prospects", {"id": f"eq.{p['id']}"}, {"status": "do_not_contact"})
                db.update("gs_emails", {"prospect_id": f"eq.{p['id']}", "status": "eq.draft"},
                          {"status": "cancelled", "note": ev})
                hit += 1
    return hit


def _queue_followup(db, sent, prospect):
    step = sent["step"] + 1
    if sent["kind"] not in ("intro", "followup") or step > 2:
        return
    days = (db.setting("gs_followup_days", [4, 9]) or [4, 9])
    gap = days[0] if step == 1 else max(1, days[1] - days[0])
    first = (prospect.get("contact_name") or "").split(" ")[0]
    subj = sent["subject"] if sent["subject"].lower().startswith("re:") else "Re: " + sent["subject"]
    db.insert("gs_emails", {"prospect_id": prospect["id"], "kind": "followup", "step": step,
                            "to_email": sent["to_email"], "subject": subj,
                            "body": FOLLOW[step].format(name=(" " + first) if first else " there", biz=prospect["name"]),
                            "approval_status": sent["approval_status"],
                            "send_after": (c.now() + timedelta(days=gap)).isoformat(),
                            "note": f"in-reply-to:{sent.get('provider_id') or ''}"})


def main(db):
    bounced = _bounces(db)
    now_et = datetime.now(ET)
    if db.setting("gs_sending_paused", False):
        return f"sending paused; {bounced} bounces/opt-outs handled"
    if now_et.weekday() >= 5 or not (8 <= now_et.hour < 17):
        return f"outside sending hours; {bounced} bounces/opt-outs handled"
    if not c.brevo_key():
        last = db.select("alerts", {"agent": "eq.gs_sender", "resolved": "is.false", "message": "like.*Brevo*", "limit": 1})
        if not last:
            db.alert("gs_sender", "Emails are ready but can't go out yet: Brevo isn't set up. Finish the Brevo step and they'll start sending.", "warn")
        return "waiting on Brevo setup"
    if not (db.setting("gs_mailing_address", "") or "").strip():
        last = db.select("alerts", {"agent": "eq.gs_sender", "resolved": "is.false", "message": "like.*mailing address*", "limit": 1})
        if not last:
            db.alert("gs_sender", "Add a business mailing address in Gleamstone Settings. Cold emails legally need one, so nothing sends until it's there.", "warn")
        return "waiting on a mailing address"
    cap = int(db.setting("gs_daily_cap", 15) or 15)
    room = min(PER_RUN, cap - _sent_today(db))
    if room <= 0:
        return f"daily cap of {cap} reached"
    rows = db.select("gs_emails", {"direction": "eq.out", "status": "eq.draft", "approval_status": "eq.approved",
                                   "or": f"(send_after.is.null,send_after.lte.{c.now().isoformat()})",
                                   "order": "step.desc,created_at.asc", "limit": room * 3})
    sent = failed = 0
    for e in rows:
        if sent >= room:
            break
        p = db.select("gs_prospects", {"id": f"eq.{e['prospect_id']}"}) if e.get("prospect_id") else []
        p = p[0] if p else None
        if not p or not e.get("to_email"):
            db.update("gs_emails", {"id": f"eq.{e['id']}"}, {"status": "cancelled", "note": "no prospect/email"})
            continue
        if p["status"] in c.STOP_STATUSES and e["kind"] != "reply" and e["kind"] != "quote":
            db.update("gs_emails", {"id": f"eq.{e['id']}"}, {"status": "cancelled", "note": f"prospect is {p['status']}"})
            continue
        if p["status"] == "do_not_contact":
            db.update("gs_emails", {"id": f"eq.{e['id']}"}, {"status": "cancelled", "note": "do not contact"})
            continue
        body = c.strip_footer(e["body"]) + "\n" + c.footer(db)
        ref = (e.get("note") or "").split("in-reply-to:")[-1].strip() if "in-reply-to:" in (e.get("note") or "") else None
        try:
            mid = c.send(e["to_email"], e["subject"], body, reply_to_id=ref or None)
        except Exception as ex:
            db.update("gs_emails", {"id": f"eq.{e['id']}"}, {"status": "failed", "note": str(ex)[:300]})
            failed += 1
            continue
        db.update("gs_emails", {"id": f"eq.{e['id']}"}, {"status": "sent", "sent_at": c.now(), "provider_id": mid, "body": body})
        upd = {"last_contact_at": c.now()}
        if p["status"] in ("new", "drafted"):
            upd["status"] = "contacted"
        db.update("gs_prospects", {"id": f"eq.{p['id']}"}, upd)
        _queue_followup(db, {**e, "provider_id": mid}, p)
        sent += 1
    if failed:
        db.alert("gs_sender", f"{failed} email(s) failed to send — see Outreach on the dashboard", "warn")
    return f"sent {sent}, failed {failed}, {bounced} bounces/opt-outs handled"
