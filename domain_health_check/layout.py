"""What the report says and in what order, independent of format.

report.py (Markdown) and pdf.py (PDF) both render a DomainReport through these
functions, so the two documents cannot disagree. Neither renderer parses the
other's output: building the PDF by parsing Markdown once dropped a whole
finding without any error.

Sections, per docs/REPORT-SPEC.md:
  1. header: domain, date, score and its one-line reading
  2. worth doing: the three findings most worth acting on
  3. also worth improving: every other finding, so nothing is dropped
  4. everything we checked: the full table, passes included
  5. what is already working
  6. what we could not check
  7. what happens next: what to do with the report, and how to reach us
"""

from __future__ import annotations

from .checks import pagespeed, site
from .models import LOCAL, SITE, CheckResult, DomainReport, Status
from .scoring import WEIGHTS, reading, score

WORD = {Status.PASS: "Good", Status.WARN: "Could be improved", Status.FAIL: "Needs action"}
NOT_CHECKED = "Not checked"
TOP = 3

SENTENCE = {
    "in good shape": "Your site is in good shape.",
    "a few things worth fixing": "Your site has a few things worth fixing.",
    "several things need attention": "Several things on your site need attention.",
    "needs work in a few areas": "Your site needs work in a few areas.",
}


def label(r: CheckResult) -> str:
    """A check that did not run verified nothing, so it never reads as Good or Could be improved."""
    return WORD[r.status] if r.ran else NOT_CHECKED


NO_SCORE = "Score: not available - we could not load your website."


def headline(report: DomainReport) -> tuple[int | None, str]:
    """(score, one-line reading). No score when nothing ran, and none when the website itself could not be
    loaded: a number computed over DNS and email alone reads as "my site is fine". Findings still print."""
    if not report.website_loaded:
        return None, NO_SCORE
    value = score(report.results)
    if value is None:
        return None, "We could not complete enough checks to give your site a score."
    return value, SENTENCE[reading(value)]


def coverage(report: DomainReport) -> str:
    """The line under a missing score, saying what the report does cover."""
    if report.website_loaded:
        return ""
    if not any(r.ran for r in report.results if r.category != SITE):
        return ""
    robots_finding = any(r.category == SITE and r.ran for r in report.results)
    covered = "your domain and email, plus your robots.txt file" if robots_finding else "your domain and email"
    return f"This report covers {covered} only."


def not_checked(report: DomainReport) -> list[CheckResult]:
    """Not-run results, minus the not-loaded row when the report already leads with the site being unreachable."""
    return [r for r in report.not_checked if not (report.unreachable and r.name == site.PAGE_LOADED)]


def counts(report: DomainReport) -> str:
    parts = [f"{report.count(Status.PASS)} checks passed", f"{report.count(Status.WARN)} could be improved",
             f"{report.count(Status.FAIL)} need action"]
    if report.not_checked:
        parts.append(f"{len(report.not_checked)} not checked")
    return " · ".join(parts)


def _to_act_on(report: DomainReport) -> list[CheckResult]:
    """Every finding that ran and is not a pass: by weight, then broken before risky."""
    found = [r for r in report.results if r.ran and r.status is not Status.PASS]
    return sorted(found, key=lambda r: (-WEIGHTS.get(r.name, 1), -r.status.rank))


def worth_doing(report: DomainReport) -> list[CheckResult]:
    return _to_act_on(report)[:TOP]


def also_worth_improving(report: DomainReport) -> list[CheckResult]:
    return _to_act_on(report)[TOP:]


def working(report: DomainReport) -> list[CheckResult]:
    return [r for r in report.results if r.ran and r.status is Status.PASS]


def next_steps(report: DomainReport) -> list[tuple[str, str]]:
    """(lead, rest) lines. What they can do with the report and how to reach us; nothing else.
    In particular no promise to run the checks again: re-checks belong to the paid care plan."""
    to_act_on = _to_act_on(report)
    if not to_act_on:
        return [("", "Nothing here needs fixing, so there is nothing you need to do with this report."),
                ("Questions?", "Reply to the email this came with.")]
    if report.count(Status.FAIL):
        first = ("The items marked as needing action are broken today, so they are worth doing first. The rest are "
                 "worth passing to whoever looks after your website and email.")
    else:
        items = "item" if len(to_act_on) == 1 else "items"
        first = (f"Nothing here is urgent. The {items} above are worth passing to whoever looks after your website "
                 "and email.")
    return [("", first),
            ("Want us to handle it?", "Reply to the email this came with and tell us which items you want done, and "
                                      "we will quote a fixed price in writing before any work starts.")]


def about(report: DomainReport) -> str:
    sources = ("DNS records, the domain registry, and a single ordinary visit to the website's home page, along with "
               "the robots.txt and sitemap files that search engines read")
    if any(r.ran and r.name in pagespeed.LAB for r in report.results):
        sources += ", plus Google's own PageSpeed Insights test of that page"
    if any(r.category == LOCAL for r in report.results):
        sources += ", and a search of Google's public business listings"
    return (f"These results come only from information that is publicly visible to anyone on the internet: {sources}. "
            "Nothing was scanned, probed or logged into. The checks show how things looked at the time above; "
            "settings can change at any time.")
