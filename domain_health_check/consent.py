"""Who a report may be run for.

A report runs only for a domain with a recorded submission: someone asked for it, through the form on
/digital, by email, in person, or it is one of our own. The record lives in submissions.yaml at the repository
root (gitignored, since it holds people's email addresses) and is written by
`domain-health-check record-submission`. Every report run is appended to a local run log with the record it
ran on.

A domain on our own lead list is never reported on, record or not: the lead list is consent-free by
definition, so the report refuses any domain that appears there, whatever else is said about it.
"""

from __future__ import annotations

import getpass
import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

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


SOURCES = ("form", "email", "in-person", "own")
NEEDS_EMAIL = ("form", "email")  # a submission that arrived in writing came from an address
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SubmissionError(ValueError):
    pass


@dataclass
class Submission:
    domain: str
    email: str
    received: date
    source: str

    def as_yaml(self) -> dict:
        return {"domain": self.domain, "email": self.email, "received": self.received.isoformat(),
                "source": self.source}


def validate(domain: str, email: str, received: date | str, source: str) -> Submission:
    if source not in SOURCES:
        raise SubmissionError(f"source must be one of {', '.join(SOURCES)}, not {source!r}")
    email = (email or "").strip()
    if source in NEEDS_EMAIL and not email:
        raise SubmissionError(f"a submission by {source} needs the email address it came from")
    if email and not EMAIL.match(email):
        raise SubmissionError(f"{email!r} is not an email address")
    if isinstance(received, str):
        try:
            received = date.fromisoformat(received)
        except ValueError:
            raise SubmissionError(f"received must be a date like 2026-10-05, not {received!r}") from None
    return Submission(_bare(domain), email, received, source)


def load_submissions(path: Path) -> dict[str, Submission]:
    """{domain: submission}. A missing file means nothing is recorded yet; a malformed one is an error."""
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    records = data.get("submissions", []) if isinstance(data, dict) else None
    if not isinstance(records, list):
        raise SubmissionError(f"{path}: expected a list under 'submissions'")
    found = {}
    for record in records:
        try:
            submission = validate(str(record["domain"]), record.get("email", ""), str(record["received"]),
                                  record["source"])
        except (KeyError, TypeError) as exc:
            raise SubmissionError(f"{path}: a record is missing {exc}") from None
        found[submission.domain] = submission
    return found


def record_submission(path: Path, submission: Submission) -> bool:
    """Write submission to path, replacing any earlier record for the same domain. True when it replaced one."""
    records = load_submissions(path)
    replaced = submission.domain in records
    records[submission.domain] = submission
    body = {"submissions": [r.as_yaml() for r in sorted(records.values(), key=lambda r: r.domain)]}
    path.write_text("# Who asked for a report. Gitignored: it holds people's email addresses.\n"
                    + yaml.safe_dump(body, sort_keys=False), encoding="utf-8")
    return replaced


def submitted(domain: str, records: dict[str, Submission]) -> Submission | None:
    return records.get(_bare(domain))


def log_run(domain: str, submission: Submission, log_path: Path, now: datetime | None = None) -> None:
    """Append one line per report run: when, who ran it, which domain, and the record it ran on."""
    now = now or datetime.now(timezone.utc)
    try:
        user = getpass.getuser()
    except Exception:  # no login name in some service environments
        user = "unknown"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"{now.isoformat(timespec='seconds')}\t{user}\treport\t{domain}\t"
                  f"source={submission.source}\treceived={submission.received.isoformat()}\n")


def add_command(domain: str) -> str:
    """The command that records a submission for domain, for the refusal message."""
    return (f"domain-health-check record-submission {domain} --source form --email ADDRESS "
            "[--received YYYY-MM-DD]")
