import pytest

from domain_health_check.checks import email_auth
from domain_health_check.models import Status


# --- SPF ---

@pytest.mark.parametrize("records, expected", [
    (["v=spf1 include:_spf.example.com -all"], Status.PASS),
    (["v=spf1 include:_spf.example.com ~all"], Status.PASS),
    (["v=spf1 redirect=_spf.example.com"], Status.PASS),
    (["v=spf1 include:_spf.example.com ?all"], Status.WARN),
    (["v=spf1 include:_spf.example.com"], Status.WARN),
    (["v=spf1 +all"], Status.WARN),
    (["v=spf1 a mx all"], Status.WARN),               # a bare "all" means +all
    (["V=SPF1 MX -ALL"], Status.PASS),                 # case-insensitive
    (["google-site-verification=abc"], Status.WARN),   # no SPF at all
    ([], Status.WARN),
    (["v=spf1 -all", "v=spf1 include:x.example.com ~all"], Status.WARN),  # two records
])
def test_spf(records, expected):
    assert email_auth.evaluate_spf(records).status is expected


def test_spf_ignores_lookalike_prefix():
    assert email_auth.evaluate_spf(["v=spf10 -all"]).status is Status.WARN


def test_check_spf_reads_domain_txt(fake_dns):
    fake_dns[("example.com", "TXT")] = ["some-verification=1", "v=spf1 mx -all"]
    [result] = email_auth.check_spf("example.com")
    assert result.status is Status.PASS
    assert result.details == ["SPF record: v=spf1 mx -all"]


# --- DMARC ---

@pytest.mark.parametrize("record, expected", [
    ("v=DMARC1; p=reject; rua=mailto:d@example.com", Status.PASS),
    ("v=DMARC1; p=quarantine; rua=mailto:d@example.com", Status.PASS),
    ("v=DMARC1; p=none; rua=mailto:d@example.com", Status.WARN),
    ("v=DMARC1; rua=mailto:d@example.com", Status.WARN),
    ("v=DMARC1; p=bogus", Status.WARN),
])
def test_dmarc_policy(record, expected):
    assert email_auth.evaluate_dmarc([record]).status is expected


def test_dmarc_missing_warns():
    assert email_auth.evaluate_dmarc([]).status is Status.WARN


def test_dmarc_duplicate_warns():
    assert email_auth.evaluate_dmarc(["v=DMARC1; p=reject", "v=DMARC1; p=none"]).status is Status.WARN


def test_dmarc_notes_missing_reports_and_partial_pct():
    result = email_auth.evaluate_dmarc(["v=DMARC1; p=quarantine; pct=25"])
    assert any("rua" in d for d in result.details)
    assert any("25%" in d for d in result.details)


def test_check_dmarc_queries_underscore_name(fake_dns):
    fake_dns[("_dmarc.example.com", "TXT")] = ["v=DMARC1; p=reject"]
    assert email_auth.check_dmarc("example.com")[0].status is Status.PASS


# --- DKIM ---

KEY = "v=DKIM1; k=rsa; p=MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA"


def test_dkim_found_on_configured_selector(fake_dns):
    fake_dns[("google._domainkey.example.com", "TXT")] = [KEY]
    [result] = email_auth.check_dkim("example.com", ["google"])
    assert result.status is Status.PASS
    assert "google" in result.summary


def test_dkim_configured_selector_missing_warns(fake_dns):
    [result] = email_auth.check_dkim("example.com", ["selector1"])
    assert result.status is Status.WARN


def test_dkim_falls_back_to_common_selectors(fake_dns):
    fake_dns[("selector2._domainkey.example.com", "TXT")] = [KEY]
    [result] = email_auth.check_dkim("example.com", [])
    assert result.status is Status.PASS
    assert "selector2" in result.summary


def test_dkim_nothing_on_common_selectors_warns(fake_dns):
    [result] = email_auth.check_dkim("example.com")
    assert result.status is Status.WARN
    assert len([d for d in result.details if d.startswith("Selector checked")]) == len(email_auth.DEFAULT_DKIM_SELECTORS)
    # The fix goes to a business owner, who has no domains.yaml.
    assert "domains.yaml" not in result.fix and "which selector name it uses" in result.fix


def test_dkim_revoked_key_warns(fake_dns):
    fake_dns[("fm1._domainkey.example.com", "TXT")] = ["v=DKIM1; p="]
    assert email_auth.check_dkim("example.com", ["fm1"])[0].status is Status.WARN
