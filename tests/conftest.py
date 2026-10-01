"""Shared fixtures. The autouse guard makes any real network access fail loudly."""

from __future__ import annotations

import socket
import urllib.request

import httpx
import pytest

from domain_health_check import dns_utils
from domain_health_check.checks import rdap
from domain_health_check.fetcher import PageContext


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
