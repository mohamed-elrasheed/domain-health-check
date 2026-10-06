"""The differentiator check. The failure cases recreate what happened on Mizan's own /services: the visible
page is correct, and the JSON-LD still carries a retired URL and a superseded price."""

from dataclasses import replace
from decimal import Decimal

import pytest
from site_helpers import ld_json, with_body

from domain_health_check.checks.site import structured_data
from domain_health_check.models import Status

OFFER = ld_json('{"@context": "https://schema.org", "@type": "Service", "name": "Monthly support", '
                '"url": "https://www.mizangroupllc.com/tech-services/monthly-support", '
                '"offers": {"@type": "Offer", "price": "%s", "priceCurrency": "USD"}}')


def test_mizan_structured_data_matches(mizan_page):
    [result] = structured_data.check_structured_data(mizan_page)
    assert result.status is Status.PASS and result.ran
    assert result.summary == "The 4 links in your home page structured data match the page."
    assert "URL https://www.mizangroupllc.com/tech at block 1: department[0].url: found (page link)" in result.details


def test_ids_images_and_other_sites_are_not_compared(mizan_page):
    [result] = structured_data.check_structured_data(mizan_page)
    joined = " ".join(result.details)
    assert "#business" not in joined and "#mohamed" not in joined  # @id
    assert "linkedin.com" not in joined and "cdn.prod.website-files.com" not in joined


def test_price_shown_on_the_page_matches(mizan_page):
    page = with_body(mizan_page, OFFER % "1500.00" + "<p>Monthly support is $1,500 per month.</p>")
    [result] = structured_data.check_structured_data(page)
    assert result.status is Status.PASS
    assert any(d.startswith("Price 1500.00") and d.endswith("found (page text)") for d in result.details)


def test_superseded_price_warns(mizan_page):
    page = with_body(mizan_page, OFFER % "1200" + "<p>Monthly support is $1,500 per month.</p>")
    [result] = structured_data.check_structured_data(page)
    assert result.status is Status.WARN
    assert "1 price" in result.summary
    assert any("Price 1200" in d and "not found in the page text" in d for d in result.details)


def test_retired_url_warns_and_says_what_it_checked(mizan_page):
    retired = ld_json('{"@type": "Service", "url": "https://www.mizangroupllc.com/old-services"}')
    [result] = structured_data.check_structured_data(with_body(mizan_page, retired))
    assert result.status is Status.WARN and "1 link" in result.summary
    assert ("URL https://www.mizangroupllc.com/old-services at block 3: url: not linked from the page or in the "
            "sitemap") in result.details
    assert any("before any scripts run" in d for d in result.details)


def test_url_in_the_sitemap_but_not_linked_matches_by_sitemap(mizan_page):
    # /glossary is in the sitemap. Take away the page's link to it, and the sitemap is the evidence.
    assert 'href="/glossary"' in mizan_page.html
    page = replace(mizan_page, html=mizan_page.html.replace('href="/glossary"', 'href="/somewhere-else"'))
    page = with_body(page, ld_json('{"@type": "WebPage", "url": "https://www.mizangroupllc.com/glossary"}'))
    [result] = structured_data.check_structured_data(page)
    assert result.status is Status.PASS
    assert "URL https://www.mizangroupllc.com/glossary at block 3: url: found (sitemap)" in result.details


def test_invalid_block_warns(mizan_page):
    [result] = structured_data.check_structured_data(with_body(mizan_page, ld_json('{"@type": "Offer",}')))
    assert result.status is Status.WARN
    assert any("Block 3 is not valid JSON" in d for d in result.details)


def test_no_structured_data_did_not_run(mizan_page):
    page = replace(mizan_page, html=mizan_page.html.replace("application/ld+json", "text/plain"))
    [result] = structured_data.check_structured_data(page)
    assert not result.ran
    assert result.status is not Status.PASS


def test_nothing_comparable_did_not_run(mizan_page):
    faq_only = '<html><body>' + "<p>word</p>" * 60 + ld_json('{"@type": "FAQPage", "name": "Questions"}') + "</body></html>"
    [result] = structured_data.check_structured_data(replace(mizan_page, html=faq_only))
    assert not result.ran


def test_page_built_by_scripts_did_not_run(mizan_page):
    shell = '<html><body><div id="app"></div>' + OFFER % "99" + "</body></html>"
    [result] = structured_data.check_structured_data(replace(mizan_page, html=shell))
    assert not result.ran and "built by scripts" in result.summary


@pytest.mark.parametrize("text, number", [
    ("1500", Decimal("1500")), ("$1,500.00", Decimal("1500")), ("USD 49.99/mo", Decimal("49.99")), ("Free", None),
])
def test_to_number(text, number):
    assert structured_data.to_number(text) == number


def test_graph_and_low_high_prices_are_found():
    values, invalid = structured_data.extract_values(
        ['{"@graph": [{"@type": "AggregateOffer", "lowPrice": 10, "highPrice": "20"}]}'], "https://example.com/")
    assert [(v.kind, v.raw) for v in values] == [("price", "10"), ("price", "20")] and not invalid


def test_a_url_repeated_in_several_places_counts_once(mizan_page):
    # Yoast repeats the home URL across @graph entries; the real page read "All 3 links" for one address.
    repeated = ld_json('{"@graph": [{"url": "https://www.mizangroupllc.com/tech"}, {"url": "https://www.mizangroupllc.com/tech"}]}')
    [result] = structured_data.check_structured_data(with_body(mizan_page, repeated))
    assert result.summary.startswith("The 4 links")


def test_only_a_rendered_page_is_called_visible(mizan_page):
    from dataclasses import replace
    [delivered] = structured_data.check_structured_data(mizan_page)
    assert delivered.summary.endswith("match the page.")
    assert "including any text the page hides" in delivered.details[0]
    [rendered] = structured_data.check_structured_data(replace(mizan_page, rendered_html=mizan_page.html))
    assert rendered.summary.endswith("match the visible page.")
    assert "leaving out anything a visitor could not see" in rendered.details[0]


def test_our_digital_page_structured_data_matches_the_page():
    """Our own /digital page, saved 2026-10-06 with the tune-up and email lines: every price in its JSON-LD,
    $250 and $150 included, is in the page text, and every URL is linked from the page."""
    from pathlib import Path

    from domain_health_check.fetcher import FetchedFile, PageContext
    ours = Path(__file__).parent / "fixtures" / "mizangroupllc.com"
    html = (ours / "digital.html").read_text(encoding="utf-8")
    url = "https://www.mizangroupllc.com/digital"
    page = PageContext(url, url, [], 200, {}, html, len(html.encode()), 100, 50, None,
                       FetchedFile("https://www.mizangroupllc.com/sitemap.xml", 200,
                                   (ours / "sitemap.xml").read_text(encoding="utf-8")))
    [result] = structured_data.check_structured_data(page)
    assert result.status is Status.PASS, result.details
    assert result.summary == "The 12 prices and 5 links in your home page structured data match the page."
    assert {"Price 250 at block 1: @graph[2].itemListElement[3].price: found (page text)",
            "Price 150 at block 1: @graph[2].itemListElement[4].price: found (page text)"} <= set(result.details)
