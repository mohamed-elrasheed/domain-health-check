"""Writes the Markdown report a non-technical client can read.

What goes in each section is decided in layout.py, which the PDF renderer
shares, so the two documents always say the same thing.

Retention: every run is kept in its own reports/<domain>/<date>/ folder, and
nothing here deletes one. A second report on the same domain later is how we
show what changed.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from . import __version__, layout, pricelist
from .models import CheckResult, DomainReport, Status

ICON = {Status.PASS: "✅", Status.WARN: "⚠️", Status.FAIL: "❌", Status.INFO: "ℹ️"}
NOT_CHECKED_ICON = "➖"
DETAILS_HEADING = "Technical details, for whoever makes the change"


def _icon(r: CheckResult) -> str:
    return ICON[r.status] if r.ran else NOT_CHECKED_ICON


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _escape(text: str) -> str:
    # Record values can contain characters that Markdown or HTML would interpret.
    return text.replace("<", "&lt;").replace(">", "&gt;")


def _details(details: list[str]) -> list[str]:
    """A visible block, not <details>: a collapsed element prints as nothing."""
    if not details:
        return []
    return ["", f"*{DETAILS_HEADING}:*", ""] + [f"- {_escape(d)}" for d in details]


def _finding(r: CheckResult) -> list[str]:
    lines = ["", f"### {_icon(r)} {r.name}", "", f"*{layout.label(r)}*", "", f"**What we found:** {r.summary}",
             "", f"**Why it matters:** {r.explanation}"]
    if r.fix:
        lines += ["", f"**What to do:** {r.fix}"]
    return lines + _details(r.details)


def _brief(r: CheckResult) -> list[str]:
    """The top of the report: one line, the finding's name and its one-sentence statement. The full text is in its
    own section below."""
    return [f"- **{r.name}:** {r.summary}"]


def _summary_only(r: CheckResult) -> list[str]:
    return (["", f"### {_icon(r)} {r.name}", "", r.summary, "", f"*Why it matters:* {r.explanation}"]
            + _details(r.details))


def render_markdown(report: DomainReport) -> str:
    value, sentence = layout.headline(report)
    lines = [f"# Website health report: {report.domain}", "", f"*Checked on {report.checked_at:%d %B %Y at %H:%M} UTC*"]
    if report.screenshot:
        lines += ["", f"![{layout.SCREENSHOT_CAPTION}]({layout.SCREENSHOT_NAME})"]
    lines += ["", (f"Score: {value} out of 100. {sentence}" if value is not None
                   else f"{sentence} {layout.coverage(report)}".rstrip()), "", layout.counts(report)]
    if report.unreachable:  # nothing else in the report matters as much, so it comes first
        lines += ["", "## Your website could not be reached", "", report.unreachable]
    worth = layout.worth_doing(report)
    lines += ["", "## Worth doing first", ""]
    for r in worth:
        lines += _brief(r)
    if not worth:
        lines.append(layout.NOTHING_FIRST)
    if layout.nearby_line(report):
        lines += ["", layout.nearby_line(report)]
    lead, rest = layout.contact_line()
    lines += ["", f"**{lead}** {rest}", "", f"# {layout.FOR_THE_DEVELOPER}"]
    yourself = layout.fix_yourself(report)
    if yourself:
        lines += ["", "## Fix it yourself", "", layout.SELF_INTRO]
        for r in yourself:
            lines += _finding(r)
    developer = layout.needs_developer(report)
    if developer:
        lines += ["", "## Needs a developer", "", layout.DEVELOPER_INTRO]
        for r in developer:
            lines += _finding(r)
        lines += ["", layout.PRICING]
    checking = layout.worth_checking(report)
    if checking:
        lines += ["", "## Worth checking", "",
                  "We could not confirm these, so they may turn out to be fine. They are worth a quick check."]
        for r in checking:
            lines += _finding(r)

    lines += ["", "## Everything we checked", "", "| Area | Check | Result | What we found |", "|---|---|---|---|"]
    for r in report.results:
        lines.append(f"| {_cell(r.category)} | {_cell(r.name)} | {_icon(r)} {layout.label(r)} | {_cell(r.summary)} |")

    skipped = layout.not_checked(report)
    if skipped:
        lines += ["", "## What we could not check", "",
                  "These were not checked this time, so they are not counted anywhere above. None of them is a "
                  "finding about your website."]
        for r in skipped:
            lines += _summary_only(r)

    lines += ["", "## What happens next", ""]
    for lead, rest in layout.next_steps(report):
        lines += [f"**{lead}** {rest}" if lead else rest, ""]
    lines += _prices(report)
    lines += ["", "---", "", f"*{layout.about(report)}*", "", f"*{layout.stamp(report)}*", ""]
    return "\n".join(lines)


def _prices(report: DomainReport) -> list[str]:
    """The last section: each confirmed finding under its rung, with what that rung shows beside it."""
    lines = ["## " + layout.PRICES_HEADING, ""]
    groups = layout.priced(report)
    if not groups:
        return lines + [layout.prices_note(report)]
    lines.append(layout.PRICES_INTRO)
    for rung, results in groups:
        if rung.shows == "name":  # their instructions are already printed in their own section
            lines += ["", f"### {rung.label}", "", rung.intro, ""] + [f"- {r.name}" for r in results]
            continue
        lines += ["", f"### {rung.label}", ""] + [f"**{line}**" for line in layout.group_prices(rung)]
        lines += (["", rung.intro] if layout.group_prices(rung) else [rung.intro])
        lines += ["", f"| Finding | {rung.column} |", "|---|---|"]
        for name, answer in layout.price_rows(rung, results):
            lines.append(f"| {_cell(name)} | {_cell('; '.join(answer))} |")
    note = layout.prices_note(report)
    return lines + (["", note] if note else [])


def report_dir(report: DomainReport, output_dir: Path) -> Path:
    """reports/<domain>/<date>/, one folder per run day, holding every file the run wrote."""
    return output_dir / report.domain / f"{report.checked_at:%Y-%m-%d}"


def write_report(report: DomainReport, output_dir: Path) -> Path:
    folder = report_dir(report, output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "report.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    if report.screenshot:  # under reports/, which is never committed
        (folder / layout.SCREENSHOT_NAME).write_bytes(report.screenshot)
    return path


def record(report: DomainReport) -> dict:
    """Everything the report found and did, for report.json: the same results the documents render, the score,
    whether the run was complete and why not, and every request it made."""
    score, band = layout.headline(report)
    return {
        "domain": report.domain,
        "checked_at": report.checked_at.isoformat(timespec="seconds"),
        "tool": {"name": "domain-health-check", "version": __version__},
        "complete": report.complete,
        "incomplete": list(report.incomplete),
        "links": {"found": report.links_found, "requested": report.links_requested},
        "cms": {"name": report.cms, "evidence": report.cms_evidence} if report.cms else None,
        "nearby": report.nearby,  # averages only; no other business is named
        "screenshot": layout.SCREENSHOT_NAME if report.screenshot else None,
        "score": score,
        "reading": band,
        "website_loaded": report.website_loaded,
        "rendered": report.rendered,
        "unreachable": report.unreachable,
        "platform": {"name": report.platform, "evidence": report.platform_evidence} if report.platform else None,
        "results": [{**asdict(r), "status": r.status.name, "rung": _rung_key(r, report)} for r in report.results],
        "requests": [r.as_dict() for r in report.requests],
    }


def _rung_key(r: CheckResult, report: DomainReport) -> str | None:
    """The rung for a graded check; None for a row that grades nothing (a check that did not run, or a note)."""
    found = pricelist.load().rung_of(r.name, report.platform)
    return found.key if found else None


def write_record(report: DomainReport, output_dir: Path) -> Path:
    """report.json, and requests.log with one line per request made (time, source, method, target, outcome)."""
    folder = report_dir(report, output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "report.json"
    path.write_text(json.dumps(record(report), indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    (folder / "requests.log").write_text("".join(f"{r.line()}\n" for r in report.requests), encoding="utf-8")
    return path
