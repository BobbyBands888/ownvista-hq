"""CONTACT FINDER — finds a real email address for each prospect.
Only accepts an address printed on the business's own website (or on its map listing). Never guesses
addresses like info@domain. Two tries, then the prospect is parked as "no email" (you can add one by hand)."""
import re
from urllib.parse import urljoin

from . import common as c

PER_RUN = 15
DIRECTORIES = re.compile(r"yelp|facebook|instagram|linkedin|yellowpages|bbb\.org|mapquest|manta|bizapedia|"
                         r"opencorporates|zoominfo|indeed|glassdoor|cars\.com|cargurus|dealerrater|edmunds|"
                         r"healthgrades|zocdoc|vitals|webmd|google\.|bing\.|apple\.com|tripadvisor|patch\.com|"
                         r"bostonglobe|wikipedia|loopnet|crexi|costar|wickedlocal|bizjournals", re.I)


def find_site(p):
    if p.get("website"):
        return p["website"]
    q = f'{p["name"]} {p.get("town") or ""} MA'
    for u in c.ddg(q, n=8):
        if DIRECTORIES.search(u):
            continue
        return u
    return None


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
    for u in list(dict.fromkeys(cand))[:4]:
        if c.root_domain(u) != dom:
            continue
        sub, _ = c.fetch(u, limit=400000)
        hits = c.emails_on(sub, dom)
        if hits:
            return hits[0], u, final
    return None, None, final


def main(db):
    rows = db.select("gs_prospects", {"status": "eq.new", "email": "is.null", "enrich_tries": "lt.2",
                                      "order": "fit_score.desc,created_at.asc", "limit": PER_RUN})
    found = 0
    for p in rows:
        site = find_site(p)
        email = src = None
        if site:
            email, src, site = find_email(site)
        upd = {"enrich_tries": (p.get("enrich_tries") or 0) + 1, "website": site or p.get("website")}
        if email:
            upd.update(email=email, email_source=src)
            found += 1
        elif upd["enrich_tries"] >= 2:
            upd["status"] = "no_email"
        db.update("gs_prospects", {"id": f"eq.{p['id']}"}, upd)
    return f"checked {len(rows)} prospects, found {found} emails"
