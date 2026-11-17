"""POST-RENDER AUTO-CHECK — reads the FINISHED video before anyone can post it.

Why: 14 of 34 reviewed renders were rejected (Nov 17 audit). The misses were things a second look at the finished
file catches: a "LAS CRUCES SHOOTOUT" badge on a case with no shootout, a rappelling claim the source never made,
aftermath on screen. Posting can't run on autopilot until the machine itself looks at every finished video.

What it does (free: same Groq / Cloudflare vision as the picker):
  1. Samples frames across the finished video (every ~2s for Shorts/Reels, ≤60 frames for an episode, plus the
     first seconds where the badge / hook / cold open sit) into numbered contact sheets.
  2. Vision reads each sheet: every word of on-screen text, and whether a body, blood, a child's face or a broken
     frame is visible unblurred.
  3. Everything shown or said (on-screen text + the Writer's narration, title, caption) is checked against the
     case file and the lead: strong words (shootout, killed, dead…) that the sources don't support, and an LLM pass
     for any other claim the sources don't back up.
  4. Verdict: "pass" only when every check is clean AND vision read ≥90% of the frames. Anything doubtful = "hold":
     the runner sets the item back to pending with the reasons, so it waits for Bobby instead of posting.
"""
import io
import json
import os
import re
import time

import media

VISION_GAP = float(os.environ.get("TFT_VISION_GAP", "4"))   # seconds between vision calls (free-tier TPM)
MIN_READ = 0.9                                             # share of sampled frames vision must read to pass
MAX_FRAMES_EPISODE = 60

# Claims that need a source. If one is on screen / in the narration and not in the case file or lead, hold.
STRONG = re.compile(r"\b(shoot[- ]?out|shootouts?|gun ?fight|fire ?fight|shot (?:dead|and killed)|shot at|"
                    r"shooting|killed|kills?|dead|dies|died|death|fatal(?:ly)?|murder(?:ed|s)?|stabb(?:ed|ing)|"
                    r"overdos(?:e|ed)|hostage|rappell?(?:ed|ing)?|explosi(?:on|ve)s?|bomb|cartel|trafficker|"
                    r"kidnapp?(?:ed|ing)?|manslaughter|convicted|sentenced|guilty)\b", re.I)

PROMPT = """These are {n} numbered frames (red labels 1..{n} in each frame's bottom-left corner, in time order) from a FINISHED police bodycam video
that is about to be posted. For EACH numbered frame report:
- "text": every word of text the EDITOR put on screen (badges, titles, hook text, captions, cards, labels,
  "Part 1"), copied exactly as written, in reading order. "" if none. Ignore the camera's own timestamp /
  serial-number overlay and the small "Footage:" credit line.
- "body": true if a person who looks dead, dying, limp on the ground after force, or badly wounded is visible
  and NOT blurred out. When unsure, true.
- "gore": true if blood or a wound is visible and NOT blurred out.
- "child": true if a child's face is clearly visible and NOT blurred out.
- "broken": true if the frame is black, frozen, garbled or a rendering error.
Return {{"frames":[{{"n":1,"text":"","body":false,"gore":false,"child":false,"broken":false}}]}}"""


def _true(x):
    return x is True or str(x).strip().lower() in ("true", "yes", "1")


def sample_times(dur, kind):
    """Dense at the start (badge, hook, cold open), then evenly across the whole video."""
    if kind == "episode" and dur > 120:
        step = max(6.0, dur / MAX_FRAMES_EPISODE)
    else:
        step = 2.0
    ts = [0.3, 1.2, 2.4]
    t = 3.5
    while t < dur - 0.3:
        ts.append(round(t, 1))
        t += step
    if dur > 1.5:
        ts.append(round(dur - 0.8, 1))                      # the end card
    return sorted({x for x in ts if x < dur})


def sheet(path, times, vertical):
    """Numbered grid of frames as JPEG bytes. Vertical videos keep their shape so badge text stays legible."""
    from PIL import Image, ImageDraw
    w, h, cols = (270, 480, 4) if vertical else (416, 234, 3)
    rows = (len(times) + cols - 1) // cols
    img = Image.new("RGB", (cols * w, rows * h), (0, 0, 0))
    d = ImageDraw.Draw(img)
    f = media.font("black", 34)
    for k, t in enumerate(times):
        fr = media.frame(path, t, w, h)
        x, y = (k % cols) * w, (k // cols) * h
        if fr:
            img.paste(fr, (x, y))
        d.rectangle([x, y + h - 46, x + 58, y + h], fill=(230, 40, 50))      # bottom-left: badges sit at the top
        d.text((x + 12, y + h - 42), str(k + 1), font=f, fill=(255, 255, 255))
        d.rectangle([x, y, x + w - 1, y + h - 1], outline=(255, 255, 255), width=2)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=78)
    return buf.getvalue()


def _frames(j, n):
    """Per-frame dicts from a vision reply in whatever shape the model used -> {index: dict}."""
    if not isinstance(j, dict):
        return {}
    fr = j.get("frames", j.get("results", j))
    items = []
    if isinstance(fr, dict):
        items = [{**v, "n": v.get("n", k)} for k, v in fr.items() if isinstance(v, dict)]
    elif isinstance(fr, list):
        items = [v for v in fr if isinstance(v, dict)]
    out = {}
    for pos, v in enumerate(items):
        raw = v.get("n", v.get("frame"))
        m = re.search(r"\d+", str(raw)) if raw is not None else None
        k = int(m[0]) - 1 if m else pos
        if 0 <= k < n and k not in out and any(x in v for x in ("text", "body", "gore", "broken")):
            out[k] = v
    return out


def read_video(path, kind, log=print, see=None):
    """Vision pass over the finished file -> (frames list, frames sampled). Each frame: t, text, flags."""
    from agents.lib import llm
    see = see or llm.see
    info = media.probe(path)
    vertical = info["h"] > info["w"]
    times = sample_times(info["duration"], kind)
    per = 8 if vertical else 9
    got, fails = [], 0
    for k in range(0, len(times), per):
        chunk = times[k:k + per]
        if fails >= 4:
            break                                           # vision is down: stop, the verdict will be "hold"
        try:
            if k:
                time.sleep(VISION_GAP)
            j = see(PROMPT.format(n=len(chunk)), sheet(path, chunk, vertical),
                    check=lambda r, c=len(chunk): len(_frames(r, c)) >= max(1, c // 2))
            for n, fr in _frames(j, len(chunk)).items():
                got.append({"t": chunk[n], "text": str(fr.get("text") or "").strip()[:200],
                            "body": _true(fr.get("body")), "gore": _true(fr.get("gore")),
                            "child": _true(fr.get("child")), "broken": _true(fr.get("broken"))})
            fails = 0
        except Exception as e:
            fails += 1
            log(f"autocheck vision error: {str(e)[:200]}")
            time.sleep(15 * fails)
    return sorted(got, key=lambda f: f["t"]), len(times), info["duration"]


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def spoken_and_written(it, script):
    """Every line the Writer/Maker put in this video or its post: title, hook, badge (case name), narration, caption."""
    sc = script if isinstance(script, dict) else {}
    parts = {"title": it.get("title"), "case name / badge": it.get("case_name"), "caption": it.get("description")}
    for k in ("hook_text", "on_screen_text", "cold_open_hook", "title_card", "caption", "question", "intro_vo",
              "outcome_vo", "narration_setup", "what_happened_next", "thumbnail_text"):
        if sc.get(k):
            parts[k] = sc[k]
    for k in ("check_ins", "thumbnail_texts"):
        if isinstance(sc.get(k), list):
            parts[k] = " | ".join(str(x) for x in sc[k])
    return {k: str(v) for k, v in parts.items() if v}


def source_text(lead, facts):
    return " ".join([lead.get("title") or "", lead.get("summary") or "", lead.get("notes") or "",
                     json.dumps(facts or {}, default=str)])


def strong_word_problems(lines, sources):
    """Deterministic: a strong claim word in the video/post that appears nowhere in the sources."""
    src = _norm(sources)
    out = []
    for where, text in lines:
        for m in STRONG.finditer(text or ""):
            word = _norm(m.group(0))
            if re.search(r"out|fight", word):            # "shootout" needs a shootout, not just "a shooting"
                ok = word.replace(" ", "") in src.replace(" ", "") or "exchange of gunfire" in src \
                    or "exchanged gunfire" in src or "exchanged fire" in src
            else:
                ok = word.split()[0][:5] in src
            if not ok:
                out.append(f'"{m.group(0)}" in {where} ("{text[:60]}") is not in the case file or lead')
    return list(dict.fromkeys(out))


def claim_problems(lines, lead, facts, ask=None):
    """LLM pass: any claim in what's shown/said that the sources don't back up. Fails closed (an error = a problem)."""
    from agents.lib import llm
    ask = ask or llm.ask
    try:
        res = ask(
            "You fact-check a police bodycam video before it is posted. The SOURCES are the only facts we have. "
            "List every statement in the VIDEO TEXT that the sources do not support: an outcome (arrest, charges, "
            "conviction, death, injury), a weapon, shots fired, a 'shootout', drugs, amounts, names, ages, places, "
            "dates, or any dramatic detail that isn't in the sources. Questions and generic hype ('watch what "
            "happens', 'follow for part 2') are fine. Charges stated as convictions are a problem. Be strict but "
            "don't flag wording that only restates the sources.",
            "SOURCES:\n" + source_text(lead, facts)[:6000] + "\n\nVIDEO TEXT:\n" +
            json.dumps(dict(lines), ensure_ascii=False)[:6000] +
            '\n\nReturn JSON {"problems":[{"text":"the exact words","why":"what the sources say instead"}]}',
            max_tokens=900, temperature=0.1)
        return [f'"{p.get("text", "")[:80]}": {p.get("why", "")[:120]}' for p in (res.get("problems") or [])
                if isinstance(p, dict) and p.get("text")]
    except Exception as e:
        return [f"fact-check couldn't run ({str(e)[:120]})"]


def check(path, it, lead, facts, script=None, log=print, see=None, ask=None):
    """-> {"verdict": "pass"|"hold", "problems": [...], "read": n, "sampled": n, "on_screen": [...]}"""
    problems = []
    frames, sampled, dur = read_video(path, it.get("kind"), log=log, see=see)
    read = len(frames)
    if sampled and read < sampled * MIN_READ:
        problems.append(f"vision read only {read}/{sampled} frames, so the video wasn't fully checked")
    bad = lambda key: [f["t"] for f in frames if f[key]]
    for key, what in (("body", "a person who looks dead/limp/badly hurt, not blurred"),
                      ("gore", "blood or a wound, not blurred"),
                      ("child", "a child's face, not blurred")):
        ts = bad(key)
        if ts:
            problems.append(f"{what} at {', '.join(f'{t:.0f}s' for t in ts[:6])}")
    broken = bad("broken")
    if len(broken) > max(2, 0.15 * max(read, 1)):
        problems.append(f"{len(broken)} black/broken frames (e.g. {', '.join(f'{t:.0f}s' for t in broken[:4])})")
    # what's on screen, de-duplicated in order of appearance
    seen, on_screen = set(), []
    for f in frames:
        key = _norm(f["text"])
        if key and key not in seen:
            seen.add(key)
            on_screen.append({"t": f["t"], "text": f["text"]})
    lines = [(f"on-screen text at {o['t']:.0f}s", o["text"]) for o in on_screen]
    lines += list(spoken_and_written(it, script).items())
    src = source_text(lead, facts)
    problems += strong_word_problems(lines, src)
    problems += claim_problems(lines, lead, facts, ask=ask)
    problems = list(dict.fromkeys(problems))
    return {"verdict": "hold" if problems else "pass", "problems": problems[:12], "read": read,
            "sampled": sampled, "on_screen": on_screen[:40]}
