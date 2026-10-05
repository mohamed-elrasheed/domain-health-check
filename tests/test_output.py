"""Tests for the runner, Markdown report, terminal summary and CLI."""

from datetime import datetime, timezone

import pytest

from domain_health_check import cli, fetcher, runner
from domain_health_check.checks import http_headers
from domain_health_check.config import DomainConfig
from domain_health_check.fetcher import FetchError
from domain_health_check.models import EMAIL, SITE, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.terminal import format_summary

NOW = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)


def sample_report(*statuses: Status) -> DomainReport:
    names = ["SSL certificate", "DMARC (anti-spoofing policy)", "Image alt text"]
    results = [
        CheckResult(EMAIL if i % 2 else WEBSITE, names[i], s, f"Found thing {i}.", f"Why {i} matters.",
                    "" if s is Status.PASS else f"Fix {i}.")
        for i, s in enumerate(statuses)
    ]
    return DomainReport("example.com", NOW, results)


@pytest.fixture(autouse=True)
def stub_pdf(monkeypatch):
    """Every run writes a PDF by default; the CLI tests stub the renderer so they do not need Pango.
    The PDF itself is tested in test_pdf.py."""
    written = []

    def fake(report, folder):
        written.append(report.domain)
        return folder / f"{report.domain}.pdf"
    monkeypatch.setattr(cli, "write_pdf", fake)
    return written


def test_overall_is_worst_status():
    assert sample_report(Status.PASS, Status.WARN).overall is Status.WARN
    assert sample_report(Status.PASS, Status.FAIL, Status.WARN).overall is Status.FAIL
    assert sample_report().overall is Status.PASS


def test_terminal_summary_plain_and_colored():
    report = sample_report(Status.PASS, Status.FAIL)
    plain = format_summary(report, color=False)
    assert "\033[" not in plain
    assert "PASS  SSL certificate" in plain and "1 pass, 0 warn, 1 fail" in plain
    assert "\033[31mFAIL" in format_summary(report, color=True)


def test_runner_turns_crashing_check_into_warning(monkeypatch, make_page):
    def boom():
        raise TimeoutError("resolver timed out")
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: make_page())
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page, ext: [
        (WEBSITE, "Fine", lambda: [CheckResult(WEBSITE, "Fine", Status.PASS, "ok", "why")]),
        (EMAIL, "Broken", boom),
    ])
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    assert [r.status for r in report.results] == [Status.PASS, Status.WARN]
    assert "TimeoutError" in report.results[1].details[0]
    assert report.results[0].ran and not report.results[1].ran


def _fake_lookups(monkeypatch):
    from domain_health_check.checks import rdap, tls
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})


def test_runner_runs_every_check_with_fake_data(fake_dns, monkeypatch, mizan_page):
    _fake_lookups(monkeypatch)
    fetched = []
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: fetched.append(d) or mizan_page)
    report = runner.run_checks(DomainConfig("mizangroupllc.com", ["google"]), NOW)
    names = [r.name for r in report.results]
    assert names[0] == "SSL certificate" and names[-1] == "Favicon"
    # TLS gives 2 results, headers 3, the link check 2 (this site, other sites) and the 15 other site checks 1 each
    assert len(names) == 29
    assert fetched == ["mizangroupllc.com"]  # one page fetch per report
    # No check should have crashed into the runner's "couldn't be completed" fallback.
    assert not any("could not be completed" in r.summary for r in report.results)
    site = [(r.name, r.status) for r in report.results if r.category == SITE]
    assert [name for name, status in site if status is not Status.PASS] == ["Meta description"]
    # The two header WARNs the live report shows: response.json has no CSP and no X-Content-Type-Options.
    headers = {r.name: r.status for r in report.results if r.name in ("Content Security Policy", "X-Content-Type-Options")}
    assert headers == {"Content Security Policy": Status.WARN, "X-Content-Type-Options": Status.WARN}


def test_unloaded_page_gives_one_site_row(fake_dns, monkeypatch):
    _fake_lookups(monkeypatch)
    def offline(domain):
        raise FetchError(f"https://{domain}/", "ConnectError: refused")
    monkeypatch.setattr(fetcher, "fetch_page", offline)
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    site = [r for r in report.results if r.category == SITE]
    assert [(r.name, r.ran) for r in site] == [("Site health checks", False)]


def test_runner_failed_fetch_becomes_a_warning(monkeypatch):
    def offline(domain):
        raise FetchError(f"https://{domain}/", "ConnectError: refused")
    monkeypatch.setattr(fetcher, "fetch_page", offline)
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page, ext: [
        (WEBSITE, "Security headers", lambda: http_headers.check_http_headers(page)),
    ])
    [result] = runner.run_checks(DomainConfig("example.com"), NOW).results
    assert result.status is Status.WARN and "could not load https://example.com/" in result.summary


def test_runner_survives_unexpected_fetch_crash(monkeypatch):
    def broken(domain):
        raise KeyError("bug")
    monkeypatch.setattr(fetcher, "fetch_page", broken)
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page, ext: [
        (WEBSITE, "Security headers", lambda: http_headers.check_http_headers(page)),
    ])
    [result] = runner.run_checks(DomainConfig("example.com"), NOW).results
    assert result.status is Status.WARN and "KeyError" in result.details[0]


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    config = tmp_path / "domains.yaml"
    config.write_text("domains: [example.com]\n", encoding="utf-8")
    out = tmp_path / "reports"

    monkeypatch.setattr(cli, "run_checks", lambda d: sample_report(Status.PASS, Status.WARN))
    assert cli.main(["report", "-c", str(config), "-o", str(out), "--no-color"]) == 0

    # A FAIL is a finding, not a failed run: a complete report exits 0 whatever it found.
    monkeypatch.setattr(cli, "run_checks", lambda d: sample_report(Status.FAIL))
    assert cli.main(["report", "-c", str(config), "-o", str(out), "--no-color"]) == 0
    run = out / "example.com" / "2026-03-14"
    assert sorted(p.name for p in run.iterdir()) == ["report.json", "report.md", "requests.log"]

    # An incomplete report is written in full and exits 3, with the reasons on stderr.
    def incomplete(d):
        report = sample_report(Status.PASS)
        report.incomplete = ["The browser could not load the home page"]
        return report
    monkeypatch.setattr(cli, "run_checks", incomplete)
    assert cli.main(["report", "-c", str(config), "-o", str(out), "--no-color"]) == 3
    assert "The browser could not load the home page" in capsys.readouterr().err
    assert (run / "report.json").exists()


def test_cli_config_error_exit_code(tmp_path, capsys):
    assert cli.main(["report", "-c", str(tmp_path / "missing.yaml")]) == 2
    assert "domains.example.yaml" in capsys.readouterr().err


def test_cli_domain_arguments_override_config(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "run_checks", lambda d: seen.append(d) or sample_report(Status.PASS))
    assert cli.main(["report", "example.org", "-o", str(tmp_path), "--no-color"]) == 0
    assert seen == [DomainConfig("example.org")]


def report_with_not_checked() -> DomainReport:
    return DomainReport("example.com", NOW, [
        CheckResult(WEBSITE, "SSL certificate", Status.PASS, "All good.", "Why."),
        CheckResult(SITE, "Real-world loading speed", Status.PASS, "Not enough traffic yet.", "Why speed.",
                    ran=False),
        CheckResult(SITE, "Site health checks", Status.WARN, "We could not load the page.", "Why site.",
                    ran=False),
        CheckResult(SITE, "Google speed test", Status.FAIL, "Did not run.", "Why test.", ran=False),
    ])


def test_terminal_marks_not_checked():
    plain = format_summary(report_with_not_checked(), color=False)
    assert "----  Google speed test" in plain
    assert "1 pass, 0 warn, 0 fail, 3 not checked" in plain


def test_cli_writes_a_pdf_by_default(tmp_path, monkeypatch, stub_pdf):
    monkeypatch.setattr(cli, "run_checks", lambda d: sample_report(Status.PASS))
    assert cli.main(["report", "example.com", "-o", str(tmp_path), "--no-color"]) == 0
    assert stub_pdf == ["example.com"]


def test_cli_no_pdf_skips_it(tmp_path, monkeypatch, stub_pdf):
    monkeypatch.setattr(cli, "run_checks", lambda d: sample_report(Status.PASS))
    assert cli.main(["report", "example.com", "-o", str(tmp_path), "--no-color", "--no-pdf"]) == 0
    assert stub_pdf == []


def test_cli_without_pango_keeps_the_markdown_and_exits_2(tmp_path, monkeypatch, capsys):
    from domain_health_check import cli as cli_module
    def no_pango(report, folder):
        raise OSError("cannot load library 'libgobject-2.0-0'")
    monkeypatch.setattr(cli_module, "run_checks", lambda d: sample_report(Status.PASS))
    monkeypatch.setattr(cli_module, "write_pdf", no_pango)
    assert cli.main(["report", "example.com", "-o", str(tmp_path), "--no-color"]) == 2
    assert (tmp_path / "example.com" / "2026-03-14" / "report.md").exists()
    assert "PDF output" in capsys.readouterr().err


def test_cli_passes_form_details(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "run_checks", lambda d: seen.append(d) or sample_report(Status.PASS))
    cli.main(["report", "example.com", "-o", str(tmp_path), "--no-color", "--business-name", " Example Plumbing ",
              "--city", "Springfield", "--phone", "555-010-0100"])
    assert seen == [DomainConfig("example.com", business_name="Example Plumbing", city="Springfield",
                                 phone="555-010-0100")]
