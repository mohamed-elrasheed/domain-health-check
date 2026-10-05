from datetime import datetime, timezone

import pytest

from domain_health_check import fetcher, runner, scoring
from domain_health_check.config import DomainConfig
from domain_health_check.fetcher import FetchError
from domain_health_check.models import EMAIL, SITE, WEBSITE, CheckResult, Status

NOW = datetime(2026, 10, 1, tzinfo=timezone.utc)


def result(name: str, status: Status, ran: bool = True) -> CheckResult:
    return CheckResult(WEBSITE, name, status, "summary", "explanation", ran=ran)


def test_weighted_formula():
    results = [
        result("SSL certificate", Status.PASS),     # tier 1: 5 of 5
        result("DNSSEC", Status.WARN),              # tier 6: 0.5 of 1
        result("Image alt text", Status.FAIL),      # tier 2: 0 of 4
    ]
    assert scoring.score(results) == round(100 * 5.5 / 10)


def test_checks_that_did_not_run_are_left_out_of_both_sides():
    ran = [result("SSL certificate", Status.PASS)]
    skipped = [result("Structured data matches the page", Status.WARN, ran=False),
               result("Security headers", Status.WARN, ran=False)]  # not in WEIGHTS, and not looked up
    assert scoring.score(ran + skipped) == scoring.score(ran) == 100


def test_nothing_ran_gives_no_score():
    assert scoring.score([result("Site health checks", Status.WARN, ran=False)]) is None
    assert scoring.score([]) is None


def test_unweighted_check_is_an_error_not_a_guess():
    with pytest.raises(KeyError):
        scoring.score([result("Some new check", Status.PASS)])


def test_one_alt_tag_cannot_drown_a_certificate():
    certificate_bad = [result("SSL certificate", Status.FAIL), result("Image alt text", Status.PASS)]
    alt_bad = [result("SSL certificate", Status.PASS), result("Image alt text", Status.FAIL)]
    assert scoring.score(certificate_bad) < scoring.score(alt_bad)


def test_dkim_weighs_the_same_as_spf_and_dmarc():
    names = ["SPF (approved senders)", "DKIM (email signatures)", "DMARC (anti-spoofing policy)"]
    assert {scoring.WEIGHTS[n] for n in names} == {1}


def test_weights_follow_the_ladder():
    from domain_health_check.ladder import LADDER, TIER_WEIGHT
    for tier, names in enumerate(LADDER, start=1):
        assert {scoring.WEIGHTS[n] for n in names} == {TIER_WEIGHT[tier]}
    assert [TIER_WEIGHT[t] for t in range(1, 7)] == sorted(TIER_WEIGHT.values(), reverse=True)  # never rises


def test_email_records_cannot_outweigh_a_missing_main_heading():
    h1 = scoring.WEIGHTS["Main heading"]
    for name in ("DKIM (email signatures)", "DMARC (anti-spoofing policy)", "SPF (approved senders)",
                 "HSTS (always use HTTPS)", "DNSSEC"):
        assert scoring.WEIGHTS[name] < h1


@pytest.mark.parametrize("value, text", [
    (100, "in good shape"), (90, "in good shape"), (89, "a few things worth fixing"), (70, "a few things worth fixing"),
    (69, "several things need attention"), (50, "several things need attention"), (49, "needs work in a few areas"),
    (0, "needs work in a few areas"),
])
def test_reading(value, text):
    assert scoring.reading(value) == text


def test_every_check_a_full_run_produces_is_weighted(fake_dns, monkeypatch, mizan_page):
    from domain_health_check.checks import rdap, tls
    fake_dns[("mizangroupllc.com", "MX")] = ["10 mx.example.net."]
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: mizan_page)
    report = runner.run_checks(DomainConfig("mizangroupllc.com"), NOW)
    assert {r.name for r in report.results if r.ran} <= set(scoring.WEIGHTS)
    assert scoring.score(report.results) is not None


def test_weights_cover_exactly_the_checks_that_exist():
    """A renamed check would otherwise drop out of the score, or leave a stale weight behind."""
    from domain_health_check.checks import rdap
    from domain_health_check.checks.site import (
        content,
        delivery,
        favicon,
        indexing,
        links,
        mixed_content,
        sharing,
        structured_data,
    )
    site = {content.TITLE, content.DESCRIPTION, content.MAIN_HEADING, content.HEADING_ORDER, content.ALT_TEXT,
            delivery.VIEWPORT, delivery.PAGE_WEIGHT, delivery.REDIRECTS, indexing.SEARCH_BLOCKING,
            indexing.CANONICAL, indexing.SITEMAP, sharing.SOCIAL_PREVIEW, structured_data.NAME,
            links.SAME_SITE, links.OTHER_SITES, mixed_content.NAME, favicon.NAME}
    assert {n for n in scoring.WEIGHTS if n in site} == site and len(site) == 17
    security = {"SSL certificate", "TLS version", "HSTS (always use HTTPS)", "Content Security Policy",
                "X-Content-Type-Options", rdap.NAME, "Nameservers", "DNSSEC", "Mail servers (MX)",
                "SPF (approved senders)", "DKIM (email signatures)", "DMARC (anti-spoofing policy)"}
    from domain_health_check.checks import pagespeed
    speed = {pagespeed.FIELD_SPEED, pagespeed.MOBILE_SPEED, pagespeed.ACCESSIBILITY, pagespeed.BEST_PRACTICES}
    from domain_health_check.checks import business_profile as bp
    profile = {bp.PROFILE, bp.COMPLETENESS, bp.WEBSITE_LINK, bp.REVIEWS}
    assert set(scoring.WEIGHTS) == site | security | speed | profile
    assert "SEO" not in scoring.WEIGHTS  # Lighthouse's seo category would double-count the site checks


def test_failed_fetch_does_not_lower_the_score(fake_dns, monkeypatch, mizan_page):
    from domain_health_check.checks import rdap, tls
    fake_dns[("mizangroupllc.com", "MX")] = ["1 smtp.google.com."]  # a domain that uses email
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})

    def offline(domain):
        raise FetchError(f"https://{domain}/", "ReadTimeout")
    monkeypatch.setattr(fetcher, "fetch_page", offline)
    report = runner.run_checks(DomainConfig("mizangroupllc.com"), NOW)
    not_run = [r for r in report.results if not r.ran]
    assert {r.category for r in not_run} == {WEBSITE, SITE}
    # The score is computed over what ran: the timeout counts for nothing either way.
    ran_only = [r for r in report.results if r.ran]
    assert scoring.score(report.results) == scoring.score(ran_only)
    assert EMAIL in {r.category for r in ran_only}


# ---------- rule B: binary versus graded, and maybes left out

def warn(name, measure=None, certain=True):
    return CheckResult(WEBSITE, name, Status.WARN, "s", "e", measure=measure, certain=certain)


@pytest.mark.parametrize("name, expected", [
    ("Main heading", 0.0),                    # tier 2: confirmed absent scores zero
    ("Search engine blocking", 0.0),          # tier 1
    ("Google Business Profile", 0.25),        # tier 3
    ("Mobile viewport", 0.25),                # tier 4
    ("DMARC (anti-spoofing policy)", 0.5),    # tier 5
    ("DNSSEC", 0.5),                          # tier 6
])
def test_binary_warn_credit_by_tier(name, expected):
    assert scoring.credit(warn(name)) == expected


def test_graded_warn_earns_its_measure_with_no_special_case():
    from domain_health_check.checks.site import content
    none_described = content.evaluate_alt_text([("https://example.com/a.jpg", None)] * 31)
    some_described = content.evaluate_alt_text([("https://example.com/a.jpg", "A floor")] * 14
                                               + [("https://example.com/b.jpg", None)] * 26)
    assert scoring.credit(none_described) == 0.0
    assert scoring.credit(some_described) == pytest.approx(14 / 40)


def test_two_heading_skips_is_not_the_same_site_as_no_main_heading():
    from domain_health_check.checks.site import content
    skipped_twice = content.evaluate_heading_order([1, 2, 4, 2, 3, 2, 4] + [2] * 23)  # 2 skips in 30 headings
    no_h1 = content.evaluate_main_heading([])
    assert scoring.credit(skipped_twice) == pytest.approx(28 / 30)
    assert scoring.credit(no_h1) == 0.0


def test_absent_and_placeholder_text_are_binary_but_length_is_graded():
    from domain_health_check.checks.site import content
    assert content.evaluate_description([]).measure is None
    assert scoring.credit(content.evaluate_description([])) == 0.0
    long = content.evaluate_description(["x" * 177])
    assert scoring.credit(long) == pytest.approx(160 / 177)


def test_measures_are_clamped():
    assert scoring.credit(warn("Image alt text", measure=1.7)) == 1.0
    assert scoring.credit(warn("Image alt text", measure=-0.2)) == 0.0


def test_a_maybe_neither_costs_nor_earns_points():
    sure = [result("SSL certificate", Status.PASS), result("Main heading", Status.PASS)]
    assert scoring.score(sure + [warn("DKIM (email signatures)", certain=False)]) == scoring.score(sure) == 100
    assert scoring.score(sure + [warn("Main heading", certain=False)]) == 100
