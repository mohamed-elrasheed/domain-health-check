"""SSL/TLS: is the website's certificate valid, and how modern is the connection?

TLS (Transport Layer Security, the successor to SSL) is what puts the "S" in
HTTPS. It does two jobs:
  * Encryption: nobody between the visitor and the server can read the traffic.
  * Identity: the server presents a certificate, signed by a trusted
    certificate authority (the "issuer"), proving it really is example.com.

A certificate is only valid for the names written on it (hostname match) and
only until its expiry date. We open one ordinary HTTPS connection, exactly as a
browser would, and read the certificate the server hands over. Nothing else.
"""

from __future__ import annotations

import socket
import ssl
from datetime import datetime, timezone

from ..models import WEBSITE, CheckResult, Status

WARN_DAYS = 30
# Every certificate error a browser shows as a full-page security warning is a FAIL: the test is whether a visitor
# can get in without clicking past a warning, and they cannot. Summaries by OpenSSL verify code; any other
# verification failure gets the general one.
CERT_SUMMARY = {
    9: "The certificate is not valid yet, so browsers block the website with a security warning.",
    10: "The certificate has expired, so browsers block the website with a security warning.",
    18: "The certificate is self-signed, so browsers block the website with a security warning.",
    19: "The certificate is signed by an authority browsers do not trust, so they block the website with a "
        "security warning.",
    62: "The certificate is for a different domain name, so browsers block the website with a security warning.",
}
UNTRUSTED = "Browsers do not trust this website's certificate, so they block it with a security warning."
MISSING_INTERMEDIATE = 20  # also what a server that forgot its intermediate certificate looks like
TIMEOUT_SECONDS = 10

CERT_EXPLANATION = (
    "The SSL certificate proves to visitors' browsers that they are talking to your real website, "
    "and encrypts everything sent between them. If it expires or doesn't match your domain, browsers "
    "show a full-page security warning and most visitors will leave."
)
CERT_FIX = (
    "Ask your web host or IT provider to install a valid certificate that covers this domain, "
    "and to turn on automatic renewal (free certificates from Let's Encrypt renew themselves)."
)
VERSION_EXPLANATION = (
    "TLS is the technology that encrypts the connection to your website. Newer versions (1.2 and 1.3) "
    "are secure; older ones (1.0 and 1.1) have known weaknesses and are rejected by modern browsers. "
    "This check shows the best version your server offered us."
)


def fetch_tls_info(domain: str) -> tuple[dict, str | None]:
    """Make one normal HTTPS handshake and return (certificate, tls_version).

    create_default_context() checks the certificate chain AND that the
    certificate matches the hostname, raising SSLCertVerificationError if not.
    """
    context = ssl.create_default_context()
    with socket.create_connection((domain, 443), timeout=TIMEOUT_SECONDS) as sock:
        with context.wrap_socket(sock, server_hostname=domain) as tls:
            return tls.getpeercert(), tls.version()


def _issuer_name(cert: dict) -> str:
    # The issuer is a tuple of "relative distinguished names", each a tuple of (key, value) pairs.
    issuer = dict(pair for rdn in cert.get("issuer", ()) for pair in rdn)
    return issuer.get("organizationName") or issuer.get("commonName") or "an unknown issuer"


def evaluate_certificate(cert: dict, now: datetime) -> CheckResult:
    expires = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)
    days_left = (expires - now).days
    issuer = _issuer_name(cert)
    details = [
        f"Issued by: {issuer}",
        f"Expires: {expires:%d %B %Y}",
        "Certificate matches the domain name: yes",
    ]

    def result(status: Status, summary: str, fix: str = "") -> CheckResult:
        return CheckResult(WEBSITE, "SSL certificate", status, summary, CERT_EXPLANATION, fix, details)

    if days_left < 0:  # broken: browsers show a full-page warning
        return result(Status.FAIL, f"The certificate expired {-days_left} days ago.", CERT_FIX)
    if days_left < WARN_DAYS:  # not broken yet, however close
        return result(
            Status.WARN,
            f"The certificate expires in {days_left} days.",
            "Confirm with your web host that the certificate will renew automatically before "
            f"{expires:%d %B %Y}. If it doesn't, renew it manually.",
        )
    return result(Status.PASS, f"Valid for another {days_left} days, issued by {issuer}.")


def evaluate_tls_version(version: str | None) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "") -> CheckResult:
        details = [f"Negotiated protocol: {version or 'unknown'}"]
        return CheckResult(WEBSITE, "TLS version", status, summary, VERSION_EXPLANATION, fix, details)

    if version == "TLSv1.3":
        return result(Status.PASS, "Uses TLS 1.3, the newest and most secure version.")
    if version == "TLSv1.2":
        return result(Status.PASS, "Uses TLS 1.2, which is still considered secure.")
    return result(
        Status.WARN,
        f"Uses an outdated protocol ({version or 'unknown'}).",
        "Ask your web host to enable TLS 1.2 and 1.3 and switch off TLS 1.0 and 1.1.",
    )


def check_tls(domain: str, now: datetime | None = None) -> list[CheckResult]:
    now = now or datetime.now(timezone.utc)
    try:
        cert, version = fetch_tls_info(domain)
    except ssl.SSLCertVerificationError as exc:
        reason = getattr(exc, "verify_message", None) or str(exc)
        code = getattr(exc, "verify_code", None)
        details = [f"Reason given: {reason}"]
        if code == MISSING_INTERMEDIATE:
            details.append("This can also mean the server is not sending its intermediate certificate. Some browsers "
                           "repair that on their own, many do not, so visitors see the warning.")
        return [CheckResult(
            WEBSITE, "SSL certificate", Status.FAIL, CERT_SUMMARY.get(code, UNTRUSTED),
            CERT_EXPLANATION, CERT_FIX, details,
        )]
    except ssl.SSLError as exc:
        return [CheckResult(
            WEBSITE, "SSL certificate", Status.WARN,
            "A secure (HTTPS) connection could not be set up.",
            CERT_EXPLANATION,
            "Ask your web host to check the HTTPS configuration; the server may only offer outdated "
            "encryption that modern software refuses to use.",
            [f"TLS error: {exc}"],
        )]
    except OSError as exc:
        # Includes timeouts and "connection refused". Some domains simply don't host a website.
        return [CheckResult(
            WEBSITE, "SSL certificate", Status.WARN,
            f"We couldn't connect to https://{domain}.",
            CERT_EXPLANATION,
            "If this domain is meant to have a website, ask your web host why it isn't reachable over "
            "HTTPS. If it's only used for email, you can ignore this.",
            [f"Connection error: {exc}"],
        )]
    return [evaluate_certificate(cert, now), evaluate_tls_version(version)]
