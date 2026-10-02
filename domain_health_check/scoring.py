"""One number, 0 to 100, for the top of the report.

Weighted rather than a flat count, so a missing alt tag cannot drown an expired
certificate. Weights live here, keyed by check name, and never on CheckResult:
a check should not know what it is worth.

  3  costs money, loses mail, or breaks trust
  2  real but not urgent
  1  polish

Checks that did not run (ran=False) are left out of both sides, so a timeout
never looks like a failure. Nothing here is adjustable per report: the number
must not be tuned to look urgent, or to look reassuring.
"""

from __future__ import annotations

from typing import Iterable

from .models import CheckResult, Status

WEIGHTS: dict[str, int] = {
    # Website security
    "SSL certificate": 3,
    "TLS version": 2,
    "HSTS (always use HTTPS)": 2,
    "Content Security Policy": 1,
    "X-Content-Type-Options": 1,
    # Domain & DNS
    "Domain registration": 3,
    "Nameservers": 2,
    "DNSSEC": 2,
    # Email security: SPF, DKIM and DMARC all fail the same way, mail lands in spam
    "Mail servers (MX)": 3,
    "SPF (approved senders)": 3,
    "DKIM (email signatures)": 3,
    "DMARC (anti-spoofing policy)": 3,
    # Site health
    "Search engine blocking": 3,
    "Page title": 2,
    "Meta description": 2,
    "Canonical tag": 2,
    "Main heading": 2,
    "Mobile viewport": 2,
    "Structured data matches the page": 2,
    "Heading order": 1,
    "Image alt text": 1,
    "Social preview": 1,
    "Sitemap and robots": 1,
    "Page weight": 1,
    "Redirect chain": 1,
    # Speed, from PageSpeed Insights. Real-world speed only scores when Google publishes field data.
    "Real-world loading speed": 2,
    "Mobile speed": 1,
    "Accessibility": 1,
    "Best practices": 1,
    # Google Business Profile. No profile costs a local business more customers than every header combined.
    "Google Business Profile": 3,
    "Profile completeness": 2,
    "Profile website link": 2,
    "Reviews": 1,  # the count only; the star rating is never scored
}

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
    scored = [r for r in results if r.ran]
    possible = sum(WEIGHTS[r.name] for r in scored)
    if not possible:
        return None
    earned = sum(WEIGHTS[r.name] * CREDIT[r.status] for r in scored)
    return round(100 * earned / possible)


def reading(value: int) -> str:
    return next(text for floor, text in READINGS if value >= floor)
