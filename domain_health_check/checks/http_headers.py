"""HTTPS security headers.

Every web page arrives with "headers": short instructions from the server to
the browser. A few of them switch on browser security features:

  * HSTS (Strict-Transport-Security): "only ever talk to me over HTTPS, for the
    next N seconds." After the first visit, the browser refuses to load the
    site over plain HTTP, even if someone on the network tries to downgrade
    the connection.
  * Content-Security-Policy (CSP): a list of where scripts, images, etc. are
    allowed to come from. If an attacker manages to inject a script, the
    browser refuses to run it.
  * X-Content-Type-Options: nosniff: "trust the file type I tell you." Stops
    browsers guessing that an uploaded text file is actually a script.

We fetch the home page once, as a browser would, and read its headers.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request

from ..models import WEBSITE, CheckResult, Status

TIMEOUT_SECONDS = 10
USER_AGENT = "domain-health-check/0.1 (+https://www.mizangroupllc.com/digital)"
HSTS_MIN_SECONDS = 15_552_000  # 180 days, the common recommendation

HSTS_EXPLANATION = (
    "HSTS tells browsers to always use the secure (HTTPS) version of your website. Without it, a visitor "
    "on an untrusted network such as public Wi-Fi can be quietly redirected to an insecure copy of the site."
)
CSP_EXPLANATION = (
    "A Content Security Policy tells browsers which sources of scripts and other content your website "
    "trusts. If an attacker manages to slip malicious code onto a page, the browser refuses to run it."
)
XCTO_EXPLANATION = (
    "This setting stops browsers from guessing what type a file is. Without it, a file that should be "
    "treated as harmless text could, in some cases, be run as code."
)


def fetch_headers(domain: str) -> tuple[str, dict[str, str]]:
    """GET the home page over HTTPS (following redirects) and return (final_url, headers)."""
    request = urllib.request.Request(f"https://{domain}/", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return response.geturl(), {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        # Error pages (403, 404, 500...) still carry headers worth checking.
        return exc.filename, {k.lower(): v for k, v in (exc.headers or {}).items()}


def evaluate_hsts(value: str | None) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(WEBSITE, "HSTS (always use HTTPS)", status, summary, HSTS_EXPLANATION, fix, list(details))

    fix = (
        "Ask your web developer or host to add the header "
        "`Strict-Transport-Security: max-age=31536000; includeSubDomains` to the website."
    )
    if value is None:
        return result(Status.FAIL, "The website doesn't tell browsers to always use HTTPS.", fix)

    details = [f"Header value: {value}"]
    match = re.search(r"max-age\s*=\s*\"?(\d+)", value, re.IGNORECASE)
    if not match:
        return result(Status.WARN, "HSTS is present but written incorrectly (no max-age).", fix, details)
    days = int(match.group(1)) // 86_400
    if int(match.group(1)) < HSTS_MIN_SECONDS:
        return result(
            Status.WARN, f"HSTS is on, but only remembered for {days} days.",
            "Increase max-age to at least 15552000 (180 days); 31536000 (one year) is typical.", details,
        )
    return result(Status.PASS, f"Browsers are told to always use HTTPS for {days} days.", details=details)


def evaluate_csp(value: str | None, report_only: str | None) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=()) -> CheckResult:
        return CheckResult(WEBSITE, "Content Security Policy", status, summary, CSP_EXPLANATION, fix, list(details))

    fix = (
        "Ask your web developer to add a Content-Security-Policy header. They can start in "
        "report-only mode to see what would break before enforcing it."
    )
    if value:
        details = [f"Header value: {value[:300]}{'...' if len(value) > 300 else ''}"]
        if "'unsafe-inline'" in value or "'unsafe-eval'" in value:
            details.append("Note: the policy allows 'unsafe-inline' or 'unsafe-eval', which weakens it.")
        return result(Status.PASS, "A Content Security Policy is in place.", details=details)
    if report_only:
        return result(
            Status.WARN, "A Content Security Policy exists but only reports problems; it doesn't block anything.",
            "Once the reports look clean, switch the header from Content-Security-Policy-Report-Only "
            "to Content-Security-Policy so it is enforced.",
            [f"Report-only header: {report_only[:300]}"],
        )
    return result(Status.WARN, "No Content Security Policy is set.", fix)


def evaluate_content_type_options(value: str | None) -> CheckResult:
    name = "X-Content-Type-Options"
    fix = "Ask your web developer or host to add the header `X-Content-Type-Options: nosniff`."
    if value is None:
        return CheckResult(WEBSITE, name, Status.WARN, "The nosniff protection is not switched on.", XCTO_EXPLANATION, fix)
    if value.strip().lower() != "nosniff":
        return CheckResult(
            WEBSITE, name, Status.WARN, "The header is present but has an unexpected value.",
            XCTO_EXPLANATION, fix, [f"Header value: {value}"],
        )
    return CheckResult(WEBSITE, name, Status.PASS, "The nosniff protection is switched on.", XCTO_EXPLANATION)


def check_http_headers(domain: str) -> list[CheckResult]:
    try:
        final_url, headers = fetch_headers(domain)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [CheckResult(
            WEBSITE, "Security headers", Status.WARN,
            f"We couldn't load https://{domain}/ to check its security headers.",
            "Security headers switch on protections built into visitors' browsers.",
            "If this domain is meant to have a website, ask your web host why the home page can't be "
            "loaded over HTTPS. If it's only used for email, you can ignore this.",
            [f"Error: {getattr(exc, 'reason', exc)}"],
        )]

    results = [
        evaluate_hsts(headers.get("strict-transport-security")),
        evaluate_csp(headers.get("content-security-policy"), headers.get("content-security-policy-report-only")),
        evaluate_content_type_options(headers.get("x-content-type-options")),
    ]
    for r in results:
        r.details.append(f"Checked page: {final_url}")
    return results
