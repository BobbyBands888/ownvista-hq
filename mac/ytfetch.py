"""YT FETCH — pulls agencies' own YouTube posts from Bobby's Mac (Nov 20).

YouTube answers GitHub's cloud servers with "Sign in to confirm you're not a bot", so the cloud publisher can't pull
an agency's YouTube release (Baltimore, Greensboro, Nashville...). A home connection isn't blocked. This runs on the
Mac as a GitHub self-hosted runner job (.github/workflows/ytfetch.yml), downloads each needed post with yt-dlp and
stores it as the lead's "<lead_id>-post" footage copy. The cloud publisher already restores that copy before it
tries YouTube itself, so nothing else changes: renders, checks and posting stay in the cloud.

Only agency posts on official channels (Scout already checked the uploader) for leads HQ is actually using."""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import runner  # noqa: E402
from agents.lib.runner import run_agent  # noqa: E402

MAX_PER_RUN = 6


def wanted(db):
    """YouTube-post leads with live work: obtained (Maker will plan it) or used with unposted, unrejected content."""
    leads = db.select("leads", {"status": "in.(obtained,used)", "source_type": "eq.agency_release",
                                "source_url": "like.*youtube.com/watch*", "select": "id,title,agency_name,source_url,status",
                                "order": "action_score.desc", "limit": 200})
    live = {c["lead_id"] for c in db.select("content", {"select": "lead_id", "approval_status": "neq.rejected",
                                                         "status": "in.(scripted,rendered)", "limit": 2000})}
    raw = {r["lead_id"] for r in db.select("records_requests", {"select": "lead_id", "status": "eq.fulfilled",
                                                                 "limit": 2000})}
    return [l for l in leads if l["id"] not in raw and (l["status"] == "obtained" or l["id"] in live)]


def main(db):
    got, kept, errs = 0, 0, []
    for lead in wanted(db):
        if got >= MAX_PER_RUN:
            break
        rel = runner._mirror_release(f"{lead['id']}-post")
        if rel and rel.get("assets"):
            kept += 1
            continue
        tmp = Path(tempfile.mkdtemp(prefix="ytfetch_"))
        try:
            runner._ytdlp(lead["source_url"], tmp)
            runner.save_mirror(f"{lead['id']}-post", tmp)
            got += 1
        except Exception as e:
            errs.append(f"{(lead.get('title') or '')[:40]}: {str(e)[:120]}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    if errs:
        db.alert_once("yt_fetch", "Mac couldn't pull some agency YouTube posts: " + " | ".join(errs[:3]), "warn",
                      key="Mac couldn't pull some agency YouTube posts")
    return f"pulled {got} agency YouTube posts for the cloud publisher ({kept} already kept)" + \
        (f"; {len(errs)} failed: {errs[:3]}" if errs else "")


if __name__ == "__main__":
    sys.exit(0 if run_agent("yt_fetch", main) else 1)
