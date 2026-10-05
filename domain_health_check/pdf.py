"""The PDF report, rendered from the DomainReport with WeasyPrint.

It is built from the same object and the same layout.py as the Markdown, never
by parsing the Markdown: regex-parsing Markdown into a PDF once dropped an
entire finding without an error.

Two print rules learned building docs/sample-report.pdf:
  * <details> does not render in print, so technical details are a visible,
    visually subordinate block.
  * Cards may break across pages, with break-after: avoid on headings.
    Unbreakable cards leave a ragged half page of white at the end of every page.

WeasyPrint needs Pango. On Windows that comes from MSYS2 (see the README); if
WEASYPRINT_DLL_DIRECTORIES is unset and MSYS2 is in its default place, we
point WeasyPrint at it.
"""

from __future__ import annotations

import os
from html import escape
from pathlib import Path

from . import layout
from .models import CheckResult, DomainReport, Status
from .report import DETAILS_HEADING, report_dir

ASSETS = Path(__file__).parent / "assets"
MSYS2_BIN = Path(r"C:\msys64\ucrt64\bin")
PILL = {Status.PASS: "good", Status.WARN: "improve", Status.FAIL: "action", Status.INFO: "info"}

CSS = """
@font-face { font-family: "PJS"; font-weight: 500; src: url("fonts/PlusJakartaSans-Medium.ttf"); }
@font-face { font-family: "PJS"; font-weight: 700; src: url("fonts/PlusJakartaSans-Bold.ttf"); }

@page {
  size: A4;
  margin: 16mm 16mm 20mm 16mm;
  @bottom-left { content: "Mizan Group LLC · mizangroupllc.com"; font: 500 7.5pt "PJS"; color: #8a9793; }
  @bottom-right { content: "Page " counter(page) " of " counter(pages); font: 500 7.5pt "PJS"; color: #8a9793; }
}
@page :first { margin-top: 0; }

* { box-sizing: border-box; }
body { font-family: "PJS", sans-serif; font-weight: 500; color: #20302e; font-size: 10pt; line-height: 1.55;
       margin: 0; }
strong, b, h1, h2, h3, .name { font-weight: 700; }

.masthead { background: #1f4b46; margin: 0 -16mm; padding: 16mm 16mm 13mm; }
.masthead img { width: 63pt; display: block; margin-bottom: 22pt; }
.eyebrow { color: #c6a761; font-size: 8pt; letter-spacing: 1.5pt; text-transform: uppercase; margin: 0 0 8pt; }
.masthead h1 { color: #f7f5f0; font-size: 22pt; line-height: 1.2; margin: 0 0 10pt; }
.domain { color: #c6a761; font-size: 13pt; margin: 0 0 2pt; }
.checked { color: #b9c6c2; font-size: 9pt; margin: 0; }

.score { background: #fbf9f6; border: 1px solid #d8ddd8; border-left: 3pt solid #c6a760; margin: 20pt 0 4pt;
         padding: 16pt 18pt; display: flex; align-items: center; }
.score .number { color: #1f4b47; font-size: 30pt; font-weight: 700; line-height: 1; margin-right: 18pt;
                 white-space: nowrap; }
.score .number small { color: #8a9793; font-size: 12pt; font-weight: 500; }
.score .reading { color: #1f4b47; font-size: 11pt; font-weight: 700; margin: 0 0 2pt; }
.score .counts { color: #5d6b67; font-size: 8.5pt; margin: 0; }
.score .coverage { color: #5d6b67; font-size: 9pt; margin: 0 0 2pt; }
.unreachable { border: 1px solid #ecd2cc; border-left: 3pt solid #8a2f22; background: #fbf3f1;
               padding: 12pt 18pt; margin: 14pt 0 0; break-inside: avoid; }
.unreachable h2 { color: #8a2f22; border: 0; margin: 0 0 6pt; padding: 0; font-size: 12pt; }
.unreachable p { margin: 0; }

h2 { color: #1f4b47; font-size: 13pt; margin: 22pt 0 12pt; padding-bottom: 6pt; border-bottom: 1px solid #e2e6e2;
     break-after: avoid; }

.card { border: 1px solid #edf0ed; border-left: 3pt solid #c6a760; margin: 0 0 12pt; background: #ffffff;
        break-inside: auto; }
.card.pass { border-left-color: #bccfc1; }
.card.skip { border-left-color: #d8ddd8; }
.card .body { padding: 13pt 18pt 4pt; }
.card.brief .summary { font-size: 10.5pt; }
p.intro { color: #5d6b67; font-size: 9pt; margin: -4pt 0 12pt; }
p.pricing { color: #5d6b67; font-size: 9pt; margin: 4pt 0 0; }
.card h3 { color: #1f4b47; font-size: 11pt; margin: 0 0 8pt; break-after: avoid; }
.card .summary { margin: 0 0 8pt; }
.card.pass .summary, .card.skip .summary { font-size: 10.5pt; }
.card.pass .explanation, .card.skip .explanation { color: #5d6b67; font-size: 8.5pt; }
.label { color: #8a9793; font-size: 7pt; letter-spacing: 1pt; text-transform: uppercase; margin: 0 0 4pt;
         break-after: avoid; }
.card p { margin: 0 0 9pt; }

.pill { display: inline-block; font-size: 7.5pt; padding: 2pt 7pt; margin-right: 8pt; vertical-align: 1pt;
        font-weight: 500; white-space: nowrap; }
.pill.good { background: #e6efe9; color: #2c6141; }
.pill.improve { background: #fbf0db; color: #8a6a1a; }
.pill.action { background: #f6e1dc; color: #8a2f22; }
.pill.skip { background: #edf0ed; color: #5d6b67; }
.pill.info { background: #e8eef2; color: #3e5566; }

.details { background: #f6f8f6; border-top: 1px solid #edf0ed; padding: 9pt 18pt 10pt; }
.details .label { margin-bottom: 5pt; }
.details ul { margin: 0; padding-left: 12pt; color: #5d6b67; font-size: 7.5pt; line-height: 1.6; }

table { width: 100%; border-collapse: collapse; font-size: 9pt; }
th { color: #8a9793; font-size: 7.5pt; font-weight: 500; letter-spacing: 1pt; text-transform: uppercase;
     text-align: left; padding: 0 6pt 8pt 0; border-bottom: 1px solid #d8ddd8; }
td { vertical-align: top; padding: 9pt 6pt 9pt 0; border-bottom: 1px solid #edf0ed; }
tr { break-inside: avoid; }
td.name { font-weight: 700; }
td.found { color: #5d6b67; }
col.area { width: 23%; } col.check { width: 26%; } col.result { width: 17%; } col.found { width: 34%; }

.next { background: #1f4b46; color: #f7f5f0; padding: 14pt 18pt 6pt; margin: 22pt 0 16pt; break-inside: avoid; }
.next h2 { color: #f7f5f0; border: 0; margin: 0 0 8pt; padding: 0; font-size: 12pt; }
.next p { font-size: 9.5pt; margin: 0 0 9pt; }
.next strong { color: #c6a761; }
.about { color: #5d6b67; font-size: 8pt; border-top: 1px solid #e2e6e2; padding-top: 12pt; }
"""


def _pill(r: CheckResult) -> str:
    kind = PILL[r.status] if r.ran else "skip"
    return f'<span class="pill {kind}">{escape(layout.label(r))}</span>'


def _details(r: CheckResult) -> str:
    if not r.details:
        return ""
    items = "".join(f"<li>{escape(d)}</li>" for d in r.details)
    return f'<div class="details"><p class="label">{escape(DETAILS_HEADING)}</p><ul>{items}</ul></div>'


def _finding(r: CheckResult) -> str:
    fix = (f'<p class="label">What to do</p><p>{escape(r.fix)}</p>' if r.fix else "")
    return (f'<div class="card finding"><div class="body"><h3>{_pill(r)}{escape(r.name)}</h3>'
            f'<p class="summary">{escape(r.summary)}</p>'
            f'<p class="label">Why it matters</p><p>{escape(r.explanation)}</p>{fix}</div>{_details(r)}</div>')


def _brief(r: CheckResult) -> str:
    """The top of the report: two or three sentences and what to do, no technical detail."""
    fix = f'<p class="label">What to do</p><p>{escape(r.fix)}</p>' if r.fix else ""
    return (f'<div class="card finding brief"><div class="body"><h3>{_pill(r)}{escape(r.name)}</h3>'
            f'<p class="summary">{escape(layout.brief(r))}</p>{fix}</div></div>')


def _summary_card(r: CheckResult, kind: str) -> str:
    return (f'<div class="card {kind}"><div class="body"><h3>{_pill(r)}{escape(r.name)}</h3>'
            f'<p class="summary">{escape(r.summary)}</p><p class="explanation">{escape(r.explanation)}</p></div>'
            f'{_details(r)}</div>')


def render_html(report: DomainReport) -> str:
    value, sentence = layout.headline(report)
    number = f'<div class="number">{value}<small>/100</small></div>' if value is not None else ""
    parts = [
        f'<div class="masthead"><img src="mizan-mark.png" alt="Mizan Group">'
        f'<p class="eyebrow">Website health report</p><h1>What we found on your site</h1>'
        f'<p class="domain">{escape(report.domain)}</p>'
        f'<p class="checked">Checked {report.checked_at.day} {report.checked_at:%B %Y at %H:%M} UTC</p></div>',
        f'<div class="score">{number}<div><p class="reading">{escape(sentence)}</p>'
        + (f'<p class="coverage">{escape(layout.coverage(report))}</p>' if layout.coverage(report) else "")
        + f'<p class="counts">{escape(layout.counts(report))}</p></div></div>',
    ]
    if report.unreachable:  # nothing else in the report matters as much, so it comes first
        parts.append(f'<div class="unreachable"><h2>Your website could not be reached</h2>'
                     f"<p>{escape(report.unreachable)}</p></div>")
    worth = layout.worth_doing(report)
    if worth:
        parts.append("<h2>Worth doing</h2>" + "".join(_brief(r) for r in worth))
    sections = [
        ("Fix it yourself", "You can do these from your website builder or your Google Business Profile, without a "
                            "developer.", layout.fix_yourself(report), ""),
        ("Needs a developer", "These involve your domain settings, your server or your site's code. Pass them to "
                              "whoever looks after your website and email.", layout.needs_developer(report),
         f'<p class="pricing">{escape(layout.PRICING)}</p>'),
        ("Worth checking", "We could not confirm these, so they may turn out to be fine. They are worth a quick check.",
         layout.worth_checking(report), ""),
    ]
    for heading, intro, results, closing in sections:
        if results:
            parts.append(f'<h2>{heading}</h2><p class="intro">{escape(intro)}</p>'
                         + "".join(_finding(r) for r in results) + closing)

    rows = "".join(
        f'<tr><td>{escape(r.category)}</td><td class="name">{escape(r.name)}</td><td>{_pill(r)}</td>'
        f'<td class="found">{escape(r.summary)}</td></tr>' for r in report.results)
    parts.append('<h2>Everything we checked</h2><table><colgroup><col class="area"><col class="check">'
                 '<col class="result"><col class="found"></colgroup><thead><tr><th>Area</th><th>Check</th>'
                 f'<th>Result</th><th>What we found</th></tr></thead><tbody>{rows}</tbody></table>')

    passed = layout.working(report)
    if passed:
        parts.append("<h2>What is already working</h2>" + "".join(_summary_card(r, "pass") for r in passed))
    skipped = layout.not_checked(report)
    if skipped:
        parts.append("<h2>What we could not check</h2><p>These were not checked this time, so they are not counted "
                     "anywhere above. None of them is a finding about your website.</p>"
                     + "".join(_summary_card(r, "skip") for r in skipped))

    steps = "".join(f"<p>{f'<strong>{escape(lead)}</strong> ' if lead else ''}{escape(rest)}</p>"
                    for lead, rest in layout.next_steps(report))
    parts.append(f'<div class="next"><h2>What happens next</h2>{steps}</div>'
                 f'<p class="about">{escape(layout.about(report))}</p>')

    title = f"Website health report · {escape(report.domain)}"
    footer = f"Mizan Group LLC · mizangroupllc.com · {layout.stamp(report)}".replace('"', "")
    page_footer = f'@page {{ @bottom-left {{ content: "{footer}"; }} }}'
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{title}</title>'
            f"<style>{CSS}{page_footer}</style></head><body>{''.join(parts)}</body></html>")


def _weasyprint():
    if os.name == "nt" and not os.environ.get("WEASYPRINT_DLL_DIRECTORIES") and MSYS2_BIN.is_dir():
        os.environ["WEASYPRINT_DLL_DIRECTORIES"] = str(MSYS2_BIN)
    import weasyprint  # imported late: it needs native libraries the rest of the tool does not
    return weasyprint


def render_pdf(report: DomainReport) -> bytes:
    weasyprint = _weasyprint()
    return weasyprint.HTML(string=render_html(report), base_url=str(ASSETS)).write_pdf()


def write_pdf(report: DomainReport, output_dir: Path) -> Path:
    folder = report_dir(report, output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "report.pdf"
    path.write_bytes(render_pdf(report))
    return path
