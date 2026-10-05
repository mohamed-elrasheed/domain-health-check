"""Command-line entry point."""

from __future__ import annotations

import argparse
import smtplib
import sys
from pathlib import Path

from . import __version__, consent, external, mailer
from .config import ConfigError, DomainConfig, load_config, load_env, normalize_domain
from .models import Status
from .pdf import write_pdf
from .report import write_report
from .runner import run_checks
from .terminal import format_summary, use_color


ENV_FILE = Path(".env")  # API keys, never committed; see .env.example
SMTP_FACTORY = smtplib.SMTP  # replaced in tests, so they never open a socket
AUTHORIZATION_LOG = Path("logs") / "report-authorizations.log"  # local only, gitignored
LEADS_FILE = Path("leads.json")  # sweep's lead list, gitignored; a report never runs on anything in it


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domain-health-check",
        description="Run health checks on domains submitted through mizangroupllc.com/digital and write client-friendly reports.",
    )
    parser.add_argument(
        "domains", nargs="*",
        help="check these domains instead of the ones in the config file (common DKIM selectors are tried)",
    )
    parser.add_argument("-c", "--config", type=Path, default=Path("domains.yaml"),
                        help="YAML file listing the domains to check (default: domains.yaml)")
    parser.add_argument("-o", "--output", type=Path, default=Path("reports"),
                        help="folder for the reports (default: reports)")
    parser.add_argument("--no-pdf", action="store_true",
                        help="skip the PDF; by default every report is written as Markdown and as a PDF")
    parser.add_argument("--email", action="store_true",
                        help="email each report, PDF attached, to REPORT_RECIPIENT (default SMTP_USERNAME) for "
                             "review. Never to the site owner.")
    parser.add_argument("--business-name", default="",
                        help="the business-name from the /digital form, to find its Google Business Profile")
    parser.add_argument("--city", default="", help="the city from the /digital form")
    parser.add_argument("--phone", default="", help="the phone number from the /digital form")
    parser.add_argument("--authorized", action="store_true",
                        help="confirm each domain was submitted through the /digital form. No submissions are "
                             "recorded yet, so every report needs this, and every use is logged to "
                             f"{AUTHORIZATION_LOG}")
    parser.add_argument("--no-color", action="store_true", help="plain terminal output without colours")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser




def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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

    # The lead list is consent-free by definition: refuse anything on it, before anything else, flag or not.
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
                  "definition, so no report runs for it, with or without --authorized.", file=sys.stderr)
            return 2

    # A report runs only for a domain someone submitted through /digital. Refuse before anything is fetched.
    unrecorded = [d.name for d in domains if not consent.recorded_submission(d.name)]
    if unrecorded and not args.authorized:
        print(f"Error: no /digital submission is recorded for {', '.join(unrecorded)}. Reports run only for "
              "domains submitted through the form. If you have seen the submission, run again with "
              f"--authorized; every use is logged to {AUTHORIZATION_LOG}.", file=sys.stderr)
        return 2
    if unrecorded:
        consent.log_authorized(unrecorded, AUTHORIZATION_LOG)

    mail = None
    if args.email:  # check before running anything, not after a three-minute run
        try:
            mail = mailer.MailerConfig.from_env()
        except (mailer.MailerNotConfigured, ValueError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2

    color = use_color(sys.stdout, disabled=args.no_color)
    any_fail = output_failed = False
    for domain in domains:
        print(f"Checking {domain.name}...", flush=True)
        report = run_checks(domain)
        path = write_report(report, args.output)
        print(format_summary(report, color, path))
        any_fail = any_fail or report.overall is Status.FAIL
        if not args.no_pdf or mail:
            pdf_path = _write_pdf(report, args.output)
            output_failed = output_failed or pdf_path is None
            if mail and pdf_path:
                output_failed = not _email(report, pdf_path, mail) or output_failed

    # A non-zero exit code lets scripts and schedulers notice problems.
    if output_failed:
        return 2
    return 1 if any_fail else 0


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
