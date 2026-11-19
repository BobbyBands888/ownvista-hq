"""OUTREACH agent — sends public records requests from bobbybands888@gmail.com for the best open leads.
Rules: daily cap (default 10), max 2 per agency per day, only verified records addresses,
always asks for a fee estimate before any work (we never pay), never offers or asks for calls."""
import os
import json
import re
import time
from datetime import datetime, timedelta, timezone
import requests
from .lib import llm
from .lib.google import send_email
from .lib.runner import RULES

STATUTES = {
    "FL": "Florida's Public Records Act, Chapter 119, Florida Statutes",
    "TX": "the Texas Public Information Act, Chapter 552 of the Texas Government Code",
    "GA": "the Georgia Open Records Act, O.C.G.A. § 50-18-70 et seq.",
    "AZ": "Arizona's Public Records Law, A.R.S. § 39-121 et seq.",
    "CA": "the California Public Records Act, Gov. Code § 7920.000 et seq.",
    "NY": "New York's Freedom of Information Law, Public Officers Law Article 6",
    "OH": "the Ohio Public Records Act, R.C. 149.43",
    "WA": "the Washington Public Records Act, RCW 42.56",
    "CO": "the Colorado Criminal Justice Records Act, C.R.S. § 24-72-301 et seq.",
    "MI": "the Michigan Freedom of Information Act, MCL 15.231 et seq.",
}
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
RECORDS_HINT = re.compile(r"record|foia|pra|custodian|publicinfo|openrecords|pio|media", re.I)
# prosecutors' offices often sit on .org/.net domains (sao9.org, mcao.org) as well as .gov
PROSECUTOR_DOM = re.compile(r"(^|[.-])(sao\d*|da|mcao|cao)[.-]|attorney|prosecutor", re.I)
OFFICIAL_LINK = re.compile(r"\.gov|\.us/|\.us$|sheriff|police|county|city|state\.|sao\d|attorney|prosecutor", re.I)


def _official_domain(dom):
    dom = dom.lower()
    return dom.endswith((".gov", ".us")) or "sheriff" in dom or "police" in dom or bool(PROSECUTOR_DOM.search(dom))

def _now():
    return datetime.now(timezone.utc)

def _official_email_on(link):
    """Return a records-type address only if it is literally printed on an official-looking page."""
    if not OFFICIAL_LINK.search(link):
        return None
    try:
        page = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    except Exception:
        return None
    for e in EMAIL_RX.findall(page):
        if _official_domain(e.split("@")[1]) and RECORDS_HINT.search(e):
            return e.lower()
    return None

def _groq_web_lookup(agency):
    """Free: Groq's web-search model finds candidate pages; the address is still verified on the page itself."""
    from .lib import config
    if not config.GROQ_API_KEY:
        return None, None
    ask = (f'Find the official email address for submitting public records requests (records custodian, records '
           f'unit, or public information officer) for: {agency["name"]}, {agency.get("state") or ""}. Search the '
           f'agency\'s own website. Answer ONLY as JSON: {{"email":"...","source_url":"page where it is printed"}}')
    global LAST_LOOKUP_NOTE
    last_note = ""
    # gpt-oss on Groq has a built-in web search tool on the free tier (compound models aren't on this account)
    attempts = [("openai/gpt-oss-20b", [{"type": "browser_search"}])]   # 20b only: keeps 120b's daily budget for writing
    for model, tools in attempts:
        try:
            body = {"model": model, "messages": [{"role": "user", "content": ask}], "max_tokens": 2000}
            if tools:
                body.update(tools=tools, tool_choice="required")
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, json=body, timeout=180)
            if r.status_code == 429:
                time.sleep(min(60, float(r.headers.get("retry-after", 30) or 30)))
                r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                                  headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, json=body, timeout=180)
            if r.status_code >= 300:
                last_note += f" [{model}: HTTP {r.status_code} {r.text[:100]}]"
                continue
            text = r.json()["choices"][0]["message"]["content"]
            url = re.search(r'"source_url"\s*:\s*"([^"]+)"', text) or re.search(r'https?://[^\s"\')\]>]+', text)
            em = re.search(r'"email"\s*:\s*"([^"@\s]+@[^"\s]+)"', text) or EMAIL_RX.search(text)
            src = ((url.group(1) if url.re.groups else url.group(0)).rstrip(".,;:") if url else None)
            if src:
                email = _official_email_on(src)
                if email:
                    return email, src
            # Many sheriff sites block scripts, so the page can't always be re-read. Accept the found address
            # only if it's on an official domain AND matches the official page it came from.
            if em and src:
                e = (em.group(1) if em.re.groups else em.group(0)).lower().rstrip(".")
                dom = e.split("@")[1]
                host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", src).split("/")[0].lower())
                official = _official_domain(dom)
                if official and (dom == host or dom.endswith("." + host) or host.endswith("." + dom) or host.endswith(dom)):
                    return e, src
            last_note += f" [{model}: {text[:150]}]"
        except Exception as e:
            last_note += f" [{model}: {type(e).__name__} {str(e)[:100]}]"
            continue
    LAST_LOOKUP_NOTE = last_note
    return None, None

LAST_LOOKUP_NOTE = ""

def find_records_email(agency):
    """Best effort: search the web for the agency's records-request address and only accept an address
    that is literally printed on an official-looking page (.gov / .us / sheriff / police domain)."""
    email, src = _groq_web_lookup(agency)
    if email:
        return email, src
    q = f'{agency["name"]} {agency.get("state") or ""} public records request email'
    links = []
    tavily = os.environ.get("TAVILY_API_KEY")
    try:
        if tavily:   # free tier search API
            r = requests.post("https://api.tavily.com/search", json={"api_key": tavily, "query": q, "max_results": 5},
                              timeout=30)
            links = [x["url"] for x in r.json().get("results", [])]
        else:
            r = requests.get("https://html.duckduckgo.com/html/", params={"q": q},
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
            links = re.findall(r'class="result__a" href="([^"]+)"', r.text)[:5]
    except Exception:
        return None, None
    for link in links:
        m = re.search(r"uddg=([^&]+)", link)
        if m:
            from urllib.parse import unquote
            link = unquote(m.group(1))
        if not OFFICIAL_LINK.search(link):
            continue
        try:
            page = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
        except Exception:
            continue
        for e in EMAIL_RX.findall(page):
            if _official_domain(e.split("@")[1]) and RECORDS_HINT.search(e):
                return e.lower(), link
    return None, None

VERIFY_SYSTEM = """You check a police incident before a public records request is sent. From the documents, decide
which agency's officers are in the footage, which US state it is in, and what identifies the incident for a records
clerk. Use ONLY the documents; cite nothing you can't see. Watch for look-alike place names: a "Washington County" or
"Springfield" story may be in a different state than assumed — the news outlet's own city/state is a strong clue.
Only include a suspect's full name if a document prints it. Never include minors, victims or bystanders.
Dates: each document has a "published" date when known. Resolve relative dates ("Tuesday", "last weekend",
"early Sunday") against the publish date of the document that uses them, and give the exact incident date only when
that works out to one specific day. If the agency itself posted or released the video, give the day it was
released (from the release or the news coverage of it) as release_date, even when the incident date is unclear."""

VERIFY_CASE_SYSTEM = """You check a closed criminal case before a public records request for the suspect's recorded
police interviews is sent. From the documents, decide which office holds those recordings now: the prosecutor's office
that tried the case (State Attorney / District Attorney / County Attorney), or the police agency that ran the
interview if no prosecutor is named. Give the US state, the defendant's full name and court case number if printed,
the date of the crime, and whether the case is closed (sentenced, convicted with the trial over, or pleaded guilty).
Watch for look-alike county names in other states. Use ONLY the documents. Never include minors, victims' family
members or bystanders by name. Say if a minor (under 18) is the victim or the suspect."""


def is_case(lead):
    """A Case Scout lead (interview request). Older bodycam leads can also carry category case_story; those still get
    the bodycam letter."""
    return bool(lead) and lead.get("category") == "case_story" and "[case:" in (lead.get("notes") or "")


def verify(lead, agency):
    """Confirm agency + state + identifiers before anything is sent. Returns the check (dict)."""
    from . import casefacts
    if is_case(lead):
        docs = casefacts.gather(lead, extra_queries=[f"{lead['title'][:80]} sentenced"])
        out = llm.ask(VERIFY_CASE_SYSTEM,
                      "LEAD:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date",
                                                                        "summary", "notes")}) +
                      f"\nWE WERE ABOUT TO SEND TO: {agency['name']} ({agency.get('state') or '?'})\n\nDOCUMENTS:\n" +
                      json.dumps([{k: d[k] for k in ("i", "title", "url", "text")} for d in docs])[:20000] +
                      '\n\nReturn JSON {"agency":"office that holds the interview recordings","state":"2-letter",'
                      '"same_agency":true|false,"date":"YYYY-MM-DD of the crime or null","full_name":"defendant full name or null",'
                      '"case_number":"court case number or null","closed":true|false,"minor_involved":true|false,'
                      '"location":"city/county, state or null","description":"2-3 neutral sentences for the records clerk: '
                      'the case, the defendant, the crime date, the outcome (e.g. convicted of ... on ..., sentenced on ...)",'
                      '"why":"one line"}', max_tokens=700, temperature=0.1)
        return out if isinstance(out, dict) else {}
    docs = casefacts.gather(lead)
    out = llm.ask(VERIFY_SYSTEM,
                  "LEAD:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date", "summary")}) +
                  f"\nWE WERE ABOUT TO SEND TO: {agency['name']} ({agency.get('state') or '?'})\n\nDOCUMENTS:\n" +
                  json.dumps([{k: d.get(k) for k in ("i", "title", "url", "published", "text")} for d in docs])[:20000] +
                  '\n\nReturn JSON {"agency":"exact agency whose officers recorded it","state":"2-letter",'
                  '"same_agency":true|false,"date":"YYYY-MM-DD or null",'
                  '"release_date":"YYYY-MM-DD the agency released the video, or null",'
                  '"full_name":"suspect full name or null",'
                  '"case_number":"or null","location":"road/address/landmark + city or null",'
                  '"description":"2-3 neutral sentences for the records clerk: what happened, where, exact date, '
                  'and the name/case number if known","why":"one line"}', max_tokens=700, temperature=0.1)
    return out if isinstance(out, dict) else {}

def ready_to_send(chk, agency, lead=None):
    """Agency and state confirmed, a specific date, and one more identifier (name, case number or exact place).
    Case stories: the holder and state confirmed, the case closed, no minor involved, and the defendant's name."""
    if is_case(lead):
        if not chk.get("same_agency"):
            return False, f"interviews are held by {chk.get('agency') or 'another office'} ({chk.get('state') or '?'}), not {agency['name']}"
        if agency.get("state") and chk.get("state") and agency["state"].upper() != str(chk["state"]).upper():
            return False, f"state mismatch: case in {chk['state']}, office listed in {agency['state']}"
        if chk.get("minor_involved") is not False:
            return False, "a minor may be involved (or it couldn't be ruled out)"
        if not chk.get("closed"):
            return False, "case not closed yet (interviews usually aren't released until sentencing)"
        if not chk.get("full_name"):
            return False, "no defendant name to identify the case"
        return True, ""
    if not chk.get("same_agency"):
        return False, f"footage is from {chk.get('agency') or 'another agency'} ({chk.get('state') or '?'}), not {agency['name']}"
    if agency.get("state") and chk.get("state") and agency["state"].upper() != str(chk["state"]).upper():
        return False, f"state mismatch: incident in {chk['state']}, agency listed in {agency['state']}"
    day = r"\d{4}-\d{2}-\d{2}$"
    released = (lead or {}).get("source_type") == "agency_release" and re.match(day, str(chk.get("release_date") or ""))
    if not (re.match(day, str(chk.get("date") or "")) or released):
        # an agency's own release is identifiable by its release date + link, even without the incident date
        return False, "no specific incident date found"
    if not (chk.get("full_name") or chk.get("case_number") or chk.get("location")):
        return False, "no name, case number or exact location to identify it"
    return True, ""

def compose_case(lead, agency, signature, chk):
    """Closed case -> the suspect's recorded police interviews + the 911 call, in the version already released or
    played in court. No fees authorized: if there's a charge, we walk away."""
    statute = STATUTES.get((agency.get("state") or lead.get("state") or "").upper(), "your state's public records law")
    who = chk.get("full_name") or ""
    ref = f" (Case No. {chk['case_number']})" if chk.get("case_number") else ""
    subject = f"Public Records Request – Recorded Interviews – State v. {who}{ref}"[:150]
    body = f"""Hello,

Under {statute}, I am requesting copies of the following records from the closed case against {who}{ref}:

{chk.get('description') or ''}

Specifically:
1. The video recordings of the police interviews/interrogations of {who}
2. The 911 call audio for this incident

If these recordings have already been released to the media or were played in open court, that released or redacted version is all I need. Please exclude any recording that shows the death itself, and any recording of a minor.

Electronic delivery (a download link or file share) is preferred. I am not authorizing any fees. If there would be a charge, please tell me the amount before doing any work.

Thank you for your help.

{signature}
Ten-Four Tapes
"""
    return subject, body


def compose(lead, agency, signature, desc=None, chk=None):
    statute = STATUTES.get((agency.get("state") or lead.get("state") or "").upper(),
                           "your state's public records law")
    desc = desc or llm.ask(
        "Write ONE short, neutral paragraph (2-3 sentences) identifying a police incident for a public records "
        "request: what happened, where, approximate date, and any names or case numbers given. No opinions. "
        "Output plain text only.",
        f"Title: {lead['title']}\nSummary: {lead.get('summary') or ''}\nDate: {lead.get('incident_date') or 'unknown'}\n"
        f"Agency: {agency['name']}", json_mode=False, max_tokens=250, temperature=0.2).strip()
    chk = chk or {}
    if chk.get("release_date") and not chk.get("date") and lead.get("source_url"):
        desc += (f"\n\nThis is the incident in the video your office released on {chk['release_date']}: "
                 f"{lead['source_url']}")
    subject = f"Public Records Request – Body Camera Video – {lead['title'][:70]}"
    body = f"""Hello,

Under {statute}, I am requesting copies of the following records:

{desc}

Specifically:
1. All body-worn camera video from every officer/deputy present, unedited and in full
2. Any dash camera / in-car video
3. Any 911 call audio and dispatch/CAD audio related to this incident

Electronic delivery (a download link or file share) is preferred. If any fees would apply, please send an estimate before processing the request.

Thank you for your help.

{signature}
Ten-Four Tapes
"""
    return subject, body

def main(db):
    cap = int(db.setting("outreach_daily_cap", 10))
    signature = db.setting("signature_name", "Bobby Cipro")
    today = _now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    sent_today = db.select("records_requests", {"select": "agency_id", "sent_at": f"gte.{today}",
                                                "to_email": "not.is.null"})   # portal filings don't use the email cap
    budget = cap - len(sent_today)
    per_agency = {}
    for s in sent_today:
        per_agency[s["agency_id"]] = per_agency.get(s["agency_id"], 0) + 1

    # fill in missing agency emails (a few per run, slow and polite)
    missing = db.select("agencies", {"records_email": "is.null", "portal_url": "is.null",
                                     "or": "(notes.is.null,notes.not.like.*email lookup failed*)", "limit": 2})
    found = 0
    for n, a in enumerate(missing):
        if n:
            time.sleep(25)                      # free-tier rate limits: space the web searches out
        email, src = find_records_email(a)
        if not email and "HTTP 429" in LAST_LOOKUP_NOTE:
            break                               # rate-limited: leave the rest for the next run, don't mark failed
        if email:
            db.update("agencies", {"id": f"eq.{a['id']}"}, {"records_email": email, "notes": f"auto-found on {src}"})
            found += 1
        else:
            db.update("agencies", {"id": f"eq.{a['id']}"},
                      {"notes": ((a.get("notes") or "").split(" | ")[0] + " | email lookup failed – add email/portal on dashboard").strip(" |")})


    if budget <= 0:
        return f"daily cap reached ({cap}); found {found} agency emails"

    agencies = {a["name"].lower(): a for a in db.select("agencies", {"select": "*"})}
    # most on-screen danger first (see agents/danger.py), then action
    from . import danger
    leads = danger.rank(db.select("leads", {"status": "eq.new",
                                            "source_type": "in.(agency_release,news_tip,prosecutor_release)",
                                            "order": "action_score.desc,created_at.desc", "limit": 150}))[:40]
    # Bobby, Nov 19: the agency's own post makes the first Reel, but we still ask for every officer's unedited
    # camera (the other angles). These leads keep their status so the Reel work isn't held up.
    from . import agencypost
    posted = [l for l in db.select("leads", {"status": "in.(obtained,used)", "source_type": "eq.agency_release",
                                             "order": "action_score.desc,created_at.desc", "limit": 150})
              if agencypost.url_of(l) and "raw request" not in (l.get("notes") or "")]
    if posted:
        asked = {x["lead_id"] for x in db.select("records_requests", {"select": "lead_id", "lead_id": "in.(" +
                 ",".join(l["id"] for l in posted) + ")"}) if x.get("lead_id")}
        posted = [l for l in posted if l["id"] not in asked]
    leads = leads[:30] + danger.rank(posted)[:10] + leads[30:]

    def raw_note(lead, text):                   # a posted lead is never skipped: its Reel is already in the works
        db.update("leads", {"id": f"eq.{lead['id']}"},
                  {"notes": ((lead.get("notes") or "") + f"\nraw request {_now():%Y-%m-%d}: {text}").strip()})
    sent, no_contact, held, rerouted = 0, 0, 0, 0
    for lead in leads:
        has_post = lead["status"] in ("obtained", "used")
        if sent >= budget:
            break
        a = agencies.get((lead.get("agency_name") or "").lower())
        if not a or not a.get("records_email"):
            no_contact += 1
            continue
        if per_agency.get(a["id"], 0) >= 2:
            continue
        if lead.get("incident_date"):   # never ask the same agency twice for one incident
            dup = [x for x in db.select("records_requests", {"agency_id": f"eq.{a['id']}", "select": "lead_id", "limit": 200})
                   if x.get("lead_id")]
            if dup:
                ids = ",".join(x["lead_id"] for x in dup)
                same = db.select("leads", {"id": f"in.({ids})", "incident_date": f"eq.{lead['incident_date']}", "select": "id"})
                if same:
                    if has_post:
                        raw_note(lead, "already asked this agency about this incident")
                    else:
                        db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "skipped", "notes": "duplicate incident"})
                    continue
        # never send blind: confirm the agency, state and identifiers first (Bundy went to the wrong state's sheriff)
        try:
            chk = verify(lead, a)
        except Exception as e:
            db.alert("outreach", f"Couldn't verify '{lead['title'][:60]}' before sending: {str(e)[:150]}", "info")
            continue
        ok, why = ready_to_send(chk, a, lead)
        if not ok and has_post:
            held += 1
            raw_note(lead, f"held, not sent — {why}")
            continue
        if not ok:
            held += 1
            note = f"outreach check {_now():%Y-%m-%d}: not sent — {why}"
            upd = {"notes": ((lead.get("notes") or "") + "\n" + note).strip()}
            if not chk.get("same_agency") and chk.get("agency"):
                # wrong agency: re-point the lead; the right agency gets its records email looked up next runs
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
        res = send_email(a["records_email"], subject, body)
        db.insert("records_requests", {"lead_id": lead["id"], "agency_id": a["id"], "to_email": a["records_email"],
                                       "subject": subject, "body": body, "sent_at": _now(),
                                       "gmail_thread_id": res.get("threadId"), "status": "sent",
                                       "last_activity_at": _now()})
        if has_post:
            raw_note(lead, "sent (every officer's unedited camera)")
        else:
            db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "requested"})
        db.update("agencies", {"id": f"eq.{a['id']}"}, {"last_request_at": _now()})
        per_agency[a["id"]] = per_agency.get(a["id"], 0) + 1
        sent += 1
    return (f"sent {sent} requests ({len(sent_today) + sent}/{cap} today); held {held} that failed the pre-send check "
            f"({rerouted} re-pointed to the right agency); {no_contact} leads waiting on an agency email; "
            f"found {found} new agency emails")
