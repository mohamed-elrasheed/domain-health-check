"""The response-code guard. An error page's body is a block page, a captcha or a maintenance notice, never the
site: reading one as the home page invents a dozen findings about a site we never saw.

Every condition here was seen on a real small-business site in October 2026. The pages are synthetic
reproductions, run through the real fetcher and the real runner on httpx.MockTransport."""

from datetime import datetime, timezone

import httpx
import pytest

from domain_health_check import fetcher, runner
from domain_health_check.checks import rdap, tls
from domain_health_check.config import DomainConfig
from domain_health_check.fetcher import FetchError, PageStatusError
from domain_health_check.models import SITE, WEBSITE, Status

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)

# What a block page looks like: one h1, no meta description, no canonical, no structured data, about 5 KB.
BLOCK_PAGE = ("<html><head><title>Access denied</title></head><body><h1>Access denied</h1>"
              + "<p>Your request was blocked.</p>" * 160 + "</body></html>")
REAL_PAGE = ('<html><head><title>Example Plumbing, Springfield plumbers</title>'
             '<meta name="description" content="Family plumbers in Springfield since 1990. Repairs, installs and '
             'emergencies, with fixed prices quoted before we start."><link rel="canonical" href="https://example.com/">'
             '<meta name="viewport" content="width=device-width, initial-scale=1"></head><body><h1>Example Plumbing</h1>'
             + "<h2>Services</h2><p>We fix leaks, install boilers and clear drains across Springfield.</p>" * 20
             + "</body></html>")


def site(home=None, robots=None, raise_on=None):
    """A fake site. home and robots are (status, body); raise_on maps a path to an exception to raise."""
    def handle(request):
        path = request.url.path
        if raise_on and path in raise_on:
            raise raise_on[path](request)
        if path == "/robots.txt":
            status, body = robots or (404, "")
        elif path == "/":
            status, body = home or (200, REAL_PAGE)
        else:
            status, body = 404, ""
        return httpx.Response(status, text=body, headers={"content-type": "text/html"})
    return httpx.MockTransport(handle)


@pytest.fixture
def report_for(fake_dns, monkeypatch):
    """Runs the whole report against a fake site, with DNS, TLS and RDAP faked out."""
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    real_fetch = fetcher.fetch_page

    def run(transport):
        monkeypatch.setattr(fetcher, "fetch_page", lambda d: real_fetch(d, transport=transport))
        return runner.run_checks(DomainConfig("example.com"), NOW)
    return run


def assert_no_content_findings(report):
    """Nothing about the page was judged: every site row either did not run or is absent."""
    judged = [r.name for r in report.results if r.category == SITE and r.ran]
    assert judged == [], f"findings about a page we never saw: {judged}"
    headers = [r for r in report.results if r.category == WEBSITE and r.name in
               ("HSTS (always use HTTPS)", "Content Security Policy", "X-Content-Type-Options")]
    assert headers == []


def not_loaded_row(report):
    [row] = [r for r in report.results if r.name == "Site health checks"]
    assert not row.ran
    return row


# ---------- the fetcher

@pytest.mark.parametrize("status", [403, 404, 429, 500, 503])
def test_error_status_raises_instead_of_returning_the_body(status):
    with pytest.raises(PageStatusError) as info:
        fetcher.fetch_page("example.com", transport=site(home=(status, BLOCK_PAGE)))
    assert info.value.status == status and f"HTTP status {status}" in info.value.reason


def test_robots_server_error_stops_before_the_home_page():
    seen = []
    transport = site(home=(200, REAL_PAGE), robots=(500, "oops"))

    def counting(request):
        seen.append(request.url.path)
        return transport.handle_request(request)
    with pytest.raises(PageStatusError) as info:
        fetcher.fetch_page("example.com", transport=httpx.MockTransport(counting))
    assert info.value.status == 500 and seen == ["/robots.txt"]


# ---------- the whole report, condition by condition

def test_403_block_page_with_failing_robots(report_for):
    report = report_for(site(home=(403, BLOCK_PAGE), robots=(500, "Internal Server Error")))
    row = not_loaded_row(report)
    # Say what happened: robots.txt failed and we stopped there; the home page was never requested.
    assert "robots.txt file (https://example.com/robots.txt) answered with an error (status 500" in row.summary
    assert "did not request your home page" in row.summary and "403" not in row.summary
    # A failing robots.txt is itself a finding: Google stops crawling the whole site.
    [blocking] = [r for r in report.results if r.name == "Search engine blocking"]
    assert blocking.ran and blocking.status is Status.FAIL and "returns a server error" in blocking.summary
    others = [r.name for r in report.results if r.category == SITE and r.ran and r.name != "Search engine blocking"]
    assert others == []


@pytest.mark.parametrize("status, fails", [(500, True), (503, True), (429, True), (403, False), (404, False)])
def test_which_robots_statuses_block_search(status, fails):
    from domain_health_check.checks.site import indexing
    from domain_health_check.fetcher import FetchedFile
    robots = FetchedFile("https://example.com/robots.txt", status, "")
    results = indexing.check_search_blocking(FetchError("https://example.com/", "x", robots))
    # Google treats 5xx and 429 as "fully disallowed"; any other 4xx, 403 included, as no robots.txt at all.
    assert (results != [] and results[0].status is Status.FAIL) is fails


def test_403_block_page_body_is_never_read(report_for):
    report = report_for(site(home=(403, BLOCK_PAGE), robots=(200, "User-agent: *\nAllow: /\n")))
    row = not_loaded_row(report)
    assert "status 403, forbidden" in row.summary
    assert "nothing needs to change" in row.fix
    assert_no_content_findings(report)
    assert not any("Access denied" in r.summary for r in report.results)


def test_429_rate_limit_page(report_for):
    report = report_for(site(home=(429, BLOCK_PAGE), robots=(200, "")))
    assert "status 429, too many requests" in not_loaded_row(report).summary
    assert_no_content_findings(report)


def test_404_home_with_a_working_robots_txt(report_for):
    report = report_for(site(home=(404, "<html><body><h1>Not found</h1></body></html>"), robots=(200, "")))
    assert "status 404" in not_loaded_row(report).summary
    assert_no_content_findings(report)


def test_domain_that_does_not_resolve(report_for):
    dns_failure = {"/robots.txt": lambda r: httpx.ConnectError("[Errno 11001] getaddrinfo failed", request=r)}
    report = report_for(site(raise_on=dns_failure))
    assert "could not load" in not_loaded_row(report).summary
    assert_no_content_findings(report)


def test_site_that_times_out(report_for):
    report = report_for(site(raise_on={"/": lambda r: httpx.ReadTimeout("timed out", request=r)}))
    assert "could not load" in not_loaded_row(report).summary
    assert_no_content_findings(report)


def test_slow_but_working_page_is_checked_normally(make_page, report_for, monkeypatch):
    slow = make_page(html=REAL_PAGE, ttfb_ms=4400, elapsed_ms=4500)
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: slow)
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    assert not [r for r in report.results if r.name == "Site health checks"]
    weight = next(r for r in report.results if r.name == "Page weight")
    assert weight.ran and weight.status is Status.PASS  # 4.4 seconds is under the 5-second line


def test_normal_large_page_is_checked_normally(report_for):
    big = REAL_PAGE.replace("</body>", "<p>" + "x" * 336_000 + "</p></body>")
    report = report_for(site(home=(200, big), robots=(200, "")))
    names = {r.name: r for r in report.results if r.category == SITE and r.ran}
    assert {"Page title", "Main heading", "Canonical tag", "Page weight"} <= set(names)
    assert names["Page weight"].status is Status.WARN  # over 150 KB


def test_sitemap_error_is_not_reported_as_missing(make_page):
    from domain_health_check.checks.site import indexing
    from domain_health_check.fetcher import FetchedFile
    page = make_page(robots=FetchedFile("https://example.com/robots.txt", 200, ""),
                     sitemap=FetchedFile("https://example.com/sitemap.xml", 429, "<html>slow down</html>"))
    [result] = indexing.check_sitemap_and_robots(page)
    assert not result.ran and "status 429" in result.summary
    assert "could not find a sitemap" not in result.summary


def test_google_is_not_asked_to_test_a_page_we_were_turned_away_from(monkeypatch):
    monkeypatch.setenv("PAGESPEED_API_KEY", "test-key")
    context = runner._fetch_external("example.com", PageStatusError("https://example.com/", 403, "https://example.com/"))
    assert context.psi_mobile == [] and "status 403" in context.errors["psi_mobile"]


def test_a_plain_fetch_error_is_still_a_fetch_error():
    assert issubclass(PageStatusError, FetchError)


# ---------- the score gate and the unreachable headline (one test per way a site fails to load)

NO_SCORE = "Score: not available - we could not load your website."


def assert_no_score(report):
    from domain_health_check import layout
    from domain_health_check.report import render_markdown
    assert not report.website_loaded
    assert layout.headline(report) == (None, NO_SCORE)
    md = render_markdown(report)
    assert "out of 100" not in md and NO_SCORE in md
    return md


def test_404_home_gives_no_score_and_leads_with_it(report_for):
    report = report_for(site(home=(404, "<h1>Not found</h1>"), robots=(200, "")))
    md = assert_no_score(report)
    assert "answers \"not found\" (status 404)" in report.unreachable
    assert md.index("## Your website could not be reached") < md.index("## Everything we checked")


def test_5xx_home_gives_no_score_and_leads_with_it(report_for):
    report = report_for(site(home=(503, "<h1>Maintenance</h1>"), robots=(200, "")))
    assert_no_score(report)
    assert "server error (status 503" in report.unreachable


def test_timeout_gives_no_score_and_leads_with_it(report_for):
    report = report_for(site(raise_on={"/": lambda r: httpx.ReadTimeout("timed out", request=r)}))
    assert_no_score(report)
    assert report.unreachable.startswith("We could not reach your website")


def test_robots_5xx_gives_no_score_but_is_not_an_unreachable_site(report_for):
    report = report_for(site(home=(200, REAL_PAGE), robots=(500, "")))
    assert_no_score(report)
    assert report.unreachable == ""  # visitors can reach the site; the robots.txt finding says what is wrong


def test_403_to_us_is_not_reported_as_unreachable_for_visitors(report_for):
    report = report_for(site(home=(403, BLOCK_PAGE), robots=(200, "")))
    assert_no_score(report)
    assert report.unreachable == ""  # a 403 usually turns away automated checks, not people


def test_nxdomain_is_one_finding_and_nothing_else(fake_dns, monkeypatch):
    fake_dns[("example.com", "NXDOMAIN")] = True
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: pytest.fail("fetched a page for a domain that does not exist"))
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    md = assert_no_score(report)
    [finding] = [r for r in report.results if r.ran]
    assert finding.status is Status.FAIL
    assert finding.summary == "This domain is not registered, or the registration has lapsed."
    names = {r.name for r in report.results}
    for restated in ("SPF (approved senders)", "DKIM (email signatures)", "DMARC (anti-spoofing policy)", "DNSSEC",
                     "Mail servers (MX)", "Nameservers", "SSL certificate", "Site health checks"):
        assert restated not in names
    assert "does not exist in DNS" in report.unreachable and "## Your website could not be reached" in md


def test_nxdomain_lookup_failure_is_not_nxdomain(fake_dns, monkeypatch, make_page):
    monkeypatch.setattr(runner.dns_utils, "domain_exists", lambda name: None)  # could not tell
    monkeypatch.setattr(fetcher, "fetch_page", lambda d: make_page(html=REAL_PAGE))
    monkeypatch.setattr(tls, "fetch_tls_info", lambda d: ({"notAfter": "Jan  1 00:00:00 2027 GMT"}, "TLSv1.3"))
    monkeypatch.setattr(rdap, "fetch_rdap", lambda d: {"events": []})
    report = runner.run_checks(DomainConfig("example.com"), NOW)
    assert report.website_loaded and len(report.results) > 5  # carries on normally
