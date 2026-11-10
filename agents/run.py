"""Entry point.
  python -m agents.run tick        -> runs whichever agents are due this hour (GitHub Actions calls this hourly)
  python -m agents.run <agent>     -> runs one agent now (research|scout|outreach|tracker|maker|compliance|analytics|overseer)
"""
import sys
from datetime import datetime, timezone
from . import research, scout, outreach, tracker, maker, compliance, analytics, overseer
from .lib.runner import run_agent

AGENTS = {
    "research": research.main, "analytics": analytics.main, "scout": scout.main, "tracker": tracker.main,
    "outreach": outreach.main, "maker": maker.main, "compliance": compliance.main,
}
RETRY = {name: (lambda n=name: run_agent(n, AGENTS[n])) for name in AGENTS}
AGENTS["overseer"] = overseer.make_main(RETRY)

# How often each agent should run. GitHub's hourly schedule skips runs on quiet repos, so instead of
# "run at exactly 14:00" each tick runs whatever is overdue based on the last run in agent_runs.
EVERY_H = {"research": 24, "analytics": 24, "scout": 3, "tracker": 2, "maker": 12, "compliance": 1}

def _last_runs():
    try:
        from .lib.db import DB
        rows = DB().select("agent_runs", {"select": "agent,started_at", "order": "started_at.desc", "limit": 400})
    except Exception:
        return {}
    last = {}
    for r in rows:
        last.setdefault(r["agent"], datetime.fromisoformat(r["started_at"].replace("Z", "+00:00")))
    return last

def due(now):
    last = _last_runs()
    age = lambda n: (now - last[n]).total_seconds() / 3600 if n in last else 1e9
    plan = [n for n, h in EVERY_H.items() if age(n) >= h - 0.25]
    # outreach: weekdays during business hours ET (13-22 UTC), 3h apart; its own daily cap still applies
    if now.weekday() < 5 and 13 <= now.hour <= 22 and age("outreach") >= 3:
        plan.append("outreach")
    plan.append("overseer")
    if "compliance" in plan:      # compliance must follow maker in the same tick
        plan.remove("compliance")
        plan.insert(len(plan) - 1, "compliance")
    return plan

def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else "tick"
    names = due(datetime.now(timezone.utc)) if arg == "tick" else [arg]
    ok = True
    for n in names:
        if n not in AGENTS:
            sys.exit(f"unknown agent {n}")
        ok = run_agent(n, AGENTS[n]) and ok
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
