"""Sweeping a business end to end on a mock transport: what gets requested, what a failure becomes, and
which verdict comes out. No socket is opened; conftest blocks them."""

from __future__ import annotations

import json
import socket
from datetime import date
from pathlib import Path

import httpx
import pytest

from domain_health_check.identity import USER_AGENT
from domain_health_check.sweep import cli, load
from domain_health_check.sweep.models import Business, Page, Visit
from domain_health_check.sweep.run import Sweeper, decide

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
GOOD = (SYNTHETIC / "good.html").read_text(encoding="utf-8")


class FakePacer(load.Pacer):
    def __init__(self):
        super().__init__(clock=lambda: 0.0, sleep=lambda s: self.slept.append(s))
        self.slept: list[float] = []


def site(routes: dict[str, object]):
    """A mock transport. routes maps a path (or a full URL) to a response, an exception, or a list of them
    to hand out in turn. Every request is recorded in .seen."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        answer = routes.get(str(request.url), routes.get(request.url.path, httpx.Response(404)))
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    transport = httpx.MockTransport(handler)
    transport.seen = seen
    return transport


def robots_ok() -> httpx.Response:
    return httpx.Response(200, text="User-agent: *\nDisallow: /wp-admin/\n")


def sweep(urls: list[str], routes: dict[str, object], year: int = 2026):
    transport = site(routes)
    pacer = FakePacer()
    with load.client(transport) as http:
        result = Sweeper(http, year, pacer=pacer).sweep(Business("lead", "Lead", "auto", urls))
    return result, transport.seen, pacer


def nxdomain_error() -> httpx.ConnectError:
    try:
        try:
            raise socket.gaierror(11001, "getaddrinfo failed")
        except socket.gaierror as cause:
            raise httpx.ConnectError("[Errno 11001] getaddrinfo failed") from cause
    except httpx.ConnectError as exc:
        return exc


def certificate_error(message: str) -> httpx.ConnectError:
    class SSLCertVerificationError(Exception):  # matched by name, as ssl's is
        verify_message = message
    try:
        try:
            raise SSLCertVerificationError(message)
        except SSLCertVerificationError as cause:
            raise httpx.ConnectError(f"[SSL: CERTIFICATE_VERIFY_FAILED] {message}") from cause
    except httpx.ConnectError as exc:
        return exc


def test_a_good_site_is_robots_then_the_home_page_and_nothing_else():
    result, seen, _ = sweep(["https://www.example.com/"], {"/robots.txt": robots_ok(), "/": httpx.Response(200, html=GOOD)})
    assert result.verdict == "good" and result.sentence == ""
    assert [r.url.path for r in seen] == ["/robots.txt", "/"]  # no sitemap, no second page
    assert all(r.headers["user-agent"] == USER_AGENT for r in seen)


def test_no_owned_address_means_none_and_no_requests():
    result, seen, _ = sweep(["https://www.facebook.com/lead", "https://www.fresha.com/lvp/lead-abc",
                             "https://www.doordash.com/store/lead-1/"], {})
    assert result.verdict == "none" and seen == []
    assert result.sentence == ("We found no site they own. What is listed lives on facebook.com, fresha.com and "
                               "doordash.com.")


def test_no_links_at_all_is_none():
    result, seen, _ = sweep([], {})
    assert result.verdict == "none" and "no website and no listing link" in result.sentence


def test_an_address_that_forwards_to_a_platform_is_none():
    routes = {"/robots.txt": robots_ok(), "/": httpx.Response(301, headers={"Location": "https://www.facebook.com/lead"}),
              "https://www.facebook.com/lead": httpx.Response(200, html=GOOD)}
    result, _, _ = sweep(["https://www.example.com/"], routes)
    assert result.verdict == "none" and "forwards to www.facebook.com" in result.sentence


def test_a_builder_subdomain_is_weak_not_none():
    result, _, _ = sweep(["https://examplebarbers.wixsite.com/examplebarbers"],
                         {"/robots.txt": robots_ok(), "/examplebarbers": httpx.Response(200, html=GOOD)})
    assert result.verdict == "weak" and result.fault.code == "builder-host"


def test_a_domain_that_does_not_exist():
    result, seen, _ = sweep(["https://www.example-listed.com/"], {"/robots.txt": nxdomain_error()})
    assert result.verdict == "weak" and result.fault.code == "nxdomain"
    assert len(seen) == 1  # not retried: a domain that does not exist will not exist in five seconds


def test_an_expired_certificate_is_weak():
    result, _, _ = sweep(["https://www.example.com/"], {"/robots.txt": certificate_error("certificate has expired")})
    assert result.verdict == "weak" and result.fault.sentence.endswith("certificate has expired.")


def test_a_certificate_only_our_client_rejects_is_unverified():
    result, _, _ = sweep(["https://www.example.com/"],
                         {"/robots.txt": certificate_error("unable to get local issuer certificate")})
    assert result.verdict == "unver" and result.visits[0].failure == "unverified"
    assert "a browser may still accept it" in result.sentence


def test_robots_server_error_is_weak_and_the_page_is_not_loaded():
    result, seen, _ = sweep(["https://www.example.com/"], {"/robots.txt": httpx.Response(500)})
    assert result.verdict == "weak" and result.fault.code == "robots-error"
    assert [r.url.path for r in seen] == ["/robots.txt"]  # RFC 9309: a 5xx robots.txt means load nothing


def test_robots_rate_limiting_us_is_unver_and_honored():
    result, seen, _ = sweep(["https://www.example.com/"], {"/robots.txt": httpx.Response(429)})
    assert result.verdict == "unver" and result.visits[0].failure == "blocked"
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_robots_that_blocks_everyone_is_weak_and_honored():
    routes = {"/robots.txt": httpx.Response(200, text=(SYNTHETIC / "robots-disallow-home.txt").read_text())}
    result, seen, _ = sweep(["https://www.example.com/"], routes)
    assert result.verdict == "weak" and result.fault.code == "google-blocked"
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_robots_that_blocks_only_us_is_unver_and_honored():
    routes = {"/robots.txt": httpx.Response(200, text=(SYNTHETIC / "robots-disallow-us-only.txt").read_text())}
    result, seen, _ = sweep(["https://www.example.com/"], routes)
    assert result.verdict == "unver" and result.visits[0].failure == "disallowed"
    assert [r.url.path for r in seen] == ["/robots.txt"]


def test_a_403_is_recorded_as_blocked():
    result, _, _ = sweep(["https://www.example.com/"], {"/robots.txt": robots_ok(), "/": httpx.Response(403)})
    assert result.verdict == "unver"
    assert result.visits[0].failure == "blocked" and "HTTP 403 (Forbidden)" in result.sentence


def test_a_timeout_is_retried_once_then_recorded():
    timeout = httpx.ConnectTimeout("timed out")
    result, seen, pacer = sweep(["https://www.example.com/"], {"/robots.txt": robots_ok(), "/": [timeout, timeout]})
    assert result.verdict == "unver" and result.visits[0].failure == "timeout"
    assert "(on all 2 attempts)" in result.sentence
    assert [r.url.path for r in seen] == ["/robots.txt", "/", "/"] and load.RETRY_PAUSE in pacer.slept


def test_a_timeout_then_an_answer_is_good():
    timeout = httpx.ReadTimeout("timed out")
    result, _, _ = sweep(["https://www.example.com/"],
                         {"/robots.txt": robots_ok(), "/": [timeout, httpx.Response(200, html=GOOD)]})
    assert result.verdict == "good" and result.visits[0].attempts == 3


def test_the_worst_fault_across_two_addresses_wins():
    old = GOOD.replace("2015-2026", "2019")
    routes = {"https://www.example.com/robots.txt": robots_ok(), "https://www.example.com/": httpx.Response(200, html=old),
              "https://www.example-old.com/robots.txt": nxdomain_error()}
    result, _, _ = sweep(["https://www.example.com/", "https://www.example-old.com/"], routes)
    assert result.verdict == "weak" and result.fault.code == "nxdomain" and result.also_found == ["stale-copyright"]


def test_an_address_listed_by_two_leads_is_visited_once():
    transport = site({"/robots.txt": robots_ok(), "/": httpx.Response(200, html=GOOD)})
    with load.client(transport) as http:
        sweeper = Sweeper(http, 2026, pacer=FakePacer())
        for lead in ("a", "b"):
            sweeper.sweep(Business(lead, lead, "auto", ["https://www.example.com/"]))
    assert len(transport.seen) == 2


def test_pacer_spaces_requests_to_one_host():
    now = [0.0]
    slept: list[float] = []
    pacer = load.Pacer(gap=1.0, clock=lambda: now[0], sleep=lambda s: slept.append(s) or now.__setitem__(0, now[0] + s))
    pacer.wait("https://www.example.com/robots.txt")
    pacer.wait("https://www.example.com/")
    pacer.wait("https://www.example.org/")
    assert slept == [1.0]


def test_decide_is_unver_only_when_nothing_loaded():
    failed = Visit("https://a.example/", failure="timeout", detail="no answer within 10 seconds")
    page = Page("https://b.example/", "https://b.example/", 200, [], GOOD)
    assert decide(["https://a.example/"], [], [failed])[0] == "unver"
    assert decide(["https://a.example/", "https://b.example/"], [], [failed, Visit("https://b.example/", page=page)])[0] == "good"


# ---------- the command

def leads_file(tmp_path: Path) -> Path:
    path = tmp_path / "leads.json"
    path.write_text(json.dumps([
        {"id": "auto-one", "n": "Auto One", "cat": "auto", "links": [["Site", "https://www.example.com/"]]},
        {"id": "clean-one", "n": "Clean One", "cat": "clean", "links": [["Facebook", "https://www.facebook.com/c"]]},
    ]), encoding="utf-8")
    return path


def own_site_and(routes):
    return site({cli.OWN_SITE: robots_ok(), **routes})


def test_cli_writes_verdicts_and_never_touches_the_lead_list(tmp_path, capsys):
    leads = leads_file(tmp_path)
    before = leads.read_bytes()
    out = tmp_path / "out"
    (out).mkdir()
    (out / "sweep-2026-09-01.json").write_text("[]")  # an older run, replaced
    (out / "auto-one").mkdir()
    (out / "auto-one" / "evidence.png").write_bytes(b"old")  # a stale picture from that run, removed
    transport = own_site_and({"https://www.example.com/robots.txt": robots_ok(),
                              "https://www.example.com/": httpx.Response(200, html=GOOD)})
    assert cli.main([str(leads), "-o", str(out), "--no-browser"], transport=transport, today=date(2026, 10, 2)) == 0
    assert leads.read_bytes() == before
    summary = json.loads((out / "sweep-2026-10-02.json").read_text())
    assert [(r["id"], r["verdict"]) for r in summary] == [("auto-one", "good"), ("clean-one", "none")]
    assert not (out / "sweep-2026-09-01.json").exists()
    assert not (out / "auto-one" / "evidence.png").exists()
    record = json.loads((out / "auto-one" / "result.json").read_text())
    assert "html" not in record["visits"][0]["page"]  # their page is not kept, only what we found on it
    assert "2 businesses: 1 none, 0 weak, 0 unver, 1 good." in capsys.readouterr().out


def test_cli_trade_uses_the_rotation_names(tmp_path, capsys):
    transport = own_site_and({})
    assert cli.main([str(leads_file(tmp_path)), "-o", str(tmp_path / "o"), "--no-browser", "--trade", "cleaning"],
                    transport=transport) == 0
    out = capsys.readouterr().out
    assert "clean-one" in out and "auto-one" not in out
    assert [r.url.host for r in transport.seen] == []  # a none needs no request, not even the network check


def test_cli_unknown_trade_or_id_is_an_error(tmp_path, capsys):
    assert cli.main([str(leads_file(tmp_path)), "--trade", "plumbing", "--no-browser"]) == 2
    assert cli.main([str(leads_file(tmp_path)), "--only", "nobody", "--no-browser"]) == 2
    assert "nobody" in capsys.readouterr().err


def test_cli_refuses_an_unsafe_id(tmp_path):
    path = tmp_path / "leads.json"
    path.write_text(json.dumps([{"id": "../escape", "n": "x", "cat": "auto", "links": []}]))
    assert cli.main([str(path), "--no-browser"]) == 2


def test_cli_stops_when_our_own_network_is_down(tmp_path, capsys):
    transport = site({cli.OWN_SITE: httpx.ConnectError("unreachable")})
    assert cli.main([str(leads_file(tmp_path)), "-o", str(tmp_path / "o"), "--no-browser"], transport=transport) == 2
    assert "Check the network" in capsys.readouterr().err
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("errno, kind", [(11001, "nxdomain"), (-2, "nxdomain"), (11002, "connection")])
def test_only_a_definite_no_such_name_counts_as_nxdomain(errno, kind):
    try:
        try:
            raise socket.gaierror(errno, "lookup failed")
        except socket.gaierror as cause:
            raise httpx.ConnectError("lookup failed") from cause
    except httpx.ConnectError as exc:
        assert load.classify(exc, "https://www.example.com/").kind == kind
