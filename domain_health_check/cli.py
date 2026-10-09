"""Command-line entry point.

    domain-health-check report example.com            run the checks and write the report
    domain-health-check record-submission example.com --source form --email owner@example.com

A report runs only for a domain with a recorded submission, and never for one on the lead list.
"""

from __future__ import annotations

import argparse
import json
import smtplib
import sys
from datetime import date, datetime
from pathlib import Path

from . import __version__, consent, external, intake, mailer, pipeline
from .config import ConfigError, DomainConfig, load_config, load_env, normalize_domain
from .pdf import write_pdf
from .report import write_record, write_report
from .runner import run_checks
from .terminal import format_summary, use_color

ENV_FILE = Path(".env")  # API keys, never committed; see .env.example
SMTP_FACTORY = smtplib.SMTP  # replaced in tests, so they never open a socket
RUN_LOG = Path("logs") / "report-runs.log"  # every report run and the record it ran on; local, gitignored
LEADS_FILE = Path("leads.json")  # sweep's lead list, gitignored; a report never runs on anything in it
SUBMISSIONS = Path("submissions.yaml")  # who asked for a report; gitignored


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domain-health-check",
        description="Health reports for domains whose owners asked for one, through mizangroupllc.com/digital or "
                    "otherwise. Every report needs a recorded submission.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND")

    report = commands.add_parser("report", help="run the checks and write the report")
    report.add_argument(
        "domains", nargs="*",
        help="check these domains instead of the ones in the config file (common DKIM selectors are tried)",
    )
    report.add_argument("-c", "--config", type=Path, default=Path("domains.yaml"),
                        help="YAML file listing the domains to check (default: domains.yaml)")
    report.add_argument("-o", "--output", type=Path, default=Path("reports"),
                        help="folder for the reports (default: reports)")
    report.add_argument("--no-pdf", action="store_true",
                        help="skip the PDF; by default every report is written as Markdown and as a PDF")
    report.add_argument("--email", action="store_true",
                        help="email each report, PDF attached, to REPORT_RECIPIENT (default SMTP_USERNAME) for "
                             "review. Never to the site owner.")
    report.add_argument("--business-name", default="",
                        help="the business-name from the /digital form, to find its Google Business Profile")
    report.add_argument("--city", default="", help="the city from the /digital form")
    report.add_argument("--phone", default="", help="the phone number from the /digital form")
    report.add_argument("--no-color", action="store_true", help="plain terminal output without colours")

    record = commands.add_parser("record-submission", help="record that someone asked for a report on a domain")
    record.add_argument("domain")
    record.add_argument("--source", required=True, choices=consent.SOURCES,
                        help="how the request reached us; own is for our own domains")
    record.add_argument("--email", default="", help="the address it came from (required for form and email)")
    record.add_argument("--received", default=date.today().isoformat(),
                        help="the date it reached us, YYYY-MM-DD (default: today)")
    pull = commands.add_parser("intake", help="read new /digital form submissions, run each report, and email the "
                                              "reviewer; never the business")
    pull.add_argument("--submissions-file", type=Path,
                      help="a saved Webflow API response to read instead of Webflow, for testing")
    pull.add_argument("-o", "--output", type=Path, default=Path("reports"), help="folder for the reports")
    pull.add_argument("--check", action="store_true",
                      help="read the form and list how many submissions there are and which field names came back; "
                           "records nothing, runs no report and sends no email")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "record-submission":
        return record(args)
    if args.command == "report":
        return report(args)
    if args.command == "intake":
        return run_intake(args)
    parser.print_help(sys.stderr)
    return 2


def record(args) -> int:
    try:
        submission = consent.validate(normalize_domain(args.domain), args.email, args.received, args.source)
        replaced = consent.record_submission(SUBMISSIONS, submission)
    except (ConfigError, consent.SubmissionError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(f"{'Updated' if replaced else 'Recorded'} the submission for {submission.domain} "
          f"({submission.source}, received {submission.received.isoformat()}) in {SUBMISSIONS}.")
    try:
        if consent.on_lead_list(submission.domain, consent.lead_domains(LEADS_FILE)):
            print(f"Note: {submission.domain} is on the lead list, so the report still refuses it until it is "
                  "taken off the lead list.")
    except consent.LeadListUnreadable:
        pass
    return 0


def report(args) -> int:
    load_env(ENV_FILE)
    # Registrar names and the like can contain characters the Windows console cannot print.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    # CLAUDE.md: cached PageSpeed responses are deleted after 24 hours. Enforced here, on every run.
    for path in external.prune_cache():
        print(f"Deleted a cached PageSpeed response older than 24 hours: {path.name}")

    try:
        if args.domains:
            domains = [DomainConfig(normalize_domain(d), business_name=args.business_name.strip(),
                                    city=args.city.strip(), phone=args.phone.strip()) for d in args.domains]
        else:
            domains = load_config(args.config)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    # The lead list is consent-free by definition: refuse anything on it, before anything else.
    try:
        listed = consent.lead_domains(LEADS_FILE)
    except consent.LeadListUnreadable as exc:
        print(f"Error: cannot check the lead list, so no report runs ({exc}). The report refuses any domain on "
              f"{LEADS_FILE}; it must be readable at the repository root.", file=sys.stderr)
        return 2
    for d in domains:
        match = consent.on_lead_list(d.name, listed)
        if match:
            print(f"Error: {d.name} is on the lead list (as {match}). The lead list is consent-free by "
                  "definition, so no report runs for it.", file=sys.stderr)
            return 2

    # A report runs only for a domain someone asked about. Refuse before anything is fetched.
    try:
        records = consent.load_submissions(SUBMISSIONS)
    except consent.SubmissionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    missing = [d.name for d in domains if not consent.submitted(d.name, records)]
    if missing:
        print(f"Error: no submission is recorded for {', '.join(missing)}, so no report runs. If the owner asked "
              "for one, record it first:", file=sys.stderr)
        for name in missing:
            print(f"  {consent.add_command(name)}", file=sys.stderr)
        return 2

    mail = None
    if args.email:  # check before running anything, not after a three-minute run
        try:
            mail = mailer.MailerConfig.from_env()
        except (mailer.MailerNotConfigured, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    color = use_color(sys.stdout, disabled=args.no_color)
    output_failed = incomplete = False
    for domain in domains:
        consent.log_run(domain.name, consent.submitted(domain.name, records), RUN_LOG)
        print(f"Checking {domain.name}...", flush=True)
        result = run_checks(domain)
        path = write_report(result, args.output)
        print(format_summary(result, color, path))
        record_path = write_record(result, args.output)
        print(f"  Record: {record_path} ({len(result.requests)} requests in {record_path.with_name('requests.log')})")
        if not args.no_pdf or mail:
            pdf_path = _write_pdf(result, args.output)
            output_failed = output_failed or pdf_path is None
            if mail and pdf_path:
                output_failed = not _email(result, pdf_path, mail) or output_failed
        if not result.complete:
            incomplete = True
            print("  This report is not complete:", file=sys.stderr)
            for reason in result.incomplete:
                print(f"    - {reason}", file=sys.stderr)

    # The exit code says whether the run worked, not what it found: 0 only for a complete report, written in full.
    # 2: a file could not be written. 3: written, but some part of the report did not run (see above).
    if output_failed:
        return 2
    return 3 if incomplete else 0


def _write_pdf(report, output_dir: Path) -> Path | None:
    try:
        path = write_pdf(report, output_dir)
    except OSError as exc:  # WeasyPrint could not load Pango
        print(f"  Could not write the PDF: {exc}", file=sys.stderr)
        print('  See "PDF output" in the README.', file=sys.stderr)
        return None
    print(f"  PDF: {path}")
    return path


def _email(report, pdf_path: Path, mail: mailer.MailerConfig) -> bool:
    try:
        mailer.send(mailer.message_for(mail, report, pdf_path), mail, smtp_factory=SMTP_FACTORY)
    except mailer.SendFailed as exc:
        print(f"  {exc}", file=sys.stderr)
        return False
    print(f"  Emailed to {mail.recipient}")
    return True


def summary_time() -> str:
    """Now, as an ISO timestamp with the local offset, for the one summary line a scheduled run writes."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def run_intake(args) -> int:
    """The scheduled hourly run. Writes exactly one line to stdout, even when there is nothing to do, so a quiet run
    in logs/intake-task.log reads as a working run; everything else goes to stderr. Exit 0 when every new submission
    was reported on and its review sent, 3 when a report was incomplete, 2 when anything failed (the reviewer was
    emailed the error). --check is a manual look at the form, not a run: it prints what it found."""
    load_env(ENV_FILE)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    if args.check:
        return _check_intake(args)
    counts = {"new": 0, "emailed": 0, "failures": 0}
    try:
        return _run_intake(args, counts)
    finally:
        print(f"{summary_time()} intake: {counts['new']} new submissions, {counts['emailed']} reports emailed, "
              f"{counts['failures']} failures", flush=True)


def _run_intake(args, counts: dict[str, int]) -> int:
    try:
        mail = mailer.MailerConfig.from_env()
    except (mailer.MailerNotConfigured, ValueError) as exc:  # nobody can be told, so say it here and stop
        counts["failures"] += 1
        print(f"Error: {exc} Intake needs it to send the reviewer each report.", file=sys.stderr)
        pipeline.log(f"FAILED: email is not configured, so intake did not run: {exc}")
        return 2
    for path in external.prune_cache():
        print(f"Deleted a cached PageSpeed response older than 24 hours: {path.name}", file=sys.stderr)
    try:
        found = intake.from_file(args.submissions_file) if args.submissions_file else intake.fetch()
    except (intake.IntakeError, OSError, ValueError) as exc:
        counts["failures"] += 1
        print(f"Error: {exc}", file=sys.stderr)
        pipeline.intake_failed(mail, str(exc), smtp_factory=SMTP_FACTORY)
        return 2
    outcome = pipeline.process(found, mail, output=args.output, submissions_path=SUBMISSIONS, leads_path=LEADS_FILE,
                               run_log=RUN_LOG, smtp_factory=SMTP_FACTORY)
    counts["new"] = len(outcome.processed) + len(outcome.skipped) + len(outcome.failed)
    counts["emailed"] = outcome.emailed
    counts["failures"] += len(outcome.failed)
    for domain in outcome.processed:
        print(f"Reported on {domain} (exit code {outcome.exit_codes[domain]}); the review went to {mailer.REVIEWER}.",
              file=sys.stderr)
    for line in outcome.skipped:
        print(f"Skipped {line}.", file=sys.stderr)
    for line in outcome.failed:
        print(f"Failed: {line}", file=sys.stderr)
    if outcome.failed:
        return 2
    return 3 if any(code == 3 for code in outcome.exit_codes.values()) else 0


def _check_intake(args) -> int:
    """Read the /digital form and describe what came back. No consent is recorded, nothing is marked seen, no
    report runs and no email is sent. Only counts and field names are printed, never a submitted value."""
    try:
        items = (json.loads(args.submissions_file.read_text(encoding="utf-8")).get("formSubmissions") or []
                 if args.submissions_file else intake.fetch_items())
    except (intake.IntakeError, OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    check = intake.check_fields(items)
    print(f"Submissions to the /digital form: {check.submissions} "
          f"({check.already_processed} already processed, {check.submissions - check.already_processed} new)")
    print("Field names that came back (how many submissions carry each):")
    for name in sorted(check.seen):
        print(f"  {name}: {check.seen[name]}")
    print("What intake reads:")
    for ours, accepted in check.expected.items():
        found = check.found_as(ours)
        print(f"  {ours} <- {' or '.join(accepted)}: " + (f"present, as {found}" if found else "NOT in any submission"))
    if check.unmapped:
        print(f"Came back but not read by intake: {', '.join(check.unmapped)}")
    if not check.submissions:
        print("There are no submissions yet, so the field names cannot be confirmed.")
        return 0
    if check.missing:
        print(f"Expected but never seen: {', '.join(check.missing)}")
        return 3
    print("Every field intake reads came back under the expected name.")
    return 0
