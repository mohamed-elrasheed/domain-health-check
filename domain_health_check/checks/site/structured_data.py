"""Does the structured data agree with the page people actually see?

Structured data (JSON-LD) is information written into the page's code for
search engines, not people. Google can show it directly in results, prices
included. It is easy to update the visible page and forget this copy: Mizan's
own /services kept retired URLs and superseded prices in JSON-LD while the
page read correctly.

We compare two kinds of value:
  * Prices (price, lowPrice, highPrice, minPrice, maxPrice) against numbers in
    the visible text, so "1500" matches "$1,500".
  * Same-site URLs against the page's links, then the sitemap's page list.
    URLs are rarely visible text, so a link is the evidence that the page
    still points there; the sitemap is the site's own list of live pages.

Skipped: @id (an identifier, not a link), @context, image URLs, and other
sites (sameAs profiles and the like). Everything is measured on the HTML as
delivered, before scripts run, so a page whose content is built by scripts is
reported as not checked rather than as a mismatch.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterator
from urllib.parse import urljoin, urlsplit

from ...fetcher import PageContext, same_site
from ...models import SITE, CheckResult, Status
from ._html import parse, visible_text, word_count
from .indexing import sitemap_pages

NAME = "Structured data matches the page"

PRICE_KEYS = {"price", "lowprice", "highprice", "minprice", "maxprice"}
SKIPPED_KEYS = {"@id", "@context", "@type", "sameas", "image", "logo", "contenturl", "thumbnailurl", "embedurl"}
MIN_WORDS = 50  # below this the visible page is mostly built by scripts, so there is nothing fair to compare
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")

EXPLANATION = (
    "Structured data is information written into your page's code for search engines rather than people. Google "
    "can show it directly in search results, prices included. If it is out of date, Google can show customers "
    "prices you no longer charge or send them to pages that no longer exist, even when the visible page is correct."
)


@dataclass
class Value:
    path: str  # where in the JSON-LD, e.g. "block 1: makesOffer[0].price"
    kind: str  # "price" or "url"
    raw: str


def to_number(text: str) -> Decimal | None:
    match = NUMBER.search(text)
    try:
        return Decimal(match.group().replace(",", "")) if match else None
    except InvalidOperation:
        return None


def _walk(data, path: str) -> Iterator[tuple[str, str, object]]:
    """(path, key, value) for every scalar, skipping the keys whose values we never compare."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in SKIPPED_KEYS:
                continue
            child = f"{path}.{key}" if path else key
            if isinstance(value, (dict, list)):
                yield from _walk(value, child)
            else:
                yield child, key.lower(), value
    elif isinstance(data, list):
        for i, item in enumerate(data):
            yield from _walk(item, f"{path}[{i}]")


def extract_values(blocks: list[str], page_url: str) -> tuple[list[Value], list[str]]:
    """(prices and same-site URLs, problems with blocks that are not valid JSON)."""
    values, invalid = [], []
    for n, block in enumerate(blocks, start=1):
        try:
            data = json.loads(block)
        except json.JSONDecodeError as exc:
            invalid.append(f"Block {n} is not valid JSON ({exc.msg} at line {exc.lineno}), so search engines ignore "
                           "it.")
            continue
        for path, key, value in _walk(data, ""):
            label = f"block {n}: {path}"
            if key in PRICE_KEYS and value not in (None, ""):
                values.append(Value(label, "price", str(value)))
            elif isinstance(value, str) and value.startswith(("http://", "https://")) and same_site(value, page_url):
                values.append(Value(label, "url", value))
    return values, invalid


def _url_key(url: str) -> str:
    """Scheme, www, trailing slash, query and fragment do not make a different page here."""
    parts = urlsplit(url)
    return f"{(parts.hostname or '').removeprefix('www.')}{parts.path.rstrip('/') or '/'}"


def evaluate_structured_data(
    blocks: list[str], page_url: str, page_text: str, page_links: set[str], sitemap_urls: set[str],
    rendered: bool = False,
) -> CheckResult:
    """rendered: page_text and page_links come from the page after a browser ran it, with what a visitor cannot
    see left out. Otherwise they come from the HTML as delivered, which can include text nobody sees, so the
    result says "the page", never "the visible page"."""
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, NAME, status, summary, EXPLANATION, fix, list(details), ran, measure=measure)

    if not blocks:
        return result(Status.WARN, "Your home page has no structured data, so there was nothing for us to compare.",
                      "Nothing needs fixing. If you would like Google to show details such as your hours, address "
                      "or prices in search results, ask your web developer about adding structured data.",
                      ran=False)
    measured = ("We compared against the page after a browser ran its scripts, leaving out anything a visitor "
                "could not see." if rendered else "We compared against the page as delivered, before any scripts "
                "run, including any text the page hides.")
    if word_count(page_text) < MIN_WORDS:
        return result(Status.WARN, "Your home page content is built by scripts after it loads, so we could not "
                                   "compare its structured data with what visitors see.",
                      "Nothing to do based on this report.", [measured], ran=False)

    values, invalid = extract_values(blocks, page_url)
    numbers = {n for n in (to_number(m.group()) for m in NUMBER.finditer(page_text)) if n is not None}
    links = {_url_key(u) for u in page_links}
    listed = {_url_key(u) for u in sitemap_urls}

    found, unmatched = [], []
    for value in values:
        if value.kind == "price":
            number = to_number(value.raw)
            if number is not None and number in numbers:
                found.append(f"Price {value.raw} at {value.path}: found (page text)")
            else:
                unmatched.append(value)
        elif _url_key(value.raw) in links:
            found.append(f"URL {value.raw} at {value.path}: found (page link)")
        elif _url_key(value.raw) in listed:
            found.append(f"URL {value.raw} at {value.path}: found (sitemap)")
        else:
            unmatched.append(value)

    details = [measured] + invalid
    for v in unmatched:
        if v.kind == "price":
            details.append(f"Price {v.raw} at {v.path}: not found in the page text")
        else:
            details.append(f"URL {v.raw} at {v.path}: not linked from the page or in the sitemap")
    details += found

    if unmatched or invalid:
        if unmatched:
            summary = (f"Your home page structured data lists {_counted(unmatched)} that we could not find on the "
                       "page itself.")
        else:
            summary = "Part of your home page structured data has an error, so search engines ignore it."
        return result(Status.WARN, summary,
                      "Ask your web developer to update the structured data on your home page so it matches what "
                      "the page says today. The technical details list each value that did not match.", details,
                      measure=len(found) / (len(found) + len(unmatched) + len(invalid)))  # the share that matched

    if not values:
        return result(Status.PASS, "Your home page structured data has no prices or links for us to compare.",
                      details=details, ran=False)
    verb = "matches" if _distinct(values) == 1 else "match"
    page = "the visible page" if rendered else "the page"
    return result(Status.PASS, f"The {_counted(values)} in your home page structured data {verb} {page}.",
                  details=details)


def _distinct(values: list[Value]) -> int:
    return len({(v.kind, v.raw) for v in values})


def _counted(values: list[Value]) -> str:
    """"2 prices and 1 link", counting a value once however many places repeat it."""
    distinct = {(v.kind, v.raw) for v in values}
    prices = sum(kind == "price" for kind, _ in distinct)
    links = len(distinct) - prices
    parts = []
    if prices:
        parts.append(f"{prices} price{'s' if prices != 1 else ''}")
    if links:
        parts.append(f"{links} link{'s' if links != 1 else ''}")
    return " and ".join(parts)


def check_structured_data(page: PageContext) -> list[CheckResult]:
    # The structured data is what a search engine reads; what it is compared against is what a visitor sees.
    blocks = [
        node.text() for node in parse(page.indexed_html).css("script[type]")
        if (node.attributes.get("type") or "").split(";")[0].strip().lower() == "application/ld+json"
    ]
    screen = parse(page.visible_html)
    links = {urljoin(page.final_url, node.attributes.get("href") or "") for node in screen.css("a[href]")}
    return [evaluate_structured_data(blocks, page.final_url, visible_text(page.visible_html), links,
                                     sitemap_pages(page.sitemap), rendered=page.rendered)]
