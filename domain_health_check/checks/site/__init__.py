"""Site health: how the home page looks to search engines and visitors.

Every check here reads the shared PageContext and makes no request of its own.
When the home page could not be loaded, check_page_loaded reports that once
instead of every check reporting it separately.

We read the HTML as delivered and do not run scripts; Google does. When the
delivered page has almost no text and almost no headings, its content is most
likely built by scripts, and the content checks would be judging an empty
shell. check_page_rendered reports that once and those checks do not run.
"""

from __future__ import annotations

from functools import lru_cache

from ...fetcher import FetchError, PageContext, PageStatusError, RobotsDisallowed, status_phrase
from ...models import SITE, CheckResult, Status
from ._html import headings, parse, visible_text, word_count

PAGE_LOADED = "Site health checks"
PAGE_RENDERED = "Page content checks"
MIN_WORDS = 50  # fewer visible words than this, and
MIN_HEADINGS = 2  # fewer headings than this, means an empty shell


@lru_cache(maxsize=4)
def _measure(html: str) -> tuple[int, int]:
    return word_count(visible_text(html)), len(headings(parse(html)))


def built_by_scripts(page: PageContext) -> bool:
    words, heading_count = _measure(page.html)
    return words < MIN_WORDS and heading_count < MIN_HEADINGS


def check_page_loaded(page: PageContext | FetchError) -> list[CheckResult]:
    if isinstance(page, PageContext):
        return []
    if isinstance(page, PageStatusError) and page.stage == "robots":
        summary = (f"Your robots.txt file ({page.where}) answered with an error (status {page.status}, "
                   f"{status_phrase(page.status).lower()}). A broken robots.txt means we are not permitted to "
                   "continue, so we stopped there deliberately and did not request your home page.")
        fix = "Fix the robots.txt file first (see the search engine finding above); the page checks can follow."
    elif isinstance(page, PageStatusError):
        summary = (f"Your home page ({page.where}) answered our visit with an error (status {page.status}, "
                   f"{status_phrase(page.status).lower()}) instead of the page, so we did not run the site "
                   "health checks.")
        fix = ("If your website loads normally for visitors, nothing needs to change: some sites turn away automated "
               "checks like ours, and this says nothing about what your visitors see. If it does not load for them "
               f"either, ask your web host why it answers with status {page.status}.")
    elif isinstance(page, RobotsDisallowed):
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


def check_page_rendered(page: PageContext | FetchError) -> list[CheckResult]:
    if not isinstance(page, PageContext) or not built_by_scripts(page):
        return []
    words, heading_count = _measure(page.html)
    return [CheckResult(
        SITE, PAGE_RENDERED, Status.WARN,
        "Your home page arrives with almost no text, which usually means scripts build it after it loads, so we did "
        "not check its title, description, headings or image descriptions.",
        "Search engines such as Google run a page's scripts before reading it. We read the page as it is delivered, "
        "without running scripts, so for this page we would only be guessing. This is not a finding about your "
        "website.",
        "Nothing to do based on this report.",
        [f"Visible words in the delivered HTML: {words} (we need {MIN_WORDS} or more)",
         f"Headings in the delivered HTML: {heading_count} (we need {MIN_HEADINGS} or more)",
         "Not checked: page title, meta description, main heading, heading order, image alt text"],
        ran=False,
    )]
