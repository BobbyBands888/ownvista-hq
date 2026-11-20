"""MAKER agent — turns obtained footage leads into full production plans: the YouTube episode,
3 YouTube Shorts (Part 1/2/3) and standalone Facebook action Reels. Uses the live playbook from
Research + Analytics. Rendering happens on Bobby's Mac (mac/runner.py) with the existing build tools."""
import json
import re
from datetime import datetime, timedelta, timezone
from .lib import llm
from .lib.runner import RULES
from .lib.sources import is_military_op, is_people_smuggling
from . import casefacts
from . import packaging
from . import footage
from . import danger
from . import backlog
from . import factcheck

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
- FACEBOOK REELS ARE BODYCAM-FIRST (Nov 18 rebuild, mac/reelcut.py): agency-released bodycam / dash with real action
  (rams, foot chases, Tasers, window punches, felony stops, shots fired) beats aerial / thermal / vessel B-roll.
  Each strong case gets TWO cuts of the same incident: a 60-95s narrated STORY cut (hook in big yellow text for the
  first 4s -> dash / approach -> bodycam action -> arrest -> 3s "How it ended") and a 20-30s all-ACTION cut. The
  renderer picks the segments and writes the captions + narrator lines from the agency's own statement.
- NARRATOR ON VERTICALS: every Reel and Part 1 Short opens with the narrator setting it up over the first seconds
  (place, who, why police were there) while the bodycam plays underneath; every Reel and Part 3 ends with a narrated
  "how it ended" line. Same voice as the episodes.
- SHORTS: 3 vertical Shorts per episode labeled "<Case Name> Part 1/2/3", each ends "Follow for Part 2/3".
- FACEBOOK REELS: standalone enforcement-action Reels (story cut 60-95s, action cuts 20-30s) (never "Part 1/2/3" — Facebook doesn't show Part 2 to
  Part 1's viewers), real audio, action in the first 2 seconds. When a case gets 2-3 Reels, each one is a DIFFERENT
  single moment of the incident (e.g. the stop, the run, the takedown) and stands on its own: a viewer who sees only
  that Reel understands it. No "part", "continued", "what happens next" or references to the other Reels. Caption line 1 = PLACE + STAKES in under 10 words
  (e.g. "Quemado, Texas. A man swinging tree branches has already hit a Border Patrol agent in the head."), plus at most
  one concrete, surprising detail the viewer will SEE (e.g. "...and the fight ends up in a swarm of bees.", "Watch the
  guy in green."), then 3-4 hashtags. No question in the caption: guessing questions ("What do you think will happen
  next?", "Was it a trap?", "Why two at once?", "What do you think about this boarding?") read as engagement bait and
  get our Reels flagged. Vague stakes ("officers converge on a rec center", "officers board a vessel") are not stakes:
  name the danger or the action. Our page data: specific-stakes captions get 37K-106K views; "Case Name — generic
  summary" captions, guessing-question captions and rescue Reels get under 1K.
- Titles: specific and dramatic but accurate. Unblurred gore or a body is never shown; a death on camera may stay in
  episodes, Shorts and Reels only under a full-frame blur (the renderer adds it); thumbnails and cold opens never
  include it. Blur bystanders as needed.
- """ + packaging.TITLE_RULES + """
- """ + packaging.THUMB_RULES + """
- FACTS: every narration line, check-in and "what happened next" must be stated in the lead text. Never invent an
  outcome (arrest, custody, charges, injuries, deaths). If the lead doesn't say how it ended, leave
  what_happened_next as "" — a wrong outcome is worse than none. If the lead says someone died, say so plainly
  and respectfully; the person is never shown dying, dead or badly wounded without a full-frame blur.
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
        return 2                    # blurred death is OK now (Nov 18): the story cut + one action cut
    strong = (lead.get("action_score") or 0) >= STRONG
    if lead.get("source_type") != "dvids_public_domain":
        return 5 if strong else 4
    return 3 if strong else 2

def _standalone(r):
    txt = " ".join(str(r.get(k) or "") for k in ("moment", "hook_text", "caption")).lower()
    return bool((r.get("moment") or "").strip()) and not PART_RE.search(txt)

def _camera_note(lead):
    kind = factcheck.camera_kind(lead)
    if kind == "body":
        return "\n\nCAMERA: this is " + factcheck.camera_phrase(kind) + "."
    return ("\n\nCAMERA: this is " + factcheck.camera_phrase(kind) + ", NOT bodycam. Never say bodycam/body camera "
            "anywhere (titles, hooks, captions, narration, hashtags); angle labels like \"" +
            factcheck.CAMERA_WORDS[kind][2] + " 1\".")



OIS_RX = re.compile(r"\b(officer|deputy|trooper|agent)[- ]involved shooting\b|\bOIS\b", re.I)
BARE_SHOOTING = re.compile(r"(?<![Ii]nvolved )\b(shooting)\b", re.I)


def ois_wording(text, lead):
    """Compliance fails a bare "Shooting" when officers fired: a lead the agency calls an officer/deputy-involved
    shooting always says so ("Erdman Shooting" -> "Erdman Officer-Involved Shooting")."""
    if not isinstance(text, str) or not text:
        return text
    src = " ".join(str((lead or {}).get(k) or "") for k in ("title", "summary"))
    m = OIS_RX.search(src)
    if not m:
        return text
    who = (m.group(1) or "officer").capitalize() if m.group(1) else "Officer"
    def rep(x):
        w = x.group(1)
        out = f"{who}-Involved {w}"
        return out.upper() if w.isupper() else out
    return BARE_SHOOTING.sub(rep, text)


def apply_ois(ep, shorts, reels, case, lead):
    case = ois_wording(case, lead)
    for k in ("title", "cold_open_hook", "title_card", "thumbnail_text"):
        ep[k] = ois_wording(ep.get(k), lead)
    ep["thumbnail_texts"] = [ois_wording(t, lead) for t in ep.get("thumbnail_texts") or []]
    for s in shorts:
        for k in ("title", "on_screen_text"):
            s[k] = ois_wording(s.get(k), lead)
    for r in reels:
        for k in ("hook_text", "caption"):
            r[k] = ois_wording(r.get(k), lead)
    return case

def plan(lead, playbook, rejects=(), facts=None, graded=None, max_reels=None):
    n_reels = reel_count(lead, facts) if max_reels is None else min(reel_count(lead, facts), max_reels)
    fatal_note = (" Someone died in this case: say so plainly and respectfully; the renderer blurs the moment of death"
                  " and any body full-frame, so never describe injuries or the body in hooks or captions."
                  if is_fatal(facts) else "")
    if is_case(lead):
        fatal_note = (" This is a case story: episode style must be case_story, and the one Reel is a teaser cut from the"
                      " police interview (a lie or a tense exchange), never the crime or its aftermath.")
    return llm.ask(
        "You are the head of production for Ten-Four Tapes. Write production plans that follow the format exactly "
        "and apply the playbook. Accuracy matters: only state facts present in the lead. Name drugs, weapons and charges exactly as the lead "
        "or case file says (cocaine is never \"cannabis\"), in thumbnails and hooks too. When officers fired and the "
        "suspect did not, say \"officer-involved shooting\" (never a bare \"Shooting\" in a name or title).\n" + RULES + "\n" + FORMAT,
        "Playbook (what works right now):\n" + json.dumps(playbook) +
        ("\n\nBobby REJECTED these recently — don't repeat what he didn't like:\n" + json.dumps(list(rejects))
         if rejects else "") +
        ("\n\nSCORECARD — our own posts graded at 48h against the same format. Write like the A's, not like the D's "
         "(captions, hooks, which moment, case type):\n" + json.dumps(graded) if graded else "") +
        "\n\nLead:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date",
                                                              "summary", "category", "source_type")}) +
        "\n\n" + casefacts.narration_rules(facts) + _camera_note(lead) +
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
 "reels":[{"moment":"one single 25-30s action moment, different from the other reels","hook_text":"the exact words shown on screen in the first 2 seconds (max 9 words; the text itself, never an instruction like 'First 2s: ...')","caption":"PLACE. STAKES of THIS moment (under 10 words) + optional one concrete visible detail; no question","hashtags":["#bodycam"],"intro_vo":"1-2 spoken sentences (max 24 words) the narrator reads over the opening seconds: place, who, why police were there","outcome_vo":"how it ended (max 25 words) or \"\""}]}
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

# ---------------- memory: never plan an incident we've already made or posted ----------------
DVIDS_ID = re.compile(r"dvidshub\.net/video/(\d+)")
DVIDS_NEAR = 15     # one release often lands as several DVIDS videos with back-to-back ids (HITRON 989073 / 989076)


def _dvids_id(lead):
    m = DVIDS_ID.search(lead.get("source_url") or "")
    return int(m[1]) if m else None


def covered(db):
    """What we've already made or posted: every case HQ planned (episodes, any status), plus every Facebook Reel and
    YouTube video Analytics has seen on our page/channel, which includes the ones posted by hand before HQ."""
    seen, out = set(), []
    def add(s):
        s = re.sub(r"\s+", " ", str(s or "")).strip()[:160]
        if s and s.lower() not in seen:
            seen.add(s.lower())
            out.append(s)
    used = db.select("leads", {"status": "eq.used", "select": "title,agency_name,source_url", "order": "created_at.desc",
                               "limit": 400})
    for c in db.select("content", {"kind": "eq.episode", "select": "case_name,title", "order": "created_at.desc", "limit": 300}):
        add(f"{c.get('case_name')}: {c.get('title')}")
    for l in used:
        add(l.get("title"))
    for m in db.select("metrics", {"external_id": "not.in.(channel,page)", "select": "raw", "order": "captured_on.desc",
                                   "limit": 600}):
        raw = m.get("raw") if isinstance(m.get("raw"), dict) else {}
        add(raw.get("title") or (raw.get("caption") or "").split("\n")[0])
    return out, used


def drop_covered(db, pool):
    """Skip leads that are the same incident as something already made/posted (or as a stronger lead in this pool).
    Rule first (neighbouring DVIDS ids from the same unit), then one AI check against the history."""
    if not pool:
        return pool, 0
    history, used = covered(db)
    used_ids = [(_dvids_id(l), (l.get("agency_name") or "").lower()) for l in used if _dvids_id(l)]
    keep, dropped = [], 0
    def skip(l, why):
        db.update("leads", {"id": f"eq.{l['id']}"}, {"status": "skipped",
                  "notes": ((l.get("notes") or "") + f"\nmaker: already covered: {why}").strip()})
    for l in pool:
        did, ag = _dvids_id(l), (l.get("agency_name") or "").lower()
        twin = next((x for x in keep if _dvids_id(x) and did and abs(_dvids_id(x) - did) <= DVIDS_NEAR
                     and (x.get("agency_name") or "").lower() == ag), None)
        if did and (twin or any(abs(did - u) <= DVIDS_NEAR and a == ag for u, a in used_ids)):
            skip(l, f"same DVIDS release as {twin['title'][:80] if twin else 'a case we already made'}")
            dropped += 1
            continue
        keep.append(l)
    if not history and len(keep) < 2:
        return keep, dropped
    try:
        j = llm.ask("You keep Ten-Four Tapes from posting the same incident twice. Same incident = the same event "
                    "(same place AND the same stop/chase/seizure/arrest), even when titled differently or released as "
                    "separate clips. The same TYPE of incident somewhere else is NOT a match.",
                    "ALREADY MADE OR POSTED:\n" + "\n".join(f"- {h}" for h in history[:250]) +
                    "\n\nCANDIDATES (in priority order):\n" + json.dumps([{"i": n, "title": l["title"],
                     "agency": l.get("agency_name"), "summary": (l.get("summary") or "")[:200]} for n, l in enumerate(keep)]) +
                    '\n\nFlag a candidate that matches the history, or that matches an EARLIER candidate in this list. '
                    'Only clear matches. Return JSON {"dupes":[{"i":0,"same_as":"what it duplicates"}]}',
                    max_tokens=700, temperature=0.1)
        dupes = {d.get("i"): d.get("same_as") for d in (j.get("dupes") or []) if isinstance(d, dict)}
    except Exception as e:
        db.alert("maker", f"Duplicate check skipped this run: {str(e)[:150]}", "info")
        return keep, dropped
    out = []
    for n, l in enumerate(keep):
        if n in dupes:
            skip(l, str(dupes[n] or "same incident")[:150])
            dropped += 1
        else:
            out.append(l)
    return out, dropped


# ---------------- re-cut mode: more Reels from the footage behind our best Facebook Reels ----------------
RECUTS_PER_WINNER = 2       # lifetime, counted from the original winner (a re-cut that wins counts toward its root)
RECUT_MAX_PER_RUN = 6
WINNER_DAYS = 60            # only Reels posted in the last 60 days
WINNER_MIN_AGE_H = 72       # let the original run its course before a re-cut follows it
WIN_VIEWS = 30000           # an A on our page's Reel floors (analytics.FLOORS)
TOP_UP_VIEWS = 10000        # if fewer than 3 A's, the best B's (10K+) count too


def winners(db):
    """Our top Facebook Reels, best first: graded A (or 30K+ views), topped up with 10K+ Reels when there are few A's.
    Views come from the Scorecard; Reels not graded yet fall back to the latest Facebook numbers."""
    now = datetime.now(timezone.utc)
    since, ripe = (now - timedelta(days=WINNER_DAYS)).isoformat(), (now - timedelta(hours=WINNER_MIN_AGE_H)).isoformat()
    base = {"kind": "eq.reel", "status": "eq.posted", "facebook_id": "not.is.null",
            "posted_at": f"gte.{since}", "limit": 200}
    cols = "id,lead_id,parent_id,case_name,title,description,script,source_type,source_credit,source_urls,posted_at"
    try:
        rows = db.select("content", {**base, "select": cols + ",score_grade,score_views"})
    except RuntimeError:                         # Scorecard SQL not run: no grades, numbers only
        rows = db.select("content", {**base, "select": cols})
    rows = [r for r in rows if str(r.get("posted_at") or "") <= ripe]
    if not rows:
        return []
    views = {}
    for m in db.select("metrics", {"platform": "eq.facebook", "content_id": f"in.({','.join(r['id'] for r in rows)})",
                                   "select": "content_id,views", "order": "captured_on.desc", "limit": 2000}):
        if m.get("views") is not None:
            views[m["content_id"]] = max(views.get(m["content_id"], 0), int(m["views"]))
    for r in rows:
        r["_views"] = max(int(r.get("score_views") or 0), views.get(r["id"], 0))
    rows.sort(key=lambda r: -r["_views"])
    top = [r for r in rows if r.get("score_grade") == "A" or r["_views"] >= WIN_VIEWS]
    if len(top) < 3:
        top += [r for r in rows if r not in top and r["_views"] >= TOP_UP_VIEWS][:3 - len(top)]
    return top


def _root(r):
    sc = r.get("script") if isinstance(r.get("script"), dict) else {}
    return sc.get("recut_of") or r["id"]


def _footage_kept(db, lead_ids):
    """Leads whose footage the publisher can still get: DVIDS (public domain, always re-downloadable) or a
    delivered records package (kept on the footage-<lead> release, or the agency's link)."""
    if not lead_ids:
        return set()
    ok = {l["id"] for l in db.select("leads", {"id": f"in.({','.join(lead_ids)})", "select": "id,source_type"})
          if l.get("source_type") == "dvids_public_domain"}
    ok |= {r["lead_id"] for r in db.select("records_requests", {"lead_id": f"in.({','.join(lead_ids)})",
                                                               "status": "eq.fulfilled", "select": "lead_id"})}
    return ok


def recut_plan(lead, winner, facts, playbook, rejects=()):
    """Words for one new standalone Reel from the same incident. The cutter (mac/picker.py) picks the window: the same
    moment from another officer's camera when there is one, otherwise the next strongest moment, never the winner's clip."""
    wsc = winner.get("script") if isinstance(winner.get("script"), dict) else {}
    return llm.ask(
        "You are the head of production for Ten-Four Tapes. Accuracy matters: only state facts present in the lead.\n"
        + RULES + "\n" + FORMAT,
        "One of our best Facebook Reels (" + f"{winner['_views']:,} views" + "):\n" + json.dumps({
            "caption": (winner.get("description") or "").splitlines()[0][:200], "hook_text": wsc.get("hook_text"),
            "moment": wsc.get("moment")}) +
        "\n\nPlaybook:\n" + json.dumps(playbook[:12]) +
        ("\n\nBobby REJECTED these recently — don't repeat what he didn't like:\n" + json.dumps(list(rejects)[:10])
         if rejects else "") +
        "\n\nLead:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date",
                                                              "summary", "category", "source_type")}) +
        "\n\n" + casefacts.narration_rules(facts) + _camera_note(lead) +
        """

Write ONE new standalone 25-30s Facebook Reel from this same incident's footage. It is a RE-CUT, not a repost:
- The cutter will first look for the SAME moment from ANOTHER officer's camera (a different angle is new footage);
  if there isn't one it takes the next strongest DIFFERENT moment of the incident. Describe both in "moment" and
  "fallback_moment". It never reuses the winner's clip.
- Keep what made the winner work (place + stakes caption, action in the first 2 seconds), but every word is new:
  a different hook_text and a different caption from the winner's. Standalone: no "part", "again", "another angle",
  "continued" or references to the earlier Reel.
Return JSON {"moment":"","fallback_moment":"","hook_text":"the exact words shown on screen in the first 2 seconds (max 9 words; the text itself, never an instruction like 'First 2s: ...')","caption":"PLACE. STAKES of THIS moment (under 10 words) + optional one concrete visible detail; no question",
"hashtags":["#bodycam"],"intro_vo":"1-2 spoken sentences (max 24 words): place, who, why police were there","outcome_vo":"how it ended (max 25 words) or \\"\\""}""",
        max_tokens=900, temperature=0.7)


def recut(db, want, playbook, rejects):
    """Plan up to `want` re-cut Reels from our top Facebook Reels. Returns (made, note)."""
    if want <= 0:
        return 0, ""
    tops = winners(db)
    if not tops:
        return 0, "no winning Reels to re-cut yet"
    ids = list({r["lead_id"] for r in tops if r.get("lead_id")})
    if not ids:
        return 0, "winning Reels have no lead on file"
    kept = _footage_kept(db, ids)
    leads = {l["id"]: l for l in db.select("leads", {"id": f"in.({','.join(ids)})", "select": "*"})}
    made, skipped = 0, []
    for w in tops:
        if made >= min(want, RECUT_MAX_PER_RUN):
            break
        lead = leads.get(w.get("lead_id"))
        if not lead or w["lead_id"] not in kept:
            skipped.append(f"{w['case_name']}: footage not kept")
            continue
        root = _root(w)
        done = db.select("content", {"script->>recut_of": f"eq.{root}", "select": "id", "limit": 10})
        if len(done) >= RECUTS_PER_WINNER:
            continue
        # a re-cut waiting to post already covers this winner: one at a time per winner
        if db.select("content", {"script->>recut_of": f"eq.{root}", "status": "in.(scripted,rendered)",
                                 "select": "id", "limit": 1}):
            continue
        sib = db.select("content", {"kind": "eq.reel", "select": "script",
                                    **({"parent_id": f"eq.{w['parent_id']}"} if w.get("parent_id")
                                       else {"lead_id": f"eq.{w['lead_id']}"})})
        n = 1 + max([int((s.get("script") or {}).get("reel_no") or 0) for s in sib if isinstance(s.get("script"), dict)] or [0])
        secs = footage.seconds_from_notes(lead.get("notes"))
        if secs is not None and footage.budget(secs)["reels"] < n:
            skipped.append(f"{w['case_name']}: every {footage.REEL_EACH}s of its {secs}s is already a Reel")
            continue
        facts = casefacts.get(db, lead["id"])
        try:
            r = recut_plan(lead, w, facts, playbook, rejects)
        except Exception as e:
            db.alert("maker", f"Re-cut plan failed for {w['case_name']}: {str(e)[:150]}", "info")
            continue
        r = factcheck.check(r, lead, facts)
        old_cap = ((w.get("description") or "").splitlines() or [""])[0].strip().lower()
        if not _standalone(r) or (r.get("caption") or "").strip().lower() == old_cap:
            skipped.append(f"{w['case_name']}: plan repeated the winner")
            continue
        wsc = w.get("script") if isinstance(w.get("script"), dict) else {}
        r.update(reel_no=n, recut_of=root, recut={"of": root, "winner": w["id"], "winner_views": w["_views"],
                                                  "winner_moment": wsc.get("moment"), "winner_cut": wsc.get("cut")})
        credit = w.get("source_credit") or f"Footage: {lead.get('agency_name')}"
        db.insert("content", {"lead_id": lead["id"], "kind": "reel", "parent_id": w.get("parent_id"), "part": None,
                              "case_name": w["case_name"], "title": w["case_name"],
                              "description": (r.get("caption") or w["case_name"]) +
                              f"\nFull episode on YouTube: Ten-Four Tapes\n{credit}" +
                              ("\n" + " ".join(r["hashtags"][:4]) if r.get("hashtags") else ""),
                              "script": r, "source_type": w.get("source_type") or lead.get("source_type"),
                              "source_credit": credit, "source_urls": w.get("source_urls") or [lead.get("source_url")]})
        made += 1
    return made, ("; ".join(skipped[:4]) if skipped and not made else "")


def _sources(ep, facts):
    if not facts or not facts.get("sources") or "Sources:" in (ep.get("description") or ""):
        return ""
    return "\n\nSources:\n" + "\n".join(s["url"] for s in facts["sources"][:5])

def main(db):
    st = backlog.status(db)
    low = st["reel"]["days"] is not None and st["reel"]["days"] < st["target_days"]
    # Mix of sources: local police/sheriff/prosecutor footage first; federal DVIDS (mostly U.S. Customs and
    # Border Protection) fills in (see below) so the channel isn't just Border Patrol videos.
    pool = db.select("leads", {"status": "eq.obtained", "order": "action_score.desc", "limit": 60})
    # cases already made as episodes before HQ existed — don't remake them
    made = ("yuma, az january 22, 2025", "brownsville, tx february 12, 2025", "brownsville, texas may 13, 2025",
            "bisbee, arizona june 19, 2024", "quemado, texas may 16, 2024", "laredo, texas sept 23, 2024")
    pool = [l for l in pool if not any(m in (l.get("title") or "").lower() for m in made)]
    # military operations / boat strikes from DVIDS are off-format: retire them instead of planning cases
    for l in [l for l in pool if is_military_op(l)]:
        db.update("leads", {"id": f"eq.{l['id']}"}, {"status": "skipped",
                                                     "notes": ((l.get("notes") or "") + "\nmaker: military operation, not police footage").strip()})
    pool = [l for l in pool if not is_military_op(l)]
    # migrant / human-smuggling boats: minors can't be ruled out on camera, so Bobby rejects every one
    for l in [l for l in pool if is_people_smuggling(l)]:
        db.update("leads", {"id": f"eq.{l['id']}"}, {"status": "skipped",
                  "notes": ((l.get("notes") or "") + "\nmaker: migrant/people-smuggling case, minors can't be ruled out").strip()})
    pool = [l for l in pool if not is_people_smuggling(l)]
    # enforcement action first (it's what the page's hits are), then case stories, then rescues
    rank = {"enforcement": 0, "case_story": 1, "other": 2, "rescue": 3}
    # Case Desk must have researched who/why/outcome first; cases without a case file wait for its next run
    files = {l["id"]: casefacts.get(db, l["id"]) for l in pool}
    # within each category, cases where nobody died go first: they pass review and yield more Reels
    # and the most on-screen danger first (agents/danger.py), then action
    pool.sort(key=lambda l: (rank.get(l.get("category") or "other", 2), is_fatal(files.get(l["id"])),
                             danger.key(l)))
    # never the same incident twice: skips what we already made/posted (HQ or by hand) and same-release twins
    pool, n_dup = drop_covered(db, pool)
    local = [l for l in pool if l.get("source_type") != "dvids_public_domain"]
    federal = [l for l in pool if l.get("source_type") == "dvids_public_domain"]
    local = [l for l in local if files.get(l["id"])]
    federal = [l for l in federal if files.get(l["id"])]
    # 3 Shorts/day = 1 case/day. Local cases first; federal DVIDS (public domain, no request needed) is capped at 1
    # per run so the channel isn't all Border Patrol — except when no local case is ready, then 2 so it never runs dry.
    # Below the 2-week backlog: up to 5 cases a run instead of 3 (federal still capped so it isn't all Border Patrol)
    n_cases = 5 if low else 3
    leads = local[:n_cases]
    leads += federal[:(2 if low else 1) if local else 2][:n_cases - len(leads)]
    pb = db.select("playbook", {"active": "is.true", "order": "created_at.desc", "limit": 40})
    # scorecard lessons always make the cut (they're about OUR posts); then the newest of the rest
    playbook = [p["insight"] for p in pb if p.get("source") == "scorecard"][:5] + \
               [p["insight"] for p in pb if p.get("source") != "scorecard"][:15]
    graded = scorecard_examples(db)
    rejects = [f"{r['kind']}: {r.get('title')} — {(r.get('publish_note') or '').replace('Rejected: ', '')}"
               for r in db.select("content", {"select": "kind,title,publish_note", "approval_status": "eq.rejected",
                                              "order": "created_at.desc", "limit": 15})]
    made = n_reel = n_fixed = 0
    for lead in leads:
        # clear any half-made plan from a failed earlier run of this lead (never touches rendered/posted items)
        db.delete("content", {"lead_id": f"eq.{lead['id']}", "status": "eq.scripted"})
        facts = files.get(lead["id"])
        # plan only what the footage can carry (length known from Scout for YouTube / DVIDS leads)
        secs = footage.seconds_from_notes(lead.get("notes"))
        fit = footage.budget(secs)
        if secs is not None and not fit["episode"] and not fit["shorts"] and not fit["reels"]:
            db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "skipped",
                      "notes": f"too short to make anything: {secs}s of video — " + (lead.get("notes") or "")})
            continue
        p = plan(lead, playbook, rejects, facts, graded, max_reels=fit["reels"])
        ep = p.get("episode", {})
        # the lead's own title can hide it ("cutter interdicts vessel"); the plan says it plainly ("240 Migrants")
        if is_people_smuggling({"title": ep.get("title"), "summary": ep.get("description") or ep.get("what_happened_next")}):
            db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "skipped",
                      "notes": ((lead.get("notes") or "") + "\nmaker: plan shows a migrant/people-smuggling case, minors can't be ruled out").strip()})
            continue
        case = p.get("case_name") or lead["title"][:30]
        credit = p.get("credit") or f"Footage: {lead.get('agency_name')}"
        src_type = lead["source_type"]
        ep = fix_packaging(ep, lead, facts)
        ep["analysis_tags"] = analysis_tags(ep.get("analysis_tags"), lead)
        shorts = [s for s in p.get("shorts", []) if isinstance(s, dict)][:fit["shorts"]]
        # standalone single-moment Reels (count from reel_count); rescues get the episode + Shorts only
        want = min(reel_count(lead, facts), fit["reels"])
        reels, seen = [], set()
        def take(cands):
            for r in cands or []:
                key = (r.get("moment") or "").strip().lower()[:60] if isinstance(r, dict) else ""
                if isinstance(r, dict) and _standalone(r) and key not in seen:
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
        reels = reels[:want]
        # Reel 1 is the 60-95s narrated story cut, the rest are 20-30s action cuts (mac/reelcut.py picks the
        # segments; a case whose action can't carry 60s gets the short cut instead). Case-story teasers stay single.
        for n, r in enumerate(reels):
            r["cut_kind"] = "story" if n == 0 and not is_case(lead) else "action"
        # fact check: hooks are screen text (not instructions), no invented facts, the right camera word
        title0 = ep.get("title")
        checked = factcheck.check({"episode": ep, "shorts": shorts, "reels": reels}, lead, facts)
        ep, shorts, reels = checked["episode"], checked["shorts"], checked["reels"]
        case = apply_ois(ep, shorts, reels, case, lead)
        if ep.get("title") != title0 and not packaging.title_ok(
                ep.get("title"), (ep.get("analysis_tags") or {}).get("title_formula"),
                bool((facts or {}).get("outcome") or (facts or {}).get("sentence"))):
            ep["title"] = factcheck._fix_camera_words(title0, factcheck.camera_kind(lead))   # the check broke the formula
        n_fixed += len((ep.get("factcheck") or {}).get("fixed") or [])
        epi = db.insert("content", {
            "lead_id": lead["id"], "kind": "episode", "case_name": case, "title": ep.get("title"),
            "description": (ep.get("description") or "") + f"\n\n{credit}" + _sources(ep, facts), "tags": ep.get("tags") or [],
            "script": ep, "source_type": src_type, "source_credit": credit, "source_urls": [lead.get("source_url")],
            # too little footage for an episode: the row stays (Shorts/Reels hang off it) but is never rendered
            **({} if fit["episode"] else {"status": "failed",
                "publish_note": f"Skipped: only {secs}s of footage (an episode needs {footage.EPISODE_MIN // 60} min+)"}),
        })[0]
        rows = []
        for s in shorts:
            rows.append({"lead_id": lead["id"], "kind": "short", "parent_id": epi["id"], "part": s.get("part"),
                         "case_name": case, "title": s.get("title") or f"{case} Part {s.get('part')}",
                         "description": f"Full episode on the channel. {credit}", "script": s,
                         "source_type": src_type, "source_credit": credit, "source_urls": [lead.get("source_url")]})
        for n, r in enumerate(reels, 1):
            r["reel_no"] = n
            rows.append({"lead_id": lead["id"], "kind": "reel", "parent_id": epi["id"], "part": None, "case_name": case,
                         "title": case, "description": (r.get("caption") or case) + f"\nFull episode on YouTube: Ten-Four Tapes\n{credit}"
                         + ("\n" + " ".join(r["hashtags"][:4]) if r.get("hashtags") else ""),
                         "script": r, "source_type": src_type, "source_credit": credit,
                         "source_urls": [lead.get("source_url")]})
        n_reel += sum(1 for r in rows if r["kind"] == "reel")
        if secs is not None and (not fit["episode"] or fit["shorts"] < 3):
            db.alert("maker", f"{case}: only {secs}s of footage, so planned "
                     f"{'an episode, ' if fit['episode'] else 'no episode, '}{min(fit['shorts'], 3)} Shorts and "
                     f"{sum(1 for r in rows if r['kind'] == 'reel')} Reels", "info")
        db.insert("content", rows)
        db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "used"})
        made += 1
    # Re-cut mode: still short of the 2-week Reel backlog after planning every case we have footage for ->
    # new Reels from the footage behind our best Facebook Reels (settings.recut_mode: "auto" | "off")
    n_re, re_note = 0, ""
    st = backlog.status(db)
    if str(db.setting("recut_mode", "auto")).lower() != "off" and st["reel"]["short_by"] > 0:
        try:
            n_re, re_note = recut(db, st["reel"]["short_by"], playbook, rejects)
        except Exception as e:
            re_note = f"re-cut error: {str(e)[:150]}"
            db.alert("maker", f"Re-cut mode failed: {str(e)[:200]}", "warn")
        if n_re:
            st = backlog.status(db)
    backlog.save(db, st)
    if st["reel"]["days"] is not None and st["reel"]["days"] < st["target_days"]:
        db.alert_once("maker", f"Backlog low — {backlog.line(st)}. Maker planned everything it has footage for"
                      + (f" and {n_re} re-cuts" if n_re else "") + ". More footage is the fix: Outreach requests the most "
                      "dangerous leads first.", "info", key="Backlog low")
    else:
        db.resolve_alerts("maker", "Backlog low")
    return (f"planned {made} cases ({made} episodes + shorts + {n_reel} standalone reels)"
            + (f", skipped {n_dup} already-covered incidents" if n_dup else "")
            + (f", fact check fixed {n_fixed} lines" if n_fixed else "")
            + (f", {n_re} re-cut reels from top Facebook Reels" if n_re else "")
            + (f" ({re_note})" if re_note else "") + f"; {backlog.line(st)}")
