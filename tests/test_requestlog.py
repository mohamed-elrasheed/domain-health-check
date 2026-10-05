"""The record of every request a report makes, and what makes a report incomplete."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

from domain_health_check import fetcher, mailer, requestlog, runner
from domain_health_check.config import DomainConfig
from domain_health_check.external import ExternalContext
from domain_health_check.models import DomainReport

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


def test_api_keys_never_reach_the_record():
    assert requestlog.mask("https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=x&key=SECRET&strategy=mobile") \
        == "https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url=x&key=<key>&strategy=mobile"
    with requestlog.recording() as log:
        requestlog.record("pagespeed", "GET", "https://example.net/run?KEY=SECRET")
    assert "SECRET" not in log[0].target


def test_nothing_is_recorded_outside_a_report():
    assert requestlog.record("page", "GET", "https://example.com/") is None


def test_httpx_requests_are_recorded_with_their_status():
    transport = httpx.MockTransport(lambda request: httpx.Response(404 if request.url.path == "/missing" else 200))
    with requestlog.recording() as log, httpx.Client(transport=transport,
                                                    event_hooks=requestlog.httpx_hooks("page")) as client:
        client.get("https://example.com/")
        client.get("https://example.com/missing")
    assert [(r.source, r.method, r.target, r.outcome) for r in log] == [
        ("page", "GET", "https://example.com/", "200"), ("page", "GET", "https://example.com/missing", "404")]


def test_the_review_email_names_the_attachment_for_the_domain_and_day(tmp_path):
    pdf = tmp_path / "example.com" / "2026-10-05" / "report.pdf"
    pdf.parent.mkdir(parents=True)
    pdf.write_bytes(b"%PDF-1.7 test")
    cfg = mailer.MailerConfig.from_env({"SMTP_USERNAME": "mo@mizangroupllc.com", "SMTP_PASSWORD": "x"})
    msg = mailer.message_for(cfg, DomainReport("example.com", NOW, []), pdf)
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_filename() == "example.com-2026-10-05.pdf"


def test_a_report_says_exactly_why_it_is_incomplete(monkeypatch, make_page):
    page = make_page(html="<html><head><title>Example</title></head><body>" + "<p>word</p>" * 60 + "</body></html>")
    monkeypatch.setattr(runner, "_domain_exists", lambda name: True)
    monkeypatch.setattr(runner, "_fetch_page", lambda name: page)
    monkeypatch.setattr(runner, "_fetch_external", lambda domain, page: ExternalContext())
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    assert not report.complete
    reasons = "\n".join(report.incomplete)
    assert "The browser could not load the home page" in reasons  # conftest refuses a browser
    assert "Google's speed test did not run: PAGESPEED_API_KEY is not set" in reasons
    assert "SSL/TLS could not be completed" in reasons  # the socket guard stops the handshake
    # And the attempt was recorded, even though it failed.
    assert any(r.source == "tls" and r.target == "example.com:443" for r in report.requests)


def test_a_report_with_everything_run_is_complete(monkeypatch, make_page):
    page = make_page()
    monkeypatch.setattr(runner, "_domain_exists", lambda name: True)
    monkeypatch.setattr(runner, "_fetch_page", lambda name: page)
    monkeypatch.setattr(runner, "_fetch_external", lambda domain, page: ExternalContext(psi_mobile=[{}]))
    monkeypatch.setattr(fetcher, "RENDERER", lambda url: fetcher.Rendered(page.html, url))
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page, ext: [])
    assert runner.run_checks(DomainConfig("example.com"), NOW).complete
