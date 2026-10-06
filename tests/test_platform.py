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


# ---------- WordPress: recognized for wording only, never as a hosted builder

@pytest.mark.parametrize("html, evidence", [
    ('<meta name="generator" content="WordPress 6.6">', "generator tag: wordpress 6.6"),
    ('<link rel="stylesheet" href="/wp-content/themes/firm/style.css">', "assets load from /wp-content/themes/firm/style.css"),
    ('<script src="/wp-includes/js/jquery/jquery.min.js"></script>', "assets load from /wp-includes/js/jquery/jquery.min.js"),
    ("<link rel='https://api.w.org/' href='https://www.example.com/wp-json/'>", "link rel: https://api.w.org/"),
])
def test_wordpress_is_recognized_from_each_sourced_signal(html, evidence, make_page):
    found = platform.detect_cms(make_page(html=f"<html><head>{html}</head></html>", final_url="https://www.example.com/"))
    assert (found.name, found.evidence) == ("WordPress", evidence)


def test_wordpress_is_not_a_hosted_builder(make_page):
    page = make_page(html=(FIXTURES / "wordpress.html").read_text(encoding="utf-8"),
                     final_url="https://www.example.com/")
    assert platform.detect(page) is None and platform.detect_cms(page).name == "WordPress"
    on_wordpress = DomainReport("example.com", NOW, [finding(n) for n in HEADERS], cms="WordPress")
    assert {rung.key for rung, _ in layout.priced(on_wordpress)} == {"tuneup"}


def test_the_golden_wordpress_page_is_recognized(make_page):
    html = (GOLDEN / "wordpress-lazyload" / "page.html").read_text(encoding="utf-8")
    assert platform.detect_cms(make_page(html=html, final_url="https://www.example.com/")).name == "WordPress"
    for other in ("webflow", "wix", "squarespace", "js-spa"):
        html = (GOLDEN / other / "page.html").read_text(encoding="utf-8")
        assert platform.detect_cms(make_page(html=html, final_url="https://www.example.com/")) is None, other


def test_every_cms_signal_cites_a_source():
    import yaml
    data = yaml.safe_load(platform.PATH.read_text(encoding="utf-8"))
    for name, spec in data["cms"].items():
        for kind in ("generator", "paths", "links"):
            for entry in spec.get(kind) or []:
                assert entry.get("source", "").startswith("https://developer.wordpress.org/"), (name, kind, entry)



# ---------- one opening phrase per platform for every self fix

BROKEN_PAGE = ("<html><head><meta name='generator' content='WordPress 6.6'></head><body>"
               "<h3>Start</h3><h2>A</h2><h4>B</h4>"
               "<a href='/'><img class='custom-logo' src='/wp-content/uploads/logo.png'></a>"
               "<img src='/wp-content/uploads/team.jpg'><img src='http://img.example.net/x.jpg' alt='A van'>"
               "<a href='/gone'>Gone</a><a href='https://elsewhere.example.org/gone'>Gone too</a></body></html>")


def run_on(monkeypatch, html: str):
    import httpx

    from domain_health_check import fetcher, linkcheck, runner
    from domain_health_check.config import DomainConfig
    from domain_health_check.external import ExternalContext
    from domain_health_check.fetcher import FetchedFile, PageContext

    def gone(request):
        return httpx.Response(404 if "gone" in request.url.path else 200)
    page = PageContext("https://www.example.com/", "https://www.example.com/", [], 200, {}, html, len(html), 100, 50,
                       FetchedFile("https://www.example.com/robots.txt", 200, "User-agent: *\nAllow: /\n"), None)
    monkeypatch.setattr(runner, "_domain_exists", lambda name: True)
    monkeypatch.setattr(runner, "_fetch_page", lambda name: page)
    monkeypatch.setattr(runner, "_fetch_external", lambda domain, page: ExternalContext())
    monkeypatch.setattr(linkcheck, "TRANSPORT", httpx.MockTransport(gone))
    monkeypatch.setattr(fetcher, "ICON_TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(404)))
    return runner.run_checks(DomainConfig("example.com"), NOW)


def self_fixes(report: DomainReport) -> dict[str, str]:
    return {r.name: r.fix for r in report.results if r.ran and r.status is Status.WARN
            and layout.rung(r, report).key == "self" and r.category == SITE}


def test_no_self_fix_says_website_builder_on_wordpress(monkeypatch):
    report = run_on(monkeypatch, BROKEN_PAGE)
    fixes = self_fixes(report)
    assert report.cms == "WordPress"
    assert {"Main heading", "Meta description", "Image alt text", "Heading order", "Social preview", "Broken links",
            "Mixed content", "Favicon", "Links to other sites"} <= set(fixes)
    assert not {name: fix for name, fix in fixes.items() if "website builder" in fix.lower()}
    assert all(fix.startswith("In WordPress") for fix in fixes.values()), fixes


@pytest.mark.parametrize("head, opening", [
    ("<meta content='Webflow' name='generator'>", "In Webflow"),
    ("", "Wherever you edit your site"),
])
def test_each_platform_gets_one_shared_opening(monkeypatch, head, opening):
    report = run_on(monkeypatch, BROKEN_PAGE.replace("<meta name='generator' content='WordPress 6.6'>", head)
                    .replace("/wp-content/uploads/", "/images/"))
    fixes = self_fixes(report)
    assert fixes and all(fix.startswith(opening) for fix in fixes.values()), fixes


def test_the_fix_it_yourself_intro_is_the_same_on_every_platform():
    assert layout.SELF_INTRO == "Changes you, or whoever edits your site, can make in its editor."
    assert pricelist.load().rungs["self"].intro == layout.SELF_INTRO
    assert "without a developer" not in render_markdown(report(""))
