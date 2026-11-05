"""Found by the second audit: a redirect to another website, and the TLS check's own connection."""

import pytest

from domain_health_check import netguard, runner
from domain_health_check.checks import tls
from domain_health_check.fetcher import FetchError


def test_a_home_page_that_redirects_to_another_website_stops_the_site_checks(make_page):
    page = make_page(requested_url="https://throwaway.example/", final_url="https://someone-else.example/")
    stopped = runner._left_the_site(page)
    assert isinstance(stopped, FetchError) and "someone-else.example" in stopped.reason


@pytest.mark.parametrize("final", ["https://example.com/", "https://www.example.com/", "http://example.com/x",
                                   "https://shop.example.com/"])
def test_a_move_within_the_same_site_is_fine(make_page, final):
    page = make_page(requested_url="https://example.com/", final_url=final)
    assert runner._left_the_site(page) is page


def test_the_tls_check_never_connects_to_a_private_address(monkeypatch):
    monkeypatch.setattr(netguard, "public", lambda host, *a: False)
    monkeypatch.setattr(tls.socket, "create_connection", lambda *a, **k: pytest.fail("connected"))
    with pytest.raises(ConnectionRefusedError, match="private network address"):
        tls.fetch_tls_info("inside.example")
