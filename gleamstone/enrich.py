"""CONTACT FINDER — finds a real email address for each prospect.
Only accepts an address printed on the business's own website (or on its map listing), on that website's own
domain (or a free-mail inbox). Search-engine and website-vendor addresses (tavily.com, dealeressential.com...) are
never kept. Never guesses
addresses like info@domain. Two tries, then the prospect is parked as "no email" (you can add one by hand)."""
import re
from urllib.parse import urljoin, urlparse

from . import common as c

PER_RUN = 25
DIRECTORIES = re.compile(r"yelp|facebook|instagram|linkedin|yellowpages|bbb\.org|mapquest|manta|bizapedia|"
                         r"opencorporates|zoominfo|indeed|glassdoor|cars\.com|cargurus|dealerrater|edmunds|"
                         r"healthgrades|zocdoc|vitals|webmd|google\.|bing\.|apple\.com|tripadvisor|patch\.com|"
                         r"bostonglobe|wikipedia|loopnet|crexi|costar|wickedlocal|bizjournals", re.I)


STOP_WORDS = {"the", "of", "and", "at", "inc", "llc", "co", "corp", "company", "pc", "pllc", "ltd", "group", "center",
              "centre", "dmd", "dds", "md", "&", "-", "a", "in", "for", "ma", "massachusetts"}


def _words(name):
    return [w for w in re.findall(r"[a-z0-9]+", (name or "").lower().replace("&", " and ")) if w not in STOP_WORDS]


def guess_site(p):
    """Free first try (no search engine needed): the business's likely own domain, e.g. "Lexington Toyota" ->
    lexingtontoyota.com. Only accepted when the page itself shows the business's name, so a guess is never trusted
    blindly. Email addresses are still only taken when printed on that site."""
    words = _words(p.get("name"))
    if not words:
        return None
    town = re.sub(r"[^a-z]", "", (p.get("town") or "").lower())
    slugs = ["".join(words), "-".join(words)]
    if len(words) > 2:
        slugs.append("".join(words[:2]))
    if town and town not in "".join(words):
        slugs.append("".join(words) + town)
    tried = set()
    for slug in slugs:
        for tld in (".com", ".net"):
            dom = slug + tld
            if dom in tried or len(slug) < 4:
                continue
            tried.add(dom)
            raw, final = c.fetch("https://" + dom, limit=200000, timeout=8)
            if not raw:
                continue
            txt = c.page_text(raw, 20000).lower()
            hits = sum(1 for w in words if w in txt)
            if hits >= max(1, (len(words) + 1) // 2) and (not town or town in txt.replace(" ", "") or hits == len(words)):
                return final or "https://" + dom
    return None


def find_site(p, db=None):
    """-> (site or None, searched): searched is False when no search engine could be asked this time."""
    if p.get("website") and not c.is_vendor(p["website"]):
        return p["website"], True
    g = guess_site(p)
    if g:
        return g, True
    q = f'{p["name"]} {p.get("town") or ""} MA'
    for u in c.ddg(q, n=8, db=db):
        if DIRECTORIES.search(u) or c.is_vendor(u):
            continue
        return u, True
    return None, c.SEARCH_STATE["available"]


def find_email(site):
    raw, final = c.fetch(site, limit=400000)
    if not raw:
        return None, None, site
    dom = c.root_domain(final or site)
    hits = c.emails_on(raw, dom)
    if hits:
        return hits[0], final, final
    links = re.findall(r'href=["\']([^"\']+)["\']', raw)
    cand = [urljoin(final, l) for l in links if re.search(r"contact|about|team|staff|location|reach", l, re.I)]
    base = f"{urlparse(final).scheme}://{urlparse(final).netloc}"
    cand += [base + p for p in ("/contact", "/contact-us", "/contact/", "/about", "/about-us")]
    for u in list(dict.fromkeys(cand))[:7]:
        if c.root_domain(u) != dom:
            continue
        sub, _ = c.fetch(u, limit=400000)
        hits = c.emails_on(sub, dom)
        if hits:
            return hits[0], u, final
    return None, None, final


def main(db):
    if not db.setting("gs_enrich_v3"):
        # one time: prospects parked as "no email" because the daily search allowance ran out (not a real miss)
        for p in db.select("gs_prospects", {"status": "eq.no_email", "select": "id", "limit": 1000}):
            db.update("gs_prospects", {"id": f"eq.{p['id']}"}, {"status": "new", "enrich_tries": 0})
        db.insert("settings", {"key": "gs_enrich_v3", "value": True}, upsert=True, on_conflict="key")
    if not db.setting("gs_email_domain_v1"):
        # one time: drop saved emails that aren't on the business's own domain (support@tavily.com etc.)
        for p in db.select("gs_prospects", {"status": "eq.new", "email": "not.is.null",
                                            "select": "id,email,website,email_source", "limit": 2000}):
            if not (p.get("email_source") or "").startswith("http"):
                continue                           # only Contact Finder's own finds; hand-added/Apollo/map ones stay
            if not c.email_matches_site(p["email"], p.get("website")):
                db.update("gs_prospects", {"id": f"eq.{p['id']}"},
                          {"email": None, "email_source": None, "status": "no_email", "enrich_tries": 2,
                           "notes": f"dropped {p['email']} (not the business's own domain)"})
        db.insert("settings", {"key": "gs_email_domain_v1", "value": True}, upsert=True, on_conflict="key")
    rows = db.select("gs_prospects", {"status": "eq.new", "email": "is.null", "enrich_tries": "lt.2",
                                      "order": "enrich_tries.asc,fit_score.desc,created_at.asc", "limit": PER_RUN})
    found = 0
    why = {"no website found": 0, "site wouldn't load": 0, "no email printed on site": 0, "search used up today": 0}
    for p in rows:
        site, searched = find_site(p, db)
        if not site and not searched:
            why["search used up today"] += 1       # not the business's fault: never park it for this
            db.update("gs_prospects", {"id": f"eq.{p['id']}"}, {"enrich_tries": 1})   # just lets fresh ones go first
            continue
        email = src = None
        if site:
            raw_ok = True
            email, src, site = find_email(site)
            if not email:
                raw_ok = bool(c.fetch(site, limit=2000)[0])
                why["no email printed on site" if raw_ok else "site wouldn't load"] += 1
        else:
            why["no website found"] += 1
        upd = {"enrich_tries": (p.get("enrich_tries") or 0) + 1, "website": site or p.get("website")}
        if email and not c.email_matches_site(email, site):
            email = None                           # belt and braces: never keep a vendor/other-domain address
        if email:
            upd.update(email=email, email_source=src)
            found += 1
        elif upd["enrich_tries"] >= 2:
            upd["status"] = "no_email"
        db.update("gs_prospects", {"id": f"eq.{p['id']}"}, upd)
    misses = ", ".join(f"{k} {v}" for k, v in why.items() if v)
    return f"checked {len(rows)} prospects, found {found} emails" + (f" (missed: {misses})" if misses else "")
