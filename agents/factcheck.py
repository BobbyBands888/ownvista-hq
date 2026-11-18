"""FACT CHECK — runs on every Maker plan before it reaches the dashboard.

Three problems kept showing up in plans Bobby reviewed (Nov 2026):
  1. hook fields holding editing instructions instead of on-screen text ("First 2s: officer runs ...")
  2. invented facts ("No weapons found", "PIT-style turn") that no source states
  3. aerial / dash footage called "bodycam"

(1) and (3) are fixed in code. (2) gets one AI pass: every viewer-facing line is checked against the lead and the
case file, unsupported claims are rewritten (or blanked), and what changed is stored on the plan as
script["factcheck"] so the dashboard reviewer can see it.
"""
import json
import re
from .lib import llm

# ---------------- camera type: what the footage actually is ----------------
AERIAL_RE = re.compile(r"\b(aerial|helicopter|black ?hawk|uh-?60|as350|air and marine|amo\b|air interdiction|hitron|"
                       r"flir|infrared|drone|uas\b|aircraft|airplane|airborne|overhead camera|from the air|"
                       r"helo\b|mh-?65|mh-?60|p-?3\b|dhc-?8|king air)", re.I)
DASH_RE = re.compile(r"\b(dash ?cam|dashboard camera|in-?car (camera|video)|cruiser camera|patrol car camera)", re.I)
BODY_RE = re.compile(r"\b(body ?cam|body-?worn|bwc\b|body camera)", re.I)
BODY_PHRASE = re.compile(r"\b(body[ -]?cam(?:era)?s?|body-worn cameras?|bwc)\b( footage| video| clip)?", re.I)

CAMERA_WORDS = {           # (noun used in text, hashtag replacement for #bodycam, angle label prefix)
    "aerial": ("aerial footage", "#aerialfootage", "Aerial Camera"),
    "dash": ("dashcam", "#dashcam", "Dash Cam"),
    "mixed": ("police footage", "#policefootage", "Camera"),
    "unknown": ("police footage", "#policefootage", "Camera"),
}


def camera_kind(lead):
    """'body' | 'aerial' | 'dash' | 'mixed' | 'unknown', from the lead's own words (title, summary, notes)."""
    txt = " ".join(str(lead.get(k) or "") for k in ("title", "summary", "notes"))
    found = [k for k, rx in (("body", BODY_RE), ("aerial", AERIAL_RE), ("dash", DASH_RE)) if rx.search(txt)]
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        return "mixed"
    # local records-request packages are bodycam by default; federal DVIDS clips are usually aerial/vessel video
    return "unknown" if lead.get("source_type") == "dvids_public_domain" else "body"


def camera_phrase(kind):
    """How prompts/cards should name the footage."""
    return "police bodycam footage" if kind == "body" else \
        {"aerial": "aerial law-enforcement footage", "dash": "police dashcam footage"}.get(kind, "law-enforcement footage")


def _fix_camera_words(s, kind):
    if kind == "body" or not isinstance(s, str):
        return s
    noun, tag, _ = CAMERA_WORDS[kind]
    s = re.sub(r"#body ?cam\w*", tag, s, flags=re.I)
    words = [x for x in re.findall(r"[A-Za-z]+", s) if len(x) > 3]
    titleish = bool(words) and sum(x[0].isupper() for x in words) / len(words) > 0.6
    def rep(m):
        w, n = m.group(1), noun
        if m.group(2) and n.endswith("footage"):      # "bodycam footage" -> "aerial footage", not "... footage footage"
            n = n
        elif m.group(2):
            n = n + m.group(2)
        if titleish:                                    # "Full Bodycam" in a title -> "Full Aerial Footage"
            return n.title()
        return n[:1].upper() + n[1:] if w[:1].isupper() else n
    return BODY_PHRASE.sub(rep, s)


# ---------------- hook fields: on-screen text, not editing instructions ----------------
HOOK_KEYS = ("hook_text", "on_screen_text", "cold_open_hook", "title_card")
TIMING_PREFIX = re.compile(r"^\s*\(?\s*(?:(?:first|opening|last)\s*(?:\d+(?:\.\d+)?|one|two|three|four|five|few)?|\d+(?:\.\d+)?(?:\s*[-–]\s*\d+(?:\.\d+)?)?)"
                           r"\s*(?:s|secs?|seconds)\b\s*\)?\s*[:\-–—]?\s*", re.I)
LABEL_PREFIX = re.compile(r"^\s*(?:on[- ]screen(?: text)?|text(?: overlay)?|overlay|hook(?: text)?|caption|title card|super|"
                          r"lower third|cold open|visual|vo|narrator)\s*[:\-–—]\s*", re.I)
DIRECTION_WORDS = re.compile(r"^\s*(show|cut to|open (on|with)|start (on|with)|zoom|freeze|slow[- ]mo|pan|use|insert|"
                             r"overlay|display|put|add|place|begin|fade)\b", re.I)


def clean_hook(s):
    """Strip editing directions; '' if what's left is still a direction, not words for the screen."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    for _ in range(3):                                   # "First 2s: On-screen: ..." -> peel every prefix
        t2 = LABEL_PREFIX.sub("", TIMING_PREFIX.sub("", t, count=1), count=1).strip()
        if t2 == t:
            break
        t = t2
    t = t.strip(" \"'“”")
    if not t or DIRECTION_WORDS.match(t) or len(t.split()) > 14:
        return ""
    return t


# ---------------- walk every viewer-facing line in a plan ----------------
TEXT_KEYS = {"title", "description", "cold_open_hook", "title_card", "narration_setup", "check_ins",
             "what_happened_next", "comment_question", "thumbnail_texts", "on_screen_text", "intro_vo", "outcome_vo",
             "hook_text", "caption", "angle_labels", "hashtags"}
CHECK_KEYS = TEXT_KEYS - {"angle_labels", "hashtags", "description"}     # what the AI pass reads


def _units(p):
    """(path, value) for every checkable text field: episode.*, shorts[i].*, reels[i].*, or a single reel dict."""
    out = []
    def walk(prefix, d):
        if not isinstance(d, dict):
            return
        for k, v in d.items():
            if k in CHECK_KEYS and isinstance(v, str) and v.strip():
                out.append((f"{prefix}{k}", v))
            elif k in CHECK_KEYS and isinstance(v, list):
                for i, x in enumerate(v):
                    if isinstance(x, str) and x.strip():
                        out.append((f"{prefix}{k}[{i}]", x))
    if "episode" in p or "shorts" in p or "reels" in p:
        walk("episode.", p.get("episode"))
        for name in ("shorts", "reels"):
            for i, x in enumerate(p.get(name) or []):
                walk(f"{name}[{i}].", x)
    else:
        walk("", p)
    return out


PATH_RE = re.compile(r"([A-Za-z_]+)(?:\[(\d+)\])?")


def _set(p, path, value):
    """Set p at a path like 'reels[1].caption' or 'episode.check_ins[2]'. Returns True if it existed."""
    cur, parts = p, path.split(".")
    for n, part in enumerate(parts):
        m = PATH_RE.fullmatch(part)
        if not m:
            return False
        key, idx = m[1], m[2]
        last = n == len(parts) - 1
        if not isinstance(cur, dict) or key not in cur:
            return False
        if idx is None:
            if last:
                if not isinstance(cur[key], str):
                    return False
                cur[key] = value
                return True
            cur = cur[key]
        else:
            lst, i = cur[key], int(idx)
            if not isinstance(lst, list) or i >= len(lst):
                return False
            if last:
                if not isinstance(lst[i], str):
                    return False
                lst[i] = value
                return True
            cur = lst[i]
    return False


def _get(p, path):
    cur = p
    for part in path.split("."):
        m = PATH_RE.fullmatch(part)
        if not m or not isinstance(cur, dict) or m[1] not in cur:
            return None
        cur = cur[m[1]]
        if m[2] is not None:
            if not isinstance(cur, list) or int(m[2]) >= len(cur):
                return None
            cur = cur[int(m[2])]
    return cur


def _deep(d, fn, keys):
    """Apply fn to every string under the given keys, recursively (lists included)."""
    if isinstance(d, dict):
        for k, v in d.items():
            if k in keys and isinstance(v, str):
                d[k] = fn(k, v)
            elif k in keys and isinstance(v, list):
                d[k] = [fn(k, x) if isinstance(x, str) else x for x in v]
            elif isinstance(v, (dict, list)):
                _deep(v, fn, keys)
    elif isinstance(d, list):
        for x in d:
            _deep(x, fn, keys)


# ---------------- the AI check ----------------
def ai_check(units, lead, facts, kind):
    return llm.ask(
        "You are the fact checker for Ten-Four Tapes, a police footage channel. You compare every line a viewer "
        "will see or hear against the SOURCES. The sources are the only facts we have. Be strict about facts, "
        "not about style: a line is a problem only if it states or implies something the sources don't say.",
        "SOURCES\nLead: " + json.dumps({k: lead.get(k) for k in ("title", "agency_name", "state", "incident_date",
                                                                  "summary", "source_type")}) +
        "\nCase file: " + json.dumps(facts or {})[:3000] +
        f"\nCamera: the footage is {camera_phrase(kind)}" +
        ("" if kind == "body" else " (NOT bodycam: never call it bodycam or body camera)") +
        "\n\nLINES (path -> text):\n" + json.dumps(dict(units))[:9000] +
        """

Flag a line if it has ANY of these:
- a fact the sources don't state: what was or wasn't found ("no weapons found"), tactics or maneuvers ("PIT-style",
  "warning shots"), injuries, arrests, charges, outcomes, motives, numbers, names, places, times, or what someone said
- an outcome or charge worded more strongly than the case file
- the camera type wrong (calling non-bodycam footage "bodycam", or claiming several officers' cameras without sources)
- an editing instruction instead of words for the viewer ("First 2s: ...", "show the ...", "cut to ...")
Do NOT flag: describing generally what a viewer will see in this kind of incident if the lead implies it
(e.g. "the chase is on" for a pursuit lead), the case name, or hashtags.

For each flagged line give "fix": the same line rewritten so every fact is supported (keep it short and punchy,
same purpose), or "" if nothing true fits.
Return JSON {"problems":[{"path":"exact path from LINES","claim":"the unsupported part","fix":""}]}""",
        max_tokens=1800, temperature=0.1)


def check(plan, lead, facts=None, use_ai=True):
    """Fix a Maker plan in place. Works on a full plan {"episode","shorts","reels"} or a single re-cut reel dict.
    Returns the plan with plan["factcheck"] (full plan) / plan["factcheck"] (reel) = {camera, fixed:[...], ai}."""
    kind = camera_kind(lead)
    log = []

    # 1. hook fields: words for the screen, not instructions
    def hook(k, v):
        if k not in HOOK_KEYS:
            return v
        c = clean_hook(v)
        if c != v.strip():
            log.append(f"{k}: '{v[:60]}' -> '{c}'" if c else f"{k}: dropped instruction '{v[:60]}'")
        return c
    _deep(plan, hook, set(HOOK_KEYS))

    # 2. camera words (angle labels first: 'Body Cam Officer 1' -> 'Aerial Camera 1')
    if kind != "body":
        label = CAMERA_WORDS[kind][2]
        def lab(k, v):
            return re.sub(r"^\s*body\s*cam(era)?\s*officer\s*", f"{label} ", v, flags=re.I).strip() \
                if k == "angle_labels" else v
        _deep(plan, lab, {"angle_labels"})

    def cam(k, v):
        new = _fix_camera_words(v, kind)
        if new != v:
            log.append(f"{k}: called {kind} footage bodycam")
        return new
    _deep(plan, cam, TEXT_KEYS)
    # 3. invented facts
    ai = "skipped"
    if use_ai:
        units = _units(plan)
        try:
            j = ai_check(units, lead, facts, kind)
            probs = [x for x in (j.get("problems") or []) if isinstance(x, dict) and x.get("path")]
            ai = "ok"
            for pr in probs:
                path, fix = str(pr["path"]).strip(), pr.get("fix")
                old = _get(plan, path)
                if not isinstance(old, str) or not isinstance(fix, str) or fix.strip() == old.strip():
                    continue
                fix = fix.strip()
                if path.rsplit(".", 1)[-1].split("[")[0] in HOOK_KEYS:
                    fix = clean_hook(fix)
                if _set(plan, path, fix):
                    log.append(f"{path}: '{str(pr.get('claim') or old)[:80]}' not in sources -> "
                               + (f"'{fix[:80]}'" if fix else "removed"))
        except Exception as e:
            ai = f"failed: {str(e)[:120]}"

    # list fields: drop lines the check emptied
    def prune(d):
        if isinstance(d, dict):
            for k, v in d.items():
                if k in ("check_ins", "thumbnail_texts") and isinstance(v, list):
                    d[k] = [x for x in v if not isinstance(x, str) or x.strip()]
                else:
                    prune(v)
        elif isinstance(d, list):
            for x in d:
                prune(x)
    prune(plan)

    record = {"camera": kind, "fixed": log[:30], "ai": ai}
    targets = [plan.get("episode")] + list(plan.get("shorts") or []) + list(plan.get("reels") or []) \
        if any(k in plan for k in ("episode", "shorts", "reels")) else [plan]
    for t in targets:
        if isinstance(t, dict):
            t["camera"] = kind
            t["factcheck"] = record
    return plan
