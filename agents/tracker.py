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
    return apply_reply(db, req, classify(req, text), text, _ts(m["internalDate"]), extra_links=_share_links(m))

def apply_reply(db, req, c, text, when, via="", extra_links=None):
    """Update one request from a classified agency reply (its own thread or a portal email) and alert Bobby."""
    links = [l for l in dict.fromkeys((extra_links or []) + LINK_RX.findall(text))
             if not re.search(r"unsubscribe|privacy|facebook|twitter|instagram|mailto:", l, re.I)]
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
                                           "followups": f"lt.{maxf}", "to_email": "not.is.null",   # portal filings: no inbox to nudge
                                           "limit": 10})
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

PORTAL_Q = ("newer_than:14d (govqa OR nextrequest OR justfoia OR \"public records\" OR \"records request\" "
            "OR \"open records\" OR foia OR cpra OR \"body camera\" OR bodycam) -from:me")
PORTALS = ("govqa.us", "nextrequest.com", "justfoia.com", "mycusthelp.com", "gmail.com", "outlook.com")
NOISE_SUBJ = re.compile(r"^(automatic reply|auto[- ]?reply|out of (the )?office|undeliverable|delivery status)"
                        r"|welcome to|portal registration|account (created|activation|registration)"
                        r"|verify your (email|account)|password reset|activate your account", re.I)
REF_RX = re.compile(r"\b[A-Z]{0,8}-?\d{2,}(?:-\d{2,})+\b")
NOT_REF = re.compile(r"^(\d{4}-\d{1,2}-\d{1,2}|\d{3}-\d{3}-\d{4}|\d{1,2}-\d{1,2}-\d{2,4})$")

def _gmail_link(thread_id):
    return f"https://mail.google.com/mail/u/0/#all/{thread_id}"

def _refs(text):
    return {r for r in REF_RX.findall(text or "") if not NOT_REF.match(r)}

def _domain(addr):
    m = re.search(r"@([\w.-]+)", addr or "")
    return ".".join(m[1].lower().split(".")[-2:]) if m else ""

def _strip_re(subject):
    return re.sub(r"^\s*((re|fw|fwd)\s*:\s*)+", "", subject or "", flags=re.I).strip()

def quick_match(reqs, sender, subject, text):
    """Match without AI when the evidence is plain: a reference number we already have on file, our own request
    subject quoted back, or the only open request to that agency's email domain."""
    refs = _refs(subject + " " + text[:3000])
    for r in reqs:
        hay = (r.get("subject") or "") + " " + (r.get("notes") or "")
        if refs & _refs(hay):
            return r
    base = _strip_re(subject).lower()
    if len(base) > 20:
        for r in reqs:
            if _strip_re(r.get("subject")).lower()[:60] == base[:60]:
                return r
    dom = _domain(sender)
    if dom and dom not in PORTALS:
        same = [r for r in reqs if _domain(r.get("to_email")) == dom]
        if len(same) == 1:
            return same[0]
    return None

def match_portal(open_reqs, sender, subject, text):
    """Which of our open requests an agency email is about (agency, case, incident, reference number) + what it says."""
    return llm.ask(
        "You match an email from a police agency or a public-records portal (GovQA, NextRequest, JustFOIA, etc.) to one "
        "of our open requests and classify it. Match only on clear evidence: agency name, sender domain, incident, date, "
        "or a reference number that also appears in the request's notes. If unsure, request_id is null. "
        "kind: 'update' for anything about a specific records request (acknowledgement, fee, question, denial, "
        "delivery, new link); 'auto_reply' for out-of-office/automatic replies; 'account' for portal welcome, "
        "registration, login or password mail; 'other' for anything else.\n" + RULES,
        "OUR OPEN REQUESTS:\n" + json.dumps([{"request_id": r["id"], "subject": r.get("subject"), "to": r.get("to_email"),
                                              "notes": (r.get("notes") or "")[-300:]} for r in open_reqs]) +
        f"\n\nEMAIL\nFrom: {sender}\nSubject: {subject}\n\n{text[:4000]}\n\n"
        'Return JSON {"request_id":"uuid or null","kind":"update|auto_reply|account|other",'
        '"reference":"request/reference number or null",'
        '"status":"acknowledged|fee_quoted|clarify|denied|fulfilled|other","fee":"amount and terms or null",'
        '"links_expire":"expiry info or null","summary":"one sentence",'
        '"agency_name":"","state":"2-letter or null","incident_date":"YYYY-MM-DD or null",'
        '"title":"short case title (the incident, not the email)","category":"enforcement|case_story|rescue|other"}',
        max_tokens=600, temperature=0.1)

def _date_or_none(d):
    """The AI sometimes writes partial dates like '2025-08-XX'; the database only takes real ones."""
    return d if isinstance(d, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else None

def adopt(db, t, m, sender, subject, text, c):
    """An agency email about a request we have no record of (sent by hand, or filed on a portal). Start tracking
    it so its later emails match, and if it already delivers footage, hand that footage to the agents."""
    status = c.get("status") if c.get("status") in ("acknowledged", "fee_quoted", "clarify", "denied", "fulfilled") \
        else "acknowledged"
    links = _share_links(m) or [l for l in LINK_RX.findall(text) if re.search(r"download|video|share|file", l, re.I)]
    if status == "fulfilled" and not links:
        status = "acknowledged"                 # says it's done but no link we can use: keep tracking, flag below
    agency = c.get("agency_name") or re.sub(r"\s*<.*", "", sender).strip('" ') or "Unknown agency"
    title = c.get("title") or _strip_re(subject)[:120] or f"Records request — {agency}"
    lead = db.insert("leads", {
        "title": title, "agency_name": agency, "state": c.get("state"), "incident_date": _date_or_none(c.get("incident_date")),
        "summary": c.get("summary"), "source_url": f"gmail:{t}", "source_type": "records_request",
        "action_score": 7, "category": c.get("category") or "enforcement", "involves_minor": None,
        "status": "requested", "notes": "Picked up from an agency email (request not sent by Outreach)"},
        upsert=True, on_conflict="source_url")[0]
    ref = c.get("reference") or ", ".join(sorted(_refs(subject + " " + text[:3000])))
    to = (re.search(r"[\w.+-]+@[\w.-]+", sender) or [None])[0]
    req = db.insert("records_requests", {
        "lead_id": lead["id"], "to_email": to, "subject": _strip_re(subject) or title, "gmail_thread_id": t,
        "status": "sent", "notes": f"[{_now():%Y-%m-%d}] tracking started from agency email" + (f"; ref {ref}" if ref else "")})[0]
    req["status"] = "sent"
    got = apply_reply(db, req, dict(c, status=status), text, _ts(m["internalDate"]),
                      via=f"ref {ref}: " if ref else "", extra_links=links)
    if got == "denied":
        db.alert_once("tracker", f"Agency said no: {title} ({agency}): {c.get('summary') or ''}", "info",
                      key=f"Agency said no: {title}")
    return got, req

def portal_mail(db):
    """Agency replies that land outside a tracked thread (portals, new threads, requests sent by hand). Match each
    to its request and update it like a normal reply. If there's no request on file, start tracking one. Auto-replies
    and portal account mail are skipped quietly."""
    seen = db.setting("portal_seen_v2", None)
    if seen is None:                             # one-time: re-read everything the old version couldn't match
        seen = db.setting("portal_seen", {}) or {}
        for a in db.select("alerts", {"agent": "eq.tracker", "resolved": "is.false", "select": "message", "limit": 500}):
            for tid in re.findall(r"#all/([0-9a-f]+)|Gmail thread ([0-9a-f]+)", a.get("message") or ""):
                for x in tid:
                    seen.pop(x, None)
        db.resolve_alerts("tracker", "Records-portal email outside a tracked thread")
    known = {r["gmail_thread_id"] for r in db.select("records_requests", {"select": "gmail_thread_id",
                                                                          "gmail_thread_id": "not.is.null"})}
    threads = []
    for h in search(PORTAL_Q, 40):
        if h["threadId"] not in known and h["threadId"] not in threads:
            threads.append(h["threadId"])
    open_reqs = db.select("records_requests", {"status": f"in.({','.join(OPEN)})",
                                               "select": "id,subject,to_email,notes,status,lead_id", "limit": 120})
    by_id = {r["id"]: r for r in open_reqs}
    matched = adopted = flagged = skipped = 0
    for t in threads[:20]:
        th = get_thread(t)
        msgs = [m for m in th.get("messages", []) if config.SENDER_EMAIL.lower() not in (header(m, "From") or "").lower()]
        if not msgs:
            continue
        m = msgs[-1]
        if seen.get(t) == m["id"]:
            continue                             # already handled this message
        sender, subject, text = header(m, "From") or "", header(m, "Subject") or "", message_text(m)
        seen[t] = m["id"]
        if NOISE_SUBJ.search(subject):
            skipped += 1
            db.resolve_alerts("tracker", _gmail_link(t))
            continue
        req = quick_match(open_reqs, sender, subject, text)
        c = match_portal(open_reqs, sender, subject, text)
        req = req or by_id.get(c.get("request_id") or "")
        if c.get("kind") in ("auto_reply", "account") and not req:
            skipped += 1
        elif req:
            ref = f"ref {c['reference']}: " if c.get("reference") else "portal: "
            apply_reply(db, req, c, text, _ts(m["internalDate"]), via=ref, extra_links=_share_links(m))
            matched += 1
        elif c.get("kind") == "update":
            _, new = adopt(db, t, m, sender, subject, text, c)
            open_reqs.append(new)              # later emails in this same run (same reference number) match it
            by_id[new["id"]] = new
            adopted += 1
        else:
            db.alert_once("tracker", f"Records email we couldn't match to a request — from {sender[:60]}: "
                          f"\"{subject[:80]}\". {c.get('summary') or ''} Open it: {_gmail_link(t)}", "info",
                          key="Records email we couldn't match")
            flagged += 1
            continue
        db.resolve_alerts("tracker", _gmail_link(t))     # handled now: clear the old "couldn't match" alert
    db.insert("settings", {"key": "portal_seen_v2", "value": dict(list(seen.items())[-300:])},
              upsert=True, on_conflict="key")
    return matched, adopted, flagged, skipped

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
    for h in search(f"in:sent newer_than:60d -to:{config.SENDER_EMAIL} (\"records request\" OR CPRA OR \"public records\") "
                    "-subject:report -subject:brief -subject:HQ", 40):
        if h["threadId"] in seen_threads or len(seen_threads) >= 30:
            continue
        seen_threads.add(h["threadId"])
        time.sleep(0.4)
        try:
            m = get_thread(h["threadId"])["messages"][0]
            if re.search(r"daily report|weekly|scoreboard|brief", header(m, "Subject") or "", re.I):
                continue
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
            "incident_date": _date_or_none(pick.get("incident_date")), "summary": pick.get("summary") or (req.get("body") or "")[:600],
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

BAD_TITLE = re.compile(r"daily report|weekly report|scoreboard|\bbrief\b|\bHQ\b", re.I)

def retitle_bad_leads(db):
    """Footage shares were sometimes matched to our own daily-report email and named after it. Rename those
    cases from the share email itself."""
    fixed = 0
    for lead in db.select("leads", {"source_type": "eq.records_request", "select": "id,title,agency_name",
                                    "order": "created_at.desc", "limit": 200}):
        if not BAD_TITLE.search(lead.get("title") or ""):
            continue
        req = (db.select("records_requests", {"lead_id": f"eq.{lead['id']}", "gmail_thread_id": "not.is.null",
                                              "select": "gmail_thread_id", "limit": 1}) or [{}])[0]
        if not req.get("gmail_thread_id"):
            continue
        try:
            msg = get_thread(req["gmail_thread_id"])["messages"][-1]
        except Exception:
            continue
        info = llm.ask("Name the police incident a footage-share email delivers. Use only what the email says.",
                       message_text(msg)[:3000] + '\n\nReturn JSON {"title":"short case title, e.g. agency + what '
                       'happened, or agency + \'records release\' if the email doesn\'t say","agency_name":""}',
                       max_tokens=200, temperature=0.1)
        title = (info.get("title") or "").strip()
        if not title or BAD_TITLE.search(title):
            agency = info.get("agency_name") or lead.get("agency_name") or "Agency"
            title = f"{agency} records release"
        old = lead["title"]
        db.update("leads", {"id": f"eq.{lead['id']}"}, {"title": title,
                  "agency_name": info.get("agency_name") or lead.get("agency_name")})
        for it in db.select("content", {"lead_id": f"eq.{lead['id']}", "status": "neq.posted",
                                        "select": "id,title,case_name"}):
            db.update("content", {"id": f"eq.{it['id']}"}, {"case_name": title,
                      "title": (it.get("title") or "").replace(old, title) if old in (it.get("title") or "") else it.get("title")})
        db.resolve_alerts("publisher", old)
        fixed += 1
    return fixed

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
    pm, pa, pf, ps = portal_mail(db)
    fixed = retitle_bad_leads(db)
    return (f"footage shares picked up {shares}; checked {len(reqs)} open requests, updates {json.dumps(changed)}, "
            f"follow-ups sent {f}, agency emails matched {pm}, newly tracked {pa}, unmatched {pf}, skipped {ps}"
            + (f", fixed {fixed} mis-titled cases" if fixed else ""))
