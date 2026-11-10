"""OUTREACH agent — sends public records requests from bobbybands888@gmail.com for the best open leads.
Rules: daily cap (default 10), max 2 per agency per day, only verified records addresses,
always asks for a fee estimate before any work (we never pay), never offers or asks for calls."""
import os
import re
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

def _now():
    return datetime.now(timezone.utc)

def _official_email_on(link):
    """Return a records-type address only if it is literally printed on an official-looking page."""
    if not re.search(r"\.gov|\.us/|\.us$|sheriff|police|county|city|state\.", link, re.I):
        return None
    try:
        page = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
    except Exception:
        return None
    for e in EMAIL_RX.findall(page):
        dom = e.split("@")[1].lower()
        if (dom.endswith(".gov") or dom.endswith(".us") or "sheriff" in dom or "police" in dom) and RECORDS_HINT.search(e):
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
    attempts = [("openai/gpt-oss-120b", [{"type": "browser_search"}]), ("openai/gpt-oss-20b", [{"type": "browser_search"}]),
                ("groq/compound", None)]
    for model, tools in attempts:
        try:
            body = {"model": model, "messages": [{"role": "user", "content": ask}], "max_tokens": 2000}
            if tools:
                body.update(tools=tools, tool_choice="required")
            r = requests.post("https://api.groq.com/openai/v1/chat/completions",
                              headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"}, json=body, timeout=180)
            if r.status_code >= 300:
                last_note = f"{model}: HTTP {r.status_code} {r.text[:120]}"
                continue
            text = r.json()["choices"][0]["message"]["content"]
            url = re.search(r'"source_url"\s*:\s*"([^"]+)"', text)
            em = re.search(r'"email"\s*:\s*"([^"@\s]+@[^"\s]+)"', text)
            src = url.group(1) if url else None
            if src:
                email = _official_email_on(src)
                if email:
                    return email, src
            # Many sheriff sites block scripts, so the page can't always be re-read. Accept the found address
            # only if it's on an official domain AND matches the official page it came from.
            if em and src:
                e = em.group(1).lower().rstrip(".")
                dom = e.split("@")[1]
                host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", src).split("/")[0].lower())
                official = dom.endswith((".gov", ".us")) or "sheriff" in dom or "police" in dom
                if official and (dom == host or dom.endswith("." + host) or host.endswith("." + dom) or host.endswith(dom)):
                    return e, src
            last_note = f"{model}: {text[:120]}"
        except Exception as e:
            last_note = f"{model}: {type(e).__name__} {str(e)[:100]}"
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
        if not re.search(r"\.gov|\.us/|\.us$|sheriff|police|county|city", link, re.I):
            continue
        try:
            page = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=20).text
        except Exception:
            continue
        for e in EMAIL_RX.findall(page):
            dom = e.split("@")[1].lower()
            if (dom.endswith(".gov") or dom.endswith(".us") or "sheriff" in dom or "police" in dom) and RECORDS_HINT.search(e):
                return e.lower(), link
    return None, None

def compose(lead, agency, signature):
    statute = STATUTES.get((agency.get("state") or lead.get("state") or "").upper(),
                           "your state's public records law")
    desc = llm.ask(
        "Write ONE short, neutral paragraph (2-3 sentences) identifying a police incident for a public records "
        "request: what happened, where, approximate date, and any names or case numbers given. No opinions. "
        "Output plain text only.",
        f"Title: {lead['title']}\nSummary: {lead.get('summary') or ''}\nDate: {lead.get('incident_date') or 'unknown'}\n"
        f"Agency: {agency['name']}", json_mode=False, max_tokens=250, temperature=0.2).strip()
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
    sent_today = db.select("records_requests", {"select": "agency_id", "sent_at": f"gte.{today}"})
    budget = cap - len(sent_today)
    per_agency = {}
    for s in sent_today:
        per_agency[s["agency_id"]] = per_agency.get(s["agency_id"], 0) + 1

    # fill in missing agency emails (a few per run, slow and polite)
    missing = db.select("agencies", {"records_email": "is.null", "portal_url": "is.null",
                                     "or": "(notes.is.null,notes.not.like.*email lookup failed*)", "limit": 8})
    found = 0
    for a in missing:
        email, src = find_records_email(a)
        if email:
            db.update("agencies", {"id": f"eq.{a['id']}"}, {"records_email": email, "notes": f"auto-found on {src}"})
            found += 1
        else:
            db.update("agencies", {"id": f"eq.{a['id']}"},
                      {"notes": ((a.get("notes") or "").split(" | ")[0] + " | email lookup failed – add email/portal on dashboard").strip(" |")})
            if LAST_LOOKUP_NOTE:
                db.alert("outreach", f"Email lookup failed for {a['name']}: {LAST_LOOKUP_NOTE}", "info")

    if budget <= 0:
        return f"daily cap reached ({cap}); found {found} agency emails"

    agencies = {a["name"].lower(): a for a in db.select("agencies", {"select": "*"})}
    leads = db.select("leads", {"status": "eq.new", "source_type": "in.(agency_release,news_tip,prosecutor_release)",
                                "order": "action_score.desc,created_at.desc", "limit": 40})
    sent, no_contact = 0, 0
    for lead in leads:
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
                    db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "skipped", "notes": "duplicate incident"})
                    continue
        subject, body = compose(lead, a, signature)
        res = send_email(a["records_email"], subject, body)
        db.insert("records_requests", {"lead_id": lead["id"], "agency_id": a["id"], "to_email": a["records_email"],
                                       "subject": subject, "body": body, "sent_at": _now(),
                                       "gmail_thread_id": res.get("threadId"), "status": "sent",
                                       "last_activity_at": _now()})
        db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "requested"})
        db.update("agencies", {"id": f"eq.{a['id']}"}, {"last_request_at": _now()})
        per_agency[a["id"]] = per_agency.get(a["id"], 0) + 1
        sent += 1
    return f"sent {sent} requests ({len(sent_today) + sent}/{cap} today); {no_contact} leads waiting on an agency email; found {found} new agency emails"
