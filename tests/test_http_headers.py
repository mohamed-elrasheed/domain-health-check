import pytest

from domain_health_check.checks import http_headers
from domain_health_check.fetcher import FetchError, RobotsDisallowed
from domain_health_check.models import Status


@pytest.mark.parametrize("value, expected", [
    ("max-age=31536000; includeSubDomains; preload", Status.PASS),
    ("max-age=15552000", Status.PASS),
    ("max-age=86400", Status.WARN),
    ("max-age=0", Status.WARN),
    ("includeSubDomains", Status.WARN),
    (None, Status.WARN),  # missing HSTS is a risk, not breakage
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


def test_check_http_headers_uses_fetched_headers(make_page):
    headers = {"strict-transport-security": "max-age=31536000", "x-content-type-options": "nosniff"}
    page = make_page(final_url="https://www.example.com/", headers=headers)
    results = http_headers.check_http_headers(page)
    assert [r.status for r in results] == [Status.PASS, Status.WARN, Status.PASS]
    assert all("Checked page: https://www.example.com/" in r.details for r in results)


def test_error_page_headers_are_not_judged():
    from domain_health_check.fetcher import PageStatusError
    [result] = http_headers.check_http_headers(PageStatusError("https://example.com/", 403, "https://example.com/"))
    assert not result.ran and "status 403" in result.summary


def test_unreachable_site_gives_single_warning():
    [result] = http_headers.check_http_headers(FetchError("https://example.com/", "ConnectError: refused"))
    assert result.status is Status.WARN
    assert "could not load https://example.com/" in result.summary
    assert result.details == ["Error: ConnectError: refused"]
    assert not result.ran


def test_robots_block_says_so_instead_of_blaming_the_host():
    [result] = http_headers.check_http_headers(RobotsDisallowed("https://example.com/", "Disallow: /"))
    assert result.status is Status.WARN
    assert "asks automated tools not to load" in result.summary
    assert "web host" not in result.fix



def test_hsts_advice_leaves_out_subdomains_until_they_all_serve_https():
    from domain_health_check.checks import http_headers
    result = http_headers.evaluate_hsts(None)
    assert "Header to add: Strict-Transport-Security: max-age=31536000" in result.details
    assert not any("includeSubDomains;" in d or d.endswith("includeSubDomains") for d in result.details)
    assert "Add includeSubDomains only after every subdomain serves HTTPS." in result.details
