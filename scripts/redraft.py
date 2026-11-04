"""Draft and review again from a saved run, without running the report or touching the website.

    python scripts/redraft.py reports/mizangroupllc.com/2026-11-04/ai.json
    python scripts/redraft.py reports/mizangroupllc.com/2026-11-04/ai.json --times 10

Takes the facts saved in an ai.json run log and runs the draft agent, the code check and the reviews on them, so a
change to a prompt can be tried in seconds and costs only the model calls. The website is never contacted, so the
report's one-visitor footprint is not spent on prompt testing. The result is saved beside the log as
ai-redraft.json, and the original log is left as it was. Needs ANTHROPIC_API_KEY in .env.

One draft passing or failing says little, because the models vary from run to run. --times N drafts N times and
prints how many passed, which is the number worth reporting. Production never retries: a failed draft sends the
template. The saved file keeps every attempt, and its top-level draft is the first one that passed (or the last
attempt if none did), so scripts/eval_review.py can plant claims in a draft the reviewers accepted.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from domain_health_check import agents
from domain_health_check.config import load_env


def _record(outcome) -> dict:
    return {
        "status": outcome.status, "reason": outcome.reason,
        "draft": asdict(outcome.draft) if outcome.draft else None, "problems": outcome.problems,
        "reviews": [asdict(r) for r in outcome.reviews], "usage": [asdict(u) for u in outcome.usage],
        "cost_usd_estimate": round(outcome.cost, 6),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("log", type=Path, help="an ai.json run log")
    parser.add_argument("--times", type=int, default=1, help="how many drafts to make, to measure the pass rate")
    args = parser.parse_args(argv)

    facts = json.loads(args.log.read_text(encoding="utf-8"))["facts"]
    load_env(Path(".env"))
    client, why = agents.make_client(require_switch=False)
    if client is None:
        print(why, file=sys.stderr)
        return 2
    outcomes = []
    for n in range(1, args.times + 1):
        outcome = agents._run(facts, client, agents.REVIEW_RUNS)
        outcomes.append(outcome)
        if args.times > 1:
            print(f"Draft {n} of {args.times}:")
        print(f"AI draft: {outcome.status}. {outcome.reason}")
        print(outcome.usage_line())
        for line in outcome.flagged():
            print(f"  - {line}")
    chosen = next((o for o in outcomes if o.passed), outcomes[-1])
    if chosen.draft is not None:
        print("\n" + agents.owner_email(chosen.draft, facts) + "\n")
    passed = sum(o.passed for o in outcomes)
    cost = sum(o.cost for o in outcomes)
    if args.times > 1:
        print(f"Passed {passed} of {args.times}. About ${cost:.4f} in all.")
    out = args.log.with_name("ai-redraft.json")
    out.write_text(json.dumps({
        **_record(chosen), "facts": facts, "times": args.times, "passed": passed,
        "total_cost_usd_estimate": round(cost, 6), "attempts": [_record(o) for o in outcomes],
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Saved {out}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
