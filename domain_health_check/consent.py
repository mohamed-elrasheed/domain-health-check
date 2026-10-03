"""Who a report may be run for.

A report runs only for a domain someone submitted through the form on /digital: the submission is the
consent. Submissions are not recorded anywhere this tool can read yet, so every domain counts as
unrecorded and the CLI refuses it unless the operator passes --authorized, confirming they have seen the
submission. Each such run is appended to a local log, so there is a record of every report that ran on
someone's word rather than on a stored submission.
"""

from __future__ import annotations

import getpass
from datetime import datetime, timezone
from pathlib import Path


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
