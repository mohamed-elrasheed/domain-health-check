"""Writes a Markdown report a non-technical client can read."""

from __future__ import annotations

from pathlib import Path

from .models import CheckResult, DomainReport, Status

ICON = {Status.PASS: "✅", Status.WARN: "⚠️", Status.FAIL: "❌"}
WORD = {Status.PASS: "Good", Status.WARN: "Could be improved", Status.FAIL: "Needs action"}
NOT_CHECKED_ICON, NOT_CHECKED = "➖", "Not checked"


def _icon(r: CheckResult) -> str:
    return ICON[r.status] if r.ran else NOT_CHECKED_ICON


def _word(r: CheckResult) -> str:
    """A check that did not run verified nothing, so it never reads as Good or Could be improved."""
    return WORD[r.status] if r.ran else NOT_CHECKED


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _overall_sentence(report: DomainReport) -> str:
    fails, warns = report.count(Status.FAIL), report.count(Status.WARN)
    if fails:
        return (f"**{fails} item(s) need action soon**" + (f", and {warns} could be improved." if warns else "."))
    if warns:
        return f"**No urgent problems.** {warns} item(s) could be improved."
    return "**Everything we checked looks healthy.** No action is needed right now."


def render_markdown(report: DomainReport) -> str:
    lines = [
        f"# Domain health report: {report.domain}",
        "",
        f"*Checked on {report.checked_at:%d %B %Y at %H:%M} UTC*",
        "",
        "## Summary",
        "",
        _overall_sentence(report),
        "",
        f"{ICON[Status.PASS]} {report.count(Status.PASS)} good · "
        f"{ICON[Status.WARN]} {report.count(Status.WARN)} could be improved · "
        f"{ICON[Status.FAIL]} {report.count(Status.FAIL)} need action"
        + (f" · {NOT_CHECKED_ICON} {len(report.not_checked)} not checked" if report.not_checked else ""),
        "",
        "| Area | Check | Result | What we found |",
        "|---|---|---|---|",
    ]
    for r in report.results:
        lines.append(f"| {_cell(r.category)} | {_cell(r.name)} | {_icon(r)} {_word(r)} | {_cell(r.summary)} |")

    to_fix = sorted((r for r in report.results if r.ran and r.status is not Status.PASS), key=lambda r: -r.status.rank)
    if to_fix:
        lines += ["", "## What to fix", "", "Most urgent first."]
        for r in to_fix:
            lines += [
                "",
                f"### {ICON[r.status]} {r.name}",
                "",
                f"**What we found:** {r.summary}",
                "",
                f"**Why it matters:** {r.explanation}",
                "",
                f"**How to fix it:** {r.fix}",
            ]
            lines += _details(r.details)

    passed = [r for r in report.results if r.ran and r.status is Status.PASS]
    if passed:
        lines += ["", "## What's working well"]
        for r in passed:
            lines += ["", f"### {ICON[r.status]} {r.name}", "", r.summary, "", f"*Why it matters:* {r.explanation}"]
            lines += _details(r.details)

    if report.not_checked:
        lines += ["", "## What we could not check", "",
                  "These were not checked this time, so they are not counted anywhere above. None of them is a "
                  "finding about your website."]
        for r in report.not_checked:
            lines += ["", f"### {NOT_CHECKED_ICON} {r.name}", "", r.summary, "", f"*Why it matters:* {r.explanation}"]
            lines += _details(r.details)

    lines += [
        "",
        "## About this report",
        "",
        "These results come only from information that is publicly visible to anyone on the internet: DNS "
        "records, the domain registry, and a single ordinary visit to the website's home page, along with the "
        "robots.txt and sitemap files that search engines read. Nothing was "
        "scanned, probed or logged into. The checks show how things looked at the time above; settings "
        "can change at any time.",
        "",
    ]
    return "\n".join(lines)


def _details(details: list[str]) -> list[str]:
    if not details:
        return []
    return ["", "<details><summary>Technical details (for your IT provider)</summary>", ""] + \
        [f"- {_escape_detail(d)}" for d in details] + ["", "</details>"]


def _escape_detail(text: str) -> str:
    # Record values can contain characters that Markdown or HTML would interpret.
    return text.replace("<", "&lt;").replace(">", "&gt;")


def write_report(report: DomainReport, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{report.domain}-{report.checked_at:%Y-%m-%d}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
