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

Lab results move between runs: across three runs the score moved 14 points and
largest contentful paint 7%. Mobile runs three times and the band comes from
the median, so it cannot flip on noise. The mobile speed finding leads with
largest contentful paint in seconds ("takes about 4.4 seconds to show its main
content"), which means more to an owner than a score, and the spread of the
three scores goes in the details. A score is never a bare number in a summary:
an owner who re-runs the test and gets another one would stop trusting the rest.

The seo category is never scored: the site checks already measure the same
things directly. A slow page is never broken, so nothing here is a FAIL.
"""

from __future__ import annotations

from datetime import datetime
from statistics import median
from urllib.parse import quote

from ..external import ExternalContext
from ..models import SITE, CheckResult, Status

FIELD_SPEED = "Real-world loading speed"
MOBILE_SPEED = "Mobile speed"
ACCESSIBILITY = "Accessibility"
BEST_PRACTICES = "Best practices"
TEST_RAN = "Google speed test"

FIELD_CATEGORIES = {"FAST": Status.PASS, "AVERAGE": Status.WARN, "SLOW": Status.WARN}
LCP = "largest-contentful-paint"
OTHER_METRICS = ["first-contentful-paint", "total-blocking-time", "cumulative-layout-shift", "speed-index",
                 "interactive"]
RUNS_WANTED = 3

FIELD_EXPLANATION = (
    "Google measures how quickly websites load for real visitors using Chrome, and publishes the results once a "
    "site has enough visitors. Unlike a lab test, this reflects your actual customers' phones and connections."
)
NOT_ENOUGH_TRAFFIC = (
    "Your website does not yet get enough traffic for Google to publish real-world speed data. This is common "
    "for small businesses and is not a problem."
)
SPEED_EXPLANATION = (
    "Google's PageSpeed Insights loads your home page on a simulated mid-range phone and measures how long it takes "
    "to show its main content. Slow pages lose visitors, and speed is a small factor in Google rankings. Results "
    "move a little every time the test runs, so we run it three times."
)


def how_chosen(completed: int) -> str:
    """The method sentence, from the number of runs that actually finished, never a fixed claim."""
    if completed >= RUNS_WANTED:
        return "This time all three runs finished, and we used the middle result."
    if completed == 2:
        return ("This time only two of the three runs finished, so we used the average of the two, which is less "
                "reliable than the middle of three.")
    return "This time only one of the three runs finished, so treat this result as less reliable than usual."
SPEED_SUMMARY = {
    "top": "which puts it in Google's top speed band.",
    "middle": "which puts it in Google's middle speed band, so it could load faster.",
    "lowest": "which puts it in Google's lowest speed band, so some visitors will give up waiting.",
}
LAB = {  # name -> (Lighthouse category, explanation, summary for each of Google's bands)
    MOBILE_SPEED: ("performance", SPEED_EXPLANATION, {
        "top": "Google's lab test puts your home page in its top speed band on phones.",
        "middle": "Google's lab test puts your home page in its middle speed band on phones, so it could load faster.",
        "lowest": "Google's lab test puts your home page in its lowest speed band on phones, so some visitors will "
                  "give up waiting.",
    }),
    ACCESSIBILITY: ("accessibility", (
        "Google's automated accessibility test checks things such as text contrast, image descriptions and button "
        "labels, which matter to visitors with impaired vision and to anyone on a small screen. An automated test "
        "catches only some problems, so a top score is a good sign rather than a guarantee."), {
        "top": "Google's automated accessibility test puts your home page in its top band.",
        "middle": "Google's automated accessibility test puts your home page in its middle band, so a few things "
                  "could be easier to use for people with disabilities.",
        "lowest": "Google's automated accessibility test puts your home page in its lowest band, so parts of it are "
                  "likely hard to use for people with disabilities.",
    }),
    BEST_PRACTICES: ("best-practices", (
        "Google's best-practices test looks for common technical issues, such as errors in the browser, outdated "
        "code libraries and images shown at the wrong size."), {
        "top": "Google's best-practices test puts your home page in its top band.",
        "middle": "Google's best-practices test puts your home page in its middle band, so a few technical details "
                  "could be tidied up.",
        "lowest": "Google's best-practices test puts your home page in its lowest band, so several technical details "
                  "are worth a look.",
    }),
}
FIX = ("Ask your web developer to open Google's PageSpeed Insights report for your home page, linked in the technical "
       "details, and work through its suggestions.")


def lab_score(response: dict | None, category: str) -> int | None:
    """0 to 100, or None when the category is missing or Google could not score it."""
    score = ((response or {}).get("lighthouseResult", {}).get("categories", {}).get(category) or {}).get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return round(score * 100)


def band(score: int) -> str:
    """Google's own bands, so our report agrees with any other tool the owner runs."""
    if score >= 90:
        return "top"
    return "middle" if score >= 50 else "lowest"


def band_status(name: str) -> Status:
    return Status.PASS if name == "top" else Status.WARN


def report_link(response: dict) -> str:
    url = response.get("lighthouseResult", {}).get("finalUrl") or response.get("id", "")
    return f"https://pagespeed.web.dev/analysis?url={quote(url, safe='')}"


def _audit(response: dict, audit: str) -> dict:
    return response.get("lighthouseResult", {}).get("audits", {}).get(audit) or {}


def _run_date(runs: list[dict]) -> str:
    try:
        when = datetime.fromisoformat(runs[0]["analysisUTCTimestamp"].replace("Z", "+00:00"))
    except (KeyError, ValueError):
        return ""
    return f" on {when.day} {when:%B %Y}"


def _listed(values: list) -> str:
    """"73, 78 and 81"."""
    text = [str(v) for v in values]
    return text[0] if len(text) == 1 else ", ".join(text[:-1]) + f" and {text[-1]}"


def spread(runs: list[dict], category: str) -> tuple[int | None, str]:
    """(the figure used, the sentence saying where it came from), built from the runs that actually scored:
      three: "Three runs returned 73, 78 and 81 on 2 October 2026. We use the middle one, 78."
      two:   "Only two of three runs finished, returning 43 and 55 on ... With two there is no middle one, so we
              use their average, 49, which is less reliable than three runs."
      one:   "Only one of three runs finished, returning 64 on ... A single run can move by several points, so
              this figure is less reliable than usual."
    The median of two numbers is their average; calling it "the middle one" would be false."""
    scores = sorted(s for s in (lab_score(run, category) for run in runs) if s is not None)
    if not scores:
        return None, ""
    when = _run_date(runs)
    figure = round(median(scores))
    if len(scores) >= RUNS_WANTED:
        return figure, f"Three runs returned {_listed(scores)}{when}. We use the middle one, {figure}."
    if len(scores) == 2:
        return figure, (f"Only two of three runs finished, returning {_listed(scores)}{when}. With two there is no "
                        f"middle one, so we use their average, {figure}, which is less reliable than three runs.")
    return figure, (f"Only one of three runs finished, returning {scores[0]}{when}. A single run can move by several "
                    "points, so this figure is less reliable than usual.")


# ---------- Real-world loading speed

def evaluate_field_speed(loading: dict | None, origin: dict | None) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, FIELD_SPEED, status, summary, FIELD_EXPLANATION, fix, list(details), ran,
                           measure=measure)

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
    fix = ("Ask your web developer to look at the measurements in the technical details. Google's PageSpeed "
           "Insights report for your home page shows what to change first.")
    if category == "FAST":
        return result(Status.PASS, "Google's data from real visitors using Chrome shows your home page loads quickly.",
                      details=details)
    if category == "AVERAGE":
        return result(Status.WARN, "Google's data from real visitors using Chrome shows your home page loads at an "
                                   "average speed, with room to be faster.", fix, details, measure=0.5)
    return result(Status.WARN, "Google's data from real visitors using Chrome shows your home page loads slowly for "
                               "many of them.", fix, details, measure=0.0)  # Google's three bands, evenly spaced


def check_field_speed(external: ExternalContext) -> list[CheckResult]:
    if not external.psi_mobile:
        return []
    data = external.psi_mobile[0]  # field data is Google's 28-day record, the same in every run
    return [evaluate_field_speed(data.get("loadingExperience"), data.get("originLoadingExperience"))]


# ---------- Lab results: mobile speed, accessibility, best practices

def _not_scored(name: str, details: list[str]) -> CheckResult:
    return CheckResult(SITE, name, Status.WARN, f"Google's test did not produce a score for {name.lower()} this time.",
                       LAB[name][1], "Nothing to do.", details, ran=False)


def evaluate_mobile_speed(runs: list[dict], desktop: dict | None, desktop_error: str = "") -> CheckResult:
    score, ran = spread(runs, "performance")
    link = [f"Full report: {report_link(runs[0])}"] if runs else []
    if score is None:
        return _not_scored(MOBILE_SPEED, link)

    name = band(score)
    lcps = sorted(v for v in (_audit(run, LCP).get("numericValue") for run in runs) if isinstance(v, (int, float)))
    if lcps:
        seconds = median(lcps) / 1000
        summary = f"Your home page takes about {seconds:.1f} seconds to show its main content on a phone, " \
                  + SPEED_SUMMARY[name]
    else:
        summary = LAB[MOBILE_SPEED][2][name]

    details = [f"Lighthouse performance score, mobile: {ran} The band comes from that figure."]
    if len(lcps) >= RUNS_WANTED:
        details.append(f"Largest Contentful Paint: {median(lcps) / 1000:.1f} s, the middle of "
                       f"{_listed([f'{v / 1000:.1f}' for v in lcps])} s")
    elif len(lcps) == 2:
        details.append(f"Largest Contentful Paint: {median(lcps) / 1000:.1f} s, the average of "
                       f"{_listed([f'{v / 1000:.1f}' for v in lcps])} s")
    elif lcps:
        details.append(f"Largest Contentful Paint: {lcps[0] / 1000:.1f} s, from a single run")
    middle_run = min(runs, key=lambda run: abs((lab_score(run, "performance") or 0) - score))
    for audit in OTHER_METRICS:
        shown = _audit(middle_run, audit)
        if shown.get("displayValue"):
            details.append(f"{shown['title']}: {shown['displayValue'].replace(chr(160), ' ')} (middle run)")
    desktop_score = lab_score(desktop, "performance")
    if desktop_score is not None:
        details.append(f"Desktop performance score: {desktop_score} out of 100 (one run; it moves between runs)")
    elif desktop_error:
        details.append(f"Desktop: not available ({desktop_error})")
    status = band_status(name)
    explanation = f"{SPEED_EXPLANATION} {how_chosen(len(runs))}"
    return CheckResult(SITE, MOBILE_SPEED, status, summary, explanation, "" if status is Status.PASS else FIX,
                       details + link, measure=score / 100)  # Google's own graded measure, the median of the runs


def check_mobile_speed(external: ExternalContext) -> list[CheckResult]:
    if not external.psi_mobile:
        return []
    return [evaluate_mobile_speed(external.psi_mobile, external.psi_desktop, external.errors.get("psi_desktop", ""))]


def evaluate_lab(name: str, runs: list[dict]) -> CheckResult:
    category, explanation, summaries = LAB[name]
    score, ran = spread(runs, category)
    link = [f"Full report: {report_link(runs[0])}"] if runs else []
    if score is None:
        return _not_scored(name, link)
    status = band_status(band(score))
    return CheckResult(SITE, name, status, summaries[band(score)], explanation, "" if status is Status.PASS else FIX,
                       [f"Lighthouse {category} score, mobile: {ran}"] + link, measure=score / 100)


def check_accessibility(external: ExternalContext) -> list[CheckResult]:
    return [evaluate_lab(ACCESSIBILITY, external.psi_mobile)] if external.psi_mobile else []


def check_best_practices(external: ExternalContext) -> list[CheckResult]:
    return [evaluate_lab(BEST_PRACTICES, external.psi_mobile)] if external.psi_mobile else []


# ---------- When the test did not run

def check_speed_test_ran(external: ExternalContext) -> list[CheckResult]:
    """One row when a key is configured but no mobile run came back. No key means no row at all."""
    if not external.pagespeed_configured or external.psi_mobile:
        return []
    return [CheckResult(
        SITE, TEST_RAN, Status.WARN, "Google's speed test did not run this time, so speed is not part of this report.",
        "These checks come from Google's PageSpeed Insights, and this time it did not produce a result. The "
        "technical details say why. This is not a finding about your website.",
        "Nothing to do.",
        [f"{source}: {why}" for source, why in external.errors.items()], ran=False,
    )]
