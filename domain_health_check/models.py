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

    # A result that did not run verified nothing, so its status never counts as a pass, a warning or a failure.

    @property
    def overall(self) -> Status:
        return max((r.status for r in self.results if r.ran), key=lambda s: s.rank, default=Status.PASS)

    def count(self, status: Status) -> int:
        return sum(1 for r in self.results if r.ran and r.status is status)

    @property
    def not_checked(self) -> list[CheckResult]:
        return [r for r in self.results if not r.ran]
