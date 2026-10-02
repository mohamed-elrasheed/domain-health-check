"""Writes the Markdown report a non-technical client can read.

What goes in each section is decided in layout.py, which the PDF renderer
shares, so the two documents always say the same thing.

Retention: we keep the most recent report per domain and nothing older. A
stale scan is misleading, and holding data we have no use for is a liability.
Writing a report removes that domain's earlier ones.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import layout
from .models import CheckResult, DomainReport, Status

ICON = {Status.PASS: "✅", Status.WARN: "⚠️", Status.FAIL: "❌"}
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


def _summary_only(r: CheckResult) -> list[str]:
    return ["", f"### {_icon(r)} {r.name}", "", r.summary, "", f"*Why it matters:* {r.explanation}"] + _details(r.details)


def render_markdown(report: DomainReport) -> str:
    value, sentence = layout.headline(report)
    lines = [
        f"# Website health report: {report.domain}",
        "",
        f"*Checked on {report.checked_at:%d %B %Y at %H:%M} UTC*",
        "",
        (f"**{value} out of 100.** {sentence}" if value is not None else f"**{sentence}**"),
        "",
        layout.counts(report),
    ]

    worth = layout.worth_doing(report)
    if worth:
        lines += ["", "## Worth doing"]
        for r in worth:
            lines += _finding(r)
    more = layout.also_worth_improving(report)
    if more:
        lines += ["", "## Also worth improving"]
        for r in more:
            lines += _finding(r)

    lines += ["", "## Everything we checked", "", "| Area | Check | Result | What we found |", "|---|---|---|---|"]
    for r in report.results:
        lines.append(f"| {_cell(r.category)} | {_cell(r.name)} | {_icon(r)} {layout.label(r)} | {_cell(r.summary)} |")

    passed = layout.working(report)
    if passed:
        lines += ["", "## What is already working"]
        for r in passed:
            lines += _summary_only(r)
    if report.not_checked:
        lines += ["", "## What we could not check", "",
                  "These were not checked this time, so they are not counted anywhere above. None of them is a "
                  "finding about your website."]
        for r in report.not_checked:
            lines += _summary_only(r)

    lines += ["", "## What happens next", ""]
    for lead, rest in layout.next_steps(report):
        lines += [f"**{lead}** {rest}" if lead else rest, ""]
    lines += ["---", "", f"*{layout.about(report)}*", ""]
    return "\n".join(lines)


def output_path(report: DomainReport, output_dir: Path, suffix: str) -> Path:
    return output_dir / f"{report.domain}-{report.checked_at:%Y-%m-%d}{suffix}"


def prune_older(report: DomainReport, output_dir: Path) -> list[Path]:
    """Delete this domain's reports from earlier days, Markdown and PDF alike. Returns what was removed."""
    pattern = re.compile(re.escape(report.domain) + r"-(\d{4}-\d{2}-\d{2})\.(md|pdf)")
    today = f"{report.checked_at:%Y-%m-%d}"
    removed = []
    for path in output_dir.iterdir() if output_dir.is_dir() else []:
        match = pattern.fullmatch(path.name)
        if match and match.group(1) != today:
            path.unlink()
            removed.append(path)
    return removed


def write_report(report: DomainReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_path(report, output_dir, ".md")
    path.write_text(render_markdown(report), encoding="utf-8")
    prune_older(report, output_dir)
    return path
