"""MAKER agent — turns obtained footage leads into full production plans: the YouTube episode,
3 YouTube Shorts (Part 1/2/3) and standalone Facebook action Reels. Uses the live playbook from
Research + Analytics. Rendering happens on Bobby's Mac (mac/runner.py) with the existing build tools."""
import json
from .lib import llm
from .lib.runner import RULES

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
- SHORTS: 3 vertical Shorts per episode labeled "<Case Name> Part 1/2/3", each ends "Follow for Part 2/3".
- FACEBOOK REELS: standalone 25-30s action Reels, real audio, action in the first 2 seconds, caption first line =
  case name, caption tags the full YouTube episode.
- Titles: specific and dramatic but accurate. Never show the death itself, gore or a lingering body; blur bystanders as needed."""

def plan(lead, playbook):
    return llm.ask(
        "You are the head of production for Ten-Four Tapes. Write production plans that follow the format exactly "
        "and apply the playbook. Accuracy matters: only state facts present in the lead.\n" + RULES + "\n" + FORMAT,
        "Playbook (what works right now):\n" + json.dumps(playbook) +
        "\n\nLead:\n" + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date",
                                                              "summary", "category", "source_type")}) +
        """

Return JSON:
{"case_name":"2-3 words",
 "credit":"Footage: <agency> (<public domain | public records request | official release>)",
 "episode":{"style":"case_story|action","title":"","description":"includes context + credit + no spoilers in first line",
   "tags":[""],"cold_open_hook":"on-screen text, under 12 words","title_card":"",
   "narration_setup":"max 3 short sentences","check_ins":["max 4 brief lines"],
   "angle_labels":["Body Cam Officer 1"],"what_happened_next":"","comment_question":"",
   "thumbnail_text":"max 4 words","blur_notes":"anything that must be blurred or cut (bodies, bystanders, IDs)"},
 "shorts":[{"part":1,"title":"<Case Name> Part 1","moment":"which moment to cut","on_screen_text":""}],
 "reels":[{"moment":"the 25-30s action moment","hook_text":"first 2s text","caption":"first line = case name"}]}
3 shorts and 1-2 reels.""", max_tokens=2500, temperature=0.6)

def main(db):
    # Mix of sources: local police/sheriff/prosecutor footage first; federal DVIDS (mostly U.S. Customs and
    # Border Protection) capped at 1 case per run so the channel isn't just Border Patrol videos.
    pool = db.select("leads", {"status": "eq.obtained", "order": "action_score.desc", "limit": 20})
    # cases already made as episodes before HQ existed — don't remake them
    made = ("yuma, az january 22, 2025", "brownsville, tx february 12, 2025", "brownsville, texas may 13, 2025",
            "bisbee, arizona june 19, 2024", "quemado, texas may 16, 2024", "laredo, texas sept 23, 2024")
    pool = [l for l in pool if not any(m in (l.get("title") or "").lower() for m in made)]
    local = [l for l in pool if l.get("source_type") != "dvids_public_domain"]
    federal = [l for l in pool if l.get("source_type") == "dvids_public_domain"]
    leads = local[:3]
    if len(leads) < 3 and federal:
        leads.append(federal[0])
    playbook = [p["insight"] for p in db.select("playbook", {"active": "is.true", "order": "created_at.desc", "limit": 20})]
    made = 0
    for lead in leads:
        # clear any half-made plan from a failed earlier run of this lead (never touches rendered/posted items)
        db.delete("content", {"lead_id": f"eq.{lead['id']}", "status": "eq.scripted"})
        p = plan(lead, playbook)
        ep = p.get("episode", {})
        case = p.get("case_name") or lead["title"][:30]
        credit = p.get("credit") or f"Footage: {lead.get('agency_name')}"
        src_type = lead["source_type"]
        epi = db.insert("content", {
            "lead_id": lead["id"], "kind": "episode", "case_name": case, "title": ep.get("title"),
            "description": (ep.get("description") or "") + f"\n\n{credit}", "tags": ep.get("tags") or [],
            "script": ep, "source_type": src_type, "source_credit": credit, "source_urls": [lead.get("source_url")],
        })[0]
        rows = []
        for s in p.get("shorts", [])[:3]:
            rows.append({"lead_id": lead["id"], "kind": "short", "parent_id": epi["id"], "part": s.get("part"),
                         "case_name": case, "title": s.get("title") or f"{case} Part {s.get('part')}",
                         "description": f"Full episode on the channel. {credit}", "script": s,
                         "source_type": src_type, "source_credit": credit, "source_urls": [lead.get("source_url")]})
        for r in p.get("reels", [])[:2]:
            rows.append({"lead_id": lead["id"], "kind": "reel", "parent_id": epi["id"], "part": None, "case_name": case,
                         "title": case, "description": (r.get("caption") or case) + f"\nFull episode on YouTube: Ten-Four Tapes\n{credit}",
                         "script": r, "source_type": src_type, "source_credit": credit,
                         "source_urls": [lead.get("source_url")]})
        db.insert("content", rows)
        db.update("leads", {"id": f"eq.{lead['id']}"}, {"status": "used"})
        made += 1
    return f"planned {made} cases ({made} episodes + shorts + reels)"
