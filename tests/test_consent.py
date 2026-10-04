"""A report runs only for a domain submitted through /digital. Until submissions are stored, that means
only with --authorized, and every such run leaves a line in the log."""

from __future__ import annotations

import json
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



# ---------- the lead list is consent-free by definition

LEADS = [
    {"id": "example-garage", "n": "Example Garage", "links": [["Site", "https://www.examplegarage.com/"],
                                                             ["Yelp", "https://www.yelp.com/biz/example-garage"]],
     "flaw": "Their old address example-garage-old.net still ranks. See robots.txt for details."},
    {"id": "example-barbers", "n": "Example Barbers",
     "links": [["Site", "https://examplebarbers.wixsite.com/home"]],
     "flaw": "Free wixsite.com subdomain."},
]


@pytest.fixture
def listed(lead_list):
    lead_list.write_text(json.dumps(LEADS), encoding="utf-8")
    return lead_list


@pytest.mark.parametrize("domain, match", [
    ("examplegarage.com", "examplegarage.com"),  # a lead's own site
    ("www.examplegarage.com", "examplegarage.com"),
    ("shop.examplegarage.com", "examplegarage.com"),  # under it
    ("example-garage-old.net", "example-garage-old.net"),  # named only in a note
    ("examplebarbers.wixsite.com", "examplebarbers.wixsite.com"),
])
def test_a_lead_list_domain_is_refused_even_when_authorized(ran, tmp_path, capsys, listed, domain, match):
    assert cli.main(["--authorized", domain, "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == []
    err = capsys.readouterr().err
    assert f"is on the lead list (as {match})" in err and "consent-free" in err


@pytest.mark.parametrize("domain", [
    "example.org",  # unrelated
    "someoneelse.wixsite.com",  # a builder named in a note is a platform, not a business
])
def test_a_domain_not_on_the_lead_list_is_not_refused_by_it(ran, tmp_path, listed, domain):
    assert cli.main(["--authorized", domain, "-o", str(tmp_path), "--no-pdf", "--no-color"]) == 0
    assert ran == [domain]


def test_file_names_are_not_domains(listed):
    assert "robots.txt" not in consent.lead_domains(listed)


def test_an_unreadable_lead_list_refuses_everything(ran, tmp_path, lead_list, capsys):
    lead_list.unlink()
    assert cli.main(["--authorized", "example.org", "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == [] and "cannot check the lead list" in capsys.readouterr().err
