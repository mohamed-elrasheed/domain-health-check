"""How the home page reaches a visitor: on a phone, how heavy, how fast, how many redirects.

Page weight here is the HTML document alone, decompressed, and time to first
byte includes any redirects. Images, scripts and styles are not loaded, so a
full speed score is a separate, heavier step.
"""

from __future__ import annotations

import re

from ...fetcher import MAX_BYTES, PageContext
from ...models import SITE, CheckResult, Status
from ._html import meta, parse

VIEWPORT = "Mobile viewport"
PAGE_WEIGHT = "Page weight"
REDIRECTS = "Redirect chain"

MAX_HTML_BYTES = 150_000  # 150 KB, counting 1 KB as 1,000 bytes
MAX_TTFB_MS = 5_000
MAX_HOPS = 2

VIEWPORT_EXPLANATION = (
    "Most visitors to a small business website arrive on a phone. This setting tells phones to fit the page to "
    "their screen instead of showing a tiny, zoomed-out desktop version."
)
WEIGHT_EXPLANATION = (
    "Large pages and slow servers make visitors wait, especially on phones, and many people leave a page that "
    "takes more than a few seconds to appear."
)
REDIRECT_EXPLANATION = (
    "A redirect sends a visitor from one address to another, for example from your address without \"www\" to "
    "the one with it. One is normal. Each extra step is another wait before the page starts to load."
)


# ---------- Mobile viewport

def evaluate_viewport(contents: list[str]) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(SITE, VIEWPORT, status, summary, VIEWPORT_EXPLANATION, fix, list(details))

    fix = (
        "Ask your web developer to add the standard mobile viewport setting, "
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">, to your home page."
    )
    if not contents:
        return result(Status.WARN, "Your home page is not set up for phones, so phones show a shrunken desktop "
                                   "version of it.", fix)
    details = [f"Viewport: {content}" for content in contents]
    if not any(re.search(r"width\s*=\s*device-width", content, re.IGNORECASE) for content in contents):
        return result(Status.WARN, "Your home page has a phone setting, but it does not fit the page to the screen "
                                   "width.", fix, details)
    return result(Status.PASS, "Your home page is set up to fit phone screens.", details=details)


def check_viewport(page: PageContext) -> list[CheckResult]:
    return [evaluate_viewport(meta(parse(page.html), "viewport"))]


# ---------- Page weight

def evaluate_page_weight(byte_size: int, ttfb_ms: int, elapsed_ms: int, hops: int, truncated: bool) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(SITE, PAGE_WEIGHT, status, summary, WEIGHT_EXPLANATION, fix, list(details))

    size_kb = f"more than {MAX_BYTES // 1000:,} KB" if truncated else f"{round(byte_size / 1000):,} KB"
    details = [
        f"HTML document: {byte_size:,} bytes{' (we stopped reading here)' if truncated else ''}, decompressed. "
        "Images, scripts and styles are not included.",
        f"Time to first byte: {ttfb_ms:,} ms, including {hops} redirect(s)",
        f"Time to last byte: {elapsed_ms:,} ms",
    ]
    problems = []
    if truncated or byte_size >= MAX_HTML_BYTES:
        problems.append(f"Your home page is {size_kb} before images, larger than the {MAX_HTML_BYTES // 1000} KB we "
                        "look for.")
    if ttfb_ms >= MAX_TTFB_MS:
        problems.append(f"Your server took {ttfb_ms / 1000:.1f} seconds to start sending your home page.")
    if problems:
        return result(Status.WARN, " ".join(problems),
                      "Ask your web developer to look at what makes the page large or slow to start. The technical "
                      "details show exactly what we measured.", details)
    return result(Status.PASS, f"Your home page is {size_kb} before images, and your server started sending it in "
                               f"{ttfb_ms / 1000:.2f} seconds.", details=details)


def check_page_weight(page: PageContext) -> list[CheckResult]:
    return [evaluate_page_weight(page.byte_size, page.ttfb_ms, page.elapsed_ms, len(page.redirect_chain),
                                 page.truncated)]


# ---------- Redirect chain

def evaluate_redirects(requested_url: str, chain: list[tuple[str, int]], final_url: str) -> CheckResult:
    """chain holds resolved URLs, so a relative Location header has already been turned into an address."""
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(SITE, REDIRECTS, status, summary, REDIRECT_EXPLANATION, fix, list(details))

    details = [f"{url} answered {status}" for url, status in chain] + [f"Final address: {final_url}"]
    hops = len(chain)
    if hops > MAX_HOPS:
        return result(Status.WARN, f"Visitors going to {requested_url} pass through {hops} redirects before they "
                                   "reach your home page.",
                      f"Ask your web developer to point your redirects straight to the final address, {final_url}",
                      details)
    if hops == 0:
        return result(Status.PASS, "Your home page loads directly, with no redirects.", details=details)
    noun = "redirect" if hops == 1 else "redirects"
    return result(Status.PASS, f"Your address reaches {final_url} in {hops} {noun}, which is normal.",
                  details=details)


def check_redirects(page: PageContext) -> list[CheckResult]:
    return [evaluate_redirects(page.requested_url, page.redirect_chain, page.final_url)]
