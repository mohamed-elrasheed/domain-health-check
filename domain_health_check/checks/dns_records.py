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
            DOMAIN, "Nameservers", Status.WARN, "No nameservers were found for this domain.", NS_EXPLANATION,
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
            "The domain openly declares that it does not receive email (a \"null MX\" record).",
            MX_EXPLANATION, details=["MX: 0 ."],
        )]
    if not records:
        return [evaluate_missing_mx(*_mail_records(domain))]
    details = [f"Priority {priority}: {host.rstrip('.')}" for priority, host in records]
    return [CheckResult(
        EMAIL, "Mail servers (MX)", Status.PASS,
        f"{len(records)} mail servers are listed." if len(records) != 1 else "1 mail server is listed.", MX_EXPLANATION,
        details=details,
    )]


def _mail_records(domain: str) -> tuple[bool, bool]:
    """(has SPF, has DMARC). Only asked when there are no mail servers."""
    spf = any(r.strip().lower().startswith("v=spf1") for r in dns_utils.lookup_txt(domain))
    dmarc = any(r.strip().lower().startswith("v=dmarc1") for r in dns_utils.lookup_txt(f"_dmarc.{domain}"))
    return spf, dmarc


def evaluate_missing_mx(has_spf: bool, has_dmarc: bool) -> CheckResult:
    """No MX, no SPF and no DMARC is the normal signature of a domain never set up for email: a fact, not a
    problem, so it is informational and not scored. No MX beside SPF or DMARC means mail was set up, at least
    in part, and now has nowhere to go: something lapsed or was half-built, and email to it bounces."""
    if not has_spf and not has_dmarc:  # checked and fine: a fact to state, not a grade
        return CheckResult(
            EMAIL, "Mail servers (MX)", Status.INFO,
            "This domain is not set up for email, which is normal if you use a different address for mail.",
            MX_EXPLANATION, "", ["No MX, SPF or DMARC records"],
        )
    present = " and ".join(name for name, found in (("SPF", has_spf), ("DMARC", has_dmarc)) if found)
    return CheckResult(
        EMAIL, "Mail servers (MX)", Status.FAIL,
        f"No mail servers are listed, so email to this domain will bounce, even though it has {present} set up.",
        MX_EXPLANATION,
        "Ask your email provider for the mail server records for this domain, and ask whoever manages your domain to "
        "add them. If you have stopped using email here, ask them to publish a record saying the domain receives no "
        "email, so senders know straight away.",
        [f"No MX records; {present} present, which suggests email setup has lapsed or was never finished",
         "To say the domain receives no email: a null MX record, priority 0, host \".\""],
    )
