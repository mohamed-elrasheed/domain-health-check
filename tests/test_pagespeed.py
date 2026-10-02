"""The speed checks, against the real saved response. Variants, including the three mobile runs, are edits of
that response, never invented ones."""

import copy
from datetime import datetime, timezone

import pytest

from domain_health_check import fetcher, runner, scoring
from domain_health_check.checks import pagespeed, rdap, tls
from domain_health_check.config import DomainConfig
from domain_health_check.external import ExternalContext
from domain_health_check.models import Status


def edited(response: dict, **scores) -> dict:
    """The real response with category scores changed, given in Google's 0 to 1 scale.
    lcp_ms sets the largest contentful paint audit; None removes a category."""
    result = copy.deepcopy(response)
    lcp = scores.pop("lcp_ms", None)
    for category, score in scores.items():
        category = category.replace("_", "-")
        if score is None:
            result["lighthouseResult"]["categories"].pop(category, None)
        else:
            result["lighthouseResult"]["categories"][category] = {"id": category, "score": score}
    if lcp is not None:
        audit = result["lighthouseResult"]["audits"]["largest-contentful-paint"]
        audit["numericValue"] = lcp
        audit["displayValue"] = f"{lcp / 1000:.1f}\xa0s"
    return result


@pytest.fixture
def three_runs(psi_mobile):
    """Three runs that disagree the way real ones do: 73, 78 and 81, LCP 4.1 to 4.7 seconds."""
    return [edited(psi_mobile, performance=0.81, lcp_ms=4100),
            edited(psi_mobile, performance=0.73, lcp_ms=4700),
            edited(psi_mobile, performance=0.78, lcp_ms=4400)]


# ---------- What the real response proves

def test_score_type_varies_and_both_kinds_are_read(psi_mobile):
    categories = psi_mobile["lighthouseResult"]["categories"]
    assert isinstance(categories["performance"]["score"], float) and isinstance(categories["seo"]["score"], int)
    assert pagespeed.lab_score(psi_mobile, "performance") == 79
    assert pagespeed.lab_score(psi_mobile, "accessibility") == 100


def test_field_data_is_empty_not_absent(psi_mobile):
    # loadingExperience is present but holds only initial_url. Checking for the key would be wrong.
    assert set(psi_mobile["loadingExperience"]) == {"initial_url"}
    assert "originLoadingExperience" not in psi_mobile


# ---------- Median of three

def test_band_comes_from_the_median_and_the_spread_is_in_the_details(three_runs):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=three_runs))
    assert result.status is Status.WARN
    assert ("Lighthouse performance score, mobile: Three runs returned 73, 78 and 81 on 2 October 2026. We use "
            "the middle one, 78. The band comes from that figure.") in result.details
    assert result.explanation.endswith("This time all three runs finished, and we used the middle result.")


def test_summary_leads_with_lcp_never_a_score(three_runs):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=three_runs))
    assert result.summary.startswith("Your home page takes about 4.4 seconds to show its main content on a phone")
    for score in ("73", "78", "81", "out of 100"):
        assert score not in result.summary
    assert "Largest Contentful Paint: 4.4 s, the middle of 4.1, 4.4 and 4.7 s" in result.details


def test_one_noisy_run_cannot_flip_the_band(psi_mobile):
    runs = [edited(psi_mobile, performance=0.91), edited(psi_mobile, performance=0.62),
            edited(psi_mobile, performance=0.92)]
    assert pagespeed.check_mobile_speed(ExternalContext(psi_mobile=runs))[0].status is Status.PASS


def test_two_runs_say_two_and_use_their_average_honestly(three_runs):
    # The live bug: "we ran it three times and used the middle result" beside "Two runs returned 43 and 55.
    # We use the middle one, 49." The median of two is their average, and the text must say so.
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=three_runs[:2]))
    assert result.ran
    detail = result.details[0]
    assert "Only two of three runs finished, returning 73 and 81" in detail
    assert "we use their average, 77, which is less reliable than three runs" in detail
    assert "We use the middle one" not in detail
    assert "only two of the three runs finished, so we used the average of the two" in result.explanation
    assert "used the middle result" not in result.explanation
    assert "Largest Contentful Paint: 4.4 s, the average of 4.1 and 4.7 s" in result.details


def test_one_run_says_one(three_runs):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=three_runs[:1]))
    assert "Only one of three runs finished, returning 81" in result.details[0]
    assert "only one of the three runs finished" in result.explanation
    assert "Largest Contentful Paint: 4.1 s, from a single run" in result.details


def test_other_metrics_come_from_the_middle_run(three_runs):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=three_runs))
    assert "First Contentful Paint: 2.6 s (middle run)" in result.details


def test_accessibility_uses_the_median_too(psi_mobile):
    runs = [edited(psi_mobile, accessibility=0.95), edited(psi_mobile, accessibility=0.84),
            edited(psi_mobile, accessibility=0.92)]
    [result] = pagespeed.check_accessibility(ExternalContext(psi_mobile=runs))
    assert result.status is Status.PASS
    assert result.details[0].startswith("Lighthouse accessibility score, mobile: Three runs returned 84, 92 and 95")


# ---------- Real-world loading speed

def test_mizan_has_not_enough_traffic_yet(psi_mobile):
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=[psi_mobile]))
    assert not result.ran
    assert "does not yet get enough traffic" in result.summary
    assert result.fix == ""  # not reported as a problem
    assert scoring.score([result]) is None


@pytest.mark.parametrize("category, status", [("FAST", Status.PASS), ("AVERAGE", Status.WARN), ("SLOW", Status.WARN)])
def test_field_categories(psi_mobile, category, status):
    response = copy.deepcopy(psi_mobile)
    response["loadingExperience"].update({
        "overall_category": category,
        "metrics": {"LARGEST_CONTENTFUL_PAINT_MS": {"percentile": 2300, "category": category}},
    })
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=[response]))
    assert result.status is status and result.ran
    assert f"LARGEST_CONTENTFUL_PAINT_MS: 2300 ({category})" in result.details


def test_origin_data_is_never_presented_as_the_page(psi_mobile):
    response = copy.deepcopy(psi_mobile)
    response["originLoadingExperience"] = {"overall_category": "SLOW"}
    [result] = pagespeed.check_field_speed(ExternalContext(psi_mobile=[response]))
    assert not result.ran
    assert "website as a whole" in result.summary and "not yet for your home page" in result.summary
    assert result.details == ["Whole website, all pages together: SLOW"]


# ---------- Bands

def test_mizan_mobile_speed(psi_mobile):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=[psi_mobile]))
    assert result.status is Status.WARN and result.ran
    assert result.summary.startswith("Your home page takes about 4.8 seconds")
    assert "Full report: https://pagespeed.web.dev/analysis?url=https%3A%2F%2Fwww.mizangroupllc.com%2F" in result.details


@pytest.mark.parametrize("score, status", [
    (1, Status.PASS), (0.9, Status.PASS), (0.895, Status.PASS),  # rounds to 90
    (0.89, Status.WARN), (0.5, Status.WARN), (0.49, Status.WARN), (0, Status.WARN),  # slow is never broken
])
def test_google_bands(psi_mobile, score, status):
    runs = [edited(psi_mobile, performance=score)] * 3
    assert pagespeed.check_mobile_speed(ExternalContext(psi_mobile=runs))[0].status is status


def test_lowest_band_wording_without_a_fail(psi_mobile):
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=[edited(psi_mobile, performance=0.3)] * 3))
    assert result.status is Status.WARN and "lowest speed band" in result.summary


def test_null_score_did_not_run(psi_mobile):
    runs = [edited(psi_mobile, performance=None)] * 3
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=runs))
    assert not result.ran


def test_mizan_accessibility_and_best_practices_pass(psi_mobile):
    context = ExternalContext(psi_mobile=[psi_mobile])
    for check in (pagespeed.check_accessibility, pagespeed.check_best_practices):
        [result] = check(context)
        assert result.status is Status.PASS and result.ran


def test_missing_categories_did_not_run(psi_mobile):
    # A request without the category parameters returns a response like this one, minus those categories.
    context = ExternalContext(psi_mobile=[edited(psi_mobile, accessibility=None, best_practices=None)])
    for check in (pagespeed.check_accessibility, pagespeed.check_best_practices):
        [result] = check(context)
        assert not result.ran and "did not produce a score" in result.summary


def test_seo_category_is_never_its_own_finding(psi_mobile):
    context = ExternalContext(psi_mobile=[psi_mobile])
    results = (pagespeed.check_field_speed(context) + pagespeed.check_mobile_speed(context)
               + pagespeed.check_accessibility(context) + pagespeed.check_best_practices(context))
    assert not any("seo" in r.name.lower() for r in results)


def test_desktop_is_one_run_in_the_details(psi_mobile):
    desktop = edited(psi_mobile, performance=0.93)
    [result] = pagespeed.check_mobile_speed(ExternalContext(psi_mobile=[psi_mobile], psi_desktop=desktop))
    assert "Desktop performance score: 93 out of 100 (one run; it moves between runs)" in result.details

    failed = ExternalContext(psi_mobile=[psi_mobile], errors={"psi_desktop": "desktop: no answer within 120 seconds"})
    assert "Desktop: not available (desktop: no answer within 120 seconds)" in \
        pagespeed.check_mobile_speed(failed)[0].details


# ---------- When the test did not run

def test_no_key_means_no_rows_at_all():
    context = ExternalContext()
    checks = (pagespeed.check_speed_test_ran, pagespeed.check_field_speed, pagespeed.check_mobile_speed,
              pagespeed.check_accessibility, pagespeed.check_best_practices)
    assert [r for check in checks for r in check(context)] == []


def test_all_runs_failing_is_one_row_that_did_not_run():
    context = ExternalContext(errors={f"psi_mobile_{n}": f"mobile run {n}: no answer within 120 seconds"
                                      for n in (1, 2, 3)})
    [result] = pagespeed.check_speed_test_ran(context)
    assert not result.ran and "not a finding about your website" in result.explanation
    assert pagespeed.check_mobile_speed(context) == []


def test_a_result_means_no_did_not_run_row(psi_mobile):
    assert pagespeed.check_speed_test_ran(ExternalContext(psi_mobile=[psi_mobile])) == []


def test_full_run_adds_the_speed_rows_and_scores_only_what_ran(fake_dns, monkeypatch, mizan_page, three_runs):
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: mizan_page)
    asked = []
    monkeypatch.setattr(runner.external, "fetch_external",
                        lambda d, url, skipped, **kw: asked.append(url) or ExternalContext(psi_mobile=three_runs))
    report = runner.run_checks(DomainConfig("mizangroupllc.com"), datetime(2026, 10, 1, tzinfo=timezone.utc))
    assert [(r.name, r.status, r.ran) for r in report.results][-4:] == [
        ("Real-world loading speed", Status.PASS, False),
        ("Mobile speed", Status.WARN, True),
        ("Accessibility", Status.PASS, True),
        ("Best practices", Status.PASS, True),
    ]
    assert asked == ["https://www.mizangroupllc.com/"]  # the final URL, after the redirect
    assert scoring.score(report.results) == scoring.score([r for r in report.results if r.ran])
