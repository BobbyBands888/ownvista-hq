"""RENDER BRIDGE — turns one Maker plan (a `content` row) + its footage folder into a finished video.
usage: python mac/render.py PLAN.json FOOTAGE_DIR OUT.mp4

Episode (1920x1080): cold-open hook -> title card -> short narrated setup -> raw bodycam clips with
"BODY CAM: OFFICER n" labels and brief narrator check-ins between them -> what happened next ->
comment question -> subscribe end card. Narrator never talks over bodycam audio.
Short / Reel (1080x1920): action from the first second, case badge (+ PART n), hook text, credit,
"Follow for Part n" end card."""
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


def seg_clip(src, info, s, e, W, H, out, overlays=()):
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
    if info["audio"]:
        fc.append("[0:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-15:TP=-1.5:LRA=11,"
                  f"aresample=48000,apad,atrim=0:{dur}[aout]")
        amap = "[aout]"
    else:
        args += ["-f", "lavfi", "-t", dur, "-i", "anullsrc=r=48000:cl=stereo"]
        amap = f"{len(overlays) + 1}:a"
    ff(*args, "-filter_complex", ";".join(fc), "-map", f"[{last}]", "-map", amap, *ENC_V, *ENC_A,
       "-t", dur, out)
    return out


def seg_card(card_png, out, vo_wav=None, min_dur=2.0, pad=0.7):
    dur = max(min_dur, (media.wav_dur(vo_wav) + pad) if vo_wav else min_dur)
    args = ["-loop", "1", "-t", round(dur, 2), "-i", card_png]
    if vo_wav:
        args += ["-i", vo_wav]
        af = ["-filter_complex", f"[1:a]aresample=48000,aformat=channel_layouts=stereo,loudnorm=I=-15:TP=-1.5,"
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

    # 2. title card (narrated, so there's no silent stretch)
    tc = sc.get("title_card") or job.plan.get("title") or case
    segs.append(seg_card(png_card(bg, W, H, job.p("png"), kicker="Ten-Four Tapes", title=case, body=tc if tc != case else None),
                         job.p("mp4"), job.vo(tc), min_dur=3))

    # 3. short narrated setup
    if sc.get("narration_setup"):
        segs.append(seg_card(png_card(bg, W, H, job.p("png"), body=sc["narration_setup"]), job.p("mp4"),
                             job.vo(sc["narration_setup"])))

    # 4. bodycam clips, labelled; brief narrator check-ins between them
    checks = list(sc.get("check_ins") or [])
    for n, c in enumerate(pk["clips"]):
        if n > 0 and checks and n <= len(checks):
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
    W, H = 1080, 1920
    plan, sc, pk = job.plan, job.sc, job.pick
    kind = plan["kind"]
    case = plan.get("case_name") or "Ten-Four Tapes"
    part = int(plan.get("part") or pk.get("part") or 0) if kind == "short" else 0
    path, info = job.src(pk["file"])
    hook = sc.get("hook_text") or sc.get("on_screen_text") or plan.get("title") or case
    credit = job.credit.replace("Footage: ", "Footage: ")[:70]
    ov = [(png_watermark(W, H, job.p("png"), credit=credit), 0, None),
          (png_badge(W, H, case, part, job.p("png")), 0, None),
          (png_hook(W, H, hook, job.p("png"), vertical=True), 0, 3.2)]
    segs = [seg_clip(path, info, pk["start"], pk["end"], W, H, job.p("mp4"), ov)]
    bg = media.blurred_still(path, max(0, pk["end"] - 1), W, H, job.p("png"))
    if kind == "short" and part in (1, 2):
        end_t, end_vo = f"Follow for Part {part + 1}", f"Follow for part {'two' if part == 1 else 'three'}."
    elif kind == "short":
        end_t, end_vo = "Full episode on our channel", "Watch the full episode on our channel."
    else:
        end_t, end_vo = "Follow for more cases", "Follow for more cases like this."
    segs.append(seg_card(png_card(bg, W, H, job.p("png"), kicker=case, title=end_t), job.p("mp4"),
                         job.vo(end_vo), min_dur=2.2, pad=0.5))
    concat(segs, out, job.work)


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
        LOG(f"{plan['kind']} '{plan.get('title')}' picks: {json.dumps(job.pick)[:400]}")
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        if plan["kind"] == "episode":
            build_episode(job, out)
        else:
            build_vertical(job, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    LOG(f"rendered {out} ({media.probe(out)['duration']:.0f}s)")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    render(sys.argv[1], sys.argv[2], sys.argv[3])
