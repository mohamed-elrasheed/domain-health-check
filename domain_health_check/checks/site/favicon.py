"""Does the site have its own browser tab icon?

The icon is resolved the way a browser resolves it: the first <link rel="icon"> (or "shortcut icon", then the
Apple touch icons) the page names, falling back to /favicon.ico. fetcher.fetch_favicon makes those requests, at
most two; this module only judges them. Two findings: no icon at all (nothing resolved to an image), and the
website builder's default icon in place of the owner's own. The defaults are listed in config/platforms.yaml.
"""

from __future__ import annotations

from ...fetcher import FetchedIcon, PageContext
from ...models import SITE, CheckResult, Status
from ...platform import default_icon

NAME = "Favicon"

EXPLANATION = (
    "The favicon is the small picture in a browser tab, a bookmark, and sometimes next to your site in search "
    "results. Your own icon helps people spot your site among their open tabs and recognize it as yours."
)
FIX = ("In your website builder, open the site settings and upload a square version of your logo as the favicon, "
       "sometimes called the site icon.")


def _line(icon: FetchedIcon) -> str:
    named = "named by the page" if icon.declared else "the standard /favicon.ico"
    if icon.error:
        return f"{icon.url} ({named}): {icon.error}"
    where = f", ended at {icon.final_url}" if icon.final_url != icon.url else ""
    kind = icon.content_type or "no content type"
    return f"{icon.url} ({named}{where}): status {icon.status}, {kind}{'' if icon.image else ', not an image'}"


def evaluate_favicon(attempts: list[FetchedIcon]) -> CheckResult:
    details = [_line(a) for a in attempts]

    def result(status: Status, summary: str, fix: str = "", ran: bool = True) -> CheckResult:
        return CheckResult(SITE, NAME, status, summary, EXPLANATION, fix, details, ran)

    found = next((a for a in attempts if a.found), None)
    if found is None:
        if attempts and all(a.status is None for a in attempts):  # no answer is not an answer of "no icon"
            why = ("your robots.txt file asks us not to load it" if all("robots" in a.error for a in attempts)
                   else "the requests for it did not get an answer")
            return result(Status.WARN, f"We could not check your site's icon, because {why}.",
                          "Nothing to do based on this report.", ran=False)
        return result(Status.WARN, "Your site has no browser tab icon, so tabs and bookmarks show a blank page "
                                   "symbol instead.", FIX)
    builder = default_icon(found.url, found.final_url)
    if builder:
        return result(Status.WARN, f"Your site shows the standard {builder} icon in browser tabs rather than your "
                                   "own.", FIX)
    return result(Status.PASS, "Your site has its own browser tab icon.")


def check_favicon(page: PageContext) -> list[CheckResult]:
    if page.favicon is None:
        return [CheckResult(SITE, NAME, Status.WARN, "We did not check your site's icon this time.", EXPLANATION,
                            "Nothing to do based on this report.", [], ran=False)]
    return [evaluate_favicon(page.favicon)]
