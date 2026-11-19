"""BODYCAM REEL (Nov 18 rebuild) — the Reel path, ported from tools/manual_reels (Kettering / Thurston).

Two cuts per strong case (Meta: 10-30s drives reach, 30s-3min drives engagement):
  story  60-95s: hook (big yellow text, first 4s) -> dash / approach -> bodycam action -> arrest -> 3s "How it ended"
  action 20-30s: the same incident, nothing but the action, one narrator line, same end card
Every second of action is kept; slates, maps, text screens and repeated angles are cut.

Narrator: Kokoro am_adam (media.VOICE). Camera audio ducks ~75% under each line; gunshots / impacts are never
talked over (lines are moved off loud peaks). Every narrator line and caption comes from the agency's own text
(the lead + case file) and is fact-checked by agents/factcheck.ai_check before the render.

Rule (Bobby, Nov 18): a death on camera is OK only under a FULL-FRAME blur over the moment and any body. Frames the
vision pass tags gore, and audio aftermath (CPR, "no pulse"), become blur windows. A child on camera is never used.

Pick shape (saved in the folder's pick cache and on the plan as script["cut"]):
  {"cut":"story|action","segments":[{"file":0,"start":18.0,"end":30.0}],"blur":[[t0,t1]],"total":92.0}
blur windows are on the OUTPUT timeline (seconds from the start of the Reel)."""
import json
import re
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import media  # noqa: E402
import picker  # noqa: E402

STORY = (60.0, 95.0)
ACTION = (20.0, 30.0)
END_SECS = 3.2            # "How it ended" card, frozen last frame under it
HOOK_SECS = 4.0           # big yellow hook text
DUCK = 0.25               # camera level under a narrator line (ducks 75%)
PEAK_DB = 10.0            # a second this far above the file's median loudness is a gunshot / impact / crash
MIN_SEG = 4.0
GAP_MERGE = 4             # action seconds this close are one beat
BLUR_PAD = 1.0
MAX_BLUR_RUN = 10.0       # a blurred stretch never runs longer than this: the cut moves on
YELLOW = "0xF5C518"


def _font(kind):
    try:
        return media.font(kind, 40).path
    except Exception:
        return "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"


# ---------------- per-second view of a file ----------------
def seconds(f):
    """Per-second dict of arrays: act (0-3), screen, child, gore, unknown, peak. Unknown = no vision frame close
    enough to say there's no child; unknown seconds are never used."""
    n = int(f["duration"]) + 1
    fr = sorted(f.get("vision") or [], key=lambda v: v["t"])
    act, screen, child, gore, unk = [0.0] * n, [0] * n, [0] * n, [0] * n, [0] * n
    gap = max(8.0, 1.6 * float(f.get("vision_step") or 5.0))
    j = 0
    for t in range(n):
        if not fr:
            unk[t] = 1
            continue
        while j + 1 < len(fr) and abs(fr[j + 1]["t"] - t) <= abs(fr[j]["t"] - t):
            j += 1
        v = fr[j]
        if abs(v["t"] - t) > gap:
            unk[t] = 1
            continue
        act[t] = float(v.get("action") or 0)
        screen[t] = 1 if v.get("view") in ("screen", "black") else 0
        child[t] = 1 if v.get("child") else 0
        gore[t] = 1 if v.get("gore") else 0
    # a child frame poisons its neighbours too (vision samples every few seconds)
    for t in [t for t in range(n) if child[t]]:
        for k in range(max(0, t - 4), min(n, t + 5)):
            child[k] = 1
    a = picker.aftermath_from(f)
    if a is not None:
        hits = [s.get("start", 0) for s in f.get("transcript") or [] if picker.AFTERMATH.search(s.get("text") or "")]
        first = int(min(hits)) if hits else a
        for t in range(max(0, first - 3), n):        # from the first CPR / "no pulse" line on: blurred
            gore[t] = 1
    rms = list(f.get("rms") or [])[:n] + [-90.0] * max(0, n - len(f.get("rms") or []))
    med = statistics.median(rms) if rms else -90.0
    peak = [1 if r > med + PEAK_DB and r > -45 else 0 for r in rms]
    return {"act": act, "screen": screen, "child": child, "gore": gore, "unk": unk, "peak": peak, "rms": rms, "n": n}


def _usable(S, t):
    return 0 <= t < S["n"] and not (S["child"][t] or S["unk"][t] or S["screen"][t])


def _split_usable(S, s, e):
    """Pieces of [s, e) without child / unknown / screen seconds (pieces under MIN_SEG dropped)."""
    out, cur = [], None
    for t in range(int(s), int(min(e, S["n"]))):
        if _usable(S, t):
            cur = t if cur is None else cur
        elif cur is not None:
            if t - cur >= MIN_SEG:
                out.append((float(cur), float(t)))
            cur = None
    end = int(min(e, S["n"]))
    if cur is not None and end - cur >= MIN_SEG:
        out.append((float(cur), float(end)))
    return out


def _cap_blur(S, s, e):
    """Cut a segment short once a blurred (gore) stretch inside it passes MAX_BLUR_RUN seconds."""
    run = 0
    for t in range(int(s), int(e)):
        run = run + 1 if S["gore"][t] else 0
        if run > MAX_BLUR_RUN:
            return s, float(t)
    return s, e


def beats(f, S):
    """Action beats of one file: runs of visible tense/peak action (or loud impacts on a live picture), padded."""
    hot = [_usable(S, t) and (S["act"][t] >= 2 or (S["act"][t] >= 1 and S["peak"][t])) for t in range(S["n"])]
    runs, cur, last = [], None, None
    for t, h in enumerate(hot):
        if h:
            if cur is None:
                cur = t
            elif t - last > GAP_MERGE:
                runs.append((cur, last + 1))
                cur = t
            last = t
    if cur is not None:
        runs.append((cur, last + 1))
    out = []
    for a, b in runs:
        a, b = max(0, a - 2), min(S["n"] - 1, b + 1)
        for s, e in _split_usable(S, a, b):
            s, e = _cap_blur(S, s, e)
            if e - s >= MIN_SEG:
                score = sum(S["act"][int(s):int(e)]) + 2 * sum(S["peak"][int(s):int(e)])
                out.append({"start": s, "end": e, "score": score})
    return out


def _words(f, s, e):
    return set(w for t in f.get("transcript") or [] if t["end"] >= s and t["start"] <= e
               for w in re.findall(r"[a-z']{3,}", (t.get("text") or "").lower()))


def _repeat(files, a, b):
    """Two segments from different cameras hearing the same words = the same moment from another angle."""
    if a["file"] == b["file"]:
        return False
    wa, wb = _words(files[a["file"]], a["start"], a["end"]), _words(files[b["file"]], b["start"], b["end"])
    if len(wa) < 6 or len(wb) < 6:
        return False
    return len(wa & wb) / min(len(wa), len(wb)) > 0.5


def _total(segs):
    return sum(s["end"] - s["start"] for s in segs)


def _llm_story(files, plan, lo, hi):
    """Ask the model for the beat-by-beat cut; code validates every second of it afterwards."""
    sc = plan.get("script") or {}
    facts = plan.get("agency_text") or plan.get("description") or ""
    j = picker.ask_llm(
        "You edit vertical Facebook Reels from agency-released police footage, the way the top bodycam pages do. " +
        picker.RULES.replace("never include the moment of a death, gore, or a lingering view of a body;",
                             "a death or a body may stay in only if it is short (it gets a full-frame blur);"),
        picker.describe(files) + "\n\nAGENCY STATEMENT (what happened):\n" + str(facts)[:2500] +
        f"\n\nThe Reel: {sc.get('moment') or plan.get('title') or plan.get('case_name')}\n" + picker.redo(plan) +
        f"""
Cut ONE {lo:.0f}-{hi:.0f}s story in segments, in the order events happened:
dash / approach (short, only if something is visible) -> the bodycam action (rams, chase, Taser, struggle, shots)
-> the arrest. Keep EVERY second of real action. Cut slates, text screens, maps, cruiser interiors with nothing
outside, walking, paperwork, and any second angle of a moment already in the cut. Segments 4-35s each.
Return JSON {{"segments":[{{"file":0,"start":18.0,"end":30.0,"beat":"spike strip, car hits barrier"}}]}}""")
    out = []
    for p in (j.get("segments") or []) if isinstance(j, dict) else []:
        c = picker.clamp(files, p, MIN_SEG, 40)
        if c:
            c["beat"] = str(p.get("beat") or "")[:80]
            out.append(c)
    return out


def _clean(files, segs, S_of, taken=()):
    """Every segment re-checked by code: child / unknown / screen seconds split out, long blurred runs capped,
    repeated angles and overlaps dropped, sibling Reels' seconds avoided (action cuts only)."""
    out = []
    for c in segs:
        S = S_of(c["file"])
        for s, e in _split_usable(S, c["start"], c["end"]):
            s, e = _cap_blur(S, s, e)
            piece = dict(c, start=s, end=e)
            if e - s < MIN_SEG:
                continue
            if any(o["file"] == c["file"] and o["start"] < e and o["end"] > s for o in out):
                continue
            if any(i == c["file"] and a < e and b > s for i, a, b in taken):
                continue
            if any(_repeat(files, o, piece) for o in out):
                continue
            out.append(piece)
    return out


def _fit(segs, hi, S_of):
    """Trim to `hi` seconds: drop the weakest segments first (never the first or last), then shave the ends."""
    def strength(c):
        S = S_of(c["file"])
        a, b = int(c["start"]), int(c["end"])
        return (sum(S["act"][a:b]) + 2 * sum(S["peak"][a:b])) / max(1, b - a)
    segs = list(segs)
    while _total(segs) > hi and len(segs) > 2:
        mid = min(segs[1:-1], key=strength)
        if _total(segs) - (mid["end"] - mid["start"]) < hi * 0.6:
            break
        segs.remove(mid)
    over = _total(segs) - hi
    if over > 0:                                   # shave the quietest ends
        for c in sorted(segs, key=strength):
            take = min(over, (c["end"] - c["start"]) - MIN_SEG)
            if take > 0:
                c["end"] -= take
                over -= take
            if over <= 0:
                break
    return segs


def blur_windows(segs, S_of):
    """Output-timeline [start, end] windows over every gore / aftermath second in the cut."""
    wins, t0 = [], 0.0
    for c in segs:
        S = S_of(c["file"])
        for t in range(int(c["start"]), int(c["end"])):
            if S["gore"][t]:
                x = t0 + (t - c["start"])
                wins.append([max(0.0, x - BLUR_PAD), x + 1 + BLUR_PAD])
        t0 += c["end"] - c["start"]
    wins.sort()
    merged = []
    for a, b in wins:
        if merged and a <= merged[-1][1] + 0.5:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    total = t0
    return [[round(a, 2), round(min(b, total + END_SECS), 2)] for a, b in merged]


def pick(files, plan, cache):
    """The cut for one Reel plan (story or action). None when the footage can't carry it."""
    sc = plan.get("script") or {}
    kind = "action" if (sc.get("cut") or {}).get("kind") == "action" or sc.get("cut_kind") == "action" else "story"
    key = f"reel2:{plan['id']}"
    if key in cache and not picker.fix_note(plan):
        return cache[key]
    lo, hi = STORY if kind == "story" else ACTION
    Smemo = {}

    def S_of(i):
        if i not in Smemo:
            Smemo[i] = seconds(files[i])
        return Smemo[i]

    # action cuts of the same case never share seconds with each other (story + action of one case may)
    taken = []
    if kind == "action":
        taken = [(i, s, e) for i, s, e in picker._taken(files, plan, cache)]
    segs = []
    if kind == "story":
        try:
            segs = _clean(files, _llm_story(files, plan, lo, hi), S_of)
        except Exception as e:
            print(f"reelcut: story pick by model failed ({str(e)[:120]}), cutting by code")
    if _total(segs) < lo * 0.75:                    # model missed or no model: cut by code from the action beats
        cands = []
        for i, f in enumerate(files):
            for b in beats(f, S_of(i)):
                cands.append({"file": i, **b})
        if kind == "action":                        # the reach cut leads with action people can see: blurred beats last
            for c in cands:
                c["score"] -= 4 * sum(S_of(c["file"])["gore"][int(c["start"]):int(c["end"])])
        cands.sort(key=lambda c: -c["score"])
        chosen = []
        for c in cands:
            if _total(chosen) >= hi:
                break
            if kind == "action":                    # tightest version of each beat: 12s around its peak
                S = S_of(c["file"])
                if c["end"] - c["start"] > 12:
                    pk = max(range(int(c["start"]), int(c["end"])), key=lambda t: S["act"][t] + 2 * S["peak"][t])
                    s = max(c["start"], pk - 4.0)
                    c = dict(c, start=s, end=min(c["end"], s + 12.0))
            chosen.append(c)
        segs = _clean(files, sorted(chosen, key=lambda c: (c["file"], c["start"])), S_of, taken)
        if kind == "story" and segs:                # lead in with the approach: up to 8s before the first beat
            f0 = segs[0]
            S = S_of(f0["file"])
            s = max(0.0, f0["start"] - 8)
            pre = _split_usable(S, s, f0["start"])
            if pre and pre[-1][1] >= f0["start"] - 0.5 and pre[-1][1] - pre[-1][0] >= 3:
                f0["start"] = pre[-1][0]
    segs = _fit(segs, hi, S_of)
    total = _total(segs)
    if total < lo * (0.75 if kind == "story" else 0.8):
        if kind == "story":                     # the action can't carry a long cut: make the short one instead
            print(f"reelcut: only {total:.0f}s of clean action, cutting the 20-30s action Reel instead")
            alt = dict(plan, script={**sc, "cut_kind": "action"})
            got = pick(files, alt, cache)
            if got:
                cache.pop(f"reel2:{plan['id']}", None)
                cache[key] = got
            return got
        return None
    out = {"cut": kind, "segments": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()
                                      if k in ("file", "start", "end", "beat")} for c in segs],
           "blur": blur_windows(segs, S_of), "total": round(total, 2), "parent": plan.get("parent_id")}
    cache[key] = out
    return out


# ---------------- what the viewer hears and reads (Writer) ----------------
def timeline(files, pk):
    """Per segment: output start, what's on screen / said (times relative to the OUTPUT), and loud seconds."""
    rows, t0, loud = [], 0.0, []
    for n, c in enumerate(pk["segments"]):
        f = files[c["file"]]
        S = seconds(f)
        frames = [f"{t0 + v['t'] - c['start']:.0f}s [{v['view']} a{v['action']}] {v['desc']}"
                  for v in f.get("vision") or [] if c["start"] <= v["t"] < c["end"] and not v.get("child")]
        said = [f"{t0 + max(0, t['start'] - c['start']):.0f}s \"{t['text']}\"" for t in f.get("transcript") or []
                if t["end"] >= c["start"] and t["start"] <= c["end"]]
        for t in range(int(c["start"]), int(c["end"])):
            if S["peak"][t]:
                loud.append(round(t0 + t - c["start"], 1))
        rows.append({"segment": n + 1, "from": round(t0, 1), "to": round(t0 + c["end"] - c["start"], 1),
                     "beat": c.get("beat") or "", "frames": frames[:20], "said": said[:20]})
        t0 += c["end"] - c["start"]
    return rows, loud


def _facts(plan):
    cf = plan.get("case_facts") or {}
    lead = plan.get("lead") or {}
    return {"agency": lead.get("agency_name") or plan.get("source_credit"), "state": lead.get("state"),
            "date": lead.get("incident_date"), "agency_statement": (lead.get("summary") or plan.get("agency_text") or "")[:2500],
            "lead_title": lead.get("title"), "case": plan.get("case_name"),
            "case_file": {k: cf.get(k) for k in ("suspect_name", "suspect_age", "say_name", "why", "charges", "status",
                                                 "outcome", "sentence") if cf.get(k) not in (None, "", [])}}


def write(job, log=print):
    """Captions, narrator lines with timings, title pill, end card and the Facebook caption, from the agency text."""
    from writer import RULES, _cam, _ask
    from agents import casefacts
    pk, plan, sc = job.pick, job.plan, job.sc
    total = pk["total"]
    rows, loud = timeline(job.files, pk)
    story = pk["cut"] == "story"
    n_vo = "6-12" if story else "1-2"
    j = _ask("You write the captions and the narrator script for a vertical Facebook Reel of " + _cam(sc) + ", AFTER "
             "the cut is locked. A narrator (calm documentary voice, EWU / Code Blue Cam style) reads short lines while "
             "the camera audio drops low underneath. " + RULES +
             " EVERY narrator line and caption must be stated in the AGENCY STATEMENT or CASE FILE, or plainly visible "
             "in the frames at that moment. Nothing invented: no motives, injuries, charges, numbers or names that the "
             "sources don't give.",
             "FACTS:\n" + json.dumps(_facts(plan)) + "\n\n" + casefacts.narration_rules(plan.get("case_facts")) +
             f"\n\nTHE CUT ({total:.0f}s, then a {END_SECS:.0f}s 'How it ended' card). Segments with what's on screen "
             "and what's said, times are seconds from the start of the Reel:\n" + json.dumps(rows) +
             f"\n\nLOUD MOMENTS (gunshots, impacts, crashes, shouting) — never put a narrator line over these: {loud[:60]}"
             + (f"\nBLURRED (death / body, full-frame blur): {pk['blur']} — say nothing graphic about these seconds"
                if pk.get("blur") else "") +
             f"""

Write:
- title: the place as "CITY, STATE" in capitals (e.g. "KETTERING, OH"), from FACTS only; "" if FACTS don't give it
- captions: short on-screen lines that follow the beats, 2-6 words per line, max 2 lines (use \\n), each with
  "t":[from,to] in Reel seconds. The FIRST caption is the hook: "t":[0,{HOOK_SECS:.0f}], "big":true, 2-4 words, the
  biggest stakes ("SHOTS FIRED\\nAT TROOPERS"). Set "yellow":true on the 1-3 biggest moments. Cover the Reel end to end.
- vo: {n_vo} narrator lines, each "at" (Reel seconds) + "text" (one or two short sentences, max 22 words). The first
  line starts at 0.3 and says the date or place and why police were there. {"Lines follow the story beat by beat, "
  "each placed where its moment is on screen, with breathing room between lines (the camera audio carries the "
  "action)." if story else "One setup line at the start; at most one more."} Leave gaps over the LOUD MOMENTS.
  The last line may sit at {total:.1f} (on the end card) and says how it ended, from FACTS only.
- ended: the end-card text, max 2 short lines (\\n), how it ended from FACTS only ("" if FACTS don't say)
- caption: Facebook caption line 1: PLACE. STAKES in under 12 words (e.g. 'Kettering, Ohio. A stolen Suburban rams
  two cruisers at a gas pump.'), no question
- hashtags: 3-4 tags
Return JSON {{"title":"","captions":[{{"t":[0,{HOOK_SECS:.0f}],"text":"","big":true}}],"vo":[{{"at":0.3,"text":""}}],
"ended":"","caption":"","hashtags":[""]}}""")
    w = _sanitize(j if isinstance(j, dict) else {}, total, story)
    w = _factcheck(w, plan, log)
    return w


def _sanitize(j, total, story):
    caps = []
    for c in j.get("captions") or []:
        if not isinstance(c, dict) or not str(c.get("text") or "").strip():
            continue
        try:
            a, b = float(c["t"][0]), float(c["t"][1])
        except Exception:
            continue
        a, b = max(0.0, min(a, total)), max(0.0, min(b, total))
        if b - a < 1.0:
            continue
        txt = "\n".join(l.strip() for l in str(c["text"]).replace("\\n", "\n").split("\n")[:2] if l.strip())
        caps.append({"t": [round(a, 2), round(b, 2)], "text": txt[:60], "big": bool(c.get("big")),
                     "yellow": bool(c.get("yellow"))})
    caps.sort(key=lambda c: c["t"][0])
    for x, y in zip(caps, caps[1:]):               # one caption on screen at a time
        if x["t"][1] > y["t"][0]:
            x["t"][1] = y["t"][0]
    caps = [c for c in caps if c["t"][1] - c["t"][0] >= 1.0]
    for c in caps[1:]:
        c["big"] = False
    vo = []
    for l in j.get("vo") or []:
        if isinstance(l, dict) and str(l.get("text") or "").strip():
            try:
                at = max(0.0, min(float(l.get("at") or 0), total + 0.2))
            except Exception:
                continue
            vo.append({"at": round(at, 2), "text": str(l["text"]).strip()[:200]})
    vo.sort(key=lambda l: l["at"])
    vo = vo[:12 if story else 2]
    title = str(j.get("title") or "").strip().upper()[:28]
    tags = [t if str(t).startswith("#") else "#" + str(t) for t in (j.get("hashtags") or [])][:4]
    return {"title": title, "captions": caps, "vo": vo,
            "ended": "\n".join(str(j.get("ended") or "").replace("\\n", "\n").split("\n")[:2]).strip()[:90],
            "caption": str(j.get("caption") or "").strip()[:160], "hashtags": [t.replace(" ", "") for t in tags]}


def _factcheck(w, plan, log):
    """agents/factcheck.ai_check over every caption, narrator line, the end card and the FB caption."""
    from agents import factcheck
    lead = plan.get("lead") or {"summary": plan.get("agency_text"), "agency_name": plan.get("source_credit")}
    units = [(f"captions[{i}]", c["text"]) for i, c in enumerate(w["captions"])] + \
            [(f"vo[{i}]", l["text"]) for i, l in enumerate(w["vo"])] + \
            [(k, w[k]) for k in ("title", "ended", "caption") if w.get(k)]
    try:
        j = factcheck.ai_check(units, lead, plan.get("case_facts"), factcheck.camera_kind(lead))
    except Exception as e:
        log(f"reel fact check skipped: {str(e)[:150]}")
        w["factcheck"] = {"ai": f"failed: {str(e)[:120]}", "fixed": []}
        return w
    fixed = []
    for pr in j.get("problems") or []:
        if not isinstance(pr, dict):
            continue
        m = re.match(r"(captions|vo)\[(\d+)\]$|(title|ended|caption)$", str(pr.get("path") or "").strip())
        fix = pr.get("fix") if isinstance(pr.get("fix"), str) else None
        if not m or fix is None:
            continue
        if m.group(1):
            lst, i = w[m.group(1)], int(m.group(2))
            if i < len(lst):
                fixed.append(f"{m.group(0)}: '{lst[i]['text'][:60]}' -> '{fix[:60]}'")
                lst[i]["text"] = fix.strip()
        else:
            fixed.append(f"{m.group(3)}: '{str(w[m.group(3)])[:60]}' -> '{fix[:60]}'")
            w[m.group(3)] = fix.strip()
    w["captions"] = [c for c in w["captions"] if c["text"]]
    w["vo"] = [l for l in w["vo"] if l["text"]]
    w["factcheck"] = {"ai": "ok", "fixed": fixed}
    for x in fixed:
        log(f"reel fact check fixed: {x[:160]}")
    return w


def place_vo(lines, wav_durs, loud, total):
    """Final narrator timings: a line never covers a loud moment or the previous line; it slides later (or earlier)
    into the nearest quiet gap, and is dropped if none fits. Returns [(index, at)]."""
    out, busy_until = [], 0.0
    loud = sorted(loud)

    def clear(a, d):
        return all(not (a - 0.3 <= p <= a + d + 0.3) for p in loud)

    for i, (l, d) in enumerate(zip(lines, wav_durs)):
        want = max(l["at"], busy_until + 0.25)
        limit = total + END_SECS - d - 0.1           # must finish before the video does
        at = None
        for shift in [x * 0.25 for x in range(0, 33)]:          # up to 8s later
            a = want + shift
            if a > limit:
                break
            if clear(a, d):
                at = a
                break
        if at is None and want - busy_until > 0.6:              # or a little earlier, after the previous line
            for shift in [x * 0.25 for x in range(1, 13)]:
                a = want - shift
                if a < busy_until + 0.25:
                    break
                if clear(a, d):
                    at = a
                    break
        if at is None:
            continue
        out.append((i, round(at, 2)))
        busy_until = at + d
    return out


# ---------------- the build (port of tools/manual_reels/build_reel.py + add_vo.py) ----------------
def _tf(work, name, text):
    p = Path(work) / f"_{name}.txt"
    p.write_text(text)
    return str(p).replace(":", r"\:")


def build(job, out):
    pk, sc, files, work = job.pick, job.sc, job.files, job.work
    F, R = _font("black"), _font("bold")
    segs = pk["segments"]
    total = pk["total"]
    # one seeked input per segment: a single decoded input feeding several trims makes ffmpeg queue every frame
    # between segments (OOM-killed at 2560x1440 on an 8 GB box, Nov 18)
    args = []
    for c in segs:
        args += ["-ss", f"{c['start']:.3f}", "-t", f"{c['end'] - c['start']:.3f}",
                 "-i", str(job.folder / files[c["file"]]["path"])]
    used = segs
    fc = []
    for k, c in enumerate(segs):
        f = files[c["file"]]
        n = k
        vert = f["h"] > f["w"]
        # landscape: a tall centre crop fills more of the phone; vertical: as is
        fg = "scale=1080:-2" if vert else "crop='min(iw,ih*0.83)':ih,scale=1080:-2"
        fc.append(f"[{n}:v]setpts=PTS-STARTPTS,fps=30,split[s{k}a][s{k}b]")
        fc.append(f"[s{k}a]scale=270:480:force_original_aspect_ratio=increase,crop=270:480,boxblur=8:2,"
                  f"eq=brightness=-0.25,scale=1080:1920,setsar=1[bg{k}]")
        fc.append(f"[s{k}b]{fg},eq=contrast=1.08,scale='min(1080,iw)':'min(1500,ih)':force_original_aspect_ratio=decrease,"
                  f"setsar=1[fg{k}]")
        fc.append(f"[bg{k}][fg{k}]overlay=(W-w)/2:(H-h)/2-60,format=yuv420p,setsar=1[v{k}]")
        if f.get("audio"):
            fc.append(f"[{n}:a]asetpts=PTS-STARTPTS,aresample=48000,"
                      f"aformat=sample_fmts=fltp:channel_layouts=stereo[a{k}]")
        else:
            fc.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{c['end'] - c['start']}[a{k}]")
    fc.append("".join(f"[v{k}][a{k}]" for k in range(len(segs))) + f"concat=n={len(segs)}:v=1:a=1[cv][ca]")
    # full-frame blur windows (death / body): heavy enough that nothing identifiable survives
    blur = "".join(f",boxblur=40:5:enable='between(t,{a},{b})'" for a, b in pk.get("blur") or [])
    fc.append(f"[cv]tpad=stop_mode=clone:stop_duration={END_SECS}{blur}[cvb]")
    title = sc.get("title_pill") or ""
    dt = [f"drawtext=fontfile={R}:textfile={_tf(work, 'br', 'TEN-FOUR TAPES')}:fontsize=30:fontcolor=white:x=40:y=60"]
    if title:
        dt.append(f"drawtext=fontfile={F}:textfile={_tf(work, 'ti', title)}:fontsize=58:fontcolor=black:box=1:"
                  f"boxcolor={YELLOW}:boxborderw=22:x=(w-tw)/2:y=400:enable='lt(t,{total})'")
    for i, c in enumerate(sc.get("captions") or []):
        big = c.get("big")
        col = YELLOW if c.get("yellow") or big else "white"
        dt.append(f"drawtext=fontfile={F}:textfile={_tf(work, 'c%d' % i, c['text'])}:fontsize={96 if big else 64}:"
                  f"fontcolor={col}:borderw=6:bordercolor=black:line_spacing=14:x=(w-tw)/2:y=1440:"
                  f"enable='between(t,{c['t'][0]},{c['t'][1]})'")
    if pk.get("blur"):
        cond = "+".join(f"between(t,{a},{b})" for a, b in pk["blur"])
        dt.append(f"drawtext=fontfile={R}:textfile={_tf(work, 'bl', 'Blurred out of respect')}:fontsize=36:"
                  f"fontcolor=white:box=1:boxcolor=black@0.6:boxborderw=12:x=(w-tw)/2:y=520:enable='{cond}'")
    e = f"gte(t,{total})"
    ended = sc.get("ended_text") or ""
    dt += [f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.72:t=fill:enable='{e}'",
           f"drawtext=fontfile={F}:textfile={_tf(work, 'e1', 'HOW IT ENDED' if ended else 'TEN-FOUR TAPES')}:fontsize=40:"
           f"fontcolor=black:box=1:boxcolor={YELLOW}:boxborderw=12:x=(w-tw)/2:y=800:enable='{e}'"]
    if ended:
        dt.append(f"drawtext=fontfile={F}:textfile={_tf(work, 'e2', ended)}:fontsize=56:fontcolor=white:line_spacing=12:"
                  f"x=(w-tw)/2:y=890:enable='{e}'")
    dt += [f"drawtext=fontfile={F}:textfile={_tf(work, 'e3', 'FOLLOW FOR MORE CASES')}:fontsize=64:fontcolor=white:"
           f"x=(w-tw)/2:y=1150:enable='gte(t,{total + 1.2})'",
           f"drawtext=fontfile={R}:textfile={_tf(work, 'cr', (job.credit or '').split(' (')[0][:60])}:fontsize=28:"
           f"fontcolor=white@0.85:x=(w-tw)/2:y=1830"]
    fc.append("[cvb]" + ",".join(dt) + ",format=yuv420p[ov]")

    # narrator: Kokoro am_adam, camera ducks 75% under each line, lines kept off the loud moments
    lines = sc.get("vo_lines") or []
    wavs = []
    for i, l in enumerate(lines):
        p = Path(work) / f"vo{i}.wav"
        media.tts(l["text"], p, speed=1.05)
        wavs.append((str(p), media.wav_dur(p)))
    _, loud = timeline(files, pk)
    placed = place_vo(lines, [d for _, d in wavs], loud, total)
    kept = dict(placed)
    for i, l in enumerate(lines):
        l.pop("dropped", None)
        if i in kept:
            l["at"] = kept[i]
        else:
            l["dropped"] = True                    # no quiet gap: never talk over a gunshot
    vo_in = [(wavs[i][0], at, wavs[i][1]) for i, at in placed]
    base = len(used)
    for p, _, _ in vo_in:
        args += ["-i", p]
    fc.append(f"[ca]apad=pad_dur={END_SECS},loudnorm=I=-16:TP=-1.5:LRA=11[cam0]")
    if vo_in:
        duck = "*".join(f"(1-{1 - DUCK}*between(t,{at - 0.15:.2f},{at + d + 0.25:.2f}))" for _, at, d in vo_in)
        fc.append(f"[cam0]volume='{duck}':eval=frame[cam]")
        for k, (p, at, d) in enumerate(vo_in):
            ms = int(at * 1000)
            fc.append(f"[{base + k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                      f"adelay={ms}|{ms},volume=1.6[n{k}]")
        fc.append("[cam]" + "".join(f"[n{k}]" for k in range(len(vo_in))) +
                  f"amix=inputs={len(vo_in) + 1}:normalize=0:duration=first,alimiter=limit=0.92[oa]")
    else:
        fc.append("[cam0]alimiter=limit=0.92[oa]")
    script = Path(work) / "reel_fc.txt"
    script.write_text(";".join(fc))
    media.ff(*args, "-filter_complex_script", str(script), "-map", "[ov]", "-map", "[oa]",
             "-t", round(total + END_SECS, 2), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", "-r", "30", *media.ENC_A, "-movflags", "+faststart", str(out))
    return out


# ---------------- glue for mac/render.py ----------------
AGENCY_TAIL = re.compile(r"\s+(police department|police dept\.?|division of police|police|county sheriff'?s office|"
                         r"sheriff'?s office|county sheriff|sheriff|pd|so)\b.*$", re.I)


def place_pill(job):
    """'KETTERING, OH' from the lead's agency + state when the Writer gave none (city/county agencies only)."""
    lead = job.plan.get("lead") or {}
    ag, st = (lead.get("agency_name") or "").strip(), (lead.get("state") or "").strip()
    if not ag or not st or re.search(r"\b(state|highway) patrol|\bu\.s\.|\bus\b|\bcustoms\b|\bfederal\b|coast guard", ag, re.I):
        return ""
    city = AGENCY_TAIL.sub("", ag).strip()
    if not city or city == ag:
        return ""
    if re.search(r"county", ag, re.I) and "county" not in city.lower():
        city += " County"
    return f"{city}, {st}".upper()[:28]


def apply(job, w):
    """Put the Writer's words on the job's script (what build() and the runner read)."""
    sc = job.sc
    sc["title_pill"] = w.get("title") or place_pill(job)
    if w.get("captions"):
        sc["captions"] = w["captions"]
        sc["hook_text"] = sc["on_screen_text"] = w["captions"][0]["text"].replace("\n", " ")
    sc["vo_lines"] = w.get("vo") or []
    sc["ended_text"] = w.get("ended") or ""
    for k in ("caption", "hashtags", "factcheck"):
        if w.get(k):
            sc[k] = w[k]
    sc.pop("question", None)                        # captions carry no question (engagement-bait flag)


def fallback_words(job):
    """No AI: the Maker's drafts, placed by code (hook over the first 4s, intro line at 0.3, outcome on the card)."""
    sc, total = job.sc, job.pick["total"]
    hook = (sc.get("hook_text") or job.plan.get("case_name") or "").upper()
    w = {"captions": [{"t": [0, min(HOOK_SECS, total)], "text": "\n".join(_wrap(hook, 14)[:2]), "big": True}] if hook else [],
         "vo": [x for x in ([{"at": 0.3, "text": sc.get("intro_vo")}] if sc.get("intro_vo") else []) +
                ([{"at": total, "text": sc.get("outcome_vo")}] if sc.get("outcome_vo") else [])],
         "ended": "\n".join(_wrap(sc.get("outcome_vo") or "", 26)[:2])}
    return w


def _wrap(text, width):
    out, cur = [], ""
    for wd in str(text).split():
        if len(cur) + len(wd) + 1 > width and cur:
            out.append(cur)
            cur = wd
        else:
            cur = (cur + " " + wd).strip()
    if cur:
        out.append(cur)
    return out
