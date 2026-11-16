"""MAKER agent — turns obtained footage leads into full production plans: the YouTube episode,
3 YouTube Shorts (Part 1/2/3) and standalone Facebook action Reels. Uses the live playbook from
Research + Analytics. Rendering happens on Bobby's Mac (mac/runner.py) with the existing build tools."""
import json
import re
from .lib import llm
from .lib.runner import RULES
from . import casefacts

FORMAT = """Ten-Four Tapes format:
- Every case gets a short, unique CASE NAME (e.g. "Backyard Shootout", "Bee Swarm") used on the Reel badge,
  the caption first line, and the YouTube title.
- EPISODE (YouTube long-form). Two styles:
  a) case_story: cold-open hook + title card, 911 call, interrogation/interview, bodycam, reveal, verdict.
  b) action: multi-bodycam high-action episode, no interview needed.
  Both: narrated setup kept SHORT (viewers should not just listen to the narrator), raw bodycam with original audio
  boosted (muted only while narrator talks), brief narrator check-ins, "what happened next" outro, one comment
  question, subscribe end card. Multiple angles are labeled "Body Cam Officer 1", "Body Cam Officer 2", etc.
  Credit line on screen and in description.
- NARRATOR ON VERTICALS: every Reel and Part 1 Short opens with the narrator setting it up over the first seconds
  (place, who, why police were there) while the bodycam plays underneath; every Reel and Part 3 ends with a narrated
  "how it ended" line. Same voice as the episodes.
- SHORTS: 3 vertical Shorts per episode labeled "<Case Name> Part 1/2/3", each ends "Follow for Part 2/3".
- FACEBOOK REELS: standalone 25-30s enforcement-action Reels (never "Part 1/2/3" — Facebook doesn't show Part 2 to
  Part 1's viewers), real audio, action in the first 2 seconds. When a case gets 2-3 Reels, each one is a DIFFERENT
  single moment of the incident (e.g. the stop, the run, the takedown) and stands on its own: a viewer who sees only
  that Reel understands it. No "part", "continued", "what happens next" or references to the other Reels. Caption line 1 = PLACE + STAKES in under 15 words
  (e.g. "Quemado, Texas. A man swinging tree branches has already hit a Border Patrol agent in the head."), then one
  short question, then 3-4 hashtags. Our page data: these get 37K-106K views; "Case Name — generic summary" captions
  and rescue Reels get under 1K.
- Titles: specific and dramatic but accurate. Never show the death itself, gore or a lingering body; blur bystanders as needed.
- FACTS: every narration line, check-in and "what happened next" must be stated in the lead text. Never invent an
  outcome (arrest, custody, charges, injuries, deaths). If the lead doesn't say how it ended, leave
  what_happened_next as "" — a wrong outcome is worse than none. If the lead says someone died, say so plainly
  and respectfully, and plan cuts so the person is never shown dying, dead, or badly wounded.
- WHO / WHY / HOW IT ENDED (every case): the setup says who the suspect is (named only if the case file allows it)
  and why police were there; what_happened_next says how it ended, using the case file's wording rules. Charges are
  never called convictions. List the case file's sources at the end of the description under "Sources:"."""

STRONG = 8          # action_score at/above this = a full enforcement moment + place + stakes -> 3 Reels
PART_RE = re.compile(r"\bpart\s*(\d|one|two|three)\b|\bpt\.?\s*\d|continued|next reel|follow for part", re.I)

def reel_count(lead):
    """Rescues get no Reels (160-700 views on our page). Strong cases get 3 single-moment Reels, the rest 2."""
    if lead.get("category") == "rescue":
        return 0
    return 3 if (lead.get("action_score") or 0) >= STRONG else 2

def _standalone(r):
    txt = " ".join(str(r.get(k) or "") for k in ("moment", "hook_text", "caption")).lower()
    return bool((r.get("moment") or "").strip()) and not PART_RE.search(txt)

def plan(lead, playbook, rejects=(), facts=None, graded=None):
    n_reels = reel_count(lead)
    return llm.ask(
        "You are the head of production for Ten-Four Tapes. Write production plans that follow the format exactly "
        "and apply the playbook. Accuracy matters: only state facts present in the lead.\n" + RULES + "\n" + FORMAT,
        "Playbook (what works right now):\n" + json.dumps(playbook) +
        ("\n\nBobby REJECTED these recently — don't repeat what he didn't like:\n" + json.dumps(list(rejects))
         if rejects else "") +
        ("\n\nSCORECARD — our own posts graded at 48h against the same format. Write like the A's, not like the D's "
         "(captions, hooks, which moment, case type):\n" + json.dumps(graded) if graded else "") +
        "\n\nLead:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date",
                                                              "summary", "category", "source_type")}) +
        "\n\n" + casefacts.narration_rules(facts) +
        """

Return JSON:
{"case_name":"2-3 words",
 "credit":"Footage: <agency> (<public domain | public records request | official release>)",
 "episode":{"style":"case_story|action","title":"","description":"includes context + credit + no spoilers in first line",
   "tags":[""],"cold_open_hook":"on-screen text, under 12 words","title_card":"",
   "narration_setup":"max 3 short sentences","check_ins":["max 4 brief lines"],
   "angle_labels":["Body Cam Officer 1"],"what_happened_next":"","comment_question":"",
   "thumbnail_text":"2-4 words in big letters over the peak action frame: the stakes or the twist, true to the lead, not the case name or the title repeated, no gore words","blur_notes":"anything that must be blurred or cut (bodies, bystanders, IDs)",
   "analysis_tags":{"pillar":"Case File|Pursuit|Border|Update","title_formula":"Person + action + twist|Situation + realization|Place + incident + bodycam|Outcome tease|Number + stakes|Other","thumbnail_type":"weapon|crash|face|scene","case_type":"pursuit|shooting|standoff|rescue|death in story|other"}},
 "shorts":[{"part":1,"title":"<Case Name> Part 1","moment":"which moment to cut","on_screen_text":"",
   "intro_vo":"Part 1 only: 1-2 spoken sentences (max 24 words): place, who, why police were there","outcome_vo":"Part 3 only: how it ended (max 25 words) or \"\""}],
 "reels":[{"moment":"one single 25-30s action moment, different from the other reels","hook_text":"first 2s text","caption":"PLACE. STAKES of THIS moment (under 15 words) + one short question","hashtags":["#bodycam"],"intro_vo":"1-2 spoken sentences (max 24 words) the narrator reads over the opening seconds: place, who, why police were there","outcome_vo":"how it ended (max 25 words) or \"\""}]}
3 shorts and """ + (f"exactly {n_reels} reels, each a different single moment in story order, each standalone."
                    if n_reels else "no reels (\"reels\":[])."), max_tokens=2800, temperature=0.6)

def scorecard_examples(db):
    """Up to 6 A's and 6 D's from the Scorecard; empty until posts are graded (or before the SQL is run)."""
    try:
        from .analytics import recent_graded, _post_brief
        posts = [_post_brief(c) for c in recent_graded(db)]
    except Exception:
        return {}
    ex = {"A": [p for p in posts if p["grade"] == "A"][:6], "D": [p for p in posts if p["grade"] == "D"][:6]}
    return ex if ex["A"] or ex["D"] else {}

TAG_CHOICES = {
    "pillar": ("Case File", "Pursuit", "Border", "Update"),
    "title_formula": ("Person + action + twist", "Situation + realization", "Place + incident + bodycam",
                      "Outcome tease", "Number + stakes", "Other"),
    "thumbnail_type": ("weapon", "crash", "face", "scene"),
    "case_type": ("pursuit", "shooting", "standoff", "rescue", "death in story", "other"),
}

def analysis_tags(raw, lead):
    """Tags the Analytics agent groups by in the monthly top-3 / bottom-3 comparison.
    Agency source and narration are set here, not by the model; length is added after render."""
    raw = raw if isinstance(raw, dict) else {}
    tags = {}
    for k, opts in TAG_CHOICES.items():
        v = str(raw.get(k) or "").strip()
        tags[k] = next((o for o in opts if o.lower() == v.lower()), opts[-1] if k in ("title_formula", "case_type") else None)
    agency = (lead.get("agency_name") or "").lower()
    tags["agency_source"] = ("CBP" if lead.get("source_type") == "dvids_public_domain" or "border" in agency or "cbp" in agency
                             else "Florida sheriff" if (lead.get("state") or "").upper() in ("FL", "FLORIDA") and "sheriff" in agency
                             else "Other")
    tags["narration"] = "AI"
    return tags

def _sources(ep, facts):
    if not facts or not facts.get("sources") or "Sources:" in (ep.get("description") or ""):
        return ""
    return "\n\nSources:\n" + "\n".join(s["url"] for s in facts["sources"][:5])

def main(db):
    # Mix of sources: local police/sheriff/prosecutor footage first; federal DVIDS (mostly U.S. Customs and
    # Border Protection) fills in (see below) so the channel isn't just Border Patrol videos.
    pool = db.select("leads", {"status": "eq.obtained", "order": "action_score.desc", "limit": 20})
    # cases already made as episodes before HQ existed — don't remake them
    made = ("yuma, az january 22, 2025", "brownsville, tx february 12, 2025", "brownsville, texas may 13, 2025",
            "bisbee, arizona june 19, 2024", "quemado, texas may 16, 2024", "laredo, texas sept 23, 2024")
    pool = [l for l in pool if not any(m in (l.get("title") or "").lower() for m in made)]
    # enforcement action first (it's what the page's hits are), then case stories, then rescues
    rank = {"enforcement": 0, "case_story": 1, "other": 2, "rescue": 3}
    pool.sort(key=lambda l: (rank.get(l.get("category") or "other", 2), -(l.get("action_score") or 0)))
    local = [l for l in pool if l.get("source_type") != "dvids_public_domain"]
    federal = [l for l in pool if l.get("source_type") == "dvids_public_domain"]
    # Case Desk must have researched who/why/outcome first; cases without a case file wait for its next run
    files = {l["id"]: casefacts.get(db, l["id"]) for l in pool[:12]}
    local = [l for l in local if files.get(l["id"])]
    federal = [l for l in federal if files.get(l["id"])]
    # 3 Shorts/day = 1 case/day. Local cases first; federal DVIDS (public domain, no request needed) is capped at 1
    # per run so the channel isn't all Border Patrol — except when no local case is ready, then 2 so it never runs dry.
    leads = local[:3]
    leads += federal[:(1 if local else 2)][:3 - len(leads)]
    pb = db.select("playbook", {"active": "is.true", "order": "created_at.desc", "limit": 40})
    # scorecard lessons always make the cut (they're about OUR posts); then the newest of the rest
    playbook = [p["insight"] for p in pb if p.get("source") == "scorecard"][:5] + \
               [p["insight"] for p in pb if p.get("source") != "scorecard"][:15]
    graded = scorecard_examples(db)
    rejects = [f"{r['kind']}: {r.get('title')} — {(r.get('publish_note') or '').replace('Rejected: ', '')}"
               for r in db.select("content", {"select": "kind,title,publish_note", "approval_status": "eq.rejected",
                                              "order": "created_at.desc", "limit": 15})]
    made = n_reel = 0
    for lead in leads:
        # clear any half-made plan from a failed earlier run of this lead (never touches rendered/posted items)
        db.delete("content", {"lead_id": f"eq.{lead['id']}", "status": "eq.scripted"})
        facts = files.get(lead["id"])
        p = plan(lead, playbook, rejects, facts, graded)
        ep = p.get("episode", {})
        case = p.get("case_name") or lead["title"][:30]
        credit = p.get("credit") or f"Footage: {lead.get('agency_name')}"
        src_type = lead["source_type"]
        ep["analysis_tags"] = analysis_tags(ep.get("analysis_tags"), lead)
        epi = db.insert("content", {
            "lead_id": lead["id"], "kind": "episode", "case_name": case, "title": ep.get("title"),
            "description": (ep.get("description") or "") + f"\n\n{credit}" + _sources(ep, facts), "tags": ep.get("tags") or [],
            "script": ep, "source_type": src_type, "source_credit": credit, "source_urls": [lead.get("source_url")],
        })[0]
        rows = []
        for s in p.get("shorts", [])[:3]:
            rows.append({"lead_id": lead["id"], "kind": "short", "parent_id": epi["id"], "part": s.get("part"),
                         "case_name": case, "title": s.get("title") or f"{case} Part {s.get('part')}",
                         "description": f"Full episode on the channel. {credit}", "script": s,
                         "source_type": src_type, "source_credit": credit, "source_urls": [lead.get("source_url")]})
        # 2-3 standalone single-moment Reels (3 for strong cases); rescues get the episode + Shorts only
        reels, seen = [], set()
        for r in p.get("reels") or []:
            key = (r.get("moment") or "").strip().lower()[:60]
            if _standalone(r) and key not in seen:
                seen.add(key)
                reels.append(r)
        for n, r in enumerate(reels[:reel_count(lead)], 1):
            r["reel_no"] = n
            rows.append({"lead_id": lead["id"], "kind": "reel", "parent_id": epi["id"], "part": None, "case_name": case,
                         "title": case, "description": (r.get("caption") or case) + f"\nFull episode on YouTube: Ten-Four Tapes\n{credit}"
                         + ("\n" + " ".join(r["hashtags"][:4]) if r.get("hashtags") else ""),
                         "script": r, "source_type": src_type, "source_credit": credit,
                         "source_urls": [lead.get("source_url")]})
        n_reel += sum(1 for r in rows if r["kind"] == "reel")
        db.insert("content", rows)
        db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "used"})
        made += 1
    return f"planned {made} cases ({made} episodes + shorts + {n_reel} standalone reels)"
