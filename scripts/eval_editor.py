"""Measure the editor on a message a person has already judged, so we know whether a failure is the writer's or
the editor's.

    python scripts/eval_editor.py reports/<domain>/<date>/edited.txt --times 5

The file holds one whole owner message, as it would be sent. Write a message a careful person would send without
changes; if the editor fails it, the editor is too strict, and its reasons say where. Put a known flaw in a copy
and it should fail every time. Each run is one editor call (about 1 to 2 cents). The message stays in reports/,
which is never committed, because it names a business.

The editor sees only the message, as in production. Nothing here changes what the pipeline does.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from domain_health_check import agents
from domain_health_check.config import load_env


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("message", type=Path, help="a text file holding one whole owner message")
    parser.add_argument("--times", type=int, default=5, help="how many times to run the editor on it")
    parser.add_argument("--model", default=agents.EDITOR_MODEL, help="the editor model")
    args = parser.parse_args(argv)

    text = args.message.read_text(encoding="utf-8").strip()
    load_env(Path(".env"))
    client, why = agents.make_client(require_switch=False)
    if client is None:
        print(why, file=sys.stderr)
        return 2
    passed, cost = 0, 0.0
    for n in range(1, args.times + 1):
        review, usage = agents.edit(text, client, model=args.model)
        passed += review.passed
        cost += sum(u.cost for u in usage)
        print(f"Run {n} of {args.times}: {'passed' if review.passed else 'failed'}. {review.reason}")
        for line in review.voice_problems:
            print(f"  - {line}")
    print(f"Editor passed it {passed} of {args.times}. About ${cost:.4f} in all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
