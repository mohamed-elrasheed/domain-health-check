"""domain-health-check-preview: write one prospect's proposal into the private previews repository.

    domain-health-check-preview some-lead-id --previews ../mizan-previews [--push]

Reads the lead from leads.json (read only) and the phone screenshot sweep took from
sweep-output/<lead-id>/phone.png, and writes public/<lead-id>/ in the previews repository: index.html (the
proposal), site.html (the proposed home page) and current.png (their site today). It also keeps the
repository's shared files in place: robots.txt, _headers, _redirects and the root page. With --push it
commits the lead's folder and pushes. It never writes into this repository.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

from ..sweep import hosts
from . import render
from .content import LeadError, proposal

PREVIEWS = Path("..") / "mizan-previews"  # the private previews repository; tests point this elsewhere


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="domain-health-check-preview",
                                     description="Write a proposal page for one lead into the private previews repository.")
    parser.add_argument("lead_id", nargs="?",
                        help="the lead to write a proposal for; leave out with --push to push what is there "
                             "(screenshots sweep published, for instance)")
    parser.add_argument("--leads", type=Path, default=Path("leads.json"), help="lead list (default: leads.json)")
    parser.add_argument("--screenshots", type=Path, default=Path("sweep-output"),
                        help="where sweep saved its screenshots (default: sweep-output)")
    parser.add_argument("--previews", type=Path, default=PREVIEWS,
                        help="the private previews repository (default: ../mizan-previews)")
    parser.add_argument("--push", action="store_true", help="commit the lead's folder and push")
    return parser


def find_lead(path: Path, lead_id: str) -> dict:
    for lead in json.loads(path.read_text(encoding="utf-8")):
        if lead.get("id") == lead_id:
            return lead
    raise LeadError(f"no lead with id {lead_id!r} in {path}")


def current_site(lead: dict) -> str:
    """The host of the site they have today: the first listed address that is not someone else's platform."""
    for _, url in lead.get("links", []):
        if hosts.kind(url) != "third-party":
            return hosts.host(url)
    return ""


def read_name(screenshots: Path, lead_id: str) -> tuple[str, str]:
    """(name, where) as sweep read it from their own page on its last visit, or ("", "")."""
    path = screenshots / lead_id / "result.json"
    if not path.exists():
        return "", ""
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("display_name", ""), data.get("display_name_source", "")


def name_note(lead: dict, read: tuple[str, str]) -> str:
    """What to say about the name on the pages, so it is confirmed before anything goes live under it."""
    if lead.get("display_name"):
        if lead.get("display_name_confirmed"):
            return ""
        source = lead.get("display_name_source") or "the lead record"
        return f"Name \"{lead['display_name']}\" is from {source}. Confirm it on the call."
    if read[0]:
        return f"Name \"{read[0]}\" was read from {read[1]}. Confirm it on the call."
    return f"No name read from their site; the pages use our lead name \"{lead['n']}\". Confirm it on the call."


def write(lead: dict, screenshot: Path, previews: Path, today: date, name_read: str = "") -> Path:
    if not (previews / ".git").is_dir():
        raise LeadError(f"{previews} is not a git repository; create the private previews repository first")
    if not screenshot.is_file():
        raise LeadError(f"no screenshot at {screenshot}; run domain-health-check-sweep --only {lead['id']} first")
    p = proposal(lead, current_site(lead), name_read)
    public = previews / "public"
    public.mkdir(exist_ok=True)
    for name, text in render.shared_files().items():
        (public / name).write_text(text, encoding="utf-8", newline="\n")
    folder = public / p.lead_id
    if folder.exists():
        shutil.rmtree(folder)  # a stale proposal is replaced, never layered on
    folder.mkdir()
    photographed = datetime.fromtimestamp(screenshot.stat().st_mtime).date()
    (folder / "index.html").write_text(render.proposal_page(p, photographed), encoding="utf-8", newline="\n")
    (folder / "site.html").write_text(render.site_page(p, today), encoding="utf-8", newline="\n")
    shutil.copyfile(screenshot, folder / "current.png")
    return folder


def push(previews: Path, lead_id: str | None) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(previews), *args], check=True)
    git("add", "public")
    if subprocess.run(["git", "-C", str(previews), "diff", "--cached", "--quiet"]).returncode == 0:
        print("Nothing changed; nothing to push.")
        return
    git("commit", "-q", "-m", f"Proposal for {lead_id}" if lead_id else "Update published screenshots")
    git("push", "-q")


def main(argv: list[str] | None = None, today: date | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.lead_id is None:
        if not args.push:
            print("Error: give a lead id, or --push to push what is already in the previews repository.",
                  file=sys.stderr)
            return 2
        push(args.previews, None)
        print("Pushed.")
        return 0
    try:
        lead = find_lead(args.leads, args.lead_id)
        read = read_name(args.screenshots, args.lead_id)
        folder = write(lead, args.screenshots / args.lead_id / "phone.png", args.previews, today or date.today(),
                       read[0])
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"Wrote {folder}")
    note = name_note(lead, read)
    if note:
        print(f"  {note}")
    if not lead.get("hours"):
        print("  Hours are not on the lead yet; the page shows them as not confirmed.")
    if args.push:
        push(args.previews, args.lead_id)
        print("Pushed.")
    return 0
