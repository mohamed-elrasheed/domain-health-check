"""Watching the scheduled run from outside it, so a failure can never be silent.

Two problems seen on November 4, 2026 made this necessary. The review email failed, and the email meant to report
that failure failed the same way, so the only trace was a log line nobody reads. Then one run hung part way through
a report and never finished or said why.

    alert()    always appends to logs/ALERT.txt, a file outside email. When NTFY_TOPIC is set in .env, it also
               sends a phone notification through ntfy (https://ntfy.sh, open source, no account needed). The
               notification says only what kind of thing failed, never a domain or anything a person submitted,
               because ntfy is a third party. The details stay in logs/intake.log on this computer.
    Limit      start() arms a timer for the whole run. If the run is still going when it fires, every thread's
               stack is written to logs/intake-hang.log, so the cause of the hang can be found, an alert goes out,
               and the process exits with code 4. A hung run can otherwise sit for hours and block the next one.

Nothing here raises: an alert that cannot be delivered is written where it can be, and the run goes on.
"""

from __future__ import annotations

import faulthandler
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx

ALERT_FILE = Path("logs") / "ALERT.txt"
HANG_FILE = Path("logs") / "intake-hang.log"
TOPIC_ENV = "NTFY_TOPIC"
LIMIT_ENV = "INTAKE_TIME_LIMIT_MINUTES"
# Up to three reports a pass (pipeline.MAX_RUNS_PER_HOUR), each a few minutes plus an AI step capped near
# 8 minutes (agents.AI_BUDGET_SECONDS and the per-call timeout). 45 covers that worst case and still ends before the
# next hourly run starts. 20 was shorter than the worst case, so a slow run could be killed with a submission
# half done (found by both audits).
DEFAULT_LIMIT_MINUTES = 45
NTFY = "https://ntfy.sh"
HANG_EXIT = 4
TRANSPORT: httpx.BaseTransport | None = None  # replaced in tests, so they never open a socket


def alert(kind: str, *, path: Path | None = None) -> None:
    """Record that something failed, outside email. kind is generic ("the review email could not be sent"), never
    a domain or a submitted value."""
    path = path or ALERT_FILE
    stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(f"{stamp}\t{kind}. Details: logs\\intake.log\n")
    except OSError:
        pass
    topic = os.environ.get(TOPIC_ENV, "").strip()
    if not topic:
        return
    try:
        with httpx.Client(timeout=10, transport=TRANSPORT) as client:
            client.post(f"{NTFY}/{topic}", content=f"domain-health-check: {kind}.".encode("utf-8"),
                        headers={"Title": "domain-health-check needs a look"})
    except httpx.HTTPError:
        pass  # the file above already holds it


def limit_minutes() -> float:
    try:
        value = float(os.environ.get(LIMIT_ENV, "") or DEFAULT_LIMIT_MINUTES)
    except ValueError:
        return DEFAULT_LIMIT_MINUTES
    return value if value > 0 else DEFAULT_LIMIT_MINUTES


def start(on_hang, *, minutes: float | None = None, hang_file: Path | None = None, exit_=os._exit) -> threading.Timer:
    """Arm the time limit. on_hang(minutes) runs first (log it, alert), then the stacks are saved and the process
    exits. Returns the timer, so a run that finishes cancels it."""
    minutes = minutes if minutes is not None else limit_minutes()
    hang_file = hang_file or HANG_FILE

    def fire() -> None:
        try:
            on_hang(minutes)
        finally:
            try:
                hang_file.parent.mkdir(parents=True, exist_ok=True)
                with hang_file.open("a", encoding="utf-8") as out:
                    out.write(f"--- {datetime.now(timezone.utc).isoformat(timespec='seconds')}: the run passed "
                              f"its {minutes:g} minute limit. Where every thread was:\n")
                    out.flush()
                    faulthandler.dump_traceback(file=out, all_threads=True)
            except OSError:
                pass
            exit_(HANG_EXIT)

    timer = threading.Timer(minutes * 60, fire)
    timer.daemon = True
    timer.start()
    return timer
