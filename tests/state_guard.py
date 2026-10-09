"""The guard behind tests/conftest.py's isolated_state: no test reads or writes real state.

An audit hook records any open, write, listing, rename or removal of the repository's submissions.yaml, .env,
logs/ or reports/ while a test runs; the fixture fails that test. Kept out of conftest.py so tests can import it:
there are two conftest modules, and "import conftest" can find the other one.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REAL_STATE = [REPO / "submissions.yaml", REPO / ".env", REPO / "logs", REPO / "reports"]
TOUCHED: list[str] = []
_WATCHING = False
_STATE_EVENTS = {"open", "os.remove", "os.rename", "os.replace", "os.rmdir", "os.mkdir", "os.listdir", "os.scandir",
                 "shutil.rmtree", "shutil.copyfile", "shutil.move"}


def touches_real_state(path) -> str | None:
    """The real state file or folder this path is, or is inside; None for anything else."""
    try:
        resolved = Path(os.fsdecode(path)).resolve()
    except (TypeError, ValueError, OSError):
        return None
    for real in REAL_STATE:
        if resolved == real or real in resolved.parents:
            return str(real)
    return None


def _audit(event: str, args, sink: list | None = None) -> None:
    """The audit hook. sink is for the guard's own tests; the hook itself records into TOUCHED while a test runs."""
    if (sink is not None or _WATCHING) and event in _STATE_EVENTS and args and             isinstance(args[0], (str, bytes, os.PathLike)):
        real = touches_real_state(args[0])
        if real:
            (TOUCHED if sink is None else sink).append(f"{event} {os.fsdecode(args[0])}")






def watching(on: bool) -> None:
    global _WATCHING
    _WATCHING = on


sys.addaudithook(_audit)
