"""The one visit sweep makes to a business's site: robots.txt, then the home page.

This is sweep's own fetch layer, deliberately separate from fetcher.py, which serves the report and also
opens the sitemap. The rules are the same ones: we name ourselves in the User-Agent, honor robots.txt
(RFC 9309), give up after a timeout, cap redirects and bytes, and space out requests to any one host.
A check never makes its own request; everything a detector reads comes through here.

When the page cannot be loaded we record why, because "unver" means our request failed, not that the
site is fine, and the reason decides what Mo does next. Failure kinds:

    nxdomain       the domain does not exist (the name lookup found no such domain)
    certificate    a certificate error a browser would show as a security warning
    unverified     a certificate our client could not verify but a browser might accept
    timeout        no answer in time, on every attempt
    connection     refused, reset or otherwise unreachable, on every attempt
    blocked        the site answered 401, 403 or 429: a filter that turns away automated visitors
    status         the home page answered some other error status
    robots         robots.txt answered 5xx or 429, so RFC 9309 says load nothing
    disallowed     robots.txt asks us by name, or everyone, not to load the home page
    redirects      too many redirects
    error          anything else
"""

from __future__ import annotations

import time
from collections.abc import Callable
from http import HTTPStatus
from urllib.parse import urlsplit, urlunsplit

import httpx

from .. import robots as robots_txt
from ..identity import ROBOTS_TOKEN, USER_AGENT
from . import hosts
from .models import Page, Robots, Visit

TIMEOUT_SECONDS = 10  # per connect / read
TOTAL_SECONDS = 30  # one download, including redirects
MAX_REDIRECTS = 5
MAX_BYTES = 5_000_000
ROBOTS_MAX_BYTES = 500_000  # RFC 9309 lets crawlers ignore anything past 500 KiB
ATTEMPTS = 2  # a timeout or dropped connection gets one more try, after RETRY_PAUSE
RETRY_PAUSE = 5.0
HOST_GAP = 1.0  # seconds between any two requests to the same host

RETRYABLE = {"timeout", "connection", "error"}
BLOCKED_STATUSES = {401, 403, 429}
# getaddrinfo's "no such name": Windows WSAHOST_NOT_FOUND and WSANO_DATA, glibc EAI_NONAME and EAI_NODATA.
# A resolver that is merely unreachable reports something else (EAI_AGAIN, WSATRY_AGAIN), which is retried.
NXDOMAIN_ERRNOS = {11001, 11004, -2, -5}
# OpenSSL verify messages a browser would also refuse, as opposed to an incomplete chain it can repair.
BROWSER_WARNINGS = ("expired", "not yet valid", "self-signed", "self signed", "hostname mismatch",
                    "doesn't match", "does not match")


class LoadFailure(Exception):
    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind
        self.detail = detail


def phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return "unknown status"


def _chain(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def classify(exc: BaseException, url: str) -> LoadFailure:
    """Turn an httpx error into a failure kind. Socket and TLS errors are recognized by name, so sweep
    never imports socket or ssl itself."""
    for cause in _chain(exc):
        name = type(cause).__name__
        if name == "gaierror" and getattr(cause, "errno", None) in NXDOMAIN_ERRNOS:
            return LoadFailure("nxdomain", f"{hosts.host(url)} does not exist: the name lookup found no such domain")
        if name == "SSLCertVerificationError":
            message = getattr(cause, "verify_message", "") or str(cause)
            if any(w in message.lower() for w in BROWSER_WARNINGS):
                return LoadFailure("certificate", message)
            return LoadFailure("unverified", f"our client could not verify the certificate ({message}); "
                                             "a browser may still accept it")
    if isinstance(exc, httpx.TimeoutException):
        return LoadFailure("timeout", f"no answer within {TIMEOUT_SECONDS} seconds")
    if isinstance(exc, httpx.TooManyRedirects):
        return LoadFailure("redirects", f"redirected more than {MAX_REDIRECTS} times")
    if isinstance(exc, (httpx.ConnectError, httpx.ReadError, httpx.WriteError, httpx.RemoteProtocolError)):
        return LoadFailure("connection", f"{type(exc).__name__}: {exc}")
    return LoadFailure("error", f"{type(exc).__name__}: {exc}")


class Pacer:
    """Spaces requests to one host at least HOST_GAP apart. Clock and sleep are injectable for tests."""

    def __init__(self, gap: float = HOST_GAP, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.gap, self._clock, self._sleep = gap, clock, sleep
        self._last: dict[str, float] = {}

    def wait(self, url: str) -> None:
        name = hosts.host(url)
        due = self._last.get(name, float("-inf")) + self.gap
        now = self._clock()
        if now < due:
            self._sleep(due - now)
        self._last[name] = self._clock()

    def pause(self, seconds: float) -> None:
        self._sleep(seconds)


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS, follow_redirects=True,
                        max_redirects=MAX_REDIRECTS, transport=transport)


def robots_url(url: str) -> str:
    parts = urlsplit(url if "//" in url else f"https://{url}")
    return urlunsplit((parts.scheme or "https", parts.netloc, "/robots.txt", "", ""))


def _download(http: httpx.Client, url: str, max_bytes: int) -> tuple[httpx.Response, bytes]:
    started = time.monotonic()
    chunks: list[bytes] = []
    size = 0
    try:
        with http.stream("GET", url) as response:
            for chunk in (response.iter_bytes() if response.status_code < 400 else ()):
                chunks.append(chunk)
                size += len(chunk)
                if size > max_bytes:
                    break
                if time.monotonic() - started > TOTAL_SECONDS:
                    raise LoadFailure("timeout", f"took longer than {TOTAL_SECONDS} seconds to load")
    except httpx.HTTPError as exc:
        raise classify(exc, url) from exc
    except httpx.InvalidURL as exc:
        raise LoadFailure("error", f"not a usable address: {exc}") from exc
    return response, b"".join(chunks)[:max_bytes]


def fetch_robots(http: httpx.Client, url: str) -> Robots:
    response, body = _download(http, robots_url(url), ROBOTS_MAX_BYTES)
    return Robots(str(response.url), response.status_code,
                  body.decode(response.encoding or "utf-8", errors="replace"))


def fetch_page(http: httpx.Client, url: str) -> Page:
    """The home page as delivered, before any scripts run. Used when there is no browser, and in tests."""
    response, body = _download(http, url, MAX_BYTES)
    check_status(response.status_code, str(response.url))
    return Page(url, str(response.url), response.status_code,
                [(str(r.url), r.status_code) for r in response.history],
                body.decode(response.encoding or "utf-8", errors="replace"), rendered=False)


def check_status(status: int, where: str) -> None:
    """An error page is a block page or a maintenance notice, never the site, so it is never read."""
    if status in BLOCKED_STATUSES:
        raise LoadFailure("blocked", f"{where} answered HTTP {status} ({phrase(status)})")
    if status >= 400:
        raise LoadFailure("status", f"{where} answered HTTP {status} ({phrase(status)})")


def robots_gate(robots: Robots, url: str) -> LoadFailure | None:
    """Whether robots.txt lets us load the home page. RFC 9309: 4xx means no rules; 5xx means load nothing."""
    if robots.status == 429 or robots.status >= 500:
        return LoadFailure("robots", f"{robots.url} answered HTTP {robots.status} ({phrase(robots.status)}), so "
                                     "we did not load the page")
    if 400 <= robots.status < 500:
        return None
    rule = robots_txt.blocking_rule(robots.text, ROBOTS_TOKEN, url)
    if rule:
        return LoadFailure("disallowed", f"{robots.url} asks us not to load the home page (\"{rule}\")")
    return None


def attempt(step: Callable[[], object], url: str, pacer: Pacer, visit: Visit):
    """Run one request, retrying once after a timeout or dropped connection."""
    for n in range(1, ATTEMPTS + 1):
        pacer.wait(url)
        visit.attempts += 1
        try:
            return step()
        except LoadFailure as failure:
            if failure.kind not in RETRYABLE or n == ATTEMPTS:
                if n > 1:
                    failure.detail = f"{failure.detail} (on all {n} attempts)"
                raise
            pacer.pause(RETRY_PAUSE)
    raise AssertionError("unreachable")


def visit_robots(url: str, http: httpx.Client, pacer: Pacer) -> Visit:
    """The first half of a visit: robots.txt. Returns a Visit that has failed if the page must not be loaded."""
    visit = Visit(url)
    try:
        visit.robots = attempt(lambda: fetch_robots(http, url), url, pacer, visit)
    except LoadFailure as failure:  # robots.txt unreachable: RFC 9309 says load nothing
        visit.failure, visit.detail = failure.kind, failure.detail
        return visit
    gate = robots_gate(visit.robots, url)
    if gate:
        visit.failure, visit.detail = gate.kind, gate.detail
    return visit
