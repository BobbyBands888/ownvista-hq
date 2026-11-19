"""WRITER — runs inside the render, right after the cut. Writes every word that appears on screen or in the
narration from what is actually in the chosen seconds (vision frame descriptions + transcript of those seconds),
so the text always matches the picture. Facts stay limited to what the plan already states (the Maker wrote it
from the lead and Compliance checked it). The Maker's lines are treated as drafts.
Fails soft: if the AI is down, the Maker's drafts are used, minus any line the check flags."""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents import packaging

RULES = """Rules: on-screen text and narration may only describe what the frames/transcript show for that moment,
plus facts from FACTS. Never invent arrests, charges, injuries, names, motives or outcomes. No graphic or gory
words. No clickbait the picture doesn't deliver. Plain, punchy, documentary tone (EWU / Code Blue Cam style).
Never "shootout", "gunfight" or "exchange of gunfire" unless FACTS say the suspect fired too; when only officers
fired, say "officer-involved shooting" or name what happened."""



def _cam(sc):
    """What the footage is, set by the Maker's fact check (agents/factcheck.py). Old plans: bodycam."""
    k = (sc or {}).get("camera") or "body"
    return ("police bodycam footage" if k == "body" else
            {"aerial": "aerial law-enforcement footage (NOT bodycam: never call it bodycam)",
             "dash": "police dashcam footage (NOT bodycam: never call it bodycam)"}.get(
                k, "law-enforcement footage (never call it bodycam unless the FACTS say it is)"))

def _span(f, s, e, pad=0.0):
    """What's on screen and said between s and e, with times relative to s."""
    frames = [f"{v['t'] - s:+.0f}s [{v['view']} a{v['action']}] {v['desc']}"
              for v in f.get("vision") or [] if s - pad <= v["t"] <= e + pad]
    words = [f"{t['start'] - s:+.0f}s \"{t['text']}\"" for t in f.get("transcript") or []
             if t["end"] >= s and t["start"] <= e]
    return {"frames": frames[:40], "said": words[:40]}


def _facts(plan, sc):
    keep = ("narration_setup", "what_happened_next", "title_card", "moment")
    cf = plan.get("case_facts") or {}
    case_file = {k: cf.get(k) for k in ("suspect_name", "suspect_age", "say_name", "why", "charges", "status", "outcome",
                                        "sentence") if cf.get(k) not in (None, "", [])}
    return {"title": plan.get("title"), "case": plan.get("case_name"), "description": (plan.get("description") or "")[:1200],
            **({"case_file": case_file} if case_file else {}), **{k: sc.get(k) for k in keep if sc.get(k)}}


def _ask(system, user):
    from agents.lib import llm
    return llm.ask(system, user, max_tokens=1800, temperature=0.4)


def write_episode(job, log=print):
    sc, pk, files = job.sc, job.pick, job.files
    clips = []
    for n, c in enumerate(pk["clips"]):
        f = files[c["file"]]
        if c.get("blur"):
            clips.append({"clip": n + 1, "label_now": c.get("label"), "length_s": round(c["end"] - c["start"]),
                          "shown": "FULLY BLURRED out of respect (aftermath). Its check-in line may only say the next "
                                   "moments are blurred out of respect; never describe injuries or the body."})
            continue
        clips.append({"clip": n + 1, "label_now": c.get("label"), "length_s": round(c["end"] - c["start"]),
                      **_span(f, c["start"], c["end"])})
    co = pk["cold_open"]
    cold = _span(files[co["file"]], co["start"], co["end"], pad=3)
    drafts = {k: sc.get(k) for k in ("cold_open_hook", "narration_setup", "check_ins", "what_happened_next",
                                      "comment_question")}
    j = _ask("You write the on-screen text and narration for a long-form episode of " + _cam(sc) + " AFTER the "
             "edit is locked. Every line must match the footage it sits next to. " + RULES,
             "FACTS (the only facts you may state):\n" + json.dumps(_facts(job.plan, sc)) +
             "\n\nDRAFTS from the planner (tone guide only; rewrite anything the footage doesn't show):\n" + json.dumps(drafts) +
             "\n\nCOLD OPEN (6-12s shown first):\n" + json.dumps(cold) +
             "\n\nCLIPS in order (frames: time from clip start, view, action 0-3, what's visible):\n" + json.dumps(clips) +
             f"""

Write:
- cold_open_hook: under 12 words, about what is visible in the cold open
- narration_setup: max 3 short sentences of context from FACTS (no claims about what the viewer is about to see
  unless clip 1 shows it)
- check_ins: exactly {max(0, len(clips) - 1)} lines; line k is read BEFORE clip k+1 and sets up what clip k+1 shows
  (max 14 words each)
- labels: one camera label per clip from what it shows (e.g. "Body Cam Officer 1", "Dash Cam", "Interview Room");
  road_ahead/windshield footage is "Dash Cam". The same officer's camera keeps the same label in every clip (it
  shows on screen as BODY CAM 1, BODY CAM 2 ...)
- what_happened_next: outcome from FACTS only, or "" if FACTS don't say
- comment_question: one short question about what the viewer just saw
- title + title_formula: the YouTube title, written for THIS cut (the cold open moment is what thumbnail A shows)
- thumbnail_texts: 3 options; option 1 is for the cold open moment, 2 and 3 for other peaks in the clips
{packaging.TITLE_RULES}
{packaging.THUMB_RULES}
Return JSON {{"cold_open_hook":"","narration_setup":"","check_ins":[""],"labels":[""],"what_happened_next":"",
"comment_question":"","title":"","title_formula":"","thumbnail_texts":["","",""]}}""")
    out = {}
    for k in ("cold_open_hook", "narration_setup", "what_happened_next", "comment_question"):
        if isinstance(j.get(k), str):
            out[k] = j[k].strip()
    cf = job.plan.get("case_facts") or {}
    has_outcome = bool(cf.get("outcome") or cf.get("sentence") or (sc.get("what_happened_next") or "").strip())
    if packaging.title_ok(j.get("title"), j.get("title_formula"), has_outcome):
        out["title"] = j["title"].strip()
        out["title_formula"] = packaging.formula_of(j["title_formula"])
    tt = packaging.thumb_texts(j.get("thumbnail_texts"), out.get("title") or job.plan.get("title"))
    if tt:
        out["thumbnail_texts"] = tt
        out["thumbnail_text"] = tt[0]
    if isinstance(j.get("check_ins"), list):
        out["check_ins"] = [str(x).strip() for x in j["check_ins"]][:max(0, len(clips) - 1)]
    if isinstance(j.get("labels"), list):
        import camlabel
        for c, lab in zip(pk["clips"], j["labels"]):
            if lab and not c.get("blur"):
                c["label"] = str(lab)[:40]
                if not camlabel.KEEP_RX.search(c["label"]):
                    c["cam"] = c["label"]          # the writer names the camera; numbering stays BODY CAM 1 / 2
        camlabel.assign(job.files, [c for c in pk["clips"] if not c.get("blur")], field="label")
    return out


def write_vertical(job, log=print):
    sc, pk, plan = job.sc, job.pick, job.plan
    f = job.files[pk["file"]]
    first = _span(f, pk["start"], pk["start"] + 4, pad=1)
    whole = _span(f, pk["start"], pk["end"])
    part = int(plan.get("part") or 0)
    from agents import casefacts
    narr = casefacts.narration_rules(plan.get("case_facts"))
    j = _ask("You write the hook text and the narrator lines for a vertical "
             f"{'YouTube Short' if plan['kind'] == 'short' else 'Facebook Reel'} of {_cam(sc)}, AFTER "
             "the clip is cut. The hook must match what is on screen in those first seconds. A narrator voice reads "
             "intro_vo over the opening seconds while the footage keeps playing underneath, and reads outcome_vo on "
             "an end card. " +
             ("This Reel is a STANDALONE single moment: never say Part 1/2/3, 'continued', 'what happens next' or "
              "refer to other clips; caption and question are about this clip only. " if plan["kind"] == "reel" else "")
             + RULES,
             "FACTS:\n" + json.dumps(_facts(plan, sc)) + "\n\n" + narr +
             "\n\nDRAFT hook (rewrite if the footage doesn't show it): " + json.dumps(sc.get("hook_text") or sc.get("on_screen_text")) +
             "\nDRAFT narrator lines: " + json.dumps({k: sc.get(k) for k in ("intro_vo", "outcome_vo")}) +
             "\n\nFIRST 4 SECONDS:\n" + json.dumps(first) + "\n\nWHOLE CLIP:\n" + json.dumps(whole) +
             '\n\nReturn JSON {"hook_text":"under 9 words, about what is visible right away (or what is about to happen '
             'in this clip)",'
             '"intro_vo":"' + ('' if plan["kind"] == "short" and part > 1 else
                               '1-2 short spoken sentences, max 24 words, read in about 6 seconds: place, who the suspect '
                               'is and why police were there, from the CASE FILE/FACTS only, natural documentary tone '
                               '(STYLE ONLY, a different case: never copy its place or facts — e.g. \'Las Cruces, New Mexico. Agents are chasing a man wanted on a felony warrant, '
                               'and he is not giving up.\'). Must not contradict the first seconds.') + '",'
             '"outcome_vo":"' + ('' if plan["kind"] == "short" and part in (1, 2) else
                                 'how the case ended in max 25 spoken words, following the HOW IT ENDED wording rule; '
                                 '"" if there is no case file or no outcome') + '"'
             + (',"caption":"PLACE. STAKES in under 10 words, about what this clip shows (e.g. '
             'STYLE ONLY, a different case: never copy its place or facts: \'Quemado, Texas. A man swinging tree branches has already hit a Border Patrol agent in the head.\')",'
             '"question":"one short question for the comments about what the viewer just saw",'
             '"hashtags":["3-4 tags like ' + ('#bodycam #police' if (sc.get('camera') or 'body') == 'body' else '#police #caughtoncamera') + '"]' if plan["kind"] == "reel" else "") + "}")
    h = (j.get("hook_text") or "").strip()
    out = {"hook_text": h, "on_screen_text": h} if h else {}
    for k in ("intro_vo", "outcome_vo"):
        v = j.get(k)
        if isinstance(v, str):
            out[k] = v.strip()
    if plan["kind"] == "reel" and (j.get("caption") or "").strip():
        out["caption"] = j["caption"].strip()
        out["question"] = (j.get("question") or "").strip()
        tags = [t if str(t).startswith("#") else "#" + str(t) for t in (j.get("hashtags") or [])][:4]
        out["hashtags"] = [t.replace(" ", "") for t in tags]
    return out


def check(job, written):
    """Second pass: flag any line that claims something the footage or facts don't support, and fix it."""
    if not written:
        return written
    pk, files = job.pick, job.files
    if job.plan["kind"] == "episode":
        ctx = {"cold_open": _span(files[pk["cold_open"]["file"]], pk["cold_open"]["start"], pk["cold_open"]["end"], 3),
               "clips": [["(fully blurred aftermath)"] if c.get("blur") else
                         _span(files[c["file"]], c["start"], c["end"])["frames"][:20] for c in pk["clips"]]}
    else:
        ctx = _span(files[pk["file"]], pk["start"], pk["end"])
    j = _ask("You fact-check video text against the footage and the facts before it is published. " + RULES,
             "FACTS:\n" + json.dumps(_facts(job.plan, job.sc)) + "\n\nFOOTAGE:\n" + json.dumps(ctx) +
             "\n\nTEXT:\n" + json.dumps(written) +
             '\n\nReturn the TEXT JSON with the same keys, changing only lines that the footage or facts do not '
             'support (rewrite them so they are supported, or "" if nothing fits). Also add "problems":["..."] '
             'listing what you changed.')
    fixed = {k: j[k] for k in written if k in j and type(j[k]) is type(written[k])}
    cf = job.plan.get("case_facts") or {}
    has_outcome = bool(cf.get("outcome") or cf.get("sentence") or (written.get("what_happened_next") or "").strip())
    if "title" in fixed and not packaging.title_ok(fixed["title"], fixed.get("title_formula") or written.get("title_formula"), has_outcome):
        fixed.pop("title")                  # the check broke the formula/length: keep the checked original
    if "thumbnail_texts" in fixed:
        fixed["thumbnail_texts"] = packaging.thumb_texts(fixed["thumbnail_texts"], fixed.get("title") or written.get("title")) \
            or written["thumbnail_texts"]
        fixed["thumbnail_text"] = fixed["thumbnail_texts"][0]
    return {**written, **fixed, "problems": j.get("problems") or []}


def write(job, log=print):
    """Rewrites job.sc in place. Returns what it wrote (also saved next to the video for the dashboard)."""
    if not any(f.get("vision") for f in job.files):
        log("writer: no vision for this footage — keeping the planner's text")
        return {}
    try:
        w = write_episode(job, log) if job.plan["kind"] == "episode" else write_vertical(job, log)
    except Exception as e:
        log(f"writer: {str(e)[:200]} — keeping the planner's text")
        return {}
    try:
        w = check(job, w)
    except Exception as e:
        log(f"writer check skipped: {str(e)[:160]}")
    cf = job.plan.get("case_facts") or {}
    if job.plan["kind"] == "episode" and not w.get("title") and not packaging.title_ok(
            job.plan.get("title"), (job.sc.get("analysis_tags") or {}).get("title_formula") or "Place + incident + bodycam",
            bool(cf.get("outcome") or job.sc.get("what_happened_next"))):
        body = (job.sc.get("camera") or "body") == "body"
        case = job.plan.get("case_name") or ("Bodycam" if body else "Police Footage")
        job.sc["title"] = f"{case}: Full {'Bodycam' if body else 'Footage'}"[:60]
        job.sc["title_formula"] = "Place + incident + bodycam"
        w["title"] = job.sc["title"]
        log(f"writer: plan title promised an outcome the case file doesn't have — using '{job.sc['title']}'")
    for p in w.get("problems") or []:
        log(f"writer fixed: {str(p)[:160]}")
    for k, v in w.items():
        if k == "check_ins" and isinstance(v, list):
            job.sc[k] = v                  # even empty: the planner's check-ins don't match the new cut
        elif k in ("hook_text", "on_screen_text", "cold_open_hook") and v == "":
            job.sc.pop(k, None)            # the check found nothing true to say: fall back to the case name
        elif k != "problems" and v not in (None, [], ""):
            job.sc[k] = v
        elif k in ("what_happened_next", "outcome_vo") and v == "":
            job.sc.pop(k, None)            # facts don't give an outcome: say nothing rather than guess
    log("writer: " + json.dumps({k: v for k, v in w.items() if k != "problems"})[:600])
    return w
