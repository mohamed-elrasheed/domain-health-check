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
  8. findings and our published prices: the last page, each confirmed finding under its rung (pricelist.py)

Findings are ranked by what the problem costs the business (the ladder below), not by score weight:
weight was a proxy for severity and the wrong one. On a real report it opened with two email records
while the missing main heading and 31 undescribed images sat further down.
"""

from __future__ import annotations

from . import __version__, pricelist
from .checks import pagespeed, site
from .checks.site import favicon, links
from .ladder import CUSTOMER_FACING, LADDER, TIER
from .models import LOCAL, SITE, CheckResult, DomainReport, Status
from .scoring import WEIGHTS, credit, score

WORD = {Status.PASS: "Good", Status.WARN: "Could be improved", Status.FAIL: "Needs action",
        Status.INFO: "For information"}
NOT_CHECKED = "Not checked"
TOP = 3
NO_SCORE = "Score: not available - we could not load your website."


SELF_INTRO = ("You can do these yourself, from your website builder, your Google Business Profile or your domain "
              "registrar, without a developer.")
DEVELOPER_INTRO = ("These involve your domain settings, your server or your site's code. Pass them to whoever looks "
                   "after your website and email.")
PRICES_HEADING = "Findings and our published prices"
PRICES_INTRO = ("Each finding in this report, grouped by who can fix it, with the matching line from our published "
                "price list, where one applies: https://www.mizangroupllc.com/digital#pricing. Prices are fixed in "
                "writing before anything starts.")
NOTHING_TO_PRICE = "Every check we ran passed, so there is nothing here to fix or to price."
NOTHING_CONFIRMED = "Nothing we could confirm needs fixing, so there is nothing here to price."
UNCONFIRMED_NOT_PRICED = "Findings we could not confirm are not listed here."
# This report sells Mizan Digital Services, which lives at /digital; /services is the physical and networking
# division.
PRICING = ("If you would like us to take care of these, our prices are at "
           "https://www.mizangroupllc.com/digital#pricing, and we quote every job in writing first.")


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


def points_lost(r: CheckResult) -> float:
    """What a finding is costing, in one figure: its weight, which tracks the ladder, times how wrong it is."""
    return WEIGHTS.get(r.name, 1) * (1 - credit(r))


def costing_customers(report: DomainReport) -> list[CheckResult]:
    """Confirmed, customer-facing (tiers 1 to 4) findings that are materially wrong (less than half right), most
    points lost first, tier breaking ties. A category is not a cost: a tier-2 finding that is 90% right costs
    almost nothing, a tier-3 finding that is 0% right costs its whole weight. The top section and the one-line
    reading both come from this list, so they cannot disagree.

    Two measures, two jobs, on purpose. The filter (less than half right) decides what qualifies; points lost
    decides the order among what qualifies. So a heavy finding at 0.55 right can lose more points than a light
    one at 0.3 and still be left out. That is intended: this list is "worth doing", and a thing that is mostly
    right is not worth leading with, however heavy it is. It still appears in Fix it yourself or Needs a
    developer. Do not drop the filter to make the two measures agree."""
    found = [r for r in confirmed(report) if tier(r) <= CUSTOMER_FACING and credit(r) < 0.5]
    return sorted(found, key=lambda r: (-points_lost(r), _rank(r)))


def worth_doing(report: DomainReport) -> list[CheckResult]:
    """At most three, and never padded: a mild finding, a maybe, or an email or hardening item never takes a slot."""
    return costing_customers(report)[:TOP]


def rung(r: CheckResult, report: DomainReport | None = None) -> pricelist.Rung:
    """Which rung a finding sits on: the one config/pricelist.yaml gives its check, or platform when the report
    found a hosted builder that sets what the check measures. Raises KeyError for a check the file does not map,
    rather than guessing: a finding with no rung would leave the last page without a price line or an
    instruction."""
    found = pricelist.load().rung_of(r.name, report.platform if report else "")
    if found is None:
        raise KeyError(f"{r.name} has no rung in config/pricelist.yaml")
    return found


def answer(found: pricelist.Rung, r: CheckResult) -> list[str]:
    """What the last page puts beside a finding: its own fix, the rung's price lines, or what we found."""
    if found.shows == "prices":
        return [str(line) for line in found.prices]
    return [r.fix if found.shows == "fix" else r.summary]


def fix_yourself(report: DomainReport) -> list[CheckResult]:
    """Confirmed findings on the self rung, so this section and the last page cannot disagree."""
    return [r for r in confirmed(report) if rung(r, report).key == "self"]


def needs_developer(report: DomainReport) -> list[CheckResult]:
    """Everything else confirmed, except what a hosted builder sets: neither the owner nor a developer can change
    that, so it appears once, on the last page, with the platform sentence."""
    return [r for r in confirmed(report) if rung(r, report).key not in ("self", "platform")]


def _actionable(report: DomainReport) -> list[CheckResult]:
    """Findings someone can act on: every finding but the ones a hosted builder sets."""
    def platform_set(r: CheckResult) -> bool:
        found = pricelist.load().rung_of(r.name, report.platform)
        return found is not None and found.key == "platform"
    return [r for r in _findings(report) if not platform_set(r)]


def priced(report: DomainReport) -> list[tuple[pricelist.Rung, list[CheckResult]]]:
    """The last page: confirmed findings grouped by rung, self first, each group in the report's order. A finding
    we could not confirm is never priced. A rung with no findings is left out."""
    found = confirmed(report)
    groups = []
    for key in pricelist.RUNGS:
        members = [r for r in found if rung(r, report).key == key]
        if members:
            groups.append((pricelist.load().rungs[key], members))
    return groups


def prices_note(report: DomainReport) -> str:
    """The one sentence the last page says when it lists nothing, or the note under the list when a finding we
    could not confirm was left out of it."""
    if not priced(report):
        return NOTHING_CONFIRMED if worth_checking(report) else NOTHING_TO_PRICE
    return UNCONFIRMED_NOT_PRICED if worth_checking(report) else ""


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
    # "Costing you customers" only for customer-facing findings that are materially wrong (less than half right):
    # a description 17 characters too long is not costing anyone customers, a missing one is.
    costly = costing_customers(report)
    if len(costly) >= 3:
        return value, "Nothing on your site is broken. Here is what is costing you customers."
    if costly:
        return value, f"Nothing on your site is broken. {_things(len(costly))} could be costing you customers."
    if found:
        many = "A few" if len(found) <= 3 else str(len(found))
        if all(tier(r) > CUSTOMER_FACING for r in found):
            return value, f"Nothing on your site is broken. {many} behind-the-scenes settings could be stronger."
        return value, f"Nothing on your site is broken. {many} small things could be better."
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
    if not _actionable(report):
        return [("", "Nothing here needs fixing, so there is nothing you need to do with this report."),
                ("Questions?", "Reply to the email this came with.")]
    if report.count(Status.FAIL):
        first = ("The items marked as needing action are broken today, so they are worth doing first. The rest are "
                 "worth passing to whoever looks after your website and email.")
    elif fix_yourself(report):
        first = ("Nothing here is urgent. You can do the items under \"Fix it yourself\" without a developer; the "
                 "rest are worth passing to whoever looks after your website and email.")
    else:
        first = ("Nothing here is urgent. The items above are worth passing to whoever looks after your website and "
                 "email.")
    return [("", first),
            ("Want us to handle it?", "Reply to the email this came with and tell us which items you want done, and "
                                      "we will quote a fixed price in writing before any work starts.")]


def about(report: DomainReport) -> str:
    sources = ("DNS records, the domain registry, and a single ordinary visit to the website's home page, along with "
               "the robots.txt and sitemap files that search engines read")
    if report.rendered:
        sources = ("DNS records, the domain registry, an ordinary visit to the website's home page, along with the "
                   "robots.txt and sitemap files that search engines read, and one more visit to that page in a "
                   "standard web browser, to see it the way a visitor does")
    if any(r.ran and r.name in (links.SAME_SITE, links.OTHER_SITES) for r in report.results):
        sources += ", a single request to each link on that page to confirm it still leads somewhere"
    if any(r.ran and r.name == favicon.NAME for r in report.results):
        sources += ", the site's browser tab icon"
    if any(r.ran and r.name in pagespeed.LAB for r in report.results):
        sources += ", plus Google's own PageSpeed Insights test of that page"
    if any(r.category == LOCAL for r in report.results):
        sources += ", and a search of Google's public business listings"
    return (f"These results come only from information that is publicly visible to anyone on the internet: {sources}. "
            "Nothing was scanned, probed or logged into. The checks show how things looked at the time above; "
            "settings can change at any time.")


def stamp(report: DomainReport) -> str:
    """Which build of the tool wrote this report, and when it ran, for the footer of every page."""
    return f"domain-health-check {__version__} · run {report.checked_at.day} {report.checked_at:%B %Y}"
