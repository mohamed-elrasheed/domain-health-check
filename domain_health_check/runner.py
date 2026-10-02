"""Runs every check for one domain and collects the results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from . import external, fetcher
from .checks import business_profile, dns_records, dnssec, email_auth, http_headers, pagespeed, rdap, site, tls
from .checks.site import content, delivery, indexing, sharing, structured_data
from .config import DomainConfig
from .external import Business, ExternalContext
from .fetcher import FetchError, PageContext, RobotsDisallowed
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
        """Content checks also need text to read. When scripts build it, check_page_rendered says so once."""
        return lambda: check(page) if isinstance(page, PageContext) and not site.built_by_scripts(page) else []

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
    now = now or datetime.now(timezone.utc)
    page = _fetch_page(domain.name)
    ext = _fetch_external(domain, page)
    results: list[CheckResult] = []
    for category, name, check in _checks_for(domain, now, page, ext):
        try:
            results.extend(check())
        except Exception as exc:  # one failing lookup shouldn't sink the whole report
            results.append(CheckResult(
                category, name, Status.WARN,
                "This check couldn't be completed, so the result is unknown.",
                "A lookup failed or timed out while running this check.",
                "Run the check again later. If it keeps failing, ask your IT provider to look at the error below.",
                [f"Error: {type(exc).__name__}: {exc}"],
                ran=False,
            ))
    return DomainReport(domain.name, now, results)


def _fetch_page(domain: str) -> PageContext | FetchError:
    """Load the home page once for every check that needs it. A failure is handed to those
    checks to report as a WARN, never raised."""
    try:
        return fetcher.fetch_page(domain)
    except FetchError as exc:
        return exc
    except Exception as exc:  # same rule as the checks: one failure shouldn't sink the report
        return FetchError(f"https://{domain}/", f"{type(exc).__name__}: {exc}")


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
    except Exception as exc:  # same rule as the checks: one failure shouldn't sink the report
        return ExternalContext(errors={"psi_mobile": f"{type(exc).__name__}"})
