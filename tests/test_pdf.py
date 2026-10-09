"""The PDF report. Structure is tested on the HTML it is printed from; one test prints a real PDF and reads
every finding back out of it, which is the failure that parsing Markdown into a PDF once produced."""

import io
from datetime import datetime, timezone

import pytest

from domain_health_check import layout, pdf
from domain_health_check.models import EMAIL, SITE, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.report import render_markdown

NOW = datetime(2026, 10, 2, 1, 19, tzinfo=timezone.utc)


def full_report() -> DomainReport:
    """Every status, a not-run result, markup-hostile text and enough findings to run over several pages."""
    results = [
        CheckResult(WEBSITE, "SSL certificate", Status.FAIL, "The certificate has expired.", "Why <it> matters & more.",
                    "Renew it.", ["Expires: 1 October 2026", "Issuer: <Example CA>"]),
        CheckResult(WEBSITE, "HSTS (always use HTTPS)", Status.WARN, "No HSTS header.", "Why.", "Add it.",
                    ["Checked page: https://example.com/"]),
        CheckResult(EMAIL, "DMARC (anti-spoofing policy)", Status.WARN, "No DMARC record was found.", "Why.", "Add one."),
        CheckResult(SITE, "Real-world loading speed", Status.PASS, "Not enough traffic yet.", "Why.", ran=False),
    ]
    filler = ["Image alt text", "Page title", "Social preview", "Heading order", "Meta description", "Canonical tag",
              "Main heading", "Mobile viewport", "Page weight", "Redirect chain", "Sitemap and robots"]
    for i, name in enumerate(filler):
        status = Status.WARN if i % 2 else Status.PASS
        results.append(CheckResult(SITE, name, status, f"Finding number {i} for {name}.", "A long explanation. " * 12,
                                   "" if status is Status.PASS else "A fix.", [f"Detail {j}" for j in range(6)]))
    return DomainReport("example.com", NOW, results)


def test_every_result_is_in_the_document():
    report = full_report()
    html = pdf.render_html(report)
    from domain_health_check.models import Status
    for r in report.results:
        assert html.count(f">{r.name}<") >= 1, r.name  # every result has its table row
        if r.ran and r.status in (Status.PASS, Status.INFO):
            assert html.count(f">{r.name}<") == 1, r.name  # a pass is its table row and nothing else


def test_same_findings_and_closing_as_the_markdown():
    report = full_report()
    html, md = pdf.render_html(report), render_markdown(report)
    for r in layout.confirmed(report) + layout.worth_checking(report):
        assert r.name in html and r.name in md
    for lead, rest in layout.next_steps(report):
        assert rest in html and rest in md


def test_details_are_visible_not_collapsed():
    html = pdf.render_html(full_report())
    assert "<details" not in html
    assert "Technical details, for whoever makes the change" in html


def test_text_is_escaped():
    html = pdf.render_html(full_report())
    assert "Why &lt;it&gt; matters &amp; more." in html and "Issuer: &lt;Example CA&gt;" in html


def test_pills_and_not_checked():
    html = pdf.render_html(full_report())
    assert '<span class="pill action">Needs action</span>' in html
    assert '<span class="pill skip">Not checked</span>' in html


def test_print_rules():
    # Cards break across pages; headings stay with what follows them.
    assert "break-inside: auto" in pdf.CSS and "break-after: avoid" in pdf.CSS


def test_no_recheck_promise():
    html = pdf.render_html(full_report()).lower()
    for promise in ("30 days", "at no charge", "run these checks again"):
        assert promise not in html


def test_assets_ship_with_the_package():
    for name in ("mizan-mark.png", "fonts/PlusJakartaSans-Medium.ttf", "fonts/PlusJakartaSans-Bold.ttf",
                 "fonts/OFL.txt"):
        assert (pdf.ASSETS / name).is_file()


def test_real_pdf_contains_every_finding():
    try:
        pdf._weasyprint()
    except OSError as exc:  # no Pango on this machine; CI installs it
        pytest.skip(f"WeasyPrint cannot load its native libraries: {exc}")
    pypdf = pytest.importorskip("pypdf")
    report = full_report()
    data = pdf.render_pdf(report)
    assert data.startswith(b"%PDF")
    reader = pypdf.PdfReader(io.BytesIO(data))
    text = " ".join(" ".join(page.extract_text().split()) for page in reader.pages)
    assert len(reader.pages) >= 2
    for r in report.results:
        assert r.name in text, f"{r.name} is missing from the PDF"
    assert f"Page {len(reader.pages)} of {len(reader.pages)}" in text



def test_pdf_has_the_same_sections_as_the_markdown():
    report = full_report()
    html, md = pdf.render_html(report), render_markdown(report)
    for heading in ("Worth doing", "Fix it yourself", "Needs a developer"):
        assert (f"<h2>{heading}</h2>" in html) == (f"## {heading}" in md)
