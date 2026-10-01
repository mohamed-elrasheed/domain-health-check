"""Site health: how the home page looks to search engines and visitors.

Every check here reads the shared PageContext and makes no request of its own.
When the home page could not be loaded, check_page_loaded reports that once
instead of every check reporting it separately.
"""

from __future__ import annotations

from ...fetcher import FetchError, PageContext, RobotsDisallowed
from ...models import SITE, CheckResult, Status

PAGE_LOADED = "Site health checks"


def check_page_loaded(page: PageContext | FetchError) -> list[CheckResult]:
    if isinstance(page, PageContext):
        return []
    if isinstance(page, RobotsDisallowed):
        summary = "Your website asks automated tools not to load its home page, so we did not run the site health checks."
        fix = ("Nothing needs to change if blocking automated tools is intentional. If you would like these checks, "
               "ask your web developer to allow domain-health-check in your robots.txt file.")
    else:
        summary = f"We could not load {page.url}, so we could not run the site health checks."
        fix = ("If this domain is meant to have a website, ask your web host why the home page cannot be loaded over "
               "HTTPS. If it is only used for email, you can ignore this.")
    return [CheckResult(
        SITE, PAGE_LOADED, Status.WARN, summary,
        "These checks look at how your home page appears to search engines and visitors, so they need the page itself.",
        fix, [f"Error: {page.reason}"], ran=False,
    )]
