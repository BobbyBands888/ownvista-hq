"""RENDER BRIDGE — turns one Maker plan (a `content` row) + its footage folder into a finished video.
usage: python mac/render.py PLAN.json FOOTAGE_DIR OUT.mp4

Episode (1920x1080): cold-open hook -> title card -> short narrated setup -> raw bodycam clips with
"BODY CAM: OFFICER n" labels and brief narrator check-ins between them -> what happened next ->
comment question -> subscribe end card. Narrator never talks over bodycam audio.
Short / Reel (1080x1920): action from the first second with the narrator setting it up over the opening seconds
(bodycam audio low underneath), case badge (+ PART n on Shorts only), hook text, credit, narrated "how it ended",
"Follow for Part n" end card on Shorts; Reels are standalone single moments ending "Follow for more cases"."""
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from PIL import Image, ImageDraw  # noqa: E402

import media  # noqa: E402
import picker  # noqa: E402
from media import GOLD, RED, WHITE, ENC_A, ENC_V, ff  # noqa: E402

LOG = print


# ---------------- graphics ----------------
def canvas(W, H):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def png_watermark(W, H, path, credit=None):
    im, d = canvas(W, H)
    media.watermark(d, scale=1.45 if W > H else 1.3)
    if credit:
        f = media.font("bold", 22 if W > H else 30)
        tw = d.textlength(credit, font=f)
        x, y = (W - tw - 30, H - 52) if W > H else ((W - tw) / 2, H - 120)
        d.rectangle([x - 12, y - 8, x + tw + 12, y + f.size + 10], fill=(0, 0, 0, 150))
        d.text((x, y), credit, font=f, fill=WHITE)
    im.save(path)
    return path


def png_label(W, H, label, path):
    im, d = canvas(W, H)
    txt = label.upper() if label.upper().startswith(("BODY CAM", "DASH CAM", "911", "INTERVIEW")) else f"BODY CAM: {label.upper()}"
    txt = txt.replace("BODY CAM ", "BODY CAM: ", 1) if txt.startswith("BODY CAM ") else txt
    f = media.font("black", 34)
    tw = d.textlength(txt, font=f)
    x, y = 60, H - 150
    d.rectangle([x, y, x + tw + 80, y + 64], fill=(0, 0, 0, 185))
    d.rectangle([x, y, x + 8, y + 64], fill=GOLD)
    d.ellipse([x + 26, y + 24, x + 42, y + 40], fill=RED)
    d.text((x + 56, y + 13), txt, font=f, fill=WHITE)
    im.save(path)
    return path


def png_hook(W, H, text, path, vertical=False):
    im, d = canvas(W, H)
    maxw = W - (120 if vertical else 360)
    f = media.fit_font(d, text.upper(), "black", 92 if vertical else 84, maxw, 4 if vertical else 2)
    lines = media.wrap(d, text.upper(), f, maxw)
    lh = int(f.size * 1.15)
    y = (1330 if vertical else H - 120 - lh * len(lines))
    for n, line in enumerate(lines):
        w = d.textlength(line, font=f)
        d.text(((W - w) / 2, y), line, font=f, fill=GOLD if n == 0 else WHITE, stroke_width=6, stroke_fill=(0, 0, 0))
        y += lh
    im.save(path)
    return path


def png_badge(W, H, case, part, path):
    im, d = canvas(W, H)
    f = media.fit_font(d, case.upper(), "black", 64, W - 160, 1)
    tw = d.textlength(case.upper(), font=f)
    y = 230
    d.rounded_rectangle([(W - tw) / 2 - 36, y, (W + tw) / 2 + 36, y + f.size + 40], 18, fill=GOLD)
    d.text(((W - tw) / 2, y + 16), case.upper(), font=f, fill=(10, 10, 10))
    if part:
        pf = media.font("black", 46)
        pt = f"PART {part}"
        pw = d.textlength(pt, font=pf)
        y2 = y + f.size + 60
        d.rounded_rectangle([(W - pw) / 2 - 26, y2, (W + pw) / 2 + 26, y2 + 74], 14, fill=(0, 0, 0, 200))
        d.text(((W - pw) / 2, y2 + 10), pt, font=pf, fill=WHITE)
    im.save(path)
    return path


def png_card(bg_png, W, H, path, kicker=None, title=None, body=None, footer=None):
    im = Image.open(bg_png).convert("RGBA").resize((W, H))
    d = ImageDraw.Draw(im)
    vertical = H > W
    maxw = W - (140 if vertical else 360)
    blocks = []
    if kicker:
        blocks.append(("kicker", kicker.upper(), media.font("black", 40 if vertical else 40), GOLD))
    if title:
        blocks.append(("title", title.upper(), media.fit_font(d, title.upper(), "black", 110 if vertical else 124, maxw, 3), WHITE))
    if body:
        blocks.append(("body", body, media.fit_font(d, body, "bold", 64 if vertical else 66, maxw, 5), WHITE))
    heights = [len(media.wrap(d, t, f, maxw)) * int(f.size * 1.2) + 34 for _, t, f, _ in blocks]
    y = (H - sum(heights)) / 2
    for (kind, t, f, col), h in zip(blocks, heights):
        if kind == "kicker":
            tw = d.textlength(t, font=f)
            d.rectangle([(W - tw) / 2 - 20, y - 8, (W + tw) / 2 + 20, y + f.size + 14], fill=(0, 0, 0, 170))
        media.text_block(d, t, f, W / 2, y, maxw, fill=col, stroke=3 if kind != "kicker" else 0)
        y += h
    if footer:
        ff_ = media.font("bold", 30 if vertical else 26)
        tw = d.textlength(footer, font=ff_)
        d.text(((W - tw) / 2, H - (160 if vertical else 80)), footer, font=ff_, fill=(220, 220, 220))
    media.watermark(d, scale=1.45 if W > H else 1.3)
    im.convert("RGB").save(path)
    return path


# ---------------- segments ----------------
def frame_filter(info, W, H):
    """Fit any source (landscape or vertical) into the output frame over a blurred fill of itself."""
    src_vertical = info["h"] > info["w"]
    out_vertical = H > W
    fg = f"scale={W}:{H}:force_original_aspect_ratio=decrease"
    if out_vertical and not src_vertical:
        fg = f"crop=ih*4/3:ih,scale={W}:-2"          # bigger picture on phones
    if out_vertical == src_vertical:
        fg = f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    # blur at quarter size then scale up: same look, several times faster on 2-core cloud runners
    return (f"[0:v]split[a][b];[a]scale={W // 4}:{H // 4}:force_original_aspect_ratio=increase,crop={W // 4}:{H // 4},"
            f"boxblur=6:1,eq=brightness=-0.28,scale={W}:{H}[bg];[b]{fg}[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,"
            f"setsar=1,fps=30,format=yuv420p[base]")


CAM_AF = ("aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:channel_layouts=stereo,"
          "dynaudnorm=f=200:g=15:p=0.9:m=12,alimiter=limit=0.89,volume=-6dB")
CAM_AF_SAFE = "aresample=48000:async=1:first_pts=0,aformat=sample_fmts=fltp:channel_layouts=stereo,volume=-3dB"


def seg_clip(src, info, s, e, W, H, out, overlays=(), vo_wav=None):
    """One bodycam clip. With vo_wav, the narrator talks over the opening seconds and the bodycam audio
    drops low underneath (never muted, so viewers still hear the scene), then comes back to full level."""
    dur = round(e - s, 2)
    args = ["-ss", s, "-t", dur, "-i", src]
    for png, *_ in overlays:
        args += ["-loop", "1", "-t", dur, "-i", png]
    fc = [frame_filter(info, W, H)]
    last = "base"
    for n, (png, t0, t1) in enumerate(overlays, 1):
        en = f":enable='between(t,{t0},{t1})'" if t1 is not None else ""
        fc.append(f"[{last}][{n}:v]overlay=0:0:format=auto{en}[v{n}]")
        last = f"v{n}"
    nxt = len(overlays) + 1
    if info["audio"]:
        cam = "[0:a]"
    else:
        args += ["-f", "lavfi", "-t", dur, "-i", "anullsrc=r=48000:cl=stereo"]
        cam, nxt = f"[{nxt}:a]", nxt + 1
    if vo_wav:
        args += ["-i", vo_wav]
        vd = round(min(media.wav_dur(vo_wav) + 0.6, dur), 2)
        vo_chain = (f"[{nxt}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,loudnorm=I=-14:TP=-1.5,"
                    f"aresample=48000,adelay=300|300,apad,atrim=0:{dur}[vo]")

    def run(cam_af):
        a = [f"{cam}{cam_af},aresample=48000,apad,atrim=0:{dur}" + ("[cam]" if vo_wav else "[aout]")]
        if vo_wav:
            a += [f"[cam]volume=0.16:enable='between(t,0,{vd})'[camd]", vo_chain,
                  "[camd][vo]amix=inputs=2:normalize=0:duration=first,alimiter=limit=0.95,"
                  "aformat=sample_fmts=fltp:channel_layouts=stereo[aout]"]
        ff(*args, "-filter_complex", ";".join(fc + a), "-map", f"[{last}]", "-map", "[aout]", *ENC_V, *ENC_A,
           "-t", dur, out)

    try:
        run(CAM_AF if info["audio"] else "anull")
    except RuntimeError as err:                 # odd source audio can break the loudness chain: retry plain
        LOG(f"clip audio retry ({str(err)[-120:]})")
        run(CAM_AF_SAFE if info["audio"] else "anull")
    return out


def seg_card(card_png, out, vo_wav=None, min_dur=2.0, pad=0.7, max_dur=None):
    dur = max(min_dur, (media.wav_dur(vo_wav) + pad) if vo_wav else min_dur)
    if max_dur:
        dur = min(dur, max_dur)
    args = ["-loop", "1", "-t", round(dur, 2), "-i", card_png]
    if vo_wav:
        args += ["-i", vo_wav]
        af = ["-filter_complex", f"[1:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,loudnorm=I=-15:TP=-1.5,"
              f"aresample=48000,adelay=250|250,apad,atrim=0:{round(dur, 2)}[a]", "-map", "0:v", "-map", "[a]"]
    else:
        args += ["-f", "lavfi", "-t", round(dur, 2), "-i", "anullsrc=r=48000:cl=stereo"]
        af = ["-map", "0:v", "-map", "1:a"]
    ff(*args, *af, "-vf", "fps=30,format=yuv420p,setsar=1", *ENC_V, *ENC_A, "-t", round(dur, 2), out)
    return out


def concat(parts, out, work):
    lst = Path(work) / "concat.txt"
    lst.write_text("".join(f"file '{Path(p).resolve()}'\n" for p in parts))
    tmp = Path(work) / "joined.mp4"
    ff("-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", tmp)
    ff("-i", tmp, "-c", "copy", "-movflags", "+faststart", out)


# ---------------- builds ----------------
class Job:
    def __init__(self, plan, folder, work):
        self.plan, self.folder, self.work = plan, Path(folder), Path(work)
        self.sc = plan.get("script") or {}
        self.n = 0
        from agents.lib import config
        self.files = picker.analyse(folder, config.GROQ_API_KEY, log=LOG)
        self.pick = picker.picks_for(folder, self.files, plan)
        self.credit = (plan.get("source_credit") or "").strip()

    def p(self, ext):
        self.n += 1
        return str(self.work / f"{self.n:03d}.{ext}")

    def src(self, i):
        return str(self.folder / self.files[i]["path"]), self.files[i]

    def vo(self, text):
        if not text:
            return None
        w = self.p("wav")
        media.tts(text, w)
        return w


def build_episode(job, out):
    W, H = 1920, 1080
    sc, pk = job.sc, job.pick
    case = job.plan.get("case_name") or "Ten-Four Tapes"
    segs = []
    wm = png_watermark(W, H, job.p("png"))
    wm_credit = png_watermark(W, H, job.p("png"), credit=job.credit)

    # 1. cold open with hook text
    co = pk["cold_open"]
    path, info = job.src(co["file"])
    hook = sc.get("cold_open_hook") or job.plan.get("title") or case
    segs.append(seg_clip(path, info, co["start"], co["end"], W, H, job.p("mp4"),
                         [(wm, 0, None), (png_hook(W, H, hook, job.p("png")), 0, None)]))
    first_path, first_info = job.src(pk["clips"][0]["file"])
    bg = media.blurred_still(first_path, pk["clips"][0]["start"] + 3, W, H, job.p("png"))

    # 2. title card: 3 seconds max (packaging rule). Narrated so there's no silent stretch, but only with a line
    # that fits; a longer title_card line is read on the setup card instead.
    tc = sc.get("title_card") or job.plan.get("title") or case
    tc_vo = job.vo(tc)
    spill = None
    if tc_vo and media.wav_dur(tc_vo) > TITLE_CARD_MAX - 0.5:
        spill = tc if tc != case else None
        tc_vo = job.vo(case)
        if media.wav_dur(tc_vo) > TITLE_CARD_MAX - 0.5:
            tc_vo = None
    segs.append(seg_card(png_card(bg, W, H, job.p("png"), kicker="Ten-Four Tapes", title=case,
                                  body=tc if tc != case and not spill else None),
                         job.p("mp4"), tc_vo, min_dur=2.5, pad=0.4, max_dur=TITLE_CARD_MAX))
    if spill and sc.get("narration_setup") and spill.lower() not in sc["narration_setup"].lower():
        sc["narration_setup"] = spill.rstrip(".") + ". " + sc["narration_setup"]

    # 3. short narrated setup
    if sc.get("narration_setup"):
        segs.append(seg_card(png_card(bg, W, H, job.p("png"), body=sc["narration_setup"]), job.p("mp4"),
                             job.vo(sc["narration_setup"])))

    # 4. bodycam clips, labelled; brief narrator check-ins between them
    checks = list(sc.get("check_ins") or [])
    for n, c in enumerate(pk["clips"]):
        if n > 0 and checks and n <= len(checks) and str(checks[n - 1]).strip():
            line = checks[n - 1]
            path_b, _ = job.src(c["file"])
            cbg = media.blurred_still(path_b, c["start"] + 2, W, H, job.p("png"))
            segs.append(seg_card(png_card(cbg, W, H, job.p("png"), body=line), job.p("mp4"), job.vo(line)))
        path, info = job.src(c["file"])
        ov = [(wm_credit if n == 0 else wm, 0, None), (png_label(W, H, c.get("label") or "Body Cam", job.p("png")), 0, 5)]
        segs.append(seg_clip(path, info, c["start"], c["end"], W, H, job.p("mp4"), ov))
        LOG(f"clip {n + 1}/{len(pk['clips'])} done")

    # 5. outro: what happened next, one comment question, subscribe end card
    last_path, _ = job.src(pk["clips"][-1]["file"])
    obg = media.blurred_still(last_path, max(0, pk["clips"][-1]["end"] - 3), W, H, job.p("png"))
    if sc.get("what_happened_next"):
        segs.append(seg_card(png_card(obg, W, H, job.p("png"), kicker="What happened next", body=sc["what_happened_next"]),
                             job.p("mp4"), job.vo("What happened next. " + sc["what_happened_next"])))
    if sc.get("comment_question"):
        segs.append(seg_card(png_card(obg, W, H, job.p("png"), kicker="Tell us in the comments", body=sc["comment_question"]),
                             job.p("mp4"), job.vo(sc["comment_question"])))
    segs.append(seg_card(png_card(obg, W, H, job.p("png"), kicker="Subscribe", title="Ten-Four Tapes",
                                  body="Real bodycam. The full story.", footer=job.credit),
                         job.p("mp4"), job.vo("Subscribe to Ten-Four Tapes for the full story on every case."), min_dur=4))
    concat(segs, out, job.work)


def build_vertical(job, out):
    """Vertical Short / Reel: narrator sets it up over the opening seconds (who + why police were there) while the
    bodycam keeps playing underneath, raw bodycam audio after that, then a narrated "how it ended" + follow card."""
    W, H = 1080, 1920
    plan, sc, pk = job.plan, job.sc, job.pick
    kind = plan["kind"]
    case = plan.get("case_name") or "Ten-Four Tapes"
    part = int(plan.get("part") or pk.get("part") or 0) if kind == "short" else 0
    path, info = job.src(pk["file"])
    hook = sc.get("hook_text") or sc.get("on_screen_text") or plan.get("title") or case
    credit = job.credit.replace("Footage: ", "Footage: ")[:70]
    intro = (sc.get("intro_vo") or "").strip()
    if kind == "short" and part > 1:
        intro = ""                                  # Parts 2/3 pick up the story; only Part 1 is set up
    intro_wav = job.vo(intro) if intro else None
    hook_end = max(3.2, round(media.wav_dur(intro_wav) + 0.6, 1)) if intro_wav else 3.2
    ov = [(png_watermark(W, H, job.p("png"), credit=credit), 0, None),
          (png_badge(W, H, case, part, job.p("png")), 0, None),
          (png_hook(W, H, hook, job.p("png"), vertical=True), 0, hook_end)]
    segs = [seg_clip(path, info, pk["start"], pk["end"], W, H, job.p("mp4"), ov, vo_wav=intro_wav)]
    bg = media.blurred_still(path, max(0, pk["end"] - 1), W, H, job.p("png"))
    if kind == "short" and part in (1, 2):
        end_t, end_vo = f"Follow for Part {part + 1}", f"Follow for part {'two' if part == 1 else 'three'}."
    elif kind == "short" and plan.get("episode_planned", True):
        end_t, end_vo = "Full episode on our channel", "Watch the full episode on our channel."
    else:
        end_t, end_vo = "Follow for more cases", "Follow for more cases like this."
    outcome = (sc.get("outcome_vo") or "").strip()
    if outcome and not (kind == "short" and part in (1, 2)):   # the ending goes on the last part / the Reel
        segs.append(seg_card(png_card(bg, W, H, job.p("png"), kicker="How it ended", body=outcome), job.p("mp4"),
                             job.vo(outcome), min_dur=3, pad=0.6))
    segs.append(seg_card(png_card(bg, W, H, job.p("png"), kicker=case, title=end_t), job.p("mp4"),
                         job.vo(end_vo), min_dur=2.2, pad=0.5))
    concat(segs, out, job.work)


# ---------------- YouTube thumbnails (3 variants for Test & Compare) ----------------
THUMB_W, THUMB_H = 1280, 720
THUMB_ZOOM = 1.35            # crop in so the subject fills the frame (bigger subjects read on a phone)
TITLE_CARD_MAX = 3.0         # seconds: the title card never holds the viewer longer than this
SAFE_VIEWS = ("outside", "road_ahead", "indoor")
MOMENT_GAP_S = 20            # variants come from different peaks, not neighbouring frames


def thumb_moments(job, k=3):
    """Up to k (file index, seconds) of the strongest SAFE frames inside the episode's cut, each from a different
    peak: highest vision action, never a frame tagged child or gore. Without vision data: loudest peaks."""
    pk = job.pick
    wins = [pk["cold_open"]] + list(pk.get("clips") or [])
    cands = []
    for w in wins:
        f = job.files[w["file"]]
        for v in f.get("vision") or []:
            if not (w["start"] + 1 <= v["t"] <= w["end"] - 1) or v.get("child") or v.get("gore"):
                continue
            score = (v.get("action") or 0) * 10 + (3 if v.get("view") in SAFE_VIEWS else -20)
            if score >= 20:                          # action 2+ in a usable view
                cands.append((score, w["file"], v["t"]))
        for s_, _ in picker.loud_peaks(f, 10):       # audio peaks fill in when vision is thin
            t = s_ + 2
            if w["start"] + 1 <= t <= w["end"] - 1 and not picker.looks_bad(f, max(0, t - 1), t + 1):
                cands.append((15, w["file"], t))
    cands.sort(key=lambda c: -c[0])
    out = []
    for _, i, t in cands:
        if all(i != j or abs(t - u) >= MOMENT_GAP_S for j, u in out):
            out.append((i, t))
        if len(out) == k:
            break
    if not out:
        co = pk["cold_open"]
        out = [(co["file"], (co["start"] + co["end"]) / 2)]
    return out


def anchor_cold_open(job):
    """The cold open shows the exact moment on thumbnail A: re-centre it on the #1 thumbnail frame (that frame
    lands ~6s in). Keeps the picker's cold open if the new window would include unsafe or dead frames."""
    if job.plan.get("kind") != "episode" or not job.pick:
        return
    i, t = thumb_moments(job, 1)[0]
    co = job.pick["cold_open"]
    if co["file"] == i and co["start"] + 1 <= t <= co["end"] - 1:
        job.thumb_anchor = (i, t)
        return
    f = job.files[i]
    s = max(0.0, t - 6)
    e = min(f["duration"], s + 10)
    s = max(0.0, e - 10)
    if e - s >= 5 and not picker.looks_bad(f, s, e, min_action=1.0, max_dull=0.3):
        job.pick["cold_open"] = {"file": i, "start": round(s, 2), "end": round(e, 2)}
        LOG(f"cold open moved to file {i} {s:.0f}-{e:.0f}s so it shows thumbnail A's moment")
        job.thumb_anchor = (i, t)


def _thumb_text(job, n):
    texts = [str(x) for x in (job.sc.get("thumbnail_texts") or []) if str(x).strip()]
    if job.sc.get("thumbnail_text") and job.sc["thumbnail_text"] not in texts:
        texts.insert(0, job.sc["thumbnail_text"])
    if not texts:
        texts = [job.plan.get("case_name") or ""]
    return " ".join(texts[n % len(texts)].upper().split()[:3])     # fewer words: 3 max


def build_thumbnail(job, out_jpg, moment=None, text=None):
    """1280x720 JPEG under 2MB: punched-up action frame zoomed so the subject is big, dark fade behind 2-3 big
    stroked words (last word gold), red BODY CAM tag, channel mark."""
    from PIL import ImageEnhance, ImageFilter
    i, t = moment or thumb_moments(job, 1)[0]
    path, _ = job.src(i)
    raw = job.p("png")
    zw, zh = int(THUMB_W * THUMB_ZOOM), int(THUMB_H * THUMB_ZOOM)
    # zoom in, keep the frame's centre-right (the subject side; text sits on the left)
    media.ff("-ss", round(max(0, t), 2), "-i", path, "-frames:v", "1", "-vf",
             f"scale={zw}:{zh}:force_original_aspect_ratio=increase,"
             f"crop={THUMB_W}:{THUMB_H}:(iw-{THUMB_W})*0.62:(ih-{THUMB_H})*0.45", raw)
    im = Image.open(raw).convert("RGB")
    im = ImageEnhance.Contrast(im).enhance(1.3)
    im = ImageEnhance.Color(im).enhance(1.3)
    im = ImageEnhance.Sharpness(im).enhance(1.6)
    fade = Image.new("L", (THUMB_W, THUMB_H), 0)
    fd = ImageDraw.Draw(fade)
    for x in range(THUMB_W):
        fd.line([(x, 0), (x, THUMB_H)], fill=int(200 * max(0.0, 1 - x / (THUMB_W * 0.5)) ** 1.4))
    im = Image.composite(Image.new("RGB", im.size, (0, 0, 0)), im, fade)
    vig = Image.new("L", im.size, 0)
    ImageDraw.Draw(vig).ellipse([-200, -160, THUMB_W + 200, THUMB_H + 160], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(120))
    im = Image.composite(im, Image.new("RGB", im.size, (0, 0, 0)), vig)
    d = ImageDraw.Draw(im)

    text = text if text is not None else _thumb_text(job, 0)
    words = text.split()
    if text:
        maxw = int(THUMB_W * 0.46)                   # text stays on the left ~half; the subject owns the rest
        f = media.fit_font(d, text, "black", 170, maxw, 2)
        lines = media.wrap(d, text, f, maxw)
        lh = int(f.size * 1.02)
        y = (THUMB_H - lh * len(lines)) // 2 + 20
        last = words[-1]
        for n, line in enumerate(lines):
            x = 52
            if n == len(lines) - 1 and len(words) > 1 and line.endswith(last):
                head = line[: -len(last)]
                d.text((x, y), head, font=f, fill=WHITE, stroke_width=10, stroke_fill=(0, 0, 0))
                d.text((x + d.textlength(head, font=f), y), last, font=f, fill=GOLD, stroke_width=10, stroke_fill=(0, 0, 0))
            else:
                d.text((x, y), line, font=f, fill=WHITE, stroke_width=10, stroke_fill=(0, 0, 0))
            y += lh
    tf = media.font("black", 38)
    tag = "BODY CAM"
    tw = d.textlength(tag, font=tf)
    d.rectangle([40, 36, 40 + tw + 84, 36 + 66], fill=RED)
    d.ellipse([62, 58, 84, 80], fill=WHITE)
    d.text((100, 47), tag, font=tf, fill=WHITE)
    mf = media.font("black", 26)
    mark = "TEN-FOUR TAPES"
    mw = d.textlength(mark, font=mf)
    d.rectangle([THUMB_W - mw - 70, THUMB_H - 74, THUMB_W - 30, THUMB_H - 28], fill=(0, 0, 0))
    d.rectangle([THUMB_W - mw - 70, THUMB_H - 74, THUMB_W - mw - 62, THUMB_H - 28], fill=GOLD)
    d.text((THUMB_W - mw - 50, THUMB_H - 68), mark, font=mf, fill=WHITE)
    q = 90
    while True:
        im.save(out_jpg, "JPEG", quality=q, optimize=True)
        if Path(out_jpg).stat().st_size < 1_900_000 or q <= 60:
            break
        q -= 10
    LOG(f"thumbnail {Path(out_jpg).name}: file {i} at {t:.0f}s, text '{text}'")
    return out_jpg


def build_thumbnails(job, out_base):
    """A/B/C for YouTube Test & Compare. A = the cold-open moment; B and C = other peaks in the episode, each with
    its own 2-3 words. Returns the paths that built (A first)."""
    moments = thumb_moments(job, 3)
    anchor = getattr(job, "thumb_anchor", None)
    if anchor:
        moments = [anchor] + [m for m in moments if m[0] != anchor[0] or abs(m[1] - anchor[1]) >= MOMENT_GAP_S][:2]
    paths = []
    for n, (m, tag) in enumerate(zip(moments, ("thumb", "thumbB", "thumbC"))):
        try:
            paths.append(build_thumbnail(job, str(Path(out_base).with_suffix(f".{tag}.jpg")), m, _thumb_text(job, n)))
        except Exception as e:
            LOG(f"thumbnail {tag} error: {str(e)[:200]}")
    return paths


def render(plan_path, footage, out):
    plan = json.loads(Path(plan_path).read_text())
    if isinstance(plan.get("script"), str):
        try:
            plan["script"] = json.loads(plan["script"])
        except Exception:
            plan["script"] = {}
    work = Path(tempfile.mkdtemp(prefix="tft_render_"))
    try:
        job = Job(plan, footage, work)
        total = sum(f["duration"] for f in job.files)
        part = int(plan.get("part") or 1)
        # Don't stretch thin footage: no 1-minute "episodes", no Part 3 that repeats Part 1
        if (plan["kind"] == "episode" and total < 180) or (plan["kind"] == "short" and total < 40 * part):
            print(f"NOT ENOUGH FOOTAGE: {total:.0f}s of video for a {plan['kind']}{' part ' + str(part) if plan['kind'] == 'short' else ''}")
            sys.exit(3)
        if plan["kind"] == "reel" and not job.pick:
            # every 24s+ stretch with visible action is already in another Reel of this case
            print("NOT ENOUGH FOOTAGE: no fresh moment left for another standalone Reel of this case")
            sys.exit(3)
        anchor_cold_open(job)                           # before the Writer, so the hook matches the new cold open
        import writer
        written = writer.write(job, log=LOG)            # words are written from the locked cut, not the plan
        LOG(f"{plan['kind']} '{plan.get('title')}' picks: {json.dumps(job.pick)[:400]}")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        thumb, thumbs = None, []
        if plan["kind"] == "episode":
            build_episode(job, out)
            try:                                    # a thumbnail problem never blocks the episode
                thumbs = build_thumbnails(job, out)
                thumb = thumbs[0] if thumbs else None
            except Exception as e:
                LOG(f"thumbnail error: {str(e)[:200]}")
        else:
            build_vertical(job, out)
        # what the Writer put on screen, for the runner to save back to the plan (dashboard + captions)
        cut = None
        if plan["kind"] == "reel":                  # saved on the plan so the case's other Reels avoid these seconds
            cut = {"path": job.files[job.pick["file"]]["path"], "start": job.pick["start"], "end": job.pick["end"]}
        Path(str(out) + ".script.json").write_text(json.dumps({"script": job.sc, "written": bool(written), "cut": cut, "thumb": thumb, "thumbs": thumbs,
                                                                "fixed": written.get("problems") or []}, default=str))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    LOG(f"rendered {out} ({media.probe(out)['duration']:.0f}s)")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    render(sys.argv[1], sys.argv[2], sys.argv[3])
