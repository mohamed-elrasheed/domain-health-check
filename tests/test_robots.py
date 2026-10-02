"""The shared robots.txt reader. Our own access goes through it, so these cases are compliance, not style."""

import httpx
import pytest

from domain_health_check import fetcher, robots
from domain_health_check.fetcher import RobotsDisallowed

US = fetcher.ROBOTS_TOKEN


@pytest.mark.parametrize("text, url, rule", [
    ("User-agent: *\nDisallow: /*\n", "/", "Disallow: /*"),          # robotparser before 3.14 allowed this
    ("User-agent: *\nDisallow: /*$\n", "/", "Disallow: /*$"),
    ("User-agent: *\nDisallow: /$\n", "/", "Disallow: /$"),
    ("User-agent: *\nDisallow: /$\n", "/about", None),
    ("User-agent: *\nDisallow: /\nAllow: /$\n", "/", None),           # longer rule wins
    ("User-agent: *\nAllow: /\nDisallow: /\n", "/", None),            # tie goes to Allow, whatever the order
    ("User-agent: *\nDisallow: /*.xml$\n", "/sitemap.xml", "Disallow: /*.xml$"),
    ("User-agent: *\nDisallow: /*.xml$\n", "/", None),
    ("User-agent: *\nDisallow: /*?\n", "/?utm=1", "Disallow: /*?"),    # the query string counts
    ("User-agent: *\nDisallow: /\n", "/robots.txt", None),            # always allowed
    ("User-agent: *\nDisallow:\n", "/", None),
    ("user-AGENT: Domain-Health-Check/0.1\nDISALLOW: /\n", "/", "Disallow: /"),  # case and version ignored
    ("User-agent: *\nAllow: /\n\nUser-agent: domain-health-check\nDisallow: /\n", "/", "Disallow: /"),
    ("User-agent: domain-health-check\nDisallow: /a\n\nUser-agent: domain-health-check\nDisallow: /\n", "/",
     "Disallow: /"),                                                  # repeated groups merge
    ("Disallow: /\n", "/", None),                                     # a rule before any user-agent is ignored
])
def test_blocking_rule_for_us(text, url, rule):
    assert robots.blocking_rule(text, US, url) == rule


def test_full_urls_are_reduced_to_path_and_query():
    assert robots.blocking_rule("User-agent: *\nDisallow: /*?\n", US, "https://example.com/?a=1") == "Disallow: /*?"


def test_fetcher_honors_a_wildcard_block():
    seen = []

    def handle(request):
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /*\n")
        return httpx.Response(200, html="<html></html>")

    with pytest.raises(RobotsDisallowed):
        fetcher.fetch_page("example.com", transport=httpx.MockTransport(handle))
    assert seen == ["https://example.com/robots.txt"]


def test_fetcher_skips_a_sitemap_blocked_by_wildcard():
    seen = []

    def handle(request):
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /*.xml$\n")
        return httpx.Response(200, html="<html></html>")

    page = fetcher.fetch_page("example.com", transport=httpx.MockTransport(handle))
    assert page.sitemap is None and seen == ["/robots.txt", "/"]
