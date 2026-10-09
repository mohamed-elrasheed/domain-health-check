"""Page 1 for the owner, the anonymous nearby comparison, the two reach-you checks, and the collapsed security row.

Every page here is synthetic, and every Places answer is invented: no real business is named anywhere.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from site_helpers import PNG

from domain_health_check import external, fetcher, layout, pdf, requestlog, runner, scoring
from domain_health_check.checks.site import reach
from domain_health_check.config import DomainConfig
from domain_health_check.external import ExternalContext
from domain_health_check.fetcher import FetchedFile, PageContext
from domain_health_check.models import SITE, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.report import record, render_markdown, write_report

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "detectors"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
URL = "https://www.example.com/"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def finding(name: str, category: str = SITE) -> CheckResult:
    return CheckResult(category, name, Status.WARN, f"{name} finding.", "Why.", f"Fix for {name}.", [])


NEARBY = {"category": "Flooring store", "count": 3, "reviews": 141.33, "rating": 4.63, "own_reviews": 87,
          "own_rating": 4.8}


def owner_report(**extra) -> DomainReport:
    results = [CheckResult(WEBSITE, "SSL certificate", Status.PASS, "Valid.", "Why.", "", []),
               finding("Main heading"), finding("Meta description"), finding("Image alt text"),
               finding("Canonical tag")]
    return DomainReport("example.com", NOW, results, screenshot=PNG, nearby=NEARBY, **extra)


# ---------- the nearby comparison: averages only, never a name

def test_nearby_averages_skip_the_business_itself_and_need_three():
    listings = [{"id": "own", "rating": 5.0, "userRatingCount": 999}, {"id": "a", "rating": 4.5, "userRatingCount": 100},
                {"id": "b", "rating": 4.7, "userRatingCount": 200}, {"id": "c", "rating": 4.9, "userRatingCount": 60}]
    assert external.nearby_averages(listings, "own") == {"count": 3, "reviews": 120.0, "rating": pytest.approx(4.7)}
    assert external.nearby_averages(listings[:3], "own") is None  # only two others


def test_the_nearby_line_names_no_one():
    line = layout.nearby_line(owner_report())
    assert line == ("The three top-ranked flooring stores near you average 141 reviews at 4.6 stars. You have 87 at "
                    "4.8.")
    assert layout.nearby_line(DomainReport("example.com", NOW, [], nearby=None)) == ""
    assert layout.nearby_line(DomainReport("example.com", NOW, [], nearby={**NEARBY, "category": ""})) == ""


@pytest.mark.parametrize("category, plural", [("Flooring store", "flooring stores"), ("Pharmacy", "pharmacies"),
                                              ("Glass business", "glass businesses"), ("Auto body shop", "auto body shops")])
def test_categories_read_as_plurals(category, plural):
    assert layout._plural(category.lower()) == plural


def test_one_nearby_search_around_the_listing_logged_like_every_places_call():
    seen = []
    own = {"id": "own", "displayName": {"text": "Example Floors"}, "websiteUri": "https://www.example.com/",
           "userRatingCount": 87, "rating": 4.8, "primaryType": "barber_shop",
           "primaryTypeDisplayName": {"text": "Barber shop"}, "location": {"latitude": 30.5, "longitude": -97.8}}

    def places(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path.endswith(":searchText"):
            return httpx.Response(200, json={"places": [{"id": "own", "displayName": {"text": "Example Floors"}}]})
        if request.url.path.endswith(":searchNearby"):
            return httpx.Response(200, json={"places": [
                {"id": "own", "rating": 4.8, "userRatingCount": 87}, {"id": "x", "rating": 4.0, "userRatingCount": 30},
                {"id": "y", "rating": 5.0, "userRatingCount": 90}, {"id": "z", "rating": 4.5, "userRatingCount": 60}]})
        return httpx.Response(200, json=own)

    context = ExternalContext()
    with requestlog.recording() as log, httpx.Client(transport=httpx.MockTransport(places),
                                                     event_hooks=requestlog.httpx_hooks("places")) as client:
        external._find_place(client, context, "example.com", external.Business("Example Floors", "Springfield"),
                             "test-key")
    nearby = next(r for r in seen if r.url.path.endswith(":searchNearby"))
    body = json.loads(nearby.content)
    assert body["includedPrimaryTypes"] == ["barber_shop"] and body["rankPreference"] == "POPULARITY"
    assert body["locationRestriction"]["circle"]["radius"] == 16_093 and body["maxResultCount"] == 4
    assert nearby.headers["X-Goog-FieldMask"] == "places.id,places.rating,places.userRatingCount"  # no names
    assert context.nearby == {"category": "Barber shop", "count": 3, "reviews": 60.0, "rating": pytest.approx(4.5)}
    assert [e.source for e in log] == ["places"] * 3


# ---------- page 1

def test_page_one_in_the_markdown():
    md = render_markdown(owner_report())
    top, rest = md.split(f"# {layout.FOR_THE_DEVELOPER}")
    assert top.index(f"![{layout.SCREENSHOT_CAPTION}]({layout.SCREENSHOT_NAME})") < top.index("Score: ")
    assert top.index("Score: ") < top.index("## Worth doing first") < top.index(layout.nearby_line(owner_report()))
    assert top.index(layout.nearby_line(owner_report())) < top.index("**Reach us:** 571.354.8352 or mo@mizangroupllc.com")
    assert "- **Main heading:** Main heading finding." in top
    assert "## Fix it yourself" in rest and "## Worth doing first" not in rest


def test_page_one_in_the_pdf_fits_on_one_page_and_the_rest_is_for_the_developer():
    try:
        pdf._weasyprint()
    except OSError as exc:
        pytest.skip(f"WeasyPrint cannot load its native libraries: {exc}")
    pypdf = pytest.importorskip("pypdf")
    report = owner_report()
    html = pdf.render_html(report)
    assert 'class="shot" src="data:image/png;base64,' in html
    # The text extractor splits a kerned "Y ou" in two; the page itself prints "You".
    pages = [" ".join(p.extract_text().split()).replace("Y ou", "You")
             for p in pypdf.PdfReader(io.BytesIO(pdf.render_pdf(report))).pages]
    first, second = pages[0], pages[1]
    assert "Worth doing first" in first and layout.nearby_line(report) in first and "571.354.8352" in first
    assert layout.SCREENSHOT_CAPTION in first and layout.FOR_THE_DEVELOPER not in first
    assert second.startswith(layout.FOR_THE_DEVELOPER)


def test_page_one_without_a_screenshot_or_findings_still_reads():
    report = DomainReport("example.com", NOW, [CheckResult(WEBSITE, "SSL certificate", Status.PASS, "Valid.", "Why.")])
    md = render_markdown(report)
    assert "![" not in md and layout.NOTHING_FIRST in md and "near you average" not in md


def test_the_screenshot_is_written_beside_the_report_and_named_in_the_record(tmp_path):
    report = owner_report()
    path = write_report(report, tmp_path)
    assert (path.parent / layout.SCREENSHOT_NAME).read_bytes() == PNG
    assert record(report)["screenshot"] == layout.SCREENSHOT_NAME and record(report)["nearby"] == NEARBY


def test_the_browser_takes_the_phone_screenshot(local_browser):
    def answer(route):
        route.fulfill(status=200, content_type="text/html", body="<html><body><h1>Hello</h1></body></html>")
    rendered = fetcher.browser_render(URL, routes=answer)
    assert rendered.screenshot.startswith(b"\x89PNG")


# ---------- tap to call

def page(html: str, **extra) -> PageContext:
    return PageContext(URL, URL, [], 200, {}, html, len(html), 100, 50,
                       FetchedFile(f"{URL}robots.txt", 200, "User-agent: *\nAllow: /\n"), None, **extra)


def test_tap_to_call_passes_when_the_number_is_a_tel_link():
    [result] = reach.check_tap_to_call(page(fixture("contact-home-form.html")))
    assert result.status is Status.PASS
    assert result.summary == "Your phone number, (555) 010-0100, starts a call when tapped on a phone."


def test_tap_to_call_warns_when_the_number_is_plain_text():
    [result] = reach.check_tap_to_call(page(fixture("contact-empty.html")))
    assert result.status is Status.WARN
    assert result.summary == "Your home page shows (555) 010-0100, but tapping it on a phone does not start a call."
    assert result.fix.startswith("Wherever you edit your site, make the phone number")


def test_tap_to_call_is_not_checked_without_a_number():
    [result] = reach.check_tap_to_call(page(fixture("contact-link.html")))
    assert not result.ran


# ---------- the contact form

def test_a_contact_form_that_sends_somewhere_passes_and_a_search_box_is_not_one():
    forms = reach.contact_forms(fixture("contact-home-form.html"))
    assert len(forms) == 1
    [result] = reach.check_contact_form(page(fixture("contact-home-form.html")))
    assert result.status is Status.PASS
    assert result.summary == ("Your contact form is set up to send to an address. We did not submit it, so we "
                              "cannot confirm messages arrive. Send yourself a test message to be sure.")
    assert "Form sends to: https://www.example.com/thanks/" in result.details


def test_a_contact_form_that_sends_nowhere_warns():
    [result] = reach.check_contact_form(page(fixture("contact-empty.html")))
    assert result.status is Status.WARN
    assert result.summary == ("The contact form on your home page does not say where to send what people type, so "
                              "messages may go nowhere.")


def test_on_a_recognized_platform_an_empty_action_is_not_checked_rather_than_guessed():
    [result] = reach.check_contact_form(page(fixture("contact-empty.html"), editor="WordPress"))
    assert not result.ran and "sent by your WordPress site's own script" in result.summary


def test_a_newsletter_sign_up_is_not_a_contact_form():
    assert reach.contact_forms(fixture("contact-link.html")) == []
    assert reach.contact_link(fixture("contact-link.html"), URL) == f"{URL}contact-us/"


def test_the_runner_loads_the_one_contact_page_logs_it_and_never_submits(monkeypatch):
    seen = []

    def site(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, str(request.url)))
        if request.url.path == "/contact-us/":
            return httpx.Response(200, headers={"content-type": "text/html"}, text=fixture("contact-page.html"))
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<html></html>")
    home = page(fixture("contact-link.html"))
    monkeypatch.setattr(runner, "_domain_exists", lambda name: True)
    monkeypatch.setattr(runner, "_fetch_page", lambda name: home)
    monkeypatch.setattr(runner, "_fetch_external", lambda domain, page: ExternalContext())
    monkeypatch.setattr(fetcher, "CONTACT_TRANSPORT", httpx.MockTransport(site))
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    form = next(r for r in report.results if r.name == "Contact form")
    assert form.status is Status.PASS and "Found on: your contact page" in form.details
    contact_requests = [e for e in report.requests if e.source == "contact"]
    assert [(e.method, e.target) for e in contact_requests] == [("GET", f"{URL}contact-us/")]
    assert not [m for m, _ in seen if m != "GET"]  # nothing is ever submitted


def test_robots_txt_can_keep_us_off_the_contact_page():
    home = page(fixture("contact-link.html"))
    home.robots = FetchedFile(f"{URL}robots.txt", 200, "User-agent: *\nDisallow: /contact-us/\n")
    assert fetcher.fetch_contact_page(home, f"{URL}contact-us/") is None


# ---------- the security settings, collapsed on the owner's pages only

HEADERS = ("HSTS (always use HTTPS)", "Content Security Policy", "X-Content-Type-Options")


def test_the_three_security_settings_are_one_row_on_the_price_page_and_separate_elsewhere():
    results = [finding(n, WEBSITE) for n in HEADERS] + [finding("Canonical tag")]
    report = DomainReport("example.com", NOW, results)
    md = render_markdown(report)
    prices = md[md.index("## " + layout.PRICES_HEADING):]
    assert ("| Three security settings your developer can switch on | Ask your web developer or host to switch on "
            "HSTS, a Content Security Policy and the nosniff protection. |") in prices
    assert not any(f"| {name} |" in prices for name in HEADERS)
    developer = md[md.index("## Needs a developer"):md.index("## Everything we checked")]
    assert all(f"### ⚠️ {name}" in developer for name in HEADERS)
    assert {r["name"] for r in record(report)["results"]} >= set(HEADERS)
    assert scoring.score(report.results) == scoring.score(results)


def test_two_security_settings_say_two():
    rows = layout.price_rows(__import__("domain_health_check").pricelist.load().rungs["tuneup"],
                             [finding(HEADERS[1], WEBSITE), finding(HEADERS[2], WEBSITE)])
    assert rows == [("Two security settings your developer can switch on",
                     ["Ask your web developer or host to switch on a Content Security Policy and the nosniff "
                      "protection."])]



@pytest.mark.parametrize("kind", ["building_materials_store", "store", "service", "establishment"])
def test_a_broad_category_gets_no_comparison_and_no_nearby_search(kind):
    seen = []

    def places(request):
        seen.append(request)
        return httpx.Response(200, json={"places": []})
    context = ExternalContext(place={"id": "own", "primaryType": kind, "location": {"latitude": 1, "longitude": 2}})
    with httpx.Client(transport=httpx.MockTransport(places)) as client:
        external._find_nearby(client, context, "test-key")
    assert seen == [] and context.nearby is None and "not a specific trade" in context.errors["nearby"]


def test_the_trade_allowlist_holds_only_documented_google_types():
    trades = external.nearby_trades()
    assert {"barber_shop", "car_repair", "restaurant", "plumber"} <= trades
    assert not {"store", "service", "establishment", "building_materials_store", "home_improvement_store"} & trades
