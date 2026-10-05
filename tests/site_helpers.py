"""Small helpers for the site check tests. Every variant starts from the real Mizan page."""

from __future__ import annotations

from dataclasses import replace

import httpx

from domain_health_check.fetcher import PageContext


def edited(page: PageContext, old: str, new: str) -> PageContext:
    """The same page with one piece of HTML changed. Fails if the piece is not there, so a fixture
    update cannot silently turn a failure test into a passing one."""
    assert old in page.html, f"fixture no longer contains {old!r}"
    return replace(page, html=page.html.replace(old, new, 1))


def with_body(page: PageContext, extra: str) -> PageContext:
    """The same page with extra HTML just before </body>."""
    return edited(page, "</body>", f"{extra}</body>")


def ld_json(data: str) -> str:
    return f'<script type="application/ld+json">{data}</script>'


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def healthy_site(request: httpx.Request) -> httpx.Response:
    """Every link works and the icon is an image: what a report sees on a site with nothing wrong."""
    if request.url.path.endswith((".ico", ".png", ".svg")):
        return httpx.Response(200, headers={"content-type": "image/png"}, content=PNG)
    return httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>")
