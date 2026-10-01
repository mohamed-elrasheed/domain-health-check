"""Tests for the runner, Markdown report, terminal summary and CLI."""

from datetime import datetime, timezone

from domain_health_check import cli, fetcher, runner
from domain_health_check.checks import http_headers
from domain_health_check.config import DomainConfig
from domain_health_check.fetcher import FetchError
from domain_health_check.models import EMAIL, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.report import render_markdown, write_report
from domain_health_check.terminal import format_summary

NOW = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)


def sample_report(*statuses: Status) -> DomainReport:
    results = [
        CheckResult(EMAIL if i % 2 else WEBSITE, f"Check {i}", s, f"Found thing {i} | with pipe.",
                    f"Why {i} matters.", "" if s is Status.PASS else f"Fix {i}.", [f"record <{i}>"])
        for i, s in enumerate(statuses)
    ]
    return DomainReport("example.com", NOW, results)


def test_overall_is_worst_status():
    assert sample_report(Status.PASS, Status.WARN).overall is Status.WARN
    assert sample_report(Status.PASS, Status.FAIL, Status.WARN).overall is Status.FAIL
    assert sample_report().overall is Status.PASS


def test_markdown_structure():
    md = render_markdown(sample_report(Status.PASS, Status.WARN, Status.FAIL))
    assert md.startswith("# Domain health report: example.com")
    assert "14 March 2026" in md
    assert "Found thing 1 \\| with pipe." in md          # table cells escaped
    assert "record &lt;0&gt;" in md                      # details escaped
    # Failures are listed before warnings in the "What to fix" section.
    fix_section = md.split("## What to fix")[1].split("## What's working well")[0]
    assert fix_section.index("Check 2") < fix_section.index("Check 1")
    assert "Check 0" not in fix_section
    assert "Nothing was scanned" in md


def test_all_pass_report_has_no_fix_section():
    md = render_markdown(sample_report(Status.PASS, Status.PASS))
    assert "## What to fix" not in md
    assert "Everything we checked looks healthy" in md


def test_write_report_uses_domain_and_date(tmp_path):
    path = write_report(sample_report(Status.PASS), tmp_path / "reports")
    assert path.name == "example.com-2026-03-14.md"
    assert path.read_text(encoding="utf-8").startswith("# Domain health report")


def test_terminal_summary_plain_and_colored():
    report = sample_report(Status.PASS, Status.FAIL)
    plain = format_summary(report, color=False)
    assert "\033[" not in plain
    assert "PASS  Check 0" in plain and "1 pass, 0 warn, 1 fail" in plain
    assert "\033[31mFAIL" in format_summary(report, color=True)


def test_runner_turns_crashing_check_into_warning(monkeypatch, make_page):
    def boom():
        raise TimeoutError("resolver timed out")
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: make_page())
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page: [
        (WEBSITE, "Fine", lambda: [CheckResult(WEBSITE, "Fine", Status.PASS, "ok", "why")]),
        (EMAIL, "Broken", boom),
    ])
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    assert [r.status for r in report.results] == [Status.PASS, Status.WARN]
    assert "TimeoutError" in report.results[1].details[0]


def test_runner_runs_every_check_with_fake_data(fake_dns, monkeypatch, make_page):
    from domain_health_check.checks import rdap, tls
    fetched = []
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: fetched.append(d) or make_page())
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    report = runner.run_checks(DomainConfig("example.com", ["google"]), NOW)
    names = [r.name for r in report.results]
    assert names[0] == "SSL certificate" and names[-1] == "DMARC (anti-spoofing policy)"
    assert len(names) == 12  # TLS gives 2 results and headers give 3
    assert fetched == ["example.com"]  # one page fetch per report
    # No check should have crashed into the runner's "couldn't be completed" fallback.
    assert not any("couldn't be completed" in r.summary for r in report.results)


def test_runner_failed_fetch_becomes_a_warning(monkeypatch):
    def offline(domain):
        raise FetchError(f"https://{domain}/", "ConnectError: refused")
    monkeypatch.setattr(fetcher, "fetch_page", offline)
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page: [
        (WEBSITE, "Security headers", lambda: http_headers.check_http_headers(page)),
    ])
    [result] = runner.run_checks(DomainConfig("example.com"), NOW).results
    assert result.status is Status.WARN and "couldn't load https://example.com/" in result.summary


def test_runner_survives_unexpected_fetch_crash(monkeypatch):
    def broken(domain):
        raise KeyError("bug")
    monkeypatch.setattr(fetcher, "fetch_page", broken)
    monkeypatch.setattr(runner, "_checks_for", lambda domain, now, page: [
        (WEBSITE, "Security headers", lambda: http_headers.check_http_headers(page)),
    ])
    [result] = runner.run_checks(DomainConfig("example.com"), NOW).results
    assert result.status is Status.WARN and "KeyError" in result.details[0]


def test_cli_exit_codes(tmp_path, monkeypatch, capsys):
    config = tmp_path / "domains.yaml"
    config.write_text("domains: [example.com]\n", encoding="utf-8")
    out = tmp_path / "reports"

    monkeypatch.setattr(cli, "run_checks", lambda d: sample_report(Status.PASS, Status.WARN))
    assert cli.main(["-c", str(config), "-o", str(out), "--no-color"]) == 0

    monkeypatch.setattr(cli, "run_checks", lambda d: sample_report(Status.FAIL))
    assert cli.main(["-c", str(config), "-o", str(out), "--no-color"]) == 1
    assert (out / "example.com-2026-03-14.md").exists()


def test_cli_config_error_exit_code(tmp_path, capsys):
    assert cli.main(["-c", str(tmp_path / "missing.yaml")]) == 2
    assert "domains.example.yaml" in capsys.readouterr().err


def test_cli_domain_arguments_override_config(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "run_checks", lambda d: seen.append(d) or sample_report(Status.PASS))
    assert cli.main(["example.org", "-o", str(tmp_path), "--no-color"]) == 0
    assert seen == [DomainConfig("example.org")]
