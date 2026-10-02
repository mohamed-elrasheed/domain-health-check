"""Speed, accessibility and best practices, from Google's PageSpeed Insights.

Read from the ExternalContext the runner fetched; no requests here.

Shapes confirmed against a real response (tests/fixtures/.../psi-mobile.json),
not the reference page:
  * lighthouseResult.categories.*.score runs from 0 to 1, and its type varies:
    0.64 came back as a float, 1 as an int. It can also be null when a category
    errors, which means did not run.
  * loadingExperience can be present with nothing in it but initial_url. Real
    field data is there only when overall_category is. originLoadingExperience
    can be missing entirely. Both being empty is the usual case for a small
    business, not an edge case.
  * originLoadingExperience describes the whole site, never the page, and is
    labeled that way.

Lab scores move a few points between runs, so a summary names Google's band and
the number goes in the details with that caveat. The seo category is never
scored: the site checks already measure the same things directly.
"""

from __future__ import annotations

from urllib.parse import quote

from ..external import ExternalContext
from ..models import SITE, CheckResult, Status

FIELD_SPEED = "Real-world loading speed"
MOBILE_SPEED = "Mobile speed"
ACCESSIBILITY = "Accessibility"
BEST_PRACTICES = "Best practices"
TEST_RAN = "Google speed test"

FIELD_CATEGORIES = {"FAST": Status.PASS, "AVERAGE": Status.WARN, "SLOW": Status.FAIL}
SPEED_AUDITS = ["first-contentful-paint", "largest-contentful-paint", "total-blocking-time",
                "cumulative-layout-shift", "speed-index", "interactive"]
VARIES = "one run; scores move a few points between runs"

FIELD_EXPLANATION = (
    "Google measures how quickly websites load for real visitors using Chrome, and publishes the results once a "
    "site has enough visitors. Unlike a lab test, this reflects your actual customers' phones and connections."
)
NOT_ENOUGH_TRAFFIC = (
    "Your website does not yet get enough traffic for Google to publish real-world speed data. This is common "
    "for small businesses and is not a problem."
)
LAB = {
    MOBILE_SPEED: (
        "performance",
        "Google's PageSpeed Insights loads your home page on a simulated mid-range phone and rates how quickly it "
        "becomes usable. Slow pages lose visitors, and speed is a small factor in Google rankings. The score moves "
        "a little every time the test runs, so the band matters more than the exact number.",
        {Status.PASS: "Google's lab test puts your home page in its top speed band on phones.",
         Status.WARN: "Google's lab test puts your home page in its middle speed band on phones, so it could load "
                      "faster.",
         Status.FAIL: "Google's lab test puts your home page in its lowest speed band on phones, so it likely feels "
                      "slow to visitors on a phone."},
    ),
    ACCESSIBILITY: (
        "accessibility",
        "Google's automated accessibility test checks things such as text contrast, image descriptions and button "
        "labels, which matter to visitors with impaired vision and to anyone on a small screen. An automated test "
        "catches only some problems, so a top score is a good sign rather than a guarantee.",
        {Status.PASS: "Google's automated accessibility test puts your home page in its top band.",
         Status.WARN: "Google's automated accessibility test puts your home page in its middle band, so a few things "
                      "could be easier to use for people with disabilities.",
         Status.FAIL: "Google's automated accessibility test puts your home page in its lowest band, so parts of it "
                      "are likely hard to use for people with disabilities."},
    ),
    BEST_PRACTICES: (
        "best-practices",
        "Google's best-practices test looks for common technical issues, such as errors in the browser, outdated "
        "code libraries and images shown at the wrong size.",
        {Status.PASS: "Google's best-practices test puts your home page in its top band.",
         Status.WARN: "Google's best-practices test puts your home page in its middle band, so a few technical "
                      "details could be tidied up.",
         Status.FAIL: "Google's best-practices test puts your home page in its lowest band, so several technical "
                      "details need attention."},
    ),
}


def lab_score(response: dict | None, category: str) -> int | None:
    """0 to 100, or None when the category is missing or Google could not score it."""
    score = ((response or {}).get("lighthouseResult", {}).get("categories", {}).get(category) or {}).get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return round(score * 100)


def band(score: int) -> Status:
    """Google's own bands, so our report agrees with any other tool the owner runs."""
    if score >= 90:
        return Status.PASS
    return Status.WARN if score >= 50 else Status.FAIL


def report_link(response: dict) -> str:
    url = response.get("lighthouseResult", {}).get("finalUrl") or response.get("id", "")
    return f"https://pagespeed.web.dev/analysis?url={quote(url, safe='')}"


# ---------- Real-world loading speed

def evaluate_field_speed(loading: dict | None, origin: dict | None) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True) -> CheckResult:
        return CheckResult(SITE, FIELD_SPEED, status, summary, FIELD_EXPLANATION, fix, list(details), ran)

    category = (loading or {}).get("overall_category")
    if category not in FIELD_CATEGORIES:
        origin_category = (origin or {}).get("overall_category")
        if origin_category in FIELD_CATEGORIES:
            return result(Status.PASS, "Google publishes real-world speed data for your website as a whole, but not "
                                       "yet for your home page on its own.",
                          details=[f"Whole website, all pages together: {origin_category}"], ran=False)
        return result(Status.PASS, NOT_ENOUGH_TRAFFIC, ran=False)

    details = [f"Home page, real Chrome visitors: {category}"]
    for metric, value in sorted((loading.get("metrics") or {}).items()):
        details.append(f"{metric}: {value.get('percentile')} ({value.get('category')})")
    if (origin or {}).get("overall_category"):
        details.append(f"Whole website, all pages together: {origin['overall_category']}")
    status = FIELD_CATEGORIES[category]
    fix = ("Ask your web developer to look at the measurements in the technical details. Google's PageSpeed "
           "Insights report for your home page shows what to change first.")
    if status is Status.PASS:
        return result(status, "Google's data from real visitors using Chrome shows your home page loads quickly.",
                      details=details)
    if status is Status.WARN:
        return result(status, "Google's data from real visitors using Chrome shows your home page loads at an "
                              "average speed, with room to be faster.", fix, details)
    return result(status, "Google's data from real visitors using Chrome shows your home page loads slowly for many "
                          "of them.", fix, details)


def check_field_speed(external: ExternalContext) -> list[CheckResult]:
    data = external.psi_mobile
    if data is None:
        return []
    return [evaluate_field_speed(data.get("loadingExperience"), data.get("originLoadingExperience"))]


# ---------- Lab scores: mobile speed, accessibility, best practices

def evaluate_lab(name: str, score: int | None, details: list[str]) -> CheckResult:
    category, explanation, summaries = LAB[name]
    if score is None:
        return CheckResult(SITE, name, Status.WARN, f"Google's test did not produce a score for {name.lower()} this time.",
                           explanation, "Nothing to do. We will run it again on the next check.", details, ran=False)
    status = band(score)
    fix = "" if status is Status.PASS else (
        "Ask your web developer to open Google's PageSpeed Insights report for your home page, linked in the "
        "technical details, and work through its suggestions.")
    return CheckResult(SITE, name, status, summaries[status], explanation, fix,
                       [f"Lighthouse {category} score: {score} out of 100 (mobile, {VARIES})"] + details)


def _lab_check(name: str, external: ExternalContext, extra: list[str] = ()) -> list[CheckResult]:
    data = external.psi_mobile
    if data is None:
        return []
    return [evaluate_lab(name, lab_score(data, LAB[name][0]), list(extra) + [f"Full report: {report_link(data)}"])]


def check_mobile_speed(external: ExternalContext) -> list[CheckResult]:
    data = external.psi_mobile or {}
    audits = data.get("lighthouseResult", {}).get("audits", {})
    extra = [f"{audits[a]['title']}: {audits[a]['displayValue'].replace(chr(160), ' ')}"
             for a in SPEED_AUDITS if audits.get(a, {}).get("displayValue")]
    desktop = lab_score(external.psi_desktop, "performance")
    if desktop is not None:
        extra.append(f"Desktop performance score: {desktop} out of 100 ({VARIES})")
    elif "psi_desktop" in external.errors:
        extra.append(f"Desktop: not available ({external.errors['psi_desktop']})")
    return _lab_check(MOBILE_SPEED, external, extra)


def check_accessibility(external: ExternalContext) -> list[CheckResult]:
    return _lab_check(ACCESSIBILITY, external)


def check_best_practices(external: ExternalContext) -> list[CheckResult]:
    return _lab_check(BEST_PRACTICES, external)


# ---------- When the test did not run

def check_speed_test_ran(external: ExternalContext) -> list[CheckResult]:
    """One row when a key is configured but there is no mobile result. No key means no row at all."""
    if not external.pagespeed_configured or external.psi_mobile is not None:
        return []
    return [CheckResult(
        SITE, TEST_RAN, Status.WARN, "Google's speed test did not run this time, so speed is not part of this report.",
        "These checks come from Google's PageSpeed Insights, and this time it did not produce a result. The "
        "technical details say why. This is not a finding about your website.",
        "Nothing to do. We will run it again on the next check.",
        [f"{source}: {why}" for source, why in external.errors.items()], ran=False,
    )]
