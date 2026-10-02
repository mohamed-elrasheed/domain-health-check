from dataclasses import replace

from domain_health_check.checks import site
from domain_health_check.checks.site import delivery, sharing
from domain_health_check.fetcher import FetchError, RobotsDisallowed
from domain_health_check.models import Status
from site_helpers import edited

VIEWPORT = '<meta content="width=device-width, initial-scale=1" name="viewport"/>'
OG_IMAGE = 'property="og:image"'


# ---------- Mobile viewport

def test_mizan_viewport_passes(mizan_page):
    assert delivery.check_viewport(mizan_page)[0].status is Status.PASS


def test_missing_viewport_fails(mizan_page):
    [result] = delivery.check_viewport(edited(mizan_page, VIEWPORT, ""))
    assert result.status is Status.WARN


def test_fixed_width_viewport_warns(mizan_page):
    [result] = delivery.check_viewport(edited(mizan_page, VIEWPORT, '<meta content="width=1024" name="viewport"/>'))
    assert result.status is Status.WARN


# ---------- Page weight

def test_mizan_page_weight_uses_measured_values(mizan_page):
    [result] = delivery.check_page_weight(mizan_page)
    assert result.status is Status.PASS
    assert "97 KB" in result.summary and "0.15 seconds" in result.summary
    assert "Time to first byte: 151 ms, including 1 redirect(s)" in result.details
    assert "Time to last byte: 203 ms" in result.details


def test_heavy_page_warns(mizan_page):
    [result] = delivery.check_page_weight(replace(mizan_page, byte_size=150_000))
    assert result.status is Status.WARN and "150 KB" in result.summary


def test_slow_first_byte_warns_even_when_total_is_what_is_slow(mizan_page):
    assert delivery.check_page_weight(replace(mizan_page, ttfb_ms=4_999, elapsed_ms=9_000))[0].status is Status.PASS
    [result] = delivery.check_page_weight(replace(mizan_page, ttfb_ms=6_200, elapsed_ms=6_400))
    assert result.status is Status.WARN and "6.2 seconds" in result.summary


def test_truncated_page_says_more_than(mizan_page):
    [result] = delivery.check_page_weight(replace(mizan_page, byte_size=5_000_001))
    assert result.status is Status.WARN and "more than 5,000 KB" in result.summary


# ---------- Redirect chain

def test_mizan_single_redirect_passes(mizan_page):
    [result] = delivery.check_redirects(mizan_page)
    assert result.status is Status.PASS
    assert "https://mizangroupllc.com/ answered 301" in result.details


def test_two_hops_pass_three_warn(mizan_page):
    two = [("https://mizangroupllc.com/", 301), ("http://www.mizangroupllc.com/", 301)]
    assert delivery.check_redirects(replace(mizan_page, redirect_chain=two))[0].status is Status.PASS
    three = two + [("https://www.mizangroupllc.com/home", 302)]
    [result] = delivery.check_redirects(replace(mizan_page, redirect_chain=three))
    assert result.status is Status.WARN and "3 redirects" in result.summary


# ---------- Social preview

def test_mizan_social_preview_passes(mizan_page):
    assert sharing.check_social_preview(mizan_page)[0].status is Status.PASS


def test_missing_image_warns(mizan_page):
    [result] = sharing.check_social_preview(edited(mizan_page, OG_IMAGE, 'property="og:image:unused"'))
    assert result.status is Status.WARN and "missing its image" in result.summary


def test_name_attribute_is_accepted(mizan_page):
    page = edited(mizan_page, OG_IMAGE, 'name="og:image"')
    assert sharing.check_social_preview(page)[0].status is Status.PASS


# ---------- When the page could not be loaded

def test_loaded_page_adds_no_row(mizan_page):
    assert site.check_page_loaded(mizan_page) == []


def test_unloaded_page_is_one_row_that_did_not_run():
    [result] = site.check_page_loaded(FetchError("https://example.com/", "ConnectError: refused"))
    assert result.status is Status.WARN and not result.ran
    assert "could not load https://example.com/" in result.summary


def test_robots_block_gets_its_own_wording():
    [result] = site.check_page_loaded(RobotsDisallowed("https://example.com/", "Disallow: /"))
    assert "asks automated tools" in result.summary and "web host" not in result.fix


# ---------- When the page is built by scripts

def app_shell(page):
    """Mizan's real head, with the body replaced by what a script-built site delivers."""
    head = page.html.split("<body", 1)[0]
    return replace(page, html=head + '<body><div id="root"></div><script src="/app.js"></script></body></html>')


def test_mizan_is_not_treated_as_script_built(mizan_page):
    assert not site.built_by_scripts(mizan_page)
    assert site.check_page_rendered(mizan_page) == []


def test_app_shell_gets_one_not_checked_row(mizan_page):
    shell = app_shell(mizan_page)
    assert site.built_by_scripts(shell)
    [result] = site.check_page_rendered(shell)
    assert not result.ran and "usually means scripts build it" in result.summary
    assert "Visible words in the delivered HTML: 0 (we need 50 or more)" in result.details


def test_short_page_with_real_headings_is_still_checked(mizan_page):
    head = mizan_page.html.split("<body", 1)[0]
    short = replace(mizan_page, html=head + "<body><h1>Coming soon</h1><h2>Call us</h2></body></html>")
    assert not site.built_by_scripts(short)


def test_runner_skips_content_checks_on_an_app_shell(fake_dns, monkeypatch, mizan_page):
    from datetime import datetime, timezone

    from domain_health_check import fetcher, runner
    from domain_health_check.checks import rdap, tls
    from domain_health_check.config import DomainConfig
    from domain_health_check.models import SITE
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: app_shell(mizan_page))
    report = runner.run_checks(DomainConfig("mizangroupllc.com"), datetime(2026, 10, 1, tzinfo=timezone.utc))
    site_rows = {r.name: r.ran for r in report.results if r.category == SITE}
    for skipped in ("Page title", "Meta description", "Main heading", "Heading order", "Image alt text"):
        assert skipped not in site_rows
    assert site_rows["Page content checks"] is False
    assert site_rows["Structured data matches the page"] is False  # its own guard, same reason
    for still_checked in ("Search engine blocking", "Canonical tag", "Mobile viewport", "Social preview",
                          "Sitemap and robots", "Page weight", "Redirect chain"):
        assert site_rows[still_checked] is True
