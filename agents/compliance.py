"""COMPLIANCE agent — the gate. Nothing posts until it passes here.
Hard checks (code): footage provenance, credit line, minors confirmed absent.
Soft checks (LLM): YouTube/Facebook violent-content policy, misleading titles, death-on-camera, blur needs."""
import json
from datetime import date
from .lib import llm
from .lib.runner import RULES
from . import casefacts
from .maker import is_fatal as maker_fatal

def provenance_ok(db, item, lead):
    st = item.get("source_type")
    if st == "dvids_public_domain":
        return True, "public domain (DVIDS)"
    if lead and "direct:" in (lead.get("notes") or ""):
        return True, "agency/prosecutor direct release confirmed by Bobby"
    if lead:
        reqs = db.select("records_requests", {"lead_id": f"eq.{lead['id']}", "status": "eq.fulfilled", "select": "id"})
        if reqs:
            return True, "obtained by public records request"
    return False, "no proof footage came from the agency (need a fulfilled records request or a confirmed direct release)"

def review(item, lead=None, facts=None):
    return llm.ask(
        "You are a strict YouTube and Facebook policy reviewer for a police bodycam channel. One strike costs a week "
        "of uploads; three end the channel. Fail anything risky.\n" + RULES,
        json.dumps({k: item.get(k) for k in ("kind", "case_name", "title", "description", "tags", "script")}) +
        "\n\nSOURCE FACTS (the only facts we have):\n" + json.dumps({k: (lead or {}).get(k) for k in
                                                                    ("title", "summary", "incident_date", "agency_name")}) +
        "\n\nCASE FILE (researched who/why/outcome with sources; also counts as source facts):\n" + json.dumps(facts) +
        '\n\nCheck: ANY claim in the title, narration, check-ins or what_happened_next that the source facts do not '
        'state (invented arrests, outcomes, charges, motives) — fail it; a case where someone was shot or died and the '
        'plan would show the person dying, dead or badly wounded WITHOUT a full-frame blur — fail it; an outcome worded more strongly than the case file '
        '(charges called a conviction, "is a thief" before a verdict) — fail it; a named person when the case file says '
        'say_name is false — fail it; graphic or shocking words in title/thumbnail text; misleading or clickbait claims not supported by '
        'the script; any sign a minor appears; any plan to show unblurred gore, a body or a death (a death on camera is ALLOWED in episodes, Shorts and Reels when the renderer puts a full-frame blur over it — do not fail a plan for that); any death imagery planned for a thumbnail or cold open; graphic words about injuries or the body; missing educational/'
        'documentary context in the description; personal info (addresses, phone numbers) of private people.\n'
        'Return JSON {"verdict":"pass|fail","issues":["..."],"required_edits":["blur/cut/rename instructions for the render"],'
        '"minor_present":true|false|null}', max_tokens=700, temperature=0.1)

def main(db):
    # rejected plans are done: no safety review needed
    items = db.select("content", {"compliance_status": "eq.pending", "status": "neq.failed",
                                  "approval_status": "neq.rejected", "order": "created_at.asc", "limit": 25})
    until = db.setting("approval_required_until", "2026-11-23")
    need_approval = date.today().isoformat() < str(until)
    # Earned autonomy: a format (reel / short / episode) posts on its own once Bobby's last N decisions on
    # that format were all approvals. One reject puts it back on review until it earns its way out again.
    streak_needed = int(db.setting("auto_post_after_approvals", 10))
    earned = {}
    for kind in ("reel", "short", "episode"):
        # only decisions on FINISHED videos count (a plan approval says nothing about what the render shows)
        recent = db.select("content", {"select": "approval_status", "kind": f"eq.{kind}",
                                       "approval_status": "in.(approved,rejected)", "media_path": "not.is.null",
                                       "order": "created_at.desc", "limit": streak_needed})
        earned[kind] = len(recent) >= streak_needed and all(r["approval_status"] == "approved" for r in recent)
        # ...and the machine's own post-render auto-check passed the last N finished videos of that kind
        checked = db.select("content", {"select": "ac:script->autocheck->>verdict", "kind": f"eq.{kind}",
                                        "media_path": "not.is.null", "script->autocheck": "not.is.null",
                                        "order": "created_at.desc", "limit": streak_needed})
        earned[kind] = earned[kind] and len(checked) >= streak_needed and all(c.get("ac") == "pass" for c in checked)
    passed = failed = 0
    leads_cache = {}
    for it in items:
        lid = it.get("lead_id")
        if lid and lid not in leads_cache:
            r = db.select("leads", {"id": f"eq.{lid}"})
            leads_cache[lid] = r[0] if r else None
        lead = leads_cache.get(lid)
        issues = []
        ok, why = provenance_ok(db, it, lead)
        if not ok:
            issues.append(why)
        if not it.get("source_credit"):
            issues.append("missing credit line")
        facts = casefacts.get(db, lid) if lid else None
        if it["kind"] == "episode":
            sc = it.get("script") or {}
            if not facts:
                issues.append("no case file yet (who / why / how it ended) — Case Desk must research it first")
            elif not (sc.get("what_happened_next") or "").strip():
                issues.append("episode doesn't say how the case ended (what_happened_next is empty)")
            if facts and facts.get("suspect_name") and not facts.get("say_name"):
                blob = json.dumps(sc) + (it.get("title") or "") + (it.get("description") or "")
                last = facts["suspect_name"].split()[-1]
                if last and last.lower() in blob.lower():
                    issues.append(f"names {facts['suspect_name']} but the case file says not to (minor / dropped / acquitted)")
        r = review(it, lead, facts)
        issues += r.get("issues", []) if r.get("verdict") == "fail" else []
        minor = r.get("minor_present")
        lead_minor = lead.get("involves_minor") if lead else None
        if minor is True or lead_minor is True:
            issues.append("minor may be present — not allowed")
        elif lead_minor is None and minor is not False:
            issues.append("minors not confirmed absent — confirm on dashboard")
        edits = r.get("required_edits", [])
        notes = (f"Provenance: {why}. " + ("Issues: " + "; ".join(issues) + ". " if issues else "") +
                 ("Render edits: " + "; ".join(edits) if edits else "")).strip()
        if issues:
            db.update("content", {"id": f"eq.{it['id']}"}, {"compliance_status": "fail", "compliance_notes": notes})
            failed += 1
        else:
            auto = (not need_approval or earned.get(it["kind"])) and it["kind"] != "episode" and not maker_fatal(facts)
            db.update("content", {"id": f"eq.{it['id']}"}, {
                "compliance_status": "pass", "compliance_notes": notes,
                # a plan Bobby already approved stays approved (it still comes back for a video review after render)
                "approval_status": "approved" if it.get("approval_status") == "approved"
                else ("not_required" if auto else "pending")})
            if auto and need_approval:
                db.alert("compliance", f"Auto-posting (earned) for {it['kind']} '{it.get('title') or it['case_name']}' — "
                         "no one reviews this video before it posts", "warn")
            passed += 1
    if failed:
        db.alert("compliance", f"{failed} item(s) blocked — see Content queue for reasons", "info")
    auto = [k for k, v in earned.items() if v]
    return (f"reviewed {len(items)}: {passed} passed, {failed} blocked; approval "
            f"{'required until ' + str(until) if need_approval else 'off (full auto)'}"
            f"{'; auto-posting earned: ' + ', '.join(auto) if auto and need_approval else ''}")
