"""PACKAGING rules shared by the Maker (plans) and the Writer (locked cut): every YouTube title uses one of the
operating doc's 5 formulas, and every episode gets 3 different thumbnail texts for Test & Compare."""
import re

FORMULAS = {
    "Person + action + twist": "Man Pulls Rifle on Border Agents, Then Makes One Mistake",
    "Situation + realization": "Driver Thinks He Lost the Deputies. He Didn't.",
    "Place + incident + bodycam": "Las Cruces Shootout: Full Bodycam of the Desert Stop",
    "Outcome tease": "He Ran From Police. The Judge Wasn't Impressed.",
    "Number + stakes": "14 Minutes of Pursuit Ends in a Backyard",
}
MAX_TITLE = 60
ACRONYMS = {"ICE", "CBP", "FBI", "DEA", "ATF", "SWAT", "DUI", "AZ", "TX", "FL", "CA", "NM", "NJ", "NY", "US", "USA",
            "AR", "AK", "HP", "FHP", "PD", "SO", "TV", "ID", "AM", "PM"}

TITLE_RULES = ("YOUTUBE TITLE: use exactly ONE of these 5 formulas (examples show the shape):\n"
               + "\n".join(f"- {k}: \"{v}\"" for k, v in FORMULAS.items()) +
               f"\nUnder {MAX_TITLE} characters, Title Case, no ALL CAPS words, at most one emotional word, never promise "
               "something the footage doesn't show, no case name / 'Part' / channel name in the title. "
               "Never promise an ending ('what happened next', 'the judge', 'sentenced', 'ends in') unless the case file has the outcome.")

THUMB_RULES = ("THUMBNAIL TEXTS: 3 different options, 2-3 words each, ALL different, each about a DIFFERENT peak "
               "moment or angle (the stakes, the twist, the danger). Never repeat words already in the title, never "
               "the case name, no gore or death words. Good: \"HE HAD A RIFLE\", \"WRONG HOUSE\", \"20 YEARS\".")


def formula_of(name):
    n = str(name or "").strip().lower()
    return next((k for k in FORMULAS if k.lower() == n), None)


PROMISES_OUTCOME = re.compile(r"what happened next|how it ended|the ending|sentenced|sentence|verdict|judge|jury|"
                              r"convicted|years in prison|\bends? in\b|\bended\b", re.I)


def title_ok(title, formula, has_outcome=True):
    """has_outcome=False (the case file has no outcome): no Outcome tease and no title that promises an ending."""
    t = str(title or "").strip()
    if not t or len(t) > MAX_TITLE or not formula_of(formula):
        return False
    if not has_outcome and (formula_of(formula) == "Outcome tease" or PROMISES_OUTCOME.search(t)):
        return False
    if re.search(r"\bpart\s*\d|ten-four tapes", t, re.I):
        return False
    caps = [w for w in re.findall(r"[A-Za-z]{2,}", t) if w.isupper() and w not in ACRONYMS]
    return not caps


def thumb_texts(xs, title=""):
    """Clean list of up to 3 distinct 2-3 word texts, none repeating the title's words."""
    tw = {w.lower() for w in re.findall(r"[A-Za-z']+", title or "")}
    out = []
    for x in xs or []:
        words = str(x).upper().split()
        if not words or len(words) > 3:         # never chop a phrase mid-thought ("HE HAD A")
            continue
        if sum(w.lower().strip(".,!?") in tw for w in words) >= len(words):   # fully repeats the title
            continue
        t = " ".join(words)
        if t not in out:
            out.append(t)
    return out[:3]
