"""CASE DESK agent: researches WHO / WHY / HOW IT ENDED for every case.

1. Before production: every obtained lead gets a case file (suspect, why police were there, charges, outcome,
   sources). Maker won't script a case until it has one, so every episode can say who, why and how it ended.
2. After posting: open cases (pending / unknown) on posted episodes are re-checked every 14 days. When an
   outcome lands, Bobby gets an alert with a ready-to-paste description update. Nothing public is changed
   automatically.

Facts come only from the agency's own release and news coverage found on the open web. Court-record sites
sit behind CAPTCHAs, so they're never scraped. Every fact must cite a source or it is dropped.
Case files are stored in the settings table under key "case_facts:<lead_id>" (no schema change needed).
"""
import html
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import quote_plus, unquote

import feedparser
import requests

from .lib import llm

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0 Safari/537.36"}
RECHECK_DAYS = 14
MAX_RESEARCH_PER_RUN = 6
FINAL = {"convicted", "pleaded_guilty", "acquitted", "dismissed", "no_charges", "deceased", "resolved"}
NO_NAME_STATUSES = {"dismissed", "acquitted", "no_charges"}


def key(lead_id):
    return f"case_facts:{lead_id}"


def get(db, lead_id):
    return db.setting(key(lead_id))


def _save(db, lead_id, facts):
    db.insert("settings", {"key": key(lead_id), "value": facts,
                           "updated_at": datetime.now(timezone.utc)}, upsert=True, on_conflict="key")


# ---------------- web ----------------
def _text(url, limit=7000):
    try:
        r = requests.get(url, headers=UA, timeout=15)
        if r.status_code >= 300 or "html" not in r.headers.get("content-type", "html"):
            return ""
        t = re.sub(r"(?is)<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>", " ", r.text)
        t = html.unescape(re.sub(r"<[^>]+>", " ", t))
        return re.sub(r"\s+", " ", t).strip()[:limit]
    except Exception:
        return ""


def _ddg(q, n=5):
    """DuckDuckGo HTML results -> real article URLs."""
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


def _gnews(q, n=6):
    """Google News RSS: titles + snippets (article links are redirects, so we keep the snippet text)."""
    try:
        feed = feedparser.parse(f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-US&gl=US&ceid=US:en")
        return [{"url": e.link, "title": e.title,
                 "text": re.sub(r"<[^>]+>", " ", e.get("summary", ""))[:500],
                 "date": e.get("published", "")} for e in feed.entries[:n]]
    except Exception:
        return []


def gather(lead, extra_queries=()):
    docs, seen = [], set()

    def add(url, title, text, published=""):
        if text and url not in seen:
            seen.add(url)
            docs.append({"i": len(docs), "url": url, "title": title, "published": published, "text": text})

    if lead.get("source_url"):
        add(lead["source_url"], "Agency / source release", _text(lead["source_url"]) or (lead.get("summary") or ""))
    q = llm.ask(
        "You write web search queries to find news coverage and court outcomes of a specific police incident.",
        json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date", "summary")}) +
        '\nReturn JSON {"queries":["3 short queries: one for the incident itself, one adding words like charged/'
        'arrested, one adding sentenced/pleaded/convicted"]}', max_tokens=300, temperature=0.2)
    queries = list(q.get("queries", []))[:3] + list(extra_queries)
    for qq in queries:
        for u in _ddg(qq, 4):
            if len(docs) >= 9:
                break
            add(u, "", _text(u))
        for g in _gnews(qq, 4):
            add(g["url"], g["title"], g["title"] + ". " + g["text"], g["date"])
    return docs[:14]


# ---------------- extraction ----------------
SYSTEM = """You are the case researcher for Ten-Four Tapes, a police bodycam channel. You read source documents
about ONE incident and fill in a case file. Rules:
- Use ONLY what the documents say. Every fact you give must cite the document numbers it came from.
  If documents disagree, prefer the agency release and the most recent dated report.
- Make sure each document is about THIS incident (same place, date, agency, events). Ignore look-alikes,
  including other incidents involving a person with the same name.
- Name the suspect only if an official release or a news report names them. Never name minors, victims,
  witnesses or bystanders.
- Outcome status: convicted | pleaded_guilty | acquitted | dismissed | no_charges | pending | deceased |
  resolved (rescues, medical calls, no crime) | unknown. Use "unknown" when no document says how it ended.
  Charges are not convictions.
- For rescues or calls with no suspect, leave suspect empty and describe who was helped and how it ended."""


def extract(lead, docs):
    out = llm.ask(SYSTEM,
                  "INCIDENT LEAD:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state",
                                                                         "incident_date", "summary")}) +
                  "\n\nDOCUMENTS:\n" + json.dumps(docs)[:24000] +
                  """

Return JSON:
{"suspect":{"name":"","age":null,"hometown":"","named_by":"official|news|none","is_minor":false,"cite":[0]},
 "why":{"text":"one plain sentence: why police were there / why the person was in trouble","cite":[0]},
 "charges":{"list":["..."],"cite":[0]},
 "outcome":{"status":"unknown","text":"one plain sentence on how it ended (plea, verdict, sentence, injuries, rescue result)","sentence":"","cite":[0]},
 "unrelated_docs":[3],
 "notes":"anything uncertain"}""", max_tokens=1200, temperature=0.1)
    return out


def _cited(part, docs):
    ok = [i for i in (part or {}).get("cite", []) if isinstance(i, int) and 0 <= i < len(docs)]
    return ok


def build(lead, extra_queries=()):
    docs = gather(lead, extra_queries)
    raw = extract(lead, docs)
    bad = set(raw.get("unrelated_docs") or [])
    docs_ok = lambda part: [i for i in _cited(part, docs) if i not in bad]
    sus, why, ch, oc = (raw.get(k) or {} for k in ("suspect", "why", "charges", "outcome"))
    # drop anything without a valid citation
    name = (sus.get("name") or "").strip() if docs_ok(sus) and sus.get("named_by") in ("official", "news") else ""
    status = oc.get("status") if docs_ok(oc) else "unknown"
    status = status if status in FINAL | {"pending", "unknown"} else "unknown"
    say_name = bool(name) and not sus.get("is_minor") and status not in NO_NAME_STATUSES
    used = sorted({i for p in (sus, why, ch, oc) for i in docs_ok(p)})
    return {
        "suspect_name": name, "say_name": say_name,
        "suspect_age": sus.get("age") if name else None, "suspect_hometown": sus.get("hometown") if name else "",
        "why": why.get("text", "") if docs_ok(why) else "",
        "charges": ch.get("list", []) if docs_ok(ch) else [],
        "status": status, "final": status in FINAL,
        "outcome": oc.get("text", "") if docs_ok(oc) else "",
        "sentence": oc.get("sentence", "") if docs_ok(oc) else "",
        "sources": [{"url": docs[i]["url"], "title": docs[i]["title"][:150]} for i in used],
        "notes": (raw.get("notes") or "")[:400],
        "checked_at": date.today().isoformat(),
    }


# ---------------- narration guidance (used by Maker + Compliance) ----------------
def narration_rules(facts):
    today = date.today().strftime("%B %Y")
    if not facts:
        return "NO CASE FILE: do not state who, why or any outcome."
    who = (f'You may name the suspect: {facts["suspect_name"]}'
           + (f', {facts["suspect_age"]}' if facts.get("suspect_age") else "") + "."
           if facts.get("say_name") else
           'Do NOT name anyone. Say "the driver", "the suspect", "the man", etc.')
    st = facts.get("status")
    wording = {
        "pending": f'Say the charges with "was charged with" / "is accused of", then "As of {today}, the case is still pending."',
        "unknown": f'State the charges if any with "was charged with", then "As of {today}, we couldn\'t find a public record of how the case ended."',
        "convicted": 'Use "was convicted of" and give the sentence if known.',
        "pleaded_guilty": 'Use "pleaded guilty to" and give the sentence if known.',
        "acquitted": 'Say a jury found him/her not guilty. Do not imply guilt anywhere in the video.',
        "dismissed": 'Say the charges were dropped. Do not imply guilt anywhere in the video.',
        "no_charges": 'Say no charges were filed.',
    }.get(st, "State the outcome plainly and respectfully.")
    return (f"CASE FILE (the ONLY source for who/why/outcome):\n{json.dumps(facts)}\n"
            f"WHO: {who}\nWHY: open the narration_setup with why police were there: {facts.get('why') or 'not public, so do not guess'}.\n"
            f"HOW IT ENDED: what_happened_next must state the outcome. {wording} Never go beyond the case file.\n"
            "Tease the outcome in the cold open or setup (e.g. 'stick around for what the judge gave him') "
            "only if the outcome is final.")


# ---------------- main ----------------
def main(db):
    researched = updated = 0
    alerts = []
    # 1) obtained leads waiting for a case file
    for lead in db.select("leads", {"status": "eq.obtained", "order": "action_score.desc", "limit": 20}):
        if researched >= MAX_RESEARCH_PER_RUN:
            break
        if get(db, lead["id"]):
            continue
        _save(db, lead["id"], build(lead))
        researched += 1

    # 2) posted episodes: back-fill missing case files and re-check open cases
    posted = db.select("content", {"kind": "eq.episode", "status": "eq.posted", "lead_id": "not.is.null",
                                   "select": "id,lead_id,title,youtube_id", "order": "posted_at.desc", "limit": 50})
    for ep in posted:
        if researched >= MAX_RESEARCH_PER_RUN:
            break
        old = get(db, ep["lead_id"])
        if old and old.get("final"):
            continue
        if old and (date.today() - date.fromisoformat(old["checked_at"])).days < RECHECK_DAYS:
            continue
        lead = (db.select("leads", {"id": f"eq.{ep['lead_id']}"}) or [None])[0]
        if not lead:
            continue
        extra = [f'"{old["suspect_name"]}" sentenced OR pleaded OR convicted OR dismissed'] if old and old.get("suspect_name") else []
        new = build(lead, extra)
        researched += 1
        if old and new["status"] == old.get("status") and new["outcome"] == old.get("outcome"):
            new["checked_at"] = date.today().isoformat()
            _save(db, ep["lead_id"], dict(old, checked_at=new["checked_at"]))
            continue
        _save(db, ep["lead_id"], new)
        if new["final"] or (not old and new["outcome"]):
            updated += 1
            line = f"UPDATE ({date.today().strftime('%b %Y')}): {new['outcome']}"
            src = "; ".join(s["url"] for s in new["sources"][:3])
            alerts.append(f"Case outcome found for \"{ep.get('title')}\" "
                          f"(youtu.be/{ep.get('youtube_id') or '?'}). Suggested description line: {line} | Sources: {src}")
    for a in alerts:
        db.alert("casefacts", a, "info")
    return f"researched {researched} case(s); {updated} posted case(s) with a new outcome flagged to Bobby"
