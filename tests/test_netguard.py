"""The report never contacts a private network address, whatever a submitted page links or redirects to."""

import httpx
import pytest

from domain_health_check import linkcheck, netguard


def resolver(table):
    def resolve(host, port):
        if host not in table:
            raise OSError("no such host")
        return [(2, 1, 6, "", (addr, 0)) for addr in table[host]]
    return resolve


@pytest.mark.parametrize("host", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "[::1]",
                                  "0.0.0.0", "100.64.0.1", "localhost-in-table"])
def test_private_hosts_are_refused(host):
    assert not netguard.public(host, resolver({"localhost-in-table": ["127.0.0.1"]}))


def test_a_name_is_refused_if_any_of_its_addresses_is_private():
    assert not netguard.public("mixed.test", resolver({"mixed.test": ["93.184.216.34", "10.0.0.1"]}))
    assert netguard.public("example.test", resolver({"example.test": ["93.184.216.34"]}))
    assert netguard.public("8.8.8.8")


def test_the_transport_refuses_each_redirect_hop_to_a_private_address():
    hits = []

    def handler(request):
        hits.append(str(request.url))
        if request.url.host == "site.test":
            return httpx.Response(302, headers={"Location": "http://inside.test/admin"})
        return httpx.Response(200)

    guard = netguard.PublicOnly(httpx.MockTransport(handler),
                                resolver({"site.test": ["93.184.216.34"], "inside.test": ["192.168.1.1"]}))
    with httpx.Client(transport=guard, follow_redirects=True) as client, pytest.raises(netguard.PrivateAddress):
        client.get("https://site.test/")
    assert hits == ["https://site.test/"]  # the private hop never reached the network


def test_a_link_to_a_private_address_is_not_verified_and_never_contacted():
    contacted = []
    guard = netguard.PublicOnly(httpx.MockTransport(lambda r: contacted.append(r) or httpx.Response(200)),
                                resolver({}))
    result = linkcheck.LinkResult("http://192.168.1.1/", "router", False, "not requested")
    with httpx.Client(transport=guard) as client:
        linkcheck._check(client, result)
    assert result.outcome == "not verified" and "private network address" in result.detail
    assert contacted == []


def test_the_browser_guard_aborts_private_requests_only():
    class Route:
        def __init__(self, url):
            self.request = type("R", (), {"url": url})()
            self.done = None

        def abort(self):
            self.done = "abort"

        def continue_(self):
            self.done = "continue"

    guard = netguard.browser_guard(resolver({"site.test": ["93.184.216.34"]}))
    inside, outside, data = Route("http://10.0.0.1/x"), Route("https://site.test/a.js"), Route("data:image/png;x")
    for r in (inside, outside, data):
        guard(r)
    assert (inside.done, outside.done, data.done) == ("abort", "continue", "continue")
