"""Draft and review again from a saved run, without running the report or touching the website.

    python scripts/redraft.py reports/mizangroupllc.com/2026-11-04/ai.json

Takes the facts saved in an ai.json run log and runs the draft agent, the code check and the reviews on them, so a
change to a prompt can be tried in seconds and costs only the model calls. The website is never contacted, so the
report's one-visitor footprint is not spent on prompt testing. The result is saved beside the log as
ai-redraft.json, and the original log is left as it was. Needs ANTHROPIC_API_KEY in .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from domain_health_check import agents
from domain_health_check.config import load_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("log", type=Path, help="an ai.json run log")
    args = parser.parse_args(argv)

    facts = json.loads(args.log.read_text(encoding="utf-8"))["facts"]
    load_env(Path(".env"))
    client, why = agents.make_client(require_switch=False)
    if client is None:
        print(why, file=sys.stderr)
        return 2
    outcome = agents._run(facts, client, agents.REVIEW_RUNS)
    print(f"AI draft: {outcome.status}. {outcome.reason}")
    print(outcome.usage_line())
    for line in outcome.flagged():
        print(f"  - {line}")
    if outcome.draft is not None:
        print("\n" + agents.owner_email(outcome.draft, facts) + "\n")
    out = args.log.with_name("ai-redraft.json")
    out.write_text(json.dumps({
        "status": outcome.status, "reason": outcome.reason, "facts": facts,
        "draft": asdict(outcome.draft) if outcome.draft else None, "problems": outcome.problems,
        "reviews": [asdict(r) for r in outcome.reviews], "usage": [asdict(u) for u in outcome.usage],
        "cost_usd_estimate": round(outcome.cost, 6),
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
