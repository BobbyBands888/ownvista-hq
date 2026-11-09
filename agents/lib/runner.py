"""Wraps every agent run: logs start/finish to agent_runs, records errors as alerts."""
import traceback
from datetime import datetime, timezone
from .db import DB

RULES = """Ten-Four Tapes channel rules (never break these):
- Footage must be released by the agency or prosecutor itself, obtained by public records request,
  or be public-domain federal footage (DVIDS). Never news-station clips, never other YouTubers' uploads,
  never downloaded from YouTube.
- No minors on camera in any capacity.
- Cases involving a death are OK, but never show the death itself, gore, or a lingering body.
- Credit the agency on every video.
- No spending money of any kind. Any fee quote goes to Bobby; nothing is paid.
- We never reply to comments.
- Outreach never offers phone calls and never asks anyone to call Bobby.
- No real-estate content."""

def run_agent(name, fn):
    db = DB()
    row = db.insert("agent_runs", {"agent": name})[0]
    try:
        summary = fn(db) or "done"
        db.update("agent_runs", {"id": f"eq.{row['id']}"},
                  {"status": "ok", "summary": str(summary)[:2000], "finished_at": datetime.now(timezone.utc)})
        print(f"[{name}] ok: {summary}")
        return True
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        db.update("agent_runs", {"id": f"eq.{row['id']}"},
                  {"status": "error", "error": tb[-2000:], "finished_at": datetime.now(timezone.utc)})
        db.alert(name, f"{type(e).__name__}: {e}", "warn")
        return False
