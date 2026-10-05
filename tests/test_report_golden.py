"""Golden reports: one synthetic home page per site archetype, and every finding the report must emit for it.

The report runs end to end through runner.run_checks, with the page fetch replaced by the fixture and every
outside lookup left to fail as it would offline. A test fails if the report emits any page finding that is not
in the fixture's expected.json, or misses one. "Page finding" means every result that reads the fetched page:
the site health checks and the three security headers. DNS, registry and TLS results need the network and are
covered elsewhere.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from domain_health_check import fetcher, runner
from domain_health_check.config import DomainConfig
from domain_health_check.external import ExternalContext
from domain_health_check.fetcher import FetchedFile, PageContext
from domain_health_check.models import SITE, Status

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "report"
ARCHETYPES = ["webflow", "wordpress-lazyload", "wix", "squarespace", "godaddy-builder", "js-spa"]
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
URL = "https://www.example.com/"
HEADER_CHECKS = {"HSTS (always use HTTPS)", "Content Security Policy", "X-Content-Type-Options"}
# Site-category results that come from outside services, not from the page.
EXTERNAL = {"Google speed test", "Real-world loading speed", "Mobile speed", "Accessibility", "Best practices"}
ROBOTS = f"User-agent: *\nAllow: /\nSitemap: {URL}sitemap.xml\n"
SITEMAP = (f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
           f"<url><loc>{URL}</loc></url><url><loc>{URL}menu</loc></url></urlset>")


def expected(archetype: str) -> dict:
    return json.loads((FIXTURES / archetype / "expected.json").read_text(encoding="utf-8"))


def page(archetype: str) -> PageContext:
    html = (FIXTURES / archetype / "page.html").read_text(encoding="utf-8")
    return PageContext(
        requested_url=URL, final_url=URL, redirect_chain=[], status=200,
        headers={k.lower(): v for k, v in expected(archetype)["headers"].items()},
        html=html, byte_size=len(html.encode()), elapsed_ms=180, ttfb_ms=90,
        robots=FetchedFile(f"{URL}robots.txt", 200, ROBOTS), sitemap=FetchedFile(f"{URL}sitemap.xml", 200, SITEMAP),
    )


def report_findings(monkeypatch, archetype: str, renderer=None) -> set[tuple[str, str, str]]:
    """{(check, status, summary)} for every page result that is not a pass."""
    monkeypatch.setattr(runner, "_domain_exists", lambda name: True)
    monkeypatch.setattr(runner, "_fetch_page", lambda name: page(archetype))
    monkeypatch.setattr(runner, "_fetch_external", lambda domain, page: ExternalContext())
    if renderer is not None:
        monkeypatch.setattr(fetcher, "RENDERER", renderer)
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    found = set()
    for r in report.results:
        if (r.category == SITE and r.name not in EXTERNAL) or r.name in HEADER_CHECKS:
            if r.status is not Status.PASS or not r.ran:
                found.add((r.name, "NOT_CHECKED" if not r.ran else r.status.name, r.summary))
    return found


def compare(found: set[tuple[str, str, str]], wanted: list[dict]) -> None:
    got = {(name, status) for name, status, _ in found}
    want = {(w["check"], w["status"]) for w in wanted}
    assert got - want == set(), f"the report said things it should not: {sorted(got - want)}"
    assert want - got == set(), f"the report missed: {sorted(want - got)}"
    for w in wanted:
        summary = next(s for name, status, s in found if (name, status) == (w["check"], w["status"]))
        assert w["says"] in summary, f"{w['check']}: {summary!r} does not say {w['says']!r}"


@pytest.mark.parametrize("archetype", [a for a in ARCHETYPES if a != "js-spa"])
def test_golden_report(monkeypatch, archetype):
    """With no browser available. Every report asks for one; when it cannot have one, the findings are the same
    on these pages, and the checks that would judge the screen say they read the page as delivered."""
    asked = []

    def unavailable(url):
        asked.append(url)
        raise fetcher.RenderFailed("no browser")
    compare(report_findings(monkeypatch, archetype, renderer=unavailable), expected(archetype)["findings"])
    assert asked == [URL]  # every report asks for a browser view of the page


def test_a_script_built_page_without_a_browser_reports_false_absences(monkeypatch):
    """No browser (conftest refuses one): the content checks say they did not run, and the checks that still
    read the empty shell report a canonical tag and structured data as missing, which is false."""
    compare(report_findings(monkeypatch, "js-spa"), expected("js-spa")["findings_without_render"])


@pytest.fixture
def local_renderer(local_browser):
    """The real browser path, pointed at the fixture on disk instead of the network, offline."""
    def render(url: str) -> fetcher.Rendered:
        assert url == URL
        return fetcher.browser_render((FIXTURES / "js-spa" / "page.html").resolve().as_uri(), offline=True)
    return render


def test_a_script_built_page_rendered_in_a_browser_has_nothing_wrong(monkeypatch, local_renderer):
    compare(report_findings(monkeypatch, "js-spa", renderer=local_renderer), expected("js-spa")["findings"])


def test_what_a_visitor_cannot_see_does_not_count(local_renderer):
    """The rendered page has two h1s, one hidden with display:none, and a zero-size image with no alt text.
    Marked by the browser, they drop out; read without the marks, they would be findings."""
    from domain_health_check.checks.site import content
    from domain_health_check.checks.site._html import HIDDEN
    rendered = fetcher.render(page("js-spa"), renderer=local_renderer)
    assert rendered.rendered and HIDDEN in rendered.rendered_html
    [heading] = content.check_main_heading(rendered)
    assert heading.status is Status.PASS and "A neighborhood restaurant in Springfield" in heading.summary
    [alt] = content.check_alt_text(rendered)
    assert alt.status is Status.PASS and "1 of the 1 images" in alt.summary
    unmarked = fetcher.PageContext(**{**rendered.__dict__,
                                      "rendered_html": rendered.rendered_html.replace(HIDDEN, "data-was-hidden")})
    assert content.check_main_heading(unmarked)[0].summary == "Your home page has 2 main headings instead of one."
    assert content.check_alt_text(unmarked)[0].status is Status.WARN



def test_the_report_says_when_it_looked_twice(monkeypatch, local_renderer):
    from domain_health_check import layout
    monkeypatch.setattr(runner, "_domain_exists", lambda name: True)
    monkeypatch.setattr(runner, "_fetch_page", lambda name: page("js-spa"))
    monkeypatch.setattr(runner, "_fetch_external", lambda domain, page: ExternalContext())
    monkeypatch.setattr(fetcher, "RENDERER", local_renderer)
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    assert report.rendered and "one more visit to that page in a standard web browser" in layout.about(report)

    def unavailable(url):
        raise fetcher.RenderFailed("no browser")
    monkeypatch.setattr(fetcher, "RENDERER", unavailable)
    unrendered = runner.run_checks(DomainConfig("example.com"), NOW)
    assert not unrendered.rendered and "a single ordinary visit" in layout.about(unrendered)
