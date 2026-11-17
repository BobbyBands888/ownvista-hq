"""Wraps every agent run: logs start/finish to agent_runs, records errors as alerts."""
import traceback
from datetime import datetime, timezone
from .db import DB

RULES = """Ten-Four Tapes channel rules (never break these):
- Footage must be released by the agency or prosecutor itself, obtained by public records request,
  or be public-domain federal footage (DVIDS). Never news-station clips, never other YouTubers' uploads,
  never downloaded from YouTube.
- No minors on camera in any capacity.
- Cases involving a death are OK. The force itself may be shown; what follows once someone goes down (the body,
  injuries, CPR) is only ever shown FULLY BLURRED by the renderer, max 20s, in long-form episodes only — never in
  thumbnails, cold opens, Shorts or Reels. No unblurred gore or body, ever.
- Never call it a "shootout", "gunfight" or "exchange of gunfire" (in names, titles, thumbnails or narration)
  unless the source says the suspect fired too. When only officers fired, say "officer-involved shooting" or
  name what happened (e.g. "Desert Stop", "Roadside Struggle").
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
        _clear_errors(db, name)
        return True
    except Exception as e:
        tb = traceback.format_exc()
        print(tb)
        db.update("agent_runs", {"id": f"eq.{row['id']}"},
                  {"status": "error", "error": tb[-2000:], "finished_at": datetime.now(timezone.utc)})
        msg = f"{type(e).__name__}: {e}"
        db.alert_once(name, msg, "warn", key=msg[:80])
        return False


def _clear_errors(db, name):
    """The agent ran fine: its earlier crash alerts are out of date, so take them off 'Needs you'."""
    import re
    try:
        for a in db.select("alerts", {"agent": f"eq.{name}", "resolved": "is.false", "select": "id,message", "limit": 100}):
            if re.match(r"^\w+(Error|Exception|Timeout)\w*: ", a.get("message") or ""):
                db.update("alerts", {"id": f"eq.{a['id']}"}, {"resolved": True})
    except Exception:
        pass
