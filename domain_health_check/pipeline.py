"""The automated report pipeline, up to but never including sending to the business.

Every hour (Windows Task Scheduler runs `domain-health-check intake`): read new submissions to the /digital form,
record each as consent, run the report with the details as submitted, and email the reviewer the PDF, the exit
code, anything incomplete and a draft message to the business. When AI drafts are on (agents.py), that draft is
written by the draft agent and must pass the code check and three reviews; otherwise it is the template. The
draft is never sent by this tool, and nothing here can email anyone but the reviewer (mailer.REVIEWER;
mailer.send refuses anything else).

Rules, in the order they apply:
  * A submission is marked seen before anything else happens to it, so a crash midway can never process it twice.
  * A domain on the lead list is skipped and logged: the lead list is consent-free by definition.
  * A submission with no website gets a notice to the reviewer, since there is nothing to run.
  * A domain reported in the last REPEAT_DAYS gets no second report: the reviewer gets a notice instead. Anyone can
    submit the form, so without this a bot could make us send the same site's server the same requests every hour.
  * At most MAX_RUNS_PER_HOUR reports run in one pass. The rest are left unseen and run on the next pass, so a
    burst of submissions is spread out and cannot outrun the watchdog's time limit.
  * Any failure, in reading the form or in one run, emails the reviewer the error. Never silence.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import agents, consent, intake, mailer, watchdog
from .config import ConfigError, DomainConfig, normalize_domain
from .pdf import write_pdf
from .report import write_record, write_report
from .runner import run_checks

LOG = Path("logs") / "intake.log"
REPEAT_DAYS = 14
MAX_RUNS_PER_HOUR = 3


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
    started = 0
    for item in submissions:
        if item.id in done:
            continue
        if started >= MAX_RUNS_PER_HOUR:  # left unseen: the next pass picks it up
            outcome.skipped.append(f"submission {item.id}: deferred to the next pass")
            log(f"deferred submission {item.id}: {MAX_RUNS_PER_HOUR} already handled this pass")
            continue
        started += 1
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
    last = last_run(output, domain)
    if last and (date.today() - last) < timedelta(days=REPEAT_DAYS):
        outcome.skipped.append(f"{domain}: reported on {last.isoformat()}, within {REPEAT_DAYS} days")
        log(f"skipped {domain} (submission {item.id}): already reported on {last.isoformat()}")
        _tell(send, mailer.notice_message(cfg, f"REPEAT REQUEST · {domain}",
                                          f"A new request for {domain} came in, and we reported on it on "
                                          f"{last.isoformat()}, within {REPEAT_DAYS} days, so no second report ran. "
                                          f"If you want a new one, start it by hand.\n\n{requested}\n"))
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
    ai = agents.run(report, output_dir=output)  # never raises; AI_DRAFTS=on in .env turns it on
    if ai.status != "off":
        log(f"{domain}: AI draft {ai.status}. {ai.reason} {ai.usage_line()}")
    send(mailer.review_message(cfg, report, pdf, exit_code, requested, item.name, item.business_name, ai))
    outcome.emailed += 1
    log(f"emailed the review of {domain} to {mailer.REVIEWER}, exit code {exit_code}")


def last_run(output: Path, domain: str) -> date | None:
    """The date of the newest report folder for this domain (reports/<domain>/<date>, with or without a suffix
    such as -first), or None."""
    found = []
    for folder in (output / domain).glob("*") if (output / domain).is_dir() else []:
        try:
            found.append(date.fromisoformat(folder.name[:10]))
        except ValueError:
            continue
    return max(found, default=None)


def _tell(send, message) -> None:
    """Send a message to the reviewer; if even that fails, it is in the log and raised as an alert outside email,
    because the email that would have reported the failure is the thing that failed."""
    try:
        send(message)
    except Exception as exc:
        log(f"could not email {mailer.REVIEWER}: {type(exc).__name__}: {exc}")
        watchdog.alert("the email to the reviewer could not be sent")


def intake_failed(cfg: mailer.MailerConfig, error: str, smtp_factory=None) -> None:
    """Reading the form failed: the reviewer gets the error."""
    log(f"FAILED reading the /digital form: {error}")
    message = mailer.failure_message(cfg, "Reading the /digital form", error)
    _tell((lambda msg: mailer.send(msg, cfg, smtp_factory=smtp_factory)) if smtp_factory
          else (lambda msg: mailer.send(msg, cfg)), message)
