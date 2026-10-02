"""Domain registration expiry via RDAP.

A domain name is rented, not owned: it's registered for a period (usually one
year at a time) through a registrar such as GoDaddy or Namecheap. If the
renewal is missed, the website and email stop working, and the name can
eventually be bought by someone else.

RDAP (Registration Data Access Protocol) is the modern replacement for WHOIS.
Each registry (the organisation running a TLD such as .com or .org) publishes
registration data as JSON over HTTPS. IANA keeps a public "bootstrap" file that
says which RDAP server is responsible for which TLD, so we:
  1. download IANA's bootstrap file (once per run),
  2. find the server for this domain's TLD,
  3. ask that server for the domain's record and read its "expiration" event.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from functools import lru_cache

from ..fetcher import USER_AGENT
from ..models import DOMAIN, CheckResult, Status

BOOTSTRAP_URL = "https://data.iana.org/rdap/dns.json"
TIMEOUT_SECONDS = 15

# Losing a domain is far worse than a lapsed certificate, so warn earlier.
WARN_DAYS = 60
FAIL_DAYS = 30  # inside a month the renewal is no longer a risk, it is about to break

NAME = "Domain registration"
EXPLANATION = (
    "Your domain name is rented from a registrar and has to be renewed, usually every year. If the renewal "
    "is missed, your website and email stop working, and someone else could register the name."
)
RENEW_FIX = "Renew the domain with your registrar now, and switch on auto-renew with a payment card that won't expire."


class RDAPUnavailable(Exception):
    """The registry for this TLD doesn't offer RDAP."""


def _get_json(url: str) -> dict:
    request = urllib.request.Request(
        url, headers={"Accept": "application/rdap+json, application/json", "User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        return json.load(response)


@lru_cache(maxsize=1)
def _load_bootstrap() -> dict:
    return _get_json(BOOTSTRAP_URL)


def find_rdap_server(domain: str, bootstrap: dict) -> str | None:
    """Return the RDAP base URL for the domain's TLD (longest matching suffix wins)."""
    labels = domain.lower().split(".")
    for i in range(1, len(labels)):
        suffix = ".".join(labels[i:])
        for tlds, urls in bootstrap.get("services", []):
            if suffix in tlds and urls:
                https = [u for u in urls if u.startswith("https://")]
                return (https or urls)[0]
    return None


def fetch_rdap(domain: str) -> dict:
    base = find_rdap_server(domain, _load_bootstrap())
    if base is None:
        raise RDAPUnavailable(f"No RDAP service is listed for .{domain.rsplit('.', 1)[-1]}")
    if not base.endswith("/"):
        base += "/"
    return _get_json(f"{base}domain/{domain}")


def _parse_date(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _registrar_name(data: dict) -> str | None:
    for entity in data.get("entities", []):
        if "registrar" in entity.get("roles", []):
            try:
                # vCard in JSON form: ["vcard", [["fn", {}, "text", "Registrar Name"], ...]]
                for prop in entity["vcardArray"][1]:
                    if prop[0] == "fn":
                        return prop[3]
            except (KeyError, IndexError, TypeError):
                pass
    return None


def evaluate_registration(data: dict, now: datetime) -> CheckResult:
    expiry = None
    for event in data.get("events", []):
        if event.get("eventAction") == "expiration" and event.get("eventDate"):
            expiry = _parse_date(event["eventDate"])

    registrar = _registrar_name(data)
    details = [f"Registrar: {registrar}"] if registrar else []

    if expiry is None:
        return CheckResult(
            DOMAIN, NAME, Status.WARN,
            "The registry doesn't publish an expiry date for this domain.",
            EXPLANATION,
            "Log in to your registrar's control panel to confirm the renewal date and that auto-renew is on.",
            details,
        )

    days_left = (expiry - now).days
    details.append(f"Expires: {expiry:%d %B %Y}")
    if days_left < FAIL_DAYS:
        summary = (f"The domain registration expired {-days_left} days ago." if days_left < 0
                   else f"The domain registration expires in {days_left} days.")
        return CheckResult(DOMAIN, NAME, Status.FAIL, summary, EXPLANATION, RENEW_FIX, details)
    if days_left < WARN_DAYS:
        return CheckResult(
            DOMAIN, NAME, Status.WARN, f"The domain registration expires in {days_left} days.", EXPLANATION,
            "Check with your registrar that auto-renew is on and the payment details are current.", details,
        )
    return CheckResult(
        DOMAIN, NAME, Status.PASS, f"Registered until {expiry:%d %B %Y} ({days_left} days from now).",
        EXPLANATION, details=details,
    )


def check_registration(domain: str, now: datetime | None = None) -> list[CheckResult]:
    now = now or datetime.now(timezone.utc)
    unknown_fix = "Log in to your registrar's control panel to confirm the renewal date and that auto-renew is on."
    try:
        data = fetch_rdap(domain)
    except urllib.error.HTTPError as exc:
        summary = ("The registry has no record of this domain." if exc.code == 404
                   else "The registry's lookup service returned an error.")
        return [CheckResult(DOMAIN, NAME, Status.WARN, summary, EXPLANATION, unknown_fix, [f"HTTP {exc.code}"])]
    except RDAPUnavailable as exc:
        return [CheckResult(
            DOMAIN, NAME, Status.WARN, "This domain's registry doesn't offer an automated lookup.",
            EXPLANATION, unknown_fix, [str(exc)],
        )]
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [CheckResult(
            DOMAIN, NAME, Status.WARN, "We couldn't reach the registry to check the expiry date.",
            EXPLANATION, unknown_fix, [f"Error: {getattr(exc, 'reason', exc)}"],
        )]
    return [evaluate_registration(data, now)]
