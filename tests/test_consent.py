"""Who a report may run for: a domain with a recorded submission, and never one on the lead list.
Every report run leaves a line in the run log."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import pytest

from domain_health_check import cli, consent
from domain_health_check.models import DomainReport

NOW = datetime(2026, 10, 5, tzinfo=timezone.utc)


@pytest.fixture
def ran(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(cli, "run_checks", lambda d: seen.append(d.name) or DomainReport(d.name, NOW, []))
    return seen


# ---------- the submissions record

def test_a_domain_with_no_record_is_refused_and_told_how_to_fix_it(ran, tmp_path, capsys):
    assert cli.main(["report", "example.net", "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == []  # refused before anything was fetched
    err = capsys.readouterr().err
    assert "no submission is recorded for example.net" in err
    assert ("domain-health-check record-submission example.net --source form --email ADDRESS "
            "[--received YYYY-MM-DD]") in err


def test_the_config_file_is_held_to_the_same_rule(ran, tmp_path):
    config = tmp_path / "domains.yaml"
    config.write_text("domains: [example.com, example.net]\n", encoding="utf-8")
    assert cli.main(["report", "-c", str(config), "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == []  # one unrecorded domain stops the whole run


def test_a_recorded_domain_runs_and_the_run_is_logged(ran, tmp_path, run_log):
    assert cli.main(["report", "example.com", "example.org", "-o", str(tmp_path), "--no-pdf", "--no-color"]) == 0
    assert ran == ["example.com", "example.org"]
    lines = run_log.read_text(encoding="utf-8").splitlines()
    assert [line.split("\t")[3] for line in lines] == ["example.com", "example.org"]
    assert lines[0].endswith("\treport\texample.com\tsource=form\treceived=2026-10-01")


def test_record_submission_writes_one(tmp_path, submissions, capsys, ran):
    assert cli.main(["record-submission", "Example.NET", "--source", "email", "--email", "owner@example.net",
                     "--received", "2026-10-03"]) == 0
    assert "Recorded the submission for example.net (email, received 2026-10-03)" in capsys.readouterr().out
    record = consent.load_submissions(submissions)["example.net"]
    assert record == consent.Submission("example.net", "owner@example.net", date(2026, 10, 3), "email")
    assert cli.main(["report", "example.net", "-o", str(tmp_path), "--no-pdf", "--no-color"]) == 0


def test_recording_again_replaces_the_record(submissions, capsys):
    assert cli.main(["record-submission", "example.com", "--source", "in-person", "--received", "2026-10-04"]) == 0
    assert "Updated the submission for example.com" in capsys.readouterr().out
    records = consent.load_submissions(submissions)
    assert records["example.com"].source == "in-person" and len(records) == 2


@pytest.mark.parametrize("argv, error", [
    (["record-submission", "example.net", "--source", "form"], "needs the email address"),
    (["record-submission", "example.net", "--source", "email", "--email", "not-an-address"], "not an email address"),
    (["record-submission", "example.net", "--source", "own", "--received", "last week"], "a date like"),
    (["record-submission", "not a domain", "--source", "own"], "does not look like a domain"),
])
def test_record_submission_refuses_what_it_cannot_stand_behind(capsys, argv, error):
    assert cli.main(argv) == 2
    assert error in capsys.readouterr().err


def test_in_person_and_own_need_no_email(submissions):
    assert cli.main(["record-submission", "example.net", "--source", "own"]) == 0
    assert consent.load_submissions(submissions)["example.net"].received == date.today()


def test_a_malformed_record_file_stops_the_report(ran, tmp_path, submissions, capsys):
    submissions.write_text("submissions:\n  - domain: example.com\n", encoding="utf-8")
    assert cli.main(["report", "example.com", "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == [] and "a record is missing" in capsys.readouterr().err


def test_no_command_prints_help(capsys):
    assert cli.main([]) == 2
    assert "record-submission" in capsys.readouterr().err


def test_the_authorized_flag_is_gone(capsys):
    with pytest.raises(SystemExit):
        cli.main(["report", "--authorized", "example.com"])


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


def record(submissions, domain: str) -> None:
    consent.record_submission(submissions, consent.validate(domain, "", "2026-10-01", "in-person"))


@pytest.mark.parametrize("domain, match", [
    ("examplegarage.com", "examplegarage.com"),  # a lead's own site
    ("www.examplegarage.com", "examplegarage.com"),
    ("shop.examplegarage.com", "examplegarage.com"),  # under it
    ("example-garage-old.net", "example-garage-old.net"),  # named only in a note
    ("examplebarbers.wixsite.com", "examplebarbers.wixsite.com"),
])
def test_a_lead_list_domain_is_refused_even_with_a_record(ran, tmp_path, capsys, listed, submissions, domain, match):
    record(submissions, domain)
    assert cli.main(["report", domain, "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == []
    err = capsys.readouterr().err
    assert f"is on the lead list (as {match})" in err and "consent-free" in err


def test_recording_a_lead_list_domain_says_the_report_will_still_refuse(listed, capsys):
    assert cli.main(["record-submission", "examplegarage.com", "--source", "in-person"]) == 0
    assert "is on the lead list, so the report still refuses it" in capsys.readouterr().out


@pytest.mark.parametrize("domain", [
    "example.org",  # unrelated
    "someoneelse.wixsite.com",  # a builder named in a note is a platform, not a business
])
def test_a_domain_not_on_the_lead_list_is_not_refused_by_it(ran, tmp_path, listed, submissions, domain):
    record(submissions, domain)
    assert cli.main(["report", domain, "-o", str(tmp_path), "--no-pdf", "--no-color"]) == 0
    assert ran == [domain]


def test_file_names_are_not_domains(listed):
    assert "robots.txt" not in consent.lead_domains(listed)


def test_an_unreadable_lead_list_refuses_everything(ran, tmp_path, lead_list, capsys):
    lead_list.unlink()
    assert cli.main(["report", "example.org", "-o", str(tmp_path), "--no-pdf"]) == 2
    assert ran == [] and "cannot check the lead list" in capsys.readouterr().err
