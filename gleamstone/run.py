"""Gleamstone agents entry point (runs inside the same hourly HQ tick, after Ten-Four Tapes).
  python -m gleamstone.run tick        -> whatever is due
  python -m gleamstone.run <agent>     -> scout | map | enrich | inbox | writer | sender | brief | recruit
Agent runs are logged as gs_<name> so they only show in the Gleamstone workspace."""
import sys
from datetime import datetime, timezone

from agents.lib.runner import run_agent
from . import scout, enrich, writer, sender, brief, inbox

AGENTS = {"scout": scout.main, "map": scout.main_map, "enrich": enrich.main, "writer": writer.main,
          "sender": sender.main, "inbox": inbox.main, "brief": brief.main, "recruit": brief.recruit}
EVERY_H = {"scout": 6, "map": 168, "enrich": 2, "writer": 2, "sender": 1, "inbox": 1, "brief": 1, "recruit": 168}
ORDER = ["map", "scout", "enrich", "inbox", "writer", "sender", "recruit", "brief"]


def _last_runs():
    try:
        from agents.lib.db import DB
        rows = DB().select("agent_runs", {"select": "agent,started_at,status", "agent": "like.gs_*",
                                          "order": "started_at.desc", "limit": 300})
    except Exception:
        return {}
    last = {}
    for r in rows:
        if r["status"] in ("ok", "error"):
            last.setdefault(r["agent"], (datetime.fromisoformat(r["started_at"].replace("Z", "+00:00")), r["status"]))
    return last


def _map_sweep_complete():
    try:
        from agents.lib.db import DB
        sw = DB().setting("gs_map_sweep", {}) or {}
        return bool(sw.get("complete"))
    except Exception:
        return True


def due(now):
    last = _last_runs()
    age = lambda n: (now - last["gs_" + n][0]).total_seconds() / 3600 if "gs_" + n in last else 1e9
    every = lambda n: min(EVERY_H[n], 6) if last.get("gs_" + n, (None, ""))[1] == "error" else EVERY_H[n]
    if not _map_sweep_complete():
        EVERY = dict(EVERY_H, map=6)            # keep going every 6h until the whole service area is mapped
        every = lambda n: min(EVERY[n], 6) if last.get("gs_" + n, (None, ""))[1] == "error" else EVERY[n]
    return [n for n in ORDER if age(n) >= every(n) - 0.25]


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "tick"
    try:
        from agents.lib.db import DB
        DB().select("gs_prospects", {"select": "id", "limit": 1})
    except Exception as e:
        print(f"Gleamstone tables not set up yet (run supabase/gleamstone.sql): {e}")
        sys.exit(0)
    names = due(datetime.now(timezone.utc)) if arg == "tick" else [arg]
    print(f"Gleamstone plan: {', '.join(names) or 'nothing due'}", flush=True)
    ok = True
    for n in names:
        if n not in AGENTS:
            sys.exit(f"unknown agent {n}")
        ok = run_agent("gs_" + n, AGENTS[n]) and ok
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
