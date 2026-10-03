"""The mailer, against a fake SMTP server. Nothing here opens a socket; conftest would fail the test if it did."""

import smtplib
import ssl
from datetime import datetime, timezone

import pytest

from domain_health_check import cli, mailer
from domain_health_check.models import EMAIL, WEBSITE, CheckResult, DomainReport, Status

NOW = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)
PASSWORD = "abcd efgh ijkl mnop"  # the shape of a Google app password
ENV = {"SMTP_USERNAME": "mo@mizangroupllc.com", "SMTP_PASSWORD": PASSWORD}


class FakeSMTP:
    instances: list["FakeSMTP"] = []

    def __init__(self, host, port, timeout=None, fail_with=None):
        self.host, self.port, self.timeout, self.fail_with = host, port, timeout, fail_with
        self.calls, self.sent = [], []
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        self.calls.append(("starttls", context))

    def login(self, user, password):
        self.calls.append(("login", user))
        if self.fail_with:
            raise self.fail_with

    def send_message(self, msg):
        self.sent.append(msg)


@pytest.fixture(autouse=True)
def fresh_fakes():
    FakeSMTP.instances = []


def report() -> DomainReport:
    return DomainReport("example.com", NOW, [
        CheckResult(WEBSITE, "SSL certificate", Status.PASS, "Valid for another 80 days.", "Why."),
        CheckResult(EMAIL, "DMARC (anti-spoofing policy)", Status.WARN, "No DMARC record was found.", "Why.", "Add."),
    ])


@pytest.fixture
def pdf_file(tmp_path):
    path = tmp_path / "example.com-2026-03-14.pdf"
    path.write_bytes(b"%PDF-1.7 test")
    return path


def config() -> mailer.MailerConfig:
    return mailer.MailerConfig.from_env(dict(ENV))


def test_config_defaults_and_recipient():
    cfg = config()
    assert (cfg.host, cfg.port, cfg.recipient) == ("smtp.gmail.com", 587, "mo@mizangroupllc.com")
    assert mailer.MailerConfig.from_env({**ENV, "REPORT_RECIPIENT": "review@mizangroupllc.com"}).recipient == \
        "review@mizangroupllc.com"


def test_missing_settings_name_what_is_missing_but_never_the_password():
    with pytest.raises(mailer.MailerNotConfigured) as info:
        mailer.MailerConfig.from_env({"SMTP_PASSWORD": PASSWORD})
    assert "SMTP_USERNAME" in str(info.value) and PASSWORD not in str(info.value)


def test_password_is_not_in_the_repr():
    assert PASSWORD not in repr(config())


def test_message_format(pdf_file):
    msg = mailer.message_for(config(), report(), pdf_file)
    assert msg["Subject"].startswith("Website health report · example.com · ")
    assert msg["From"] == msg["To"] == "mo@mizangroupllc.com"
    body = msg.get_body(("plain",)).get_content()
    assert "Score " in body and "out of 100." in body
    assert "1 checks passed, 1 could be improved." in body
    assert "DMARC" not in body  # email security never leads; the email lists the report's top section only
    assert f"The full report is attached as {pdf_file.name}." in body
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_content_type() == "application/pdf" and attachment.get_filename() == pdf_file.name
    assert attachment.get_content() == b"%PDF-1.7 test"


def test_no_call_to_action_or_marketing(pdf_file):
    body = mailer.message_for(config(), report(), pdf_file).get_body(("plain",)).get_content().lower()
    for pitch in ("book a call", "quote", "price", "offer", "http", "contact us", "reply to"):
        assert pitch not in body, pitch


def test_send_verifies_the_server_and_never_writes_the_password(pdf_file):
    msg = mailer.message_for(config(), report(), pdf_file)
    mailer.send(msg, config(), smtp_factory=FakeSMTP)
    [server] = FakeSMTP.instances
    (_, context), login = server.calls
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode is ssl.CERT_REQUIRED and context.check_hostname
    assert login == ("login", "mo@mizangroupllc.com")
    assert server.sent == [msg]
    assert PASSWORD not in msg.as_string()


def test_failure_message_never_contains_the_password(pdf_file):
    echoed = smtplib.SMTPAuthenticationError(535, f"bad credentials {PASSWORD}".encode())

    def factory(host, port, timeout=None):
        return FakeSMTP(host, port, timeout, fail_with=echoed)

    with pytest.raises(mailer.SendFailed) as info:
        mailer.send(mailer.message_for(config(), report(), pdf_file), config(), smtp_factory=factory)
    assert PASSWORD not in str(info.value) and "<password>" in str(info.value)
    assert info.value.__cause__ is None and info.value.__suppress_context__  # the original is not chained


# ---------- through the CLI

@pytest.fixture
def cli_env(monkeypatch, tmp_path):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(cli, "SMTP_FACTORY", FakeSMTP)
    monkeypatch.setattr(cli, "run_checks", lambda d: DomainReport(d.name, NOW, report().results))

    def fake_pdf(rep, folder):
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{rep.domain}.pdf"
        path.write_bytes(b"%PDF")
        return path
    monkeypatch.setattr(cli, "write_pdf", fake_pdf)
    return tmp_path


def test_cli_email_sends_one_report_to_the_reviewer(cli_env, capsys):
    assert cli.main(["--authorized", "example.com", "-o", str(cli_env), "--no-color", "--email"]) == 0
    [server] = FakeSMTP.instances
    [msg] = server.sent
    assert msg["To"] == "mo@mizangroupllc.com"
    assert "Emailed to mo@mizangroupllc.com" in capsys.readouterr().out


def test_cli_email_without_settings_stops_before_running_checks(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "run_checks", lambda d: pytest.fail("checks ran without mail settings"))
    assert cli.main(["--authorized", "example.com", "-o", str(tmp_path), "--email"]) == 2
    assert "SMTP_USERNAME" in capsys.readouterr().err


def test_cli_send_failure_exits_2_without_the_password(cli_env, monkeypatch, capsys):
    def failing(host, port, timeout=None):
        return FakeSMTP(host, port, timeout, fail_with=smtplib.SMTPAuthenticationError(535, PASSWORD.encode()))
    monkeypatch.setattr(cli, "SMTP_FACTORY", failing)
    assert cli.main(["--authorized", "example.com", "-o", str(cli_env), "--no-color", "--email"]) == 2
    captured = capsys.readouterr()
    assert PASSWORD not in captured.out + captured.err


def test_worth_doing_is_the_reports_top_section(pdf_file):
    from domain_health_check import layout
    from domain_health_check.models import LOCAL, SITE
    # Mizan's shape: a mostly-right description and mobile speed, an unfindable profile, hardening gaps.
    report = DomainReport("example.com", NOW, [
        CheckResult(SITE, "Meta description", Status.WARN, "Description is 177 characters.", "Why.", "Fix.",
                    measure=160 / 177),
        CheckResult(LOCAL, "Google Business Profile", Status.WARN, "We could not find a profile.", "Why.", "Fix."),
        CheckResult(SITE, "Mobile speed", Status.WARN, "About 4.5 seconds.", "Why.", "Fix.", measure=0.8),
        CheckResult(WEBSITE, "Content Security Policy", Status.WARN, "No CSP.", "Why.", "Fix."),
    ])
    body = mailer.message_for(config(), report, pdf_file).get_body(("plain",)).get_content()
    bullets = [line for line in body.splitlines() if line.startswith("- ")]
    assert bullets == [f"- {r.name}: {r.summary}" for r in layout.worth_doing(report)]
    assert bullets == ["- Google Business Profile: We could not find a profile."]
    assert "One thing could be costing you customers." in body


def test_nothing_worth_doing_means_no_list(pdf_file):
    report = DomainReport("example.com", NOW, [
        CheckResult(WEBSITE, "Content Security Policy", Status.WARN, "No CSP.", "Why.", "Fix."),
    ])
    body = mailer.message_for(config(), report, pdf_file).get_body(("plain",)).get_content()
    assert "Worth doing" not in body and "- " not in body
