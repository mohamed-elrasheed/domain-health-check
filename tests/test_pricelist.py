"""Findings mapped to the price list: every check has a rung, every price line is the published one, and the last
page lists confirmed findings under their rung, self first, or says in one sentence that there is nothing to list."""

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml
from selectolax.parser import HTMLParser

from domain_health_check import layout, pdf, pricelist, scoring
from domain_health_check.checks import business_profile as bp
from domain_health_check.checks import rdap
from domain_health_check.checks.site import content, sharing
from domain_health_check.external import ExternalContext
from domain_health_check.models import DOMAIN, EMAIL, SITE, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.report import record, render_markdown

OURS = Path(__file__).parent / "fixtures" / "mizangroupllc.com"  # saved copies of our own /digital and /services
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
PRICES = pricelist.load()


def page_lines(page: str = "digital") -> list[str]:
    tree = HTMLParser((OURS / f"{page}.html").read_text(encoding="utf-8"))
    for node in tree.css("script, style, noscript"):
        node.decompose()
    return [line.strip() for line in tree.body.text(separator="\n").splitlines() if line.strip()]


def result(name: str, status: Status = Status.WARN, category: str = SITE, fix: str = "Do the thing.",
           certain: bool = True, ran: bool = True) -> CheckResult:
    return CheckResult(category, name, status, f"{name} summary.", "Why.", fix, [], ran, certain=certain)


def report_of(*results: CheckResult) -> DomainReport:
    return DomainReport("example.com", NOW, list(results))


# ---------- the config

def test_every_check_has_a_rung():
    """A check missing here would reach the last page with no instruction and no price line."""
    assert set(PRICES.checks) == set(scoring.WEIGHTS), (
        f"no rung: {sorted(set(scoring.WEIGHTS) - set(PRICES.checks))}; "
        f"no such check: {sorted(set(PRICES.checks) - set(scoring.WEIGHTS))}")
    assert set(PRICES.checks.values()) <= set(pricelist.RUNGS)


def test_every_price_line_is_published_word_for_word():
    lines = page_lines()
    for key, line in PRICES.prices.items():
        assert line.item in lines, f"{key}: {line.item!r} is not on /digital"
        assert lines[lines.index(line.item) + 1] == line.price, f"{key}: /digital does not price {line.item!r} " \
                                                                 f"at {line.price!r}"


def test_every_published_price_is_in_the_config():
    """The mirror runs both ways: a price added to the page is a price this file has not caught up with."""
    published = [line for line in page_lines("digital") if re.search(r"\$\d", line) and len(line) < 40]
    assert sorted(published) == sorted(line.price for line in PRICES.prices.values() if line.page == "digital")


def test_only_the_paid_rungs_carry_prices_and_self_carries_none():
    assert PRICES.rungs["self"].prices == ()
    assert [str(p) for p in PRICES.rungs["tuneup"].prices] == ["Custom work outside a package: $85 per hour"]
    assert [p.price for p in PRICES.rungs["rebuild"].prices] == [
        "Starting at $900", "Starting at $1,800", "Starting at $2,800"]


@pytest.mark.parametrize("change, problem", [
    (lambda d: d["rungs"].pop("rebuild"), "the rungs must be exactly"),
    (lambda d: d["rungs"]["tuneup"].update(prices=["discount"]), "not in the list: discount"),
    (lambda d: d["checks"].update({"Page title": "someday"}), "Page title: someday"),
])
def test_a_broken_config_is_refused(change, problem):
    data = yaml.safe_load(pricelist.PATH.read_text(encoding="utf-8"))
    change(data)
    with pytest.raises(ValueError, match=problem):
        pricelist.parse(data)


def test_the_config_reads_in_report_voice():
    data = yaml.safe_load(pricelist.PATH.read_text(encoding="utf-8"))
    text = [r["label"] for r in data["rungs"].values()] + [r["intro"] for r in data["rungs"].values()]
    for line in text:
        assert "—" not in line and "!" not in line and not re.search(r"(?i)n't|'(re|ll|ve)\b", line), line
        assert not re.search(r"(?i)urgent|immediately|limited time|today only|act now", line), line


# ---------- self means the owner can act on the fix

SELF_RESULTS = [
    content.evaluate_title(None, "https://www.example.com/"),
    content.evaluate_title("x" * 90, "https://www.example.com/"),
    content.evaluate_description([]),
    content.evaluate_description(["Too short."]),
    content.evaluate_main_heading([]),
    content.evaluate_main_heading(["One", "Two"]),
    content.evaluate_heading_order([1, 3]),
    content.evaluate_alt_text([("https://www.example.com/a.jpg", None)]),
    sharing.evaluate_social_preview({}),
    rdap.evaluate_registration({"events": [{"eventAction": "expiration", "eventDate": "2026-10-20T00:00:00Z"}]}, NOW),
    rdap.evaluate_registration({}, NOW),
    bp.evaluate_profile(ExternalContext(place_outcome="not_found", errors={"place": "x"})),
    bp.evaluate_profile(ExternalContext(place_outcome="unconfirmed", errors={"place": "x"})),
    bp.evaluate_profile(ExternalContext(place={"businessStatus": "CLOSED_TEMPORARILY"}, place_match="website")),
    bp.evaluate_completeness(ExternalContext(place={"businessStatus": "OPERATIONAL"}, place_match="website")),
    bp.evaluate_website_link(ExternalContext(place={"businessStatus": "OPERATIONAL"}, place_match="website"),
                             "example.com"),
    bp.evaluate_reviews(ExternalContext(place={"userRatingCount": 2}, place_match="website")),
]


@pytest.mark.parametrize("r", SELF_RESULTS, ids=lambda r: f"{r.name}: {r.summary[:30]}")
def test_a_self_finding_comes_with_a_one_or_two_sentence_instruction(r):
    assert r.status is not Status.PASS
    assert layout.rung(r).key == "self"
    sentences = [s for s in re.split(r"(?<=[.?])\s+(?=[A-Z\"])", r.fix.strip()) if s]
    assert r.fix and 1 <= len(sentences) <= 2, r.fix
    assert "developer" not in r.fix.lower(), "a self fix the owner has to hand to someone else is not self"


# ---------- the last page

def test_groups_are_self_then_tuneup_then_rebuild_and_unconfirmed_findings_are_not_priced():
    report = report_of(
        result("Mobile viewport"),
        result("DMARC (anti-spoofing policy)", category=EMAIL, fix="Ask for a DMARC record."),
        result("Meta description", fix="Write a description."),
        result("Redirect chain"),
        result("Canonical tag", certain=False),
        result("Page title", status=Status.PASS),
        result("SSL certificate", ran=False, category=WEBSITE),
    )
    groups = [(rung.key, [r.name for r in results]) for rung, results in layout.priced(report)]
    assert groups == [("self", ["Meta description"]), ("tuneup", ["Redirect chain"]),
                      ("email", ["DMARC (anti-spoofing policy)"]), ("rebuild", ["Mobile viewport"])]
    assert layout.prices_note(report) == layout.UNCONFIRMED_NOT_PRICED


def test_the_markdown_lists_each_finding_with_its_rung_and_price_line():
    report = report_of(result("Meta description", fix="Write a description."), result("Canonical tag"),
                       result("DMARC (anti-spoofing policy)", category=EMAIL, fix="Ask for a DMARC record."),
                       result("Mobile viewport"))
    md = render_markdown(report)
    section = md[md.index("## " + layout.PRICES_HEADING):]
    assert (section.index("### Fix it yourself") < section.index("### Tune-up") < section.index("### Email and domain")
            < section.index("### New site"))
    assert "| Meta description | Write a description. |" in section
    assert "| Canonical tag | Custom work outside a package: $85 per hour |" in section
    assert "| Finding | What to ask for |\n|---|---|\n| DMARC (anti-spoofing policy) | Ask for a DMARC record. |" in section
    assert ("| Mobile viewport | Starter site, up to five pages: Starting at $900; Business site, up to ten pages, "
            "edit it yourself: Starting at $1,800; Online store with checkout and payments: Starting at $2,800 |"
            ) in section
    assert md.index("## What happens next") < md.index("## " + layout.PRICES_HEADING)


def test_every_dollar_figure_on_the_last_page_comes_from_the_config():
    report = report_of(*[result(name) for name in PRICES.checks])
    md = render_markdown(report)
    section = md[md.index("## " + layout.PRICES_HEADING):]
    assert set(re.findall(r"\$[\d,]+", section)) <= {re.search(r"\$[\d,]+", p.price).group()
                                                     for p in PRICES.prices.values()}


def test_when_everything_passes_the_last_page_is_one_sentence():
    report = report_of(result("Page title", status=Status.PASS), result("DNSSEC", Status.PASS, DOMAIN))
    md = render_markdown(report)
    section = md[md.index("## " + layout.PRICES_HEADING):md.index("---", md.index(layout.PRICES_HEADING))]
    assert section.split("\n", 1)[1].strip() == layout.NOTHING_TO_PRICE
    assert layout.NOTHING_TO_PRICE.count(".") == 1


def test_only_unconfirmed_findings_still_say_nothing_is_priced():
    report = report_of(result("Canonical tag", certain=False))
    assert layout.priced(report) == [] and layout.prices_note(report) == layout.NOTHING_CONFIRMED


def test_the_fix_yourself_section_is_the_self_rung():
    report = report_of(result("Domain registration", category=DOMAIN), result("Canonical tag"))
    assert [r.name for r in layout.fix_yourself(report)] == ["Domain registration"]
    assert [r.name for r in layout.needs_developer(report)] == ["Canonical tag"]


def test_a_check_with_no_rung_is_refused_rather_than_guessed():
    with pytest.raises(KeyError, match="no rung"):
        layout.priced(report_of(result("A check nobody mapped")))


def test_the_record_carries_each_rung():
    report = report_of(result("Meta description"), result("DNSSEC", category=DOMAIN),
                       result("Site health checks", ran=False))
    rungs = {r["name"]: r["rung"] for r in json.loads(json.dumps(record(report), default=str))["results"]}
    assert rungs == {"Meta description": "self", "DNSSEC": "email", "Site health checks": None}


def test_the_pdf_ends_on_the_price_page():
    try:
        pdf._weasyprint()
    except OSError as exc:  # no Pango on this machine; CI installs it
        pytest.skip(f"WeasyPrint cannot load its native libraries: {exc}")
    pypdf = pytest.importorskip("pypdf")
    report = report_of(result("Meta description", fix="Write a description."), result("Canonical tag"))
    pages = pypdf.PdfReader(io.BytesIO(pdf.render_pdf(report))).pages
    last = " ".join(pages[-1].extract_text().split())
    assert last.startswith(layout.PRICES_HEADING)
    assert "Custom work outside a package: $85 per hour" in last and "Write a description." in last
    assert layout.PRICES_HEADING not in " ".join(p.extract_text() for p in pages[:-1])

    clean = pypdf.PdfReader(io.BytesIO(pdf.render_pdf(report_of(result("Page title", Status.PASS))))).pages
    text = " ".join(clean[-1].extract_text().split())
    assert text.startswith(f"{layout.PRICES_HEADING} {layout.NOTHING_TO_PRICE}")
