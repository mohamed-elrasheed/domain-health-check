"""The four faults the 1 October PDFs showed, checked on what the reader actually gets: the Markdown, a real
PDF and the email body, rendered from results the real checks produce for a site that has the problems.

  1. no promise to run the checks again at no charge
  2. a missing HSTS header or DMARC record is a warning ("Could be improved"), never "Needs action"
  3. one mail server reads "1 mail server is listed", not "1 mail servers"
  4. no Markdown escape such as "\\|" outside a Markdown table, and no contractions anywhere
"""

from __future__ import annotations

import io
import re
from datetime import datetime, timezone

import pytest

from domain_health_check import layout, mailer, pdf
from domain_health_check.checks import dns_records, email_auth, http_headers
from domain_health_check.checks.site import content
from domain_health_check.models import DomainReport, Status
from domain_health_check.report import render_markdown

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
CONTRACTION = re.compile(r"(?i)n['’]t\b|['’](re|ll|ve|m|d)\b|\b(it|that|there|here|what|who)['’]s\b")
RECHECK = re.compile(r"(?i)again in \d+ days|at no charge|run these checks again|free re-?check")


@pytest.fixture
def report(fake_dns, make_page) -> DomainReport:
    fake_dns[("example.com", "MX")] = ["10 mx.example.net."]  # one mail server
    fake_dns[("example.com", "TXT")] = ["v=spf1 include:_spf.example.net ~all"]  # and no DMARC record
    page = make_page(headers={}, html="<html><head><title>Home | Example Garage</title></head><body></body></html>")
    results = (http_headers.check_http_headers(page) + dns_records.check_mx("example.com")
               + email_auth.check_dmarc("example.com") + content.check_title(page))
    return DomainReport("example.com", NOW, results)


def by_name(report: DomainReport, name: str):
    return next(r for r in report.results if r.name == name)


def test_missing_hsts_and_dmarc_are_warnings(report):
    assert by_name(report, "HSTS (always use HTTPS)").status is Status.WARN
    assert by_name(report, "DMARC (anti-spoofing policy)").status is Status.WARN
    assert report.count(Status.FAIL) == 0


def check_text(text: str, where: str) -> None:
    assert not RECHECK.search(text), f"{where}: promises a re-check"
    assert "Needs action" not in text, f"{where}: a warning labelled as needing action"
    assert "1 mail server is listed" in text and "1 mail servers" not in text, where
    assert not CONTRACTION.search(text), f"{where}: {CONTRACTION.search(text).group(0)!r}"
    assert "Home | Example Garage" in text, f"{where}: the title is mangled"


def test_markdown(report):
    md = render_markdown(report)
    check_text(md.replace("\\|", "|"), "Markdown")
    # A pipe inside a Markdown table cell must be escaped, or it splits the cell. Nowhere else.
    stray = [line for line in md.splitlines() if "\\|" in line and not line.lstrip().startswith("|")]
    assert stray == []


def test_pdf(report):
    try:
        pdf._weasyprint()
    except OSError as exc:  # no Pango on this machine; CI installs it
        pytest.skip(f"WeasyPrint cannot load its native libraries: {exc}")
    pypdf = pytest.importorskip("pypdf")
    reader = pypdf.PdfReader(io.BytesIO(pdf.render_pdf(report)))
    text = " ".join(" ".join(page.extract_text().split()) for page in reader.pages)
    check_text(text, "PDF")
    assert "\\|" not in text
    assert "Could be improved HSTS" in text and "Could be improved DMARC" in text


def test_email(report, tmp_path):
    attachment = tmp_path / "example.com-2026-10-05.pdf"
    attachment.write_bytes(b"%PDF-1.7 test")
    cfg = mailer.MailerConfig.from_env({"SMTP_USERNAME": "mo@mizangroupllc.com", "SMTP_PASSWORD": "x"})
    body = mailer.message_for(cfg, report, attachment).get_body(("plain",)).get_content()
    assert not RECHECK.search(body) and not CONTRACTION.search(body) and "\\|" not in body
    assert "Needs action" not in body and "need action" not in layout.headline(report)[1].lower()
