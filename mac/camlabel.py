"""CAMERA LABELS (Bobby, Nov 19): every officer's camera gets its own on-screen tag: BODY CAM 1, BODY CAM 2,
DASH CAM (DASH CAM 1 / 2 when there are two cruisers), DRONE. One camera keeps its number for the whole video.

Which camera a segment is:
  - its file (a records package is one file per camera), or
  - a "cam" name the editing model gives within one file (agency edits stitch several officers' cameras into
    one video; the model names them from the agency's own on-screen labels / who is talking), and
  - its kind: the file name (BWC / body / dash / ICV / in-car / drone / UAS) first, else what the frames show
    (mostly road_ahead / inside_car = dash).
Numbers appear only when the video has two or more of that kind: a single bodycam is just "BODY CAM".
Non-camera labels the Maker already set ("911 Call", "Interview Room") are kept as they are."""
import re

BODY_RX = re.compile(r"(?<![a-z])(bwc|body[\s_-]?(worn|cam)|bodycam|axon[\s_-]?body)(?![a-z])", re.I)
DASH_RX = re.compile(r"(?<![a-z])(dash(?:[\s_-]?cam(?:era)?)?|icv|in[\s_-]?car|fleet|squad[\s_-]?cam|cruiser)(?![a-z])", re.I)
DRONE_RX = re.compile(r"(?<![a-z])(drone|uas|suas|aerial|air[\s_-]?unit|helicopter|aviation|flir)(?![a-z])", re.I)
KEEP_RX = re.compile(r"(?<![a-z])(911|interview|interrogation|dispatch|radio|jail|booking|surveillance|cctv|doorbell)", re.I)
NAMES = {"body": "BODY CAM", "dash": "DASH CAM", "drone": "DRONE"}


def kind_of(files, seg):
    """'body' | 'dash' | 'drone' for one segment."""
    f = files[seg["file"]]
    hint = f"{seg.get('cam') or ''} {f.get('path') or ''}"
    for rx, k in ((BODY_RX, "body"), (DRONE_RX, "drone"), (DASH_RX, "dash")):
        if rx.search(hint):
            return k
    views = [v.get("view") for v in f.get("vision") or [] if seg["start"] <= v["t"] < seg["end"]]
    views = [v for v in views if v not in ("screen", "black", None)]
    if views and sum(v in ("road_ahead", "inside_car") for v in views) / len(views) >= 0.6:
        return "dash"
    return "body"


def identity(seg):
    """Same file + same model-given camera name = same camera."""
    cam = re.sub(r"[^a-z0-9]+", " ", str(seg.get("cam") or "").lower()).strip()
    return (seg["file"], cam)


def assign(files, segs, field="cam_label"):
    """Put a label on every segment (in place) and return the segments. Numbering follows first appearance."""
    kinds, order = {}, {}
    for s in segs:
        if KEEP_RX.search(str(s.get("label") or "")):
            continue
        ident = identity(s)
        k = kinds.setdefault(ident, kind_of(files, s))
        order.setdefault(k, [])
        if ident not in order[k]:
            order[k].append(ident)
    for s in segs:
        if KEEP_RX.search(str(s.get("label") or "")):
            s[field] = str(s["label"]).upper()
            continue
        ident = identity(s)
        k = kinds[ident]
        n = order[k].index(ident) + 1
        s[field] = NAMES[k] + (f" {n}" if len(order[k]) > 1 else "")
    return segs


RUN_MIN = 6      # seconds: a camera switch shorter than this is vision noise, not a new camera


def runs(f, s, e, cam=None):
    """Camera tag runs for ONE window of one file (Shorts): [(t0, t1, label)] with times relative to s.
    A records-package file named BWC / dash / drone is one camera for the whole window. An agency edit stitches
    cameras into one file, so there the tag follows the frames: road_ahead = DASH CAM, on foot / indoors = BODY CAM
    (cruiser interior, slates and black frames keep the camera before them). One window can't tell two officers'
    bodycams apart, so Shorts never number them."""
    hint = f"{cam or ''} {f.get('path') or ''}"
    for rx, k in ((BODY_RX, "body"), (DRONE_RX, "drone"), (DASH_RX, "dash")):
        if rx.search(hint):
            return [(0.0, round(e - s, 2), NAMES[k])]
    fr = sorted(f.get("vision") or [], key=lambda v: v["t"])
    per = []
    for t in range(int(s), int(e)):
        near = min(fr, key=lambda v: abs(v["t"] - t)) if fr else None
        view = near.get("view") if near and abs(near["t"] - t) <= 8 else None
        per.append("dash" if view == "road_ahead" else "body" if view in ("outside", "indoor") else None)
    known = [k for k in per if k]
    if not known:
        return [(0.0, round(e - s, 2), NAMES[kind_of([f], {"file": 0, "start": s, "end": e, "cam": cam})])]
    first = known[0]
    cur, out = first, []
    for i, k in enumerate(per):                    # carry the last known camera over unknown seconds
        per[i] = cur = k or cur
    a = 0
    for i in range(1, len(per) + 1):
        if i == len(per) or per[i] != per[a]:
            out.append([a, i, per[a]])
            a = i
    merged = []                                     # short runs join the run before them (or after, for the first)
    for r in out:
        if merged and (r[1] - r[0] < RUN_MIN or merged[-1][2] == r[2]):
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    if len(merged) > 1 and merged[0][1] - merged[0][0] < RUN_MIN:
        merged[1][0] = merged[0][0]
        merged.pop(0)
    end = round(e - s, 2)
    return [(float(a), float(b) if n < len(merged) - 1 else end, NAMES[k]) for n, (a, b, k) in enumerate(merged)]
