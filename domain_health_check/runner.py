"""Runs every check for one domain and collects the results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from . import fetcher
from .checks import dns_records, dnssec, email_auth, http_headers, rdap, tls
from .config import DomainConfig
from .fetcher import FetchError, PageContext
from .models import DOMAIN, EMAIL, WEBSITE, CheckResult, DomainReport, Status


def _checks_for(
    domain: DomainConfig, now: datetime, page: PageContext | FetchError,
) -> list[tuple[str, str, Callable[[], list[CheckResult]]]]:
    """(category, name, zero-argument function) in the order they appear in the report."""
    d = domain.name
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
    ]


def run_checks(domain: DomainConfig, now: datetime | None = None) -> DomainReport:
    now = now or datetime.now(timezone.utc)
    page = _fetch_page(domain.name)
    results: list[CheckResult] = []
    for category, name, check in _checks_for(domain, now, page):
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
