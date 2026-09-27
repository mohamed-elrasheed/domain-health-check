import io
import urllib.error
from datetime import datetime, timezone

import pytest

from domain_health_check.checks import rdap
from domain_health_check.models import Status

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)

BOOTSTRAP = {
    "services": [
        [["com", "net"], ["http://rdap.example-registry.test/", "https://rdap.example-registry.test/"]],
        [["test"], ["https://rdap.test-registry.test"]],
        [["co.test"], ["https://rdap.co-test-registry.test/"]],
    ]
}


def rdap_record(expiry: str | None, registrar: str = "Example Registrar, Inc.") -> dict:
    events = [{"eventAction": "registration", "eventDate": "2015-03-01T00:00:00Z"}]
    if expiry:
        events.append({"eventAction": "expiration", "eventDate": expiry})
    return {
        "events": events,
        "entities": [{"roles": ["registrar"], "vcardArray": ["vcard", [["version", {}, "text", "4.0"],
                                                                     ["fn", {}, "text", registrar]]]}],
    }


def test_find_rdap_server_prefers_https():
    assert rdap.find_rdap_server("example.com", BOOTSTRAP) == "https://rdap.example-registry.test/"


def test_find_rdap_server_prefers_longest_suffix():
    assert rdap.find_rdap_server("shop.example.co.test", BOOTSTRAP) == "https://rdap.co-test-registry.test/"


def test_find_rdap_server_unknown_tld():
    assert rdap.find_rdap_server("example.invalid", BOOTSTRAP) is None


def test_fetch_rdap_builds_url(monkeypatch):
    requested = []
    monkeypatch.setattr(rdap, "_load_bootstrap", lambda: BOOTSTRAP)
    monkeypatch.setattr(rdap, "_get_json", lambda url: requested.append(url) or {})
    rdap.fetch_rdap("example.test")
    assert requested == ["https://rdap.test-registry.test/domain/example.test"]


@pytest.mark.parametrize("expiry, expected", [
    ("2027-01-01T00:00:00Z", Status.PASS),
    ("2026-02-15T00:00:00Z", Status.WARN),   # 45 days
    ("2026-01-10T00:00:00Z", Status.FAIL),   # 9 days
    ("2025-12-01T00:00:00Z", Status.FAIL),   # already expired
])
def test_expiry_thresholds(expiry, expected):
    result = rdap.evaluate_registration(rdap_record(expiry), NOW)
    assert result.status is expected
    assert "Registrar: Example Registrar, Inc." in result.details


def test_missing_expiry_is_warn():
    assert rdap.evaluate_registration(rdap_record(None), NOW).status is Status.WARN


def test_http_404_is_warn(monkeypatch):
    def not_found(domain):
        raise urllib.error.HTTPError("https://rdap.test/domain/x", 404, "Not Found", {}, io.BytesIO())
    monkeypatch.setattr(rdap, "fetch_rdap", not_found)
    [result] = rdap.check_registration("example.com", NOW)
    assert result.status is Status.WARN
    assert "no record" in result.summary


def test_unreachable_is_warn(monkeypatch):
    def offline(domain):
        raise urllib.error.URLError("timed out")
    monkeypatch.setattr(rdap, "fetch_rdap", offline)
    [result] = rdap.check_registration("example.com", NOW)
    assert result.status is Status.WARN


def test_check_registration_success(monkeypatch):
    monkeypatch.setattr(rdap, "fetch_rdap", lambda domain: rdap_record("2027-06-01T00:00:00Z"))
    [result] = rdap.check_registration("example.com", NOW)
    assert result.status is Status.PASS
    assert "01 June 2027" in result.summary
