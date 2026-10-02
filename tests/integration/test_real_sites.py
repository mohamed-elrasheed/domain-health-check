"""Known-answer checks against real sites. Opt-in only: pytest -m integration.

These hit real servers and the answers drift, so the tests assert behaviour, never findings: no crash; when
the website was not loaded, no score, no finding about the page, and (when a visitor cannot reach it) a reason
at the top of the report; when it was loaded, the content checks ran. A site that has changed so it no longer
covers its condition makes its test skip with a note rather than fail.

The only committed target is mizangroupllc.com, so something always runs. Other sites come from a gitignored
list on the machine that runs them, never from the repository: the businesses we test against are prospects,
not test subjects, and naming them beside a tool that looks for problems reads badly.
  tests/integration/sites.txt   one "<domain> <condition>" per line; # starts a comment
  INTEGRATION_SITES             or "domain=condition,domain=condition"
Conditions: loads | error status | does not resolve | times out
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from domain_health_check import layout, pdf
from domain_health_check.config import DomainConfig
from domain_health_check.models import SITE
from domain_health_check.report import render_markdown
from domain_health_check.runner import run_checks

pytestmark = pytest.mark.integration

LOADS, ERROR_STATUS, NO_DNS, TIMEOUT = "loads", "error status", "does not resolve", "times out"
CONDITIONS = {LOADS, ERROR_STATUS, NO_DNS, TIMEOUT}
COMMITTED = [("mizangroupllc.com", LOADS)]
LOCAL_LIST = Path(__file__).parent / "sites.txt"
CONTENT_CHECKS = {"Page title", "Meta description", "Canonical tag", "Main heading", "Mobile viewport",
                  "Heading order", "Image alt text", "Social preview", "Page weight", "Redirect chain"}


def local_sites() -> list[tuple[str, str]]:
    entries = []
    if os.environ.get("INTEGRATION_SITES"):
        for item in os.environ["INTEGRATION_SITES"].split(","):
            domain, _, condition = item.partition("=")
            entries.append((domain.strip(), condition.strip()))
    elif LOCAL_LIST.is_file():
        for line in LOCAL_LIST.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                domain, condition = re.split(r"\s+", line, maxsplit=1)
                entries.append((domain, condition.strip()))
    for domain, condition in entries:
        if condition not in CONDITIONS:
            raise ValueError(f"unknown condition {condition!r} for {domain}; use one of {sorted(CONDITIONS)}")
    return entries


LOCAL = local_sites()
PARAMS = [pytest.param(d, c, id=d) for d, c in COMMITTED + LOCAL] or []
if not LOCAL:
    PARAMS.append(pytest.param(None, None, id="local-sites",
                               marks=pytest.mark.skip(reason="no local site list (tests/integration/sites.txt or "
                                                             "INTEGRATION_SITES); only mizangroupllc.com ran")))


@pytest.mark.parametrize("domain, condition", PARAMS)
def test_real_site_produces_a_graceful_report(domain, condition):
    report = run_checks(DomainConfig(domain))  # must never raise
    assert report.results

    # Both renderers must cope with whatever came back.
    assert render_markdown(report) and pdf.render_html(report)
    value, sentence = layout.headline(report)

    if condition == LOADS:
        if not report.website_loaded:
            pytest.skip(f"{domain} no longer loads; pick another normal site")
        assert value is not None
        assert CONTENT_CHECKS <= {r.name for r in report.results if r.ran}
        return

    if report.website_loaded:
        pytest.skip(f"{domain} now loads, so it no longer covers '{condition}'; pick another site")
    assert value is None and sentence == layout.NO_SCORE  # no number computed over DNS and email alone
    if condition in (NO_DNS, TIMEOUT) and not report.unreachable:
        why = next((d for r in report.not_checked for d in r.details), "unknown")
        pytest.skip(f"{domain} no longer {condition} ({why}); pick another site")
    # No finding about a page we never saw. Search engine blocking may still report from robots.txt alone.
    judged = [r.name for r in report.results if r.category == SITE and r.ran and r.name != "Search engine blocking"]
    assert judged == [], f"{domain}: findings about a page we never saw: {judged}"
    assert not [r for r in report.results if r.name in ("HSTS (always use HTTPS)", "Content Security Policy",
                                                        "X-Content-Type-Options")]
