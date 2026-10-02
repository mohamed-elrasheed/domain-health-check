"""What the report says and in what order, independent of format.

report.py (Markdown) and pdf.py (PDF) both render a DomainReport through these
functions, so the two documents cannot disagree. Neither renderer parses the
other's output: building the PDF by parsing Markdown once dropped a whole
finding without any error.

Sections, per docs/REPORT-SPEC.md:
  1. header: domain, date, score and a reading that says plainly whether anything is broken
  2. worth doing: the three confirmed findings that cost the owner most, in brief
  3. fix it yourself: confirmed findings the owner can fix from their website builder or Google profile
  4. needs a developer: every other confirmed finding
  5. worth checking: findings we could not confirm, near the end, in honest wording
  6. everything we checked, what is already working, what we could not check
  7. what happens next: what to do with the report, and how to reach us

Findings are ranked by what the problem costs the business (the ladder below), not by score weight:
weight was a proxy for severity and the wrong one. On a real report it opened with two email records
while the missing main heading and 31 undescribed images sat further down.
"""

from __future__ import annotations

from .checks import pagespeed, site
from .models import LOCAL, SITE, CheckResult, DomainReport, Status
from .scoring import score

WORD = {Status.PASS: "Good", Status.WARN: "Could be improved", Status.FAIL: "Needs action",
        Status.INFO: "For information"}
NOT_CHECKED = "Not checked"
TOP = 3
NO_SCORE = "Score: not available - we could not load your website."

# The owner-cost ladder. Within a tier, the order listed is the order shown.
LADDER = [
    # 1. Customers cannot reach the site.
    ["Search engine blocking", "SSL certificate", "Domain registration"],
    # 2. Google cannot understand the site.
    ["Main heading", "Meta description", "Page title", "Image alt text", "Heading order", "Canonical tag",
     "Sitemap and robots", "Structured data matches the page", "Social preview"],
    # 3. Customers cannot find the business locally.
    ["Google Business Profile", "Profile completeness", "Profile website link", "Reviews"],
    # 4. The site is slow enough that people leave.
    ["Real-world loading speed", "Mobile speed", "Page weight", "Mobile viewport", "Redirect chain", "Accessibility"],
    # 5. Email can be spoofed.
    ["DMARC (anti-spoofing policy)", "SPF (approved senders)", "DKIM (email signatures)", "Mail servers (MX)"],
    # 6. Hardening.
    ["HSTS (always use HTTPS)", "Content Security Policy", "X-Content-Type-Options", "DNSSEC", "TLS version",
     "Nameservers", "Best practices"],
]
TIER = {name: (tier, position) for tier, names in enumerate(LADDER, start=1) for position, name in enumerate(names)}
CUSTOMER_FACING = 4  # tiers 1 to 4 cost customers; 5 and 6 are behind the scenes

# What an owner can fix from their website builder or their Google profile, without DNS, server settings or code.
SELF_FIX = {"Page title", "Meta description", "Image alt text", "Main heading", "Heading order", "Social preview",
            "Google Business Profile", "Profile completeness", "Profile website link", "Reviews"}
# This report sells Mizan Digital Services, which lives at /digital; /services is the physical and networking
# division.
PRICING = ("If you would like us to take care of these, our prices are at https://www.mizangroupllc.com/digital, "
           "and we quote every job in writing first.")


def label(r: CheckResult) -> str:
    """A check that did not run verified nothing, so it never reads as Good or Could be improved."""
    return WORD[r.status] if r.ran else NOT_CHECKED


def tier(r: CheckResult) -> int:
    return TIER.get(r.name, (len(LADDER), 99))[0]


def _rank(r: CheckResult) -> tuple:
    """Tier, then confirmed before uncertain, then broken before risky, then the ladder's order within the tier."""
    level, position = TIER.get(r.name, (len(LADDER), 99))
    return level, not r.certain, -r.status.rank, position


def _findings(report: DomainReport) -> list[CheckResult]:
    found = [r for r in report.results if r.ran and r.status in (Status.WARN, Status.FAIL)]
    return sorted(found, key=_rank)


def confirmed(report: DomainReport) -> list[CheckResult]:
    return [r for r in _findings(report) if r.certain]


def worth_doing(report: DomainReport) -> list[CheckResult]:
    """Up to three confirmed, customer-facing findings (tiers 1 to 4). Three is a maximum, not a quota: email and
    hardening findings are never promoted to fill a slot, and a maybe never gets top billing."""
    return [r for r in confirmed(report) if tier(r) <= CUSTOMER_FACING][:TOP]


def fix_yourself(report: DomainReport) -> list[CheckResult]:
    return [r for r in confirmed(report) if r.name in SELF_FIX]


def needs_developer(report: DomainReport) -> list[CheckResult]:
    return [r for r in confirmed(report) if r.name not in SELF_FIX]


def worth_checking(report: DomainReport) -> list[CheckResult]:
    """Findings we could not confirm: shown near the end, in their own honest wording."""
    return [r for r in _findings(report) if not r.certain]


def brief(r: CheckResult) -> str:
    """Two or three sentences for the top of the report: what we found and why it matters. No technical detail."""
    why = r.explanation.split(". ")[0].rstrip(".") + "."
    return f"{r.summary} {why}"


def working(report: DomainReport) -> list[CheckResult]:
    return [r for r in report.results if r.ran and r.status in (Status.PASS, Status.INFO)]


def _things(n: int) -> str:
    words = {1: "One thing", 2: "Two things", 3: "Three things"}
    return words.get(n, f"{n} things")


def headline(report: DomainReport) -> tuple[int | None, str]:
    """(score, one-line reading). No score when nothing ran, and none when the website itself could not be
    loaded: a number computed over DNS and email alone reads as "my site is fine". The reading tracks what was
    found, not the score band: fifteen warnings is not "a few", and saying plainly that nothing is broken is
    more credible than a manufactured failure."""
    if not report.website_loaded:
        return None, NO_SCORE
    value = score(report.results)
    if value is None:
        return None, "We could not complete enough checks to give your site a score."
    broken = report.count(Status.FAIL)
    if broken:
        verb = "is" if broken == 1 else "are"
        return value, f"{_things(broken)} on your site {verb} broken today."
    found = confirmed(report)
    customer = [r for r in found if tier(r) <= CUSTOMER_FACING]
    if len(customer) >= 3:
        return value, "Nothing on your site is broken. Here is what is costing you customers."
    if customer:
        return value, f"Nothing on your site is broken. {_things(len(customer))} could be costing you customers."
    if found:
        many = "A few" if len(found) <= 3 else str(len(found))
        return value, f"Nothing on your site is broken. {many} behind-the-scenes settings could be stronger."
    return value, "Nothing on your site is broken, and everything we checked looks good."


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
    if report.count(Status.INFO):
        parts.append(f"{report.count(Status.INFO)} for information")
    if report.not_checked:
        parts.append(f"{len(report.not_checked)} not checked")
    return " · ".join(parts)


def next_steps(report: DomainReport) -> list[tuple[str, str]]:
    """(lead, rest) lines. What they can do with the report and how to reach us; nothing else.
    In particular no promise to run the checks again: re-checks belong to the paid care plan."""
    if not _findings(report):
        return [("", "Nothing here needs fixing, so there is nothing you need to do with this report."),
                ("Questions?", "Reply to the email this came with.")]
    if report.count(Status.FAIL):
        first = ("The items marked as needing action are broken today, so they are worth doing first. The rest are "
                 "worth passing to whoever looks after your website and email.")
    elif fix_yourself(report):
        first = ("Nothing here is urgent. You can do the items under \"Fix it yourself\" from your website builder; "
                 "the rest are worth passing to whoever looks after your website and email.")
    else:
        first = ("Nothing here is urgent. The items above are worth passing to whoever looks after your website and "
                 "email.")
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
