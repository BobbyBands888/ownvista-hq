"""MAKER agent — turns obtained footage leads into full production plans: the YouTube episode,
3 YouTube Shorts (Part 1/2/3) and standalone Facebook action Reels. Uses the live playbook from
Research + Analytics. Rendering happens on Bobby's Mac (mac/runner.py) with the existing build tools."""
import json
import re
from .lib import llm
from .lib.runner import RULES
from . import casefacts
from . import packaging

FORMAT = """Ten-Four Tapes format:
- Every case gets a short, unique CASE NAME (e.g. "Backyard Standoff", "Bee Swarm") used on the Reel badge,
  the caption first line, and the YouTube title.
- EPISODE (YouTube long-form). Two styles:
  a) case_story (JCS / EWU style, 15-25 min): cold-open hook (the most telling moment of the interview, e.g. the
     lie or the moment the story changes) + title card, then in order: the 911 call, the bodycam of the response or
     arrest, the police interview/interrogation (the longest part: let the suspect talk; narrator check-ins point out
     the lie, the evidence, the turn), and the verdict/sentence. Check-ins: up to 6. Facebook gets ONE teaser Reel
     from the interview (a lie or a tense exchange, no outcome given away); no other Reels.
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
  that Reel understands it. No "part", "continued", "what happens next" or references to the other Reels. Caption line 1 = PLACE + STAKES in under 10 words
  (e.g. "Quemado, Texas. A man swinging tree branches has already hit a Border Patrol agent in the head."), then one
  short question, then 3-4 hashtags. Our page data: these get 37K-106K views; "Case Name — generic summary" captions
  and rescue Reels get under 1K.
- Titles: specific and dramatic but accurate. Unblurred gore or a body is never shown; in episodes the renderer shows
  the aftermath fully blurred (max 20s); Shorts, Reels and thumbnails never include it. Blur bystanders as needed.
- """ + packaging.TITLE_RULES + """
- """ + packaging.THUMB_RULES + """
- FACTS: every narration line, check-in and "what happened next" must be stated in the lead text. Never invent an
  outcome (arrest, custody, charges, injuries, deaths). If the lead doesn't say how it ended, leave
  what_happened_next as "" — a wrong outcome is worse than none. If the lead says someone died, say so plainly
  and respectfully, and plan cuts so the person is never shown dying, dead, or badly wounded.
- WHO / WHY / HOW IT ENDED (every case): the setup says who the suspect is (named only if the case file allows it)
  and why police were there; what_happened_next says how it ended, using the case file's wording rules. Charges are
  never called convictions. List the case file's sources at the end of the description under "Sources:"."""

STRONG = 8          # action_score at/above this = a full enforcement moment + place + stakes -> 3 Reels
PART_RE = re.compile(r"\bpart\s*(\d|one|two|three)\b|\bpt\.?\s*\d|continued|next reel|follow for part", re.I)

FATAL_RE = re.compile(r"\b(died|dies|dead|death|killed|fatal|deceased|pronounced)\b", re.I)


def is_case(lead):
    """A Case Scout lead (interview episode). Older bodycam leads can also be labeled case_story."""
    return lead.get("category") == "case_story" and "[case:" in (lead.get("notes") or "")


def is_fatal(facts):
    """True when the case file says someone died. Fatal cases keep getting blocked as Reels (the big moment is the
    shooting), so they get one Reel from before anyone is hurt and go to the back of the queue."""
    if not facts:
        return False
    if (facts.get("status") or "").lower() in ("deceased", "dead", "killed"):
        return True
    return bool(FATAL_RE.search(facts.get("outcome") or ""))


def reel_count(lead, facts=None):
    """How many standalone Reels a case gets. Facebook Reels are where the page's reach is, so long agency packages
    (records requests: often hours of footage, many separate moments) get 4-5; short federal DVIDS clips 2-3;
    fatal cases 1; rescues none (160-700 views on our page)."""
    if lead.get("category") == "rescue":
        return 0
    if is_case(lead):
        return 1                    # one interview teaser; long-form doesn't belong on FB (Boone 13-min: 402 views)
    if is_fatal(facts):
        return 1
    strong = (lead.get("action_score") or 0) >= STRONG
    if lead.get("source_type") != "dvids_public_domain":
        return 5 if strong else 4
    return 3 if strong else 2

def _standalone(r):
    txt = " ".join(str(r.get(k) or "") for k in ("moment", "hook_text", "caption")).lower()
    return bool((r.get("moment") or "").strip()) and not PART_RE.search(txt)

def plan(lead, playbook, rejects=(), facts=None, graded=None):
    n_reels = reel_count(lead, facts)
    fatal_note = (" Someone died in this case: the one Reel must END BEFORE any shot, strike or injury — the"
                  " confrontation or the chase, never the outcome." if is_fatal(facts) else "")
    if is_case(lead):
        fatal_note = (" This is a case story: episode style must be case_story, and the one Reel is a teaser cut from the"
                      " police interview (a lie or a tense exchange), never the crime or its aftermath.")
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
 "episode":{"style":"case_story|action","title":"one of the 5 formulas, under 60 chars","title_formula":"the formula used","description":"includes context + credit + no spoilers in first line",
   "tags":[""],"cold_open_hook":"on-screen text, under 12 words","title_card":"",
   "narration_setup":"max 3 short sentences","check_ins":["max 4 brief lines"],
   "angle_labels":["Body Cam Officer 1"],"what_happened_next":"","comment_question":"",
   "thumbnail_texts":["3 options, 2-3 words each, big letters over 3 different peak frames: the stakes or the twist, true to the lead, not the case name or the title repeated, no gore words"],"blur_notes":"anything that must be blurred or cut (bodies, bystanders, IDs)",
   "analysis_tags":{"pillar":"Case File|Pursuit|Border|Update","title_formula":"Person + action + twist|Situation + realization|Place + incident + bodycam|Outcome tease|Number + stakes","thumbnail_type":"weapon|crash|face|scene","case_type":"pursuit|shooting|standoff|rescue|death in story|other"}},
 "shorts":[{"part":1,"title":"<Case Name> Part 1","moment":"which moment to cut","on_screen_text":"",
   "intro_vo":"Part 1 only: 1-2 spoken sentences (max 24 words): place, who, why police were there","outcome_vo":"Part 3 only: how it ended (max 25 words) or \"\""}],
 "reels":[{"moment":"one single 25-30s action moment, different from the other reels","hook_text":"first 2s text","caption":"PLACE. STAKES of THIS moment (under 10 words) + one short question","hashtags":["#bodycam"],"intro_vo":"1-2 spoken sentences (max 24 words) the narrator reads over the opening seconds: place, who, why police were there","outcome_vo":"how it ended (max 25 words) or \"\""}]}
3 shorts and """ + (f"exactly {n_reels} reels, each a different single moment in story order, each standalone." + fatal_note
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

def fix_packaging(ep, lead, facts):
    """Title from one of the 5 formulas (one retry if the plan missed), 3 thumbnail texts."""
    f = packaging.formula_of(ep.get("title_formula") or (ep.get("analysis_tags") or {}).get("title_formula"))
    has_outcome = bool((facts or {}).get("outcome") or (facts or {}).get("sentence"))
    if not packaging.title_ok(ep.get("title"), f, has_outcome):
        try:
            j = llm.ask("You title police bodycam episodes for YouTube. Accuracy first: only facts in the lead.",
                        packaging.TITLE_RULES + "\n\n" + packaging.THUMB_RULES +
                        "\n\nLead:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "summary")}) +
                        "\nCase file: " + json.dumps(facts or {})[:1500] +
                        f"\nRejected title: {ep.get('title')!r}\n"
                        'Return JSON {"title":"","title_formula":"","thumbnail_texts":["","",""]}',
                        max_tokens=300, temperature=0.5)
            if packaging.title_ok(j.get("title"), j.get("title_formula"), has_outcome):
                ep["title"], f = j["title"].strip(), packaging.formula_of(j["title_formula"])
                ep["thumbnail_texts"] = ep.get("thumbnail_texts") or j.get("thumbnail_texts")
        except Exception:
            pass
    tt = packaging.thumb_texts((ep.get("thumbnail_texts") or []) + [ep.get("thumbnail_text") or ""], ep.get("title"))
    if tt:
        ep["thumbnail_texts"], ep["thumbnail_text"] = tt, tt[0]
    ep.setdefault("analysis_tags", {})
    if isinstance(ep["analysis_tags"], dict):
        ep["analysis_tags"]["title_formula"] = f or "Other"
    return ep

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
    # Case Desk must have researched who/why/outcome first; cases without a case file wait for its next run
    files = {l["id"]: casefacts.get(db, l["id"]) for l in pool}
    # within each category, cases where nobody died go first: they pass review and yield more Reels
    pool.sort(key=lambda l: (rank.get(l.get("category") or "other", 2), is_fatal(files.get(l["id"])),
                             -(l.get("action_score") or 0)))
    local = [l for l in pool if l.get("source_type") != "dvids_public_domain"]
    federal = [l for l in pool if l.get("source_type") == "dvids_public_domain"]
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
        ep = fix_packaging(ep, lead, facts)
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
        # standalone single-moment Reels (count from reel_count); rescues get the episode + Shorts only
        want = reel_count(lead, facts)
        reels, seen = [], set()
        def take(cands):
            for r in cands or []:
                key = (r.get("moment") or "").strip().lower()[:60]
                if _standalone(r) and key not in seen:
                    seen.add(key)
                    reels.append(r)
        take(p.get("reels"))
        if len(reels) < want:
            # the model sometimes returns fewer Reels than asked (Sebring came back with 2 of 4): one more try,
            # keeping only moments we don't already have
            try:
                take(plan(lead, playbook, rejects, facts, graded).get("reels"))
            except Exception as e:
                db.alert("maker", f"Reel top-up failed for {case}: {str(e)[:150]}", "info")
            if len(reels) < want:
                db.alert("maker", f"{case}: planned {len(reels)} of {want} Reels", "info")
        for n, r in enumerate(reels[:want], 1):
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
