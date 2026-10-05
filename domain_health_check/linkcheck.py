"""Verify the links on the consented home page. Report mode only; sweep never reaches this module.

The rule is CLAUDE.md's, and this module is held to it exactly:

  * Only links found on the page itself (every <a href> on the rendered page, or the page as delivered when no
    browser ran). Nothing found by following a link is ever requested: this is verification, not discovery.
  * At most 80 URLs in all: up to 60 on the same site, up to 20 on other sites. The rest are counted, not
    requested.
  * One request per URL: HEAD, or GET only when HEAD is refused (405 or 501). The GET is streamed and closed
    unread, so no response body is read or stored.
  * No more than 3 redirect hops.
  * Every request is written to requests.log, under its own source, "links".

Same-site links that robots.txt disallows for us are not requested. A link counts as broken when it ends in an
error status, a timeout, or more than three redirects. Statuses that usually mean "automated checks turned
away" (401, 403, 429 and non-standard codes such as 999) say nothing about whether a visitor gets through, so
they are reported as not verified rather than broken.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urldefrag, urljoin, urlsplit

import httpx
from selectolax.parser import HTMLParser

from . import requestlog
from .fetcher import PageContext, robots_allows, same_site, status_phrase
from .identity import USER_AGENT

MAX_SAME_SITE = 60
MAX_OTHER_SITES = 20
MAX_URLS = MAX_SAME_SITE + MAX_OTHER_SITES  # 80, the cap in CLAUDE.md
MAX_HOPS = 3
TIMEOUT_SECONDS = 10
DEADLINE_SECONDS = 90  # the whole verification; what is left when it passes is counted as not verified
WORKERS = 6
PER_HOST = 2  # never more than two requests at once to any one host
HEAD_REFUSED = {405, 501}
TURNED_AWAY = {401, 403, 429}
TRANSPORT: httpx.BaseTransport | None = None  # tests put a transport of their own here


@dataclass
class LinkResult:
    url: str
    text: str  # what a visitor sees for the link
    same_site: bool
    outcome: str  # "ok", "broken", "not verified" or "not requested"
    status: int | None = None
    final_url: str = ""
    method: str = ""  # HEAD, or GET when HEAD was refused
    detail: str = ""  # why it is broken or was not verified

    @property
    def broken(self) -> bool:
        return self.outcome == "broken"


def _label(node) -> str:
    text = " ".join(node.text(separator=" ").split())
    if not text:
        text = node.attributes.get("aria-label") or node.attributes.get("title") or ""
    if not text:
        text = " ".join(img.attributes.get("alt") or "" for img in node.css("img")).strip()
    return " ".join(text.split()) or "(a link with no text)"


def links_on(html: str, page_url: str) -> list[tuple[str, str]]:
    """(url, visible text) for every distinct web link on the page, in page order. Fragments are dropped, so
    "/menu#lunch" and "/menu" are one link, and a link to the page itself is not a link to verify."""
    found: dict[str, str] = {}
    here = urldefrag(page_url).url
    for node in HTMLParser(html).css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if not href or href.startswith("#"):
            continue
        url = urldefrag(urljoin(page_url, href)).url
        if urlsplit(url).scheme not in ("http", "https") or url == here:
            continue
        found.setdefault(url, _label(node))
    return list(found.items())


def verify(page: PageContext, *, transport: httpx.BaseTransport | None = None) -> list[LinkResult]:
    """Every link on the page, each verified, skipped by robots.txt, or counted past the cap."""
    links = links_on(page.rendered_html or page.html, page.final_url)
    same = [(u, t) for u, t in links if same_site(u, page.final_url)]
    other = [(u, t) for u, t in links if not same_site(u, page.final_url)]
    results: list[LinkResult] = []
    queue: list[LinkResult] = []
    for group, cap, is_same in ((same, MAX_SAME_SITE, True), (other, MAX_OTHER_SITES, False)):
        for i, (url, text) in enumerate(group):
            result = LinkResult(url, text, is_same, "not requested")
            if i >= cap:
                result.detail = f"past the cap of {cap} links"
            elif is_same and page.robots and not robots_allows(page.robots.status, page.robots.text, url):
                result.detail = "robots.txt asks us not to load it"
            else:
                queue.append(result)
            results.append(result)
    assert len(queue) <= MAX_URLS
    if queue:
        _run(queue, transport or TRANSPORT)
    return results


def _run(queue: list[LinkResult], transport: httpx.BaseTransport | None) -> None:
    deadline = time.monotonic() + DEADLINE_SECONDS
    gates: dict[str, threading.Semaphore] = defaultdict(lambda: threading.Semaphore(PER_HOST))
    lock = threading.Lock()

    def gate(url: str) -> threading.Semaphore:
        with lock:
            return gates[(urlsplit(url).hostname or "").lower()]

    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS, follow_redirects=True,
                      max_redirects=MAX_HOPS, transport=transport,
                      event_hooks=requestlog.httpx_hooks("links")) as client:
        def one(result: LinkResult) -> None:
            if time.monotonic() > deadline:
                result.detail = f"the {DEADLINE_SECONDS} second limit for checking links ran out"
                return
            with gate(result.url):
                _check(client, result)

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            list(pool.map(one, queue))


def _check(client: httpx.Client, result: LinkResult) -> None:
    """One request for this URL: HEAD, or a GET closed unread when HEAD is refused."""
    try:
        response = client.head(result.url)
        result.method = "HEAD"
        if response.status_code in HEAD_REFUSED:
            with client.stream("GET", result.url) as streamed:  # closed without reading the body
                response = streamed
            result.method = "GET"
    except httpx.TooManyRedirects:
        result.outcome, result.detail = "broken", f"more than {MAX_HOPS} redirects, a loop or a long chain"
        return
    except httpx.TimeoutException:
        result.outcome, result.detail = "broken", f"no answer within {TIMEOUT_SECONDS} seconds"
        return
    except httpx.ConnectError as exc:
        result.outcome, result.detail = "broken", f"could not connect ({exc})"
        return
    except Exception as exc:  # anything else says nothing about the link itself
        result.outcome, result.detail = "not verified", f"{type(exc).__name__}: {exc}"
        return
    status = response.status_code
    result.status, result.final_url = status, str(response.url)
    if status < 400:
        result.outcome = "ok"
    elif status in TURNED_AWAY or status >= 600:
        result.outcome = "not verified"
        result.detail = f"status {status}, which usually means automated checks are turned away, not visitors"
    else:
        result.outcome, result.detail = "broken", f"status {status} ({status_phrase(status)})"
