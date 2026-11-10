"""Footage analysis + clip picking. Reads what's actually in the footage (Whisper transcript + loudness +
a vision pass over sampled frames) and decides which seconds go into each episode, Short and Reel. Uses the
Groq LLM when available and a loudness/vision fallback otherwise, so a render never stalls on the AI.
Every pick is checked against what is ON SCREEN: a window that only shows a cruiser's interior, a dashboard
or a black screen is swapped out even if the audio (sirens, shouting) is loud."""
import os
import statistics
import zipfile
from pathlib import Path

import media

ANALYSIS = ".tft_analysis.json"
PICKS = ".tft_picks_v2.json"


# ---------------- analysis (cached per footage folder) ----------------
def unpack_zips(folder):
    for z in Path(folder).rglob("*.zip"):
        dest = z.with_suffix("")
        if dest.exists():
            z.unlink(missing_ok=True)
            continue
        try:
            with zipfile.ZipFile(z) as zf:
                zf.extractall(dest)
            z.unlink()                      # don't keep two copies of a multi-GB package
        except Exception:
            pass


def analyse(folder, groq_key, log=print):
    folder = Path(folder)
    unpack_zips(folder)
    cache = media.load_json(folder / ANALYSIS, {"files": []})
    known = {f["path"]: f for f in cache["files"]}
    vids = sorted(p for p in folder.rglob("*") if p.suffix.lower() in media.VIDEO_EXT and not p.name.startswith("."))
    files = []
    for p in vids:
        key = str(p.relative_to(folder))
        if key in known and known[key].get("size") == p.stat().st_size:
            f = known[key]
            if "visible" not in f:
                f["visible"] = media.visible(p, f["duration"])
            files.append(f)
            continue
        info = media.probe(p)
        if not info["video"] or info["duration"] < 3:
            continue
        log(f"analysing {key} ({info['duration']:.0f}s)")
        info.update(path=key, size=p.stat().st_size,
                    rms=media.loudness(p, info["duration"]) if info["audio"] else [-90.0] * (int(info["duration"]) + 1),
                    transcript=media.transcribe(p, folder / ".tft_work", groq_key) if info["audio"] else [],
                    visible=media.visible(p, info["duration"]))
        files.append(info)
        media.save_json(folder / ANALYSIS, {"files": files + [f for f in cache["files"] if f["path"] not in {x["path"] for x in files}]})
    media.save_json(folder / ANALYSIS, {"files": files})
    if not files:
        raise RuntimeError(f"No usable video files in {folder}")
    # Black-screen files (dispatch audio, blank exports) can't carry a bodycam segment
    seen = [f for f in files if f.get("visible", 1) >= 0.5]
    if seen:
        dropped = len(files) - len(seen)
        if dropped:
            log(f"skipping {dropped} file(s) with no picture")
        files = seen
    if any(not f.get("vision_ok") for f in files):
        look(folder, files, log)
        media.save_json(folder / ANALYSIS, {"files": files + [f for f in media.load_json(folder / ANALYSIS, {"files": []})["files"]
                                                         if f["path"] not in {x["path"] for x in files}]})
    return files


# ---------------- vision: what is actually on screen ----------------
SHEET = 9                                            # frames per vision call (3x3 grid)
MAX_SHEETS = int(os.environ.get("TFT_VISION_SHEETS", "70"))   # per case, keeps us inside the free tier
LOOK_PROMPT = """This grid shows {n} numbered frames (red labels), in time order, from police body-camera / dash-camera footage.
For EACH numbered frame judge ONLY what is visible in the picture (there is no audio):
- view: "outside" (officer on foot outdoors), "road_ahead" (dash/windshield view of the road), "inside_car" (cruiser
  interior: dashboard, steering wheel, seats, laptop, officer driving with nothing happening outside), "indoor", "black"
  (blank, dark, covered or too blurry to see), "screen" (title card, document, map)
- action 0-3: 0 nothing happening / empty scene; 1 calm talking, walking, routine driving; 2 tense: confrontation,
  weapon drawn, someone fleeing, pursuit with the suspect vehicle visible ahead; 3 peak: struggle, tackle, arrest
  on the ground, crash, shots fired, foot chase with the suspect in view
- child: true if a child appears; gore: true if blood, a badly injured person or a body is visible
- desc: what is visible, max 10 words
Return {{"frames":[{{"n":1,"view":"outside","action":2,"child":false,"gore":false,"desc":"officer points gun at driver"}}]}}"""


def look(folder, files, log=print):
    """Caption sampled frames of every file (cached in the analysis). Fails soft: no vision = old behaviour."""
    from agents.lib import llm
    total = sum(f["duration"] for f in files)
    step = max(5.0, total / (MAX_SHEETS * SHEET))
    fails = 0
    for f in files:
        if f.get("vision_ok") and f.get("vision_step", 99) <= step + 0.01:
            continue
        times = [round(t, 1) for t in frange(step / 2, f["duration"] - 0.5, step)] or [f["duration"] / 2]
        got = {v["t"]: v for v in f.get("vision") or []}
        ok = True
        for k in range(0, len(times), SHEET):
            chunk = times[k:k + SHEET]
            if all(t in got for t in chunk):
                continue
            if fails >= 3:                      # vision is down this run — stop burning time, retry next run
                ok = False
                break
            try:
                img = media.contact_sheet(Path(folder) / f["path"], chunk)
                j = llm.see(LOOK_PROMPT.format(n=len(chunk)), img)
                for fr in j.get("frames", []):
                    n = int(fr.get("n", 0)) - 1
                    if 0 <= n < len(chunk):
                        got[chunk[n]] = {"t": chunk[n], "view": str(fr.get("view", ""))[:12],
                                         "action": max(0, min(3, int(fr.get("action") or 0))),
                                         "child": bool(fr.get("child")), "gore": bool(fr.get("gore")),
                                         "desc": str(fr.get("desc", ""))[:80]}
                fails = 0
            except Exception as e:
                fails += 1
                ok = False
                log(f"vision: {str(e)[:160]}")
        f["vision"] = sorted(got.values(), key=lambda v: v["t"])
        f["vision_step"] = step
        f["vision_ok"] = ok and len(f["vision"]) >= len(times) * 0.8
        log(f"vision {f['path']}: {len(f['vision'])}/{len(times)} frames read")
    return files


def frange(a, b, step):
    t = a
    while t < b:
        yield t
        t += step


_VA = {}

def vis(f):
    """Per-second arrays (action, dull, bad) from the vision frames, or None when there is no vision for this file."""
    key = (f["path"], len(f.get("vision") or []))
    if key in _VA:
        return _VA[key]
    fr = f.get("vision") or []
    if len(fr) < 2:
        _VA[key] = None
        return None
    n = int(f["duration"]) + 1
    act, dull, bad = [0.0] * n, [0.0] * n, [0.0] * n
    j = 0
    for t in range(n):
        while j + 1 < len(fr) and abs(fr[j + 1]["t"] - t) <= abs(fr[j]["t"] - t):
            j += 1
        v = fr[j]
        act[t] = v["action"]
        dull[t] = 1.0 if v["action"] < 2 and (v["view"] in ("inside_car", "black", "screen") or v["action"] == 0) else 0.0
        bad[t] = 1.0 if v["child"] or v["gore"] else 0.0
    out = {"act": act, "dull": dull, "bad": bad}
    _VA[key] = out
    return out


def on_screen(f, s, e):
    """(mean action, dull share, any child/gore) for seconds s..e, or None without vision."""
    v = vis(f)
    if not v:
        return None
    a, b = max(0, int(s)), max(int(s) + 1, min(len(v["act"]), int(e)))
    n = b - a
    if n <= 0:
        return None
    return (sum(v["act"][a:b]) / n, sum(v["dull"][a:b]) / n, any(v["bad"][a:b]))


def looks_bad(f, s, e, min_action=1.0, max_dull=0.5):
    q = on_screen(f, s, e)
    return bool(q) and (q[0] < min_action or q[1] > max_dull or q[2])


# ---------------- helpers ----------------
def window_scores(rms, length):
    """Mean level of every window of `length` seconds."""
    n = len(rms)
    if n <= length:
        return [(0, statistics.fmean(rms) if rms else -90)]
    pref = [0.0]
    for v in rms:
        pref.append(pref[-1] + v)
    return [(s, (pref[s + length] - pref[s]) / length) for s in range(0, n - length)]


def scored_windows(f, length):
    """Loudness plus what's on screen: visible action scores up, cruiser-interior / black stretches score down,
    anything showing a child or gore is excluded."""
    sc = window_scores(f["rms"], length)
    if not vis(f):
        return sc
    out = []
    for s, v in sc:
        a, dull, bad = on_screen(f, s, s + length)
        if not bad:
            out.append((s, v + 6 * a - 15 * dull))
    return out          # may be empty: every window shows a child/gore — better no render than an unsafe one


def action_start(rms, s, e, f=None):
    """Move a clip start to where the action begins: the first visibly tense frame if vision has it,
    otherwise the biggest jump in sound inside the clip's first half."""
    v = vis(f) if f else None
    if v:
        for t in range(int(s), int(s + (e - s) / 2)):
            if t < len(v["act"]) and v["act"][t] >= 2:
                return max(0, t - 1)
            if t < len(v["act"]) and v["act"][t] >= 1 and not v["dull"][t]:
                break                            # already opens on something worth seeing
    best, bt = 0, s
    for t in range(int(s) + 1, int(s + (e - s) / 2)):
        if t >= len(rms):
            break
        base = statistics.fmean(rms[max(0, t - 4):t]) if t > 0 else -90
        jump = rms[t] - base
        if jump > best:
            best, bt = jump, t
    return max(0, bt - 1) if best > 6 else s


def loud_peaks(f, k=10):
    sc = window_scores(f["rms"], 5)
    sc.sort(key=lambda x: -x[1])
    out = []
    for s, v in sc:
        if all(abs(s - o) >= 20 for o, _ in out):
            out.append((s, v))
        if len(out) >= k:
            break
    return sorted(out)


def best_windows(files, length, count, used=None):
    used = list(used or [])
    cands = []
    for i, f in enumerate(files):
        L = min(length, int(f["duration"]) - 1)
        if L < 8:
            continue
        for s, v in scored_windows(f, L):
            cands.append((v, i, s, s + L))
    cands.sort(reverse=True)
    picks = []
    for v, i, s, e in cands:
        if all(not (i == j and s < e2 and e > s2) for j, s2, e2 in used + [(p["file"], p["start"], p["end"]) for p in picks]):
            picks.append({"file": i, "start": float(s), "end": float(e)})
        if len(picks) >= count:
            break
    return picks


def describe(files, max_chars=14000):
    lines = []
    for i, f in enumerate(files):
        lines.append(f"FILE {i}: {f['path']} — {f['duration']:.0f}s, {'vertical' if f['h'] > f['w'] else 'horizontal'}")
        peaks = ", ".join(f"{s}s({v:.0f}dB)" for s, v in loud_peaks(f))
        lines.append(f"  loudest moments: {peaks or 'no audio'}")
    head = "\n".join(lines)
    tl = []
    for i, f in enumerate(files):
        for s in f["transcript"]:
            tl.append(f"F{i} {s['start']:.0f}-{s['end']:.0f}s: {s['text']}")
    body = "\n".join(tl)
    if len(body) > max_chars:  # keep an even sample across the whole footage
        step = len(tl) / (max_chars / 90)
        body = "\n".join(tl[int(k * step)] for k in range(int(len(tl) / step)))
    seen = []
    for i, f in enumerate(files):
        for v in f.get("vision") or []:
            flag = (" CHILD" if v["child"] else "") + (" GORE" if v["gore"] else "")
            seen.append(f"F{i} {v['t']:.0f}s [{v['view']} a{v['action']}{flag}] {v['desc']}")
    screen = "\n".join(seen)
    if len(screen) > 9000:
        step = len(seen) / (9000 / 70)
        screen = "\n".join(seen[int(k * step)] for k in range(int(len(seen) / step)))
    out = head + "\n\nTRANSCRIPT (speaker words from the bodycam audio):\n" + (body or "(no speech found)")
    if screen:
        out += ("\n\nWHAT'S ON SCREEN (sampled frames; a0 = nothing happening ... a3 = peak action; inside_car = cruiser "
                "interior/dashboard; black = no picture):\n" + screen)
    return out


def clamp(files, p, min_len, max_len):
    try:
        i = int(p["file"])
        f = files[i]
        s, e = float(p["start"]), float(p["end"])
    except Exception:
        return None
    s = max(0.0, min(s, f["duration"] - 2))
    e = max(s + min_len, min(e, s + max_len, f["duration"]))
    if e - s < min(min_len, f["duration"] - 1):
        return None
    out = {"file": i, "start": round(s, 1), "end": round(e, 1)}
    if p.get("label"):
        out["label"] = str(p["label"])[:40]
    return out


def ask_llm(system, user):
    from agents.lib import llm
    return llm.ask(system, user, max_tokens=2500, temperature=0.3)


RULES = """Hard rules for every cut: never include the moment of a death, gore, or a lingering view of a body;
skip any stretch where a child is on camera; skip long dead air (walking, paperwork, silence).
Prefer real action: shouting, commands, foot chases, struggles, arrests, crashes, shots fired (but not a death on screen).
The action must be VISIBLE: use WHAT'S ON SCREEN. Sirens or shouting heard while the picture only shows a cruiser's
interior, dashboard or a black screen is NOT action — never pick those stretches. Never pick frames marked CHILD or GORE."""


# ---------------- picks ----------------
def fix_note(plan):
    """Bobby's reason when he asked for a re-cut (dashboard 'Re-cut' button), else ''."""
    n = plan.get("publish_note") or ""
    return n.split(":", 1)[1].strip() if n.startswith("Re-cut") else ""


def redo(plan):
    n = fix_note(plan)
    return f"\nBobby REJECTED the previous cut of this video: \"{n}\". Pick different moments that fix that.\n" if n else ""


def pick_reel(files, plan, cache):
    key = f"reel:{plan['id']}"
    if key in cache:
        return cache[key]
    sc = plan.get("script") or {}
    pick = None
    try:
        j = ask_llm("You cut 25-30 second Facebook Reels from police bodycam footage. " + RULES,
                    describe(files) + f"\n\nThe Reel is for this moment: {sc.get('moment') or plan.get('title')}\n"
                    f"Hook text: {sc.get('hook_text', '')}\n" + redo(plan) +
                    "Pick ONE continuous 25-30s window where visible action starts within the first 2 seconds. "
                    'Return JSON {"file":0,"start":12.0,"end":40.0,"why":"..."}')
        pick = clamp(files, j, 24, 30)
    except Exception:
        pass
    if pick and looks_bad(files[pick["file"]], pick["start"], pick["end"], min_action=1.5, max_dull=0.35):
        pick = None                             # the AI chose a stretch with nothing to see — use the vision ranking
    if not pick:
        long_enough = [f for f in files if f["duration"] >= 30] or files
        pick = best_windows(long_enough, 27, 1)[0]
        pick["file"] = files.index(long_enough[pick["file"]])
    f = files[pick["file"]]
    s = action_start(f["rms"], pick["start"], pick["end"], f)
    pick.update(start=float(s), end=float(min(f["duration"], s + (pick["end"] - pick["start"]))))
    cache[key] = pick
    return pick


def pick_shorts(files, plan, cache):
    """All three parts of a case are picked together so Part 1/2/3 run in story order without overlap."""
    key = f"shorts:{plan.get('parent_id') or plan['case_name']}"
    if key in cache:
        return cache[key]
    parts = []
    try:
        j = ask_llm("You cut 3-part YouTube Shorts series from police bodycam footage. " + RULES,
                    describe(files) + f"\n\nCase: {plan.get('case_name')}\n" + redo(plan) +
                    "Pick 3 non-overlapping windows of 35-55 seconds each, in story order (Part 1 sets up and ends on a "
                    "cliffhanger, Part 2 escalates, Part 3 has the climax/resolution). Every window must show action "
                    'on screen, not just sound. Return JSON {"parts":[{"part":1,"file":0,"start":0,"end":45}, ...]}')
        for p in j.get("parts", [])[:3]:
            c = clamp(files, p, 30, 55)
            if c and not looks_bad(files[c["file"]], c["start"], c["end"]):
                c["part"] = int(p.get("part", len(parts) + 1))
                parts.append(c)
    except Exception:
        pass
    if len(parts) < 3:                          # top up only the missing parts from the vision/loudness ranking
        extra = best_windows(files, 45, 3 - len(parts), used=[(p["file"], p["start"], p["end"]) for p in parts])
        parts += extra
        parts.sort(key=lambda p: (p["file"], p["start"]))
        for n, p in enumerate(parts, 1):
            p["part"] = n
    cache[key] = parts
    return parts


def recut_short(files, plan, cache, parts):
    """Re-pick one rejected Part, keeping the other parts (they may already be posted)."""
    want = int(plan.get("part") or 1)
    others = [p for p in parts if p["part"] != want]
    old = next((p for p in parts if p["part"] == want), None)
    used = [(p["file"], p["start"], p["end"]) for p in parts]   # never reuse the rejected window either
    new = None
    try:
        j = ask_llm("You cut one part of a 3-part YouTube Shorts series from police bodycam footage. " + RULES,
                    describe(files) + f"\n\nCase: {plan.get('case_name')}. Re-cut Part {want}.{redo(plan)}"
                    f"Windows already used (don't overlap): {used}\n"
                    'Pick ONE 35-55s window with visible action. Return JSON {"file":0,"start":0,"end":45}')
        c = clamp(files, j, 30, 55)
        if c and not looks_bad(files[c["file"]], c["start"], c["end"]) and \
                all(not (c["file"] == u[0] and c["start"] < u[2] and c["end"] > u[1]) for u in used):
            new = c
    except Exception:
        pass
    if not new:
        got = best_windows(files, 45, 1, used=used)
        new = got[0] if got else old
    new["part"] = want
    return sorted(others + [new], key=lambda p: p["part"])


def clean_clip(f, c):
    """Trim cruiser-interior / black stretches off a clip's ends and split it around any child/gore frames."""
    v = vis(f)
    if not v:
        return [c]
    s, e = int(c["start"]), int(min(c["end"], len(v["act"])))
    while s < e - 15 and v["dull"][s] and not v["bad"][s]:
        s += 1
    while e > s + 15 and v["dull"][e - 1] and not v["bad"][e - 1]:
        e -= 1
    segs, cur = [], s
    for t in range(s, e):
        if v["bad"][t]:
            if t - 3 - cur >= 15:
                segs.append((cur, t - 3))
            cur = t + 4
    if e - cur >= 15:
        segs.append((cur, e))
    out = []
    for a, b in segs:
        q = on_screen(f, a, b)
        if q and q[1] > 0.6:                    # mostly nothing to see — drop it
            continue
        out.append(dict(c, start=float(a), end=float(b)))
    return out


def pick_episode(files, plan, cache):
    key = f"episode:{plan['id']}"
    if key in cache:
        return cache[key]
    sc = plan.get("script") or {}
    total = sum(f["duration"] for f in files)
    target = min(total, 14 * 60)
    result = None
    try:
        j = ask_llm("You edit long-form YouTube episodes from police bodycam footage, like EWU, Code Blue Cam and "
                    "Dr Insanity. " + RULES,
                    describe(files) + f"\n\nEpisode: {plan.get('title')} ({sc.get('style', 'action')} style)\n"
                    f"Angle labels available: {sc.get('angle_labels') or ['Body Cam Officer 1']}\n" + redo(plan) +
                    f"Build the episode from about {target / 60:.0f} minutes of footage (less if the footage is thin; "
                    "cut dead air and stretches where the camera shows nothing but a cruiser interior). Clips run in "
                    "story order; each clip 20s-6min. Label each clip with which camera it "
                    "is (e.g. Body Cam Officer 1, Dash Cam, Interview Room, 911 Call). Also pick a 6-12s cold open: the "
                    "most gripping VISIBLE moment, from later in the story. "
                    'Return JSON {"cold_open":{"file":0,"start":300,"end":310},'
                    '"clips":[{"file":0,"start":0,"end":120,"label":"Body Cam Officer 1"}]}')
        clips = [c for c in (clamp(files, x, 15, 360) for x in j.get("clips", [])) if c]
        clips = [x for c in clips for x in clean_clip(files[c["file"]], c)]
        cold = clamp(files, j.get("cold_open") or {}, 5, 12)
        if cold and looks_bad(files[cold["file"]], cold["start"], cold["end"], min_action=2.0, max_dull=0.2):
            cold = None
        if sum(c["end"] - c["start"] for c in clips) < min(360, total * 0.4):
            clips = []                      # AI cut was far too thin for the footage we have — use the fallback
        if clips:
            result = {"cold_open": cold or best_windows(files, 9, 1)[0], "clips": clips}
    except Exception:
        pass
    if not result:
        clips = []
        share = target / max(1, len(files))
        for i, f in enumerate(files[:8]):
            rms = f["rms"]
            v = vis(f)
            med = statistics.median(rms) if rms else -90
            active = [t for t, x in enumerate(rms) if x > med + 6 and not (v and t < len(v["dull"]) and v["dull"][t])]
            if v:
                active = sorted(set(active) | {t for t, a in enumerate(v["act"]) if a >= 2})
            s = max(0, (active[0] if active else 0) - 15)
            e = min(f["duration"], (active[-1] if active else f["duration"]) + 15)
            if e - s > share:  # keep the best stretch of this file
                s = max(0, best_windows([f], int(share), 1)[0]["start"])
                e = s + share
            if e - s >= 15:
                clips += clean_clip(f, {"file": i, "start": float(s), "end": float(e)})
        if not clips:
            clips = [{"file": 0, "start": 0.0, "end": float(min(files[0]["duration"], target))}]
        result = {"cold_open": best_windows(files, 9, 1)[0], "clips": clips}
    labels = (sc.get("angle_labels") or [])
    for n, c in enumerate(result["clips"]):
        if not c.get("label"):
            c["label"] = labels[c["file"]] if c["file"] < len(labels) else f"Body Cam Officer {c['file'] + 1}"
    cache[key] = result
    return result


def picks_for(folder, files, plan):
    cache = media.load_json(Path(folder) / PICKS, {})
    kind = plan["kind"]
    recut = bool(fix_note(plan))
    if kind == "reel":
        if recut:
            cache.pop(f"reel:{plan['id']}", None)
        out = pick_reel(files, plan, cache)
    elif kind == "short":
        key = f"shorts:{plan.get('parent_id') or plan['case_name']}"
        want = int(plan.get("part") or 1)
        if recut and not cache.get(key + ":vision"):
            # cut before the vision check existed: re-pick the whole series so Parts 1-3 stay in story order;
            # the other parts' re-cuts then use these fresh picks instead of re-picking again
            cache.pop(key, None)
            cache[key + ":fresh"] = [1, 2, 3]
            recut = False
        parts = pick_shorts(files, plan, cache)
        cache[key + ":vision"] = True
        fresh = cache.get(key + ":fresh") or []
        if recut and want in fresh:
            recut = False
        if want in fresh:
            cache[key + ":fresh"] = [x for x in fresh if x != want]
        if recut:
            parts = cache[key] = recut_short(files, plan, cache, parts)
        out = next((p for p in parts if p["part"] == want), parts[min(want, len(parts)) - 1])
    else:
        if recut:
            cache.pop(f"episode:{plan['id']}", None)
        out = pick_episode(files, plan, cache)
    media.save_json(Path(folder) / PICKS, cache)
    return out
