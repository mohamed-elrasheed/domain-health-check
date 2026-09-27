"""Nameserver (NS) and mail server (MX) records.

  * NS records name the servers that answer every DNS question about the
    domain. If they all go down, the website and email disappear with them,
    so there should be at least two.
  * MX records name the servers that receive email for the domain, each with
    a priority number (lower = tried first). A domain that never receives
    email can publish a "null MX" (priority 0, host ".") to say so.
"""

from __future__ import annotations

from .. import dns_utils
from ..models import DOMAIN, EMAIL, CheckResult, Status

NS_EXPLANATION = (
    "Nameservers are the directory servers that tell the internet where your website and email live. "
    "Having at least two means one can fail without taking everything offline."
)
MX_EXPLANATION = (
    "MX records tell other mail systems where to deliver email addressed to your domain. Without them, "
    "email sent to you bounces."
)


def check_nameservers(domain: str) -> list[CheckResult]:
    servers = sorted(ns.rstrip(".") for ns in dns_utils.lookup(domain, "NS"))
    details = [f"Nameserver: {ns}" for ns in servers]
    if not servers:
        return [CheckResult(
            DOMAIN, "Nameservers", Status.FAIL, "No nameservers were found for this domain.", NS_EXPLANATION,
            "Check with your registrar that the domain is active and points to your DNS provider's nameservers.",
        )]
    if len(servers) == 1:
        return [CheckResult(
            DOMAIN, "Nameservers", Status.WARN, "Only one nameserver is listed.", NS_EXPLANATION,
            "Ask your DNS provider for a second nameserver and add it at your registrar.", details,
        )]
    return [CheckResult(
        DOMAIN, "Nameservers", Status.PASS, f"{len(servers)} nameservers are listed.", NS_EXPLANATION,
        details=details,
    )]


def check_mx(domain: str) -> list[CheckResult]:
    records = []
    for record in dns_utils.lookup(domain, "MX"):
        priority, host = record.split(maxsplit=1)
        records.append((int(priority), host))
    records.sort()

    if records == [(0, ".")]:
        return [CheckResult(
            EMAIL, "Mail servers (MX)", Status.PASS,
            "The domain openly declares that it doesn't receive email (a \"null MX\" record).",
            MX_EXPLANATION, details=["MX: 0 ."],
        )]
    if not records:
        return [CheckResult(
            EMAIL, "Mail servers (MX)", Status.WARN, "No mail servers are listed, so email to this domain will bounce.",
            MX_EXPLANATION,
            "If you use email on this domain, add the MX records your email provider gives you. If you "
            "don't, add a \"null MX\" record (priority 0, host \".\") so senders know straight away.",
        )]
    details = [f"Priority {priority}: {host.rstrip('.')}" for priority, host in records]
    return [CheckResult(
        EMAIL, "Mail servers (MX)", Status.PASS, f"{len(records)} mail server(s) are listed.", MX_EXPLANATION,
        details=details,
    )]
