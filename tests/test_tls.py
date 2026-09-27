import ssl
from datetime import datetime, timedelta, timezone

import pytest

from domain_health_check.checks import tls
from domain_health_check.models import Status

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def cert_expiring_in(days: int) -> dict:
    expires = NOW + timedelta(days=days, hours=1)
    return {
        "notAfter": expires.strftime("%b %d %H:%M:%S %Y GMT"),
        "issuer": ((("countryName", "US"),), (("organizationName", "Example CA"),), (("commonName", "R1"),)),
    }


@pytest.mark.parametrize("days, expected", [
    (90, Status.PASS),
    (30, Status.PASS),
    (29, Status.WARN),
    (7, Status.WARN),
    (6, Status.FAIL),
    (-3, Status.FAIL),
])
def test_certificate_expiry_thresholds(days, expected):
    result = tls.evaluate_certificate(cert_expiring_in(days), NOW)
    assert result.status is expected
    assert result.fix or expected is Status.PASS


def test_certificate_reports_issuer():
    result = tls.evaluate_certificate(cert_expiring_in(90), NOW)
    assert "Example CA" in result.summary
    assert "Issued by: Example CA" in result.details


@pytest.mark.parametrize("version, expected", [
    ("TLSv1.3", Status.PASS), ("TLSv1.2", Status.PASS), ("TLSv1.1", Status.FAIL), (None, Status.FAIL),
])
def test_tls_version(version, expected):
    assert tls.evaluate_tls_version(version).status is expected


def test_check_tls_success(monkeypatch):
    monkeypatch.setattr(tls, "fetch_tls_info", lambda domain: (cert_expiring_in(60), "TLSv1.3"))
    results = tls.check_tls("example.com", NOW)
    assert [r.name for r in results] == ["SSL certificate", "TLS version"]
    assert all(r.status is Status.PASS for r in results)


def test_verification_failure_is_fail(monkeypatch):
    def fail(domain):
        err = ssl.SSLCertVerificationError("certificate verify failed")
        err.verify_message = "Hostname mismatch, certificate is not valid for 'example.com'."
        raise err
    monkeypatch.setattr(tls, "fetch_tls_info", fail)
    [result] = tls.check_tls("example.com", NOW)
    assert result.status is Status.FAIL
    assert "Hostname mismatch" in result.details[0]


def test_connection_failure_is_warn(monkeypatch):
    def refuse(domain):
        raise ConnectionRefusedError("connection refused")
    monkeypatch.setattr(tls, "fetch_tls_info", refuse)
    [result] = tls.check_tls("example.com", NOW)
    assert result.status is Status.WARN
