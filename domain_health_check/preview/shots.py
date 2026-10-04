"""Publishing sweep's screenshots into the private previews repository, for the lead board to show.

Copies sweep-output/<id>/phone.png and desktop.png to public/_shots/<id>/ in mizan-previews, where they are
served (noindex, and disallowed in robots.txt) and pushed with the previews. A screenshot only ever lives in
sweep-output/ (gitignored) and the private previews repository, never in domain-health-check.

A lead sweep could not reach this time keeps its last published screenshots. A lead that has left the lead
list loses them: we do not keep pictures of a business we are no longer talking to.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .render import PREVIEW_BASE, shared_files

KINDS = ("phone", "desktop")


def url(lead_id: str, kind: str) -> str:
    return f"{PREVIEW_BASE}/_shots/{lead_id}/{kind}.png"


def publish(screenshots: Path, previews: Path, lead_ids: list[str]) -> dict[str, dict[str, str | None]]:
    """{lead id: {"phone": url or None, "desktop": url or None}} for what is published after copying."""
    public = previews / "public"
    public.mkdir(exist_ok=True)
    for name, text in shared_files().items():
        (public / name).write_text(text, encoding="utf-8", newline="\n")
    shots = public / "_shots"
    shots.mkdir(exist_ok=True)
    keep = set(lead_ids)
    for folder in shots.iterdir():
        if folder.is_dir() and folder.name not in keep:
            shutil.rmtree(folder)
    published: dict[str, dict[str, str | None]] = {}
    for lead_id in lead_ids:
        published[lead_id] = {}
        for kind in KINDS:
            source = screenshots / lead_id / f"{kind}.png"
            target = shots / lead_id / f"{kind}.png"
            if source.is_file() and (not target.is_file() or target.read_bytes() != source.read_bytes()):
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            published[lead_id][kind] = url(lead_id, kind) if target.is_file() else None
    return published


def preview_url(previews: Path, lead_id: str) -> str | None:
    return f"{PREVIEW_BASE}/{lead_id}/" if (previews / "public" / lead_id / "index.html").is_file() else None
