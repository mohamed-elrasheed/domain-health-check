"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import ConfigError, DomainConfig, load_config, normalize_domain
from .models import Status
from .report import write_report
from .runner import run_checks
from .terminal import format_summary, use_color


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domain-health-check",
        description="Run passive, public health checks on domains and write client-friendly reports.",
    )
    parser.add_argument(
        "domains", nargs="*",
        help="check these domains instead of the ones in the config file (common DKIM selectors are tried)",
    )
    parser.add_argument("-c", "--config", type=Path, default=Path("domains.yaml"),
                        help="YAML file listing the domains to check (default: domains.yaml)")
    parser.add_argument("-o", "--output", type=Path, default=Path("reports"),
                        help="folder for the Markdown reports (default: reports)")
    parser.add_argument("--no-color", action="store_true", help="plain terminal output without colours")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Registrar names and the like can contain characters the Windows console can't print.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")

    try:
        if args.domains:
            domains = [DomainConfig(normalize_domain(d)) for d in args.domains]
        else:
            domains = load_config(args.config)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    color = use_color(sys.stdout, disabled=args.no_color)
    any_fail = False
    for domain in domains:
        print(f"Checking {domain.name}...", flush=True)
        report = run_checks(domain)
        path = write_report(report, args.output)
        print(format_summary(report, color, path))
        any_fail = any_fail or report.overall is Status.FAIL

    # A non-zero exit code lets scripts and schedulers notice problems.
    return 1 if any_fail else 0
