"""The speed checks, against the real saved response. Variants are edits of that response, never invented ones."""

import copy
from datetime import datetime, timezone

import pytest

from domain_health_check import fetcher, runner, scoring
from domain_health_check.checks import pagespeed, rdap, tls
from domain_health_check.config import DomainConfig
from domain_health_check.external import ExternalContext
from domain_health_check.models import Status


def with_category(response: dict, category: str, score) -> dict:
    """The real response, with one Lighthouse category set to score (in Google's 0 to 1 scale)."""
    edited = copy.deepcopy(response)
    edited["lighthouseResult"]["categories"][category] = {"id": category, "score": score}
    return edited


# ---------- What the real response proves

def test_score_type_varies_and_both_kinds_are_read(psi_mobile):
    categories = psi_mobile["lighthouseResult"]["categories"]
    assert isinstance(categories["performance"]["score"], float) and isinstance(categories["seo"]["score"], int)
    assert pagespeed.lab_score(psi_mobile, "performance") == 64
    assert pagespeed.lab_score(psi_mobile, "seo") == 100


def test_field_data_is_empty_not_absent(psi_mobile):
    # loadingExperience is present but holds only initial_url. Checking for the key would be wrong.
    assert set(psi_mobile["loadingExperience"]) == {"initial_url"}
    assert "originLoadingExperience" not in psi_mobile


# ---------- Real-world loading speed

def test_mizan_has_not_enough_traffic_yet(psi_mobile):
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=psi_mobile))
    assert not result.ran
    assert "does not yet get enough traffic" in result.summary
    assert result.status is not Status.FAIL and result.fix == ""  # not reported as a problem


def test_no_field_data_scores_nothing(psi_mobile):
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=psi_mobile))
    assert scoring.score([result]) is None


@pytest.mark.parametrize("category, status", [("FAST", Status.PASS), ("AVERAGE", Status.WARN), ("SLOW", Status.FAIL)])
def test_field_categories(psi_mobile, category, status):
    response = copy.deepcopy(psi_mobile)
    response["loadingExperience"].update({
        "overall_category": category,
        "metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300, "category": category}},
    })
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=response))
    assert result.status is status and result.ran
    assert f"LARGEST_CONTENTFUL_PAINT_MS: 2300 ({category})" in result.details


def test_origin_data_is_never_presented_as_the_page(psi_mobile):
    response = copy.deepcopy(psi_mobile)
    response["originLoadingExperience"] = {"overall_category": "SLOW"}
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=response))
    assert not result.ran
    assert "website as a whole" in result.summary and "not yet for your home page" in result.summary
    assert result.details == ["Whole website, all pages together: SLOW"]


# ---------- Lab scores

def test_mizan_mobile_speed_is_in_the_middle_band(psi_mobile):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=psi_mobile))
    assert result.status is Status.WARN and result.ran
    assert "64" not in result.summary  # the band, not a precise-sounding number
    assert "Lighthouse performance score: 64 out of 100 (mobile, one run; scores move a few points between runs)" \
        in result.details
    assert "Largest Contentful Paint: 5.7 s" in result.details
    assert "Full report: https://pagespeed.web.dev/analysis?url=https%3A%2F%2Fwww.mizangroupllc.com%2F" in result.details


@pytest.mark.parametrize("score, status", [
    (1, Status.PASS), (0.9, Status.PASS), (0.895, Status.PASS),  # rounds to 90
    (0.89, Status.WARN), (0.5, Status.WARN), (0.49, Status.FAIL), (0, Status.FAIL),
])
def test_google_bands(psi_mobile, score, status):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=with_category(psi_mobile, "performance", score)))
    assert result.status is status


def test_null_score_did_not_run(psi_mobile):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=with_category(psi_mobile, "performance", None)))
    assert not result.ran


def test_missing_categories_in_the_real_response_did_not_run(psi_mobile):
    # The saved response has no accessibility or best-practices category, so neither can be scored.
    context = ExternalContext(psi_mobile=psi_mobile)
    for check in (pagespeed.check_accessibility, pagespeed.check_best_practices):
        [result] = check(context)
        assert not result.ran and "did not produce a score" in result.summary


@pytest.mark.parametrize("check, category", [
    (pagespeed.check_accessibility, "accessibility"), (pagespeed.check_best_practices, "best-practices"),
])
def test_accessibility_and_best_practices_score_when_present(psi_mobile, check, category):
    [result] = check(ExternalContext(psi_mobile=with_category(psi_mobile, category, 0.96)))
    assert result.status is Status.PASS and result.ran
    assert f"Lighthouse {category} score: 96 out of 100" in result.details[0]


def test_seo_category_is_never_its_own_finding(psi_mobile):
    context = ExternalContext(psi_mobile=psi_mobile)
    results = (pagespeed.check_field_speed(context) + pagespeed.check_mobile_speed(context)
               + pagespeed.check_accessibility(context) + pagespeed.check_best_practices(context))
    assert not any("seo" in r.name.lower() for r in results)


def test_desktop_score_goes_in_the_details(psi_mobile):
    desktop = with_category(psi_mobile, "performance", 0.93)
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=psi_mobile, psi_desktop=desktop))
    assert "Desktop performance score: 93 out of 100 (one run; scores move a few points between runs)" in result.details

    failed = ExternalContext(psi_mobile=psi_mobile, errors={"psi_desktop": "desktop: no answer within 120 seconds"})
    assert "Desktop: not available (desktop: no answer within 120 seconds)" in pagespeed.check_mobile_speed(failed)[0].details


# ---------- When the test did not run

def test_no_key_means_no_rows_at_all():
    context = ExternalContext()
    checks = (pagespeed.check_speed_test_ran, pagespeed.check_field_speed, pagespeed.check_mobile_speed,
              pagespeed.check_accessibility, pagespeed.check_best_practices)
    assert [r for check in checks for r in check(context)] == []


def test_timeout_is_one_row_that_did_not_run():
    context = ExternalContext(errors={"psi_mobile": "mobile: no answer within 120 seconds"})
    [result] = pagespeed.check_speed_test_ran(context)
    assert not result.ran and "not a finding about your website" in result.explanation
    assert pagespeed.check_mobile_speed(context) == []


def test_a_result_means_no_did_not_run_row(psi_mobile):
    assert pagespeed.check_speed_test_ran(ExternalContext(psi_mobile=psi_mobile)) == []


def test_full_run_adds_the_speed_rows_and_scores_only_what_ran(fake_dns, monkeypatch, mizan_page, psi_mobile):
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: mizan_page)
    asked = []
    monkeypatch.setattr(runner.external, "fetch_external",
                        lambda d, url, skipped: asked.append(url) or ExternalContext(psi_mobile=psi_mobile))
    report = runner.run_checks(DomainConfig("mizangroupllc.com"), datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert [(r.name, r.status, r.ran) for r in report.results][-4:] == [
        ("Real-world loading speed", Status.PASS, False),
        ("Mobile speed", Status.WARN, True),
        ("Accessibility", Status.WARN, False),
        ("Best practices", Status.WARN, False),
    ]
    assert asked == ["https://www.mizangroupllc.com/"]  # the final URL, after the redirect
    assert scoring.score(report.results) == scoring.score([r for r in report.results if r.ran])
