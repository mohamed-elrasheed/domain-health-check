"""Can search engines find and list the home page?

  * Search engine blocking: a "noindex" instruction in the page or its headers,
    or a robots.txt rule that keeps Google out. Sites often launch with one left
    on from the building stage, and nothing on the page looks wrong.
  * Canonical tag: <link rel="canonical"> names the main address of the page,
    so the www and non-www versions count as one page.
  * Sitemap and robots: the sitemap lists the site's pages; robots.txt is the
    usual place to tell search engines where it is.

robots.txt is read by robots.py, the same reader the fetcher uses for our own
access, the way Google reads it.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from ... import robots as robots_txt
from ...fetcher import (SITEMAP_MAX_BYTES, FetchedFile, FetchError, PageContext, robots_blocks_search,
                        same_site, status_phrase)
from ...models import SITE, CheckResult, Status
from ._html import meta, parse

SEARCH_BLOCKING = "Search engine blocking"
CANONICAL = "Canonical tag"
SITEMAP = "Sitemap and robots"

# X-Robots-Tag directives that take a value after a colon, so "name: value" is not a user agent.
VALUE_DIRECTIVES = {"unavailable_after", "max-snippet", "max-image-preview", "max-video-preview"}

SEARCH_EXPLANATION = (
    "Search engines such as Google follow instructions a website gives them about what to list. One leftover "
    "setting, often from when the site was being built, can keep your home page out of search results, and "
    "nothing on the page itself looks wrong."
)
CANONICAL_EXPLANATION = (
    "A canonical tag tells search engines which address is the main one for a page. It makes sure the "
    "versions of your address with and without \"www\", or with tracking codes added, count as one page "
    "instead of competing with each other."
)
SITEMAP_EXPLANATION = (
    "A sitemap is a list of the pages on your website that helps search engines find all of them. The "
    "robots.txt file is a short file of instructions for search engines, and it is the usual place to tell "
    "them where your sitemap is."
)


def googlebot_block(robots_text: str, path: str = "/") -> str | None:
    """The robots.txt rule that stops Googlebot crawling path, or None if it may."""
    return robots_txt.blocking_rule(robots_text, "googlebot", path)


def header_noindex(value: str) -> bool:
    """Whether an X-Robots-Tag header says noindex to Google ("noindex" or "googlebot: noindex")."""
    scope = None
    for token in value.split(","):
        token = token.strip().lower()
        scoped = re.match(r"([a-z0-9_-]+)\s*:\s*(.*)", token)
        if scoped and scoped.group(1) not in VALUE_DIRECTIVES:
            scope, token = scoped.group(1), scoped.group(2).strip()
        if token in ("noindex", "none") and scope in (None, "googlebot"):
            return True
    return False


def _meta_noindex(content: str) -> bool:
    return any(d.strip().lower() in ("noindex", "none") for d in content.split(","))


# ---------- Search engine blocking

def evaluate_search_blocking(
    meta_robots: list[tuple[str, str]], x_robots_tag: str | None, robots_rule: str | None, robots_url: str = "",
) -> CheckResult:
    """meta_robots is [(meta name, content)] for name="robots" and name="googlebot"."""
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(SITE, SEARCH_BLOCKING, status, summary, SEARCH_EXPLANATION, fix, list(details))

    noindex = [f'<meta name="{name}" content="{content}">' for name, content in meta_robots if _meta_noindex(content)]
    if x_robots_tag and header_noindex(x_robots_tag):
        noindex.append(f"X-Robots-Tag header: {x_robots_tag}")
    details = [f"Found: {signal}" for signal in noindex]
    if robots_rule:
        details.append(f"Found: {robots_url or 'robots.txt'} has \"{robots_rule}\" for Googlebot")

    fix = (
        "Ask your web developer to remove the setting that tells search engines to stay away. When a site has "
        "recently launched, this is usually a setting left on from the building stage, and it is a small change."
    )
    if noindex:
        return result(Status.FAIL, "Your home page tells search engines not to list it, so it will not appear in "
                                   "Google search results.", fix, details)
    if robots_rule:
        return result(Status.FAIL, "Your website tells Google not to visit your home page, so it is unlikely to "
                                   "appear properly in search results.", fix, details)
    return result(Status.PASS, "Your home page allows search engines to list it.",
                  details=["No noindex instruction in the page or its headers, and robots.txt lets Googlebot in."])


def evaluate_robots_status(robots: FetchedFile) -> CheckResult:
    """A robots.txt that answers with a server error (or 429) is itself a block: search engines stop crawling
    the whole site until it recovers. This is broken today, so it is a FAIL."""
    kind = "is being turned away (too many requests)" if robots.status == 429 else "returns a server error"
    return CheckResult(
        SITE, SEARCH_BLOCKING, Status.FAIL,
        f"Your robots.txt file {kind}. Search engines treat that as an instruction to stop crawling your site "
        "entirely, so your pages may be dropping out of Google.",
        "Search engines read your robots.txt file, a short file of instructions, before they visit any page. When "
        "it fails to load, Google treats that as an instruction to stay away and stops crawling your whole site "
        "until it loads again. Nothing on your pages looks wrong while this happens.",
        "Ask your web developer or host to make the robots.txt file load normally. It can be very short, but it "
        "has to answer without an error.",
        [f"{robots.url} answered with HTTP status {robots.status} ({status_phrase(robots.status)})",
         "Google treats a 5xx or 429 on robots.txt as fully disallowed; after 30 days it falls back to its last "
         "copy of the file."],
    )


def check_search_blocking(page: PageContext | FetchError) -> list[CheckResult]:
    """Runs even when the home page could not be loaded: robots.txt alone can show that Google is kept out."""
    robots = page.robots
    if robots is not None and robots_blocks_search(robots.status):
        return [evaluate_robots_status(robots)]
    readable = robots is not None and robots.status == 200
    if isinstance(page, FetchError):
        rule = googlebot_block(robots.text) if readable else None
        return [evaluate_search_blocking([], None, rule, robots.url)] if rule else []

    path = urlsplit(page.final_url).path or "/"
    tree = parse(page.html)
    meta_robots = [(name, content) for name in ("robots", "googlebot") for content in meta(tree, name)]
    rule = googlebot_block(robots.text, path) if readable else None
    return [evaluate_search_blocking(meta_robots, page.headers.get("x-robots-tag"), rule,
                                     robots.url if robots else "")]


# ---------- Canonical tag

def _path(url: str) -> str:
    return urlsplit(url).path.rstrip("/") or "/"


def evaluate_canonical(canonicals: list[str], final_url: str) -> CheckResult:
    """Only missing, relative, or another site is worth flagging. Differences in scheme, www, trailing slash
    or query string are what canonical tags exist to smooth over."""
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(SITE, CANONICAL, status, summary, CANONICAL_EXPLANATION, fix, list(details))

    details = [f"Canonical tag: {href}" for href in canonicals] + [f"Page we loaded: {final_url}"]
    if not canonicals:
        return result(Status.WARN, "Your home page does not tell search engines which address is its main one.",
                      f"Ask your web developer to add a canonical tag to your home page pointing to {final_url}",
                      details)
    for href in canonicals:
        parts = urlsplit(href)
        if not (parts.scheme and parts.netloc):
            return result(Status.WARN, "Your home page canonical tag uses a partial address instead of a full one.",
                          f"Ask your web developer to change the canonical tag to the full address, {final_url}",
                          details)
        if not same_site(href, final_url):
            return result(Status.WARN, "Your home page canonical tag points to a different website.",
                          "Ask your web developer whether this is intended. If it is not, the canonical tag should "
                          f"point to your own address, {final_url}", details)

    if len(set(canonicals)) > 1:
        details.append(f"Note: the page has {len(set(canonicals))} different canonical tags.")
    if any(_path(href) != _path(final_url) for href in canonicals):
        details.append("Note: the canonical points to a different page on your site, which asks search engines "
                       "to list that page instead of this one.")
    return result(Status.PASS, "Your home page tells search engines which address is its main one.",
                  details=details)


def check_canonical(page: PageContext) -> list[CheckResult]:
    tree = parse(page.html)
    canonicals = [
        (node.attributes.get("href") or "").strip()
        for node in tree.css("link[rel]")
        if "canonical" in (node.attributes.get("rel") or "").lower().split()
    ]
    return [evaluate_canonical(canonicals, page.final_url)]


# ---------- Sitemap and robots

def read_sitemap(sitemap: FetchedFile) -> tuple[str | None, list[str], str | None]:
    """(urlset | sitemapindex | None, every <loc>, problem). A truncated file cannot be fully parsed, so
    only its opening element is judged."""
    text = sitemap.text
    if sitemap.truncated:
        opening = re.search(r"<(?:[\w-]+:)?(urlset|sitemapindex)\b", text)
        kind = opening.group(1) if opening else None
    else:
        try:
            kind = ET.fromstring(text).tag.rsplit("}", 1)[-1]
        except ET.ParseError as exc:
            return None, [], f"the sitemap is not valid XML ({exc})"
    if kind not in ("urlset", "sitemapindex"):
        return None, [], f"the sitemap's main element is <{kind}>, not <urlset> or <sitemapindex>"
    # Unprefixed <loc> only: <image:loc> inside a urlset is an image, not a page.
    locs = [html.unescape(loc.strip()) for loc in re.findall(r"<loc>\s*(.*?)\s*</loc>", text, re.S)]
    return kind, locs, None


def sitemap_pages(sitemap: FetchedFile | None) -> set[str]:
    """Page URLs a sitemap lists. Empty for a sitemap index, whose entries are sitemaps, not pages."""
    if sitemap is None or sitemap.status != 200:
        return set()
    kind, locs, _ = read_sitemap(sitemap)
    return set(locs) if kind == "urlset" else set()


def _same_file(a: str, b: str) -> bool:
    return same_site(a, b) and _path(a) == _path(b)


def evaluate_sitemap_and_robots(robots: FetchedFile, sitemap: FetchedFile) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(SITE, SITEMAP, status, summary, SITEMAP_EXPLANATION, fix, list(details))

    details = [f"robots.txt: {robots.url} (status {robots.status})",
               f"Sitemap: {sitemap.url} (status {sitemap.status})"]
    if sitemap.truncated:
        details.append(f"We read only the first {SITEMAP_MAX_BYTES // 1_000_000} MB of the sitemap, so we checked "
                       "how it starts rather than every entry.")
    problems: list[tuple[str, str]] = []  # (summary, fix), most important first

    kind, locs = None, []
    if sitemap.status != 200:
        problems.append(("We could not find a sitemap for your website.",
                         "Most website builders can create a sitemap automatically from their SEO settings. If "
                         "yours does not, ask your web developer to add one at /sitemap.xml."))
    else:
        kind, locs, problem = read_sitemap(sitemap)
        if problem:
            details.append(f"Problem: {problem}")
            problems.append(("Your sitemap is not in a format search engines can read.",
                             "Ask your web developer to fix the sitemap so it is valid XML. The technical details "
                             "show the error."))

    listed = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", robots.text) if robots.status == 200 else []
    details += [f"robots.txt lists sitemap: {url}" for url in listed]
    if robots.status != 200:
        problems.append(("Your website has no robots.txt file to point search engines to your sitemap.",
                         "Ask your web developer to add a robots.txt file with a line pointing to your sitemap."))
    elif sitemap.status == 200 and not any(_same_file(url, sitemap.url) for url in listed):
        problems.append(("Your robots.txt file does not mention your sitemap, so search engines have to find it "
                         "on their own.",
                         f"Ask your web developer to add the line \"Sitemap: {sitemap.url}\" to your robots.txt "
                         "file."))

    if problems:
        return result(Status.WARN, problems[0][0], " ".join(fix for _, fix in problems), details)

    count = f"at least {len(locs)}" if sitemap.truncated else str(len(locs))
    if kind == "sitemapindex":
        details.append("This is a sitemap index. We did not open the sitemaps it lists.")
        summary = f"Your sitemap index lists {count} sitemaps, and your robots.txt file points search engines to it."
    else:
        summary = f"Your sitemap lists {count} pages, and your robots.txt file points search engines to it."
    return result(Status.PASS, summary, details=details)


ANSWERED = (200, 404, 410)  # found, or genuinely not there; anything else tells us nothing about the file


def check_sitemap_and_robots(page: PageContext) -> list[CheckResult]:
    for file in (page.robots, page.sitemap):
        if file is not None and file.status not in ANSWERED:
            return [CheckResult(
                SITE, SITEMAP, Status.WARN,
                f"Your website answered with an error (status {file.status}) when we asked for {file.url}, so we "
                "could not check your sitemap.",
                SITEMAP_EXPLANATION, "Nothing to do based on this report.",
                [f"robots.txt: {page.robots.url} (status {page.robots.status})" if page.robots else "robots.txt: not read",
                 f"Sitemap: {page.sitemap.url} (status {page.sitemap.status})" if page.sitemap else "Sitemap: not read"],
                ran=False,
            )]
    if page.robots is None or page.sitemap is None:
        return [CheckResult(
            SITE, SITEMAP, Status.WARN, "We could not read your sitemap, so we could not check it.",
            SITEMAP_EXPLANATION,
            "Nothing to do based on this report.",
            [f"robots.txt: {page.robots.url if page.robots else 'not read'}",
             "Sitemap: not read (robots.txt does not allow it, or it could not be reached)"],
            ran=False,
        )]
    return [evaluate_sitemap_and_robots(page.robots, page.sitemap)]
