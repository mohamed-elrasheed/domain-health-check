"""Who a report may be run for.

A report runs only for a domain someone submitted through the form on /digital: the submission is the
consent. A domain on our own lead list is never one: the lead list is consent-free by definition, so the
report refuses any domain that appears there, whatever else is said about it.

Submissions are not recorded anywhere this tool can read yet, so every domain counts as unrecorded and the
CLI refuses it unless the operator passes --authorized, confirming they have seen the submission. Each such run is appended to a local log, so there is a record of every report that ran on
someone's word rather than on a stored submission.
"""

from __future__ import annotations

import getpass
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

# A token that looks like a domain but is a file name.
FILE_SUFFIXES = {"txt", "png", "jpg", "jpeg", "gif", "webp", "svg", "html", "htm", "xml", "json", "php", "js",
                 "css", "pdf"}
DOMAIN_IN_TEXT = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b")


class LeadListUnreadable(Exception):
    pass


def _bare(host: str) -> str:
    return host.strip().lower().rstrip(".").removeprefix("www.")


def lead_domains(path: Path) -> set[str]:
    """Every domain on the lead list: the host of every link on every lead, and every domain written
    anywhere in the file (hand notes name domains that are not linked). A domain mentioned only in text
    that is the parent of a linked host, such as a site builder named in a note, is a platform, not a
    business, and is left out so it does not shut out everyone who builds there."""
    try:
        text = path.read_text(encoding="utf-8")
        leads = json.loads(text)
    except (OSError, ValueError) as exc:
        raise LeadListUnreadable(f"{path}: {exc}") from None
    linked = set()
    for lead in leads:
        for link in lead.get("links", []):
            url = link[1] if isinstance(link, (list, tuple)) else link
            host = urlsplit(url if "//" in url else f"https://{url}").hostname
            if host:
                linked.add(_bare(host))
    written = {_bare(m) for m in DOMAIN_IN_TEXT.findall(text.lower())
               if m.rsplit(".", 1)[-1] not in FILE_SUFFIXES}
    platforms = {d for d in written if any(host.endswith(f".{d}") for host in linked)}
    return linked | (written - platforms)


def on_lead_list(domain: str, domains: set[str]) -> str | None:
    """The lead-list domain that domain is, contains or sits under, or None."""
    domain = _bare(domain)
    for listed in sorted(domains):
        if domain == listed or domain.endswith(f".{listed}") or listed.endswith(f".{domain}"):
            return listed
    return None


def recorded_submission(domain: str) -> bool:
    """Whether the /digital form has a stored submission for domain. There is no store yet, so never."""
    return False


def log_authorized(domains: list[str], log_path: Path, now: datetime | None = None) -> None:
    """Append one line per domain run under --authorized: when, who, and which domain."""
    now = now or datetime.now(timezone.utc)
    try:
        user = getpass.getuser()
    except Exception:  # no login name in some service environments
        user = "unknown"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        for domain in domains:
            log.write(f"{now.isoformat(timespec='seconds')}\t{user}\t--authorized\t{domain}\n")
