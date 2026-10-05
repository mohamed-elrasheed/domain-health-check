"""Hosted website builders, recognized from what the report already fetched, and the three header findings they
control moved to the platform rung: listed, never priced, and scored exactly as before."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain_health_check import layout, platform, pricelist, scoring
from domain_health_check.models import SITE, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.report import record, render_markdown

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "platforms"
CASES = json.loads((FIXTURES / "cases.json").read_text(encoding="utf-8"))
GOLDEN = Path(__file__).parent / "fixtures" / "synthetic" / "report"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
HEADERS = ("HSTS (always use HTTPS)", "Content Security Policy", "X-Content-Type-Options")


@pytest.mark.parametrize("name", sorted(CASES))
def test_each_builder_is_recognized_from_one_kind_of_signal(name, make_page):
    case = CASES[name]
    page = make_page(html=(FIXTURES / f"{name}.html").read_text(encoding="utf-8"),
                     final_url="https://www.example.com/", headers=case["headers"])
    found = platform.detect(page)
    assert (found.name if found else None) == case["platform"]


@pytest.mark.parametrize("archetype, expected", [
    ("webflow", "Webflow"), ("wix", "Wix"),
    ("godaddy-builder", None),  # every GoDaddy signal is disabled: none has a source in GoDaddy's documentation
    ("squarespace", "Squarespace"),  # its assets load from static1.squarespace.com
    ("wordpress-lazyload", None), ("js-spa", None),
])
def test_the_golden_archetypes(archetype, expected, make_page):
    html = (GOLDEN / archetype / "page.html").read_text(encoding="utf-8")
    headers = json.loads((GOLDEN / archetype / "expected.json").read_text(encoding="utf-8"))["headers"]
    found = platform.detect(make_page(html=html, final_url="https://www.example.com/",
                                      headers={k.lower(): v for k, v in headers.items()}))
    assert (found.name if found else None) == expected


def test_resources_the_browser_loaded_count_but_a_framed_page_does_not(make_page):
    page = make_page(final_url="https://www.example.com/", rendered_html="<html></html>",
                     resources=[("https://www.example.com/a.js", "script"),
                                ("https://shop.myshopify.com/embed", "iframe")])
    assert platform.detect(page) is None
    page = replace(page, resources=page.resources + [("https://cdn.shopify.com/s/x.js", "script")])
    assert platform.detect(page).evidence == "assets load from cdn.shopify.com"


def finding(name: str, category: str = WEBSITE) -> CheckResult:
    return CheckResult(category, name, Status.WARN, f"{name} summary.", "Why.",
                       f"Ask your web developer or host about {name}.", [])


def report(platform_name: str) -> DomainReport:
    results = [finding(n) for n in HEADERS] + [finding("Canonical tag", SITE)]
    return DomainReport("example.com", NOW, results, platform=platform_name,
                        platform_evidence="generator tag: webflow" if platform_name else "")


def test_on_a_builder_the_header_findings_are_set_by_the_platform_and_listed_last():
    groups = [(rung.key, [r.name for r in rs]) for rung, rs in layout.priced(report("Webflow"))]
    assert groups == [("tuneup", ["Canonical tag"]), ("platform", list(HEADERS))]
    md = render_markdown(report("Webflow"))
    section = md[md.index("### Set by your website platform"):]
    assert pricelist.load().rungs["platform"].intro in section
    assert section.split("\n")[2] == ("This is set by your website platform, not by you or a developer. We list it "
                                      "for completeness and do not charge for it.")
    assert "$" not in section.split("---")[0]


def test_without_a_builder_they_stay_tuneup():
    groups = [(rung.key, [r.name for r in rs]) for rung, rs in layout.priced(report(""))]
    assert groups == [("tuneup", ["Canonical tag"] + list(HEADERS))]  # the report's own order: ladder tier


def test_the_platform_does_not_change_the_score():
    assert scoring.score(report("Webflow").results) == scoring.score(report("").results)


def test_the_record_names_the_platform_and_the_rung():
    data = record(report("Wix"))
    assert data["platform"] == {"name": "Wix", "evidence": "generator tag: webflow"}
    assert {r["name"]: r["rung"] for r in data["results"]}["Content Security Policy"] == "platform"
    assert record(report(""))["platform"] is None


def test_platform_is_never_assigned_by_hand():
    assert "platform" not in pricelist.load().checks.values()
    assert pricelist.load().platform_checks == frozenset(HEADERS)


def test_on_a_builder_the_headers_appear_once_and_never_under_needs_a_developer():
    """The owner cannot change them and neither can a developer, so they are not in "Needs a developer", no
    finding tells the owner to ask a developer or host about them, and they appear once: on the last page, with
    the platform sentence."""
    on_builder = report("Webflow")
    assert [r.name for r in layout.needs_developer(on_builder)] == ["Canonical tag"]
    md = render_markdown(on_builder)
    developer = md[md.index("## Needs a developer"):md.index("## Everything we checked")]
    assert not any(name in developer for name in HEADERS)
    sentence = pricelist.load().rungs["platform"].intro
    for name in HEADERS:
        findings = [line for line in md.splitlines() if line.startswith(("### ", "| ")) and name in line
                    and not line.startswith(("| Website security", "| Site health"))]
        assert findings == [f"| {name} | {name} summary. |"], findings
    assert md.count(sentence) == 1
    assert md.index(sentence) < md.index("| HSTS (always use HTTPS) | HSTS (always use HTTPS) summary. |")
    # Their fix is the developer advice, and it is nowhere in the report.
    assert not [name for name in HEADERS if f"Ask your web developer or host about {name}." in md]


def test_with_only_platform_findings_there_is_nothing_to_pass_on():
    only = DomainReport("example.com", NOW, [finding(n) for n in HEADERS], platform="Wix")
    assert layout.next_steps(only)[0][1] == "Nothing here needs fixing, so there is nothing you need to do with this report."
    assert "## Needs a developer" not in render_markdown(only)


def test_every_signal_cites_a_source_or_is_disabled(tmp_path):
    """Nothing from memory ships: the loader refuses a signal with neither a source nor a reason it is off."""
    import yaml
    data = yaml.safe_load(platform.PATH.read_text(encoding="utf-8"))
    for name, spec in data["platforms"].items():
        for kind in platform.SIGNALS:
            for entry in spec.get(kind) or []:
                assert bool(entry.get("source")) != bool(entry.get("disabled")), (name, kind, entry)
    bad = tmp_path / "platforms.yaml"
    bad.write_text('platforms:\n  X:\n    hosts: [{value: "x.example.net"}]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="source to cite or the reason"):
        platform.load(bad)


def test_a_disabled_signal_is_not_used(make_page):
    page = make_page(html="<html><head></head></html>", final_url="https://www.example.com/",
                     headers={"x-wf-region": "us-east-1", "server": "Squarespace", "x-shopid": "1"})
    assert platform.detect(page) is None
