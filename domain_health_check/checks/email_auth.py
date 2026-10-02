"""Email authentication: SPF, DKIM and DMARC.

Email was designed with no proof of who sent a message, so anyone can put
"From: ceo@example.com" on an email. These three DNS records let a domain owner
publish rules that receiving mail systems (Gmail, Outlook...) check:

  * SPF (Sender Policy Framework), a TXT record on the domain itself, starting
    "v=spf1". It lists the servers allowed to send mail for the domain and ends
    with an "all" rule saying what to do with everything else:
      -all  hard fail: reject mail from anyone not listed (strictest)
      ~all  soft fail: accept but mark as suspicious
      ?all  neutral: no opinion (nearly useless)
      +all  pass everything: anyone in the world may send as you (dangerous)
    A domain must have exactly ONE SPF record; two or more break it.

  * DKIM (DomainKeys Identified Mail). The sending server signs each message
    with a private key, and publishes the matching public key in DNS at
    <selector>._domainkey.<domain>. The "selector" is just a label chosen by
    the email provider (Google uses "google", Microsoft 365 "selector1" and
    "selector2", Fastmail "fm1".."fm3"), so it can't be discovered; you have
    to know it. That's why selectors are configured per domain.

  * DMARC (Domain-based Message Authentication, Reporting and Conformance), a
    TXT record at _dmarc.<domain>. It ties SPF and DKIM together and tells
    receivers what to do when a message fails both:
      p=none        do nothing, just send me reports (monitoring only)
      p=quarantine  send it to spam
      p=reject      refuse it outright
"""

from __future__ import annotations

from .. import dns_utils
from ..models import EMAIL, CheckResult, Status

DEFAULT_DKIM_SELECTORS = ["google", "fm1", "fm2", "fm3", "selector1", "selector2"]

SPF_EXPLANATION = (
    "SPF is a published list of the servers allowed to send email from your domain. Receiving mail systems "
    "use it to spot forged emails that pretend to come from you."
)
DKIM_EXPLANATION = (
    "DKIM adds a tamper-proof digital signature to every email you send. Receivers check the signature "
    "against a key published in your DNS to confirm the message really came from you and wasn't altered."
)
DMARC_EXPLANATION = (
    "DMARC tells other mail systems what to do with emails that claim to be from you but fail the SPF and "
    "DKIM checks: deliver, send to spam, or reject. Without an enforcing policy, scammers can send emails "
    "that appear to come from your domain."
)


def parse_tags(record: str) -> dict[str, str]:
    """Parse 'v=DMARC1; p=reject; rua=mailto:x' into {'v': 'DMARC1', 'p': 'reject', ...}."""
    tags = {}
    for part in record.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            tags[key.strip().lower()] = value.strip()
    return tags


# --- SPF ---------------------------------------------------------------------

def _is_spf(record: str) -> bool:
    lowered = record.strip().lower()
    return lowered == "v=spf1" or lowered.startswith("v=spf1 ")


def _all_qualifier(record: str) -> str | None:
    """Return '+', '-', '~' or '?' for the record's 'all' mechanism, or None if there isn't one."""
    for term in record.split()[1:]:
        term = term.lower()
        if term in ("all", "+all"):
            return "+"
        if term in ("-all", "~all", "?all"):
            return term[0]
    return None


def evaluate_spf(txt_records: list[str]) -> CheckResult:
    spf = [r for r in txt_records if _is_spf(r)]
    details = [f"SPF record: {r}" for r in spf]

    def result(status: Status, summary: str, fix: str = "") -> CheckResult:
        return CheckResult(EMAIL, "SPF (approved senders)", status, summary, SPF_EXPLANATION, fix, details)

    if not spf:
        return result(
            Status.WARN, "No SPF record was found.",
            "Add a TXT record to your domain listing your email provider, ending in -all or ~all. Your email "
            "provider's help pages give the exact text (for Google Workspace: "
            "`v=spf1 include:_spf.google.com ~all`).",
        )
    if len(spf) > 1:
        return result(
            Status.WARN, f"There are {len(spf)} SPF records; only one is allowed, so all of them are ignored.",
            "Merge them into a single SPF record that includes every service that sends email for you.",
        )

    record = spf[0]
    qualifier = _all_qualifier(record)
    if qualifier == "+":
        return result(
            Status.WARN, "The SPF record allows ANY server in the world to send email as you (+all).",
            "Change `+all` (or a bare `all`) at the end of the SPF record to `-all` or `~all`.",
        )
    if qualifier == "-":
        return result(Status.PASS, "SPF is set up and rejects email from unlisted servers (-all).")
    if qualifier == "~":
        return result(Status.PASS, "SPF is set up and flags email from unlisted servers as suspicious (~all).")
    if qualifier == "?":
        return result(
            Status.WARN, "SPF is present but takes no position on unlisted servers (?all), so it offers little protection.",
            "Change `?all` at the end of the SPF record to `~all` or `-all`.",
        )
    if "redirect=" in record.lower():
        return result(Status.PASS, "SPF is set up and points to another domain's SPF policy (redirect).")
    return result(
        Status.WARN, "The SPF record doesn't end with an 'all' rule, so unlisted servers aren't blocked.",
        "Add `~all` or `-all` to the end of the SPF record.",
    )


def check_spf(domain: str) -> list[CheckResult]:
    return [evaluate_spf(dns_utils.lookup_txt(domain))]


# --- DMARC -------------------------------------------------------------------

def evaluate_dmarc(txt_records: list[str]) -> CheckResult:
    dmarc = [r for r in txt_records if r.strip().lower().startswith("v=dmarc1")]
    details = [f"DMARC record: {r}" for r in dmarc]

    def result(status: Status, summary: str, fix: str = "") -> CheckResult:
        return CheckResult(EMAIL, "DMARC (anti-spoofing policy)", status, summary, DMARC_EXPLANATION, fix, details)

    start_fix = (
        "Add a TXT record at _dmarc.<your domain> such as `v=DMARC1; p=none; rua=mailto:dmarc@<your domain>`, "
        "review the reports for a few weeks, then tighten the policy to p=quarantine and finally p=reject."
    )
    if not dmarc:
        return result(Status.WARN, "No DMARC record was found.", start_fix)
    if len(dmarc) > 1:
        return result(
            Status.WARN, f"There are {len(dmarc)} DMARC records; only one is allowed, so receivers ignore them.",
            "Delete the extra records so exactly one DMARC record remains.",
        )

    tags = parse_tags(dmarc[0])
    policy = tags.get("p", "").lower()
    if "rua" not in tags:
        details.append("No 'rua' address is set, so you won't receive reports about who is sending as you.")
    pct = tags.get("pct")
    if pct and pct.isdigit() and int(pct) < 100:
        details.append(f"The policy only applies to {pct}% of failing messages (pct={pct}).")

    if policy == "none":
        return result(
            Status.WARN, "DMARC is in monitoring-only mode (p=none): forged emails are still delivered.",
            "Once the DMARC reports show all your genuine email passing, change the policy to "
            "`p=quarantine`, then later `p=reject`.",
        )
    if policy == "quarantine":
        return result(Status.PASS, "DMARC sends forged emails to spam (p=quarantine).")
    if policy == "reject":
        return result(Status.PASS, "DMARC tells receivers to reject forged emails (p=reject), the strongest setting.")
    return result(Status.WARN, "The DMARC record has a missing or invalid policy (p=), so it is ignored.", start_fix)


def check_dmarc(domain: str) -> list[CheckResult]:
    return [evaluate_dmarc(dns_utils.lookup_txt(f"_dmarc.{domain}"))]


# --- DKIM --------------------------------------------------------------------

def check_dkim(domain: str, selectors: list[str] | None = None) -> list[CheckResult]:
    configured = bool(selectors)
    selectors = selectors or DEFAULT_DKIM_SELECTORS
    found, revoked = [], []
    for selector in selectors:
        for record in dns_utils.lookup_txt(f"{selector}._domainkey.{domain}"):
            tags = parse_tags(record)
            if "p" in tags:
                # An empty p= means the key has been deliberately revoked.
                (found if tags["p"] else revoked).append(selector)
                break

    details = [f"Selector checked: {s}" for s in selectors]
    details += [f"DKIM key found: {s}._domainkey.{domain}" for s in found]
    details += [f"Revoked (empty) key: {s}._domainkey.{domain}" for s in revoked]

    def result(status: Status, summary: str, fix: str = "") -> list[CheckResult]:
        return [CheckResult(EMAIL, "DKIM (email signatures)", status, summary, DKIM_EXPLANATION, fix, details)]

    setup_fix = (
        "Turn on DKIM signing in your email provider's admin console (e.g. Google Workspace or Microsoft 365) "
        "and publish the DNS record it gives you."
    )
    if found:
        return result(Status.PASS, f"DKIM signing keys are published (selector: {', '.join(found)}).")
    if revoked:
        return result(
            Status.WARN, "Only revoked DKIM keys were found, so emails can't be verified with them.",
            setup_fix,
        )
    if configured:
        return result(
            Status.WARN, f"No DKIM key was found for the configured selector(s): {', '.join(selectors)}.",
            setup_fix,
        )
    return result(
        Status.WARN,
        "No DKIM key was found under the common selector names. DKIM may still be set up under a different name.",
        "Ask your email provider whether DKIM signing is switched on and which selector name it uses. If it is "
        "not set up yet: " + setup_fix[0].lower() + setup_fix[1:],
    )
