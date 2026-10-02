"""A fix is something the owner can act on or ask for, never syntax. Records, headers and tags belong in the
technical details, where whoever makes the change will look for them."""

import pytest

from domain_health_check.checks import dns_records, email_auth, http_headers
from domain_health_check.checks.site import delivery

SYNTAX = ("`", "v=spf1", "v=dmarc1", "<meta", "max-age=", "x-content-type-options:", "_dmarc.", "p=quarantine",
          "p=reject", "~all", "-all", "null mx")


@pytest.mark.parametrize("result", [
    email_auth.evaluate_spf([]),
    email_auth.evaluate_spf(["v=spf1 +all"]),
    email_auth.evaluate_spf(["v=spf1 ?all"]),
    email_auth.evaluate_spf(["v=spf1 mx"]),
    email_auth.evaluate_dmarc([]),
    email_auth.evaluate_dmarc(["v=DMARC1; p=none"]),
    email_auth.evaluate_dmarc(["v=DMARC1; p=bogus"]),
    http_headers.evaluate_hsts(None),
    http_headers.evaluate_content_type_options(None),
    delivery.evaluate_viewport([]),
    dns_records.evaluate_missing_mx(True, False),
], ids=lambda r: f"{r.name}: {r.summary[:30]}")
def test_fix_is_advice_and_the_syntax_is_in_the_details(result):
    lowered = result.fix.lower()
    assert lowered and not [s for s in SYNTAX if s in lowered], result.fix
    assert result.details, "the record, header or tag to add should be in the technical details"


def test_dmarc_reads_as_advice():
    result = email_auth.evaluate_dmarc([])
    assert result.fix == ("Ask whoever manages your domain to add a DMARC record so other mail servers can tell real "
                          "email from spoofed email.")
    assert any("v=DMARC1; p=none" in d for d in result.details)
