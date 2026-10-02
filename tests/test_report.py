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


def test_header_has_domain_date_score_and_reading():
    report = report_of(Status.PASS, Status.WARN, Status.FAIL)
    md = render_markdown(report)
    assert md.startswith("# Website health report: example.com")
    assert "*Checked on 14 March 2026 at 09:30 UTC*" in md
    value = scoring.score(report.results)
    assert f"**{value} out of 100.** {layout.SENTENCE[scoring.reading(value)]}" in md
    assert "1 checks passed · 1 could be improved · 1 need action" in md


def test_worth_doing_is_top_three_by_weight_then_severity_and_nothing_is_dropped():
    # Weights: alt text 1, HSTS 2, title 2, social 1, heading order 1; DMARC 3.
    report = report_of(Status.PASS, Status.WARN, Status.WARN, Status.WARN, Status.FAIL, Status.WARN, Status.WARN)
    md = render_markdown(report)
    worth = section(md, "Worth doing")
    shown = [line.split(" ", 2)[2] for line in worth.splitlines() if line.startswith("### ")]
    # DMARC weighs 3; title and HSTS weigh 2, and the title FAIL comes before the HSTS WARN.
    assert shown == ["DMARC (anti-spoofing policy)", "Page title", "HSTS (always use HTTPS)"]
    more = section(md, "Also worth improving")
    for name in ("Image alt text", "Social preview", "Heading order"):
        assert name in more
    for r in report.results:  # every finding appears in the table, passes included
        assert f"| {r.name} |" in section(md, "Everything we checked")


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


def test_clean_report_is_short():
    md = render_markdown(report_of(Status.PASS, Status.PASS))
    assert "## Worth doing" not in md and "## Also worth improving" not in md
    assert "Your site is in good shape." in md


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


@pytest.mark.parametrize("statuses, sentence", [
    ((Status.PASS,), "Your site is in good shape."),
    ((Status.FAIL,), "Your site needs work in a few areas."),
])
def test_headline_sentence(statuses, sentence):
    assert layout.headline(report_of(*statuses))[1] == sentence


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
    assert block < md.index("## Worth doing")
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
