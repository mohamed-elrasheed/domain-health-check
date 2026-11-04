"""Measure the findings agent on questions whose right answers code already knows.

    python scripts/eval_ask.py reports/mizangroupllc.com/2026-11-04

Builds the questions from the report folder itself, asks the agent each one, and grades the answers with code,
never with another model: the answer must contain what the report says (the WARN checks, the score, the request
count, who can fix a finding), the unanswerable question must get "The report does not say.", and every cited
source must be a check the agent actually looked up. Results go beside the report as eval-ask.json, which stays
out of git with reports/. Makes real API calls (a few cents per question) and needs ANTHROPIC_API_KEY in .env.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from domain_health_check import agents, ask, pricelist
from domain_health_check.config import load_env


def cases(folder: ask.Folder) -> list[dict]:
    """(question, the strings a right answer must contain, a check the answer must cite or None)."""
    checks = folder.list_checks()
    warns = [c["name"] for c in checks if c["status"] in ("WARN", "FAIL")]
    unchecked = [c["name"] for c in checks if c["status"] == "NOT CHECKED"]
    overview = folder.get_overview()
    out = [
        {"question": "Which checks have a WARN or FAIL status?", "expect": warns, "cite": None},
        {"question": "What score did the report give, out of 100?", "expect": [str(overview["score"])], "cite": None},
        {"question": "Which checks were not checked?", "expect": unchecked, "cite": None},
        {"question": "How many requests did the report make in total?",
         "expect": [str(overview["requests_made"])], "cite": None},
        {"question": "What did the person who asked for this report write in the form?",
         "expect": ["The report does not say"], "cite": None},
    ]
    if warns:
        first = folder.get_check(warns[0])
        rung = pricelist.load().rungs.get(next((r.get("rung") for r in folder.record["results"]
                                                if r["name"] == warns[0]), "") or "")
        out.append({"question": f"What does the report say to do about {warns[0]}, and why?",
                    "expect": [], "cite": first["name"]})
        if rung:
            out.append({"question": f"Who can fix {warns[0]}?", "expect": [rung.label], "cite": first["name"]})
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("folder", type=Path, help="a report folder with report.json in it")
    args = parser.parse_args(argv)

    folder = ask.Folder(args.folder)
    load_env(Path(".env"))
    client, why = agents.make_client(require_switch=False)
    if client is None:
        print(why, file=sys.stderr)
        return 2

    rows, cost = [], 0.0
    for case in cases(folder):
        answer = ask.ask(folder, case["question"], client)
        cost += answer.cost
        missing = [e for e in case["expect"] if e.lower() not in answer.text.lower()]
        cited = case["cite"] is None or case["cite"] in answer.sources
        passed = answer.status == "answered" and not missing and cited and not answer.problems
        rows.append({**case, "passed": passed, "status": answer.status, "missing": missing, "cited": cited,
                     "problems": answer.problems, "steps": [s["tool"] for s in answer.steps],
                     "answer": answer.text, "cost_usd_estimate": round(answer.cost, 6)})
        print(f"{'pass' if passed else 'FAIL':4}  {len(answer.steps)} step{'s' if len(answer.steps) != 1 else ' '}  "
              f"{case['question']}")
        for why_not in [f"missing {m!r}" for m in missing] + ([] if cited else [f"did not cite {case['cite']}"]) \
                + answer.problems + ([answer.text] if answer.status != "answered" else []):
            print(f"        {why_not}")

    summary = {"model": ask.MODEL, "folder": str(args.folder), "questions": len(rows),
               "passed": sum(r["passed"] for r in rows), "cost_usd_estimate": round(cost, 6), "rows": rows}
    out = args.folder / "eval-ask.json"
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nPassed {summary['passed']} of {summary['questions']}. About ${cost:.4f}. Saved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
