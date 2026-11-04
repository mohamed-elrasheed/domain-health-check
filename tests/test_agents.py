"""The draft and review agents, against a fake Anthropic client. No socket opens; conftest fails the test if one does.

The fake returns whatever each test scripts, so these tests prove the workflow, not the models: what is sent, what
is checked in code, when the template takes over, and that nothing reaches anyone but the reviewer.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from domain_health_check import agents, mailer
from domain_health_check.models import SITE, CheckResult, DomainReport, Status
from domain_health_check.report import record

NOW = datetime(2026, 11, 3, 9, 30, tzinfo=timezone.utc)


def report() -> DomainReport:
    return DomainReport("example.com", NOW, [
        CheckResult(SITE, "Main heading", Status.WARN, "Your home page has no main heading.", "Why.",
                    "Ask for one main heading that says what you do.", ["no h1"]),
        CheckResult(SITE, "Page title", Status.PASS, "Your page title is 42 characters.", "Why."),
    ])


GOOD = agents.Draft(bottom_line="Nothing on your site is broken. One thing could be better.",
                    missing=["Your home page has no main heading."],
                    next_steps=[agents.Step(action="Ask for one main heading that says what you do.", who="us")])
PASS = agents.Review(passed=True, reason="Every sentence matches the record.", unsupported_claims=[],
                     voice_problems=[])


class FakeClient:
    """Stands in for anthropic.Anthropic(). Each parse() call pops the next scripted answer."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []
        self.messages = SimpleNamespace(parse=self.parse)

    def parse(self, *, model, max_tokens, system, messages, output_format):
        self.calls.append({"model": model, "system": system, "user": messages[0]["content"],
                           "shape": output_format})
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return SimpleNamespace(parsed_output=answer, stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=100, output_tokens=20))


def test_a_clean_draft_and_three_passing_reviews_is_used():
    client = FakeClient(GOOD, PASS, PASS, PASS)
    out = agents.ai_draft(record(report()), client)
    assert out.passed and out.reasons == [] and out.flagged == []
    assert [c["model"] for c in client.calls] == [agents.DRAFT_MODEL] + [agents.REVIEW_MODEL] * 3
    assert "Your home page has no main heading." in out.body and "We can help with this." in out.body
    assert out.usage[agents.REVIEW_MODEL] == {"calls": 3, "input_tokens": 300, "output_tokens": 60}


def test_one_failing_review_out_of_three_means_the_template():
    fail = agents.Review(passed=False, reason="The bottom line says broken; the record says WARN.",
                         unsupported_claims=["Nothing on your site is broken."], voice_problems=[])
    out = agents.ai_draft(record(report()), FakeClient(GOOD, PASS, fail, PASS))
    assert not out.passed and out.body == ""
    assert out.reasons == [fail.reason] and out.flagged == ["Nothing on your site is broken."]


def test_a_review_that_passes_but_quotes_a_problem_is_a_fail():
    """A reviewer that says passed yet lists an unsupported claim contradicts itself. Contradiction is a fail."""
    odd = agents.Review(passed=True, reason="Fine.", unsupported_claims=["Your home page has no main heading."],
                        voice_problems=[])
    assert not agents.ai_draft(record(report()), FakeClient(GOOD, PASS, odd, PASS)).passed


@pytest.mark.parametrize("bad, why", [
    ("Your site has 12 broken links.", "number not in the record '12'"),
    ("This is urgent.", "banned word 'urgent'"),
    ("Your heading is missing!", "exclamation mark"),
    ("Your heading is missing — add one.", "dash used as punctuation"),
    ("WARNING your heading is missing.", "all capitals not in the record 'WARNING'"),
    ("We will run the checks again next month.", "promise to run the checks again"),
    ("A tune-up costs $250.", "price"),
    ("It isn't there.", "contraction"),
    ("I found no heading.", "first person singular"),
])
def test_the_code_check_catches_a_planted_rule_break_before_any_review_is_paid_for(bad, why):
    planted = GOOD.model_copy(update={"missing": [bad]})
    client = FakeClient(planted)  # no review answers scripted: a review call would fail the test
    out = agents.ai_draft(record(report()), client)
    assert not out.passed and len(client.calls) == 1
    assert any(line.startswith(why) for line in out.flagged), out.flagged


def test_numbers_and_capitals_from_the_record_are_allowed():
    ok = GOOD.model_copy(update={"missing": ["Your page title is 42 characters, which is fine for SSL."]})
    f = agents.facts({**record(report()), "reading": "SSL is fine."})
    assert agents.voice_lint(ok, f) == []


@pytest.mark.parametrize("error", [RuntimeError("API down"), ConnectionError("no route")])
def test_any_error_falls_back_to_the_template_and_never_raises(error):
    out = agents.ai_draft(record(report()), FakeClient(error))
    assert not out.passed and out.reasons == [f"{type(error).__name__}: {error}"]


def test_the_models_see_the_findings_but_not_who_asked_or_the_technical_details():
    client = FakeClient(GOOD, PASS, PASS, PASS)
    agents.ai_draft(record(report()), client)
    sent = client.calls[0]["user"]
    shown = json.loads(sent.split("\n", 1)[1])
    assert set(shown) == {"domain", "checked_at", "website_loaded", "score", "reading", "incomplete", "results"}
    assert set(shown["results"][0]) == set(agents.RESULT_FIELDS)
    assert "no h1" not in sent and "requests" not in shown  # details and the request log stay home


def test_the_gate_is_off_unless_set_to_on(monkeypatch):
    monkeypatch.delenv(agents.GATE, raising=False)
    assert not agents.enabled()
    monkeypatch.setenv(agents.GATE, "yes")
    assert not agents.enabled()
    monkeypatch.setenv(agents.GATE, "on")
    assert agents.enabled()


def test_the_command_refuses_to_send_anything_with_the_gate_off(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv(agents.GATE, raising=False)
    path = tmp_path / "report.json"
    path.write_text(json.dumps(record(report()), default=str), encoding="utf-8")
    assert agents.main([str(path)]) == 2
    assert "nothing was sent" in capsys.readouterr().out
    assert not (tmp_path / agents.OUTCOME_FILE).exists()


def test_the_outcome_is_saved_for_the_eval_log(tmp_path):
    out = agents.ai_draft(record(report()), FakeClient(GOOD, PASS, PASS, PASS))
    saved = json.loads(agents.save(out, tmp_path).read_text(encoding="utf-8"))
    assert saved["passed"] and len(saved["reviews"]) == 3 and saved["draft"]["missing"] == GOOD.missing


# ---------- what Mo sees in the review email

def body_of(msg) -> str:
    return msg.get_body(("plain",)).get_content()


def test_a_passed_draft_is_shown_with_the_template_for_comparison():
    out = agents.ai_draft(record(report()), FakeClient(GOOD, PASS, PASS, PASS))
    msg = mailer.review_message(CFG_REAL, report(), None, 0, "test", "Test Person", "Shop", out)
    text = body_of(msg)
    assert msg["To"] == mailer.REVIEWER
    assert "written by AI and passed" in text and "Hello Test," in text
    assert "Template draft for comparison:" in text and agents.DRAFT_MODEL in text


def test_a_failed_draft_shows_the_template_and_why():
    out = agents.ai_draft(record(report()), FakeClient(GOOD.model_copy(update={"bottom_line": "This is urgent."})))
    text = body_of(mailer.review_message(CFG_REAL, report(), None, 0, "test", ai=out))
    assert "The AI draft did not pass, so this is the template." in text
    assert "banned word 'urgent'" in text and "This is urgent." not in text.split("Draft message")[1]


def test_with_ai_off_the_review_email_is_unchanged():
    before = body_of(mailer.review_message(CFG_REAL, report(), None, 0, "test"))
    assert "AI" not in before and "Draft message to the business (not sent):" in before


CFG_REAL = mailer.MailerConfig("smtp.gmail.com", 587, username="mo@mizangroupllc.com", password="x")
