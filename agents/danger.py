"""On-screen danger: how much threat is VISIBLE in the footage (to officers, suspects or the public), 0-10.

Scout scores every lead with it, and every agent that picks leads (Outreach, Portal Filer, Case Desk, Maker) works the
most dangerous footage first: our winning Reels are the ones where viewers can see the threat (the narco sub boarding,
warning shots, a suspect swinging at an agent). Action score still breaks ties.

Stored in leads.danger_score (run the SQL in supabase/schema.sql) and, so nothing breaks before that SQL is run,
also as a [danger:N] tag in leads.notes.
"""
import re

RUBRIC = """DANGER (0-10) = the threat a viewer will SEE on camera, from the lead text only:
 10   shots fired on camera, or a weapon pointed at officers
 8-9  armed suspect on camera (gun, knife, club), a car used as a weapon, an officer dragged or hit by a vehicle,
      a pursuit that ends in a crash, a boarding of a fleeing vessel with warning or disabling fire
 6-7  a violent fight or struggle, taser/K9/force used, a foot chase through traffic, officers in fire/water peril
 4-5  resisting arrest, a combative or irate subject, a pursuit with no crash
 2-3  a tense argument or refusal, no physical threat
 0-1  a calm stop, an interview room, paperwork, a press conference
Danger is the THREAT, never the aftermath: injuries, blood or a body add nothing. Unknown -> score conservatively."""

TAG_RE = re.compile(r"\[danger:(\d+)\]")


def clamp(v):
    try:
        return max(0, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return None


def of(lead):
    """Danger for a lead row: the column if set, else the notes tag, else None (not scored yet)."""
    v = clamp(lead.get("danger_score"))
    if v is not None:
        return v
    m = TAG_RE.search(lead.get("notes") or "")
    return int(m[1]) if m else None


def tag(notes, n):
    """Notes with a [danger:N] tag (replaces an old one); kept after any [len:..] tag."""
    notes = TAG_RE.sub("", notes or "").strip(" —")
    if n is None:
        return notes
    m = re.match(r"(\[len:\d+s\])\s*(?:—\s*)?(.*)", notes, re.S)
    if m:
        return f"{m[1]} [danger:{n}]" + (f" — {m[2]}" if m[2] else "")
    return f"[danger:{n}]" + (f" — {notes}" if notes else "")


def key(lead):
    """Sort key: most dangerous first, then most action, then newest. Unscored leads sit at their action score - 1
    so a scored 8 beats an unscored 8 until the backfill gets to it."""
    d = of(lead)
    a = lead.get("action_score") or 0
    return (-(d if d is not None else max(0, a - 1)), -a, -_ts(lead.get("created_at")))


def _ts(s):
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0


def rank(leads):
    return sorted(leads, key=key)


def has_column_error(e):
    t = str(e)
    return "danger_score" in t and ("column" in t or "PGRST" in t or "schema cache" in t)
