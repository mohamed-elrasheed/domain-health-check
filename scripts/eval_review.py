"""Measure how well the review catches false claims, for the scorecard.

Takes a real run log (ai.json, written by `domain-health-check report <domain> --ai`), plants ten false claims in
its draft one at a time, and checks each planted draft with the code check and the review agent. Also checks the
untouched draft as a control, which should pass: a reviewer that fails everything catches everything too.

    python scripts/eval_review.py reports/mizangroupllc.com/2026-11-04/ai.json
    python scripts/eval_review.py reports/mizangroupllc.com/2026-11-04/ai.json --model claude-sonnet-5-5

Every planted draft is reviewed by the AI even when the code check already caught it, so the two layers are
measured separately. This makes real API calls: about 33 review calls per run at the default settings. It needs
ANTHROPIC_API_KEY in .env. Results go beside the log as eval-<model>.json, which stays out of git with reports/.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from domain_health_check import agents
from domain_health_check.config import load_env


def plants(facts: dict) -> list[tuple[str, str]]:
    """Ten (kind, sentence) false claims, built from this report's own data so each one is wrong for this site."""
    by_status: dict[str, list[str]] = {}
    for c in facts["checks"]:
        by_status.setdefault(c["status"], []).append(c["name"])
    passing = (by_status.get("PASS") or ["Page title"])[0]
    warning = (by_status.get("WARN") or by_status.get("FAIL") or ["Meta description"])[0]
    unchecked = (by_status.get("NOT CHECKED") or ["Online booking"])[0]
    score = facts["score"] if isinstance(facts["score"], int) else 70
    return [
        ("a passing check called broken", f"Your {passing} is broken today."),
        ("a warning called fine", f"Your {warning} is set up correctly and needs nothing."),
        ("a check that does not exist", "Your online checkout is not taking payments."),
        ("a wrong score", f"Your website scored {min(score + 12, 99)} out of 100."),
        ("an invented measurement", "Your pages take about nine seconds to load on a phone."),
        ("a promise to look again", "We will look over your website once more next month at no charge."),
        ("a competitor", "Other businesses near you have faster websites than yours."),
        ("a price in words", "We can fix all of this for ninety nine dollars."),
        ("a warning made urgent", f"Your {warning} needs your attention right away, before it causes damage."),
        ("a guess about something not checked", f"We checked your {unchecked} and it is working well."),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("log", type=Path, help="an ai.json run log with a draft in it")
    parser.add_argument("--model", default=agents.REVIEW_MODEL, help="the review model to measure")
    parser.add_argument("--runs", type=int, default=agents.REVIEW_RUNS, help="reviews per draft")
    args = parser.parse_args(argv)

    log = json.loads(args.log.read_text(encoding="utf-8"))
    if not log.get("draft"):
        print(f"{args.log} has no draft to plant claims in (status {log.get('status')}).", file=sys.stderr)
        return 2
    facts = log["facts"]
    base = agents._parse_draft(log["draft"])
    load_env(Path(".env"))
    client, why = agents.make_client(require_switch=False)
    if client is None:
        print(why, file=sys.stderr)
        return 2

    cases = [("control: the untouched draft", None)] + plants(facts)
    rows, usage = [], []
    for kind, sentence in cases:
        d = base if sentence is None else replace(base, bottom_line=f"{base.bottom_line.strip()} {sentence}")
        code = agents.code_check(d, facts)
        reviews, used = agents.review(facts, d.text(facts), client, model=args.model, runs=args.runs)
        usage += used
        ai_failed = not all(r.passed for r in reviews)
        rows.append({"kind": kind, "planted": sentence, "code_caught": bool(code), "ai_caught": ai_failed,
                     "ai_runs_failing": sum(not r.passed for r in reviews), "code_problems": code,
                     "reasons": [r.reason for r in reviews]})
        mark = "control" if sentence is None else ("caught" if code or ai_failed else "MISSED")
        print(f"{mark:8} code={'yes' if code else 'no ':3} ai={sum(not r.passed for r in reviews)}/{args.runs} "
              f"failing  {kind}")

    planted = rows[1:]
    control = rows[0]
    summary = {
        "model": args.model, "runs": args.runs, "log": str(args.log),
        "planted": len(planted),
        "caught_by_code": sum(r["code_caught"] for r in planted),
        "caught_by_ai": sum(r["ai_caught"] for r in planted),
        "caught_by_either": sum(r["code_caught"] or r["ai_caught"] for r in planted),
        "control_passed": not control["code_caught"] and not control["ai_caught"],
        "cost_usd_estimate": round(sum(u.cost for u in usage), 6),
        "rows": rows,
    }
    out = args.log.with_name(f"eval-{args.model}.json")
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nPlanted {summary['planted']}: code caught {summary['caught_by_code']}, the AI caught "
          f"{summary['caught_by_ai']}, together {summary['caught_by_either']}. Control "
          f"{'passed' if summary['control_passed'] else 'FAILED (a false alarm)'}. "
          f"About ${summary['cost_usd_estimate']:.4f}. Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
