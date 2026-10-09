"""The automated report pipeline, up to but never including sending to the business.

Every hour (Windows Task Scheduler runs `domain-health-check intake`): read new submissions to the /digital form,
record each as consent, run the report with the details as submitted, and email the reviewer the PDF, the exit
code, anything incomplete and a draft message to the business. The draft is never sent by this tool, and nothing
here can email anyone but the reviewer (mailer.REVIEWER; mailer.send refuses anything else).

Rules, in the order they apply:
  * A submission is marked seen before anything else happens to it, so a crash midway can never process it twice.
  * A domain on the lead list is skipped and logged: the lead list is consent-free by definition.
  * A submission with no website gets a notice to the reviewer, since there is nothing to run.
  * Any failure, in reading the form or in one run, emails the reviewer the error. Never silence.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import consent, intake, mailer
from .config import ConfigError, DomainConfig, normalize_domain
from .pdf import write_pdf
from .report import write_record, write_report
from .runner import run_checks

LOG = Path("logs") / "intake.log"


@dataclass
class Outcome:
    processed: list[str] = field(default_factory=list)  # domains reported on
    skipped: list[str] = field(default_factory=list)  # why each skipped submission was skipped
    failed: list[str] = field(default_factory=list)
    exit_codes: dict[str, int] = field(default_factory=dict)
    emailed: int = 0  # review emails sent to the reviewer


def log(line: str, path: Path | None = None) -> None:
    path = path or LOG  # read at call time, so the log can be redirected
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\t{line}\n")


def process(submissions: list[intake.FormSubmission], cfg: mailer.MailerConfig, *, output: Path,
            submissions_path: Path, leads_path: Path, run_log: Path, seen_path: Path | None = None,
            smtp_factory=None) -> Outcome:
    """Handle every submission not seen before. Returns what happened to each."""
    send = (lambda msg: mailer.send(msg, cfg, smtp_factory=smtp_factory)) if smtp_factory else (
        lambda msg: mailer.send(msg, cfg))
    outcome = Outcome()
    seen_path = seen_path or intake.SEEN  # read at call time, so it can be redirected
    done = intake.seen(seen_path)
    for item in submissions:
        if item.id in done:
            continue
        intake.mark_seen(item.id, seen_path)  # first, so it can never run twice
        done.add(item.id)
        if item.unknown_fields:
            log(f"submission {item.id}: fields the config does not map: {', '.join(item.unknown_fields)}")
        try:
            _one(item, cfg, send, outcome, output=output, submissions_path=submissions_path, leads_path=leads_path,
                 run_log=run_log)
        except Exception as exc:  # never silence: the reviewer gets the error
            what = f"report for {item.domain or 'a submission'} (submission {item.id})"
            error = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            outcome.failed.append(f"{what}: {error}")
            log(f"FAILED {what}: {error}")
            _tell(send, mailer.failure_message(cfg, what, error))
    return outcome


def _one(item: intake.FormSubmission, cfg: mailer.MailerConfig, send, outcome: Outcome, *, output: Path,
         submissions_path: Path, leads_path: Path, run_log: Path) -> None:
    requested = (f"{item.business_name or '(no business name)'}, {item.city or '(no city)'}, "
                 f"{item.phone or '(no phone)'}, from {item.email or '(no email)'} on {item.submitted.isoformat()} "
                 "through the form on /digital")
    if not item.domain:
        outcome.skipped.append(f"submission {item.id}: no website given")
        log(f"skipped submission {item.id}: no website given")
        _tell(send, mailer.notice_message(cfg, f"NEW REQUEST WITHOUT A WEBSITE · {item.business_name or item.email}",
                                          f"A request came in through the form on /digital with no website, so "
                                          f"there is no report to run.\n\n{requested}\n"))
        return
    try:
        domain = normalize_domain(item.domain)
    except ConfigError as exc:
        raise ValueError(f"the website field {item.website!r} is not a domain: {exc}") from None
    listed = consent.on_lead_list(domain, consent.lead_domains(leads_path))
    if listed:
        outcome.skipped.append(f"{domain}: on the lead list (as {listed})")
        log(f"skipped {domain} (submission {item.id}): on the lead list as {listed}")
        return
    record = consent.validate(domain, item.email, item.submitted, "form", item.business_name, item.city, item.phone,
                              item.id)
    consent.record_submission(submissions_path, record)
    consent.log_run(domain, record, run_log)
    log(f"running {domain} (submission {item.id})")
    report = run_checks(DomainConfig(domain, business_name=item.business_name, city=item.city, phone=item.phone))
    write_report(report, output)
    write_record(report, output)
    pdf = None
    try:
        pdf = write_pdf(report, output)
    except OSError as exc:  # no Pango: the reviewer still hears about the run
        log(f"{domain}: the PDF could not be written: {exc}")
    exit_code = 2 if pdf is None else (0 if report.complete else 3)
    outcome.processed.append(domain)
    outcome.exit_codes[domain] = exit_code
    send(mailer.review_message(cfg, report, pdf, exit_code, requested, item.name, item.business_name))
    outcome.emailed += 1
    log(f"emailed the review of {domain} to {mailer.REVIEWER}, exit code {exit_code}")


def _tell(send, message) -> None:
    """Send a message to the reviewer; if even that fails, it is in the log."""
    try:
        send(message)
    except Exception as exc:
        log(f"could not email {mailer.REVIEWER}: {type(exc).__name__}: {exc}")


def intake_failed(cfg: mailer.MailerConfig, error: str, smtp_factory=None) -> None:
    """Reading the form failed: the reviewer gets the error."""
    log(f"FAILED reading the /digital form: {error}")
    message = mailer.failure_message(cfg, "Reading the /digital form", error)
    _tell((lambda msg: mailer.send(msg, cfg, smtp_factory=smtp_factory)) if smtp_factory
          else (lambda msg: mailer.send(msg, cfg)), message)
