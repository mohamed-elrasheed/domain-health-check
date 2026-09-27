"""Tests for the dnspython wrapper, with dns.resolver.resolve replaced by a fake."""

import dns.exception
import dns.resolver
import pytest

from domain_health_check import dns_utils


class FakeRecord:
    def __init__(self, text, strings=()):
        self._text = text
        self.strings = strings

    def to_text(self):
        return self._text


def fake_resolve(result):
    def resolve(name, rdtype, lifetime=None):
        if isinstance(result, Exception):
            raise result
        return result
    return resolve


def test_lookup_returns_text(monkeypatch):
    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve([FakeRecord("10 mx1.example.com.")]))
    assert dns_utils.lookup("example.com", "MX") == ["10 mx1.example.com."]


@pytest.mark.parametrize("error", [dns.resolver.NXDOMAIN(), dns.resolver.NoAnswer()])
def test_missing_records_return_empty_list(monkeypatch, error):
    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve(error))
    assert dns_utils.lookup("example.com", "DS") == []


def test_timeouts_raise_lookup_error(monkeypatch):
    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve(dns.exception.Timeout()))
    with pytest.raises(dns_utils.DNSLookupError):
        dns_utils.lookup("example.com", "NS")


def test_txt_chunks_are_joined(monkeypatch):
    record = FakeRecord('"v=spf1 include:a" " -all"', strings=(b"v=spf1 include:a", b" -all"))
    monkeypatch.setattr(dns.resolver, "resolve", fake_resolve([record]))
    assert dns_utils.lookup_txt("example.com") == ["v=spf1 include:a -all"]
