"""One number, 0 to 100, for the top of the report.

Weighted rather than a flat count, so a missing alt tag cannot drown an expired
certificate. Weights live here, keyed by check name, and never on CheckResult:
a check should not know what it is worth.

Each check's weight comes from its tier on the owner-cost ladder (ladder.py),
the same ladder that orders the report, so the number and the narrative rank
problems the same way: reach 5, understanding 4, local listing 3, speed 2,
email 1, hardening 1. DKIM and DMARC cannot move the score more than a
missing main heading does.

Credit for a finding (rule B):

  PASS earns full credit, FAIL none.
  A WARN that is a matter of degree carries a measure from its check (14 of 40
  images described is 0.35), and earns exactly that.
  A WARN that is binary, present or absent, earns by tier: nothing in tiers 1
  and 2, a quarter in tiers 3 and 4, half in tiers 5 and 6.

Why a confirmed absence in tiers 1 and 2 earns nothing: half credit was
correct when WARN meant "this might be a problem". It is not correct now.
Uncertain findings go to "Worth checking", so every WARN left in the main list
is a confirmed, observed defect. A meta description either exists or it does
not; there is no partial credit for sort-of-having-one. Confirmed absent
scores zero. Graded checks keep their middle: "heading order skipped twice"
and "no main heading at all" are not the same site, and proportional credit
says so without a special case (0 of 31 images described scores zero, 14 of 40
does not).

Left out of both sides: checks that did not run (a timeout must not look like
a failure), INFO results (a fact, not a grade) and findings we could not
confirm (certain=False). A maybe neither costs nor earns points.

Nothing here is adjustable per report: the number must not be tuned to look
urgent, or to look reassuring.
"""

from __future__ import annotations

from typing import Iterable

from .ladder import TIER, TIER_WEIGHT
from .models import CheckResult, Status

WEIGHTS: dict[str, int] = {name: TIER_WEIGHT[tier] for name, (tier, _) in TIER.items()}

BINARY_WARN_CREDIT = {1: 0.0, 2: 0.0, 3: 0.25, 4: 0.25, 5: 0.5, 6: 0.5}  # by tier on the ladder

READINGS = [  # (lowest score in the band, one-line reading)
    (90, "in good shape"),
    (70, "a few things worth fixing"),
    (50, "several things need attention"),
    (0, "needs work in a few areas"),
]


def credit(r: CheckResult) -> float:
    """The share of a check's weight a result earns, 0 to 1."""
    if r.status is Status.PASS:
        return 1.0
    if r.status is Status.FAIL:
        return 0.0
    if r.measure is not None:  # graded: a matter of degree
        return min(max(r.measure, 0.0), 1.0)
    return BINARY_WARN_CREDIT[TIER[r.name][0]]  # binary: confirmed absent


def counted(r: CheckResult) -> bool:
    """Whether a result is part of the score: it ran, it is a grade rather than a fact, and it is confirmed."""
    return r.ran and r.status is not Status.INFO and r.certain


def score(results: Iterable[CheckResult]) -> int | None:
    """round(100 * earned / possible) over the results that count, or None when none do.
    Raises KeyError for a check missing from WEIGHTS rather than guessing its worth."""
    scored = [r for r in results if counted(r)]
    possible = sum(WEIGHTS[r.name] for r in scored)
    if not possible:
        return None
    earned = sum(WEIGHTS[r.name] * credit(r) for r in scored)
    return round(100 * earned / possible)


def reading(value: int) -> str:
    return next(text for floor, text in READINGS if value >= floor)
