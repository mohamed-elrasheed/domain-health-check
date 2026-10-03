"""A report runs only for a domain submitted through /digital. Until submissions are stored, that means
only with --authorized, and every such run leaves a line in the log."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from domain_health_check import cli, consent
from domain_health_check.models import DomainReport


@pytest.fixture
def ran(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(cli, "run_checks", lambda d: seen.append(d.name) or DomainReport(d.name, NOW, []))
    return seen


NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def test_no_submission_is_recorded_yet():
    assert consent.recorded_submission("example.com") is False


def test_report_refuses_a_domain_without_authorization(ran, tmp_path, capsys, authorization_log):
    assert cli.main(["example.com", "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == []  # refused before anything was fetched
    assert "--authorized" in capsys.readouterr().err
    assert not authorization_log.exists()


def test_report_refuses_the_config_file_too(ran, tmp_path):
    config = tmp_path / "domains.yaml"
    config.write_text("domains: [example.com]\n", encoding="utf-8")
    assert cli.main(["-c", str(config), "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == []


def test_authorized_runs_are_logged(ran, tmp_path, authorization_log):
    assert cli.main(["--authorized", "example.com", "example.org", "-o", str(tmp_path), "--no-pdf",
                     "--no-color"]) == 0
    assert ran == ["example.com", "example.org"]
    lines = authorization_log.read_text(encoding="utf-8").splitlines()
    assert [line.split("\t")[-1] for line in lines] == ["example.com", "example.org"]
    assert all("\t--authorized\t" in line for line in lines)


def test_log_appends_rather_than_replaces(tmp_path):
    log = tmp_path / "a.log"
    consent.log_authorized(["example.com"], log, NOW)
    consent.log_authorized(["example.org"], log, NOW)
    assert log.read_text(encoding="utf-8").splitlines()[0].startswith("2026-10-02T00:00:00+00:00\t")
    assert len(log.read_text(encoding="utf-8").splitlines()) == 2
