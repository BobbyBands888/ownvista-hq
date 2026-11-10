"""RECORDS TRACKER agent — reads agency replies, updates each request, catches download links,
flags fee quotes / clarification asks to Bobby (never pays, never negotiates fees), and sends polite
follow-ups on silent requests."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from .lib import config, llm
from .lib.google import get_thread, message_text, message_links, header, send_email, search
from .lib.runner import RULES

OPEN = ("sent", "acknowledged", "fee_quoted", "clarify")
LINK_RX = re.compile(r"https?://[^\s<>\"')]+")

def _now():
    return datetime.now(timezone.utc)

def _ts(ms):
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc)

def classify(req, text):
    return llm.ask(
        "You read replies from police agencies to public records requests. Classify the latest reply. "
        "Be literal; do not guess.\n" + RULES,
        f"Our request subject: {req['subject']}\n\nAgency reply:\n{text[:5000]}\n\n"
        'Return JSON {"status":"acknowledged|fee_quoted|clarify|denied|fulfilled|other",'
        '"fee":"amount and terms or null","deadline":"any date mentioned or null",'
        '"links_expire":"expiry info or null","needs_bobby":true|false,"summary":"one sentence"}',
        max_tokens=400, temperature=0.1)

def process_request(db, req):
    th = get_thread(req["gmail_thread_id"])
    last = datetime.fromisoformat(req["last_activity_at"].replace("Z", "+00:00")) if req.get("last_activity_at") else None
    new_msgs = [m for m in th.get("messages", [])
                if config.SENDER_EMAIL.lower() not in (header(m, "From") or "").lower()
                and (last is None or _ts(m["internalDate"]) > last)]
    if not new_msgs:
        return None
    m = new_msgs[-1]
    text = message_text(m)
    return apply_reply(db, req, classify(req, text), text, _ts(m["internalDate"]))

def apply_reply(db, req, c, text, when, via=""):
    """Update one request from a classified agency reply (its own thread or a portal email) and alert Bobby."""
    links = [l for l in LINK_RX.findall(text) if not re.search(r"unsubscribe|privacy|facebook|twitter|instagram", l, re.I)]
    status = c.get("status") if c.get("status") in ("acknowledged", "fee_quoted", "clarify", "denied", "fulfilled") else req["status"]
    upd = {"status": status, "last_activity_at": when,
           "notes": ((req.get("notes") or "") + f"\n[{_now():%Y-%m-%d}] {via}{c.get('summary')}").strip()}
    if c.get("fee"):
        upd["fee_quote"] = c["fee"]
    if status == "fulfilled" and links:
        upd["download_links"] = links[:10]
    db.update("records_requests", {"id": f"eq.{req['id']}"}, upd)
    subj = (req.get("subject") or "")[:80]
    if status == "fulfilled":
        if req.get("lead_id"):
            db.update("leads", {"id": f"eq.{req['lead_id']}"}, {"status": "obtained"})
        lvl = "urgent" if c.get("links_expire") else "info"
        db.alert("tracker", f"Footage ready: {subj}. Links: {', '.join(links[:3]) or 'see email'}"
                 + (f" — EXPIRES: {c['links_expire']}" if c.get("links_expire") else ""), lvl)
    elif status == "fee_quoted":
        db.alert("tracker", f"Fee quote (not paid — your call): {subj}: {c.get('fee')}", "warn")
    elif status == "clarify":
        db.alert("tracker", f"Agency needs clarification: {subj}: {c.get('summary')}", "warn")
    elif status == "denied" and req.get("lead_id"):
        db.update("leads", {"id": f"eq.{req['lead_id']}"}, {"status": "rejected"})
    return status

def followups(db):
    days = int(db.setting("followup_after_days", 10))
    maxf = int(db.setting("max_followups", 3))
    cutoff = (_now() - timedelta(days=days)).isoformat()
    stale = db.select("records_requests", {"status": "in.(sent,acknowledged)", "last_activity_at": f"lt.{cutoff}",
                                           "followups": f"lt.{maxf}", "limit": 10})
    n = 0
    for r in stale:
        body = ("Hello,\n\nFollowing up on my public records request below. Could you share the current status "
                "and an expected completion date?\n\nThank you,\n" + db.setting("signature_name", "Bobby Cipro") +
                "\nTen-Four Tapes\n")
        send_email(r["to_email"], "Re: " + r["subject"], body, thread_id=r["gmail_thread_id"])
        db.update("records_requests", {"id": f"eq.{r['id']}"},
                  {"followups": r["followups"] + 1, "last_activity_at": _now()})
        n += 1
    return n

PORTAL_Q = ("newer_than:3d (govqa OR nextrequest OR justfoia OR \"public records\" OR \"records request\" "
            "OR \"open records\" OR foia) -from:me")

def _gmail_link(thread_id):
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"

def match_portal(open_reqs, sender, subject, text):
    """Which of our open requests a portal email is about (agency, case, incident, reference number) + what it says."""
    return llm.ask(
        "You match a public-records portal email (GovQA, NextRequest, JustFOIA, etc.) to one of our open requests "
        "and classify it. Match only on clear evidence: agency name, sender domain, incident, date, or a reference "
        "number that also appears in the request's notes. If unsure, request_id is null.\n" + RULES,
        "OUR OPEN REQUESTS:\n" + json.dumps([{"request_id": r["id"], "subject": r.get("subject"), "to": r.get("to_email"),
                                              "notes": (r.get("notes") or "")[-300:]} for r in open_reqs]) +
        f"\n\nPORTAL EMAIL\nFrom: {sender}\nSubject: {subject}\n\n{text[:4000]}\n\n"
        'Return JSON {"request_id":"uuid or null","reference":"portal request number or null",'
        '"status":"acknowledged|fee_quoted|clarify|denied|fulfilled|other","fee":"amount and terms or null",'
        '"links_expire":"expiry info or null","summary":"one sentence"}',
        max_tokens=500, temperature=0.1)

def portal_mail(db):
    """Agencies using GovQA/NextRequest/JustFOIA portals reply from a new thread. Read each one, match it to the
    open request it's about and update that request like a normal reply; flag only what can't be matched — once."""
    seen = db.setting("portal_seen", {}) or {}
    known = {r["gmail_thread_id"] for r in db.select("records_requests", {"select": "gmail_thread_id",
                                                                          "gmail_thread_id": "not.is.null"})}
    threads = []
    for h in search(PORTAL_Q, 30):
        if h["threadId"] not in known and h["threadId"] not in threads:
            threads.append(h["threadId"])
    open_reqs = db.select("records_requests", {"status": f"in.({','.join(OPEN)})",
                                               "select": "id,subject,to_email,notes,status,lead_id", "limit": 80})
    by_id = {r["id"]: r for r in open_reqs}
    matched = flagged = 0
    for t in threads[:12]:
        th = get_thread(t)
        msgs = [m for m in th.get("messages", []) if config.SENDER_EMAIL.lower() not in (header(m, "From") or "").lower()]
        if not msgs:
            continue
        m = msgs[-1]
        if seen.get(t) == m["id"]:
            continue                             # already handled this message
        sender, subject, text = header(m, "From") or "", header(m, "Subject") or "", message_text(m)
        c = match_portal(open_reqs, sender, subject, text) if open_reqs else {}
        req = by_id.get(c.get("request_id") or "")
        if req:
            ref = f"portal {c['reference']}: " if c.get("reference") else "portal: "
            apply_reply(db, req, c, text, _ts(m["internalDate"]), via=ref)
            matched += 1
        else:
            db.alert("tracker", f"Records email we couldn't match to a request — from {sender[:60]}: \"{subject[:80]}\". "
                     f"{c.get('summary') or ''} Open it: {_gmail_link(t)}", "warn" if c.get("status") in
                     ("fee_quoted", "clarify", "fulfilled") else "info")
            flagged += 1
        seen[t] = m["id"]
    if matched or flagged:
        recent = dict(list(seen.items())[-200:])  # keep the memory small
        db.insert("settings", {"key": "portal_seen", "value": recent}, upsert=True, on_conflict="key")
    return matched, flagged

SHARE_SENDERS = "from:(noreply@evidence.com OR evidence.com OR nextrequest.com OR govqa.us OR justfoia.com OR sharefile.com)"

def _share_links(msg):
    links = [l for l in message_links(msg) if re.search(r"download|evidence|share|/axon/", l, re.I)
             and not re.search(r"agencyname\.|unsubscribe|privacy|support|help\.|/legal", l, re.I)]
    links.sort(key=lambda l: "/axon/download/" not in l)        # the real package link first
    return links

def shared_footage(db):
    """Footage shares (Axon Evidence.com etc.) usually arrive in a NEW thread, often for requests Bobby sent by
    hand. Match each share to the request it answers and turn it into an obtained lead the agents can use."""
    hits = search(f"newer_than:30d {SHARE_SENDERS} (download OR shared OR evidence)", 20)
    known = {r["gmail_thread_id"] for r in db.select("records_requests", {"select": "gmail_thread_id"})}
    # repair shares stored with placeholder links (the real download button only lives in the HTML part)
    for r in db.select("records_requests", {"status": "eq.fulfilled", "gmail_thread_id": "not.is.null",
                                            "select": "id,gmail_thread_id,download_links"}):
        if r["gmail_thread_id"] in {h["threadId"] for h in hits} and not any(
                "/axon/download/" in l or "click" in l for l in (r.get("download_links") or [])):
            m = get_thread(r["gmail_thread_id"])["messages"][-1]
            good = _share_links(m)
            if good:
                db.update("records_requests", {"id": f"eq.{r['id']}"}, {"download_links": good[:10]})
    sent = []
    new_shares = {h["threadId"] for h in hits} - known
    if not new_shares:
        return 0
    seen_threads = set()
    for h in search("in:sent newer_than:45d (\"records request\" OR CPRA OR \"public records\")", 40):
        if h["threadId"] in seen_threads or len(seen_threads) >= 30:
            continue
        seen_threads.add(h["threadId"])
        time.sleep(0.4)
        try:
            m = get_thread(h["threadId"])["messages"][0]
            sent.append({"thread": h["threadId"], "to": header(m, "To"), "subject": header(m, "Subject"),
                         "body": message_text(m)[:700]})
        except Exception:
            continue
    made = 0
    for t in new_shares:
        msg = get_thread(t)["messages"][-1]
        text = message_text(msg)
        links = _share_links(msg)
        if not links:
            continue
        pick = llm.ask(
            "Match a footage-share email from a police agency to the public records request it answers.",
            "Share email:\n" + text[:2500] + "\n\nRequests we sent:\n" +
            json.dumps([{"i": i, "to": s["to"], "subject": s["subject"], "body": s["body"][:400]} for i, s in enumerate(sent)]) +
            '\n\nReturn JSON {"i": index or null, "agency_name": "", "state": "2-letter", "incident_date": "YYYY-MM-DD or null",'
            '"title": "short case title", "summary": "2 sentences on the incident from our request", '
            '"links_expire": "date or null", "category": "enforcement|case_story|rescue|other"}', max_tokens=500, temperature=0.1)
        i = pick.get("i")
        req = sent[i] if isinstance(i, int) and 0 <= i < len(sent) else {}
        agency = pick.get("agency_name") or (re.search(r"Axon - ([^\n]+)", text) or [None, "Unknown agency"])[1]
        lead = db.insert("leads", {
            "title": pick.get("title") or req.get("subject") or agency, "agency_name": agency, "state": pick.get("state"),
            "incident_date": pick.get("incident_date"), "summary": pick.get("summary") or (req.get("body") or "")[:600],
            "source_url": f"gmail:{t}", "source_type": "records_request", "action_score": 7,
            "category": pick.get("category") or "enforcement", "involves_minor": None, "status": "obtained",
            "notes": "Footage delivered by the agency" + (f"; links expire {pick['links_expire']}" if pick.get("links_expire") else "")},
            upsert=True, on_conflict="source_url")[0]
        db.insert("records_requests", {
            "lead_id": lead["id"], "to_email": req.get("to"), "subject": req.get("subject") or f"Footage share from {agency}",
            "gmail_thread_id": t, "status": "fulfilled", "last_activity_at": _ts(msg["internalDate"]),
            "download_links": links[:10], "notes": f"[{_now():%Y-%m-%d}] footage share picked up automatically"})
        db.alert("tracker", f"Footage in: {lead['title']} ({agency})"
                 + (f" — link expires {pick['links_expire']}" if pick.get("links_expire") else ""), "info")
        made += 1
    return made

def main(db):
    shares = shared_footage(db)
    reqs = db.select("records_requests", {"status": f"in.({','.join(OPEN)})", "gmail_thread_id": "not.is.null",
                                          "order": "last_activity_at.asc", "limit": 40})
    changed = {}
    for r in reqs:
        try:
            s = process_request(db, r)
            if s:
                changed[s] = changed.get(s, 0) + 1
        except Exception as e:
            db.alert("tracker", f"could not read thread for '{r['subject'][:60]}': {e}", "warn")
    f = followups(db)
    pm, pf = portal_mail(db)
    return (f"footage shares picked up {shares}; checked {len(reqs)} open requests, updates {json.dumps(changed)}, "
            f"follow-ups sent {f}, portal emails matched {pm}, unmatched flagged {pf}")
