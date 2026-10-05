"""DNSSEC: is the domain's DNS cryptographically signed?

Ordinary DNS answers are not signed, so an attacker who can tamper with them
(for example on a compromised network) can send visitors to a fake server.
DNSSEC adds digital signatures to DNS answers.

The chain of trust runs downwards: the root zone vouches for .com, and .com
vouches for example.com by publishing a DS ("Delegation Signer") record, which
is a fingerprint of example.com's signing key. If there's no DS record in the
parent zone, DNSSEC is not switched on for the domain, whatever the domain's own
DNS provider does. That DS record is what we look for.

A DS record shows DNSSEC is switched on; it does not prove every signature
underneath is valid. That would need a validating resolver, which is beyond
this tool's scope.
"""

from __future__ import annotations

from .. import dns_utils
from ..models import DOMAIN, CheckResult, Status

ALGORITHMS = {8: "RSA/SHA-256", 10: "RSA/SHA-512", 13: "ECDSA P-256", 14: "ECDSA P-384", 15: "Ed25519"}

EXPLANATION = (
    "DNSSEC adds a digital signature to your domain's DNS records, so visitors cannot be secretly "
    "redirected to a fake website or mail server by someone tampering with DNS answers."
)


def check_dnssec(domain: str) -> list[CheckResult]:
    records = dns_utils.lookup(domain, "DS")
    if not records:
        return [CheckResult(
            DOMAIN, "DNSSEC", Status.WARN, "DNSSEC is not switched on for this domain.", EXPLANATION,
            "Ask your DNS provider to enable DNSSEC signing, then add the DS record they give you at your "
            "registrar (many providers, such as Cloudflare, do both in a few clicks).",
        )]
    details = []
    for record in records:
        key_tag, algorithm, *_ = record.split()
        name = ALGORITHMS.get(int(algorithm), f"algorithm {algorithm}")
        details.append(f"DS record: key tag {key_tag}, {name}")
    return [CheckResult(DOMAIN, "DNSSEC", Status.PASS, "DNSSEC is switched on for this domain.", EXPLANATION, details=details)]
