"""Shared helpers for the Gleamstone agents. Gleamstone data lives in gs_* tables and gs_* settings,
so nothing here touches Ten-Four Tapes."""
import html
import math
import re
from datetime import datetime, timezone
from urllib.parse import quote_plus, unquote, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"}

SENDER_NAME = "Bobby at Gleamstone"
SENDER_EMAIL = "bobby@gleamstonecleaning.com"
SITE = "https://gleamstonecleaning.com"

RULES = """Gleamstone Commercial Cleaning rules (never break these):
- Gleamstone cleans offices, medical and dental suites, car dealerships and showrooms, and other small commercial
  spaces within 20 miles of Winchester, MA (01890). Evenings or early mornings, month-to-month, flat monthly price.
  It also does one-time post-construction, move-in and turnover cleans (flat price per job) for builders and
  property managers, and takes overflow or hard-to-staff accounts from other cleaning companies.
- Email only. Never offer a phone call, never ask anyone to call Bobby, never include a phone number.
- Never promise "the same crew" or the same cleaners every visit.
- Prices are competitive, but never quote a number in a first email. A quote comes after square footage and schedule.
- Short and plain. No hype words ("premier", "top-notch", "best-in-class", "unparalleled", "elevate").
- No real estate offers of any kind.
- Never spend money. Never sign anything.
- Sign as Bobby, Gleamstone Commercial Cleaning."""

# Towns within reach of Winchester, MA with approximate town-center coordinates.
TOWNS = {
    "Winchester": (42.452, -71.137), "Woburn": (42.479, -71.152), "Burlington": (42.505, -71.196),
    "Lexington": (42.447, -71.225), "Arlington": (42.415, -71.157), "Medford": (42.418, -71.106),
    "Stoneham": (42.480, -71.099), "Melrose": (42.458, -71.066), "Malden": (42.425, -71.066),
    "Everett": (42.408, -71.054), "Somerville": (42.388, -71.100), "Cambridge": (42.373, -71.110),
    "Boston": (42.360, -71.058), "Charlestown": (42.378, -71.061), "Chelsea": (42.392, -71.033),
    "Revere": (42.408, -71.012), "Saugus": (42.465, -71.010), "Wakefield": (42.506, -71.073),
    "Reading": (42.526, -71.095), "Lynnfield": (42.539, -71.048), "Lynn": (42.467, -70.949),
    "Swampscott": (42.471, -70.918), "Marblehead": (42.500, -70.858), "Salem": (42.519, -70.897),
    "Peabody": (42.528, -70.929), "Danvers": (42.575, -70.930), "Beverly": (42.558, -70.880),
    "Middleton": (42.595, -71.016), "North Reading": (42.575, -71.079), "Wilmington": (42.546, -71.174),
    "Tewksbury": (42.611, -71.234), "Billerica": (42.558, -71.269), "Bedford": (42.491, -71.276),
    "Concord": (42.460, -71.349), "Lincoln": (42.426, -71.304), "Belmont": (42.396, -71.179),
    "Watertown": (42.371, -71.183), "Waltham": (42.376, -71.236), "Newton": (42.337, -71.209),
    "Brookline": (42.332, -71.121), "Weston": (42.367, -71.303), "Wellesley": (42.297, -71.292),
    "Needham": (42.283, -71.233), "Dedham": (42.242, -71.166), "Westwood": (42.214, -71.224),
    "Quincy": (42.253, -71.002), "Milton": (42.250, -71.066), "Braintree": (42.222, -71.000),
    "Weymouth": (42.220, -70.940), "Andover": (42.658, -71.137), "North Andover": (42.699, -71.135),
    "Lawrence": (42.707, -71.163), "Methuen": (42.726, -71.191), "Lowell": (42.633, -71.316),
    "Dracut": (42.670, -71.302), "Chelmsford": (42.600, -71.367), "Westford": (42.579, -71.438),
    "Carlisle": (42.529, -71.350), "Acton": (42.485, -71.433), "Sudbury": (42.384, -71.416),
    "Wayland": (42.363, -71.361), "Natick": (42.283, -71.349), "Framingham": (42.279, -71.416),
    "Winthrop": (42.375, -70.983), "Nahant": (42.426, -70.927), "Topsfield": (42.637, -70.950),
    "Wenham": (42.604, -70.891), "Hamilton": (42.618, -70.857),
}
# What each kind of prospect is offered. Anything not listed gets the regular recurring-cleaning pitch.
PITCH = {
    "contractor": "They are a builder / general contractor. Offer one-time post-construction (final) cleans and "
                  "move-in cleans when a job wraps up: dust, debris, windows, floors, fixtures, ready for the owner "
                  "walkthrough. Flat price per job. Ask if they have a project finishing in the next month or two.",
    "property_manager": "They manage commercial or mixed-use buildings. Offer cleaning for common areas and tenant "
                        "suites, plus one-time move-in / turnover cleans when a space changes hands. Flat price. "
                        "Ask if any of their buildings or vacant suites need a cleaner right now.",
    "janitorial": "They are another cleaning company, not a customer. Offer to take overflow work: accounts they "
                  "can't staff, towns north of Boston they don't like driving to, or one-time jobs they'd rather "
                  "pass along. Gleamstone works under their name or its own, whichever they prefer. Never criticise "
                  "them. Ask if they ever turn down work north of Boston.",
}

FOLLOW_PITCH = {
    "contractor": ("If you have a job wrapping up in the next month or two, send me the address, rough square footage "
                   "and target date and I'll send a flat price for the final clean. Would that help?"),
    "property_manager": ("If one of your buildings needs a cleaner, or a suite needs a move-in or turnover clean, "
                         "send me the address and rough square footage and I'll send a flat price. Would that help?"),
    "janitorial": ("If you ever have an account north of Boston you can't staff, or a one-time job you'd rather "
                   "pass along, I'm glad to take it. Is it worth keeping my email on file?"),
}


def daily_cap(db):
    return int(db.setting("gs_daily_cap", 15) or 15)


def ramp_cap(db):
    """Grow gs_daily_cap a little each week so a young sending domain warms up slowly.
    gs_ramp = {"to": 40, "per_week": 5, "last": "YYYY-MM-DD", "hold": false}. "hold" (set when bounces or
    complaints come in) stops the growth; Bobby can still change the cap by hand in Settings."""
    ramp = db.setting("gs_ramp", None)
    if not isinstance(ramp, dict) or ramp.get("hold"):
        return None
    try:
        last = datetime.fromisoformat(ramp.get("last") or "2000-01-01").replace(tzinfo=timezone.utc)
    except Exception:
        return None
    cap, to = daily_cap(db), int(ramp.get("to", 40))
    if (now() - last).days < 7 or cap >= to:
        return None
    new = min(to, cap + int(ramp.get("per_week", 5)))
    db.insert("settings", {"key": "gs_daily_cap", "value": new}, upsert=True, on_conflict="key")
    db.insert("settings", {"key": "gs_ramp", "value": {**ramp, "last": now().date().isoformat()}},
              upsert=True, on_conflict="key")
    return new


STOP_STATUSES = {"replied", "interested", "quoted", "won", "lost", "do_not_contact"}


def now():
    return datetime.now(timezone.utc)


def miles(a, b):
    (la1, lo1), (la2, lo2) = a, b
    r = 3958.8
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = math.radians(la2 - la1), math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def home(db):
    return (float(db.setting("gs_home_lat", 42.4526)), float(db.setting("gs_home_lon", -71.1373)))


def radius(db):
    return float(db.setting("gs_radius_mi", 20))


def match_town(text):
    """Town name from free text, longest match first (so 'North Reading' beats 'Reading')."""
    t = (text or "").lower()
    for name in sorted(TOWNS, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", t):
            return name
    return None


def towns_in_range(db):
    h, r = home(db), radius(db)
    return [t for t, c in TOWNS.items() if miles(h, c) <= r]


def excluded(db):
    return [x.lower() for x in (db.setting("gs_excluded", []) or [])]


def is_excluded(db, name, _cache={}):
    if "x" not in _cache:
        _cache["x"] = excluded(db)
    n = (name or "").lower()
    return any(x and (x in n or n in x) for x in _cache["x"])


# ---------------- web ----------------
def fetch(url, limit=None, timeout=15):
    try:
        r = requests.get(url, headers=UA, timeout=timeout, allow_redirects=True)
        if r.status_code >= 300:
            return "", url
        return (r.text[:limit] if limit else r.text), r.url
    except Exception:
        return "", url


def page_text(raw, limit=6000):
    t = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", raw)
    t = html.unescape(re.sub(r"<[^>]+>", " ", t))
    return re.sub(r"\s+", " ", t).strip()[:limit]


def _ddg_html(q, n):
    r = requests.get("https://html.duckduckgo.com/html/", params={"q": q}, headers=UA, timeout=15)
    if r.status_code != 200:
        return None                                 # 202 = DuckDuckGo's bot page (common from cloud servers)
    out = []
    for u in re.findall(r'class="result__a"[^>]+href="([^"]+)"', r.text):
        m = re.search(r"uddg=([^&]+)", u)
        out.append(unquote(m.group(1)) if m else u)
    return out


def _ddg_lite(q, n):
    r = requests.post("https://lite.duckduckgo.com/lite/", data={"q": q}, headers=UA, timeout=15)
    if r.status_code != 200 or "anomaly" in r.text[:5000].lower():
        return None
    out = []
    for u in re.findall(r'<a[^>]+href="([^"]+)"[^>]*class=.result-link', r.text) + \
            re.findall(r"<a[^>]+class=.result-link[^>]*href=\"([^\"]+)\"", r.text):
        m = re.search(r"uddg=([^&]+)", u)
        out.append(unquote(m.group(1)) if m else u)
    return out


def _tavily(q, n, db=None):
    """Tavily free tier (1,000 searches/month, shared with Ten-Four Outreach): capped per day."""
    import os
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return None
    cap = 15
    used = {}
    if db is not None:
        try:
            cap = int(db.setting("gs_tavily_daily", 15) or 15)
            used = db.setting("gs_tavily_used", {}) or {}
        except Exception:
            pass
    day = now().strftime("%Y-%m-%d")
    if used.get(day, 0) >= cap:
        return None
    r = requests.post("https://api.tavily.com/search", json={"api_key": key, "query": q, "max_results": n}, timeout=30)
    if db is not None:
        try:
            db.insert("settings", {"key": "gs_tavily_used", "value": {day: used.get(day, 0) + 1}},
                      upsert=True, on_conflict="key")
        except Exception:
            pass
    return [x.get("url", "") for x in (r.json().get("results") or [])] if r.status_code < 300 else None


SEARCH_STATE = {"available": True}


def ddg(q, n=6, db=None):
    """Web search: DuckDuckGo first (free, no key), Tavily when DuckDuckGo blocks the server.
    SEARCH_STATE["available"] is False when no search engine could be asked at all (blocked + Tavily quota used),
    so callers can tell "nothing found" apart from "couldn't search"."""
    SEARCH_STATE["available"] = False
    for fn in (_ddg_html, _ddg_lite, lambda q, n: _tavily(q, n, db)):
        try:
            res = fn(q, n)
        except Exception:
            continue
        if res is None:                      # engine not usable right now (blocked / no key / daily cap)
            continue
        SEARCH_STATE["available"] = True
        out = [u for u in res if u.startswith("http") and "duckduckgo.com" not in u]
        if out:
            return out[:n]
    return []


def gnews(q, n=10):
    """Google News RSS -> [{title, text, url, date}]"""
    import feedparser
    try:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en")
        return [{"title": e.title, "text": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:400],
                 "url": e.link, "date": e.get("published", "")} for e in feed.entries[:n]]
    except Exception:
        return []


EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
FREE_MAIL = ("gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "comcast.net", "verizon.net")
JUNK = re.compile(r"(example|sentry|wixpress|domain\.com|email\.com|yourname|\.png|\.jpg|\.gif|\.webp|noreply|no-reply|"
                  r"donotreply|privacy|abuse|webmaster|postmaster|godaddy|squarespace|wordpress|cloudflare)", re.I)
GOOD_BOX = ("info", "office", "contact", "hello", "admin", "manager", "facilities", "operations", "frontdesk", "service")


def root_domain(url):
    host = urlparse(url if "//" in url else "https://" + url).netloc.lower()
    host = host.split(":")[0]
    return host[4:] if host.startswith("www.") else host


# Search engines, website builders and dealer/medical/gym website vendors. Their addresses show up in page footers
# and API pages but are never the business's own inbox (e.g. support@tavily.com, info@dealeressential.com).
VENDOR_DOMAINS = {
    "tavily.com", "duckduckgo.com", "google.com", "bing.com",
    "dealeressential.com", "dealer.com", "dealerinspire.com", "dealeron.com", "dealerfire.com", "dealersocket.com",
    "dealereprocess.com", "dealercenter.com", "dealerspike.com", "dealerspecialties.com", "cdk.com", "cdkglobal.com",
    "foxdealer.com", "sincrodigital.com", "autorevo.com", "autotrader.com", "carsforsale.com", "drivecentric.com",
    "reyrey.com", "reyrey.net", "fusionzone.com", "jazelauto.com", "dealervenom.com", "overfuel.com",
    "wix.com", "wixsite.com", "squarespace.com", "godaddy.com", "secureserver.net", "wordpress.com", "wpengine.com",
    "weebly.com", "shopify.com", "duda.co", "webflow.io", "hubspot.com", "mailchimp.com", "constantcontact.com",
    "yext.com", "scorpion.co", "thryv.com", "hibu.com", "birdeye.com", "podium.com", "sentry.io", "cloudflare.com",
    "mindbodyonline.com", "mindbody.io", "glofox.com", "clubready.com", "abcfitness.com", "zenplanner.com",
    "officite.com", "prosites.com", "pbhs.com", "weave.com", "solutionreach.com", "nexhealth.com", "patientpop.com",
    "tebra.com", "doctible.com", "lighthouse360.com", "demandforce.com", "zocdoc.com", "healthgrades.com",
}
_MULTI_TLD = ("co.uk", "com.au", "co.nz", "co.ca")


def reg_domain(host):
    """'mail.sales.bostonvw.com' -> 'bostonvw.com' (the part a business actually registers)."""
    host = (host or "").lower().strip(". ")
    host = host[4:] if host.startswith("www.") else host
    parts = host.split(".")
    n = 3 if any(host.endswith("." + t) for t in _MULTI_TLD) else 2
    return ".".join(parts[-n:]) if len(parts) >= n else host


def is_vendor(url_or_domain):
    d = url_or_domain or ""
    d = root_domain(d) if ("/" in d or ":" in d) else d
    return reg_domain(d) in VENDOR_DOMAINS


def email_matches_site(email, site):
    """True only when the address is on the business's own domain (same registered domain as its website),
    or a free-mail inbox (gmail etc.) - never a search engine or website vendor."""
    if not email or "@" not in email:
        return False
    dom = reg_domain(email.split("@")[1])
    if dom in VENDOR_DOMAINS:
        return False
    if dom in FREE_MAIL:
        return True
    return bool(site) and not is_vendor(site) and dom == reg_domain(root_domain(site))


def emails_on(raw, site_domain):
    """Addresses printed on a business's own page, best first. Must be on the site's own registered domain
    (or a free-mail address printed on the site itself). Nothing is taken from a vendor/search-engine page."""
    found = []
    if not site_domain or is_vendor(site_domain):
        return found
    for e in set(EMAIL_RX.findall(html.unescape(raw)) + re.findall(r"mailto:([^\"'?>\s]+)", raw)):
        e = unquote(e).strip(".,;:").lower()
        if JUNK.search(e) or "@" not in e:
            continue
        if not email_matches_site(e, site_domain):
            continue
        found.append(e)
    def rank(e):
        box = e.split("@")[0]
        return (0 if any(box.startswith(g) for g in GOOD_BOX) else 1, len(e))
    return sorted(set(found), key=rank)


# ---------------- email (Brevo free tier: 300/day) ----------------
def brevo_key():
    import os
    return os.environ.get("BREVO_API_KEY")


def send(to, subject, body, reply_to_id=None):
    import os
    if os.environ.get("DRY_RUN") == "1":
        print(f"[DRY_RUN] gleamstone email to {to}: {subject}")
        return "dry-run"
    key = brevo_key()
    if not key:
        raise RuntimeError("BREVO_API_KEY not set")
    payload = {"sender": {"name": SENDER_NAME, "email": SENDER_EMAIL}, "to": [{"email": to}],
               "replyTo": {"email": SENDER_EMAIL, "name": SENDER_NAME},
               "subject": subject, "textContent": body}
    if reply_to_id:
        payload["headers"] = {"In-Reply-To": reply_to_id, "References": reply_to_id}
    r = requests.post("https://api.brevo.com/v3/smtp/email", json=payload, timeout=30,
                      headers={"api-key": key, "accept": "application/json", "content-type": "application/json"})
    if r.status_code >= 300:
        raise RuntimeError(f"Brevo {r.status_code}: {r.text[:200]}")
    return r.json().get("messageId", "")


def brevo_events(event, days=7):
    key = brevo_key()
    if not key:
        return []
    try:
        r = requests.get("https://api.brevo.com/v3/smtp/statistics/events", timeout=30,
                         params={"event": event, "days": days, "limit": 500},
                         headers={"api-key": key, "accept": "application/json"})
        return r.json().get("events", []) if r.status_code < 300 else []
    except Exception:
        return []


def footer(db):
    addr = (db.setting("gs_mailing_address", "") or "").strip()
    lines = ["", "Bobby", "Gleamstone Commercial Cleaning", SITE]
    if addr:
        lines.append(addr)
    lines += ["", "If you'd rather not hear from me, reply \"no thanks\" and I won't email again."]
    return "\n".join(lines)


def strip_footer(body):
    return body.split("\n\nBobby\nGleamstone Commercial Cleaning")[0].rstrip()
