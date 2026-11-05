"""The draft and review agents. Every model call here goes to a fake client: the suite blocks the network, and
what is under test is our side of the workflow, the facts we send, the checks we run on what comes back, and that
every failure falls back to the template. How well the real models do is measured by scripts/eval_review.py."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from domain_health_check import agents, mailer
from domain_health_check.models import EMAIL, LOCAL, SITE, WEBSITE, CheckResult, DomainReport, Status

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
CFG = mailer.MailerConfig("smtp.gmail.com", 587, "mo@mizangroupllc.com", "app-password")


def report() -> DomainReport:
    return DomainReport("example.com", NOW, [
        CheckResult(WEBSITE, "SSL certificate", Status.PASS, "Your certificate is valid for 80 more days.", "Why."),
        CheckResult(SITE, "Main heading", Status.WARN, "Your home page has no main heading.", "Why.", "Add one.",
                    ["No h1 element on the page."]),
        CheckResult(SITE, "Meta description", Status.WARN, "Your home page has no description for search results.",
                    "Why.", "Add one."),
        CheckResult(EMAIL, "DMARC (anti-spoofing policy)", Status.WARN, "No DMARC record was found.", "Why.",
                    "Ask for one."),
        CheckResult(LOCAL, "Reviews", Status.WARN, "We could not look up reviews.", "Why.", ran=False),
    ])


GOOD = {
    "bottom_line": "Nothing on your website is broken today. Two things could help more people find you.",
    "missing": [
        {"check": "Main heading", "text": "Your home page has no main heading, a title that says what the page is "
                                          "about."},
        {"check": "Meta description", "text": "Your home page has no short description for search results."},
    ],
    "next_steps": [
        {"check": "Main heading", "text": "Add one clear heading at the top of your home page."},
        {"check": "Meta description", "text": "Add a one or two sentence description in your site settings."},
    ],
}
PASS = {"passed": True, "reason": "Every claim matches the data.", "unsupported_claims": [], "voice_problems": [],
        "problems": []}  # "problems" is the editor's field; one PASS serves the reviews and the editor
FAIL = {"passed": False, "reason": "One claim is not in the data.",
        "unsupported_claims": ["Your site loads in nine seconds."], "voice_problems": []}


class FakeClient:
    """Stands in for anthropic.Anthropic: messages.create returns the next scripted reply, or raises it."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        stop = "end_turn"
        if isinstance(reply, tuple):
            reply, stop = reply
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=json.dumps(reply))],
                               usage=SimpleNamespace(input_tokens=1000, output_tokens=200), stop_reason=stop)


def draft_from(data: dict) -> agents.Draft:
    return agents._parse_draft(data)


# ---------- the facts: only what the agents need

def test_facts_carry_the_results_and_nothing_about_the_requests_or_the_person():
    f = agents.facts(report())
    assert set(f) == {"domain", "checked_at", "score", "score_out_of", "reading", "complete", "platform",
                      "top_findings", "lead_with", "more_to_look_at", "checks"}
    by_name = {c["name"]: c for c in f["checks"]}
    assert set(by_name["Main heading"]) == {"name", "category", "status", "summary", "certain", "explanation", "fix",
                                            "who"}
    assert set(by_name["SSL certificate"]) == {"name", "category", "status", "summary"}  # nothing to do, so less
    text = json.dumps(f)
    assert "No h1 element" not in text  # technical details stay out
    assert "requests" not in f and "nearby" not in f


def test_why_a_run_was_incomplete_stays_on_this_computer():
    r = report()
    r.incomplete.append(r"The browser could not start: C:\Users\someone\AppData\Local\ms-playwright")
    f = agents.facts(r)
    assert f["complete"] is False and "AppData" not in json.dumps(f)


def test_facts_mark_what_was_not_checked_and_who_can_fix_each_finding():
    by_name = {c["name"]: c for c in agents.facts(report())["checks"]}
    assert by_name["Reviews"]["status"] == "NOT CHECKED"
    assert by_name["Main heading"]["who"] == "You can do this yourself"
    assert by_name["DMARC (anti-spoofing policy)"]["who"] == "We can help with this"


def test_the_report_decides_what_leads_not_the_model():
    assert agents.facts(report())["top_findings"] == ["Main heading", "Meta description"]


# ---------- the code check

def test_a_good_draft_passes_the_code_check():
    assert agents.code_check(draft_from(GOOD), agents.facts(report())) == []


def bad(**changes) -> agents.Draft:
    return draft_from({**GOOD, **changes})


@pytest.mark.parametrize("sentence, problem", [
    ("Your site is fine — mostly.", "dash"),
    ("Your site is fine - mostly.", "dash"),
    ("Your site is great!", "exclamation"),
    ("Your site is fine...", "ellipsis"),
    ("Your site is fine…", "ellipsis"),
    ("This is urgent.", '"urgent"'),
    ("This is a critical gap.", '"critical"'),
    ("We can fix it for $99.", "price"),
    ("We will check your site again next month.", "check again"),
    ("We can recheck it for you.", "check again"),
    ("Your competitors are ahead.", "competitors"),
    ("I looked at your site.", "First person"),
    ("Your site loads in 9.7 seconds.", "number 9.7"),
    ("Your site scored 88 out of 100.", "number 88"),
    ("Your site is VERY slow.", '"VERY"'),
    ("This is a WARN, so it could be better.", 'status label "WARN"'),
    ("The one visitors are most likely to notice is speed.", '"most likely"'),
    ("Your website is in very good shape.", '"very good"'),
    ("The site is in healthy shape overall.", '"healthy shape"'),
    ("The site is doing well overall.", '"doing well"'),
    ("The overall picture is of a site in sound shape.", '"sound shape"'),
    ("None of them needs rushing.", '"rushing"'),
    ("Some checks were not checked, and we say which below.", "not checked"),
    ("PageSpeed Insights is Google's free tool that tests how fast a page loads.", "costs nothing"),
    ("It costs nothing to try.", "costs nothing"),
    ("You can use it at no cost.", "costs nothing"),
    ("Here is what is costing you customers.", "pressure"),
    ("Adding one is also part of a tune-up on our price list.", "sales push"),
])
def test_the_code_check_catches_every_rule_a_program_can_check(sentence, problem):
    problems = agents.code_check(bad(bottom_line=sentence), agents.facts(report()))
    assert any(problem in p for p in problems), problems


def test_numbers_and_acronyms_from_the_report_are_allowed():
    ok = bad(bottom_line="Your site scored 39 out of 100. Your SSL certificate is valid for 80 more days.")
    assert agents.code_check(ok, agents.facts(report())) == []


def test_feel_free_is_an_idiom_and_free_is_allowed_when_the_report_says_it():
    facts = agents.facts(report())
    assert agents.code_check(bad(bottom_line="Feel free to ask us about any of this."), facts) == []
    facts["checks"][0]["summary"] += " The test is free."
    assert agents.code_check(bad(bottom_line="The test is free."), facts) == []


def test_a_check_the_report_does_not_have_is_caught():
    problems = agents.code_check(bad(missing=GOOD["missing"] + [{"check": "Online checkout", "text": "Broken."}]),
                                 agents.facts(report()))
    assert any('does not have: "Online checkout"' in p for p in problems)


def test_a_passing_or_unchecked_check_listed_as_missing_is_caught():
    for name, status in (("SSL certificate", "PASS"), ("Reviews", "NOT CHECKED")):
        problems = agents.code_check(bad(missing=GOOD["missing"] + [{"check": name, "text": "A problem."}]),
                                     agents.facts(report()))
        assert any(f'lists "{name}", but the report says {status}' in p for p in problems), problems


def test_leaving_out_a_top_finding_is_caught():
    problems = agents.code_check(bad(missing=GOOD["missing"][:1]), agents.facts(report()))
    assert any('leaves out "Meta description"' in p for p in problems)


def test_who_can_fix_each_step_is_added_by_code():
    text = draft_from(GOOD).text(agents.facts(report()))
    assert "(You can do this yourself.)" in text
    # DMARC is a warning the message does not lead with; the unchecked Reviews row is not counted.
    assert "The attached report lists 1 more thing that could be better." in text


def test_code_writes_the_greeting_the_opening_and_the_signature_and_none_of_it_is_reviewed():
    f = agents.facts(report())
    reviewed = draft_from(GOOD).text(f)
    full = agents.owner_email(draft_from(GOOD), f, "Jane Doe")
    opening = "Thank you for asking us to look at example.com. Your full report is attached."
    assert full.startswith(f"Hello Jane,\n\n{opening}\n\nThe short version:")
    assert opening not in reviewed and "Hello" not in reviewed and "Mizan Digital Services" not in reviewed


# ---------- the workflow

def test_a_good_draft_that_passes_three_reviews_passes(tmp_path):
    client = FakeClient(GOOD, PASS, PASS, PASS, PASS)
    outcome = agents.run(report(), client, output_dir=tmp_path)
    assert outcome.passed and outcome.reason == "Passed the code check, 3 of 3 reviews and the editor."
    draft_call, *review_calls, editor_call = client.calls
    assert draft_call["model"] == agents.DRAFT_MODEL
    assert [c["model"] for c in review_calls] == [agents.REVIEW_MODEL] * 3
    assert editor_call["model"] == agents.EDITOR_MODEL and editor_call["system"] == agents.EDITOR_SYSTEM
    for call in client.calls:  # structured outputs, never a forced tool call
        assert call["output_config"]["format"]["type"] == "json_schema" and "tool_choice" not in call
    assert "example.com" in draft_call["messages"][0]["content"]
    assert outcome.cost == pytest.approx(5 * 0.004)  # Sonnet writes, reviews and edits: 1,000 in, 200 out a call


def test_one_failed_review_of_three_fails_the_draft():
    outcome = agents.run(report(), FakeClient(GOOD, PASS, FAIL, PASS))
    assert outcome.status == "failed"
    assert "only 2 of 3 reviews" in outcome.reason
    assert outcome.flagged() == ["Your site loads in nine seconds."]


def test_a_draft_that_breaks_a_rule_is_never_sent_for_review():
    client = FakeClient({**GOOD, "bottom_line": "Your site is great!"})
    outcome = agents.run(report(), client)
    assert outcome.status == "failed" and len(client.calls) == 1  # the draft only; no review was paid for
    assert "no review was run" in outcome.reason


@pytest.mark.parametrize("reply", [
    RuntimeError("connection refused"),
    ({"bottom_line": "Half a"}, "max_tokens"),  # stopped early
    ({"bottom_line": "x"}, "refusal"),
    {"bottom_line": 3, "missing": [], "next_steps": [], "email_body": ""},  # wrong shape
])
def test_a_broken_draft_call_is_an_error_and_never_raises(reply):
    outcome = agents.run(report(), FakeClient(reply))
    assert outcome.status == "error" and not outcome.passed


def test_a_review_that_cannot_run_counts_as_a_failed_review():
    outcome = agents.run(report(), FakeClient(GOOD, PASS, RuntimeError("overloaded"), PASS))
    assert outcome.status == "failed"
    assert "This review could not run: RuntimeError: overloaded" in outcome.reason


def test_off_without_the_switch_or_the_key(monkeypatch):
    monkeypatch.delenv(agents.SWITCH, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "not-a-real-key")
    outcome = agents.run(report())
    assert outcome.status == "off" and "AI_DRAFTS" in outcome.reason
    monkeypatch.setenv(agents.SWITCH, "on")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert "ANTHROPIC_API_KEY" in agents.run(report()).reason
    # The --ai flag on a manual run is its own decision, so it does not need the switch, but still needs the key.
    assert "ANTHROPIC_API_KEY" in agents.run(report(), require_switch=False).reason


def test_the_run_log_keeps_everything_the_eval_needs(tmp_path):
    agents.run(report(), FakeClient(GOOD, PASS, PASS, FAIL), output_dir=tmp_path)
    log = json.loads((tmp_path / "example.com" / "2026-11-03" / "ai.json").read_text(encoding="utf-8"))
    assert log["status"] == "failed" and log["facts"]["domain"] == "example.com"
    assert log["draft"]["bottom_line"] == GOOD["bottom_line"]
    assert len(log["reviews"]) == 3 and len(log["usage"]) == 4
    assert "requests" not in json.dumps(log["facts"])


# ---------- the review email

def test_a_passed_draft_replaces_the_template_in_the_review_email():
    outcome = agents.run(report(), FakeClient(GOOD, PASS, PASS, PASS, PASS))
    msg = mailer.review_message(CFG, report(), None, 0, "test", "Test Person", "Example LLC", outcome)
    body = msg.get_content()
    assert msg["To"] == mailer.REVIEWER
    assert "written by AI; Passed the code check, 3 of 3 reviews and the editor." in body
    assert "Hello Test," in body and GOOD["bottom_line"] in body
    assert "AI cost: about $" in body


def test_a_failed_draft_keeps_the_template_and_says_why():
    outcome = agents.run(report(), FakeClient(GOOD, PASS, FAIL, PASS))
    body = mailer.review_message(CFG, report(), None, 0, "test", ai=outcome).get_content()
    assert "Draft message to the business (not sent):" in body
    assert GOOD["bottom_line"] not in body
    assert "AI draft: failed." in body and "- Your site loads in nine seconds." in body


# ---------- the eval script, offline

def test_the_eval_plants_ten_claims_and_measures_each_layer(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "eval_review", Path(__file__).parent.parent / "scripts" / "eval_review.py")
    eval_review = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(eval_review)

    agents.run(report(), FakeClient(GOOD, PASS, PASS, PASS, PASS), output_dir=tmp_path)
    log = tmp_path / "example.com" / "2026-11-03" / "ai.json"
    # A reviewer that passes everything: whatever is caught here, the code check caught.
    replies = [PASS] * 33
    monkeypatch.setattr(agents, "make_client", lambda require_switch=True: (FakeClient(*replies), None))
    assert eval_review.main([str(log)]) == 0
    summary = json.loads(log.with_name(f"eval-{agents.REVIEW_MODEL}.json").read_text(encoding="utf-8"))
    assert summary["planted"] == 10 and summary["control_passed"] is True
    assert summary["caught_by_ai"] == 0
    # The plants are worded to slip past the code check, so the eval measures the AI reviewer. Only the wrong score
    # trips it, since the number is not in the report.
    assert {r["kind"] for r in summary["rows"] if r["code_caught"]} == {"a wrong score"}
    assert "Planted 10:" in capsys.readouterr().out


def test_a_step_for_something_the_website_platform_sets_is_caught():
    f = agents.facts(report())
    for c in f["checks"]:
        if c["name"] == "Meta description":
            c["who"] = agents.WHO["platform"]
    problems = agents.code_check(draft_from(GOOD), f)
    assert problems == ['What would help asks the owner to change "Meta description", which their website platform '
                        "sets."]


def test_redraft_reuses_the_saved_facts_and_never_runs_the_report(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "redraft", Path(__file__).parent.parent / "scripts" / "redraft.py")
    redraft = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redraft)

    agents.run(report(), FakeClient(GOOD, PASS, PASS, FAIL), output_dir=tmp_path)
    log = tmp_path / "example.com" / "2026-11-03" / "ai.json"
    before = log.read_text(encoding="utf-8")
    monkeypatch.setattr(agents, "make_client", lambda require_switch=True: (FakeClient(GOOD, PASS, PASS, PASS, PASS), None))
    assert redraft.main([str(log)]) == 0
    out = capsys.readouterr().out
    assert "AI draft: passed." in out and "Thank you for asking us to look at example.com." in out
    saved = json.loads(log.with_name("ai-redraft.json").read_text(encoding="utf-8"))
    assert saved["status"] == "passed" and saved["facts"]["domain"] == "example.com"
    assert log.read_text(encoding="utf-8") == before  # the original run log is left alone


def test_the_writer_and_the_reviewer_hold_the_same_rule_for_explaining_a_term():
    # Run 5 failed one review because the reviewer read "same sentence" more strictly than the writer did.
    rule = "the same sentence or the one right after it"
    assert rule in " ".join(agents.DRAFT_SYSTEM.split())
    assert rule in " ".join(agents.REVIEW_SYSTEM.split())


def test_redraft_times_reports_the_pass_rate_and_keeps_the_first_passing_draft(tmp_path, monkeypatch, capsys):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "redraft", Path(__file__).parent.parent / "scripts" / "redraft.py")
    redraft = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redraft)

    agents.run(report(), FakeClient(GOOD, PASS, PASS, PASS, PASS), output_dir=tmp_path)
    log = tmp_path / "example.com" / "2026-11-03" / "ai.json"
    client = FakeClient(GOOD, PASS, FAIL, PASS, GOOD, PASS, PASS, PASS, PASS, GOOD, PASS, PASS, FAIL)
    monkeypatch.setattr(agents, "make_client", lambda require_switch=True: (client, None))
    assert redraft.main([str(log), "--times", "3"]) == 0
    assert "Passed 1 of 3." in capsys.readouterr().out
    saved = json.loads(log.with_name("ai-redraft.json").read_text(encoding="utf-8"))
    assert saved["times"] == 3 and saved["passed"] == 1 and len(saved["attempts"]) == 3
    assert saved["status"] == "passed" and saved["draft"] is not None  # the eval plants claims in this one
    assert [a["status"] for a in saved["attempts"]] == ["failed", "passed", "failed"]


def test_redraft_can_measure_a_different_review_model(tmp_path, monkeypatch):
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "redraft", Path(__file__).parent.parent / "scripts" / "redraft.py")
    redraft = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(redraft)

    agents.run(report(), FakeClient(GOOD, PASS, PASS, PASS, PASS), output_dir=tmp_path)
    log = tmp_path / "example.com" / "2026-11-03" / "ai.json"
    client = FakeClient(GOOD, PASS, PASS, PASS, PASS)
    monkeypatch.setattr(agents, "make_client", lambda require_switch=True: (client, None))
    assert redraft.main([str(log), "--review-model", agents.DRAFT_MODEL]) == 0
    assert [c["model"] for c in client.calls] == [agents.DRAFT_MODEL] * 4 + [agents.EDITOR_MODEL]
    saved = json.loads(log.with_name("ai-redraft.json").read_text(encoding="utf-8"))
    assert saved["review_model"] == agents.DRAFT_MODEL


# ---------- what the message leads with (Nov 4: a real draft listed all 13 warnings and repeated a step)

def test_the_message_leads_with_the_top_findings_and_anything_broken_and_counts_the_rest():
    r = report()
    r.results.append(CheckResult(WEBSITE, "TLS version", Status.FAIL, "An old TLS version is in use.", "Why.", "Fix."))
    f = agents.facts(r)
    assert f["lead_with"] == f["top_findings"] + ["TLS version"]
    assert f["more_to_look_at"] == 1  # DMARC; the unchecked Reviews row is not counted


def test_a_warning_the_message_does_not_lead_with_is_caught():
    extra = {"check": "DMARC (anti-spoofing policy)", "text": "Ask for a DMARC record."}
    for key in ("missing", "next_steps"):
        problems = agents.code_check(bad(**{key: GOOD[key] + [extra]}), agents.facts(report()))
        assert any('"DMARC (anti-spoofing policy)", which the message does not lead with' in p for p in problems)


def test_the_same_step_twice_is_caught():
    twice = GOOD["next_steps"] + [{"check": "Meta description", "text": "Add one  clear heading at the top of "
                                                                         "your home page."}]
    problems = agents.code_check(bad(next_steps=twice), agents.facts(report()))
    assert any("says the same thing twice" in p for p in problems)


def test_the_count_line_reads_right_with_and_without_a_list():
    assert agents.more_line(1, True) == "The attached report lists 1 more thing that could be better."
    assert agents.more_line(4, False) == "The attached report lists 4 things that could be better."


# ---------- the editor: judges the whole message, after the reviews have checked every fact

EDIT_FAIL = {"passed": False, "reason": "Rule 2: the same point is made twice.", "problems": ["Says twice to add a heading."]}


def test_the_editor_runs_only_after_every_review_passes_and_its_no_sends_the_template():
    client = FakeClient(GOOD, PASS, PASS, PASS, EDIT_FAIL)
    outcome = agents.run(report(), client)
    assert outcome.status == "failed" and "not the editor: Rule 2" in outcome.reason
    assert "Says twice to add a heading." in outcome.flagged()
    skipped = FakeClient(GOOD, PASS, FAIL, PASS)
    assert agents.run(report(), skipped).editor is None and len(skipped.calls) == 4


def test_the_editor_sees_the_message_but_never_the_report_data():
    client = FakeClient(GOOD, PASS, PASS, PASS, PASS)
    agents.run(report(), client)
    prompt = client.calls[-1]["messages"][0]["content"]
    assert "The short version:" in prompt and '"checks"' not in prompt and '"score"' not in prompt


def test_an_editor_that_cannot_run_fails_closed():
    outcome = agents.run(report(), FakeClient(GOOD, PASS, PASS, PASS, RuntimeError("overloaded")))
    assert outcome.status == "failed" and "The editor could not run" in outcome.reason


def test_facts_saved_before_lead_with_get_the_same_lead_and_count_as_today():
    today = agents.facts(report())
    saved = {k: v for k, v in today.items() if k not in ("lead_with", "more_to_look_at")}
    upgraded = agents.upgrade_facts(saved)
    assert upgraded["lead_with"] == today["lead_with"] and upgraded["more_to_look_at"] == today["more_to_look_at"]
    assert agents.upgrade_facts(today) == today


def test_the_same_sentence_on_every_item_is_caught():
    padded = [{"check": i["check"], "text": i["text"] + " This could be better, but it is not broken."}
              for i in GOOD["missing"]]
    problems = agents.code_check(bad(missing=padded), agents.facts(report()))
    assert any('appears in 2 items: "this could be better, but it is not broken."' in p for p in problems)


def test_the_writer_never_sees_costing_you_customers():
    # Told not to quote the report's heading, the writer said it in other words in 6 of 6 drafts. It never sees it.
    assert agents.calm("Nothing on your site is broken. Here is what is costing you customers.") == (
        "Nothing on your site is broken. Some things could be better.")
    assert agents.calm("Nothing on your site is broken. Two things could be costing you customers.") == (
        "Nothing on your site is broken. Two things could be better.")
    saved = {**agents.facts(report()), "reading": "Nothing on your site is broken. Here is what is costing you customers."}
    assert "costing" not in agents.upgrade_facts(saved)["reading"]


def test_a_fail_outside_the_top_findings_can_never_be_left_out():
    # Found by an independent audit: code_check enforced only top_findings, so a draft listing nothing hid a FAIL,
    # and the closing line then said nothing needed action.
    broken = report()
    broken.results.append(CheckResult(EMAIL, "Mail servers (MX)", Status.FAIL, "No mail servers are listed.", "Why.",
                                      "Ask for them."))
    f = {**agents.facts(broken), "top_findings": []}
    f["lead_with"], f["more_to_look_at"] = agents._lead_with(
        [{"name": c["name"], "ran": c["status"] != "NOT CHECKED", "status": c["status"]} for c in f["checks"]], [])
    assert f["lead_with"] == ["Mail servers (MX)"]
    empty = agents.Draft("Something on your site is broken today.", [], [])
    assert any("Mail servers (MX)" in p and "must lead with" in p for p in agents.code_check(empty, f))


def test_a_clean_site_still_leads_with_the_reports_first_findings():
    # A site with nothing broken and nothing costing customers got a message saying only "see the report", and the
    # editor failed it 5 of 5 for giving no next step. It now leads with the report's own first findings.
    clean = DomainReport("example.com", NOW, [
        CheckResult(WEBSITE, "SSL certificate", Status.PASS, "Valid.", "Why."),
        CheckResult(EMAIL, "DMARC (anti-spoofing policy)", Status.WARN, "Monitoring only.", "Why.", "Ask."),
        CheckResult(WEBSITE, "DNSSEC", Status.WARN, "Not on.", "Why.", "Ask."),
    ])
    f = agents.facts(clean)
    assert f["top_findings"] == [] and len(f["lead_with"]) == 2 and f["more_to_look_at"] == 0
    saved = {**f, "lead_with": []}
    assert agents.upgrade_facts(saved)["lead_with"] == f["lead_with"]


def test_a_billed_call_that_fails_still_counts_in_the_cost(monkeypatch):
    # Found by the second audit: a max_tokens stop dropped its usage, so the email said no AI calls were made.
    def stopped(*a, **k):
        raise agents.CallFailed("the model stopped early (max_tokens)", agents.Usage(agents.DRAFT_MODEL, 7000, 8000))
    monkeypatch.setattr(agents, "_call", stopped)
    outcome = agents._run(agents.facts(report()), object(), 3)
    assert outcome.status == "error" and outcome.cost > 0


def test_the_ai_step_stops_when_it_passes_its_time_budget(monkeypatch):
    # A stalled API must never hold the hourly run past the watchdog, which would kill it and lose the submission.
    f = agents.facts(report())
    good = agents.Draft("Nothing on your site is broken today.", [], [])
    monkeypatch.setattr(agents, "draft", lambda facts, client: (good, agents.Usage(agents.DRAFT_MODEL, 1, 1)))
    monkeypatch.setattr(agents, "code_check", lambda d, facts: [])
    monkeypatch.setattr(agents, "_over_budget", lambda started: True)
    monkeypatch.setattr(agents, "review", lambda *a, **k: pytest.fail("reviews ran past the budget"))
    outcome = agents._run(f, object(), 3)
    assert outcome.status == "error" and "budget" in outcome.reason
