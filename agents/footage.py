"""How much a case's footage can carry. One rule, used by Scout (length known from YouTube/DVIDS), Maker (plans only
what fits) and the publisher (trims the plan once the real files are on disk, before any vision time is spent).

Las Cruces lesson: a 28-second clip got an episode + 3 Reels + 3 Shorts planned. Every extra item then cost vision
calls, a failed render, and a review slot on the dashboard.
"""
import re

LEN_RE = re.compile(r"\[len:(\d+)s\]")
EPISODE_MIN = 180          # same floor render.py uses: no 1-minute "episodes"
SHORT_EACH = 40            # (old Part Shorts) Part p needed p*40s
SHORTS_ON = False          # Bobby, Nov 20: no Part 1/2/3 Shorts; each Reel goes to YouTube as a standalone Short
REEL_EACH = 30             # each Reel is its own 25-30s moment
REEL_MIN = 20              # below this there is no standalone moment at all


def budget(secs):
    """-> {"episode": bool, "shorts": 0-3, "reels": n} for this many seconds of footage (None = unknown = no cap)."""
    if secs is None:
        return {"episode": True, "shorts": 3 if SHORTS_ON else 0, "reels": 99}
    secs = float(secs)
    return {"episode": secs >= EPISODE_MIN,
            "shorts": max(0, min(3, int(secs // SHORT_EACH))) if SHORTS_ON else 0,
            "reels": 0 if secs < REEL_MIN else max(1, int(secs // REEL_EACH))}


def fits(it, b):
    """Does this content row fit the budget? -> (ok, reason)"""
    k = it.get("kind")
    if k == "episode" and not b["episode"]:
        return False, f"an episode needs {EPISODE_MIN // 60} min+ of footage"
    if k == "short":
        part = int(it.get("part") or 1)
        if part > b["shorts"]:
            return False, f"Short Part {part} needs {part * SHORT_EACH}s+ of footage"
    if k == "reel":
        sc = it.get("script") if isinstance(it.get("script"), dict) else {}
        n = int(sc.get("reel_no") or 1)
        if n > b["reels"]:
            return False, f"Reel {n} needs {n * REEL_EACH}s+ of footage (one fresh moment each)"
    return True, ""


def seconds_from_notes(notes):
    m = LEN_RE.search(notes or "")
    return int(m[1]) if m else None


def tag(notes, secs):
    """Notes with a [len:NNs] tag (replaces an old one)."""
    notes = LEN_RE.sub("", notes or "").strip(" —")
    return (f"[len:{int(secs)}s]" + (f" — {notes}" if notes else "")) if secs else notes


def iso_seconds(d):
    """YouTube ISO-8601 duration (PT1H2M3S) -> seconds."""
    m = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", d or "")
    if not m:
        return None
    dd, h, mi, s = (int(x or 0) for x in m.groups())
    return dd * 86400 + h * 3600 + mi * 60 + s
