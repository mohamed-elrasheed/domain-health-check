import urllib.error

import pytest

from domain_health_check.checks import http_headers
from domain_health_check.models import Status


@pytest.mark.parametrize("value, expected", [
    ("max-age=31536000; includeSubDomains; preload", Status.PASS),
    ("max-age=15552000", Status.PASS),
    ("max-age=86400", Status.WARN),
    ("max-age=0", Status.WARN),
    ("includeSubDomains", Status.WARN),
    (None, Status.FAIL),
])
def test_hsts(value, expected):
    assert http_headers.evaluate_hsts(value).status is expected


def test_csp_present_passes_and_notes_unsafe_inline():
    result = http_headers.evaluate_csp("default-src 'self'; script-src 'self' 'unsafe-inline'", None)
    assert result.status is Status.PASS
    assert any("unsafe-inline" in d for d in result.details)


def test_csp_report_only_warns():
    assert http_headers.evaluate_csp(None, "default-src 'self'").status is Status.WARN


def test_csp_missing_warns():
    assert http_headers.evaluate_csp(None, None).status is Status.WARN


@pytest.mark.parametrize("value, expected", [("nosniff", Status.PASS), ("NoSniff ", Status.PASS),
                                             ("sniff", Status.WARN), (None, Status.WARN)])
def test_content_type_options(value, expected):
    assert http_headers.evaluate_content_type_options(value).status is expected


def test_check_http_headers_uses_fetched_headers(monkeypatch):
    headers = {"strict-transport-security": "max-age=31536000", "x-content-type-options": "nosniff"}
    monkeypatch.setattr(http_headers, "fetch_headers", lambda d: ("https://www.example.com/", headers))
    results = http_headers.check_http_headers("example.com")
    assert [r.status for r in results] == [Status.PASS, Status.WARN, Status.PASS]
    assert all("Checked page: https://www.example.com/" in r.details for r in results)


def test_unreachable_site_gives_single_warning(monkeypatch):
    def offline(domain):
        raise urllib.error.URLError("Name or service not known")
    monkeypatch.setattr(http_headers, "fetch_headers", offline)
    [result] = http_headers.check_http_headers("example.com")
    assert result.status is Status.WARN
