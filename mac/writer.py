"""WRITER — runs inside the render, right after the cut. Writes every word that appears on screen or in the
narration from what is actually in the chosen seconds (vision frame descriptions + transcript of those seconds),
so the text always matches the picture. Facts stay limited to what the plan already states (the Maker wrote it
from the lead and Compliance checked it). The Maker's lines are treated as drafts.
Fails soft: if the AI is down, the Maker's drafts are used, minus any line the check flags."""
import json

RULES = """Rules: on-screen text and narration may only describe what the frames/transcript show for that moment,
plus facts from FACTS. Never invent arrests, charges, injuries, names, motives or outcomes. No graphic or gory
words. No clickbait the picture doesn't deliver. Plain, punchy, documentary tone (EWU / Code Blue Cam style)."""


def _span(f, s, e, pad=0.0):
    """What's on screen and said between s and e, with times relative to s."""
    frames = [f"{v['t'] - s:+.0f}s [{v['view']} a{v['action']}] {v['desc']}"
              for v in f.get("vision") or [] if s - pad <= v["t"] <= e + pad]
    words = [f"{t['start'] - s:+.0f}s \"{t['text']}\"" for t in f.get("transcript") or []
             if t["end"] >= s and t["start"] <= e]
    return {"frames": frames[:40], "said": words[:40]}


def _facts(plan, sc):
    keep = ("narration_setup", "what_happened_next", "title_card", "moment")
    return {"title": plan.get("title"), "case": plan.get("case_name"), "description": (plan.get("description") or "")[:1200],
            **{k: sc.get(k) for k in keep if sc.get(k)}}


def _ask(system, user):
    from agents.lib import llm
    return llm.ask(system, user, max_tokens=1800, temperature=0.4)


def write_episode(job, log=print):
    sc, pk, files = job.sc, job.pick, job.files
    clips = []
    for n, c in enumerate(pk["clips"]):
        f = files[c["file"]]
        clips.append({"clip": n + 1, "label_now": c.get("label"), "length_s": round(c["end"] - c["start"]),
                      **_span(f, c["start"], c["end"])})
    co = pk["cold_open"]
    cold = _span(files[co["file"]], co["start"], co["end"], pad=3)
    drafts = {k: sc.get(k) for k in ("cold_open_hook", "narration_setup", "check_ins", "what_happened_next",
                                      "comment_question")}
    j = _ask("You write the on-screen text and narration for a long-form police bodycam episode AFTER the edit is "
             "locked. Every line must match the footage it sits next to. " + RULES,
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
  road_ahead/windshield footage is "Dash Cam"
- what_happened_next: outcome from FACTS only, or "" if FACTS don't say
- comment_question: one short question about what the viewer just saw
Return JSON {{"cold_open_hook":"","narration_setup":"","check_ins":[""],"labels":[""],"what_happened_next":"",
"comment_question":""}}""")
    out = {}
    for k in ("cold_open_hook", "narration_setup", "what_happened_next", "comment_question"):
        if isinstance(j.get(k), str):
            out[k] = j[k].strip()
    if isinstance(j.get("check_ins"), list):
        out["check_ins"] = [str(x).strip() for x in j["check_ins"]][:max(0, len(clips) - 1)]
    if isinstance(j.get("labels"), list):
        for c, lab in zip(pk["clips"], j["labels"]):
            if lab:
                c["label"] = str(lab)[:40]
    return out


def write_vertical(job, log=print):
    sc, pk, plan = job.sc, job.pick, job.plan
    f = job.files[pk["file"]]
    first = _span(f, pk["start"], pk["start"] + 4, pad=1)
    whole = _span(f, pk["start"], pk["end"])
    j = _ask("You write the 2-3 second hook text that sits over the FIRST seconds of a vertical "
             f"{'YouTube Short' if plan['kind'] == 'short' else 'Facebook Reel'} of police bodycam footage, AFTER "
             "the clip is cut. The hook must match what is on screen in those first seconds. " + RULES,
             "FACTS:\n" + json.dumps(_facts(plan, sc)) +
             "\n\nDRAFT hook (rewrite if the footage doesn't show it): " + json.dumps(sc.get("hook_text") or sc.get("on_screen_text")) +
             "\n\nFIRST 4 SECONDS:\n" + json.dumps(first) + "\n\nWHOLE CLIP:\n" + json.dumps(whole) +
             '\n\nReturn JSON {"hook_text":"under 9 words, about what is visible right away (or what is about to happen '
             'in this clip)"' + (',"caption":"PLACE. STAKES in under 15 words, about what this clip shows (e.g. '
             '\'Quemado, Texas. A man swinging tree branches has already hit a Border Patrol agent in the head.\')",'
             '"question":"one short question for the comments about what the viewer just saw",'
             '"hashtags":["3-4 tags like #bodycam #police"]' if plan["kind"] == "reel" else "") + "}")
    h = (j.get("hook_text") or "").strip()
    out = {"hook_text": h, "on_screen_text": h} if h else {}
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
               "clips": [_span(files[c["file"]], c["start"], c["end"])["frames"][:20] for c in pk["clips"]]}
    else:
        ctx = _span(files[pk["file"]], pk["start"], pk["end"])
    j = _ask("You fact-check video text against the footage and the facts before it is published. " + RULES,
             "FACTS:\n" + json.dumps(_facts(job.plan, job.sc)) + "\n\nFOOTAGE:\n" + json.dumps(ctx) +
             "\n\nTEXT:\n" + json.dumps(written) +
             '\n\nReturn the TEXT JSON with the same keys, changing only lines that the footage or facts do not '
             'support (rewrite them so they are supported, or "" if nothing fits). Also add "problems":["..."] '
             'listing what you changed.')
    fixed = {k: j[k] for k in written if k in j and type(j[k]) is type(written[k])}
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
    for p in w.get("problems") or []:
        log(f"writer fixed: {str(p)[:160]}")
    for k, v in w.items():
        if k == "check_ins" and isinstance(v, list):
            job.sc[k] = v                  # even empty: the planner's check-ins don't match the new cut
        elif k != "problems" and v not in (None, [], ""):
            job.sc[k] = v
        elif k in ("what_happened_next",) and v == "":
            job.sc.pop(k, None)            # facts don't give an outcome: say nothing rather than guess
    log("writer: " + json.dumps({k: v for k, v in w.items() if k != "problems"})[:600])
    return w
