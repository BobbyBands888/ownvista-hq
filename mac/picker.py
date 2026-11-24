"""Footage analysis + clip picking. Reads what's actually in the footage (Whisper transcript + loudness +
a vision pass over sampled frames) and decides which seconds go into each episode, Short and Reel. Uses the
Groq LLM when available and a loudness/vision fallback otherwise, so a render never stalls on the AI.
Every pick is checked against what is ON SCREEN: a window that only shows a cruiser's interior, a dashboard
or a black screen is swapped out even if the audio (sirens, shouting) is loud."""
import os
import re
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
    if any(not f.get("vision_ok") or f.get("vision_v") != VISION_V for f in files):
        look(folder, files, log)
        media.save_json(folder / ANALYSIS, {"files": files + [f for f in media.load_json(folder / ANALYSIS, {"files": []})["files"]
                                                         if f["path"] not in {x["path"] for x in files}]})
    if any(f.get("vision_ok") and f.get("dense_v") != DENSE_V for f in files):
        densify(folder, files, log)
        media.save_json(folder / ANALYSIS, {"files": files + [f for f in media.load_json(folder / ANALYSIS, {"files": []})["files"]
                                                         if f["path"] not in {x["path"] for x in files}]})
    return files


# ---------------- vision: what is actually on screen ----------------
VISION_V = 2                                         # bump when LOOK_PROMPT changes: cached frames get re-read
SHEET = 9                                            # frames per vision call (3x3 grid)
VISION_GAP = float(os.environ.get("TFT_VISION_GAP", "4"))     # seconds between vision calls
MAX_SHEETS = int(os.environ.get("TFT_VISION_SHEETS", "70"))   # per case, keeps us inside the free tier
# Stop vision once llm.vision_calls reaches this (None = no cap). Screening new leads sets it so one long video
# (the 38-min SF town hall, Nov 23) can't use the whole day's free allowance before approved clips render. Frames
# already read are kept, so a long video is finished over the next runs instead of skipped.
CALL_CAP = None


def _stop_vision(log):
    """True when this run must not make another vision call (daily allowance gone, or the screening share used)."""
    from agents.lib import llm
    if llm.vision_exhausted():
        log("vision: free daily allowance used up; the rest is read after the reset")
        return True
    if CALL_CAP is not None and llm.vision_calls >= CALL_CAP:
        log("vision: this run's screening share is used; continuing next run")
        return True
    return False
LOOK_PROMPT = """This grid shows {n} numbered frames (red labels), in time order, from police body-camera / dash-camera footage.
For EACH numbered frame judge ONLY what is visible in the picture (there is no audio):
- view: "outside" (officer on foot outdoors), "road_ahead" (dash/windshield view of the road), "inside_car" (cruiser
  interior: dashboard, steering wheel, seats, laptop, officer driving with nothing happening outside), "indoor", "black"
  (blank, dark, covered or too blurry to see), "screen" (anything that is NOT live camera footage: title card, text
  slate, disclaimer, viewer warning, document, map, satellite/aerial still, Google Street View, diagram, agency
  briefing graphic, or a paragraph of text laid over dimmed / blurred footage)
- action 0-3: 0 nothing happening / empty scene; 1 calm talking, walking, routine driving; 2 tense: confrontation,
  weapon drawn, someone fleeing, pursuit with the suspect vehicle visible ahead; 3 peak: struggle, tackle, arrest
  on the ground, crash, shots fired, foot chase with the suspect in view
- child: true if a child appears
- gore: true if blood, a badly injured person or a body is visible, AND true for any aftermath of force: a person
  lying limp or motionless on the ground after shots / a struggle, someone being given CPR, first aid or checked
  for a pulse, officers kneeling over a downed person. When unsure whether a person on the ground is hurt, say true
- desc: what is visible, max 10 words
Return {{"frames":[{{"n":1,"view":"outside","action":2,"child":false,"gore":false,"desc":"officer points gun at driver"}}]}}"""


def frames_of(j, n):
    """Per-frame dicts from a vision reply, whatever shape the model used: {"frames":[...]}, {"frames":{"1":...}},
    {"1":{...}}, a bare list, "n" as int / "1" / "frame 1", or no "n" at all (then position order). -> {index: dict}"""
    import re
    if not isinstance(j, dict):
        return {}
    fr = j.get("frames", j.get("results", j.get("data", j)))
    items = []
    if isinstance(fr, dict):
        for k, v in fr.items():
            if isinstance(v, dict):
                items.append({**v, "n": v.get("n", k)})
    elif isinstance(fr, list):
        items = [v for v in fr if isinstance(v, dict)]
    out = {}
    for pos, v in enumerate(items):
        raw = v.get("n", v.get("frame", v.get("index", v.get("id"))))
        m = re.search(r"\d+", str(raw)) if raw is not None else None
        k = int(m[0]) - 1 if m else pos
        if 0 <= k < n and k not in out and any(x in v for x in ("view", "action", "desc")):
            out[k] = v
    return out


def _int03(x):
    import re
    m = re.search(r"\d", str(x or 0))
    return max(0, min(3, int(m[0]))) if m else 0


def _true(x):
    return x is True or str(x).strip().lower() in ("true", "yes", "1")


def look(folder, files, log=print):
    """Caption sampled frames of every file (cached in the analysis). Fails soft: no vision = old behaviour."""
    from agents.lib import llm
    total = sum(f["duration"] for f in files)
    step = max(5.0, total / (MAX_SHEETS * SHEET))
    fails = 0
    for f in files:
        if f.get("vision_v") != VISION_V:      # older prompt missed slates over footage and aftermath: re-read
            f["vision"], f["vision_ok"] = [], False
        if f.get("vision_ok") and f.get("vision_step", 99) <= step + 0.01:
            continue
        times = [round(t, 1) for t in frange(step / 2, f["duration"] - 0.5, step)] or [f["duration"] / 2]
        got = {v["t"]: v for v in f.get("vision") or []}
        ok = True
        for k in range(0, len(times), SHEET):
            chunk = times[k:k + SHEET]
            if all(t in got for t in chunk):
                continue
            if fails >= 5 or _stop_vision(log):  # vision is down / out for now: keep what was read, retry next run
                ok = False
                break
            try:
                import time
                time.sleep(VISION_GAP)          # stay under the free tier's tokens-per-minute cap
                img = media.contact_sheet(Path(folder) / f["path"], chunk)
                j = llm.see(LOOK_PROMPT.format(n=len(chunk)), img,
                            check=lambda r, c=len(chunk): len(frames_of(r, c)) >= max(1, c // 2))
                for n, fr in frames_of(j, len(chunk)).items():
                    got[chunk[n]] = {"t": chunk[n], "view": str(fr.get("view", ""))[:12],
                                     "action": _int03(fr.get("action")),
                                     "child": _true(fr.get("child")), "gore": _true(fr.get("gore")),
                                     "desc": str(fr.get("desc", ""))[:80]}
                fails = 0
            except Exception as e:
                fails += 1
                ok = False
                log(f"vision error: {str(e)[:300]}")
                import time
                time.sleep(20 * fails)          # back off; free-tier limits are per minute
        f["vision"] = sorted(got.values(), key=lambda v: v["t"])
        f["vision_step"] = step
        f["vision_v"] = VISION_V
        # A file stuck on one unreadable sheet (a few frames the fallback model garbles) used to block the whole
        # case forever (Sebring, Nov 17: 93/102 frames, every run). 90% read is enough even with errors;
        # every render is still checked frame by frame before approval.
        f["vision_ok"] = len(f["vision"]) >= len(times) * (0.8 if ok else 0.9)
        log(f"vision {f['path']}: {len(f['vision'])}/{len(times)} frames read")
    return files


def frange(a, b, step):
    t = a
    while t < b:
        yield t
        t += step


# ---------------- dense pass: every second around the danger ----------------
# Glendale knife reels (Nov 21): the shot suspect lay limp on the floor for ~4s between two 5s vision samples, both
# read "no gore", and the gap borrowed their label, so he went out unblurred. Shootings, crashes and takedowns are
# where a downed person appears, so those stretches are read frame by frame, and after shots are fired every second
# nobody read counts as aftermath (blurred / cut), never as clean.
DENSE_V = 1
DENSE_STEP = 1.0
SHOT_AFTER = 45            # seconds after shots that must be read 1 fps before they count as clean
HOT_AFTER = 15             # same for other peak moments (crash, tackle, weapon)
HOT_BEFORE = 3
MAX_DENSE = int(os.environ.get("TFT_DENSE_FRAMES", "270"))     # per case (30 vision calls)
SHOT_WORDS = re.compile(r"\bshots? fired\b|\bshoot(?:ing)?\b|\bshots\b|\bhe'?s (?:been )?shot\b|\bi'?m hit\b|"
                        r"\bman down\b|\bofficer down\b", re.I)
SHOT_DESC = re.compile(r"\bshoot|\bshots?\b|\bfir(?:es|ing|ed)\b|muzzle", re.I)
LESS_LETHAL = re.compile(r"taser|stun|less.lethal|bean ?bag|pepper|40 ?mm", re.I)
HOT_DESC = re.compile(r"\bgun\b|\bknife\b|weapon|taser|tackl|struggl|crash|on the ground|\bdown\b|lying|fight", re.I)


def shot_times(f):
    """Seconds where shots are fired in this file: transcript lines and vision captions. [] if none."""
    ts = [float(s.get("start", 0)) for s in f.get("transcript") or [] if SHOT_WORDS.search(s.get("text") or "")]
    ts += [float(v["t"]) for v in f.get("vision") or []
           if SHOT_DESC.search(v.get("desc") or "") and not LESS_LETHAL.search(v.get("desc") or "")]
    return sorted(ts)


def hot_windows(f):
    """[(start, end)] stretches to read every second: after any shots (SHOT_AFTER) and around peak moments."""
    n = float(f["duration"])
    w = [(t - HOT_BEFORE, t + SHOT_AFTER) for t in shot_times(f)]
    for v in f.get("vision") or []:
        if v.get("dense"):
            continue
        if v.get("action", 0) >= 3 or v.get("gore") or (v.get("action", 0) >= 2 and HOT_DESC.search(v.get("desc") or "")):
            w.append((v["t"] - HOT_BEFORE - 2, v["t"] + HOT_AFTER))
    w = sorted((max(0.0, a), min(n, b)) for a, b in w if b > 0)
    out = []
    for a, b in w:
        if out and a <= out[-1][1] + 2:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def densify(folder, files, log=print):
    """Read every second of each file's hot windows (cached in the analysis with "dense": True)."""
    from agents.lib import llm
    import time
    budget, fails = MAX_DENSE, 0
    # shootings first: their windows matter most if the budget runs out
    for f in sorted(files, key=lambda f: -len(shot_times(f))):
        if not f.get("vision_ok"):
            continue
        got = {v["t"]: v for v in f.get("vision") or []}
        dense_t = {round(t) for t, v in got.items() if v.get("dense")}
        want = []
        for a, b in hot_windows(f):
            want += [float(t) for t in range(int(a), int(min(b, f["duration"] - 0.5)) + 1) if t not in dense_t]
        want = sorted(set(want))[:budget]
        done = True
        for k in range(0, len(want), SHEET):
            chunk = want[k:k + SHEET]
            if fails >= 5 or _stop_vision(log):
                done = False
                break
            try:
                time.sleep(VISION_GAP)
                img = media.contact_sheet(Path(folder) / f["path"], chunk)
                j = llm.see(LOOK_PROMPT.format(n=len(chunk)), img,
                            check=lambda r, c=len(chunk): len(frames_of(r, c)) >= max(1, c // 2))
                for n, fr in frames_of(j, len(chunk)).items():
                    got[chunk[n]] = {"t": chunk[n], "view": str(fr.get("view", ""))[:12],
                                     "action": _int03(fr.get("action")),
                                     "child": _true(fr.get("child")), "gore": _true(fr.get("gore")),
                                     "desc": str(fr.get("desc", ""))[:80], "dense": True}
                fails = 0
            except Exception as e:
                fails += 1
                done = False
                log(f"dense vision error: {str(e)[:300]}")
                time.sleep(20 * fails)
        budget -= len(want)
        f["vision"] = sorted(got.values(), key=lambda v: v["t"])
        if done and budget >= 0:
            f["dense_v"] = DENSE_V          # unread hot seconds stay unsafe (gore_secs) until a later run reads them
        log(f"dense vision {f['path']}: {len(want)} frames around {len(hot_windows(f))} hot moment(s)")
        _VA.clear()
    return files


def gore_secs(f, n=None):
    """Per-second 0/1: 1 where a downed / injured person may be on screen. Conservative on purpose:
    - a gore frame marks its neighbours too (dense frame: +-1s; sampled frame: +-half the sample step + 1s)
    - after shots, every second not read 1 fps (within 1s) counts as gore until the dense pass clears it."""
    n = n or int(f["duration"]) + 1
    g = [0] * n
    fr = f.get("vision") or []
    half = max(2, int(float(f.get("vision_step") or 5.0) / 2) + 1)
    dense = [0] * n
    for v in fr:
        t = int(round(v["t"]))
        r = 1 if v.get("dense") else half
        if v.get("dense") and 0 <= t < n:
            dense[t] = 1
        if v.get("gore"):
            for k in range(max(0, t - r), min(n, t + r + 1)):
                g[k] = 1
    for s in shot_times(f):
        for t in range(max(0, int(s)), min(n, int(s) + SHOT_AFTER + 1)):
            if not any(dense[k] for k in range(max(0, t - 1), min(n, t + 2))):
                g[t] = 1
    return g


# Words that only come after someone is down. From AFTERMATH_LEAD s before the first one to the end of that file is
# treated like gore: vision samples every few seconds and can miss a body; the audio doesn't.
AFTERMATH = re.compile(r"\bno pulse\b|check (?:the |his |her |for a )?pulse|\bcpr\b|compressions|not breathing|"
                       r"recovery position|(?:he|she)(?:'s| is) (?:dead|gone|not responsive|unresponsive)|tourniquet|"
                       r"chest seal|where(?:'s| is) he hit|stay with (?:me|us)", re.I)
AFTERMATH_LEAD = 60


# Nov 23-24: vision read the frames after the Glendale shots (dense pass done) and still called the downed, wounded man
# "no gore", so the episode re-cut showed him being treated, unblurred. A person shot on camera is on the ground right
# after the shots, so from SHOT_GRACE s after the first shot on, a file counts as aftermath whatever vision says:
# episodes end the clear footage there and add a blurred tail, Reels blur from there, Shorts stop before it.
SHOT_GRACE = 2


# Only live-event evidence starts the aftermath: briefings and slates say "officer-involved shooting" in their first
# seconds, and an officer yelling "I'll shoot" comes before any shots, so neither may cut the footage there.
SHOTS_LIVE = re.compile(r"\bshots? fired\b|\bhe'?s (?:been )?shot\b|\bi'?m hit\b|\bman down\b|\bofficer down\b", re.I)


def shot_aftermath(f):
    """Second just after the first shot seen in this file's live footage (SHOT_GRACE s on), or None."""
    ts = [float(x.get("start", 0)) for x in f.get("transcript") or [] if SHOTS_LIVE.search(x.get("text") or "")]
    ts += [float(v["t"]) for v in f.get("vision") or []
           if v.get("view") not in ("screen", "black") and SHOT_DESC.search(v.get("desc") or "")
           and not LESS_LETHAL.search(v.get("desc") or "")]
    return int(min(ts)) + SHOT_GRACE if ts else None


def aftermath_from(f):
    """Second from which this file shows the aftermath of force (by its audio, or right after shots), or None."""
    hits = [s.get("start", 0) for s in f.get("transcript") or [] if AFTERMATH.search(s.get("text") or "")]
    a = max(0, int(min(hits)) - AFTERMATH_LEAD) if hits else None
    sa = shot_aftermath(f)
    if sa is not None:
        a = sa if a is None else min(a, sa)
    return a


def hits_aftermath(f, s, e):
    a = aftermath_from(f)
    return a is not None and e > a


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
    act, dull, bad, screen = [0.0] * n, [0.0] * n, [0.0] * n, [0.0] * n
    child, gore = [0.0] * n, [0.0] * n           # Shorts may blur gore, never use a child
    after = aftermath_from(f)
    hits = [x.get("start", 0) for x in f.get("transcript") or [] if AFTERMATH.search(x.get("text") or "")]
    blur_from = max(0, int(min(hits)) - 3) if hits else None   # the Reels rule (mac/reelcut.py seconds())
    j = 0
    # A second with no read frame nearby is unknown, and unknown counts as unsafe: since files may now pass with
    # up to 10% of frames unread (PR #18), a gap must never borrow a neighbour's "no child / no gore" label.
    gap = max(8.0, 1.6 * float(f.get("vision_step") or 5.0))
    g = gore_secs(f, n)                             # never borrowed from the nearest clean frame (see densify)
    for t in range(n):
        while j + 1 < len(fr) and abs(fr[j + 1]["t"] - t) <= abs(fr[j]["t"] - t):
            j += 1
        v = fr[j]
        if abs(v["t"] - t) > gap:
            act[t], dull[t], bad[t], screen[t] = 0.0, 1.0, 1.0, 0.0
            child[t] = 1.0                          # unknown counts as a possible child: never used, never blurred
            continue
        act[t] = v["action"]
        dull[t] = 1.0 if v["view"] == "screen" or (v["action"] < 2 and (v["view"] in ("inside_car", "black")
                                                                         or v["action"] == 0)) else 0.0
        child[t] = 1.0 if v["child"] else 0.0
        gore[t] = 1.0 if g[t] or (blur_from is not None and t >= blur_from) else 0.0
        bad[t] = 1.0 if v["child"] or g[t] or (after is not None and t >= after) else 0.0
        screen[t] = 1.0 if v["view"] == "screen" else 0.0
    out = {"act": act, "dull": dull, "bad": bad, "screen": screen, "child": child, "gore": gore}
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


def screen_summary(files):
    """What the footage SHOWS, for Maker to plan from (Oakfield, Nov 21: the lead text said PIT + Taser; the video
    was 4 minutes of headlights and a hands-up surrender). Action seconds with no child, slate or dead air.
    Seconds that get blurred (a downed person after shots) still count: the action around them is what the page
    wants, and the renderer blurs them (Nov 23: the Newport sailboat shootout and the Bradenton officers-hit clip
    were skipped because every second after the shots was flagged aftermath)."""
    secs = tense = peak = 0
    moments, shots = [], []
    for f in files:
        v = vis(f)
        secs += float(f["duration"])
        if v:
            for t in range(len(v["act"])):
                if v["child"][t] or v["screen"][t] or v["dull"][t]:
                    continue
                tense += v["act"][t] >= 2
                peak += v["act"][t] >= 3
        shots += [(f["path"], round(t)) for t in shot_times(f)]
        for fr in f.get("vision") or []:
            if fr.get("action", 0) >= 2 and not fr.get("child") and fr.get("view") not in ("screen", "black"):
                moments.append({"file": f["path"], "t": round(fr["t"]), "action": fr["action"],
                                "desc": fr.get("desc") or "", "aftermath": bool(fr.get("gore"))})
    moments.sort(key=lambda m: (-m["action"], m["file"], m["t"]))
    keep = []
    for m in moments:                                # one line per moment: frames within 10s are the same moment
        if not any(k["file"] == m["file"] and abs(k["t"] - m["t"]) < 10 for k in keep):
            keep.append(m)
        if len(keep) >= 15:
            break
    keep.sort(key=lambda m: (m["file"], m["t"]))
    return {"secs": round(secs), "tense_secs": int(tense), "peak_secs": int(peak),
            "n_moments": sum(1 for m in keep if not m["aftermath"]), "moments": keep,
            "shots": [{"file": p, "t": t} for p, t in shots[:10]],
            "vision_ok": all(f.get("vision_ok") for f in files)}


SCREEN_MIN_PEAK = 3      # clean seconds of PEAK action (struggle, tackle, crash, shots, foot chase in view) a lead
                         # needs to be made at all. A pursuit that is only taillights ahead (Oakfield) doesn't pass:
                         # Bobby, Nov 21: "we need good high action content like our competitors".


def screen_verdict(s):
    if not s.get("vision_ok"):
        return "incomplete"
    if s["peak_secs"] >= SCREEN_MIN_PEAK:
        return "action"
    # shots fired on camera with a tense build-up is the content the page wants even if vision rated it 2/3
    # (dark boat cabin, night stairwell)
    return "action" if s.get("shots") and s["tense_secs"] >= SCREEN_MIN_PEAK + 2 else "no_action"


SHORT_BLUR_MAX = 10   # seconds of death / body a Short may keep under a full-frame blur (same cap as Reels)


def blur_ok(f, s, e):
    """Shorts rule (Bobby, Nov 18-19): a death on camera is OK only under a full-frame blur. A window passes when
    it has no child (or unread) second and at most SHORT_BLUR_MAX gore / aftermath seconds, which mac/render.py
    blurs. Without vision there's nothing to blur by, so any aftermath still fails."""
    v = vis(f)
    if not v:
        return not hits_aftermath(f, s, e)
    a, b = max(0, int(s)), min(len(v["act"]), int(e))
    return not any(v["child"][a:b]) and sum(v["gore"][a:b]) <= SHORT_BLUR_MAX


def looks_bad(f, s, e, min_action=1.0, max_dull=0.5, allow_blur=False):
    if allow_blur:
        if not blur_ok(f, s, e):
            return True
    elif hits_aftermath(f, s, e):
        return True
    q = on_screen(f, s, e)
    return bool(q) and (q[0] < min_action or q[1] > max_dull or (q[2] and not allow_blur))


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


def scored_windows(f, length, allow_blur=False):
    """Loudness plus what's on screen: visible action scores up, cruiser-interior / black stretches score down,
    anything showing a child or gore is excluded. allow_blur (Shorts): a short gore stretch may stay (it gets a
    full-frame blur), scored a little down so a clean window of the same action wins."""
    sc = window_scores(f["rms"], length)
    if not vis(f):
        return [(s, v) for s, v in sc if not hits_aftermath(f, s, s + length)]
    out = []
    for s, v in sc:
        a, dull, bad = on_screen(f, s, s + length)
        if not bad:
            out.append((s, v + 6 * a - 15 * dull))
        elif allow_blur and blur_ok(f, s, s + length):
            g = sum(vis(f)["gore"][int(s):int(s + length)])
            out.append((s, v + 6 * a - 15 * dull - g))
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


BLUR_TAIL = 20     # seconds of aftermath shown fully blurred (real audio) instead of cut — episodes only


def add_blurred_tails(files, clips):
    """Rule (Nov 16): a death case may show what happens after someone goes down, but only fully blurred, max
    BLUR_TAIL seconds, never in thumbnails / cold opens / Shorts / Reels. A clip that stops at a file's aftermath
    line gets a blurred continuation right after it."""
    out, done = [], set()
    for c in clips:
        out.append(c)
        f = files[c["file"]]
        a = aftermath_from(f)
        if a is None or c["file"] in done or c.get("blur"):
            continue
        if a - 8 <= c["end"] <= a + 1:
            e = min(f["duration"], a + BLUR_TAIL)
            if e - a >= 5:
                out.append({"file": c["file"], "start": float(a), "end": float(e), "blur": True,
                            "label": c.get("label")})
                done.add(c["file"])
    return out


def safe_clips(files, clips):
    """Last check on any episode cut, whatever made it: no clear clip may contain a child/gore frame or run past
    the aftermath line; such a clip is split around those seconds (dropping pieces under 15s). Blurred tails are
    the only footage allowed past the aftermath line, and only BLUR_TAIL seconds of it."""
    out = []
    for c in clips:
        f = files[c["file"]]
        a = aftermath_from(f)
        if c.get("blur"):
            if a is not None:
                s = max(c["start"], float(a))
                e = min(c["end"], s + BLUR_TAIL)
                if e - s >= 5:
                    out.append(dict(c, start=s, end=e))
            continue
        v = vis(f)
        s, e = int(c["start"]), int(c["end"])
        if a is not None:
            e = min(e, a)
        if not v:
            if e - s >= 15:
                out.append(dict(c, start=float(s), end=float(e)))
            continue
        e = min(e, len(v["bad"]))
        cur = s
        for t in range(s, e):
            if v["bad"][t]:
                if t - 3 - cur >= 15:
                    out.append(dict(c, start=float(cur), end=float(t - 3)))
                cur = t + 4
        if e - cur >= 15:
            out.append(dict(c, start=float(cur), end=float(e)))
    if not out:
        raise RuntimeError("NO SAFE CUT: nothing left after removing child/gore/aftermath footage")
    return out


def _cold_fallback(files, clips):
    """Best 9s window anywhere usable; else the first 9s of the first clip (never crashes on an empty pick)."""
    bw = best_windows(files, 9, 1)
    if bw:
        return bw[0]
    c = clips[0]
    return {"file": c["file"], "start": c["start"], "end": min(c["end"], c["start"] + 9)}


def best_windows(files, length, count, used=None, allow_blur=False):
    used = list(used or [])
    cands = []
    for i, f in enumerate(files):
        L = min(length, int(f["duration"]) - 1)
        if L < 8:
            continue
        for s, v in scored_windows(f, L, allow_blur):
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


RULES = """Hard rules for every cut: never include the moment of a death, gore, or a lingering view of a body
(Reels and Shorts may keep a short one, 10 seconds at most: a full-frame blur goes over it);
skip any stretch where a child is on camera; skip long dead air (walking, paperwork, silence).
Prefer real action: shouting, commands, foot chases, struggles, arrests, crashes, shots fired (but not a death on screen).
The action must be VISIBLE: use WHAT'S ON SCREEN. Sirens or shouting heard while the picture only shows a cruiser's
interior, dashboard or a black screen is NOT action — never pick those stretches. Never pick frames marked CHILD.
Frames marked GORE only inside a Reel or Short, briefly (they get blurred); never in a long-form clip."""


# ---------------- picks ----------------
def fix_note(plan):
    """Bobby's reason when he asked for a re-cut (dashboard 'Re-cut' button), else ''."""
    n = plan.get("publish_note") or ""
    return n.split(":", 1)[1].strip() if n.startswith("Re-cut") else ""


def _skip_until(note):
    m = re.search(r"(?:before|until|after|from)\s+(?:about\s+|~)?(\d{1,2}):(\d{2})", note or "", re.I)
    return int(m[1]) * 60 + int(m[2]) if m else 0


def redo(plan):
    n = fix_note(plan)
    return f"\nBobby REJECTED the previous cut of this video: \"{n}\". Pick different moments that fix that.\n" if n else ""


REEL_PAD = 5          # seconds kept between two Reels of the same case so they never share a moment


def _taken(files, plan, cache):
    """Windows already used by this case's OTHER Reels: from the plan (runner passes rendered siblings' cuts)
    and from this folder's pick cache. Returned as (file_index, start, end) padded by REEL_PAD."""
    idx = {f["path"]: i for i, f in enumerate(files)}
    # cuts made on another machine (cloud runner vs Mac) carry that machine's folder: match on the file name too
    by_name = {}
    for i, f in enumerate(files):
        by_name.setdefault(Path(str(f["path"])).name, i)
    out = []
    sc = plan.get("script") if isinstance(plan.get("script"), dict) else {}
    full = (sc.get("cut_kind") or "story") == "story" and not (sc.get("recut") or {}).get("winner_cut")
    cuts = [] if full else list(plan.get("sibling_cuts") or [])
    if (sc.get("recut") or {}).get("winner_cut"):       # a re-cut never reuses the winning Reel's seconds
        cuts.append(sc["recut"]["winner_cut"])
    flat = []
    for c in cuts:                                      # multi-segment Reels (mac/reelcut.py) list every segment
        if isinstance(c, dict) and c.get("segments"):
            if (c.get("kind") or "action") == "story" and (sc.get("cut_kind") or "story") == "action":
                continue                                # a case's action cut may reuse its story cut's seconds
            flat += [s for s in c["segments"] if isinstance(s, dict)]
        else:
            flat.append(c)
    for c in flat:
        if not isinstance(c, dict) or c.get("start") is None:
            continue
        i = idx.get(c.get("path"))
        if i is None:
            i = by_name.get(Path(str(c.get("path") or "")).name)
        if i is not None:
            out.append((i, float(c["start"]) - REEL_PAD, float(c["end"]) + REEL_PAD))
    parent = plan.get("parent_id")
    if full:
        # Nov 23: Facebook gets ONE full clip per case, start to finish. It may use every second of the incident,
        # whatever older short action cuts of the case picked (Backyard Knives' full clip failed "not enough
        # footage" because 5 short cuts had claimed its seconds).
        return out
    for k, v in cache.items():
        if k.startswith("reel:") and k != f"reel:{plan['id']}" and isinstance(v, dict) and parent \
                and v.get("parent") == parent and v.get("file") is not None:
            out.append((v["file"], v["start"] - REEL_PAD, v["end"] + REEL_PAD))
    return out


def _clear(p, taken):
    return all(not (p["file"] == i and p["start"] < e and p["end"] > s) for i, s, e in taken)


def pick_reel(files, plan, cache):
    """One standalone single-moment Reel. A case's 2-3 Reels never overlap; if no fresh 24s+ window with visible
    action is left, returns None and the render is skipped (no Reel that repeats another Reel's clip)."""
    key = f"reel:{plan['id']}"
    if key in cache:
        return cache[key]
    sc = plan.get("script") or {}
    taken = _taken(files, plan, cache)
    # a case story's one Reel is an interview teaser: a calm room is fine, a hooking line in the first 2s is the action
    talk = bool(TALK_RX.search(sc.get("moment") or ""))
    rc = sc.get("recut") if isinstance(sc.get("recut"), dict) else None
    recut_note = ""
    if rc:
        recut_note = (f"This is a RE-CUT of one of our best Reels (it showed: {rc.get('winner_moment') or 'see the taken window'}). "
                      "First choice: the SAME moment from ANOTHER file, if another file is a different officer's camera "
                      "covering it (a different angle is new footage). Otherwise the next strongest DIFFERENT moment: "
                      f"{sc.get('fallback_moment') or 'the most visible action left'}. Never overlap the taken windows.\n")
    pick = None
    try:
        j = ask_llm("You cut 60-90 second Facebook Reels from police bodycam footage. " + RULES,
                    describe(files) + f"\n\nThe Reel is for this moment: {sc.get('moment') or plan.get('title')}\n"
                    f"Hook text: {sc.get('hook_text', '')}\n" + recut_note + redo(plan) +
                    (f"Windows other Reels of this case already use (do NOT overlap them, pick a different moment): "
                     f"{[(i, round(a), round(b)) for i, a, b in taken]}\n" if taken else "") +
                    ("Pick ONE continuous 60-90s window of the police interview that opens on a line that hooks "
                     "(a lie, a denial, the detective putting evidence to them) and doesn't give away how the case ended. "
                     if talk else
                     "Pick ONE continuous 60-90s window where visible action starts within the first 2 seconds. ") +
                    'Return JSON {"file":0,"start":12.0,"end":40.0,"why":"..."}')
        pick = clamp(files, j, 60, 90)            # Bobby, Nov 23: every video at least a minute
    except Exception:
        pass
    if pick and talk:
        q = on_screen(files[pick["file"]], pick["start"], pick["end"])
        if hits_aftermath(files[pick["file"]], pick["start"], pick["end"]) or (q and q[2]) or not _clear(pick, taken):
            pick = None
        else:
            pick["parent"] = plan.get("parent_id")
            cache[key] = pick
            return pick
    if pick and (looks_bad(files[pick["file"]], pick["start"], pick["end"], min_action=1.5, max_dull=0.35)
                 or not _clear(pick, taken)):
        pick = None                             # nothing to see, or it reuses a sibling Reel's moment
    if not pick:
        long_enough = [f for f in files if f["duration"] >= 60]
        if not long_enough:
            return None                         # under a minute of footage: no Reel
        used = [(long_enough.index(files[i]), s, e) for i, s, e in taken if files[i] in long_enough]
        for c in best_windows(long_enough, 70, 4, used=used):
            c["file"] = files.index(long_enough[c["file"]])
            if not looks_bad(files[c["file"]], c["start"], c["end"], min_action=1.0, max_dull=0.5) or not taken:
                pick = c
                break
    if not pick:
        return None
    f = files[pick["file"]]
    pick = trim_open(f, pick, 60)
    s = action_start(f["rms"], pick["start"], pick["end"], f)
    pick.update(start=float(s), end=float(min(f["duration"], s + (pick["end"] - pick["start"]))))
    if taken and not _clear(pick, taken):       # action_start nudged it into a sibling's window
        return None
    pick["parent"] = plan.get("parent_id")
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
            if c:
                c = trim_open(files[c["file"]], c, 30)
            if c and not looks_bad(files[c["file"]], c["start"], c["end"], allow_blur=True):
                c["part"] = int(p.get("part", len(parts) + 1))
                parts.append(c)
    except Exception:
        pass
    if len(parts) < 3:                          # top up only the missing parts from the vision/loudness ranking
        extra = [trim_open(files[x["file"]], x, 30)
                 for x in best_windows(files, 45, 3 - len(parts), used=[(p["file"], p["start"], p["end"]) for p in parts],
                                       allow_blur=True)]
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
        if c:
            c = trim_open(files[c["file"]], c, 30)
        if c and not looks_bad(files[c["file"]], c["start"], c["end"], allow_blur=True) and \
                all(not (c["file"] == u[0] and c["start"] < u[2] and c["end"] > u[1]) for u in used):
            new = c
    except Exception:
        pass
    if not new:
        got = best_windows(files, 45, 1, used=used, allow_blur=True)
        new = got[0] if got else old
    new["part"] = want
    return sorted(others + [new], key=lambda p: p["part"])


LEAD_IN = 15        # seconds of build-up kept before the first tense moment
DULL_GAP = 20       # a dead stretch this long (maps, silent cruiser) is cut out
SLATE_GAP = 3       # text slates, warnings and maps are always dead footage: any run this long is cut out

def trim_open(f, c, min_len):
    """Shorts and Reels are one window: move the start past opening slates / dead frames, keeping the length
    (the end slides later) as long as that doesn't run into gore or the end of the file."""
    v = vis(f)
    if not v:
        return c
    s, e = int(c["start"]), int(c["end"])
    t = s
    while t < e - min_len and t < len(v["dull"]) and (v["dull"][t] or v["screen"][t]) and not v["bad"][t]:
        t += 1
    if t == s:
        return c
    end = min(f["duration"], e + (t - s))
    if any(v["bad"][int(e):int(min(end, len(v["bad"])))]):
        end = e
    return dict(c, start=float(t), end=float(end))


TALK_RX = re.compile(r"interview|interrogation|911|dispatch|call", re.I)


def clean_clip(f, c):
    """Trim cruiser-interior / black stretches off a clip's ends and split it around any child/gore frames.
    Interview-room and 911 clips are talk: a still camera or a slate over 911 audio is the point there, so only the
    child/gore/aftermath cuts apply to them."""
    v = vis(f)
    if not v:
        a = aftermath_from(f)
        if a is not None and c["end"] > a:
            return [dict(c, end=float(a))] if a - c["start"] >= 15 else []
        return [c]
    if TALK_RX.search(c.get("label") or ""):
        s, e = int(c["start"]), int(min(c["end"], len(v["bad"])))
        out, cur = [], s
        for t in range(s, e):
            if v["bad"][t]:
                if t - 3 - cur >= 15:
                    out.append(dict(c, start=float(cur), end=float(t - 3)))
                cur = t + 4
        if e - cur >= 15:
            out.append(dict(c, start=float(cur), end=float(e)))
        return out
    s, e = int(c["start"]), int(min(c["end"], len(v["act"])))
    while s < e - 15 and v["dull"][s] and not v["bad"][s]:
        s += 1
    while e > s + 15 and v["dull"][e - 1] and not v["bad"][e - 1]:
        e -= 1
    # No slow lead-in: start at most LEAD_IN s before the first tense moment (agency briefings open with maps,
    # slates and minutes of silent driving)
    first = next((t for t in range(s, e) if v["act"][t] >= 2), None)
    if first is not None and first - s > LEAD_IN:
        s = first - LEAD_IN
    segs, cur = [], s
    run = slate = 0
    for t in range(s, e):
        if v["bad"][t]:
            if t - 3 - cur >= 15:
                segs.append((cur, t - 3))
            cur = t + 4
            run = slate = 0
            continue
        slate = slate + 1 if v["screen"][t] else 0
        if slate == SLATE_GAP:                  # slates go no matter how short the rest of the dead stretch is
            if t - SLATE_GAP + 1 - cur >= 15:
                segs.append((cur, t - SLATE_GAP + 1))
            cur = t + 1
            run = 0
            continue
        elif slate > SLATE_GAP:
            cur = t + 1
            run = 0
            continue
        run = run + 1 if v["dull"][t] else 0
        if run == DULL_GAP:                     # cut long dead stretches out of the middle too
            if t - DULL_GAP + 1 - cur >= 15:
                segs.append((cur, t - DULL_GAP + 1))
            cur = t + 1
        elif run > DULL_GAP:
            cur = t + 1
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
    if key in cache and not fix_note(plan):  # a re-cut request always cuts fresh (Nov 20: it reused the old cut)
        r = cache[key]
        clear = [x for c in r["clips"] if not c.get("blur") for x in clean_clip(files[c["file"]], c)]
        r["clips"] = add_blurred_tails(files, safe_clips(files, clear))
        return r
    sc = plan.get("script") or {}
    total = sum(f["duration"] for f in files)
    case = sc.get("style") == "case_story"
    # case stories (911 + bodycam + interview + verdict) run 15-25 min; the interview is the longest part
    target = min(total, 22 * 60 if case else 14 * 60)
    max_clip = 480 if case else 360
    order = ("Clips run in this order: the 911 call (label '911 Call'), then the bodycam of the response or arrest, "
             "then the police interview (label 'Interview Room'; the longest part, about half the episode: keep the "
             "suspect's own account, the lies, the evidence put to them and the moment the story changes; cut long "
             "silences, breaks and paperwork). Each clip 20s-8min. " if case else
             "Clips run in story order; each clip 20s-6min. ")
    result = None
    try:
        j = ask_llm("You edit long-form YouTube episodes from police bodycam footage, like EWU, Code Blue Cam and "
                    "Dr Insanity" + (", and case-story interrogation episodes like JCS - Criminal Psychology" if case else "")
                    + ". " + RULES,
                    describe(files) + f"\n\nEpisode: {plan.get('title')} ({sc.get('style', 'action')} style)\n"
                    f"Angle labels available: {sc.get('angle_labels') or ['Body Cam Officer 1']}\n" + redo(plan) +
                    f"Build the episode from about {target / 60:.0f} minutes of footage (less if the footage is thin; "
                    "cut dead air and stretches where the camera shows nothing but a cruiser interior). " + order +
                    "Label each clip with which camera it "
                    "is (e.g. Body Cam Officer 1, Dash Cam, Interview Room, 911 Call). Also pick a 6-12s cold open: the "
                    "most gripping VISIBLE moment, from later in the story" +
                    (" (in a case story, the interview moment where the story cracks)" if case else "") + ". "
                    'Return JSON {"cold_open":{"file":0,"start":300,"end":310},'
                    '"clips":[{"file":0,"start":0,"end":120,"label":"Body Cam Officer 1"}]}')
        clips = [c for c in (clamp(files, x, 15, max_clip) for x in j.get("clips", [])) if c]
        clips = [x for c in clips for x in clean_clip(files[c["file"]], c)]
        cold = clamp(files, j.get("cold_open") or {}, 5, 12)
        if cold and (hits_aftermath(files[cold["file"]], cold["start"], cold["end"]) if case else
                     looks_bad(files[cold["file"]], cold["start"], cold["end"], min_action=2.0, max_dull=0.2)):
            cold = None
        elif cold and case and (on_screen(files[cold["file"]], cold["start"], cold["end"]) or (0, 0, False))[2]:
            cold = None                     # interview cold opens are calm by nature; still never a child/gore frame
        if sum(c["end"] - c["start"] for c in clips) < min(360, total * 0.4):
            clips = []                      # AI cut was far too thin for the footage we have — use the fallback
        if clips:
            result = {"cold_open": cold or _cold_fallback(files, clips), "clips": clips}
        else:
            print("episode cut: AI cut empty or too thin after the safety cut; using the fallback", flush=True)
    except Exception as e:
        print(f"episode cut: AI cut failed ({str(e)[:200]}); using the fallback", flush=True)
    if not result:
        # Fallback: the active stretch of each file, run through the safety cut FIRST (slates, dead air, child/gore,
        # aftermath), then filled in story order up to its share. (Before Nov 17 it hunted one window the length
        # of the whole share; on a single 14-min file every such window held the aftermath, so it found nothing and
        # rendered the raw file: 4:45 of CBP slates + an unblurred death. Las Cruces, rejected.)
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
            left = share
            for c in clean_clip(f, {"file": i, "start": float(s), "end": float(e)}):
                if left < 15:
                    break
                c = dict(c, end=min(c["end"], c["start"] + left))
                if c["end"] - c["start"] >= 15:
                    clips.append(c)
                    left -= c["end"] - c["start"]
        if not clips:
            # never the raw file: no safe cut means no episode (the runner alerts and retries / waits for a re-cut)
            raise RuntimeError("NO SAFE CUT: every stretch of this footage is slates, dead air, a child, gore or "
                               "the aftermath")
        result = {"cold_open": _cold_fallback(files, clips), "clips": clips}
    skip = _skip_until(fix_note(plan))        # "never use anything before 2:05" (agency slate the frame check missed)
    if skip:
        result["clips"] = [dict(c, start=max(c["start"], skip)) for c in result["clips"]
                           if c["end"] - max(c["start"], skip) >= 15]
        co = result.get("cold_open") or {}
        if not co or co.get("start", 0) < skip:
            result["cold_open"] = _cold_fallback(files, result["clips"]) if result["clips"] else co
        if not result["clips"]:
            raise RuntimeError("NO SAFE CUT: nothing left after the re-cut's skip")
    result["clips"] = add_blurred_tails(files, safe_clips(files, result["clips"]))
    labels = (sc.get("angle_labels") or [])
    for n, c in enumerate(result["clips"]):
        if not c.get("label"):
            c["label"] = labels[c["file"]] if c["file"] < len(labels) else f"Body Cam Officer {c['file'] + 1}"
    # Bobby, Nov 19: each officer's camera is BODY CAM 1 / BODY CAM 2 / DASH CAM, numbered the same all episode.
    # The Maker's per-camera label is the camera's name; 911 / interview labels stay as they are.
    import camlabel
    for c in result["clips"]:
        if not camlabel.KEEP_RX.search(c.get("label") or ""):
            c.setdefault("cam", c.get("label"))
    camlabel.assign(files, result["clips"], field="label")
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
