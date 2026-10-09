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

import base64
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
.masthead img { width: 63pt; display: block; margin-bottom: 14pt; }
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

.prices { break-before: page; }
.prices h2 { margin-top: 0; }
.prices h3 { color: #1f4b47; font-size: 11pt; margin: 18pt 0 4pt; break-after: avoid; }
.prices p.intro { margin: 0 0 8pt; }
.prices p.note { margin-top: 12pt; }
.prices p.price { color: #1f4b47; font-weight: 700; margin: 0 0 4pt; }
.prices ul.names { margin: 0 0 4pt; padding-left: 14pt; }
.prices ul.names li { margin: 0 0 2pt; }
ul.worth { margin: 0 0 8pt; padding-left: 14pt; }
ul.worth li { margin: 0 0 6pt; }
.prices + .about { margin-top: 18pt; }

table.page-one { margin-top: 16pt; border-collapse: collapse; }
table.page-one td { border: 0; padding: 0; vertical-align: top; }
table.page-one td.left { width: 60mm; padding-right: 10mm; }
table.page-one img.shot { width: 58mm; display: block; border: 1px solid #d8ddd8; }
table.page-one p.caption { color: #8a9793; font-size: 7.5pt; margin: 4pt 0 10pt; }
table.page-one p.small-score { color: #1f4b47; font-size: 18pt; font-weight: 700; margin: 0 0 2pt; }
table.page-one p.small-score small { color: #8a9793; font-size: 9pt; font-weight: 500; }
table.page-one p.reading { color: #1f4b47; font-size: 9pt; font-weight: 700; margin: 0 0 3pt; }
table.page-one p.counts, table.page-one p.coverage { color: #5d6b67; font-size: 7.5pt; margin: 0 0 2pt; }
table.page-one h2 { margin-top: 0; }
table.page-one p.nearby { margin: 14pt 0 0; }
table.page-one p.reach { margin: 14pt 0 0; }
h1.for-developer { break-before: page; color: #1f4b47; font-size: 18pt; margin: 0 0 6pt; }
.prices td p { margin: 0 0 3pt; }
col.finding { width: 34%; } col.answer { width: 66%; }
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
    """The top of the report: one line, the finding's name and its one-sentence statement. The full text is in its
    own section below."""
    return f'<li><strong>{escape(r.name)}:</strong> {escape(r.summary)}</li>'


def _summary_card(r: CheckResult, kind: str) -> str:
    return (f'<div class="card {kind}"><div class="body"><h3>{_pill(r)}{escape(r.name)}</h3>'
            f'<p class="summary">{escape(r.summary)}</p><p class="explanation">{escape(r.explanation)}</p></div>'
            f'{_details(r)}</div>')


def _prices(report: DomainReport) -> str:
    """The last page: each confirmed finding under its rung, with what that rung shows beside it."""
    groups = layout.priced(report)
    note = layout.prices_note(report)
    if not groups:
        return f'<div class="prices"><h2>{escape(layout.PRICES_HEADING)}</h2><p>{escape(note)}</p></div>'
    body = [f'<p class="intro">{escape(layout.PRICES_INTRO)}</p>']
    for rung, results in groups:
        if rung.shows == "name":  # their instructions are already printed in their own section
            names = "".join(f"<li>{escape(r.name)}</li>" for r in results)
            body.append(f'<h3>{escape(rung.label)}</h3><p class="intro">{escape(rung.intro)}</p>'
                        f'<ul class="names">{names}</ul>')
            continue
        rows = "".join(f'<tr><td class="name">{escape(name)}</td><td>'
                       + "".join(f"<p>{escape(line)}</p>" for line in lines) + "</td></tr>"
                       for name, lines in layout.price_rows(rung, results))
        body.append(f'<h3>{escape(rung.label)}</h3>'
                    + "".join(f'<p class="price">{escape(line)}</p>' for line in layout.group_prices(rung))
                    + f'<p class="intro">{escape(rung.intro)}</p>'
                    f'<table><colgroup><col class="finding"><col class="answer"></colgroup><thead><tr><th>Finding</th>'
                    f"<th>{escape(rung.column)}</th></tr></thead><tbody>{rows}</tbody></table>")
    if note:
        body.append(f'<p class="intro note">{escape(note)}</p>')
    return f'<div class="prices"><h2>{escape(layout.PRICES_HEADING)}</h2>{"".join(body)}</div>'


def _page_one(report: DomainReport) -> str:
    """The owner's one-page summary: their home page at phone width with the score under it, and beside it the
    top three findings, the nearby comparison and how to reach us."""
    value, sentence = layout.headline(report)
    shot = ""
    if report.screenshot:
        data = base64.b64encode(report.screenshot).decode("ascii")
        shot = (f'<img class="shot" src="data:image/png;base64,{data}" alt="{escape(layout.SCREENSHOT_CAPTION)}">'
                f'<p class="caption">{escape(layout.SCREENSHOT_CAPTION)}</p>')
    number = f'<p class="small-score">{value}<small>/100</small></p>' if value is not None else ""
    coverage = f'<p class="coverage">{escape(layout.coverage(report))}</p>' if layout.coverage(report) else ""
    left = (f'{shot}{number}<p class="reading">{escape(sentence)}</p>{coverage}'
            f'<p class="counts">{escape(layout.counts(report))}</p>')
    right = []
    if report.unreachable:  # nothing else in the report matters as much, so it comes first
        right.append(f'<div class="unreachable"><h2>Your website could not be reached</h2>'
                     f"<p>{escape(report.unreachable)}</p></div>")
    worth = layout.worth_doing(report)
    right.append("<h2>Worth doing first</h2>" + (
        '<ul class="worth">' + "".join(_brief(r) for r in worth) + "</ul>" if worth
        else f"<p>{escape(layout.NOTHING_FIRST)}</p>"))
    if layout.nearby_line(report):
        right.append(f'<p class="nearby">{escape(layout.nearby_line(report))}</p>')
    lead, rest = layout.contact_line()
    right.append(f'<p class="reach"><strong>{escape(lead)}</strong> {escape(rest)}</p>')
    return (f'<table class="page-one"><tr><td class="left">{left}</td><td class="right">{"".join(right)}</td></tr>'
            "</table>")


def render_html(report: DomainReport) -> str:
    parts = [
        f'<div class="masthead"><img src="mizan-mark.png" alt="Mizan Group">'
        f'<p class="eyebrow">Website health report</p><h1>What we found on your site</h1>'
        f'<p class="domain">{escape(report.domain)}</p>'
        f'<p class="checked">Checked {report.checked_at.day} {report.checked_at:%B %Y at %H:%M} UTC</p></div>',
        _page_one(report),
        f'<h1 class="for-developer">{escape(layout.FOR_THE_DEVELOPER)}</h1>',
    ]
    sections = [
        ("Fix it yourself", layout.SELF_INTRO, layout.fix_yourself(report), ""),
        ("Needs a developer", layout.DEVELOPER_INTRO, layout.needs_developer(report),
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

    skipped = layout.not_checked(report)
    if skipped:
        parts.append("<h2>What we could not check</h2><p>These were not checked this time, so they are not counted "
                     "anywhere above. None of them is a finding about your website.</p>"
                     + "".join(_summary_card(r, "skip") for r in skipped))

    steps = "".join(f"<p>{f'<strong>{escape(lead)}</strong> ' if lead else ''}{escape(rest)}</p>"
                    for lead, rest in layout.next_steps(report))
    parts.append(f'<div class="next"><h2>What happens next</h2>{steps}</div>')
    parts.append(_prices(report))
    parts.append(f'<p class="about">{escape(layout.about(report))}</p>')  # last, after the price page

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
