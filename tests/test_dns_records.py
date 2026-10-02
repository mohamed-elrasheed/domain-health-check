import pytest

from domain_health_check.checks import dns_records, dnssec
from domain_health_check.models import Status


def test_two_nameservers_pass(fake_dns):
    fake_dns[("example.com", "NS")] = ["ns2.example.net.", "ns1.example.net."]
    [result] = dns_records.check_nameservers("example.com")
    assert result.status is Status.PASS
    assert result.details == ["Nameserver: ns1.example.net", "Nameserver: ns2.example.net"]


def test_one_nameserver_warns(fake_dns):
    fake_dns[("example.com", "NS")] = ["ns1.example.net."]
    assert dns_records.check_nameservers("example.com")[0].status is Status.WARN


def test_no_nameservers_warns(fake_dns):
    assert dns_records.check_nameservers("example.com")[0].status is Status.WARN


def test_mx_records_sorted_by_priority(fake_dns):
    fake_dns[("example.com", "MX")] = ["20 mx2.example.com.", "10 mx1.example.com."]
    [result] = dns_records.check_mx("example.com")
    assert result.status is Status.PASS
    assert result.details == ["Priority 10: mx1.example.com", "Priority 20: mx2.example.com"]


def test_null_mx_passes(fake_dns):
    fake_dns[("example.com", "MX")] = ["0 ."]
    [result] = dns_records.check_mx("example.com")
    assert result.status is Status.PASS
    assert "doesn't receive email" in result.summary


def test_domain_never_set_up_for_mail_is_informational(fake_dns):
    # No MX, no SPF, no DMARC: the normal signature of a domain that does not use email. Not a finding.
    [result] = dns_records.check_mx("example.com")
    assert result.status is Status.INFO and result.ran  # checked and fine, not "not checked"
    assert result.summary == "This domain is not set up for email, which is normal if you use a different address for mail."
    assert result.fix == ""


@pytest.mark.parametrize("record, name", [
    (("example.com", "TXT"), "SPF"),
    (("_dmarc.example.com", "TXT"), "DMARC"),
])
def test_partial_mail_setup_without_mx_fails(fake_dns, record, name):
    # Mail was set up at least in part and now has nowhere to go: broken today, email bounces.
    fake_dns[record] = ["v=spf1 include:_spf.example.net ~all" if name == "SPF" else "v=DMARC1; p=none"]
    [result] = dns_records.check_mx("example.com")
    assert result.status is Status.FAIL and result.ran
    assert f"even though it has {name} set up" in result.summary


def test_dnssec_ds_present(fake_dns):
    fake_dns[("example.com", "DS")] = ["370 13 2 BE74359954660069D5C63D200C39F5603827D7DD02B56F120EE9F3A8 6764247C"]
    [result] = dnssec.check_dnssec("example.com")
    assert result.status is Status.PASS
    assert result.details == ["DS record: key tag 370, ECDSA P-256"]


def test_dnssec_missing_warns(fake_dns):
    assert dnssec.check_dnssec("example.com")[0].status is Status.WARN
