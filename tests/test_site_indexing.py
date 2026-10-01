from dataclasses import replace

import pytest

from domain_health_check.checks.site import indexing
from domain_health_check.fetcher import FetchedFile, FetchError, RobotsDisallowed
from domain_health_check.models import Status
from site_helpers import edited

CANONICAL = '<link href="https://www.mizangroupllc.com" rel="canonical"/>'


# ---------- Search engine blocking

def test_mizan_is_not_blocked(mizan_page):
    [result] = indexing.check_search_blocking(mizan_page)
    assert result.status is Status.PASS


@pytest.mark.parametrize("tag", [
    '<meta name="robots" content="noindex, nofollow">',
    '<meta name="ROBOTS" content="NOINDEX">',
    '<meta name="googlebot" content="none">',
])
def test_noindex_meta_fails(mizan_page, tag):
    page = edited(mizan_page, "</head>", f"{tag}</head>")
    [result] = indexing.check_search_blocking(page)
    assert result.status is Status.FAIL
    assert "not to list it" in result.summary
    assert any("noindex" in d.lower() or "none" in d for d in result.details)


def test_meta_robots_without_noindex_passes(mizan_page):
    page = edited(mizan_page, "</head>", '<meta name="robots" content="index, follow, max-snippet:-1"></head>')
    assert indexing.check_search_blocking(page)[0].status is Status.PASS


@pytest.mark.parametrize("header, blocked", [
    ("noindex", True),
    ("none", True),
    ("googlebot: noindex", True),
    ("otherbot: noindex", False),
    ("otherbot: noindex, googlebot: nofollow", False),
    ("max-snippet: 50, noindex", True),
    ("unavailable_after: 25 Jun 2030 15:00:00 PST", False),
    ("nofollow", False),
])
def test_x_robots_tag(mizan_page, header, blocked):
    page = replace(mizan_page, headers={**mizan_page.headers, "x-robots-tag": header})
    expected = Status.FAIL if blocked else Status.PASS
    assert indexing.check_search_blocking(page)[0].status is expected


@pytest.mark.parametrize("robots, rule", [
    ("User-agent: *\nDisallow: /\n", "Disallow: /"),
    ("User-agent: *\nDisallow: /*\n", "Disallow: /*"),  # Python's robotparser misses this one
    ("User-agent: Googlebot\nDisallow: /\n\nUser-agent: *\nAllow: /\n", "Disallow: /"),
    ("User-agent: *\nDisallow: /\n\nUser-agent: Googlebot\nAllow: /\n", None),  # the googlebot group wins
    ("User-agent: *\nDisallow: /\nAllow: /$\n", None),  # longer rule wins
    ("User-agent: *\nDisallow: /private/\n", None),
    ("User-agent: *\nDisallow:\n", None),  # an empty Disallow allows everything
    ("User-agent: SomeOtherBot\nDisallow: /\n", None),
    ("User-agent: Googlebot-Image\nDisallow: /\n", None),  # a different Google crawler
    ("User-agent: bingbot\nUser-agent: Googlebot\nDisallow: / # staging\n", "Disallow: /"),
    ("Sitemap: https://www.mizangroupllc.com/sitemap.xml", None),  # Mizan's real file
])
def test_googlebot_block(robots, rule):
    assert indexing.googlebot_block(robots) == rule


def test_robots_disallow_fails_on_the_real_page(mizan_page):
    robots = replace(mizan_page.robots, text="User-agent: *\nDisallow: /\n" + mizan_page.robots.text)
    [result] = indexing.check_search_blocking(replace(mizan_page, robots=robots))
    assert result.status is Status.FAIL
    assert "tells Google not to visit" in result.summary
    assert any("Disallow: /" in d for d in result.details)


def test_robots_404_means_no_rules(mizan_page):
    page = replace(mizan_page, robots=FetchedFile("https://www.mizangroupllc.com/robots.txt", 404, "Disallow: /"))
    assert indexing.check_search_blocking(page)[0].status is Status.PASS


def test_blocked_by_robots_is_still_reported_without_the_page():
    robots = FetchedFile("https://example.com/robots.txt", 200, "User-agent: *\nDisallow: /\n")
    [result] = indexing.check_search_blocking(RobotsDisallowed("https://example.com/", "Disallow: /", robots))
    assert result.status is Status.FAIL and result.ran


def test_page_unavailable_and_robots_fine_leaves_it_to_the_unavailable_row():
    robots = FetchedFile("https://example.com/robots.txt", 200, "User-agent: domain-health-check\nDisallow: /\n")
    assert indexing.check_search_blocking(RobotsDisallowed("https://example.com/", "us only", robots)) == []
    assert indexing.check_search_blocking(FetchError("https://example.com/", "ConnectError")) == []


# ---------- Canonical tag

def test_mizan_canonical_without_trailing_slash_passes(mizan_page):
    [result] = indexing.check_canonical(mizan_page)
    assert result.status is Status.PASS
    assert "Canonical tag: https://www.mizangroupllc.com" in result.details


@pytest.mark.parametrize("href", [
    "http://www.mizangroupllc.com/",       # scheme
    "https://mizangroupllc.com/",          # www
    "https://www.mizangroupllc.com/?ref=x",  # query string
    "HTTPS://WWW.MIZANGROUPLLC.COM",       # case
])
def test_normalization_differences_pass(mizan_page, href):
    page = edited(mizan_page, CANONICAL, f'<link href="{href}" rel="canonical"/>')
    assert indexing.check_canonical(page)[0].status is Status.PASS


def test_different_path_passes_with_a_note(mizan_page):
    page = edited(mizan_page, CANONICAL, '<link href="https://www.mizangroupllc.com/services" rel="canonical"/>')
    [result] = indexing.check_canonical(page)
    assert result.status is Status.PASS
    assert any("different page" in d for d in result.details)


@pytest.mark.parametrize("replacement, phrase", [
    ("", "does not tell search engines"),
    ('<link href="/" rel="canonical"/>', "partial address"),
    ('<link href="https://staging.webflow.io/" rel="canonical"/>', "different website"),
])
def test_canonical_warnings(mizan_page, replacement, phrase):
    [result] = indexing.check_canonical(edited(mizan_page, CANONICAL, replacement))
    assert result.status is Status.WARN
    assert phrase in result.summary


def test_canonical_never_fails(mizan_page):
    for replacement in ("", '<link href="x" rel="canonical"/>', '<link href="https://other.test/" rel="canonical"/>'):
        assert indexing.check_canonical(edited(mizan_page, CANONICAL, replacement))[0].status is not Status.FAIL


# ---------- Sitemap and robots

def test_mizan_sitemap_and_robots_pass(mizan_page):
    [result] = indexing.check_sitemap_and_robots(mizan_page)
    assert result.status is Status.PASS
    assert "27 pages" in result.summary


def test_sitemap_missing(mizan_page):
    page = replace(mizan_page, sitemap=replace(mizan_page.sitemap, status=404, text="Not found"))
    [result] = indexing.check_sitemap_and_robots(page)
    assert result.status is Status.WARN and "could not find a sitemap" in result.summary


def test_sitemap_invalid_xml(mizan_page):
    broken = mizan_page.sitemap.text.replace("</urlset>", "")
    [result] = indexing.check_sitemap_and_robots(replace(mizan_page, sitemap=replace(mizan_page.sitemap, text=broken)))
    assert result.status is Status.WARN and "format" in result.summary
    assert any("not valid XML" in d for d in result.details)


def test_sitemap_not_referenced_from_robots(mizan_page):
    page = replace(mizan_page, robots=replace(mizan_page.robots, text="User-agent: *\nAllow: /\n"))
    [result] = indexing.check_sitemap_and_robots(page)
    assert result.status is Status.WARN and "does not mention your sitemap" in result.summary
    assert "Sitemap: https://www.mizangroupllc.com/sitemap.xml" in result.fix


def test_robots_missing(mizan_page):
    page = replace(mizan_page, robots=replace(mizan_page.robots, status=404, text=""))
    [result] = indexing.check_sitemap_and_robots(page)
    assert result.status is Status.WARN and "no robots.txt" in result.summary


def test_sitemap_index_counts_sitemaps_without_opening_them(mizan_page):
    index = ('<?xml version="1.0" encoding="UTF-8"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
             "<sitemap><loc>https://www.mizangroupllc.com/a.xml</loc></sitemap>"
             "<sitemap><loc>https://www.mizangroupllc.com/b.xml</loc></sitemap></sitemapindex>")
    [result] = indexing.check_sitemap_and_robots(replace(mizan_page, sitemap=replace(mizan_page.sitemap, text=index)))
    assert result.status is Status.PASS and "lists 2 sitemaps" in result.summary
    assert any("did not open" in d for d in result.details)


def test_truncated_sitemap_is_judged_by_how_it_starts(mizan_page):
    cut = mizan_page.sitemap.text[:1500]
    page = replace(mizan_page, sitemap=replace(mizan_page.sitemap, text=cut, truncated=True))
    [result] = indexing.check_sitemap_and_robots(page)
    assert result.status is Status.PASS and "at least" in result.summary


def test_sitemap_not_read_did_not_run(mizan_page):
    [result] = indexing.check_sitemap_and_robots(replace(mizan_page, sitemap=None))
    assert not result.ran


def test_image_locs_are_not_pages(mizan_page):
    text = mizan_page.sitemap.text.replace(
        "<urlset ", '<urlset xmlns:image="http://www.google.com/schemas/sitemap-image/1.1" ', 1).replace(
        "</url>", "<image:image><image:loc>https://cdn.test/a.png</image:loc></image:image></url>", 1)
    pages = indexing.sitemap_pages(replace(mizan_page.sitemap, text=text))
    assert "https://cdn.test/a.png" not in pages and len(pages) == 27
