"""Shared fixtures. The autouse guard makes any real network access fail loudly."""

from __future__ import annotations

import socket
import urllib.request

import pytest

from domain_health_check import dns_utils
from domain_health_check.checks import rdap


def _blocked(*args, **kwargs):
    raise RuntimeError("Tests must never touch the network; mock the lookup instead.")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(urllib.request, "urlopen", _blocked)
    rdap._load_bootstrap.cache_clear()


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
