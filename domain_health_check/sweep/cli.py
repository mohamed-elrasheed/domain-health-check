"""domain-health-check-sweep: classify local businesses for our own lead list.

This is its own entry point on purpose. It shares no command with the report, so there is no flag that
turns one into the other. It reads a lead list (never writes to it), visits each business's own site once,
prints one line per business, and writes the verdicts and screenshots under sweep-output/ for us alone.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .. import __version__
from . import hosts, load
from .browser import Browser, BrowserUnavailable
from .models import Business, Fault, SweepResult
from .run import Sweeper

# The trades we sweep, in rotation order, with the short codes the lead list uses.
TRADES = {"auto": "auto", "barber": "barber", "cleaning": "clean", "clean": "clean", "landscaping": "land",
          "land": "land", "food": "food"}
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
# Our own site, loaded once before a run: if it cannot be reached, the problem is our network, and every
# business would otherwise come back as unver (or worse, as a domain that does not exist).
OWN_SITE = "https://www.mizangroupllc.com/robots.txt"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="domain-health-check-sweep",
        description="Classify local businesses (none, weak, unver, good) for Mizan's own lead list. Loads each "
                    "business's home page once, as any visitor would. Never writes a report or contacts anyone.")
    parser.add_argument("leads", type=Path, nargs="?", default=Path("leads.json"),
                        help="lead list (JSON), read only (default: leads.json, gitignored)")
    parser.add_argument("--trade", help="only this trade: auto, barber, cleaning, landscaping or food")
    parser.add_argument("--only", nargs="+", metavar="ID", help="only these lead ids")
    parser.add_argument("-o", "--output", type=Path, default=Path("sweep-output"),
                        help="folder for verdicts and screenshots (default: sweep-output, gitignored)")
    parser.add_argument("--no-browser", action="store_true",
                        help="read the HTML as delivered, without a browser and without screenshots")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def read_leads(path: Path) -> list[Business]:
    """The lead list as Business records. Accepts the board's short keys (n, cat, links as [label, url])."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    businesses = []
    for lead in raw:
        lead_id = str(lead["id"])
        if not SAFE_ID.fullmatch(lead_id):
            raise ValueError(f"lead id {lead_id!r} is not URL safe; it becomes a folder name")
        urls = [link[1] if isinstance(link, (list, tuple)) else link for link in lead.get("links", [])]
        hand = lead.get("hand_fault")
        hand_fault = Fault(hand["code"], hand["sentence"], hand.get("quote", ""), found_by="hand") if hand else None
        businesses.append(Business(lead_id, lead.get("n") or lead.get("name", ""),
                                   lead.get("cat") or lead.get("trade", ""), [u for u in urls if u], hand_fault))
    return businesses


def select(businesses: list[Business], trade: str | None, only: list[str] | None) -> list[Business]:
    if trade:
        code = TRADES.get(trade.lower())
        if code is None:
            raise ValueError(f"unknown trade {trade!r}; use one of auto, barber, cleaning, landscaping, food")
        businesses = [b for b in businesses if TRADES.get(b.trade.lower(), b.trade) == code]
    if only:
        missing = set(only) - {b.id for b in businesses}
        if missing:
            raise ValueError(f"no lead with id {', '.join(sorted(missing))}")
        businesses = [b for b in businesses if b.id in only]
    return businesses


def to_json(result: SweepResult) -> dict:
    return asdict(result)


def clear(folder: Path) -> None:
    """Remove a lead's previous screenshots and verdict, so a stale picture never sits beside a new verdict."""
    if folder.is_dir():
        for old in folder.iterdir():
            if old.is_file() and old.suffix in (".png", ".json"):
                old.unlink()


def write(result: SweepResult, out: Path) -> None:
    folder = out / result.id
    folder.mkdir(parents=True, exist_ok=True)
    data = to_json(result)
    for visit in data["visits"]:  # the page itself stays out of the record; the verdict quotes what matters
        if visit["page"]:
            visit["page"].pop("html")
            visit["page"].pop("visible_text")
    (folder / "result.json").write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_summary(results: list[SweepResult], out: Path, today: date) -> Path:
    """sweep-YYYY-MM-DD.json, replacing any older summary: a stale verdict is misleading."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"sweep-{today.isoformat()}.json"
    for old in out.glob("sweep-*.json"):
        if old != path:
            old.unlink()
    rows = [{"id": r.id, "name": r.name, "trade": r.trade, "verdict": r.verdict, "sentence": r.sentence,
             "fault": r.fault.code if r.fault else "", "found_by": r.fault.found_by if r.fault else "",
             "also_found": r.also_found,
             "failures": [{"url": v.url, "kind": v.failure, "detail": v.detail} for v in r.visits if v.failure],
             "screenshots": [f"{r.id}/{s}" for v in r.visits for s in v.screenshots]} for r in results]
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return path


def main(argv: list[str] | None = None, *, transport=None, today: date | None = None) -> int:
    args = build_parser().parse_args(argv)
    today = today or date.today()
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    try:
        businesses = select(read_leads(args.leads), args.trade, args.only)
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    with load.client(transport) as http:
        if any(hosts.kind(u) != "third-party" for b in businesses for u in b.urls) and not _network_ok(http):
            print(f"Error: could not reach {OWN_SITE}. Check the network before sweeping; otherwise every "
                  "business would come back unverified.", file=sys.stderr)
            return 2
        try:
            browser = nullcontext(None) if args.no_browser else Browser()
            with browser as session:
                sweeper = Sweeper(http, today.year, args.output, session)
                results = []
                for business in businesses:
                    clear(args.output / business.id)
                    result = sweeper.sweep(business)
                    write(result, args.output)
                    results.append(result)
                    by_hand = "[found by hand, check before using] " if result.fault and                         result.fault.found_by == "hand" else ""
                    print(f"{result.id:32} {result.verdict:6} {by_hand}{result.sentence}", flush=True)
        except BrowserUnavailable as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
    summary = write_summary(results, args.output, today)
    counts = {v: sum(r.verdict == v for r in results) for v in ("none", "weak", "unver", "good")}
    print(f"\n{len(results)} businesses: " + ", ".join(f"{n} {v}" for v, n in counts.items()) + f". {summary}")
    return 0


def _network_ok(http) -> bool:
    try:
        return http.get(OWN_SITE).status_code < 500
    except Exception:
        return False
