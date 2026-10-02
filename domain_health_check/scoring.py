"""One number, 0 to 100, for the top of the report.

Weighted rather than a flat count, so a missing alt tag cannot drown an expired
certificate. Weights live here, keyed by check name, and never on CheckResult:
a check should not know what it is worth.

Each check's weight comes from its tier on the owner-cost ladder (ladder.py),
the same ladder that orders the report, so the number and the narrative rank
problems the same way: reach 5, understanding 4, local listing 3, speed 2,
email 1, hardening 1. DKIM and DMARC cannot move the score more than a
missing main heading does.

Checks that did not run (ran=False) are left out of both sides, so a timeout
never looks like a failure. Nothing here is adjustable per report: the number
must not be tuned to look urgent, or to look reassuring.
"""

from __future__ import annotations

from typing import Iterable

from .ladder import TIER, TIER_WEIGHT
from .models import CheckResult, Status

WEIGHTS: dict[str, int] = {name: TIER_WEIGHT[tier] for name, (tier, _) in TIER.items()}

CREDIT = {Status.PASS: 1.0, Status.WARN: 0.5, Status.FAIL: 0.0}

READINGS = [  # (lowest score in the band, one-line reading)
    (90, "in good shape"),
    (70, "a few things worth fixing"),
    (50, "several things need attention"),
    (0, "needs work in a few areas"),
]


def score(results: Iterable[CheckResult]) -> int | None:
    """round(100 * earned / possible) over the checks that ran, or None when none did.
    Raises KeyError for a check missing from WEIGHTS rather than guessing its worth."""
    scored = [r for r in results if r.ran and r.status is not Status.INFO]  # INFO is a fact, not a grade
    possible = sum(WEIGHTS[r.name] for r in scored)
    if not possible:
        return None
    earned = sum(WEIGHTS[r.name] * CREDIT[r.status] for r in scored)
    return round(100 * earned / possible)


def reading(value: int) -> str:
    return next(text for floor, text in READINGS if value >= floor)
