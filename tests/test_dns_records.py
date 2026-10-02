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


def test_no_mx_fails(fake_dns):
    # Broken, not a risk: email sent to the domain bounces today.
    assert dns_records.check_mx("example.com")[0].status is Status.FAIL


def test_dnssec_ds_present(fake_dns):
    fake_dns[("example.com", "DS")] = ["370 13 2 BE74359954660069D5C63D200C39F5603827D7DD02B56F120EE9F3A8 6764247C"]
    [result] = dnssec.check_dnssec("example.com")
    assert result.status is Status.PASS
    assert result.details == ["DS record: key tag 370, ECDSA P-256"]


def test_dnssec_missing_warns(fake_dns):
    assert dnssec.check_dnssec("example.com")[0].status is Status.WARN
