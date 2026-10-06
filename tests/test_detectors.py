"""Broken links, mixed content and the browser tab icon: one passing and one failing synthetic page each, the
link checker held to the capped rule in CLAUDE.md, and every request it makes written to requests.log."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from site_helpers import PNG, healthy_site

from domain_health_check import fetcher, linkcheck, platform, requestlog
from domain_health_check.checks.site import favicon, links, mixed_content
from domain_health_check.fetcher import FetchedFile, FetchedIcon
from domain_health_check.models import Status

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic" / "detectors"
URL = "https://www.example.com/"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def site(routes: dict[str, httpx.Response | Exception], seen: list | None = None):
    """A transport answering by path (or full URL for other hosts); anything not listed is a healthy page or icon."""
    def handle(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append((request.method, str(request.url)))
        answer = routes.get(str(request.url), routes.get(request.url.path if request.url.host == "www.example.com"
                                                         else "", None))
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            return answer(request)
        return answer or healthy_site(request)
    return httpx.MockTransport(handle)


# ---------- broken links

def test_links_pass(make_page):
    page = make_page(html=fixture("links-pass.html"), final_url=URL)
    results = linkcheck.verify(page, transport=site({}))
    same, other = links.check_links(fetcher_replace(page, results))
    assert (same.name, same.status, other.name, other.status) == (links.SAME_SITE, Status.PASS,
                                                                  links.OTHER_SITES, Status.PASS)
    assert same.summary == ("4 of 4 links on your home page to other pages on your site were verified, and none of "
                            "them is broken.")
    assert "all" not in same.summary.lower().split()
    # mailto, tel, fragments and the page itself are not links to verify; /order#today is /order.
    assert sorted(r.url for r in results if r.same_site) == [
        f"{URL}about/", f"{URL}contact", f"{URL}menu", f"{URL}order"]
    assert all(r.outcome == "ok" for r in results)


def fetcher_replace(page, results):
    from dataclasses import replace
    return replace(page, links=results)


def test_links_fail(make_page):
    page = make_page(html=fixture("links-fail.html"), final_url=URL)

    def loop(request):
        return httpx.Response(301, headers={"location": "/loop"})
    transport = site({"/old-specials": httpx.Response(404), "/loop": loop,
                      "https://news.example.org/gone-story": httpx.Response(410)})
    results = linkcheck.verify(page, transport=transport)
    same, other = links.check_links(fetcher_replace(page, results))
    assert same.status is Status.WARN and same.fix == links.FIX
    assert same.summary == ("5 of 5 links on your home page to other pages on your site were verified, and 2 of "
                            "them do not work.")
    assert '"Specials" links to https://www.example.com/old-specials: status 404 (Not Found)' in same.details
    assert any(d.startswith('"Gift cards" links to https://www.example.com/loop: more than 3 redirects')
               for d in same.details)
    assert other.status is Status.WARN and other.summary == (
        "2 of 2 links on your home page to other websites were verified, and 1 of them does not work.")
    assert same.measure == pytest.approx(3 / 5)
    # A link whose only content is an image is named by its alt text.
    assert next(r for r in results if r.url.endswith("/catering")).text == "Catering trays"


def test_a_broken_link_is_never_a_fail(make_page):
    page = make_page(html='<a href="/a">A</a><a href="https://other.example.org/">B</a>', final_url=URL)
    results = linkcheck.verify(page, transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert {r.status for r in links.check_links(fetcher_replace(page, results))} == {Status.WARN}


def test_only_an_href_in_the_page_is_a_link():
    """A link is an href on an <a> in the page. A path a script could assemble from a slug, a data attribute, or
    a URL in text is never requested or reported: an address we guessed is not a link the owner published."""
    html = ('<div class="card" data-slug="email-and-domains" data-href="/old/path">Email and domains</div>'
            '<a data-slug="networks">Networks</a><a href="">Empty</a>'
            '<script>const base = "/tech-services/"; cards.forEach(c => c.href = base + c.dataset.slug);</script>'
            '<p>See /tech-services/email-and-domains or https://www.example.com/written-out</p>'
            '<a href="/tech-services/networks-and-wi-fi">Networks and Wi-Fi</a>')
    assert linkcheck.links_on(html, URL) == [(f"{URL}tech-services/networks-and-wi-fi", "Networks and Wi-Fi")]


def test_head_then_get_only_when_head_is_refused(make_page):
    seen = []
    page = make_page(html='<a href="/a">A</a><a href="/b">B</a>', final_url=URL)

    def refuses_head(request):
        return httpx.Response(405) if request.method == "HEAD" else httpx.Response(200)
    linkcheck.verify(page, transport=site({"/a": refuses_head}, seen))
    assert sorted(seen) == [("GET", f"{URL}a"), ("HEAD", f"{URL}a"), ("HEAD", f"{URL}b")]


def test_at_most_80_urls_60_on_the_site_and_20_elsewhere(make_page):
    anchors = "".join(f'<a href="/page-{i}">Page {i}</a>' for i in range(100))
    anchors += "".join(f'<a href="https://site-{i}.example.org/">Other {i}</a>' for i in range(40))
    seen = []
    results = linkcheck.verify(make_page(html=anchors, final_url=URL), transport=site({}, seen))
    assert len(seen) == 80 == linkcheck.MAX_URLS
    assert sum(1 for _, u in seen if u.startswith(URL)) == 60
    assert sum(r.outcome == "not requested" for r in results) == 60
    assert all("past our cap" in r.detail for r in results if r.outcome == "not requested")


def test_redirects_stop_after_three_hops(make_page):
    seen = []

    def hop(request):
        n = int(request.url.path.rsplit("-", 1)[-1])
        return httpx.Response(301, headers={"location": f"/hop-{n + 1}"})
    page = make_page(html='<a href="/hop-0">Start</a>', final_url=URL)
    [result] = linkcheck.verify(page, transport=httpx.MockTransport(lambda r: seen.append(r) or hop(r)))
    assert result.broken and len(seen) == 4  # the request and three redirects followed, then it stops


def test_timeouts_are_broken_and_turned_away_is_not_verified(make_page):
    page = make_page(html='<a href="/slow">Slow</a><a href="https://shop.example.org/">Shop</a>', final_url=URL)
    results = linkcheck.verify(page, transport=site({"/slow": httpx.ReadTimeout("slow"),
                                                     "https://shop.example.org/": httpx.Response(403)}))
    outcomes = {r.url: r.outcome for r in results}
    assert outcomes == {f"{URL}slow": "broken", "https://shop.example.org/": "not verified"}


def test_robots_disallowed_links_are_not_requested(make_page):
    seen = []
    robots = FetchedFile(f"{URL}robots.txt", 200, "User-agent: *\nDisallow: /private/\n")
    page = make_page(html='<a href="/private/x">X</a><a href="/open">Open</a>', final_url=URL, robots=robots)
    results = linkcheck.verify(page, transport=site({}, seen))
    assert seen == [("HEAD", f"{URL}open")]
    assert next(r for r in results if r.url.endswith("/private/x")).detail == "robots.txt asks us not to load it"


def test_every_link_request_is_in_the_request_log(make_page):
    page = make_page(html=fixture("links-fail.html"), final_url=URL)
    with requestlog.recording() as log:
        results = linkcheck.verify(page, transport=site({"/old-specials": httpx.Response(404)}))
    requested = [r for r in results if r.outcome != "not requested"]
    assert {e.target for e in log if e.source == "links"} >= {r.url for r in requested}
    assert all(e.source == "links" for e in log)


def test_links_that_were_not_verified_are_said_to_be_not_checked(make_page):
    from dataclasses import replace
    page = make_page(html='<a href="/a">A</a>', final_url=URL)
    results = linkcheck.verify(page, transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(RuntimeError())))
    [result] = links.check_links(replace(page, links=results))
    assert not result.ran
    [skipped, _] = links.check_links(replace(page, links=None))
    assert not skipped.ran


# ---------- mixed content

def test_mixed_content_pass(make_page):
    [result] = mixed_content.check_mixed_content(make_page(html=fixture("mixed-pass.html"), final_url=URL))
    assert result.status is Status.PASS


def test_mixed_content_fail_lists_five_and_counts_the_rest(make_page):
    [result] = mixed_content.check_mixed_content(make_page(html=fixture("mixed-fail.html"), final_url=URL))
    assert result.status is Status.WARN and result.fix == mixed_content.FIX
    assert result.summary == "7 files on your home page load over an insecure connection."
    listed = [d for d in result.details if ": http://" in d]
    assert len(listed) == 5 and result.details[-1] == "And 2 more."
    assert "as delivered" in result.details[0]


def test_mixed_content_reads_the_rendered_resource_list(make_page):
    """Assets a script added, and the ones the browser warned about, count once the page was rendered."""
    resources = [("https://www.example.com/a.js", "script"), ("http://ads.example.net/pixel.gif", "image"),
                 ("http://fonts.example.net/x.woff2", "font"), ("http://partner.example.org/", "document")]
    page = make_page(html="<html></html>", final_url=URL, rendered_html="<html><body></body></html>",
                     resources=resources)
    [result] = mixed_content.check_mixed_content(page)
    assert result.summary == "2 files on your home page load over an insecure connection."
    assert "after a browser loaded it" in result.details[0]


@pytest.mark.parametrize("message, found", [
    ("Mixed Content: The page at 'https://www.example.com/' was loaded over HTTPS, but requested an insecure "
     "script 'http://cdn.example.net/app.js'. This request has been blocked; the content must be served over HTTPS.",
     ("http://cdn.example.net/app.js", "script")),
    ("Mixed Content: The page at 'https://www.example.com/' was loaded over HTTPS, but requested an insecure "
     "element 'http://img.example.net/a.jpg'. This request was automatically upgraded to HTTPS.",
     ("http://img.example.net/a.jpg", "image")),
    ("Mixed Content: The page at 'https://www.example.com/' was loaded over HTTPS, but requested an insecure "
     "XMLHttpRequest endpoint 'http://api.example.net/'.", None),
    ("Some other console message", None),
])
def test_the_browser_warning_names_the_insecure_file(message, found):
    assert fetcher.mixed_console(message) == found


def test_mixed_content_needs_a_secure_page(make_page):
    [result] = mixed_content.check_mixed_content(make_page(html=fixture("mixed-fail.html"),
                                                           final_url="http://www.example.com/"))
    assert not result.ran


def test_the_browser_finds_mixed_content_a_script_adds(local_browser):
    """A real browser, answered from memory: the http image only exists after the page's script runs."""
    page = ('<!doctype html><html><head><title>Script added</title></head><body><h1>Hello</h1><script>'
            'const i = document.createElement("img"); i.src = "http://img.example.net/late.png"; '
            'document.body.appendChild(i);</script></body></html>')

    def answer(route):
        if route.request.url == URL:
            route.fulfill(status=200, content_type="text/html", body=page)
        else:
            route.fulfill(status=200, content_type="image/png", body=PNG)
    rendered = fetcher.browser_render(URL, routes=answer)
    assert any(u == "http://img.example.net/late.png" for u, _ in rendered.resources)


# ---------- the browser tab icon

def icons(transport, html: str, robots: FetchedFile | None = None, make_page=None) -> list[FetchedIcon]:
    return fetcher.fetch_favicon(make_page(html=html, final_url=URL, robots=robots), transport=transport)


def test_favicon_pass(make_page):
    seen = []
    attempts = icons(site({}, seen), fixture("favicon-pass.html"), make_page=make_page)
    [result] = favicon.check_favicon(fetcher_icon(make_page, attempts))
    assert result.status is Status.PASS
    assert seen == [("GET", f"{URL}icons/maple-row-32.png")]  # rel="icon" before the Apple touch icon


def fetcher_icon(make_page, attempts):
    return make_page(final_url=URL, favicon=attempts)


def test_favicon_missing_tries_favicon_ico_and_stops(make_page):
    seen = []
    soft_404 = httpx.Response(200, headers={"content-type": "text/html"}, text="<html>Not found</html>")
    attempts = icons(site({"/favicon.ico": soft_404}, seen), fixture("favicon-fail.html"), make_page=make_page)
    [result] = favicon.check_favicon(fetcher_icon(make_page, attempts))
    assert result.status is Status.WARN and result.fix == favicon.FIX
    assert result.summary.startswith("Your site has no browser tab icon")
    assert seen == [("GET", f"{URL}favicon.ico")]


def test_a_named_icon_that_fails_falls_back_once(make_page):
    seen = []
    attempts = icons(site({"/icons/maple-row-32.png": httpx.Response(404),
                           "/favicon.ico": httpx.Response(200, headers={"content-type": "image/x-icon"},
                                                          content=b"\x00\x00\x01\x00")}, seen),
                     fixture("favicon-pass.html"), make_page=make_page)
    assert len(seen) == 2 and favicon.evaluate_favicon(attempts).status is Status.PASS


@pytest.fixture
def test_icons(monkeypatch):
    """Default icons from the test config: the shipped config lists none without a source to cite."""
    monkeypatch.setattr(platform, "PATH", Path(__file__).parent / "fixtures" / "synthetic" / "platforms" /
                        "default-icons.yaml")


def test_favicon_default_builder_icon(make_page, test_icons):
    attempts = icons(site({}), fixture("favicon-default.html"), make_page=make_page)
    result = favicon.evaluate_favicon(attempts)
    assert result.status is Status.WARN
    assert result.summary == "Your site shows the standard Example Builder icon in browser tabs rather than your own."


def test_a_default_icon_is_recognized_after_its_redirect(make_page, test_icons):
    transport = site({"/favicon.ico": httpx.Response(302, headers={"location": "/cms-assets/default-site-icon.png"}),
                      "/cms-assets/default-site-icon.png": httpx.Response(
                          200, headers={"content-type": "image/png"}, content=PNG)})
    result = favicon.evaluate_favicon(icons(transport, fixture("favicon-fail.html"), make_page=make_page))
    assert "standard Example CMS icon" in result.summary


def test_the_shipped_config_recognizes_no_default_icon(make_page):
    """Nothing from memory ships: with no sourced entry, the invented builder's icon is just an icon."""
    attempts = icons(site({}), fixture("favicon-default.html"), make_page=make_page)
    assert favicon.evaluate_favicon(attempts).status is Status.PASS


def test_a_default_icon_without_a_source_is_refused(tmp_path):
    config = tmp_path / "platforms.yaml"
    config.write_text('platforms:\n  X:\n    default_icons: ["x.example.net/favicon.ico"]\n', encoding="utf-8")
    with pytest.raises(ValueError, match="a source to cite"):
        platform.load(config)


def test_no_answer_is_not_a_missing_icon(make_page):
    attempts = icons(httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))),
                     fixture("favicon-fail.html"), make_page=make_page)
    assert not favicon.evaluate_favicon(attempts).ran


def test_every_icon_request_is_in_the_request_log(make_page):
    with requestlog.recording() as log:
        icons(site({}), fixture("favicon-pass.html"), make_page=make_page)
    assert [(e.source, e.target) for e in log] == [("favicon", f"{URL}icons/maple-row-32.png")]


# ---------- the link checker, after the first real run

def test_a_link_that_resolves_through_a_redirect_works(make_page):
    """A path written without https:// resolves under the site; if the site redirects it to a working page, the
    link works. The only thing we judge is where a visitor ends up."""
    page = make_page(html='<a href="www.example.com/contact-us/">Contact</a>', final_url=URL)
    transport = site({"/www.example.com/contact-us/": httpx.Response(301, headers={"location": "/contact-us/"}),
                      "/contact-us/": httpx.Response(200)})
    [result] = linkcheck.verify(page, transport=transport)
    assert result.outcome == "ok" and result.final_url == f"{URL}contact-us/"


def test_each_distinct_url_is_requested_once(make_page):
    seen = []
    html = ('<a href="/menu">Menu</a><a href="/menu#lunch">Lunch</a><a href="HTTPS://WWW.EXAMPLE.COM/menu">Menu</a>'
            '<a href="https://Other.Example.org/x">X</a><a href="https://other.example.org/x">X</a>')
    linkcheck.verify(make_page(html=html, final_url=URL), transport=site({}, seen))
    assert sorted(u for _, u in seen) == ["https://other.example.org/x", f"{URL}menu"]


def test_same_site_and_other_site_links_take_turns(make_page, monkeypatch):
    order = []
    monkeypatch.setattr(linkcheck, "WORKERS", 1)
    html = "".join(f'<a href="/p{i}">P{i}</a>' for i in range(4)) + "".join(
        f'<a href="https://o{i}.example.org/">O{i}</a>' for i in range(2))
    linkcheck.verify(make_page(html=html, final_url=URL), transport=site({}, order))
    hosts = ["here" if u.startswith(URL) else "there" for _, u in order]
    assert hosts == ["here", "there", "here", "there", "here", "here"]


def test_running_out_of_time_is_said_plainly_and_is_our_limit(make_page, monkeypatch):
    from dataclasses import replace
    monkeypatch.setattr(linkcheck, "DEADLINE_SECONDS", -1)  # the limit has already passed
    page = make_page(html='<a href="/a">A</a><a href="/b">B</a>', final_url=URL)
    results = linkcheck.verify(page, transport=site({}))
    assert {r.outcome for r in results} == {"not requested"} and {r.detail for r in results} == {"we ran out of time"}
    [result] = links.check_links(replace(page, links=results))
    assert not result.ran
    assert result.summary == ("0 of 2 links on your home page to other pages on your site were verified. We ran out "
                              "of time before checking 2 links. That was our time limit, not a problem with your "
                              "links.")


def test_some_links_out_of_time_still_counts_what_was_checked(make_page):
    from dataclasses import replace

    from domain_health_check.linkcheck import LinkResult
    found = [LinkResult(f"{URL}a", "A", True, "ok", 200), LinkResult(f"{URL}b", "B", True, "ok", 200),
             LinkResult(f"{URL}c", "C", True, "not requested", detail="we ran out of time")]
    [result] = links.check_links(replace(make_page(final_url=URL), links=found))
    assert result.status is Status.PASS
    assert result.summary.startswith("2 of 3 links on your home page to other pages on your site were verified, and "
                                     "none of them is broken. We ran out of time before checking 1 link.")


# ---------- the phone number on the page and on the listing

from domain_health_check.checks import business_profile as bp  # noqa: E402
from domain_health_check.external import ExternalContext  # noqa: E402


def listing(phone="(555) 010-0100"):
    return ExternalContext(place={"displayName": {"text": "Cedar Ridge Tile and Stone"}, "nationalPhoneNumber": phone},
                           place_match="website")


def test_phone_matches_the_listing(make_page):
    [result] = bp.check_phone(listing(), make_page(html=fixture("phone-match.html"), final_url=URL))
    assert result.status is Status.PASS
    assert result.summary == ("The phone number on your Google Business Profile, (555) 010-0100, is also on your home "
                              "page.")


def test_phone_mismatch_names_both_numbers_and_never_fails(make_page):
    [result] = bp.check_phone(listing(), make_page(html=fixture("phone-mismatch.html"), final_url=URL))
    assert result.status is Status.WARN
    assert result.summary == ("Your home page shows (555) 010-0199 and (555) 010-0177, but your Google Business "
                              "Profile shows (555) 010-0100.")
    assert result.fix.startswith("If both numbers are yours and that is on purpose, nothing needs to change.")


def test_phone_is_not_checked_without_a_number_or_a_listing(make_page):
    [no_number] = bp.check_phone(listing(), make_page(html=fixture("phone-none.html"), final_url=URL))
    assert not no_number.ran
    [no_listing] = bp.check_phone(ExternalContext(place_outcome="not_found", errors={"place": "x"}),
                                  make_page(html=fixture("phone-match.html"), final_url=URL))
    assert not no_listing.ran
    assert bp.check_phone(ExternalContext(), make_page(html=fixture("phone-match.html"))) == []  # no lookup at all


def test_phone_digits_ignore_punctuation_and_country_code():
    assert bp.digits("+1 (555) 010-0100") == bp.digits("555.010.0100") == bp.digits("tel:5550100100"[4:]) == \
        "5550100100"
    assert bp.digits("20240117") == ""


def test_the_profile_link_names_an_inner_page():
    context = ExternalContext(place={"displayName": {"text": "X"}, "websiteUri": "https://example.com/contact-us/"},
                              place_match="website")
    assert bp.evaluate_website_link(context, "example.com").summary == (
        "Your Google Business Profile links to your contact page.")
    context.place["websiteUri"] = "https://example.com/"
    assert bp.evaluate_website_link(context, "example.com").summary == (
        "Your Google Business Profile links to your website.")


# ---------- page weight: what the server sends, and only that

def test_page_weight_scores_the_server_response_and_shows_the_rendered_size(make_page):
    from domain_health_check.checks.site import delivery
    page = make_page(html="<html>" + "x" * 1000 + "</html>", final_url=URL, byte_size=200_000,
                     rendered_html="<html>" + "y" * 900_000 + "</html>")
    [result] = delivery.check_page_weight(page)
    assert result.summary.startswith("Your home page is 200 KB before images")
    assert any(d.startswith("For comparison only, not scored: after a browser ran the page's scripts, the page was "
                            "900,013 bytes.") for d in result.details)
