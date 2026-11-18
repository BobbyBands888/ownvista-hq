"""CASE SCOUT: finds big, closed criminal cases whose police interviews/interrogations can be requested.
Why: interrogations of major murder cases are the niche's top view-getters (JCS, EWU), and an interview room shows
no death on screen. Interview recordings usually become public once the case is closed (sentenced, or a verdict
with the trial over), so the scout looks back 30-90 days for sentencings, convictions and released interrogations.

Runs inside the Scout about once a day. Each kept case becomes a lead with category "case_story", the prosecutor's
office (or the agency that ran the interview) as the records holder, and a case key so the same case reported by
twenty outlets becomes one lead."""
import json
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus
import feedparser
from .lib import llm
from .lib.runner import RULES

EVERY_H = 20
# (query, lookback days). Sentencings/convictions: the case is closed, the interviews are now public records.
QUERIES = [
    ("sentenced murder interrogation video", 90),
    ("jury watched interrogation video", 60),
    ("jury watched police interview", 60),
    ("interrogation video released murder", 90),
    ("police interview video released", 60),
    ("confession video played in court", 60),
    ("found guilty murder police interview video", 60),
    ("sentenced life in prison interview with detectives", 45),
    ("prosecutors release interrogation video", 90),
    ("state attorney releases interview video", 90),
    ("district attorney releases interrogation video", 90),
    ("bodycam and interrogation video released trial", 60),
    ("convicted murder 911 call played in court", 45),
    ("pleaded guilty murder detectives interview video", 45),
]
MIN_SCORE = 6

SYSTEM = """You screen U.S. criminal cases for Ten-Four Tapes' long-form case-story episodes (911 call, bodycam,
the police interview/interrogation, the verdict), in the style of JCS - Criminal Psychology and EWU.
What ranks high (score 8-10): a case people have heard of or will want to (a murder or attempted murder, a
disappearance, a killer who lied to detectives, a twist), a recorded police interview or interrogation of the
suspect that exists (the article says the jury watched it, it was played in court, or it was released), and the case
is CLOSED (sentenced, convicted with the trial over, or pleaded guilty). Open cases (only arrested/charged, trial
pending, appeal-only coverage) score 5 at most: their recordings aren't released yet.
Score 3 at most and keep=false: any case where the victim or the suspect is a minor (under 18), child-abuse cases,
sexual-assault cases, cases outside the U.S., and stories with no single identifiable case.
Never score on anyone's looks or body. Judge only from the article text given; don't invent details.
The records holder is the prosecutor's office that tried the case (e.g. "State Attorney's Office, 9th Judicial
Circuit", "Maricopa County Attorney's Office", "Harris County District Attorney's Office"); if the article only names
the police agency that ran the interview, give that agency.
""" + RULES


def _now():
    return datetime.now(timezone.utc)


def due(db, forced=False):
    last = db.setting("case_scout_last")
    return forced or not last or (_now() - datetime.fromisoformat(last)).total_seconds() >= EVERY_H * 3600


def search():
    items, seen = [], set()
    for q, days in QUERIES:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote_plus(q)}+when:{days}d&hl=en-US&gl=US&ceid=US:en")
        for e in feed.entries[:25]:
            if e.link in seen:
                continue
            seen.add(e.link)
            items.append({"title": e.title[:300], "summary": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:600],
                          "source_url": e.link, "published": e.get("published", "")})
    return items


US = set("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND "
         "OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split())


def case_key(name, county=None, state=None):
    """Same case, many outlets: key on the defendant's legal last name only. The AI guesses county/state differently
    from article to article (Caleb Flynn came back as OH, FL and Butler County), so those can't be in the key."""
    name = re.sub(r"[\"“”'‘’][^\"“”'‘’]*[\"“”'‘’]", " ", name or "")      # drop nicknames: Duane "Keffe D" Davis
    toks = [t for t in re.sub(r"[^A-Za-z\s-]", " ", name).split() if len(t) > 1 and t.lower() not in ("jr", "sr", "ii", "iii")]
    return re.sub(r"[^a-z]", "", toks[-1].lower()) if toks else ""


def score(items):
    out = []
    for i in range(0, len(items), 12):
        batch = items[i:i + 12]
        res = llm.ask(
            SYSTEM,
            "Articles:\n" + json.dumps([{"i": n, "title": x["title"], "summary": x["summary"][:450],
                                         "published": x["published"]} for n, x in enumerate(batch)]) +
            '\n\nReturn JSON {"cases":[{"i":0,"case_score":1-10,"keep":true|false,'
            '"suspect_name":"the defendant\'s legal full name (first + last, no nickname; for two defendants, the first one), or null","county":"county or city, or null","state":"2-letter or null",'
            '"holder":"prosecutor office (or police agency) that holds the interview recordings, or null",'
            '"stage":"sentenced|convicted|pleaded|charged|other","interview_mentioned":true|false,'
            '"incident_date":"YYYY-MM-DD or null","minor_involved":true|false|null,'
            '"hook":"one line: who did what and the twist, only from the text","why":"short"}]}',
            max_tokens=2500, temperature=0.1)
        cases = res if isinstance(res, list) else (res.get("cases") or [])   # the model sometimes returns the bare list
        by_i = {x.get("i"): x for x in cases if isinstance(x, dict)}
        for n, it in enumerate(batch):
            s = by_i.get(n)
            if s:
                out.append((it, s))
    return out


def _rank(s):
    sc = int(s.get("case_score") or 0)
    if s.get("stage") not in ("sentenced", "convicted", "pleaded"):
        sc = min(sc, 5)                       # recordings aren't public while the case is open
    if not s.get("interview_mentioned"):
        sc = min(sc, 7)
    if s.get("minor_involved"):
        sc = min(sc, 3)
    return max(1, min(10, sc))


def find(db, forced=False):
    """Returns lead rows ready to insert (category case_story), one per case, and a short stats line."""
    if not due(db, forced):
        return [], ""
    items = search()
    # drop links we already have before spending AI calls on them
    have = set()
    urls = [x["source_url"] for x in items]
    for i in range(0, len(urls), 40):
        q = ",".join('"' + u.replace('"', "") + '"' for u in urls[i:i + 40])
        have |= {r["source_url"] for r in db.select("leads", {"select": "source_url", "source_url": f"in.({q})"})}
    items = [x for x in items if x["source_url"] not in have][:120]
    scored = score(items) if items else []
    # a case we're working stays known for 180 days; a skipped one only for 30 (an open case gets sentenced later)
    since, recent = (_now() - timedelta(days=180)).isoformat(), (_now() - timedelta(days=30)).isoformat()
    known = {m for r in db.select("leads", {"select": "notes,status,created_at", "category": "eq.case_story",
                                            "created_at": f"gte.{since}", "limit": 2000})
             if r.get("status") != "skipped" or (r.get("created_at") or "") >= recent
             for m in re.findall(r"\[case:([a-z0-9-]+)\]", r.get("notes") or "")}
    best = {}
    for it, s in scored:
        key = case_key(s.get("suspect_name"), s.get("county"), s.get("state"))
        if not key or key in known:
            continue
        sc = _rank(s)
        if key not in best or sc > best[key][0]:
            best[key] = (sc, it, s)
    rows = []
    for key, (sc, it, s) in best.items():
        keep = (bool(s.get("keep")) and sc >= MIN_SCORE and s.get("minor_involved") is not True and bool(s.get("holder"))
                and str(s.get("state") or "").upper() in US)
        where = ", ".join(x for x in (s.get("county"), s.get("state")) if x)
        rows.append({
            "title": it["title"], "summary": ((s.get("hook") or "") + " — " + it["summary"])[:900],
            "source_url": it["source_url"], "source_type": "news_tip", "category": "case_story",
            "agency_name": s.get("holder"), "state": s.get("state"), "incident_date": s.get("incident_date"),
            "action_score": sc, "involves_minor": s.get("minor_involved"),
            "status": "new" if keep else "skipped",
            "notes": f"[case:{key}] suspect: {s.get('suspect_name')} | {where} | stage: {s.get('stage')} | "
                     f"interview mentioned: {'yes' if s.get('interview_mentioned') else 'no'} — {s.get('why') or ''}"})
    db.insert("settings", {"key": "case_scout_last", "value": _now().isoformat(), "updated_at": _now().isoformat()},
              upsert=True, on_conflict="key")
    kept = [r for r in rows if r["status"] == "new"]
    top = sorted(kept, key=lambda r: -r["action_score"])[:3]
    return rows, (f"cases: {len(items)} articles, {len(best)} cases, {len(kept)} kept"
                  + (" (top: " + "; ".join(f"{r['action_score']} {r['title'][:45]}" for r in top) + ")" if top else ""))
