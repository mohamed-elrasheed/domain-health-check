"""The Markdown report and the layout it shares with the PDF."""

from datetime import datetime, timezone

import pytest

from domain_health_check import layout, scoring
from domain_health_check.models import EMAIL, SITE, WEBSITE, CheckResult, DomainReport, Status
from domain_health_check.report import output_path, prune_older, render_markdown, write_report

NOW = datetime(2026, 3, 14, 9, 30, tzinfo=timezone.utc)

# Real check names, so the score can be computed. Weights: 3, 3, 1, 2, 2, 1, 1.
NAMES = ["SSL certificate", "DMARC (anti-spoofing policy)", "Image alt text", "HSTS (always use HTTPS)",
         "Page title", "Social preview", "Heading order"]


def result(i: int, status: Status, ran: bool = True) -> CheckResult:
    category = [WEBSITE, EMAIL, SITE][i % 3]
    return CheckResult(category, NAMES[i], status, f"Found thing {i} | with pipe.", f"Why {i} matters.",
                       "" if status is Status.PASS else f"Fix {i}.", [f"record <{i}>"], ran)


def report_of(*statuses: Status) -> DomainReport:
    return DomainReport("example.com", NOW, [result(i, s) for i, s in enumerate(statuses)])


def section(md: str, heading: str) -> str:
    return md.split(f"## {heading}")[1].split("\n## ")[0]


def test_cells_and_details_are_escaped_and_details_are_visible():
    md = render_markdown(report_of(Status.WARN))
    assert "Found thing 0 \\| with pipe." in md
    assert "record &lt;0&gt;" in md
    assert "<details>" not in md  # a collapsed block prints as nothing
    assert "*Technical details, for whoever makes the change:*" in md


def test_passes_are_shown():
    md = render_markdown(report_of(Status.PASS, Status.WARN))
    assert "### ✅ SSL certificate" in section(md, "What is already working")


def test_next_steps_without_a_recheck_promise():
    for statuses in [(Status.PASS,), (Status.WARN,), (Status.FAIL, Status.WARN)]:
        md = render_markdown(report_of(*statuses))
        closing = section(md, "What happens next").lower()
        for promise in ("30 days", "again", "at no charge", "re-check", "next check"):
            assert promise not in closing, (statuses, promise)


def test_next_steps_wording_follows_what_was_found():
    assert "Nothing here needs fixing" in section(render_markdown(report_of(Status.PASS)), "What happens next")
    assert "Nothing here is urgent" in section(render_markdown(report_of(Status.WARN)), "What happens next")
    broken = section(render_markdown(report_of(Status.FAIL, Status.WARN)), "What happens next")
    assert "broken today" in broken and "Want us to handle it?" in broken


def test_not_run_never_reads_as_verified():
    report = DomainReport("example.com", NOW, [
        result(0, Status.PASS),
        CheckResult(SITE, "Real-world loading speed", Status.PASS, "Not enough traffic yet.", "Why speed.", ran=False),
        CheckResult(SITE, "Site health checks", Status.WARN, "We could not load the page.", "Why site.",
                    "Fix nothing.", ["Error: ConnectError"], ran=False),
        CheckResult(SITE, "Google speed test", Status.FAIL, "Did not run.", "Why test.", ran=False),
    ], website_loaded=False)
    md = render_markdown(report)
    table = section(md, "Everything we checked")
    for name in ("Real-world loading speed", "Site health checks", "Google speed test"):
        assert f"| {name} | ➖ Not checked |" in table
        assert f"### ➖ {name}" in section(md, "What we could not check")
    assert "1 checks passed · 0 could be improved · 0 need action · 3 not checked" in md
    assert "## Worth doing" not in md
    assert "Real-world loading speed" not in section(md, "What is already working")
    assert "Error: ConnectError" in section(md, "What we could not check")
    assert report.overall is Status.PASS
    assert "out of 100" not in md  # the website was not loaded, so there is no score at all


def test_about_mentions_google_only_when_its_test_ran():
    plain = layout.about(report_of(Status.PASS))
    assert "Nothing was scanned" in plain and "PageSpeed" not in plain
    with_speed = DomainReport("example.com", NOW, [CheckResult(SITE, "Mobile speed", Status.PASS, "s", "e")])
    assert "Google's own PageSpeed Insights test" in layout.about(with_speed)


def test_write_report_uses_domain_and_date(tmp_path):
    path = write_report(report_of(Status.PASS), tmp_path / "reports")
    assert path.name == "example.com-2026-03-14.md"
    assert path.read_text(encoding="utf-8").startswith("# Website health report")


def test_only_the_latest_report_per_domain_is_kept(tmp_path):
    folder = tmp_path / "reports"
    folder.mkdir()
    for name in ("example.com-2026-02-01.md", "example.com-2026-02-01.pdf", "example.com-2026-03-01.md",
                 "other.com-2026-02-01.md", "sub.example.com-2026-02-01.md", "notes.txt"):
        (folder / name).write_text("old", encoding="utf-8")
    write_report(report_of(Status.PASS), folder)
    assert sorted(p.name for p in folder.iterdir()) == [
        "example.com-2026-03-14.md", "notes.txt", "other.com-2026-02-01.md", "sub.example.com-2026-02-01.md"]


def test_same_day_pdf_is_kept(tmp_path):
    report = report_of(Status.PASS)
    tmp_path.joinpath(output_path(report, tmp_path, ".pdf").name).write_bytes(b"%PDF")
    assert prune_older(report, tmp_path) == []


def test_no_score_when_nothing_ran():
    report = DomainReport("example.com", NOW, [CheckResult(SITE, "Google speed test", Status.WARN, "s", "e",
                                                           ran=False)])
    assert layout.headline(report)[0] is None
    assert "We could not complete enough checks" in render_markdown(report)


def test_no_score_when_the_website_was_not_loaded():
    # A number computed over DNS and email alone would read as "my site is fine".
    report = DomainReport("example.com", NOW, [
        result(0, Status.PASS), result(1, Status.PASS),
        CheckResult(SITE, "Site health checks", Status.WARN, "We could not load it.", "Why.", ran=False),
    ], website_loaded=False)
    assert layout.headline(report) == (None, "Score: not available - we could not load your website.")
    assert layout.coverage(report) == "This report covers your domain and email only."
    md = render_markdown(report)
    assert "out of 100" not in md
    assert "**Score: not available - we could not load your website.** This report covers your domain and email " \
           "only." in md


def test_no_score_but_robots_finding_is_mentioned():
    report = DomainReport("example.com", NOW, [
        result(0, Status.PASS),
        CheckResult(SITE, "Search engine blocking", Status.FAIL, "Your robots.txt file returns a server error.", "Why."),
        CheckResult(SITE, "Site health checks", Status.WARN, "We stopped at robots.txt.", "Why.", ran=False),
    ], website_loaded=False)
    assert layout.headline(report)[0] is None
    assert layout.coverage(report) == "This report covers your domain and email, plus your robots.txt file only."
    assert "Search engine blocking" in section(render_markdown(report), "Worth doing")


def test_unreachable_site_leads_the_report_and_is_not_repeated_below():
    report = DomainReport("example.com", NOW, [
        result(0, Status.PASS), result(1, Status.WARN),
        CheckResult(SITE, "Site health checks", Status.WARN, "We could not load https://example.com/.", "Why.",
                    ran=False),
    ], website_loaded=False, unreachable="We could not reach your website at https://example.com/ at all.")
    md = render_markdown(report)
    block = md.index("## Your website could not be reached")
    assert block < md.index("## Needs a developer")  # DMARC is tier 5, so there is no Worth doing section
    assert "We could not reach your website at https://example.com/ at all." in md
    assert "## What we could not check" not in md  # the same fact, already the headline


def test_pdf_leads_with_the_unreachable_block_too():
    from domain_health_check import pdf
    report = DomainReport("example.com", NOW, [result(0, Status.PASS)], website_loaded=False,
                          unreachable="Your home page answers with a server error (status 503).")
    html = pdf.render_html(report)
    assert html.index('class="unreachable"') < html.index("Everything we checked")
    assert "Score: not available - we could not load your website." in html
    assert "/100" not in html


def test_about_mentions_the_business_listing_search_when_it_ran():
    from domain_health_check.models import LOCAL
    searched = DomainReport("example.com", NOW, [CheckResult(LOCAL, "Google Business Profile", Status.WARN, "s", "e",
                                                             ran=False)])
    assert "a search of Google's public business listings" in layout.about(searched)
    assert "business listings" not in layout.about(report_of(Status.PASS))


def test_information_is_its_own_state():
    info = CheckResult(EMAIL, "Mail servers (MX)", Status.INFO,
                       "This domain is not set up for email, which is normal if you use a different address for mail.",
                       "Why.")
    report = DomainReport("example.com", NOW, [result(0, Status.PASS), info])
    assert scoring.score(report.results) == scoring.score([result(0, Status.PASS)]) == 100  # never scored
    assert layout.worth_doing(report) == [] and layout.next_steps(report)[0][1].startswith("Nothing here needs")
    md = render_markdown(report)
    assert "| Mail servers (MX) | ℹ️ For information |" in md and "Not checked" not in md
    assert "### ℹ️ Mail servers (MX)" in section(md, "What is already working")
    assert "1 checks passed · 0 could be improved · 0 need action · 1 for information" in md
    from domain_health_check import pdf
    assert '<span class="pill info">For information</span>' in pdf.render_html(report)


# ---------- the owner-cost ladder, the two fix sections and "Worth checking"

def finding(category, name, status=Status.WARN, certain=True, fix="Do the thing."):
    return CheckResult(category, name, status, f"{name} finding.", f"Why {name} matters. More detail.", fix,
                       [f"{name} detail"], certain=certain)


def flooring_like() -> DomainReport:
    """The shape of a real small-business report: nothing broken, fifteen warnings, email gaps weighted highest."""
    return DomainReport("example.com", NOW, [
        finding(EMAIL, "DKIM (email signatures)", certain=False),
        finding(EMAIL, "DMARC (anti-spoofing policy)"),
        finding(WEBSITE, "HSTS (always use HTTPS)"),
        finding(WEBSITE, "Content Security Policy"),
        finding(SITE, "Meta description"),
        finding(SITE, "Main heading"),
        finding(SITE, "Image alt text"),
        finding(SITE, "Page weight"),
        finding("Google Business Profile", "Google Business Profile"),
        CheckResult(WEBSITE, "SSL certificate", Status.PASS, "Valid.", "Why."),
    ])


def test_ladder_puts_what_costs_customers_first():
    assert [r.name for r in layout.worth_doing(flooring_like())] == ["Main heading", "Meta description",
                                                                     "Image alt text"]


def test_tier_order_then_ladder_order():
    names = [r.name for r in layout.confirmed(flooring_like())]
    assert names == ["Main heading", "Meta description", "Image alt text", "Google Business Profile", "Page weight",
                     "DMARC (anti-spoofing policy)", "HSTS (always use HTTPS)", "Content Security Policy"]


def test_broken_and_customer_facing_beats_everything():
    report = flooring_like()
    report.results.append(finding(WEBSITE, "SSL certificate", Status.FAIL))
    assert layout.worth_doing(report)[0].name == "SSL certificate"


def test_a_hedged_finding_never_opens_the_report():
    report = DomainReport("example.com", NOW, [finding(SITE, "Meta description", certain=False),
                                               finding(EMAIL, "DKIM (email signatures)", certain=False),
                                               finding(SITE, "Canonical tag")])
    assert [r.name for r in layout.worth_doing(report)] == ["Canonical tag"]
    md = render_markdown(report)
    assert "DKIM" not in section(md, "Worth doing") and "Meta description" not in section(md, "Worth doing")
    assert "### ⚠️ Meta description" in section(md, "Worth checking")
    assert "### ⚠️ DKIM (email signatures)" in section(md, "Worth checking")
    assert md.index("## Worth checking") > md.index("## Needs a developer")


def test_every_confirmed_finding_is_in_exactly_one_fix_section():
    report = flooring_like()
    yourself = {r.name for r in layout.fix_yourself(report)}
    developer = {r.name for r in layout.needs_developer(report)}
    assert yourself == {"Main heading", "Meta description", "Image alt text", "Google Business Profile"}
    assert not yourself & developer
    assert yourself | developer == {r.name for r in layout.confirmed(report)}
    md = render_markdown(report)
    assert "### ⚠️ Main heading" in section(md, "Fix it yourself")
    assert "### ⚠️ DMARC (anti-spoofing policy)" in section(md, "Needs a developer")
    assert layout.PRICING in section(md, "Needs a developer")


def test_top_three_are_brief_with_no_technical_detail():
    worth = section(render_markdown(flooring_like()), "Worth doing")
    assert "Main heading finding. Why Main heading matters." in worth
    assert "More detail" not in worth and "Technical details" not in worth and "**What to do:** Do the thing." in worth


@pytest.mark.parametrize("results, sentence", [
    ([], "Nothing on your site is broken, and everything we checked looks good."),
    (["Content Security Policy"], "Nothing on your site is broken. A few behind-the-scenes settings could be stronger."),
    (["Content Security Policy", "DNSSEC", "HSTS (always use HTTPS)", "DMARC (anti-spoofing policy)"],
     "Nothing on your site is broken. 4 behind-the-scenes settings could be stronger."),
    (["Main heading"], "Nothing on your site is broken. One thing could be costing you customers."),
    (["Main heading", "Meta description", "Image alt text", "DNSSEC"],
     "Nothing on your site is broken. Here is what is costing you customers."),
])
def test_reading_tracks_what_was_found(results, sentence):
    report = DomainReport("example.com", NOW, [result(0, Status.PASS)] + [finding(SITE, n) for n in results])
    assert layout.headline(report)[1] == sentence


def test_reading_says_plainly_when_something_is_broken():
    report = DomainReport("example.com", NOW, [result(0, Status.FAIL), finding(SITE, "Main heading")])
    value, sentence = layout.headline(report)
    assert value is not None and sentence == "One thing on your site is broken today."
    assert f"**{value} out of 100.** {sentence}" in render_markdown(report)


def test_hedged_findings_do_not_count_as_costing_customers():
    report = DomainReport("example.com", NOW, [result(0, Status.PASS),
                                               finding(SITE, "Meta description", certain=False)])
    assert layout.headline(report)[1] == "Nothing on your site is broken, and everything we checked looks good."


def test_brief_leads_with_why_it_matters_for_the_owner_fixable_checks():
    # The brief uses the explanation's first sentence, so that sentence must be the reason, not a definition.
    from domain_health_check.checks.site import content
    for explanation in (content.ALT_TEXT_EXPLANATION, content.HEADING_ORDER_EXPLANATION):
        first = explanation.split(". ")[0]
        assert not first.startswith(("Alt text is", "Headings work like")), first


def test_top_section_is_never_padded():
    one = DomainReport("example.com", NOW, [finding(SITE, "Main heading"), finding(EMAIL, "DMARC (anti-spoofing policy)"),
                                            finding(WEBSITE, "Content Security Policy"), finding(WEBSITE, "DNSSEC")])
    assert [r.name for r in layout.worth_doing(one)] == ["Main heading"]
    behind_the_scenes = DomainReport("example.com", NOW, [finding(EMAIL, "DMARC (anti-spoofing policy)"),
                                                          finding(WEBSITE, "Content Security Policy")])
    assert layout.worth_doing(behind_the_scenes) == []
    assert "## Worth doing" not in render_markdown(behind_the_scenes)
    assert "### ⚠️ DMARC (anti-spoofing policy)" in section(render_markdown(behind_the_scenes), "Needs a developer")


def test_pricing_points_at_the_digital_division():
    assert "https://www.mizangroupllc.com/digital" in layout.PRICING and "/services" not in layout.PRICING


def test_alt_text_fix_has_no_invented_example():
    from domain_health_check.checks.site import content
    result = content.evaluate_alt_text([("https://example.com/a.jpg", None)] * 3)
    assert "such as" not in result.fix and "over the phone" in result.fix and "listed under Fix it yourself" in result.fix


def test_costing_customers_only_counts_findings_that_are_materially_wrong():
    mild = [CheckResult(SITE, "Meta description", Status.WARN, "s", "Why. More.", "f", measure=0.9),
            CheckResult(SITE, "Mobile speed", Status.WARN, "s", "Why. More.", "f", measure=0.8)]
    report = DomainReport("example.com", NOW, [result(0, Status.PASS)] + mild)
    assert layout.headline(report)[1] == "Nothing on your site is broken. A few small things could be better."
    report.results.append(finding("Google Business Profile", "Google Business Profile"))  # binary, credit 0.25
    assert layout.headline(report)[1] == "Nothing on your site is broken. One thing could be costing you customers."
