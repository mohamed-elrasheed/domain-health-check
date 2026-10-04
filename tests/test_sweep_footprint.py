"""How often sweep touches a site: the cache, the seven-day cooldown, and backing off after a 429."""

from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from domain_health_check.sweep import cli, footprint, load
from domain_health_check.sweep.footprint import Footprint
from domain_health_check.sweep.models import Business, Page, Visit
from domain_health_check.sweep.run import Sweeper

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
GOOD = (SYNTHETIC / "good.html").read_text(encoding="utf-8")
MONDAY = date(2026, 10, 5)
LEADS = [{"id": "auto-one", "n": "Example Auto Care", "cat": "auto", "links": [["Site", "https://www.example.com/"]]}]


def transport(routes: dict[str, object]):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        answer = routes.get(str(request.url), routes.get(request.url.path, httpx.Response(404)))
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        return answer

    mock = httpx.MockTransport(handler)
    mock.seen = seen
    return mock


def their_site(**overrides):
    routes = {cli.OWN_SITE: httpx.Response(200, text="User-agent: *\n"),
              "https://www.example.com/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /\n"),
              "https://www.example.com/": httpx.Response(200, html=GOOD)}
    routes.update(overrides)
    return transport(routes)


def to_them(mock) -> list[str]:
    return [u for u in mock.seen if "example.com" in u]


@pytest.fixture
def run(tmp_path):
    leads = tmp_path / "leads.json"
    leads.write_text(json.dumps(LEADS), encoding="utf-8")
    out = tmp_path / "sweep-output"

    def go(mock, today: date, *extra: str) -> int:
        return cli.main([str(leads), "-o", str(out), "--no-browser", *extra], transport=mock, today=today)
    go.out = out
    return go


def state(out: Path) -> dict:
    return json.loads((out / "_state.json").read_text(encoding="utf-8"))


def test_a_rerun_the_same_week_requests_nothing(run, capsys):
    first = their_site()
    assert run(first, MONDAY) == 0
    assert to_them(first) == ["https://www.example.com/robots.txt", "https://www.example.com/"]
    again = their_site()
    assert run(again, MONDAY + timedelta(days=3)) == 0
    assert to_them(again) == []
    assert "[from the visit on 2026-10-05]" in capsys.readouterr().out
    assert state(run.out)["example.com"] == {"last_fetch": "2026-10-05", "retry_after": "2026-10-12",
                                             "reason": "fetched"}


def test_the_same_weekday_next_week_fetches_again(run):
    run(their_site(), MONDAY)
    next_week = their_site()
    run(next_week, MONDAY + timedelta(days=7))
    assert len(to_them(next_week)) == 2


def test_a_cooling_domain_with_nothing_cached_is_deferred_and_redecided(run, capsys):
    run(their_site(), MONDAY)
    for day in (run.out / "_cache").iterdir():  # as if this week's visit predated the cache
        for f in day.iterdir():
            f.unlink()
    later = their_site()
    assert run(later, MONDAY + timedelta(days=2)) == 0
    assert to_them(later) == []
    out = capsys.readouterr().out
    assert "auto-one" in out and "good" in out and "[deferred: 2026-10-12]" in out
    summary = json.loads((run.out / "sweep-2026-10-07.json").read_text())
    assert summary[0]["verdict"] == "good" and summary[0]["deferred_until"] == "2026-10-12"


def test_force_fetches_anyway(run):
    run(their_site(), MONDAY)
    forced = their_site()
    run(forced, MONDAY + timedelta(days=1), "--force")
    assert len(to_them(forced)) == 2


def test_a_429_backs_the_domain_off(run):
    limited = their_site(**{"https://www.example.com/robots.txt": httpx.Response(429)})
    run(limited, MONDAY)
    entry = state(run.out)["example.com"]
    assert entry["retry_after"] == "2026-11-04" and "429" in entry["reason"]
    later = their_site()
    run(later, MONDAY + timedelta(days=10))
    assert to_them(later) == []  # nothing cached from a failed visit, and still backed off


def test_retry_after_longer_than_the_back_off_is_honored(run):
    seconds = str(45 * 86400)
    limited = their_site(**{"https://www.example.com/": httpx.Response(429, headers={"Retry-After": seconds})})
    run(limited, MONDAY)
    assert state(run.out)["example.com"]["retry_after"] == (MONDAY + timedelta(days=45)).isoformat()


@pytest.mark.parametrize("value, days", [("3600", 1), ("Fri, 20 Nov 2026 00:00:00 GMT", 46), ("soon", 0), ("", 0)])
def test_retry_after_forms(value, days):
    assert footprint._retry_after_days(value, MONDAY) == days


def test_first_run_counts_the_visits_already_on_record(tmp_path):
    out = tmp_path / "sweep-output"
    (out / "a").mkdir(parents=True)
    (out / "b").mkdir()
    (out / "a" / "result.json").write_text(json.dumps({"visits": [{"url": "https://www.example.com/"}]}))
    (out / "b" / "result.json").write_text(json.dumps({"visits": [{
        "url": "https://limited.example.org/", "failure": "blocked",
        "detail": "https://limited.example.org/robots.txt answered HTTP 429 (Too Many Requests)"}]}))
    written = time.mktime(datetime(2026, 10, 3, 12).timetuple())
    for f in out.glob("*/result.json"):
        os.utime(f, (written, written))
    fp = Footprint(out, MONDAY)
    assert fp.state["example.com"]["retry_after"] == "2026-10-10"
    assert fp.state["limited.example.org"]["retry_after"] == "2026-11-02"
    with pytest.raises(footprint.Deferred):
        fp.check("https://example.com/")


def test_cached_pages_older_than_the_window_are_deleted(tmp_path):
    old = tmp_path / "_cache" / "2026-09-20"
    old.mkdir(parents=True)
    (old / "x.json").write_text("{}")
    recent = tmp_path / "_cache" / "2026-10-01"
    recent.mkdir()
    Footprint(tmp_path, MONDAY)
    assert not old.exists() and recent.exists()


def test_a_stored_page_never_confirms_a_new_on_screen_claim(tmp_path):
    """A rendered page cached with no browser checks: its placeholder is set aside, not reported as seen."""
    html = (SYNTHETIC / "placeholders.html").read_text(encoding="utf-8")
    fp = Footprint(tmp_path, MONDAY)
    url = "https://www.example.com/"
    fp.store(Visit(url, page=Page(url, url, 200, [], html, rendered=True)), checks={})
    with load.client(transport({})) as http:
        sweeper = Sweeper(http, 2026, footprint=fp)
        result = sweeper.sweep(Business("lead", "Example Service Center", "auto", [url]))
    assert result.verdict == "good"
    assert "{{placeholder_hero_banner}}" in result.visits[0].unchecked


def test_a_stored_page_keeps_what_a_browser_confirmed(tmp_path):
    html = (SYNTHETIC / "placeholders.html").read_text(encoding="utf-8")
    fp = Footprint(tmp_path, MONDAY)
    url = "https://www.example.com/"
    fp.store(Visit(url, page=Page(url, url, 200, [], html, rendered=True)),
             checks={"{{placeholder_hero_banner}}": True})
    with load.client(transport({})) as http:
        result = Sweeper(http, 2026, footprint=fp).sweep(Business("lead", "Example Service Center", "auto", [url]))
    assert result.verdict == "weak" and result.fault.quote == "{{placeholder_hero_banner}}"
