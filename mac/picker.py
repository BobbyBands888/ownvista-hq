"""Footage analysis + clip picking. Reads what's actually in the footage (Whisper transcript + loudness)
and decides which seconds go into each episode, Short and Reel. Uses the Groq LLM when available and a
loudness-based fallback otherwise, so a render never stalls on the AI."""
import statistics
import zipfile
from pathlib import Path

import media

ANALYSIS = ".tft_analysis.json"
PICKS = ".tft_picks.json"


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
            files.append(known[key])
            continue
        info = media.probe(p)
        if not info["video"] or info["duration"] < 3:
            continue
        log(f"analysing {key} ({info['duration']:.0f}s)")
        info.update(path=key, size=p.stat().st_size,
                    rms=media.loudness(p, info["duration"]) if info["audio"] else [-90.0] * (int(info["duration"]) + 1),
                    transcript=media.transcribe(p, folder / ".tft_work", groq_key) if info["audio"] else [])
        files.append(info)
        media.save_json(folder / ANALYSIS, {"files": files + [f for f in cache["files"] if f["path"] not in {x["path"] for x in files}]})
    media.save_json(folder / ANALYSIS, {"files": files})
    if not files:
        raise RuntimeError(f"No usable video files in {folder}")
    return files


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


def action_start(rms, s, e):
    """Move a clip start onto the biggest jump in sound inside its first half (action in the first seconds)."""
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
        for s, v in window_scores(f["rms"], L):
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
    return head + "\n\nTRANSCRIPT (speaker words from the bodycam audio):\n" + (body or "(no speech found)")


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
Prefer real action: shouting, commands, foot chases, struggles, arrests, crashes, shots fired (but not a death on screen)."""


# ---------------- picks ----------------
def pick_reel(files, plan, cache):
    key = f"reel:{plan['id']}"
    if key in cache:
        return cache[key]
    sc = plan.get("script") or {}
    pick = None
    try:
        j = ask_llm("You cut 25-30 second Facebook Reels from police bodycam footage. " + RULES,
                    describe(files) + f"\n\nThe Reel is for this moment: {sc.get('moment') or plan.get('title')}\n"
                    f"Hook text: {sc.get('hook_text', '')}\n"
                    "Pick ONE continuous 25-30s window where the action starts within the first 2 seconds. "
                    'Return JSON {"file":0,"start":12.0,"end":40.0,"why":"..."}')
        pick = clamp(files, j, 24, 30)
    except Exception:
        pass
    if not pick:
        pick = best_windows(files, 27, 1)[0]
    f = files[pick["file"]]
    s = action_start(f["rms"], pick["start"], pick["end"])
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
                    describe(files) + f"\n\nCase: {plan.get('case_name')}\n"
                    "Pick 3 non-overlapping windows of 35-55 seconds each, in story order (Part 1 sets up and ends on a "
                    "cliffhanger, Part 2 escalates, Part 3 has the climax/resolution). "
                    'Return JSON {"parts":[{"part":1,"file":0,"start":0,"end":45}, ...]}')
        for p in j.get("parts", [])[:3]:
            c = clamp(files, p, 30, 55)
            if c:
                c["part"] = int(p.get("part", len(parts) + 1))
                parts.append(c)
    except Exception:
        pass
    if len(parts) < 3:
        parts = best_windows(files, 45, 3)
        parts.sort(key=lambda p: (p["file"], p["start"]))
        for n, p in enumerate(parts, 1):
            p["part"] = n
    cache[key] = parts
    return parts


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
                    f"Angle labels available: {sc.get('angle_labels') or ['Body Cam Officer 1']}\n"
                    f"Build the episode from about {target / 60:.0f} minutes of footage (less if the footage is thin; "
                    "cut dead air). Clips run in story order; each clip 20s-6min. Label each clip with which camera it "
                    "is (e.g. Body Cam Officer 1, Dash Cam, Interview Room, 911 Call). Also pick a 6-12s cold open: the "
                    "most gripping moment, from later in the story. "
                    'Return JSON {"cold_open":{"file":0,"start":300,"end":310},'
                    '"clips":[{"file":0,"start":0,"end":120,"label":"Body Cam Officer 1"}]}')
        clips = [c for c in (clamp(files, x, 15, 360) for x in j.get("clips", [])) if c]
        cold = clamp(files, j.get("cold_open") or {}, 5, 12)
        if clips:
            result = {"cold_open": cold or best_windows(files, 9, 1)[0], "clips": clips}
    except Exception:
        pass
    if not result:
        clips = []
        share = target / max(1, len(files))
        for i, f in enumerate(files[:8]):
            rms = f["rms"]
            med = statistics.median(rms) if rms else -90
            active = [t for t, v in enumerate(rms) if v > med + 6]
            s = max(0, (active[0] if active else 0) - 15)
            e = min(f["duration"], (active[-1] if active else f["duration"]) + 15)
            if e - s > share:  # keep the loudest stretch of this file
                s = max(0, best_windows([f], int(share), 1)[0]["start"])
                e = s + share
            if e - s >= 15:
                clips.append({"file": i, "start": float(s), "end": float(e)})
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
    if kind == "reel":
        out = pick_reel(files, plan, cache)
    elif kind == "short":
        parts = pick_shorts(files, plan, cache)
        want = int(plan.get("part") or 1)
        out = next((p for p in parts if p["part"] == want), parts[min(want, len(parts)) - 1])
    else:
        out = pick_episode(files, plan, cache)
    media.save_json(Path(folder) / PICKS, cache)
    return out
