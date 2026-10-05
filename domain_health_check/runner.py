"""Runs every check for one domain and collects the results."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
from typing import Callable

from . import dns_utils, external, fetcher, linkcheck, platform, requestlog
from .checks import business_profile, dns_records, dnssec, email_auth, http_headers, pagespeed, rdap, site, tls
from .checks.site import content, delivery, favicon, indexing, links, mixed_content, sharing, structured_data
from .config import DomainConfig
from .external import Business, ExternalContext
from .fetcher import FetchError, PageContext, PageStatusError, RobotsDisallowed, status_phrase
from .models import DOMAIN, EMAIL, LOCAL, SITE, WEBSITE, CheckResult, DomainReport, Status


def _checks_for(
    domain: DomainConfig, now: datetime, page: PageContext | FetchError, ext: ExternalContext,
) -> list[tuple[str, str, Callable[[], list[CheckResult]]]]:
    """(category, name, zero-argument function) in the order they appear in the report."""
    d = domain.name

    def on_page(check: Callable[[PageContext], list[CheckResult]]) -> Callable[[], list[CheckResult]]:
        """Site checks need the page itself. When it could not be loaded, check_page_loaded says so once."""
        return lambda: check(page) if isinstance(page, PageContext) else []

    def on_rendered_page(check: Callable[[PageContext], list[CheckResult]]) -> Callable[[], list[CheckResult]]:
        """Content checks also need text to read. When scripts build it and no browser could run them,
        check_page_rendered says so once."""
        return lambda: check(page) if isinstance(page, PageContext) and not (
            page.script_built and not page.rendered) else []

    return [
        (WEBSITE, "SSL/TLS", lambda: tls.check_tls(d, now)),
        (WEBSITE, "Security headers", lambda: http_headers.check_http_headers(page)),
        (DOMAIN, "Domain registration", lambda: rdap.check_registration(d, now)),
        (DOMAIN, "Nameservers", lambda: dns_records.check_nameservers(d)),
        (DOMAIN, "DNSSEC", lambda: dnssec.check_dnssec(d)),
        (EMAIL, "Mail servers (MX)", lambda: dns_records.check_mx(d)),
        (EMAIL, "SPF (approved senders)", lambda: email_auth.check_spf(d)),
        (EMAIL, "DKIM (email signatures)", lambda: email_auth.check_dkim(d, domain.dkim_selectors)),
        (EMAIL, "DMARC (anti-spoofing policy)", lambda: email_auth.check_dmarc(d)),
        (SITE, "Search engine blocking", lambda: indexing.check_search_blocking(page)),
        (SITE, "Site health checks", lambda: site.check_page_loaded(page)),
        (SITE, "Page content checks", lambda: site.check_page_rendered(page)),
        (SITE, "Page title", on_rendered_page(content.check_title)),
        (SITE, "Meta description", on_rendered_page(content.check_description)),
        (SITE, "Canonical tag", on_page(indexing.check_canonical)),
        (SITE, "Main heading", on_rendered_page(content.check_main_heading)),
        (SITE, "Mobile viewport", on_page(delivery.check_viewport)),
        (SITE, "Structured data matches the page", on_page(structured_data.check_structured_data)),
        (SITE, "Heading order", on_rendered_page(content.check_heading_order)),
        (SITE, "Image alt text", on_rendered_page(content.check_alt_text)),
        (SITE, "Social preview", on_page(sharing.check_social_preview)),
        (SITE, "Sitemap and robots", on_page(indexing.check_sitemap_and_robots)),
        (SITE, "Page weight", on_page(delivery.check_page_weight)),
        (SITE, "Redirect chain", on_page(delivery.check_redirects)),
        (SITE, "Broken links", on_page(links.check_links)),
        (SITE, "Mixed content", on_page(mixed_content.check_mixed_content)),
        (SITE, "Favicon", on_page(favicon.check_favicon)),
        (SITE, "Google speed test", lambda: pagespeed.check_speed_test_ran(ext)),
        (SITE, "Real-world loading speed", lambda: pagespeed.check_field_speed(ext)),
        (SITE, "Mobile speed", lambda: pagespeed.check_mobile_speed(ext)),
        (SITE, "Accessibility", lambda: pagespeed.check_accessibility(ext)),
        (SITE, "Best practices", lambda: pagespeed.check_best_practices(ext)),
        (LOCAL, "Google Business Profile", lambda: business_profile.check_profile(ext)),
        (LOCAL, "Profile completeness", lambda: business_profile.check_completeness(ext)),
        (LOCAL, "Profile website link", lambda: business_profile.check_website_link(ext, d)),
        (LOCAL, "Reviews", lambda: business_profile.check_reviews(ext)),
    ]


def run_checks(domain: DomainConfig, now: datetime | None = None) -> DomainReport:
    """The report for one domain, with every request it made recorded on it."""
    with requestlog.recording() as requests:
        report = _run_checks(domain, now or datetime.now(timezone.utc))
    report.requests = list(requests)
    return report


def _run_checks(domain: DomainConfig, now: datetime) -> DomainReport:
    if _domain_exists(domain.name) is False:
        return _unregistered(domain.name, now)
    incomplete: list[str] = []
    page = _fetch_page(domain.name)
    if isinstance(page, FetchError):
        incomplete.append(f"The home page could not be loaded, so the site health checks did not run: {page.reason}")
    page, render_failure = _render_in_browser(page)
    if render_failure:
        incomplete.append(f"The browser could not load the home page, so the checks that judge what a visitor sees "
                          f"read the page as delivered instead: {render_failure}")
    page, link_failure = _verify_links(page)
    if link_failure:
        incomplete.append(f"The links on the home page could not be verified: {link_failure}")
    page, icon_failure = _fetch_favicon(page)
    if icon_failure:
        incomplete.append(f"The site's icon could not be checked: {icon_failure}")
    detected = platform.detect(page) if isinstance(page, PageContext) else None
    ext = _fetch_external(domain, page)
    if isinstance(page, PageContext) and not ext.psi_mobile:
        why = ext.errors.get("psi_mobile") or ("PAGESPEED_API_KEY is not set" if not ext.pagespeed_configured
                                               else "no run succeeded")
        incomplete.append(f"Google's speed test did not run: {why}")
    results: list[CheckResult] = []
    for category, name, check in _checks_for(domain, now, page, ext):
        try:
            results.extend(check())
        except Exception as exc:  # one failing lookup should not sink the whole report
            incomplete.append(f"{name} could not be completed: {type(exc).__name__}: {exc}")
            results.append(CheckResult(
                category, name, Status.WARN,
                "This check could not be completed, so the result is unknown.",
                "A lookup failed or timed out while running this check.",
                "There is nothing for you to do unless the error below names something you recognize; if it does, "
                "ask your IT provider to look at it.",
                [f"Error: {type(exc).__name__}: {exc}"],
                ran=False,
            ))
    return DomainReport(domain.name, now, results, website_loaded=isinstance(page, PageContext),
                        unreachable=_unreachable(page), rendered=isinstance(page, PageContext) and page.rendered,
                        incomplete=incomplete, platform=detected.name if detected else "",
                        platform_evidence=detected.evidence if detected else "")


def _fetch_page(domain: str) -> PageContext | FetchError:
    """Load the home page once for every check that needs it. A failure is handed to those
    checks to report as a WARN, never raised."""
    try:
        return fetcher.fetch_page(domain)
    except FetchError as exc:
        return exc
    except Exception as exc:  # same rule as the checks: one failure should not sink the report
        return FetchError(f"https://{domain}/", f"{type(exc).__name__}: {exc}")


def _render_in_browser(page: PageContext | FetchError) -> tuple[PageContext | FetchError, str]:
    """Every report reads the page a second time, in a real browser, so the checks an owner verifies by looking
    at their own screen (main heading, heading order, image descriptions, structured data against the page)
    are judged on what that screen shows. Whether the delivered page is an empty shell is decided first, on
    what the server sent. When the browser fails the delivered page stands, and those checks say they read
    the page as delivered rather than claiming what is visible."""
    if not isinstance(page, PageContext):
        return page, ""
    page = replace(page, script_built=site.built_by_scripts(page))
    try:
        return fetcher.render(page), ""
    except Exception as exc:  # no browser, or it could not load the page: say so, never guess
        return page, f"{type(exc).__name__}: {exc}"


def _verify_links(page: PageContext | FetchError) -> tuple[PageContext | FetchError, str]:
    """The links on the consented page, each verified once under the cap in CLAUDE.md (linkcheck.py)."""
    if not isinstance(page, PageContext):
        return page, ""
    try:
        return replace(page, links=linkcheck.verify(page)), ""
    except Exception as exc:  # the check then says it did not run; the report is marked incomplete
        return page, f"{type(exc).__name__}: {exc}"


def _fetch_favicon(page: PageContext | FetchError) -> tuple[PageContext | FetchError, str]:
    """The site's icon, resolved the way a browser does, in at most two requests (fetcher.fetch_favicon)."""
    if not isinstance(page, PageContext):
        return page, ""
    try:
        return replace(page, favicon=fetcher.fetch_favicon(page)), ""
    except Exception as exc:
        return page, f"{type(exc).__name__}: {exc}"


def _fetch_external(domain: DomainConfig | str, page: PageContext | FetchError) -> ExternalContext:
    """Outside services, once per report. We never ask Google to load a page we could not, or were asked
    not to, load ourselves. Like the page fetch, a failure here is reported by the checks, never raised."""
    if isinstance(page, RobotsDisallowed):
        url, skipped = None, "not run, because robots.txt asks us not to load the home page"
    elif isinstance(page, FetchError):
        url, skipped = None, f"not run, because we could not load the home page ({page.reason})"
    else:
        url, skipped = page.final_url, ""
    if isinstance(domain, str):
        domain = DomainConfig(domain)
    business = Business(domain.business_name, domain.city, domain.phone) if domain.business_name else None
    try:
        return external.fetch_external(domain.name, url, skipped, business=business)
    except Exception as exc:  # same rule as the checks: one failure should not sink the report
        return ExternalContext(errors={"psi_mobile": f"{type(exc).__name__}"})


def _domain_exists(domain: str) -> bool | None:
    try:
        return dns_utils.domain_exists(domain)
    except Exception:  # unknown: carry on and let the individual checks report what they find
        return None


def _unregistered(domain: str, now: datetime) -> DomainReport:
    """NXDOMAIN: one fact, so one finding. Every DNS, mail and website check would only restate it (no
    nameservers, no MX, no SPF, no DKIM, no DMARC, no DNSSEC, no website), so none of them is emitted."""
    finding = CheckResult(
        DOMAIN, "Domain registration", Status.FAIL,
        "This domain is not registered, or the registration has lapsed.",
        "When a domain does not exist in DNS, nobody can reach a website at it and email sent to it cannot be "
        "delivered.",
        "If you still own this domain, check with your registrar that it is renewed and pointed at your DNS "
        "provider. If it has lapsed, renew it quickly, before someone else can register it.",
        [f"DNS answered NXDOMAIN (no such domain) for {domain}"],
    )
    rest = CheckResult(
        DOMAIN, "Website, DNS and email checks", Status.WARN,
        "We did not run the website, DNS or email checks, because the domain does not exist in DNS.",
        "Every one of them depends on the domain resolving, so each would only repeat the finding above.",
        "Nothing to do until the domain resolves again.",
        ["Not checked: nameservers, DNSSEC, mail servers (MX), SPF, DKIM, DMARC, SSL certificate, the website"],
        ran=False,
    )
    return DomainReport(domain, now, [finding, rest], website_loaded=False,
                        unreachable=f"{domain} does not exist in DNS, so nobody can reach a website at it or send it "
                                    "email.")


def _unreachable(page: PageContext | FetchError) -> str:
    """Why a visitor cannot reach the site, or "" when they can, or when only we were turned away (a 403 or 429
    usually blocks automated checks, not people) or we stopped at robots.txt by choice."""
    if isinstance(page, PageContext) or isinstance(page, RobotsDisallowed):
        return ""
    if isinstance(page, PageStatusError):
        if page.stage == "robots":
            return ""
        if page.status in (404, 410):
            return (f"Your home page at {page.where} answers \"not found\" (status {page.status}), so visitors who "
                    "type your address see an error page.")
        if page.status >= 500:
            return (f"Your home page at {page.where} answers with a server error (status {page.status}, "
                    f"{status_phrase(page.status).lower()}), so visitors see an error instead of your site.")
        return ""
    return (f"We could not reach your website at {page.url} at all ({page.reason}). If your visitors cannot either, "
            "nobody can see your site right now.")
