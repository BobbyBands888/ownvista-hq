"""Media helpers for the Mac renderer: ffmpeg, probing, loudness, transcripts, narrator voice, text cards.
Everything here is free: local ffmpeg, local Kokoro voice, Groq free-tier Whisper for transcripts."""
import json
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path

from PIL import Image, ImageFilter, ImageFont

HOME = Path(os.environ.get("TENFOUR_HOME", Path.home() / "TenFourTapes"))
MODELS = HOME / "models"
FONTS = HOME / "fonts"
VOICE = os.environ.get("TENFOUR_VOICE", "am_adam")     # Bobby's pick: "voice 4"
GOLD, WHITE, RED, BG = (245, 196, 48), (255, 255, 255), (230, 40, 50), (13, 15, 20)
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".ts", ".mts", ".wmv", ".mpg", ".mpeg", ".webm", ".asf"}

ENC_V = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p", "-r", "30"]
ENC_A = ["-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2"]


# ---------------- ffmpeg ----------------
def ffmpeg_bin():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg  # bundled static ffmpeg, installed by install.sh
    return imageio_ffmpeg.get_ffmpeg_exe()

FF = None

def ff(*args, quiet=True):
    global FF
    FF = FF or ffmpeg_bin()
    cmd = [FF, "-y", "-hide_banner"] + (["-v", "error"] if quiet else []) + [str(a) for a in args]
    raw = "rawvideo" in args
    r = subprocess.run(cmd, capture_output=True, text=not raw)
    if raw:
        if r.returncode:
            raise RuntimeError("ffmpeg failed")
        return r
    if r.returncode:
        raise RuntimeError("ffmpeg failed: " + r.stderr[-1500:])
    return r


def probe(path):
    """Duration, size and audio presence, parsed from ffmpeg's own header dump (no ffprobe needed)."""
    global FF
    FF = FF or ffmpeg_bin()
    err = subprocess.run([FF, "-hide_banner", "-i", str(path)], capture_output=True, text=True).stderr
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0
    v = re.search(r"Stream #.*Video:.*?(\d{2,5})x(\d{2,5})", err)
    w, h = (int(v[1]), int(v[2])) if v else (1920, 1080)
    rot = re.search(r"rotate\s*:\s*(-?\d+)|rotation of (-?[\d.]+)", err)
    if rot and abs(int(float(rot[1] or rot[2]))) in (90, 270):
        w, h = h, w
    return {"duration": dur, "w": w, "h": h, "audio": bool(re.search(r"Stream #.*Audio:", err)), "video": bool(v)}


def wav_dur(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def loudness(path, dur):
    """RMS level (dB) for each second of the file's audio; -90 where silent/no audio."""
    try:
        r = ff("-i", path, "-vn", "-ac", "1", "-af",
               "aresample=8000,asetnsamples=8000,astats=metadata=1:reset=1,"
               "ametadata=print:key=lavfi.astats.Overall.RMS_level:file=-", "-f", "null", "-", quiet=True)
        vals = [float(x) if x not in ("-inf", "inf", "nan") else -90.0
                for x in re.findall(r"RMS_level=(-?[\d.]+|-?inf|nan)", r.stdout)]
    except Exception:
        vals = []
    n = int(dur) + 1
    return (vals + [-90.0] * n)[:n]


def visible(path, dur, samples=6):
    """Share of sampled frames that actually show a picture (dispatch audio and some exports are a black screen)."""
    lit = 0
    for k in range(samples):
        t = dur * (k + 0.5) / samples
        try:
            r = ff("-ss", round(t, 2), "-i", path, "-frames:v", "1", "-vf", "scale=64:36,format=gray",
                   "-f", "rawvideo", "-", quiet=True)
        except Exception:
            continue
        data = r.stdout.encode("latin-1", "ignore") if isinstance(r.stdout, str) else r.stdout
        if data and sum(data) / len(data) > 18:
            lit += 1
    return lit / samples


# ---------------- transcripts (Groq Whisper, free tier) ----------------
def transcribe(path, work, groq_key):
    """Timed transcript segments [{start,end,text}] or [] if unavailable. Audio is chunked to stay under upload limits."""
    if not groq_key:
        return []
    import requests
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"\W", "_", Path(path).stem)[:40]
    try:
        ff("-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "32k", "-f", "segment",
           "-segment_time", "1200", "-reset_timestamps", "1", work / f"{stem}_%03d.mp3")
    except Exception:
        return []
    segs = []
    for i, chunk in enumerate(sorted(work.glob(f"{stem}_*.mp3"))):
        off = i * 1200
        for attempt in range(3):
            try:
                with open(chunk, "rb") as f:
                    r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                                      headers={"Authorization": f"Bearer {groq_key}"},
                                      files={"file": (chunk.name, f, "audio/mpeg")},
                                      data={"model": "whisper-large-v3-turbo", "response_format": "verbose_json",
                                            "language": "en"}, timeout=300)
                if r.status_code == 429:
                    import time
                    time.sleep(20 * (attempt + 1))
                    continue
                if r.status_code < 300:
                    for s in r.json().get("segments", []):
                        t = (s.get("text") or "").strip()
                        if t and s.get("no_speech_prob", 0) < 0.8:
                            segs.append({"start": round(s["start"] + off, 1), "end": round(s["end"] + off, 1), "text": t})
                break
            except Exception:
                continue
    return segs


# ---------------- narrator (Kokoro, local) ----------------
_kokoro = None

def tts(text, out_wav, speed=1.0):
    global _kokoro
    import soundfile as sf
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(str(MODELS / "kokoro-v1.0.onnx"), str(MODELS / "voices-v1.0.bin"))
    text = re.sub(r"\s+", " ", text.replace("—", ", ").replace("–", ", ")).strip()
    audio, sr = _kokoro.create(text, voice=VOICE, speed=speed, lang="en-us")
    sf.write(str(out_wav), audio, sr)
    return wav_dur(out_wav)


# ---------------- text graphics ----------------
def font(kind="black", size=60):
    names = {"black": ["Inter-Black.ttf", "Inter-Black.otf"], "bold": ["Inter-Bold.ttf", "Inter-Bold.otf"]}[kind]
    dirs = [FONTS, Path("/usr/share/fonts/opentype/inter"), Path("/usr/share/fonts/truetype/inter")]
    for d in dirs:
        for n in names:
            if (d / n).exists():
                return ImageFont.truetype(str(d / n), size)
    for mac in ["/System/Library/Fonts/Supplemental/Arial Black.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                "/Library/Fonts/Arial Bold.ttf"]:
        if os.path.exists(mac):
            return ImageFont.truetype(mac, size)
    return ImageFont.load_default(size)


def wrap(draw, text, fnt, max_w):
    lines, cur = [], ""
    for word in str(text).split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= max_w or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def text_block(draw, text, fnt, cx, y, max_w, fill=WHITE, stroke=0, spacing=1.18, anchor_mid=True):
    """Draws wrapped, centred text starting at y; returns the y below it."""
    lh = int(fnt.size * spacing)
    for line in wrap(draw, text, fnt, max_w):
        w = draw.textlength(line, font=fnt)
        x = cx - w / 2 if anchor_mid else cx
        draw.text((x, y), line, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=(0, 0, 0))
        y += lh
    return y


def fit_font(draw, text, kind, start, max_w, max_lines):
    size = start
    while size > 24:
        f = font(kind, size)
        if len(wrap(draw, text, f, max_w)) <= max_lines:
            return f
        size -= 4
    return font(kind, size)


def blurred_still(video, t, w, h, out_png):
    """A darkened, blurred frame of the footage to sit behind narration cards."""
    try:
        ff("-ss", max(0, t), "-i", video, "-frames:v", "1", "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}",
           out_png)
        im = Image.open(out_png).convert("RGB").filter(ImageFilter.GaussianBlur(28))
        im = Image.blend(im, Image.new("RGB", (w, h), BG), 0.62)
    except Exception:
        im = Image.new("RGB", (w, h), BG)
    im.save(out_png)
    return out_png


def watermark(draw, x=18, y=18, scale=1.0):
    f = font("black", int(20 * scale))
    tw = draw.textlength("TEN-FOUR TAPES", font=f)
    draw.rectangle([x, y, x + tw + 24 * scale, y + 36 * scale], fill=(0, 0, 0, 150))
    draw.text((x + 12 * scale, y + 7 * scale), "TEN-FOUR TAPES", font=f, fill=WHITE)


def save_json(p, data):
    Path(p).write_text(json.dumps(data, indent=1))


def load_json(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default
