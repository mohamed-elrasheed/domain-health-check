"""The automated pipeline: intake from the /digital form, consent, the run, and delivery to the reviewer only.

The one rule above all: nothing here can email anyone but mo@mizangroupllc.com. Every submission is synthetic;
every email goes to a fake SMTP server.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import date, datetime, timezone
from email.message import EmailMessage
from pathlib import Path

import httpx
import pytest
import yaml
from selectolax.parser import HTMLParser

from domain_health_check import intake, mailer, pipeline
from domain_health_check.models import SITE, CheckResult, DomainReport, Status

PACKAGE = Path(__file__).parent.parent / "domain_health_check"
OURS = Path(__file__).parent / "fixtures" / "mizangroupllc.com"
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
CFG = mailer.MailerConfig("smtp.gmail.com", 587, "mo@mizangroupllc.com", "app-password")


class FakeSMTP:
    sent: list[EmailMessage] = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, user, password):
        pass

    def send_message(self, msg, to_addrs=None):
        assert to_addrs == [mailer.REVIEWER]
        FakeSMTP.sent.append(msg)


@pytest.fixture(autouse=True)
def fresh_outbox():
    FakeSMTP.sent = []


# ---------- nobody but the reviewer, ever

def test_the_recipient_is_hard_coded_and_cannot_be_configured():
    assert mailer.REVIEWER == "mo@mizangroupllc.com"
    env = {"SMTP_USERNAME": "mo@mizangroupllc.com", "SMTP_PASSWORD": "x", "REPORT_RECIPIENT": "owner@example.com"}
    assert mailer.MailerConfig.from_env(env).recipient == mailer.REVIEWER


@pytest.mark.parametrize("header, value", [("To", "owner@example.com"), ("Cc", "owner@example.com"),
                                            ("Bcc", "owner@example.com"), ("To", "mo@mizangroupllc.com, x@example.com")])
def test_send_refuses_any_other_recipient(header, value):
    msg = EmailMessage()
    msg["To"] = mailer.REVIEWER if header != "To" else value
    if header != "To":
        msg[header] = value
    msg["Subject"] = "x"
    with pytest.raises(mailer.WrongRecipient):
        mailer.send(msg, CFG, smtp_factory=FakeSMTP)
    assert FakeSMTP.sent == []


def test_no_code_path_addresses_anyone_but_the_reviewer():
    """Every To, Cc or Bcc set anywhere in the package is the REVIEWER constant, and nothing else names a
    recipient for send_message. A new code path that addressed the business would fail here."""
    problems = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant)
                            and str(target.slice.value).lower() in ("to", "cc", "bcc")):
                        if not (isinstance(node.value, ast.Name) and node.value.id == "REVIEWER"):
                            problems.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in ("send_message", "sendmail"):
                for keyword in node.keywords:
                    if keyword.arg == "to_addrs" and "REVIEWER" not in ast.unparse(keyword.value):
                        problems.append(f"{path.name}:{node.lineno} to_addrs")
    assert problems == []


def report_for(domain: str = "mizangroupllc.com", incomplete=()) -> DomainReport:
    results = [CheckResult(SITE, "Main heading", Status.WARN, "Your home page has no main heading.", "Why.", "Fix.",
                           []),
               CheckResult(SITE, "Page title", Status.PASS, "Good title.", "Why.", "", [])]
    return DomainReport(domain, NOW, results, incomplete=list(incomplete))


def test_every_pipeline_message_goes_to_the_reviewer_only(tmp_path):
    pdf = tmp_path / "2026-10-09" / "report.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF")
    for msg in (mailer.review_message(CFG, report_for(), pdf, 0, "a request"),
                mailer.failure_message(CFG, "a run", "boom"), mailer.notice_message(CFG, "subject", "body")):
        assert mailer.recipients(msg) == {mailer.REVIEWER}


# ---------- the review email and the draft

def test_the_review_email_carries_the_pdf_the_exit_code_the_gaps_and_a_draft(tmp_path):
    pdf = tmp_path / "2026-10-09" / "report.pdf"
    pdf.parent.mkdir()
    pdf.write_bytes(b"%PDF")
    msg = mailer.review_message(CFG, report_for(incomplete=["Google's speed test did not run"]), pdf, 3, "a request")
    body = msg.get_body(("plain",)).get_content()
    assert msg["Subject"].startswith("REVIEW BEFORE SENDING")
    assert "Exit code: 3 (written, but incomplete)." in body and "- Google's speed test did not run" in body
    assert "Draft message to the business (not sent):" in body and "Main heading" in body
    [attachment] = list(msg.iter_attachments())
    assert attachment.get_filename() == "mizangroupllc.com-2026-10-09.pdf"


def test_the_draft_names_the_top_findings_and_asks_nothing():
    draft = mailer.draft_to_business(report_for())
    assert "- Main heading: Your home page has no main heading." in draft
    assert "?" not in draft and "!" not in draft and "—" not in draft
    assert not re.search(r"(?i)\b(let us know|reply|call us|book|schedule|would you|please|interested)\b", draft)
    assert not re.search(r"(?i)n't\b|'(re|ll|ve|d)\b", draft)


# ---------- intake from Webflow

def test_the_intake_config_matches_our_own_digital_page():
    cfg = yaml.safe_load(intake.PATH.read_text(encoding="utf-8"))
    html = (OURS / "digital.html").read_text(encoding="utf-8")
    tree = HTMLParser(html)
    assert tree.css_first("html").attributes.get("data-wf-site") == cfg["site_id"]
    form = tree.css_first("form")
    assert form.attributes.get("data-wf-page-id") == cfg["page_id"]
    names = {n.attributes.get("data-name") for n in form.css("input, textarea, select")}
    assert set(cfg["fields"].values()) <= names
    by_id = {n.attributes.get("id"): n.attributes.get("data-name") for n in form.css("input")}
    assert (by_id["phone"], by_id["website"], by_id["business-name"]) == (
        cfg["fields"]["phone"], cfg["fields"]["website"], cfg["fields"]["business_name"])


SUBMISSION = {"id": "sub-1", "dateSubmitted": "2026-10-09T13:00:00.000Z", "formResponse": {
    "Name": "Test Person", "Email": "mo@mizangroupllc.com", "Field": "571.354.8352", "Business name": "Mizan Group LLC",
    "City or ZIP": "Centreville, VA", "Field 2": "https://www.mizangroupllc.com/", "Field 3": "Website", "Field 4": "x"}}


def webflow(seen: list, pages: list[list[dict]], token="secret-token-123"):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["Authorization"] == f"Bearer {token}" and token not in str(request.url)
        if request.url.path.endswith("/forms"):
            return httpx.Response(200, json={"forms": [{"id": "home-form", "pageId": "home"},
                                                       {"id": "digital-form", "pageId": intake.config()["page_id"]}]})
        offset = int(request.url.params.get("offset", 0))
        batch = pages[offset // intake.PAGE_SIZE] if offset // intake.PAGE_SIZE < len(pages) else []
        return httpx.Response(200, json={"formSubmissions": batch,
                                         "pagination": {"total": sum(len(p) for p in pages)}})
    return httpx.MockTransport(handle)


def test_fetch_finds_the_digital_form_and_reads_every_page(monkeypatch):
    monkeypatch.setattr(intake, "PAGE_SIZE", 1)
    seen = []
    second = {**SUBMISSION, "id": "sub-2", "dateSubmitted": "2026-10-08T09:00:00Z"}
    found = intake.fetch("secret-token-123", transport=webflow(seen, [[SUBMISSION], [second]]))
    assert [s.id for s in found] == ["sub-2", "sub-1"]  # oldest first
    assert all("/forms/digital-form/submissions" in str(r.url) for r in seen[1:])
    first = next(s for s in found if s.id == "sub-1")
    assert (first.domain, first.business_name, first.city, first.phone) == (
        "mizangroupllc.com", "Mizan Group LLC", "Centreville, VA", "571.354.8352")
    assert first.unknown_fields == ("Field 3", "Field 4")


def test_the_token_never_appears_in_an_error():
    def refuse(request):
        raise httpx.ConnectError(f"cannot reach with secret-token-123 {request.url}")
    with pytest.raises(intake.IntakeError) as caught:
        intake.fetch("secret-token-123", transport=httpx.MockTransport(refuse))
    assert "secret-token-123" not in str(caught.value) and "<token>" in str(caught.value)
    with pytest.raises(intake.IntakeError, match="WEBFLOW_API_TOKEN is not set"):
        intake.fetch("")


# ---------- the pipeline

@pytest.fixture
def places(tmp_path, monkeypatch):
    """A temporary world: submissions, lead list, logs and seen-state under tmp_path; a fake report run."""
    monkeypatch.setattr(pipeline, "LOG", tmp_path / "logs" / "intake.log")
    leads = tmp_path / "leads.json"
    leads.write_text(json.dumps([{"id": "x", "links": [["Site", "https://listed-shop.example/"]]}]), encoding="utf-8")
    ran = []

    def fake_run(domain_config):
        ran.append(domain_config)
        return report_for(domain_config.name)

    def fake_pdf(report, output):
        path = output / report.domain / "2026-10-09" / "report.pdf"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"%PDF")
        return path
    monkeypatch.setattr(pipeline, "run_checks", fake_run)
    monkeypatch.setattr(pipeline, "write_pdf", fake_pdf)
    return {"tmp": tmp_path, "leads": leads, "ran": ran,
            "kwargs": dict(output=tmp_path / "reports", submissions_path=tmp_path / "submissions.yaml",
                           leads_path=leads, run_log=tmp_path / "logs" / "runs.log",
                           seen_path=tmp_path / "logs" / "seen.json", smtp_factory=FakeSMTP)}


def submission(**changes) -> intake.FormSubmission:
    base = dict(id="sub-1", submitted=date(2026, 10, 9), name="Test Person", email="mo@mizangroupllc.com",
                phone="571.354.8352", business_name="Mizan Group LLC", city="Centreville, VA",
                website="https://www.mizangroupllc.com/")
    return intake.FormSubmission(**{**base, **changes})


def test_a_new_submission_is_recorded_run_and_reviewed_once(places):
    outcome = pipeline.process([submission()], CFG, **places["kwargs"])
    assert outcome.processed == ["mizangroupllc.com"] and outcome.exit_codes == {"mizangroupllc.com": 0}
    records = yaml.safe_load((places["tmp"] / "submissions.yaml").read_text(encoding="utf-8"))["submissions"]
    [record] = [r for r in records if r["domain"] == "mizangroupllc.com"]
    assert record == {"domain": "mizangroupllc.com", "email": "mo@mizangroupllc.com", "received": "2026-10-09",
                      "source": "form", "business_name": "Mizan Group LLC", "city": "Centreville, VA",
                      "phone": "571.354.8352", "submission_id": "sub-1"}
    [config] = places["ran"]
    assert (config.business_name, config.city, config.phone) == ("Mizan Group LLC", "Centreville, VA",
                                                                 "571.354.8352")
    [msg] = FakeSMTP.sent
    assert msg["Subject"].startswith("REVIEW BEFORE SENDING · mizangroupllc.com")
    again = pipeline.process([submission()], CFG, **places["kwargs"])
    assert again.processed == [] and len(FakeSMTP.sent) == 1 and len(places["ran"]) == 1  # never twice


def test_a_lead_list_domain_is_skipped_and_logged_and_never_run(places):
    outcome = pipeline.process([submission(website="https://www.listed-shop.example/")], CFG, **places["kwargs"])
    assert outcome.skipped == ["listed-shop.example: on the lead list (as listed-shop.example)"]
    assert places["ran"] == [] and FakeSMTP.sent == []
    assert "on the lead list" in (places["tmp"] / "logs" / "intake.log").read_text(encoding="utf-8")
    text = (places["tmp"] / "submissions.yaml").read_text(encoding="utf-8") if (
        places["tmp"] / "submissions.yaml").exists() else ""
    assert "listed-shop.example" not in text


def test_a_request_without_a_website_tells_the_reviewer(places):
    pipeline.process([submission(website="")], CFG, **places["kwargs"])
    [msg] = FakeSMTP.sent
    assert msg["Subject"] == "NEW REQUEST WITHOUT A WEBSITE · Mizan Group LLC" and places["ran"] == []


def test_a_failed_run_emails_the_reviewer_the_error(places, monkeypatch):
    def broken(domain_config):
        raise RuntimeError("the network went away")
    monkeypatch.setattr(pipeline, "run_checks", broken)
    outcome = pipeline.process([submission()], CFG, **places["kwargs"])
    assert outcome.failed and outcome.processed == []
    [msg] = FakeSMTP.sent
    assert msg["Subject"].startswith("REPORT RUN FAILED") and "the network went away" in msg.get_content()


def test_a_failed_intake_emails_the_reviewer_the_error(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "LOG", tmp_path / "intake.log")
    pipeline.intake_failed(CFG, "Webflow answered 401 while listing the site's forms", smtp_factory=FakeSMTP)
    [msg] = FakeSMTP.sent
    assert msg["Subject"] == "REPORT RUN FAILED · Reading the /digital form"
    assert "Webflow answered 401" in msg.get_content()


def test_the_cli_runs_intake_from_a_saved_response(places, monkeypatch, tmp_path, capsys):
    from domain_health_check import cli
    saved = tmp_path / "submissions.json"
    saved.write_text(json.dumps({"formSubmissions": [SUBMISSION]}), encoding="utf-8")
    monkeypatch.setattr(cli, "SMTP_FACTORY", FakeSMTP)
    monkeypatch.setattr(cli, "SUBMISSIONS", places["kwargs"]["submissions_path"])
    monkeypatch.setattr(cli, "LEADS_FILE", places["leads"])
    monkeypatch.setattr(cli, "RUN_LOG", places["kwargs"]["run_log"])
    monkeypatch.setattr(intake, "SEEN", places["kwargs"]["seen_path"])
    monkeypatch.setenv("SMTP_USERNAME", "mo@mizangroupllc.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    assert cli.main(["intake", "--submissions-file", str(saved), "-o", str(places["kwargs"]["output"])]) == 0
    out = capsys.readouterr().out
    assert "Reported on mizangroupllc.com (exit code 0); the review went to mo@mizangroupllc.com." in out
    [msg] = FakeSMTP.sent
    assert msg["To"] == "mo@mizangroupllc.com"
