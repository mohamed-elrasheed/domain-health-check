"""Integration tests reach real servers, so this folder replaces the socket guard in tests/conftest.py.
They are opt-in (pytest -m integration) and never spend API quota: every key is still stripped."""

from __future__ import annotations

from pathlib import Path

import pytest

from domain_health_check import cli
from domain_health_check.checks import rdap


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Overrides the parent fixture of the same name: the network stays open, the secrets stay out."""
    rdap._load_bootstrap.cache_clear()
    for secret in ("PAGESPEED_API_KEY", "PLACES_API_KEY", "SMTP_USERNAME", "SMTP_PASSWORD", "REPORT_RECIPIENT"):
        monkeypatch.delenv(secret, raising=False)
    monkeypatch.setattr(cli, "ENV_FILE", Path(__file__).parent / "no-such.env")
