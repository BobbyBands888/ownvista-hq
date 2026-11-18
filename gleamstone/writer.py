"""WRITER — drafts every Gleamstone email.
  1. Intro emails for prospects that have a verified address (best fit first).
  2. Answers to replies you log on the dashboard: reads the reply, updates the prospect, drafts a response.
Everything goes to Approve on the dashboard while approvals are on. Follow-ups are written by the Sender."""
import re

from agents.lib import llm
from . import common as c

INTRO = c.RULES + """

Write a first cold email from Bobby, owner of Gleamstone Commercial Cleaning, to the business below.
- Under 110 words in the body. Plain text, no bullet points, no links in the body.
- If there is a "why now" signal (new lease, opening, move), open with it in one plain line. Don't overdo it.
- Say what Gleamstone does for a space like theirs in one or two sentences (after-hours cleaning, written checklist,
  flat monthly price, month-to-month, Bobby answers emails directly).
- Offer a free walkthrough or a quote from rough square footage and schedule.
- End with ONE simple question.
- Greeting: "Hi {contact first name}," if a contact name is given, otherwise "Hi there,".
- Do NOT write a sign-off or signature (it's added automatically).
- Subject: short, lowercase-ish, specific to them, no clickbait (e.g. "cleaning for the new Woburn office").
Return JSON {"subject":"...","body":"..."}"""

REPLY = c.RULES + """

A prospect replied to Gleamstone. Read their reply and the thread, then:
1. Classify it: interested | question | not_now | not_interested | unsubscribe | wrong_person | other
2. Draft Bobby's answer (unless unsubscribe/not_interested, then a one-line polite close is fine, or empty for unsubscribe).
   - Under 120 words, plain, friendly. Answer exactly what they asked. Never invent prices, dates, insurance details
     or facts not given. If they want a price, ask for what's missing (address, rough square footage, how often,
     restrooms, floor types) or offer a short walkthrough at a time that suits them.
   - If they pointed to someone else, thank them and ask for that person's email.
   - No sign-off (added automatically).
Return JSON {"label":"...","subject":"Re: ...","body":"...","summary":"one line for Bobby"}"""

BANNED = re.compile(r"\bcall (me|us)\b|phone|\(\d{3}\)|\d{3}[-.]\d{3}[-.]\d{4}|same crew|same team every|"
                    r"premier|top-notch|best-in-class|unparalleled|elevate", re.I)


def _clean(body):
    body = (body or "").strip()
    body = re.sub(r"\n+(best|thanks|thank you|regards|cheers|sincerely)[,!]?\s*\n.*$", "", body, flags=re.I | re.S)
    return body.strip()


def draft_intro(db, p):
    facts = {k: p.get(k) for k in ("name", "town", "category", "address", "signal", "sqft", "contact_name", "website")}
    for attempt in range(2):
        res = llm.ask(INTRO, str(facts) + ("\nYour last draft broke a rule. Follow every rule." if attempt else ""),
                      max_tokens=900, temperature=0.5)
        subj, body = (res or {}).get("subject", "").strip(), _clean((res or {}).get("body", ""))
        if subj and body and not BANNED.search(body + " " + subj) and len(body.split()) <= 140:
            return subj[:90], body
    raise RuntimeError(f"intro for {p['name']} kept breaking the rules")


def handle_reply(db, inbound, approve):
    p = db.select("gs_prospects", {"id": f"eq.{inbound['prospect_id']}"})
    p = p[0] if p else {}
    thread = db.select("gs_emails", {"prospect_id": f"eq.{inbound['prospect_id']}", "status": "in.(sent,logged)",
                                     "order": "created_at.asc", "limit": 10})
    hist = "\n\n".join(f"[{'Bobby' if e['direction'] == 'out' else 'Them'}] {c.strip_footer(e['body'] or '')}" for e in thread)
    res = llm.ask(REPLY, f"Business: {p.get('name')} ({p.get('town')})\nThread so far:\n{hist}\n\nNEW REPLY:\n{inbound['body']}",
                  max_tokens=1000, temperature=0.3) or {}
    label = res.get("label", "other")
    status = {"interested": "interested", "question": "replied", "not_now": "lost", "not_interested": "lost",
              "unsubscribe": "do_not_contact", "wrong_person": "replied"}.get(label, "replied")
    if p:
        db.update("gs_prospects", {"id": f"eq.{p['id']}"}, {"status": status})
    # any follow-up still waiting is cancelled the moment they reply
    db.update("gs_emails", {"prospect_id": f"eq.{inbound['prospect_id']}", "status": "eq.draft", "kind": "eq.followup"},
              {"status": "cancelled", "note": "they replied"})
    db.update("gs_emails", {"id": f"eq.{inbound['id']}"}, {"note": f"handled: {label} — {res.get('summary', '')}"[:300]})
    body = _clean(res.get("body", ""))
    if label != "unsubscribe" and body and p.get("email"):
        last_out = next((e for e in reversed(thread) if e["direction"] == "out"), None)
        db.insert("gs_emails", {"prospect_id": p["id"], "direction": "out", "kind": "reply", "step": 9,
                                "to_email": p["email"], "subject": res.get("subject") or f"Re: {last_out['subject'] if last_out else ''}",
                                "body": body, "approval_status": "pending",
                                "note": f"Their reply: {label}. {res.get('summary', '')}"[:300]})
    level = "urgent" if label == "interested" else "info"
    db.alert("gs_writer", f"{p.get('name', 'A prospect')} replied ({label.replace('_', ' ')}): {res.get('summary', '')}", level)
    return label


def main(db):
    approve = bool(db.setting("gs_approvals", True))
    cap = int(db.setting("gs_daily_cap", 15) or 15)
    out = []
    # replies first
    inbound = db.select("gs_emails", {"direction": "eq.in", "note": "is.null", "limit": 10})
    for m in inbound:
        out.append(handle_reply(db, m, approve))
    # keep about two days of intros ready to go, no more
    waiting = db.select("gs_emails", {"kind": "eq.intro", "status": "eq.draft", "select": "id", "limit": 200})
    room = max(0, cap * 2 - len(waiting))
    made = 0
    if room:
        rows = db.select("gs_prospects", {"status": "eq.new", "email": "not.is.null",
                                          "order": "fit_score.desc,signal_date.desc.nullslast,created_at.asc",
                                          "limit": min(room, 10)})
        for p in rows:
            if c.is_excluded(db, p["name"]):
                db.update("gs_prospects", {"id": f"eq.{p['id']}"}, {"status": "do_not_contact"})
                continue
            if c.is_vendor(p["email"].split("@")[-1]):     # last guard: never draft to a vendor's inbox
                db.update("gs_prospects", {"id": f"eq.{p['id']}"},
                          {"email": None, "status": "no_email", "enrich_tries": 2,
                           "notes": f"dropped {p['email']} (website vendor, not the business)"})
                continue
            try:
                subj, body = draft_intro(db, p)
            except Exception as e:
                db.alert("gs_writer", str(e)[:200], "info")
                continue
            db.insert("gs_emails", {"prospect_id": p["id"], "kind": "intro", "step": 0, "to_email": p["email"],
                                    "subject": subj, "body": body,
                                    "approval_status": "pending" if approve else "approved"})
            db.update("gs_prospects", {"id": f"eq.{p['id']}"}, {"status": "drafted"})
            made += 1
    return f"{made} intro drafts, {len(out)} replies handled" + (f" ({', '.join(out)})" if out else "")
