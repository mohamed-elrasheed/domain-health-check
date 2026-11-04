from dataclasses import replace

import pytest

from domain_health_check.checks.site import ai_access
from domain_health_check.fetcher import FetchedFile
from domain_health_check.models import Status

ROBOTS_URL = "https://www.example.com/robots.txt"


def with_robots(page, text="", status=200):
    return replace(page, robots=FetchedFile(ROBOTS_URL, status, text))


def search_tokens():
    return {c.token for c in ai_access.load() if c.role == "search"}


# ---------- The config

def test_every_robot_in_the_config_is_cited():
    crawlers = ai_access.load()
    assert {c.role for c in crawlers} == {"search", "training"}
    assert {"OAI-SearchBot", "Claude-SearchBot", "PerplexityBot"} <= search_tokens()
    # Robots their makers say may ignore robots.txt cannot be blocked by it, so they are disabled, not checked.
    assert not {"ChatGPT-User", "Perplexity-User"} & {c.token for c in crawlers}


@pytest.mark.parametrize("entry, problem", [
    ("{token: X, company: Y, role: search}", "either a source"),
    ("{token: X, company: Y, role: search, source: a, disabled: b}", "either a source"),
    ("{token: X, company: Y, role: ads, source: a}", "a role of"),
    ("{company: Y, role: search, source: a}", "needs a token"),
])
def test_the_loader_refuses_an_uncited_or_malformed_robot(tmp_path, entry, problem):
    path = tmp_path / "ai_crawlers.yaml"
    path.write_text(f"crawlers:\n  - {entry}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=problem):
        ai_access.load(path)


# ---------- The check

def test_mizan_lets_ai_search_in(mizan_page):
    [result] = ai_access.check_ai_access(mizan_page)
    assert result.status is Status.PASS


def test_nothing_blocked_passes(mizan_page):
    [result] = ai_access.check_ai_access(with_robots(mizan_page, "User-agent: *\nAllow: /\n"))
    assert result.status is Status.PASS
    assert result.fix == ""
    assert all(line.endswith("allowed") for line in result.details)


def test_one_search_robot_blocked_warns_and_names_it(mizan_page):
    text = "User-agent: OAI-SearchBot\nDisallow: /\n\nUser-agent: *\nAllow: /\n"
    [result] = ai_access.check_ai_access(with_robots(mizan_page, text))
    assert result.status is Status.WARN
    assert "OpenAI (OAI-SearchBot)" in result.summary
    assert f"1 of {len(search_tokens())}" in result.summary
    assert result.measure == pytest.approx((len(search_tokens()) - 1) / len(search_tokens()))
    assert "OAI-SearchBot (OpenAI, search): blocked by Disallow: /" in result.details


def test_blocking_every_robot_warns_for_every_search_robot(mizan_page):
    [result] = ai_access.check_ai_access(with_robots(mizan_page, "User-agent: *\nDisallow: /\n"))
    assert result.status is Status.WARN
    n = len(search_tokens())
    assert f"{n} of {n}" in result.summary
    assert result.measure == 0


def test_blocking_only_training_robots_passes_and_says_so(mizan_page):
    text = "User-agent: GPTBot\nDisallow: /\n\nUser-agent: ClaudeBot\nDisallow: /\n"
    [result] = ai_access.check_ai_access(with_robots(mizan_page, text))
    assert result.status is Status.PASS
    assert any("training AI models" in line and "does not affect" in line for line in result.details)


def test_a_rule_for_one_folder_does_not_block_the_home_page(mizan_page):
    text = "User-agent: PerplexityBot\nDisallow: /private/\n"
    [result] = ai_access.check_ai_access(with_robots(mizan_page, text))
    assert result.status is Status.PASS


@pytest.mark.parametrize("status", [404, 410])
def test_no_robots_file_passes(mizan_page, status):
    [result] = ai_access.check_ai_access(with_robots(mizan_page, status=status))
    assert result.status is Status.PASS
    assert "no robots.txt" in result.summary


@pytest.mark.parametrize("status", [403, 429, 500])
def test_an_unreadable_robots_file_is_not_checked(mizan_page, status):
    [result] = ai_access.check_ai_access(with_robots(mizan_page, status=status))
    assert result.ran is False
    assert "could not read" in result.summary


def test_no_robots_file_read_at_all_is_not_checked(mizan_page):
    [result] = ai_access.check_ai_access(replace(mizan_page, robots=None))
    assert result.ran is False


def test_never_fails():
    # FAIL means broken today. Blocking AI search can be a choice, so the worst this check says is WARN.
    for text in ("User-agent: *\nDisallow: /\n", "User-agent: *\nDisallow: /*\n"):
        assert ai_access.evaluate_ai_access(text).status is Status.WARN


@pytest.mark.parametrize("text", ["", "User-agent: *\nDisallow: /\n", "User-agent: GPTBot\nDisallow: /\n"])
def test_copy_follows_the_writing_rules(text):
    result = ai_access.evaluate_ai_access(text)
    for field in (result.summary, result.explanation, result.fix, *result.details):
        assert "—" not in field and "–" not in field and "!" not in field and "..." not in field
