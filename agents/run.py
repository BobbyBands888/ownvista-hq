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

def due(now):
    h, wd = now.hour, now.weekday()  # UTC
    plan = []
    if h == 6: plan.append("research")
    if h == 10: plan.append("analytics")
    if h % 3 == 0: plan.append("scout")
    if h % 2 == 0: plan.append("tracker")
    if wd < 5 and h in (14, 18): plan.append("outreach")    # ~9am / 1pm ET weekdays
    if h in (11, 23): plan.append("maker")
    plan += ["compliance", "overseer"]
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
