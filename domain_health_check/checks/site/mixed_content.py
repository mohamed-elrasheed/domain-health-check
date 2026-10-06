"""Does everything on the secure home page also load securely?

A page served over https that pulls an image, script, stylesheet, font or framed page over plain http is
"mixed content". Browsers block the scripts and fonts, which can break the page, and may show the padlock as not
secure. We read the rendered page's resource list (what the browser requested, what it warned about, and what the
page names after its scripts ran and lazy loading caught up), so assets added by scripts count. Without a browser
we read the page as delivered, and say so.
"""

from __future__ import annotations

from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from ...fetcher import PageContext
from ...models import SITE, CheckResult, Status
from ._editor import where

NAME = "Mixed content"
KINDS = ("image", "script", "stylesheet", "font", "iframe")
EXAMPLES = 5

EXPLANATION = (
    "Your page is served securely, but it also loads some files over an insecure connection. Browsers block some "
    "of those files, which can break parts of the page, and can stop showing the page as fully secure."
)
FIX = ("{where}, change each address listed in the technical details from http:// to https://, or replace the file "
       "with a copy uploaded to your site.")


def delivered_resources(html: str, base: str) -> list[tuple[str, str]]:
    """(url, kind) for the assets the delivered page names, for when no browser ran."""
    tree = HTMLParser(html)
    found = []
    for node in tree.css("img, source"):
        found.append((node.attributes.get("src") or "", "image"))
        found += [(part.strip().split(" ")[0], "image") for part in (node.attributes.get("srcset") or "").split(",")]
    found += [(node.attributes.get("src") or "", "script") for node in tree.css("script[src]")]
    for node in tree.css("link[href]"):
        rel = (node.attributes.get("rel") or "").lower()
        if "stylesheet" in rel:
            found.append((node.attributes.get("href") or "", "stylesheet"))
        elif "preload" in rel and (node.attributes.get("as") or "").lower() == "font":
            found.append((node.attributes.get("href") or "", "font"))
    found += [(node.attributes.get("src") or "", "iframe") for node in tree.css("iframe[src]")]
    return [(urljoin(base, u.strip()), kind) for u, kind in found if u and u.strip()]


def evaluate_mixed_content(page_url: str, resources: list[tuple[str, str]], rendered: bool,
                           editor: str = "") -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True) -> CheckResult:
        return CheckResult(SITE, NAME, status, summary, EXPLANATION, fix, list(details), ran)

    source = ("Read from the page after a browser loaded it and scrolled to the end, including what its scripts "
              "added and what the browser warned about." if rendered else
              "Read from the page as delivered, before any scripts ran, so files that scripts add are not included.")
    if urlsplit(page_url).scheme != "https":
        return result(Status.WARN, "Your home page is not served over a secure connection, so there is no mixed "
                                   "content to look for.", "Nothing to do based on this check.", [source], ran=False)
    insecure: dict[str, str] = {}
    for url, kind in resources:
        if kind in KINDS and url.lower().startswith("http://"):
            insecure.setdefault(url, kind)
    if not insecure:
        return result(Status.PASS, "Everything on your home page loads over a secure connection.", details=[source])
    items = list(insecure.items())
    details = [source] + [f"{kind}: {url}" for url, kind in items[:EXAMPLES]]
    if len(items) > EXAMPLES:
        details.append(f"And {len(items) - EXAMPLES} more.")
    noun = "file" if len(items) == 1 else "files"
    verb = "loads" if len(items) == 1 else "load"
    return result(Status.WARN, f"{len(items)} {noun} on your home page {verb} over an insecure connection.",
                  FIX.format(where=where(editor)),
                  details)


def check_mixed_content(page: PageContext) -> list[CheckResult]:
    resources = page.resources if page.rendered else delivered_resources(page.html, page.final_url)
    return [evaluate_mixed_content(page.final_url, resources, page.rendered, page.editor)]
