"""domain-health-check-sweep: classify local businesses for our own lead list.

This is its own entry point on purpose. It shares no command with the report, so there is no flag that
turns one into the other. It reads a lead list (never writes to it), visits each business's own site once,
prints one line per business, and writes the verdicts and screenshots under sweep-output/ for us alone.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from contextlib import nullcontext
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path

from .. import __version__
from ..preview import shots
from . import board, hosts, load
from .browser import Browser, BrowserUnavailable
from .footprint import Deferred, Footprint
from .models import Business, Fault, SweepResult
from .run import Sweeper, redecide

# The trades we sweep, in rotation order, with the short codes the lead list uses.
TRADES = {"auto": "auto", "barber": "barber", "cleaning": "clean", "clean": "clean", "landscaping": "land",
          "land": "land", "food": "food"}
SAFE_ID = re.compile(r"[a-z0-9][a-z0-9-]*")
# Our own site, loaded once before a run: if it cannot be reached, the problem is our network, and every
# business would otherwise come back as unver (or worse, as a domain that does not exist).
OWN_SITE = "https://www.mizangroupllc.com/robots.txt"
PREVIEWS = Path("..") / "mizan-previews"  # the private previews repository; tests point this elsewhere
REPO_ROOT = Path(".")  # where sweep runs: the lead list and its fix patches live here


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
    parser.add_argument("--force", action="store_true",
                        help="fetch even if the domain was fetched in the last 7 days, is backed off after a 429, or "
                             "has a stored visit. Every forced fetch is another visit to their site.")
    parser.add_argument("--no-browser", action="store_true",
                        help="read the HTML as delivered, without a browser and without screenshots")
    parser.add_argument("--previews", type=Path, default=PREVIEWS,
                        help="the private previews repository, where screenshots are published for the lead board "
                             "(default: ../mizan-previews)")
    parser.add_argument("--board-only", action="store_true",
                        help="regenerate sweep-output/board.json from what is stored, without sweeping")
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
        if hand and not hand.get("found"):
            raise ValueError(f"{lead_id}: a hand fault must carry the date it was observed, as \"found\"")
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
             "flags": [{"code": f.code, "sentence": f.sentence} for f in r.flags],
             "display_name": r.display_name, "display_name_source": r.display_name_source,
             "deferred_until": r.deferred_until,
             "from_visit_on": next((v.cached_on for v in r.visits if v.cached_on), ""),
             "unchecked": [t for v in r.visits for t in v.unchecked],
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
        raw_leads = json.loads(args.leads.read_text(encoding="utf-8"))
    except (OSError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.board_only:
        return 0 if _board(args, raw_leads) else 2

    with load.client(transport) as http:
        if any(hosts.kind(u) != "third-party" for b in businesses for u in b.urls) and not _network_ok(http):
            print(f"Error: could not reach {OWN_SITE}. Check the network before sweeping; otherwise every "
                  "business would come back unverified.", file=sys.stderr)
            return 2
        footprint = Footprint(args.output, today, force=args.force)
        try:
            browser = nullcontext(None) if args.no_browser else Browser()
            with browser as session:
                sweeper = Sweeper(http, today.year, args.output, session, footprint=footprint)
                results = []
                for business in businesses:
                    try:
                        result = sweeper.sweep(business)
                    except Deferred as deferred:
                        result = _stored(args.output, business, deferred)
                        if result is None:
                            print(f"{business.id:32} deferred, nothing stored: {deferred}", flush=True)
                            continue
                    write(result, args.output)
                    results.append(result)
                    by_hand = "[found by hand, check before using] " if result.fault and                         result.fault.found_by == "hand" else ""
                    when = (f" [deferred: {result.deferred_until}]" if result.deferred_until else
                            next((f" [from the visit on {v.cached_on}]" for v in result.visits if v.cached_on), ""))
                    print(f"{result.id:32} {result.verdict:6} {by_hand}{result.sentence}{when}", flush=True)
        except BrowserUnavailable as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
    summary = write_summary(results, args.output, today)
    counts = {v: sum(r.verdict == v for r in results) for v in ("none", "weak", "unver", "good")}
    print(f"\n{len(results)} businesses: " + ", ".join(f"{n} {v}" for v, n in counts.items()) + f". {summary}")
    return 0 if _board(args, raw_leads) else 2


def board_blockers(leads: Path, root: Path) -> list[str]:
    """Why board.json must not be regenerated, or [] when it may. The board is built only from leads.json at
    the repository root with every leads-*.patch there fully applied: building from a patched copy, or from a
    file a patch has not reached, is how the board quietly goes stale."""
    problems = []
    expected = (root / "leads.json").resolve()
    if not expected.is_file():
        return [f"there is no leads.json at the repository root ({expected})"]
    if leads.resolve() != expected:
        problems.append(f"the lead list must be leads.json at the repository root ({expected}); "
                        f"this run read {leads.resolve()}")
    for patch in sorted(root.glob("leads-*.patch")):
        def applies(*flags: str) -> bool:
            try:
                return subprocess.run(["git", "apply", "--check", *flags, patch.name], cwd=root,
                                      capture_output=True).returncode == 0
            except OSError:
                return False
        if applies("--reverse"):
            continue  # fully applied
        if applies():
            problems.append(f"{patch.name} is not applied to leads.json yet: run git apply {patch.name}")
        else:
            problems.append(f"{patch.name} neither is applied to leads.json nor applies cleanly: the file and the "
                            "patch disagree, so look at both before regenerating")
    return problems


def _board(args, raw_leads: list[dict]) -> bool:
    problems = board_blockers(args.leads, REPO_ROOT)
    if problems:
        print("Board not regenerated:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return False
    print(f"Board: {export_board(raw_leads, args.output, args.previews)}")
    return True


def export_board(raw_leads: list[dict], out: Path, previews: Path, now: datetime | None = None) -> Path:
    """Regenerate board.json for every lead in the list, publishing screenshots into the previews repository
    first so the board's links point at files that exist. Without the previews repository the links are null."""
    ids = [lead["id"] for lead in raw_leads]
    if (previews / ".git").is_dir():
        published = shots.publish(out, previews, ids)
        pages = {lead_id: shots.preview_url(previews, lead_id) for lead_id in ids}
    else:
        print(f"  No previews repository at {previews}; screenshot and preview links are null.", file=sys.stderr)
        published, pages = {}, {}
    return board.write(board.build(raw_leads, out, published, pages, now or datetime.now(timezone.utc)), out)


def _stored(out: Path, business: Business, deferred: Deferred) -> SweepResult | None:
    """The last stored result for a lead whose domain is cooling down, decided again under today's rules."""
    path = out / business.id / "result.json"
    if not path.exists():
        return None
    result = redecide(json.loads(path.read_text(encoding="utf-8")), business)
    result.deferred_until = deferred.until.isoformat()
    return result


def _network_ok(http) -> bool:
    try:
        return http.get(OWN_SITE).status_code < 500
    except Exception:
        return False
