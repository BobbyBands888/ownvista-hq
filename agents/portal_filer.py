"""Portal Filer: records requests for agencies that only take them through a web portal (GovQA, JustFOIA,
NextRequest, mycusthelp...).

Those portals need a per-city account and often a CAPTCHA, so nothing here submits to a portal. For each portal-only
lead this agent runs the same pre-send check Outreach uses, writes the full request letter, and queues it as a
records_requests row with status "to_file". The dashboard's "File on portal" card shows the link and the letter with
copy buttons. Once Bobby submits it and clicks Filed, the row becomes "sent" and the tracker handles the agency's
replies like any other request (the portal tracking number is kept in notes so reply emails match on it).
"""
from datetime import datetime, timezone

from .outreach import verify, ready_to_send, compose, compose_case, is_case

SOURCES = "in.(agency_release,news_tip,prosecutor_release)"


def _now():
    return datetime.now(timezone.utc)


def _same_incident_requested(db, agency_id, lead):
    """Never ask the same agency twice for one incident (emailed or portal)."""
    if not lead.get("incident_date"):
        return False
    prior = [x["lead_id"] for x in db.select("records_requests", {"agency_id": f"eq.{agency_id}",
                                                                  "select": "lead_id", "limit": 200}) if x.get("lead_id")]
    if not prior:
        return False
    same = db.select("leads", {"id": f"in.({','.join(prior)})", "incident_date": f"eq.{lead['incident_date']}",
                               "select": "id"})
    return bool(same)


def main(db):
    max_queue = int(db.setting("portal_queue_max", 8))      # don't pile up more than Bobby can file
    per_run = int(db.setting("portal_per_run", 4))
    waiting = db.select("records_requests", {"status": "eq.to_file", "select": "id"})
    room = min(per_run, max_queue - len(waiting))
    if room <= 0:
        return f"{len(waiting)} portal requests already waiting to be filed; nothing new queued"

    signature = db.setting("signature_name", "Bobby Cipro")
    agencies = {a["name"].lower(): a for a in db.select("agencies", {"select": "*"})}
    leads = db.select("leads", {"status": "eq.new", "source_type": SOURCES,
                                "order": "action_score.desc,created_at.desc", "limit": 60})
    queued, held, rerouted, used_agency = 0, 0, 0, set()
    for lead in leads:
        if queued >= room:
            break
        a = agencies.get((lead.get("agency_name") or "").lower())
        if not a or a.get("records_email") or not a.get("portal_url"):
            continue                                    # emailable agencies belong to Outreach
        if a["id"] in used_agency:
            continue                                    # one per agency per run
        if db.select("records_requests", {"lead_id": f"eq.{lead['id']}", "select": "id"}):
            continue
        if _same_incident_requested(db, a["id"], lead):
            db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "skipped", "notes": "duplicate incident"})
            continue
        try:
            chk = verify(lead, a)
        except Exception as e:
            db.alert("portal_filer", f"Couldn't verify '{lead['title'][:60]}': {str(e)[:150]}", "info")
            continue
        ok, why = ready_to_send(chk, a, lead)
        if not ok:
            held += 1
            upd = {"notes": ((lead.get("notes") or "") + f"\nportal check {_now():%Y-%m-%d}: not queued — {why}").strip()}
            if not chk.get("same_agency") and chk.get("agency"):
                upd.update(agency_name=chk["agency"], state=(chk.get("state") or lead.get("state")))
                db.insert("agencies", {"name": chk["agency"], "state": chk.get("state")}, upsert=True, on_conflict="name")
                rerouted += 1
            else:
                upd["status"] = "skipped"
            db.update("leads", {"id": f"eq.{lead['id']}"}, upd)
            continue
        if chk.get("date") and not lead.get("incident_date"):
            db.update("leads", {"id": f"eq.{lead['id']}"}, {"incident_date": chk["date"]})
        if is_case(lead):
            subject, body = compose_case(lead, a, signature, chk)
        else:
            subject, body = compose(lead, a, signature, desc=chk.get("description"), chk=chk)
        db.insert("records_requests", {"lead_id": lead["id"], "agency_id": a["id"], "to_email": None,
                                       "subject": subject, "body": body, "status": "to_file",
                                       "notes": f"portal: {a['portal_url']}"})
        db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "queued_request"})
        used_agency.add(a["id"])
        queued += 1
    return (f"queued {queued} portal requests for Bobby to file ({len(waiting) + queued} waiting); "
            f"held {held} that failed the pre-send check ({rerouted} re-pointed to the right agency)")
