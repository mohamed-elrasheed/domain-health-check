"""The one place this tool loads anything from the website being checked.

Every report is allowed one page view: robots.txt, then the home page, the
same footprint as a single visitor. The runner calls fetch_page once and hands
the resulting PageContext to every check that needs the page, so checks never
make HTTP requests of their own.

This module owns the rules that keep that footprint honest: we identify
ourselves in the User-Agent, honor robots.txt, give up after a timeout, follow
a limited number of redirects, and stop reading a page that is too large.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib import robotparser

import httpx

USER_AGENT = "domain-health-check/0.1 (+https://www.mizangroupllc.com/digital)"
TIMEOUT_SECONDS = 10  # per connect / read, as httpx measures it
TOTAL_SECONDS = 30  # the whole page, including redirects and a slow trickle of bytes
MAX_REDIRECTS = 5
MAX_BYTES = 5_000_000  # decompressed HTML; well beyond any real home page
ROBOTS_MAX_BYTES = 500_000  # RFC 9309 lets crawlers ignore anything past 500 KiB


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

    @property
    def truncated(self) -> bool:
        """True when the page hit MAX_BYTES, so html is incomplete and byte_size is a lower bound."""
        return self.byte_size > MAX_BYTES


class FetchError(Exception):
    """The page couldn't be loaded. Checks report this; it never sinks the report."""

    def __init__(self, url: str, reason: str):
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason


class RobotsDisallowed(FetchError):
    """The site's robots.txt asks us not to load the page, so we didn't."""


def robots_allows(status: int, text: str, url: str) -> bool:
    """Whether robots.txt (already fetched) lets our User-Agent load url. Follows RFC 9309:
    a 4xx means there are no rules, and a 5xx means assume everything is disallowed."""
    if 400 <= status < 500:
        return True
    if status >= 500:
        return False
    parser = robotparser.RobotFileParser()
    parser.parse(text.splitlines())
    return parser.can_fetch(USER_AGENT, url)


def fetch_page(domain: str, *, transport: httpx.BaseTransport | None = None) -> PageContext:
    """robots.txt, then the home page over HTTPS. Raises FetchError. transport is for tests."""
    url = f"https://{domain}/"
    with httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS,
        follow_redirects=True, max_redirects=MAX_REDIRECTS, transport=transport,
    ) as client:
        robots_url = f"https://{domain}/robots.txt"
        try:
            status, body, _ = _get(client, robots_url, ROBOTS_MAX_BYTES)
        except FetchError as exc:  # unreachable robots.txt: RFC 9309 says don't load anything
            raise FetchError(url, f"{robots_url} {exc.reason}") from exc
        if not robots_allows(status, body[:ROBOTS_MAX_BYTES].decode("utf-8", errors="replace"), url):
            raise RobotsDisallowed(url, f"{robots_url} (status {status}) does not allow {USER_AGENT} to load /")

        started = time.monotonic()
        status, body, response = _get(client, url, MAX_BYTES)
        return PageContext(
            requested_url=url,
            final_url=str(response.url),
            redirect_chain=[(str(r.url), r.status_code) for r in response.history],
            status=status,
            headers={k.lower(): v for k, v in response.headers.items()},
            html=body[:MAX_BYTES].decode(response.encoding or "utf-8", errors="replace"),
            byte_size=len(body),
            elapsed_ms=int((time.monotonic() - started) * 1000),
        )


def _get(client: httpx.Client, url: str, max_bytes: int) -> tuple[int, bytes, httpx.Response]:
    """Stream url, stopping once more than max_bytes have arrived, so an oversized body reads
    as max_bytes plus at most one chunk. Error statuses are returned, not raised."""
    deadline = time.monotonic() + TOTAL_SECONDS
    chunks: list[bytes] = []
    size = 0
    try:
        with client.stream("GET", url) as response:
            for chunk in response.iter_bytes():
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
    return response.status_code, b"".join(chunks), response
