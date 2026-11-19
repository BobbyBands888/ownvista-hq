"""AGENCY POST FINDER: from a bodycam news story, find the agency's OWN public Facebook / YouTube post of the video.

Local outlets (Patch, county news sites, TV station pages) usually embed or link the sheriff's / police department's
own post ("watch it here"). This reads the article, pulls every Facebook reel / video and YouTube link out of it,
and asks yt-dlp (metadata only, no download) who posted each one. A post counts only when the poster is the lead's
agency. Re-posts by TV stations or "bodycam" pages never count (rule: agency / prosecutor / DVIDS footage only).

The finder never replaces the records request: Outreach still asks the agency for every officer's unedited camera
(that's where the second and third angles come from). The post just lets HQ make a Reel now."""
import re
from urllib.parse import unquote

import requests

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
FB_RX = re.compile(r"https?://(?:www\.|m\.|web\.)?facebook\.com/(?:reel/\d{6,}|watch/?\?v=\d{6,}|"
                   r"[\w.\-]+/videos/(?:[\w.\-]+/)?\d{6,}|share/[rv]/[\w-]+)", re.I)
YT_RX = re.compile(r"(?:youtube\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([\w-]{11})", re.I)
# words every agency name shares: they don't tell two agencies apart
GENERIC = {"county", "police", "sheriff", "sheriffs", "office", "department", "division", "city", "state", "town",
           "township", "village", "public", "safety", "official", "page", "the", "and", "dept", "patrol", "law",
           "enforcement", "agency", "parish", "borough", "metro", "metropolitan", "news"}
STATE_WORDS = {"florida", "texas", "ohio", "georgia", "california", "arizona", "wisconsin", "michigan", "indiana",
               "tennessee", "kentucky", "carolina", "virginia", "york", "jersey", "pennsylvania", "illinois",
               "missouri", "alabama", "louisiana", "oklahoma", "colorado", "nevada", "oregon", "washington"}
MAX_CANDIDATES = 5


def _key_words(name):
    words = set(re.findall(r"[a-z]{3,}", (name or "").lower().replace("'", "")))
    return words - GENERIC - STATE_WORDS


def same_agency(uploader, agency):
    """'Fond du Lac County Sheriff's Office' vs 'FDL County Sheriff' etc: share a distinctive word, and both are
    the same KIND of agency (a sheriff's post never stands in for a police department's case)."""
    if not uploader or not agency:
        return False
    a, u = _key_words(agency), _key_words(uploader)
    if not a or not (a & u):
        return False
    lo_a, lo_u = agency.lower(), uploader.lower()
    for kind in ("sheriff", "police", "patrol", "attorney", "prosecutor"):
        if (kind in lo_a) != (kind in lo_u) and kind in lo_a + lo_u:
            # "Columbus Division of Police" vs "Columbus Police" both say police; a TV station says neither
            return False
    return True


def links_in(html):
    """Facebook reel/video and YouTube links in an article, embeds included (plugins/video.php?href=...)."""
    text = unquote(unquote(html.replace("\\/", "/").replace("&amp;", "&")))
    out = []
    for m in FB_RX.finditer(text):
        out.append(m.group(0).rstrip("/"))
    for m in YT_RX.finditer(text):
        out.append(f"https://www.youtube.com/watch?v={m.group(1)}")
    return list(dict.fromkeys(out))


def post_info(url):
    """Who posted it, when, how long. Metadata only."""
    import yt_dlp
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as y:
        i = y.extract_info(url, download=False)
    return {"url": url, "uploader": i.get("uploader") or i.get("channel") or "",
            "duration": i.get("duration"), "upload_date": i.get("upload_date"),
            "description": (i.get("description") or "")[:1500]}


def find(article_url, agency_name, min_secs=20):
    """The agency's own post of the video in this news story, or None."""
    if not article_url or not agency_name:
        return None
    try:
        r = requests.get(article_url, headers=UA, timeout=25)
        if r.status_code >= 300 or "html" not in r.headers.get("content-type", "html"):
            return None
        html = r.text[:1_500_000]
    except Exception:
        return None
    for url in links_in(html)[:MAX_CANDIDATES]:
        try:
            info = post_info(url)
        except Exception:
            continue
        if not same_agency(info["uploader"], agency_name):
            continue
        if info.get("duration") and info["duration"] < min_secs:
            continue
        return info
    return None


NOTE_RX = re.compile(r"agency post: (https?://\S+)")


def url_of(lead):
    """The agency's own post for a lead: its source_url when that is the post, or the one Scout found for it."""
    src = (lead or {}).get("source_url") or ""
    if FB_RX.match(src) or YT_RX.search(src):
        return src
    m = NOTE_RX.search((lead or {}).get("notes") or "")
    return m.group(1).rstrip(".,;)") if m else None
