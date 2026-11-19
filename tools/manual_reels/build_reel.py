"""Build a vertical Ten-Four Tapes reel from segments + timed captions. Usage: python3 build_reel.py spec.json"""
import json, subprocess, sys, os
s = json.load(open(sys.argv[1])); d = os.path.dirname(os.path.abspath(sys.argv[1]))
F = "/usr/share/fonts/opentype/inter/Inter-ExtraBold.otf"; R = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
def tf(name, text):
    p = os.path.join(d, f"_{name}.txt"); open(p, "w").write(text); return p
segs = s["segments"]; n = len(segs); total = sum(b - a for a, b in segs); end = s.get("end_secs", 3.2)
crop = s.get("crop_w", 900)
fc = [f"[0:v]split={n}" + "".join(f"[v{i}]" for i in range(n)), f"[0:a]asplit={n}" + "".join(f"[a{i}]" for i in range(n))]
for i, (a, b) in enumerate(segs):
    fc.append(f"[v{i}]trim={a}:{b},setpts=PTS-STARTPTS[sv{i}]"); fc.append(f"[a{i}]atrim={a}:{b},asetpts=PTS-STARTPTS[sa{i}]")
fc.append("".join(f"[sv{i}][sa{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[cv][ca]")
blur = "".join(f",boxblur=40:5:enable='between(t,{x},{y})'" for x, y in s.get("blur", []))   # full-frame blur windows (death/injury)
fc.append(f"[cv]tpad=stop_mode=clone:stop_duration={end}{blur},split[p1][p2]")
fc.append("[p1]scale=-2:1920,crop=1080:1920,boxblur=30:3,eq=brightness=-0.25[bg]")
fc.append(f"[p2]crop={crop}:ih,scale=1080:-2,eq=contrast=1.08[fg]")
dt = [f"drawtext=fontfile={R}:textfile={tf('br','TEN-FOUR TAPES')}:fontsize=30:fontcolor=white:x=40:y=60",
      f"drawtext=fontfile={F}:textfile={tf('ti',s['title'])}:fontsize=58:fontcolor=black:box=1:boxcolor=0xF5C518:boxborderw=22:x=(w-tw)/2:y=400:enable='lt(t,{total})'"]
for i, c in enumerate(s["captions"]):
    big = c.get("big"); col = "0xF5C518" if c.get("yellow") or big else "white"
    dt.append(f"drawtext=fontfile={F}:textfile={tf('c%d'%i,c['text'])}:fontsize={96 if big else 64}:fontcolor={col}:borderw=6:bordercolor=black:line_spacing=14:x=(w-tw)/2:y=1440:enable='between(t,{c['t'][0]},{c['t'][1]})'")
e = f"gte(t,{total})"
dt += [f"drawbox=x=0:y=0:w=iw:h=ih:color=black@0.72:t=fill:enable='{e}'",
       f"drawtext=fontfile={F}:textfile={tf('e1','HOW IT ENDED')}:fontsize=40:fontcolor=black:box=1:boxcolor=0xF5C518:boxborderw=12:x=(w-tw)/2:y=800:enable='{e}'",
       f"drawtext=fontfile={F}:textfile={tf('e2',s['ended'])}:fontsize=56:fontcolor=white:line_spacing=12:x=(w-tw)/2:y=890:enable='{e}'",
       f"drawtext=fontfile={F}:textfile={tf('e3','FOLLOW FOR MORE CASES')}:fontsize=64:fontcolor=white:x=(w-tw)/2:y=1150:enable='gte(t,{total+1.2})'",
       f"drawtext=fontfile={R}:textfile={tf('cr',s['credit'])}:fontsize=28:fontcolor=white@0.85:x=(w-tw)/2:y=1830"]
fc.append(f"[bg][fg]overlay=0:(H-h)/2-60," + ",".join(dt) + ",format=yuv420p[ov]")
fc.append(f"[ca]apad=pad_dur={end},loudnorm=I=-16:TP=-1.5:LRA=11[oa]")
out = os.path.join(d, s["out"])
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", os.path.join(d, s["src"]), "-filter_complex", ";".join(fc), "-map", "[ov]", "-map", "[oa]",
                "-t", str(total + end), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-r", "30",
                "-movflags", "+faststart", out], check=True)
subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", out, "-vf", f"fps=1/{max(2.5,(total+end)/21):.2f},scale=180:-1,tile=7x3", "-frames:v", "1", out + ".check.jpg"], check=True)
print(out, total + end)
