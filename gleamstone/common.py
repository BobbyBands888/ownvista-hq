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


def ddg(q, n=6):
    try:
        r = requests.get("https://html.duckduckgo.com/html/", params={"q": q}, headers=UA, timeout=15)
        urls = re.findall(r'class="result__a"[^>]+href="([^"]+)"', r.text)
        out = []
        for u in urls:
            m = re.search(r"uddg=([^&]+)", u)
            out.append(unquote(m.group(1)) if m else u)
        return [u for u in out if u.startswith("http") and "duckduckgo.com" not in u][:n]
    except Exception:
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


def emails_on(raw, site_domain):
    """Addresses printed on a business's own page, best first. Must be on the site's domain (or a free-mail
    address printed on the site itself)."""
    found = []
    for e in set(EMAIL_RX.findall(html.unescape(raw)) + re.findall(r"mailto:([^\"'?>\s]+)", raw)):
        e = unquote(e).strip(".,;:").lower()
        if JUNK.search(e) or "@" not in e:
            continue
        dom = e.split("@")[1]
        if not (dom == site_domain or dom.endswith("." + site_domain) or site_domain.endswith(dom) or dom in FREE_MAIL):
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
