"""Known-answer checks against real small-business sites, verified 2026-10-02.

Opt-in only: pytest -m integration. These hit real servers and the answers drift, so the tests assert
behaviour, never findings: no crash; when the page was not loaded, one clear not-loaded row and no
findings about the page; when it was loaded, the content checks ran. If a site has changed so that its
case no longer exercises the condition it was chosen for, the test skips and says so rather than failing.
"""

from __future__ import annotations

import pytest

from domain_health_check import layout, pdf
from domain_health_check.config import DomainConfig
from domain_health_check.models import SITE
from domain_health_check.report import render_markdown
from domain_health_check.runner import run_checks

pytestmark = pytest.mark.integration

ERROR_STATUS, NO_DNS, TIMEOUT, LOADS = "error status", "does not resolve", "times out", "loads"
SITES = [
    ("site-a.example", ERROR_STATUS),   # 403 home behind 5 KB of HTML, 500 on robots.txt
    ("site-b.example", NO_DNS),
    ("site-c.example", TIMEOUT),                      # no response, around 7 seconds
    ("site-d.example", ERROR_STATUS),    # 404 home, 200 robots.txt
    ("site-e.example", LOADS),                # 200, about 4.4 seconds
    ("site-f.example", LOADS),         # 200, 336 KB
]
CONTENT_CHECKS = {"Page title", "Meta description", "Canonical tag", "Main heading", "Mobile viewport",
                  "Heading order", "Image alt text", "Social preview", "Page weight", "Redirect chain"}


@pytest.mark.parametrize("domain, condition", SITES, ids=[d for d, _ in SITES])
def test_real_site_produces_a_graceful_report(domain, condition):
    report = run_checks(DomainConfig(domain))  # must never raise
    assert report.results

    # Both renderers must cope with whatever came back.
    assert render_markdown(report) and pdf.render_html(report)
    assert layout.headline(report)[1]

    not_loaded = [r for r in report.results if r.name == "Site health checks"]
    if condition == LOADS:
        if not_loaded:
            pytest.skip(f"{domain} no longer loads ({not_loaded[0].summary}); pick another normal site")
        assert CONTENT_CHECKS <= {r.name for r in report.results if r.ran}
        return

    if not not_loaded:
        pytest.skip(f"{domain} now loads, so it no longer covers '{condition}'; pick another site")
    [row] = not_loaded
    assert not row.ran and row.summary and row.details
    if condition == ERROR_STATUS:
        assert "status" in row.summary
    # No finding about a page we never saw. Search engine blocking may still report from robots.txt alone.
    judged = [r.name for r in report.results if r.category == SITE and r.ran and r.name != "Search engine blocking"]
    assert judged == [], f"{domain}: findings about a page we never saw: {judged}"
    assert not [r for r in report.results if r.name in ("HSTS (always use HTTPS)", "Content Security Policy",
                                                        "X-Content-Type-Options")]
