"""Do the links on the home page work?

The requests are made in linkcheck.py, under the capped rule in CLAUDE.md, before any check runs; this module
only judges the outcomes. Links to pages on the site and links to other sites are two results: the owner
controls their own pages, but not someone else's, so a broken link to another site is never more than a WARN
and carries less weight.
"""

from __future__ import annotations

from ...fetcher import PageContext
from ...linkcheck import LinkResult
from ...models import SITE, CheckResult, Status

SAME_SITE = "Broken links"
OTHER_SITES = "Links to other sites"
SHOWN = 10  # broken links listed in full; the rest are counted

EXPLANATION = (
    "A link that leads to an error page is a dead end for a visitor who clicked it, and search engines read "
    "broken links as a sign that a site is not looked after."
)
OTHER_EXPLANATION = (
    "Links to other websites can stop working when those sites move or close a page. You cannot fix their site, "
    "but you can update or remove the link."
)
FIX = ("In your website builder, find each link listed in the technical details and point it at the right page, or "
       "remove it.")


def _line(r: LinkResult) -> str:
    where = f" (ended at {r.final_url})" if r.final_url and r.final_url != r.url else ""
    return f"\"{r.text}\" links to {r.url}{where}: {r.detail}"


def evaluate_links(results: list[LinkResult], same_site: bool, rendered: bool) -> CheckResult:
    """The links of one kind (this site, or other sites). The caller passes only kinds the page has."""
    name = SAME_SITE if same_site else OTHER_SITES
    explanation = EXPLANATION if same_site else OTHER_EXPLANATION
    where = "to other pages on your site" if same_site else "to other websites"
    mine = [r for r in results if r.same_site == same_site]
    checked = [r for r in mine if r.outcome in ("ok", "broken")]
    broken = [r for r in checked if r.broken]
    source = ("Links read from the page after a browser ran it, including menus that open on a tap." if rendered
              else "Links read from the page as delivered, before any scripts ran.")
    details = [source, f"Verified {len(checked)} of {len(mine)} links {where}, one request each (HEAD, or GET when "
                       "HEAD is refused), following at most 3 redirects."]
    details += [_line(r) for r in broken[:SHOWN]]
    if len(broken) > SHOWN:
        details.append(f"And {len(broken) - SHOWN} more.")
    unverified = [r for r in mine if r.outcome in ("not verified", "not requested")]
    details += [f"Not verified: {r.url}: {r.detail}" for r in unverified]

    def result(status: Status, summary: str, fix: str = "", ran: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, name, status, summary, explanation, fix, details, ran, measure=measure)

    if not checked:
        return result(Status.WARN, f"We could not verify the links on your home page {where} this time.",
                      "Nothing to do based on this report.", ran=False)
    if broken:
        if len(checked) == 1:
            count, verb = "The one link", "does"
        else:
            count, verb = f"{len(broken)} of the {len(checked)} links", "does" if len(broken) == 1 else "do"
        return result(Status.WARN, f"{count} on your home page {where} {verb} not work.", FIX,
                      measure=(len(checked) - len(broken)) / len(checked))
    every = "The one link" if len(checked) == 1 else f"All {len(checked)} links"
    verb = "works" if len(checked) == 1 else "work"
    return result(Status.PASS, f"{every} on your home page {where} that we verified {verb}.")


def check_links(page: PageContext) -> list[CheckResult]:
    if page.links is None:  # verification did not run; the report says why in its list of what is incomplete
        return [CheckResult(SITE, name, Status.WARN, "We did not verify the links on your home page this time.",
                            explanation, "Nothing to do based on this report.", [], ran=False)
                for name, explanation in ((SAME_SITE, EXPLANATION), (OTHER_SITES, OTHER_EXPLANATION))]
    # A kind of link the page does not have gets no result: there was nothing to verify and nothing to fix.
    return [evaluate_links(page.links, same, page.rendered) for same in (True, False)
            if any(r.same_site == same for r in page.links)]
