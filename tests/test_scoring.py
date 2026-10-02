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
        result("SSL certificate", Status.PASS),     # 3 of 3
        result("DNSSEC", Status.WARN),              # 1 of 2
        result("Image alt text", Status.FAIL),      # 0 of 1
    ]
    assert scoring.score(results) == round(100 * 4 / 6)


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
    assert {scoring.WEIGHTS[n] for n in names} == {3}


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
    from domain_health_check.checks.site import content, delivery, indexing, sharing, structured_data
    site = {content.TITLE, content.DESCRIPTION, content.MAIN_HEADING, content.HEADING_ORDER, content.ALT_TEXT,
            delivery.VIEWPORT, delivery.PAGE_WEIGHT, delivery.REDIRECTS, indexing.SEARCH_BLOCKING,
            indexing.CANONICAL, indexing.SITEMAP, sharing.SOCIAL_PREVIEW, structured_data.NAME}
    assert {n for n in scoring.WEIGHTS if n in site} == site and len(site) == 13
    security = {"SSL certificate", "TLS version", "HSTS (always use HTTPS)", "Content Security Policy",
                "X-Content-Type-Options", rdap.NAME, "Nameservers", "DNSSEC", "Mail servers (MX)",
                "SPF (approved senders)", "DKIM (email signatures)", "DMARC (anti-spoofing policy)"}
    from domain_health_check.checks import pagespeed
    speed = {pagespeed.FIELD_SPEED, pagespeed.MOBILE_SPEED, pagespeed.ACCESSIBILITY, pagespeed.BEST_PRACTICES}
    assert set(scoring.WEIGHTS) == site | security | speed
    assert "SEO" not in scoring.WEIGHTS  # Lighthouse's seo category would double-count the site checks


def test_failed_fetch_does_not_lower_the_score(fake_dns, monkeypatch, mizan_page):
    from domain_health_check.checks import rdap, tls
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
