"""INBOX — reads bobby@gleamstonecleaning.com (Zoho Mail, IMAP) and logs prospects' replies.

Replies to our cold emails land in Zoho (Brevo sends with Reply-To = the Zoho address). Until now HQ only knew
about a reply if someone logged it by hand, so follow-ups kept going to people who had already answered.

Every run (hourly):
- reads the last few days of the inbox, read-only (messages stay unread for Bobby)
- matches the sender to a prospect: same email address, or same business domain (never a gmail-type domain)
- logs it as an inbound gs_emails row; the Writer then classifies it, drafts Bobby's answer for approval and
  cancels pending follow-ups for that prospect
- out-of-office / auto-replies are logged as handled (no answer drafted); bounces are left to the Sender
- a reply from someone we can't match raises one alert so Bobby can look at it

Needs GitHub secrets ZOHO_IMAP_USER (bobby@gleamstonecleaning.com) and ZOHO_IMAP_PASSWORD (a Zoho app password).
Without them it does nothing."""
import email
import email.utils
import imaplib
import os
import re
from datetime import timedelta
from email.header import decode_header, make_header

from . import common as c

HOST = os.environ.get("ZOHO_IMAP_HOST", "imap.zoho.com")
DAYS = 7
SKIP_FROM = re.compile(r"mailer-daemon|postmaster|no-?reply|donotreply|notifications?@|zoho\.com$", re.I)
AUTO = re.compile(r"out of (the )?office|automatic reply|auto(matic)?[- ]?reply|autoreply|away from (the|my) office|"
                  r"on vacation|undeliverable|delivery status", re.I)


def _h(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return v or ""


def _text(msg):
    """Plain-text body of the message (falls back to stripped HTML)."""
    parts = msg.walk() if msg.is_multipart() else [msg]
    plain = html_part = None
    for p in parts:
        if p.get_content_maintype() == "multipart" or (p.get("Content-Disposition") or "").startswith("attachment"):
            continue
        try:
            raw = p.get_payload(decode=True)
            if raw is None:
                continue
            s = raw.decode(p.get_content_charset() or "utf-8", "replace")
        except Exception:
            continue
        if p.get_content_type() == "text/plain" and plain is None:
            plain = s
        elif p.get_content_type() == "text/html" and html_part is None:
            html_part = s
    if plain is None and html_part:
        plain = c.page_text(html_part, 20000)
    return plain or ""


def new_part(body):
    """Just what they wrote: cut the quoted thread below the reply."""
    out = []
    for line in body.replace("\r", "").split("\n"):
        s = line.strip()
        if s.startswith(">"):
            break
        if re.match(r"^(on .{5,120} wrote:|-{2,} ?original message ?-{2,}|from: .+|sent from my (iphone|android))",
                     s, re.I):
            break
        if re.match(r"^_{5,}$", s):
            break
        out.append(line.rstrip())
    text = "\n".join(out).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:4000] or body.strip()[:4000]


def match_prospect(db, addr):
    addr = (addr or "").lower().strip()
    if not addr or "@" not in addr:
        return None
    rows = db.select("gs_prospects", {"email": f"eq.{addr}", "limit": 1})
    if rows:
        return rows[0]
    dom = c.reg_domain(addr.split("@")[1])
    if dom in c.FREE_MAIL or dom in c.VENDOR_DOMAINS:
        return None                      # a gmail address only counts when it's the exact one we wrote to
    for p in db.select("gs_prospects", {"email": f"ilike.*@*{dom}", "limit": 5}):
        if c.reg_domain((p.get("email") or "@").split("@")[1]) == dom:
            return p
    for p in db.select("gs_prospects", {"website": f"ilike.*{dom}*", "limit": 5}):
        if c.reg_domain(c.root_domain(p.get("website") or "")) == dom:
            return p
    return None


def fetch(days=DAYS):
    user, pw = os.environ.get("ZOHO_IMAP_USER"), os.environ.get("ZOHO_IMAP_PASSWORD")
    if not (user and pw):
        return None
    m = imaplib.IMAP4_SSL(HOST, 993, timeout=60)
    try:
        m.login(user, pw)
        m.select("INBOX", readonly=True)            # read-only: nothing gets marked as read
        since = (c.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        typ, data = m.search(None, "SINCE", since)
        out = []
        for num in (data[0].split() if data and data[0] else [])[-200:]:
            typ, msg_data = m.fetch(num, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            name, addr = email.utils.parseaddr(_h(msg.get("From")))
            out.append({"msg_id": (msg.get("Message-ID") or "").strip() or f"imap-{num.decode()}-{_h(msg.get('Date'))}",
                        "from": addr.lower(), "name": name, "subject": _h(msg.get("Subject")),
                        "auto": bool(msg.get("Auto-Submitted", "no").lower() != "no" or msg.get("X-Autoreply")
                                     or (msg.get("Precedence", "").lower() in ("auto_reply", "bulk", "junk"))),
                        "body": _text(msg)})
        return out
    finally:
        try:
            m.logout()
        except Exception:
            pass


def main(db):
    msgs = fetch()
    if msgs is None:
        return "Zoho inbox not connected yet (add ZOHO_IMAP_USER and ZOHO_IMAP_PASSWORD secrets)"
    seen = set(db.setting("gs_inbox_seen", []) or [])
    logged = auto = unknown = 0
    me = c.SENDER_EMAIL.lower()
    for mm in msgs:
        mid = mm["msg_id"]
        if mid in seen or mm["from"] == me or SKIP_FROM.search(mm["from"]):
            seen.add(mid)
            continue
        if db.select("gs_emails", {"provider_id": f"eq.{mid}", "select": "id", "limit": 1}):
            seen.add(mid)
            continue
        p = match_prospect(db, mm["from"])
        if not p:
            if mm["subject"].lower().startswith(("re:", "re :", "aw:")):
                db.alert("gs_inbox", f"Reply in Zoho from {mm['from']} we couldn't match to a prospect: "
                                     f"\"{mm['subject'][:80]}\" — check bobby@gleamstonecleaning.com", "warn")
                unknown += 1
            seen.add(mid)
            continue
        if db.select("gs_emails", {"prospect_id": f"eq.{p['id']}", "direction": "eq.in", "provider_id": "is.null",
                                   "subject": f"eq.{mm['subject'][:200]}", "select": "id", "limit": 1}):
            seen.add(mid)                  # already logged by hand on the dashboard
            continue
        is_auto = mm["auto"] or bool(AUTO.search(mm["subject"]))
        db.insert("gs_emails", {"prospect_id": p["id"], "direction": "in", "kind": "inbound",
                                "to_email": me, "subject": mm["subject"][:200], "body": new_part(mm["body"]),
                                "approval_status": "approved", "status": "logged", "provider_id": mid,
                                "note": "handled: auto-reply (out of office)" if is_auto else None})
        if is_auto:
            auto += 1
        else:
            logged += 1
        seen.add(mid)
    db.insert("settings", {"key": "gs_inbox_seen", "value": sorted(seen)[-500:]}, upsert=True, on_conflict="key")
    return f"read {len(msgs)} inbox emails: {logged} replies logged, {auto} auto-replies, {unknown} unmatched"
