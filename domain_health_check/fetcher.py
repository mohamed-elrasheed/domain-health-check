"""The one place this tool loads anything from the website being checked.

Every report is allowed one page view: robots.txt, the home page and the
sitemap, the same footprint as a single visitor plus the two files search
engines read. The runner calls fetch_page once and hands the resulting
PageContext to every check that needs it, so checks never make HTTP requests
of their own.

This module owns the rules that keep that footprint honest: we identify
ourselves in the User-Agent, honor robots.txt, give up after a timeout, follow
a limited number of redirects, and stop reading anything that is too large.
A sitemap index is recorded but never followed, since opening the sitemaps it
lists would mean more requests.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from http import HTTPStatus
from urllib.parse import urljoin, urlsplit

import httpx

from . import robots as robots_txt
from .identity import ROBOTS_TOKEN, USER_AGENT  # noqa: F401 (re-exported: fetcher owns the report's fetch)
TIMEOUT_SECONDS = 10  # per connect / read, as httpx measures it
TOTAL_SECONDS = 30  # one download, including redirects and a slow trickle of bytes
MAX_REDIRECTS = 5
MAX_BYTES = 5_000_000  # decompressed HTML; well beyond any real home page
ROBOTS_MAX_BYTES = 500_000  # RFC 9309 lets crawlers ignore anything past 500 KiB
SITEMAP_MAX_BYTES = 2_000_000  # roughly 20,000 URLs; a full 50,000-URL sitemap can reach 50 MB


@dataclass
class FetchedFile:
    url: str  # after redirects
    status: int
    text: str
    truncated: bool = False  # we stopped reading at the size cap, so text is only the start of the file


@dataclass
class PageContext:
    requested_url: str
    final_url: str  # after redirects
    redirect_chain: list[tuple[str, int]]  # (url requested, status) for each hop before final_url
    status: int
    headers: dict[str, str]  # lowercased keys
    html: str
    byte_size: int  # decompressed size of the HTML document alone, not images, scripts or styles
    elapsed_ms: int  # first request to last byte, including redirects
    ttfb_ms: int  # first request until the final response's headers arrived, including redirects
    robots: FetchedFile | None
    sitemap: FetchedFile | None  # None when robots.txt disallows it or it could not be reached
    # Every report also reads the page in a real browser. rendered_html is the DOM after scripts ran, with
    # every element a visitor cannot see marked; it is "" when the browser could not load the page.
    # script_built: the delivered html is an empty shell that scripts fill in.
    rendered_html: str = ""
    script_built: bool = False

    @property
    def rendered(self) -> bool:
        return bool(self.rendered_html)

    @property
    def as_delivered(self) -> str:
        """Exactly what the server sent. Link previews read this: the apps that draw them run no scripts."""
        return self.html

    @property
    def indexed_html(self) -> str:
        """What a search engine reads: the page as delivered, unless scripts build it, in which case the page
        after they ran (Google runs them). Title, description, canonical, viewport and structured data."""
        return self.rendered_html if self.script_built and self.rendered_html else self.html

    @property
    def visible_html(self) -> str:
        """What a visitor sees: the rendered page with off-screen elements marked, or, when the browser could not
        load it, the delivered page (and the checks then say so instead of claiming what is visible)."""
        return self.rendered_html or self.html

    @property
    def truncated(self) -> bool:
        """True when the page hit MAX_BYTES, so html is incomplete and byte_size is a lower bound."""
        return self.byte_size > MAX_BYTES


class FetchError(Exception):
    """The page couldn't be loaded. Checks report this; it never sinks the report."""

    def __init__(self, url: str, reason: str, robots: FetchedFile | None = None):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason
        self.robots = robots  # kept when we got that far, so search engine blocking can still be checked


class RobotsDisallowed(FetchError):
    """The site's robots.txt asks us not to load the page, so we didn't."""


class PageStatusError(FetchError):
    """The site answered with an error status instead of the page. Its body is a block page, a captcha or a
    maintenance notice, never the site, so nothing reads it: reading one 403 page as the home page produced a
    dozen findings about a site we never saw."""

    def __init__(self, url: str, status: int, where: str, robots: FetchedFile | None = None, stage: str = "page"):
        super().__init__(url, f"{where} answered with HTTP status {status} ({status_phrase(status)})", robots)
        self.status = status
        self.where = where  # the URL that answered with the error
        self.stage = stage  # "robots": we stopped at robots.txt and never requested the home page; "page": the home page


def robots_blocks_search(status: int) -> bool:
    """Whether a robots.txt status alone stops search engines crawling the whole site. Google treats 5xx and 429
    as "fully disallowed" until the file recovers. Every other 4xx, 403 included, it treats as no robots.txt at
    all, meaning no restrictions (RFC 9309 agrees), so a 403 here is not a search problem."""
    return status == 429 or status >= 500


def status_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "unknown status"


def robots_allows(status: int, text: str, url: str) -> bool:
    """Whether robots.txt (already fetched) lets us load url. Follows RFC 9309: a 4xx means there
    are no rules, and a 5xx means assume everything is disallowed. Wildcards and longest-match are
    honored on every supported Python, which urllib.robotparser only does from 3.14."""
    if 400 <= status < 500:
        return True
    if status >= 500:
        return False
    return robots_txt.blocking_rule(text, ROBOTS_TOKEN, url) is None


def same_site(a: str, b: str) -> bool:
    """Whether two URLs are on the same host, treating www.example.com and example.com as one."""
    def host(url: str) -> str:
        return (urlsplit(url).hostname or "").removeprefix("www.")
    return host(a) == host(b) != ""


def sitemap_url(robots: FetchedFile) -> str:
    """The first same-site sitemap robots.txt lists, otherwise /sitemap.xml next to robots.txt."""
    if robots.status == 200:
        for listed in re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", robots.text):
            if same_site(listed, robots.url):
                return listed
    return urljoin(robots.url, "/sitemap.xml")


def fetch_page(domain: str, *, transport: httpx.BaseTransport | None = None) -> PageContext:
    """robots.txt, the home page over HTTPS, then the sitemap. Raises FetchError. transport is for tests."""
    url = f"https://{domain}/"
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS,
        follow_redirects=True, max_redirects=MAX_REDIRECTS, transport=transport,
    ) as client:
        robots_requested = f"https://{domain}/robots.txt"
        try:
            robots = _get_file(client, robots_requested, ROBOTS_MAX_BYTES)
        except FetchError as exc:  # unreachable robots.txt: RFC 9309 says don't load anything
            raise FetchError(url, f"{robots_requested} {exc.reason}") from exc
        if robots_blocks_search(robots.status):
            # RFC 9309: a server error on robots.txt means assume everything is disallowed, so we stop here,
            # and say so plainly instead of claiming robots.txt told us to stay away.
            raise PageStatusError(url, robots.status, robots.url, robots, stage="robots")
        if not robots_allows(robots.status, robots.text, url):
            raise RobotsDisallowed(
                url, f"{robots.url} (status {robots.status}) does not allow {USER_AGENT} to load /", robots)

        try:
            response, body, ttfb_ms, elapsed_ms = _get(client, url, MAX_BYTES)
        except FetchError as exc:
            exc.robots = robots
            raise
        if response.status_code != 200:  # the guard: an error page's body is never read as the site
            raise PageStatusError(url, response.status_code, str(response.url), robots)

        sitemap = None
        candidate = sitemap_url(robots)
        if robots_allows(robots.status, robots.text, candidate):
            try:
                sitemap = _get_file(client, candidate, SITEMAP_MAX_BYTES)
            except FetchError:
                pass  # the sitemap check reports it as not run; the page itself is still fine

        return PageContext(
            requested_url=url,
            final_url=str(response.url),
            redirect_chain=[(str(r.url), r.status_code) for r in response.history],
            status=response.status_code,
            headers={k.lower(): v for k, v in response.headers.items()},
            html=body[:MAX_BYTES].decode(response.encoding or "utf-8", errors="replace"),
            byte_size=len(body),
            elapsed_ms=elapsed_ms,
            ttfb_ms=ttfb_ms,
            robots=robots,
            sitemap=sitemap,
        )


def _get_file(client: httpx.Client, url: str, max_bytes: int) -> FetchedFile:
    response, body, _, _ = _get(client, url, max_bytes)
    return FetchedFile(
        str(response.url), response.status_code,
        body[:max_bytes].decode(response.encoding or "utf-8", errors="replace"), len(body) > max_bytes,
    )


def _get(client: httpx.Client, url: str, max_bytes: int) -> tuple[httpx.Response, bytes, int, int]:
    """Stream url, stopping once more than max_bytes have arrived, so an oversized body reads
    as max_bytes plus at most one chunk. Returns (response, body, ttfb_ms, elapsed_ms).
    Error statuses are returned, not raised; an error body is not even downloaded."""
    started = time.monotonic()
    deadline = started + TOTAL_SECONDS
    chunks: list[bytes] = []
    size = 0
    try:
        with client.stream("GET", url) as response:
            ttfb_ms = int((time.monotonic() - started) * 1000)
            for chunk in (response.iter_bytes() if response.status_code < 400 else ()):
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    break
                if time.monotonic() > deadline:
                    raise FetchError(url, f"took longer than {TOTAL_SECONDS} seconds to load")
    except httpx.TooManyRedirects:
        raise FetchError(url, f"redirected more than {MAX_REDIRECTS} times") from None
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        raise FetchError(url, f"{type(exc).__name__}: {exc}") from exc
    return response, b"".join(chunks), ttfb_ms, int((time.monotonic() - started) * 1000)



# ---------- the second look, for pages that scripts build

@dataclass
class Rendered:
    html: str  # the DOM after scripts ran, with elements a visitor cannot see marked data-dhc-hidden
    final_url: str


class RenderFailed(Exception):
    pass


def browser_render(url: str, offline: bool = False) -> Rendered:
    """Load url in a real browser, through the path sweep uses, and return the rendered page. A second view of
    the home page, made on every report: the report runs only on submitted domains, and the checks an owner
    verifies by looking at their own screen are judged on what that screen shows."""
    from .browser import BrowserUnavailable, NavigationFailed, Session, mark_hidden
    try:
        with Session(hint=" to read pages that scripts build", offline=offline) as session,                 session.tab(url) as (tab, response):
            if response.status and response.status >= 400:
                raise RenderFailed(f"the browser got status {response.status} ({status_phrase(response.status)})")
            mark_hidden(tab)
            return Rendered(tab.content(), response.url)
    except (BrowserUnavailable, NavigationFailed) as exc:
        raise RenderFailed(str(exc)) from exc


RENDERER: Callable[[str], Rendered] = browser_render  # tests put a renderer of their own here


def render(page: PageContext, renderer: Callable[[str], Rendered] | None = None) -> PageContext:
    """The page as a browser shows it. Raises RenderFailed; the caller keeps the delivered page."""
    rendered = (renderer or RENDERER)(page.final_url)
    return replace(page, rendered_html=rendered.html)
