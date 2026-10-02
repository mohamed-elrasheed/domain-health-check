"""The PageSpeed Insights client, on httpx.MockTransport. The response body is always the real saved one."""

import json
import os
import threading
import time

import httpx
import pytest

from domain_health_check import cli, external, runner
from domain_health_check.config import DomainConfig, load_env
from domain_health_check.fetcher import FetchError, RobotsDisallowed

KEY = "test-key-not-real"
URL = "https://www.mizangroupllc.com/"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(external, "CACHE_DIR", tmp_path / "pagespeed")
    return tmp_path / "pagespeed"


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", KEY)


def google(psi_mobile, seen=None, status=200, body=None):
    def handle(request):
        if seen is not None:
            seen.append(request)
        return httpx.Response(status, json=body if body is not None else psi_mobile)
    return httpx.MockTransport(handle)


def test_no_key_makes_no_call(psi_mobile):
    seen = []
    context = external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile, seen))
    assert seen == [] and context == external.ExternalContext()
    assert not context.pagespeed_configured


def test_three_mobile_runs_and_one_desktop_all_at_once(psi_mobile, with_key):
    seen = []
    all_in_flight = threading.Barrier(4)

    def handle(request):
        seen.append(request)
        all_in_flight.wait(timeout=5)  # raises BrokenBarrierError if the calls ran one after the other
        return httpx.Response(200, json=psi_mobile)

    context = external.fetch_external("mizangroupllc.com", URL, transport=httpx.MockTransport(handle))
    assert context.psi_mobile == [psi_mobile] * 3 and context.psi_desktop == psi_mobile and context.errors == {}
    assert sorted(r.url.params["strategy"] for r in seen) == ["desktop", "mobile", "mobile", "mobile"]
    for request in seen:
        assert request.url.params["url"] == URL and request.url.params["key"] == KEY
        assert request.url.params.get_list("category") == ["performance", "accessibility", "best-practices"]
        assert "seo" not in request.url.params.get_list("category")


def test_timeout_is_recorded_and_the_key_never_appears(psi_mobile, with_key):
    def handle(request):
        raise httpx.ReadTimeout(f"timed out reading {request.url}", request=request)
    context = external.fetch_external("mizangroupllc.com", URL, transport=httpx.MockTransport(handle))
    assert context.psi_mobile == [] and context.pagespeed_configured
    assert context.errors["psi_mobile_1"] == "mobile run 1: no answer within 120 seconds"
    assert context.errors["psi_desktop"] == "desktop: no answer within 120 seconds"
    assert not any(KEY in why for why in context.errors.values())


def test_http_error_message_is_kept_without_the_key(psi_mobile, with_key):
    body = {"error": {"code": 429, "message": f"Quota exceeded for key {KEY}"}}
    context = external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile, status=429, body=body))
    assert context.errors["psi_mobile_2"] == "mobile run 2: HTTP 429 Quota exceeded for key <key>"


def test_read_is_capped(psi_mobile, with_key, monkeypatch):
    monkeypatch.setattr(external, "PSI_MAX_BYTES", 1000)  # the real response is about 10 KB trimmed
    context = external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile))
    assert context.psi_mobile == [] and "larger than 1,000 bytes" in context.errors["psi_mobile_3"]


def test_one_run_can_fail_alone(psi_mobile, with_key):
    calls = {"mobile": 0}
    lock = threading.Lock()

    def handle(request):
        if request.url.params["strategy"] == "desktop":
            raise httpx.ConnectError("refused", request=request)
        with lock:
            calls["mobile"] += 1
            first = calls["mobile"] == 1
        if first:
            raise httpx.ConnectError("refused", request=request)
        return httpx.Response(200, json=psi_mobile)
    context = external.fetch_external("mizangroupllc.com", URL, transport=httpx.MockTransport(handle))
    assert len(context.psi_mobile) == 2 and context.psi_desktop is None
    assert sorted(context.errors) == ["psi_desktop", next(k for k in context.errors if k.startswith("psi_mobile_"))]


def test_cache_is_reused_for_a_day_then_deleted_and_refreshed(psi_mobile, with_key, isolated_cache):
    seen = []
    external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile, seen))
    assert len(seen) == 4
    assert sorted(p.name for p in isolated_cache.iterdir()) == [
        "mizangroupllc.com-desktop-1.json", "mizangroupllc.com-mobile-1.json", "mizangroupllc.com-mobile-2.json",
        "mizangroupllc.com-mobile-3.json"]
    cached = json.loads((isolated_cache / "mizangroupllc.com-mobile-1.json").read_text(encoding="utf-8"))
    assert cached == psi_mobile and KEY not in json.dumps(cached)

    external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile, seen))
    assert len(seen) == 4  # served from the cache

    old = time.time() - external.CACHE_SECONDS - 60
    for path in isolated_cache.iterdir():
        os.utime(path, (old, old))
    (isolated_cache / "other.example-mobile-1.json").write_text("{}", encoding="utf-8")
    os.utime(isolated_cache / "other.example-mobile-1.json", (old, old))
    external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile, seen))
    assert len(seen) == 8  # a day later, a fresh call
    assert not (isolated_cache / "other.example-mobile-1.json").exists()  # expired data is deleted, not kept


def test_damaged_cache_is_ignored(psi_mobile, with_key, isolated_cache):
    isolated_cache.mkdir(parents=True)
    (isolated_cache / "mizangroupllc.com-mobile-1.json").write_text("{not json", encoding="utf-8")
    context = external.fetch_external("mizangroupllc.com", URL, transport=google(psi_mobile))
    assert context.psi_mobile == [psi_mobile] * 3


def test_unloadable_page_is_not_sent_to_google(psi_mobile, with_key):
    seen = []
    context = external.fetch_external("example.com", None, "not run, because we could not load the home page",
                                      transport=google(psi_mobile, seen))
    assert seen == [] and context.errors["psi_mobile"].startswith("not run")
    assert context.pagespeed_configured


@pytest.mark.parametrize("page, phrase", [
    (RobotsDisallowed("https://example.com/", "Disallow: /"), "robots.txt asks us not to load"),
    (FetchError("https://example.com/", "ConnectError"), "could not load the home page"),
])
def test_runner_skips_google_when_we_could_not_load_the_page(with_key, page, phrase):
    context = runner._fetch_external("example.com", page)
    assert context.psi_mobile == [] and phrase in context.errors["psi_mobile"]


def test_load_env_reads_keys_without_overriding(tmp_path, monkeypatch):
    for name in ("PAGESPEED_API_KEY", "PLACES_API_KEY"):
        monkeypatch.setenv(name, "x")  # registers each, so whatever load_env sets is undone after the test
        monkeypatch.delenv(name)
    monkeypatch.setenv("OTHER", "already set")
    env = tmp_path / ".env"
    env.write_text('# comment\nPAGESPEED_API_KEY="from-file"\nPLACES_API_KEY=\nOTHER=from-file\n', encoding="utf-8")
    load_env(env)
    assert os.environ["PAGESPEED_API_KEY"] == "from-file"
    assert "PLACES_API_KEY" not in os.environ  # empty values are skipped
    assert os.environ["OTHER"] == "already set"


def test_tests_never_see_the_real_env_file():
    assert not cli.ENV_FILE.exists()
    assert "PAGESPEED_API_KEY" not in os.environ
