"""PROSPECT SCOUT — finds businesses that need a cleaner, within the service radius of Winchester.

Two lanes:
  lease_news (every 6h): Google News for leases signed, new offices, openings and moves in towns in range.
      A business that just leased space needs cleaning set up. Tracked over time, never re-added.
  map (weekly): OpenStreetMap listings for car dealerships, medical/dental offices, gyms and offices in range.
      Many OSM listings carry the website or email already.
Excluded names (gs_excluded setting) and anything marked do-not-contact are never re-added."""
from datetime import timedelta
from email.utils import parsedate_to_datetime

import requests

from agents.lib import llm
from . import common as c

QUERIES = ['"{t}" MA "signed a lease"', '"{t}" MA lease office space company', '"{t}" MA "new office" opens',
           '"{t}" MA "coming soon" OR "grand opening" business', '"{t}" Massachusetts dealership OR clinic opening']
TOWNS_PER_RUN = 6

EXTRACT = """You read local news headlines and snippets and pick out businesses that would need an outside commercial
cleaning company soon: they just signed a lease, are moving into new space, opening, expanding, or renovating offices.
Good fits: offices, medical/dental suites, clinics, car dealerships and showrooms, gyms, banks, small retail, co-working,
light industrial with offices. Skip: restaurants (they clean in-house), schools, government, hospitals, churches,
homes and apartments, big-box chains, anything already closed, anything outside Massachusetts.
Only use what the text says. Never invent a business or a square footage.
Return JSON: {"businesses":[{"name":"...","town":"...","category":"office|medical|dealership|showroom|retail|gym|warehouse|other",
"signal":"short plain sentence: what happened and where","sqft":number or null,"address":"if printed, else null",
"item":index of the news item it came from,"fit":1-10}]}. Empty list if none."""


def _date(s):
    try:
        return parsedate_to_datetime(s)
    except Exception:
        return None


def _known(db):
    rows = db.select("gs_prospects", {"select": "name,town", "limit": 10000})
    return {((r["name"] or "").lower().strip(), (r.get("town") or "").lower()) for r in rows}


def _add(db, rows, limit=None):
    known = _known(db)
    out = []
    for r in rows:
        k = (r["name"].lower().strip(), (r.get("town") or "").lower())
        if not r["name"].strip() or k in known or c.is_excluded(db, r["name"]):
            continue
        known.add(k)
        out.append(r)
        if limit and len(out) >= limit:
            break
    for i in range(0, len(out), 50):
        db.insert("gs_prospects", out[i:i + 50])
    return len(out)


def lease_news(db):
    towns = c.towns_in_range(db)
    cur = int(db.setting("gs_scout_cursor", 0) or 0)
    pick = [towns[(cur + i) % len(towns)] for i in range(TOWNS_PER_RUN)]
    db.insert("settings", {"key": "gs_scout_cursor", "value": (cur + TOWNS_PER_RUN) % len(towns),
                           "updated_at": c.now()}, upsert=True, on_conflict="key")
    cutoff = c.now() - timedelta(days=120)
    items, seen = [], set()
    for t in pick:
        for q in QUERIES:
            for it in c.gnews(q.format(t=t), n=8):
                d = _date(it["date"])
                if (d and d < cutoff) or it["title"] in seen:
                    continue
                seen.add(it["title"])
                items.append(it)
    if not items:
        return 0, pick
    found = []
    h, rad = c.home(db), c.radius(db)
    for i in range(0, len(items), 25):
        batch = items[i:i + 25]
        listing = "\n".join(f"[{j}] {x['title']} — {x['text'][:240]} ({x['date'][:16]})" for j, x in enumerate(batch))
        try:
            res = llm.ask(EXTRACT, listing, max_tokens=2500, temperature=0.1)
        except Exception as e:
            db.alert("gs_scout", f"news read failed: {str(e)[:160]}", "info")
            continue
        for b in (res or {}).get("businesses", []) or []:
            town = c.match_town(b.get("town") or "") or c.match_town(b.get("address") or "")
            if not town or not b.get("name"):
                continue
            dist = c.miles(h, c.TOWNS[town])
            if dist > rad:
                continue
            src = batch[b["item"]] if isinstance(b.get("item"), int) and 0 <= b["item"] < len(batch) else {}
            d = _date(src.get("date", ""))
            found.append({"name": b["name"][:120], "town": town, "category": b.get("category") or "other",
                          "address": b.get("address"), "signal": (b.get("signal") or "")[:300],
                          "sqft": b.get("sqft") if isinstance(b.get("sqft"), int) else None,
                          "source": "lease_news", "source_url": src.get("url"),
                          "signal_date": d.date().isoformat() if d else None,
                          "lat": c.TOWNS[town][0], "lon": c.TOWNS[town][1], "distance_mi": round(dist, 1),
                          "fit_score": max(1, min(10, int(b.get("fit") or 6)))})
    return _add(db, found), pick


# ---------------- map lane (OpenStreetMap, free) ----------------
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://lz4.overpass-api.de/api/interpreter",
            "https://z.overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter", "https://overpass.kumi.systems/api/interpreter"]
MAP_KINDS = [  # (osm filter, category, base fit)
    ('["shop"="car"]', "dealership", 7),
    ('["amenity"="dentist"]', "medical", 7),
    ('["amenity"="doctors"]', "medical", 7),
    ('["amenity"="clinic"]', "medical", 6),
    ('["healthcare"="physiotherapist"]', "medical", 6),
    ('["leisure"="fitness_centre"]', "gym", 6),
    ('["office"~"insurance|lawyer|accountant|financial|consulting|it|company|architect|engineer"]', "office", 5),
]
def _classify(tg):
    if tg.get("shop") == "car":
        return "dealership", 7
    if tg.get("amenity") in ("dentist", "doctors"):
        return "medical", 7
    if tg.get("amenity") == "clinic" or tg.get("healthcare"):
        return "medical", 6
    if tg.get("leisure") == "fitness_centre":
        return "gym", 6
    return "office", 5


CHAINS = ("planet fitness", "cvs", "walgreens", "mass general", "beth israel", "brigham", "minuteclinic")


def _overpass(q, deadline):
    """Public Overpass servers are often busy (429/504), especially for cloud servers: try each mirror, starting
    at a different one each call, and wait a little between rounds."""
    import random
    import time
    last = ""
    order = OVERPASS[:]
    random.shuffle(order)
    for rnd in range(2):
        for url in order:
            if time.time() > deadline:
                raise RuntimeError(f"OpenStreetMap: out of time this run ({last})")
            try:
                r = requests.post(url, data={"data": q}, headers=c.UA, timeout=60)
                if r.status_code < 300 and r.text.lstrip().startswith("{"):
                    return r.json().get("elements", [])
                last = f"{url.split('/')[2]} {r.status_code}"
            except Exception as e:
                last = f"{url.split('/')[2]} {type(e).__name__}"
        time.sleep(20)
    raise RuntimeError(f"OpenStreetMap servers busy ({last})")


def _boxes(h, miles, n=2):
    """Split the service circle's bounding box into n x n tiles: small queries finish where one big one times out."""
    import math
    dlat = miles / 69.0
    dlon = miles / (69.0 * math.cos(math.radians(h[0])))
    s, w = h[0] - dlat, h[1] - dlon
    out = []
    for i in range(n):
        for j in range(n):
            out.append((s + 2 * dlat * i / n, w + 2 * dlon * j / n, s + 2 * dlat * (i + 1) / n, w + 2 * dlon * (j + 1) / n))
    return out


def map_lane(db):
    """One small query per kind of business and map tile, so one slow piece doesn't sink the run. Whatever comes
    back is used; the rest is tried again next run."""
    h, rad = c.home(db), c.radius(db)
    import time
    deadline = time.time() + 9 * 60            # never hold up the hourly run for more than ~9 minutes
    # pieces finished this sweep are remembered, so each run only asks for the ones still missing
    sweep = db.setting("gs_map_sweep", {}) or {}
    key = f"{h[0]:.3f},{h[1]:.3f},{rad}"
    if sweep.get("key") != key or sweep.get("complete"):
        sweep = {"key": key, "done": [], "complete": False, "started": c.now().isoformat()}
    done_set = set(sweep.get("done") or [])
    elements, fails = [], []
    pieces = [(i, f, b) for i, (f, b) in enumerate((f, b) for f, _, _ in MAP_KINDS for b in _boxes(h, rad))]
    for i, f, b in pieces:
        if i in done_set:
            continue
        if time.time() > deadline:
            break
        q = f'[out:json][timeout:50];nwr{f}["name"]({b[0]:.4f},{b[1]:.4f},{b[2]:.4f},{b[3]:.4f});out center tags;'
        try:
            elements += _overpass(q, deadline)
            done_set.add(i)
        except Exception as e:
            fails.append(str(e))
        time.sleep(4)                           # public map servers turn away rapid-fire requests
    sweep["done"] = sorted(done_set)
    sweep["complete"] = len(done_set) >= len(pieces)
    db.insert("settings", {"key": "gs_map_sweep", "value": sweep, "updated_at": c.now()}, upsert=True, on_conflict="key")
    done = len(done_set)
    if not elements and fails and not done:
        raise RuntimeError(fails[-1])
    data = {"elements": elements}
    rows = []
    for el in data.get("elements", []):
        tg = el.get("tags", {})
        name = tg.get("name", "").strip()
        if not name or any(x in name.lower() for x in CHAINS):
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or c.miles(h, (lat, lon)) > rad:
            continue
        cat, fit = _classify(tg)
        town = c.match_town(tg.get("addr:city") or "") or min(c.TOWNS, key=lambda t: c.miles((lat, lon), c.TOWNS[t]))
        addr = " ".join(x for x in [tg.get("addr:housenumber"), tg.get("addr:street")] if x) or None
        email = (tg.get("email") or tg.get("contact:email") or "").split(";")[0].strip().lower() or None
        rows.append({"name": name[:120], "town": town, "category": cat, "address": addr,
                     "website": tg.get("website") or tg.get("contact:website") or tg.get("url"),
                     "email": email, "email_source": "OpenStreetMap listing" if email else None,
                     "lat": lat, "lon": lon, "distance_mi": round(c.miles(h, (lat, lon)), 1),
                     "source": "map", "source_url": f"https://www.openstreetmap.org/{el['type']}/{el['id']}",
                     "fit_score": fit + (1 if email else 0)})
    rows.sort(key=lambda r: (-r["fit_score"], r["distance_mi"]))
    total = len(pieces)
    return _add(db, rows, limit=int(db.setting("gs_map_batch", 150) or 150)), len(rows), f"{done}/{total}"


def main(db):
    n, towns = lease_news(db)
    return f"lease/opening news in {', '.join(towns)}: {n} new prospects"


def main_map(db):
    n, seen, parts = map_lane(db)
    return f"map: {seen} businesses in range, {n} new prospects (map pieces loaded {parts})"
