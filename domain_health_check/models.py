"""Data types shared by every check, the report writer and the terminal output."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Report sections. Each check belongs to one of these.
WEBSITE = "Website security"
DOMAIN = "Domain & DNS"
EMAIL = "Email security"
SITE = "Site health"
LOCAL = "Google Business Profile"


class Status(str, Enum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"  # checked and fine, but nothing to grade: shown, never scored, never a finding

    @property
    def rank(self) -> int:
        """Higher is worse, so max() finds the most serious result."""
        return {"PASS": 0, "INFO": 0, "WARN": 1, "FAIL": 2}[self.value]


@dataclass
class CheckResult:
    category: str
    name: str
    status: Status
    summary: str  # one sentence: what we found
    explanation: str  # plain English: why this matters
    fix: str = ""  # what to do about it (empty when there is nothing to do)
    details: list[str] = field(default_factory=list)  # technical specifics for an IT provider
    ran: bool = True  # False when there was nothing we could measure; the score leaves these out
    certain: bool = True  # False when the finding is a maybe; it never opens the report
    # For a graded finding, how much of the thing is right, 0 to 1 (14 of 40 images described is 0.35).
    # None means binary: present or absent, nothing in between. scoring.py turns this into credit.
    measure: float | None = None


@dataclass
class DomainReport:
    domain: str
    checked_at: datetime
    results: list[CheckResult]
    website_loaded: bool = True  # False: no score is shown, because one would cover DNS and email alone
    unreachable: str = ""  # set when a visitor cannot reach the site; the report leads with it
    rendered: bool = False  # the home page was loaded a second time, in a browser, to judge what a visitor sees
    # Why this report is not complete: a check that crashed, a page or browser load that failed, a speed test
    # that did not run. Empty means every part of the report ran. The CLI exits 0 only when it is empty.
    incomplete: list[str] = field(default_factory=list)
    requests: list = field(default_factory=list)  # requestlog.Request, every request the report made
    # The hosted website builder serving the site, when one was recognized (platform.py), and what gave it away.
    platform: str = ""
    platform_evidence: str = ""
    # Distinct links found on the home page, and how many of them got a request (linkcheck.py).
    links_found: int = 0
    links_requested: int = 0
    # The content management system the site runs on (platform.detect_cms), and what gave it away.
    cms: str = ""
    cms_evidence: str = ""
    # Page 1: the home page at phone width (PNG bytes, from the report's own browser load), and the anonymous
    # comparison with the top-ranked nearby listings of the same type: {"place_type", "count", "reviews", "rating",
    # "own_reviews", "own_rating"}. Neither is ever committed: the screenshot is written under reports/.
    screenshot: bytes = field(default=b"", repr=False)
    nearby: dict | None = None

    @property
    def complete(self) -> bool:
        return not self.incomplete

    # A result that did not run verified nothing, so its status never counts as a pass, a warning or a failure.

    @property
    def overall(self) -> Status:
        return max((r.status for r in self.results if r.ran), key=lambda s: s.rank, default=Status.PASS)

    def count(self, status: Status) -> int:
        return sum(1 for r in self.results if r.ran and r.status is status)

    @property
    def not_checked(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ran]
