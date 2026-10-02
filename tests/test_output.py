"""Tests for the runner, Markdown report, terminal summary and CLI."""

from datetime import datetime, timezone

from domain_health_check import cli, fetcher, runner
from domain_health_check.checks import http_headers
from domain_health_check.config import DomainConfig
from domain_health_check.fetcher import FetchError
from domain_health_check.models import EMAIL, SITE, WEBSITE, CheckResult, DomainReport, Status
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
    assert names[0] == "SSL certificate" and names[-1] == "Redirect chain"
    assert len(names) == 25  # TLS gives 2 results, headers 3, and the 13 site checks 1 each
    assert fetched == ["mizangroupllc.com"]  # one page fetch per report
    # No check should have crashed into the runner's "couldn't be completed" fallback.
    assert not any("couldn't be completed" in r.summary for r in report.results)
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
    assert result.status is Status.WARN and "couldn't load https://example.com/" in result.summary


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


def report_with_not_checked() -> DomainReport:
    results = [
        CheckResult(WEBSITE, "Checked fine", Status.PASS, "All good.", "Why."),
        CheckResult(SITE, "Real-world loading speed", Status.PASS, "Not enough traffic yet.", "Why speed.",
                    ran=False),
        CheckResult(SITE, "Site health checks", Status.WARN, "We could not load the page.", "Why site.",
                    "Fix nothing.", ["Error: ConnectError"], ran=False),
        CheckResult(SITE, "Google speed test", Status.FAIL, "Did not run.", "Why test.", ran=False),
    ]
    return DomainReport("example.com", NOW, results)


def test_not_run_never_reads_as_verified():
    md = render_markdown(report_with_not_checked())
    table = md.split("## What to fix")[0].split("## What's working well")[0]
    assert "| Real-world loading speed | ➖ Not checked |" in table
    assert "| Site health checks | ➖ Not checked |" in table
    assert "| Google speed test | ➖ Not checked |" in table
    assert "✅ 1 good · ⚠️ 0 could be improved · ❌ 0 need action · ➖ 3 not checked" in md
    assert "## What to fix" not in md  # the only non-PASS results did not run
    working = md.split("## What's working well")[1].split("## What we could not check")[0]
    assert "Checked fine" in working and "Real-world loading speed" not in working
    not_checked = md.split("## What we could not check")[1].split("## About this report")[0]
    for name in ("Real-world loading speed", "Site health checks", "Google speed test"):
        assert f"### ➖ {name}" in not_checked
    assert "Error: ConnectError" in not_checked


def test_not_run_does_not_change_overall_counts_or_exit_code():
    report = report_with_not_checked()
    assert report.overall is Status.PASS  # the FAIL above did not run, so it is not a failure
    assert (report.count(Status.PASS), report.count(Status.WARN), report.count(Status.FAIL)) == (1, 0, 0)
    assert "Everything we checked looks healthy" in render_markdown(report)


def test_terminal_marks_not_checked():
    plain = format_summary(report_with_not_checked(), color=False)
    assert "----  Google speed test" in plain
    assert "1 pass, 0 warn, 0 fail, 3 not checked" in plain
