"""Mix Ten-Four Tapes narrator (Kokoro am_adam) over a built reel; camera audio ducks under each line.
Usage: python3 add_vo.py in.mp4 vo.json out.mp4   vo.json = [{"at": seconds, "text": "..."}]"""
import json, subprocess, sys, os, tempfile
import soundfile as sf
from kokoro_onnx import Kokoro
src, spec, out = sys.argv[1:4]
lines = json.load(open(spec))
k = Kokoro("/home/claude/models/kokoro-v1.0.onnx", "/home/claude/models/voices-v1.0.bin")
tmp = tempfile.mkdtemp(); wavs = []
dur = float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src]))
for i, l in enumerate(lines):
    a, sr = k.create(l["text"], voice="am_adam", speed=l.get("speed", 1.05), lang="en-us")
    p = os.path.join(tmp, f"v{i}.wav"); sf.write(p, a, sr); d = len(a) / sr
    if l["at"] + d > dur + 0.05: print(f"WARN line {i} runs past end ({l['at']+d:.1f}s > {dur:.1f}s)")
    if i + 1 < len(lines) and l["at"] + d > lines[i + 1]["at"]: print(f"WARN line {i} overlaps next ({l['at']+d:.1f} > {lines[i+1]['at']})")
    wavs.append((p, l["at"], d))
duck = "*".join(f"(1-0.75*between(t,{at-0.15:.2f},{at+d+0.25:.2f}))" for _, at, d in wavs)
fc = [f"[0:a]volume='{duck}':eval=frame[cam]"]
for i, (p, at, d) in enumerate(wavs):
    fc.append(f"[{i+1}:a]aresample=48000,aformat=channel_layouts=stereo,adelay={int(at*1000)}|{int(at*1000)},volume=1.6[n{i}]")
fc.append("[cam]" + "".join(f"[n{i}]" for i in range(len(wavs))) + f"amix=inputs={len(wavs)+1}:normalize=0:duration=first,alimiter=limit=0.92[a]")
cmd = ["ffmpeg", "-v", "error", "-y", "-i", src] + sum([["-i", p] for p, _, _ in wavs], []) + \
      ["-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", out]
subprocess.run(cmd, check=True); print(out)
