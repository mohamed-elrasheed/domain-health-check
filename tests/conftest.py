"""Shared fixtures. The autouse guard makes any real network access fail loudly."""

from __future__ import annotations

import json
import socket
import urllib.request
from pathlib import Path

import httpx
import pytest

from domain_health_check import cli, dns_utils
from domain_health_check.checks import rdap
from domain_health_check.fetcher import FetchedFile, PageContext

MIZAN = Path(__file__).parent / "fixtures" / "mizangroupllc.com"


def _blocked(*args, **kwargs):
    raise RuntimeError("Tests must never touch the network; mock the lookup instead.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", _blocked)  # httpx.MockTransport still works
    rdap._load_bootstrap.cache_clear()
    # Never let a developer's real API key, or their .env file, into a test run.
    for secret in ("PAGESPEED_API_KEY", "PLACES_API_KEY", "SMTP_USERNAME", "SMTP_PASSWORD", "REPORT_RECIPIENT"):
        monkeypatch.delenv(secret, raising=False)
    monkeypatch.setattr(cli, "ENV_FILE", Path(__file__).parent / "no-such.env")


@pytest.fixture
def make_page():
    """Builds a PageContext as if the fetch had succeeded. Override any field by keyword."""
    def build(**overrides) -> PageContext:
        html = overrides.pop("html", "<html><head><title>Example</title></head><body></body></html>")
        fields = dict(
            requested_url="https://example.com/", final_url="https://example.com/", redirect_chain=[],
            status=200, headers={}, html=html, byte_size=len(html.encode()), elapsed_ms=120, ttfb_ms=80,
            robots=None, sitemap=None,
        )
        fields.update(overrides)
        return PageContext(**fields)
    return build


@pytest.fixture
def mizan_page() -> PageContext:
    """www.mizangroupllc.com as captured on 2026-10-01: the saved files plus the measured response in
    response.json. Tests that need a failing page edit a copy of this one rather than inventing a page."""
    measured = json.loads((MIZAN / "response.json").read_text(encoding="utf-8"))
    return PageContext(
        requested_url=measured["requested_url"],
        final_url=measured["final_url"],
        redirect_chain=[tuple(hop) for hop in measured["redirect_chain"]],
        status=measured["status"],
        headers=measured["headers"],
        html=(MIZAN / "home.html").read_text(encoding="utf-8"),
        byte_size=measured["byte_size"],
        elapsed_ms=measured["elapsed_ms"],
        ttfb_ms=measured["ttfb_ms"],
        robots=FetchedFile(text=(MIZAN / "robots.txt").read_text(encoding="utf-8"), **measured["robots"]),
        sitemap=FetchedFile(text=(MIZAN / "sitemap.xml").read_text(encoding="utf-8"), **measured["sitemap"]),
    )


@pytest.fixture
def psi_mobile() -> dict:
    """A real PageSpeed Insights v5 response for www.mizangroupllc.com, mobile, trimmed. It has
    all four categories (performance as a float, the others as ints), and loadingExperience holds nothing
    but initial_url."""
    return json.loads((MIZAN / "psi-mobile.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_dns(monkeypatch):
    """Returns a dict you fill with {(name, rdtype): [records]}. A value can also be an exception to raise."""
    records: dict[tuple[str, str], object] = {}

    def lookup(name: str, rdtype: str) -> list[str]:
        value = records.get((name.lower(), rdtype.upper()), [])
        if isinstance(value, Exception):
            raise value
        return list(value)

    monkeypatch.setattr(dns_utils, "lookup", lookup)
    monkeypatch.setattr(dns_utils, "lookup_txt", lambda name: lookup(name, "TXT"))
    return records
