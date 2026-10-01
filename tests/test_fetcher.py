"""The fetcher runs against httpx.MockTransport: real request/redirect handling, no sockets."""

import httpx
import pytest

from domain_health_check import fetcher
from domain_health_check.fetcher import FetchError, RobotsDisallowed, robots_allows

HOME = "<html><head><title>Example</title></head><body><h1>Hello</h1></body></html>"


def site(routes: dict[str, httpx.Response], seen: list[httpx.Request] | None = None) -> httpx.MockTransport:
    """A fake web server: maps full URLs to responses, 404 for anything else."""
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        return routes.get(str(request.url), httpx.Response(404))
    return httpx.MockTransport(handle)


def test_fetches_page_and_records_redirect_chain():
    seen = []
    transport = site({
        "https://example.com/": httpx.Response(301, headers={"Location": "/home"}),  # relative is valid
        "https://example.com/home": httpx.Response(302, headers={"Location": "https://www.example.com/"}),
        "https://www.example.com/": httpx.Response(
            200, html=HOME, headers={"Strict-Transport-Security": "max-age=31536000"}),
    }, seen)
    page = fetcher.fetch_page("example.com", transport=transport)

    assert page.requested_url == "https://example.com/"
    assert page.final_url == "https://www.example.com/"
    assert page.redirect_chain == [("https://example.com/", 301), ("https://example.com/home", 302)]
    assert page.status == 200
    assert page.headers["strict-transport-security"] == "max-age=31536000"
    assert page.html == HOME and page.byte_size == len(HOME) and not page.truncated
    assert [str(r.url) for r in seen][0] == "https://example.com/robots.txt"
    assert all(r.headers["user-agent"] == fetcher.USER_AGENT for r in seen)


def test_user_agent_names_us_and_links_to_the_form():
    assert fetcher.USER_AGENT == "domain-health-check/0.1 (+https://www.mizangroupllc.com/digital)"


def test_error_status_is_returned_not_raised():
    transport = site({"https://example.com/": httpx.Response(503, text="down", headers={"X-Test": "1"})})
    page = fetcher.fetch_page("example.com", transport=transport)
    assert page.status == 503 and page.headers["x-test"] == "1"


def test_robots_disallow_stops_before_the_home_page():
    seen = []
    transport = site({
        "https://example.com/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /\n"),
        "https://example.com/": httpx.Response(200, html=HOME),
    }, seen)
    with pytest.raises(RobotsDisallowed):
        fetcher.fetch_page("example.com", transport=transport)
    assert [str(r.url) for r in seen] == ["https://example.com/robots.txt"]


@pytest.mark.parametrize("status, text, allowed", [
    (200, "User-agent: *\nDisallow: /private/\n", True),
    (200, "User-agent: *\nDisallow: /\n", False),
    (200, "User-agent: domain-health-check\nDisallow: /\n\nUser-agent: *\nAllow: /\n", False),
    (200, "User-agent: SomeOtherBot\nDisallow: /\n", True),
    (200, "", True),
    (404, "", True),   # RFC 9309: no robots.txt means no rules
    (403, "", True),
    (500, "", False),  # RFC 9309: server error means assume everything is disallowed
])
def test_robots_allows(status, text, allowed):
    assert robots_allows(status, text, "https://example.com/") is allowed


def test_too_many_redirects_is_a_fetch_error():
    transport = site({"https://example.com/": httpx.Response(302, headers={"Location": "https://example.com/"})})
    with pytest.raises(FetchError, match="redirected more than"):
        fetcher.fetch_page("example.com", transport=transport)


def test_oversized_page_is_cut_off_and_flagged(monkeypatch):
    monkeypatch.setattr(fetcher, "MAX_BYTES", 100)
    big = b"<html>" + b"x" * 10_000

    def stream():
        for i in range(0, len(big), 40):
            yield big[i:i + 40]

    transport = site({"https://example.com/": httpx.Response(200, content=stream())})
    page = fetcher.fetch_page("example.com", transport=transport)
    assert page.truncated
    assert len(page.html) == 100
    assert 100 < page.byte_size <= 140  # stopped within one chunk of the cap


def test_connection_failure_is_a_fetch_error():
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)
    with pytest.raises(FetchError, match="ConnectError") as info:
        fetcher.fetch_page("example.com", transport=httpx.MockTransport(refuse))
    assert info.value.url == "https://example.com/"  # the owner sees their home page, not robots.txt
    assert "robots.txt" in info.value.reason
