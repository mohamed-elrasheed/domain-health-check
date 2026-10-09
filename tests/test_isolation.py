"""The guard in state_guard.py: no test reads or writes the real submissions.yaml, logs/, reports/ or .env.

Every test runs from its own temporary directory, and an audit hook fails any test that opens, writes, lists,
renames or deletes one of those real paths. These tests prove the guard works without touching anything real:
they feed it paths, never open them.
"""

from __future__ import annotations

import os
from pathlib import Path

import state_guard

REPO = Path(__file__).resolve().parent.parent


def test_every_test_runs_outside_the_repository():
    cwd = Path(os.getcwd()).resolve()
    assert REPO != cwd and REPO not in cwd.parents


def test_the_guard_recognizes_each_real_state_path():
    for path in ("submissions.yaml", ".env", "logs/report-runs.log", "logs/intake-seen.json",
                 "reports/example.com/2026-10-09/report.pdf"):
        assert state_guard.touches_real_state(REPO / path), path
    for path in ("tests/fixtures/mizangroupllc.com/home.html", "config/pricelist.yaml", "submissions.yaml.bak"):
        assert state_guard.touches_real_state(REPO / path) is None, path


def test_a_touch_of_real_state_is_recorded_and_would_fail_the_test():
    recorded = []
    state_guard._audit("open", (str(REPO / "submissions.yaml"), "r", 0), recorded)
    state_guard._audit("os.remove", (str(REPO / "logs" / "intake.log"),), recorded)
    state_guard._audit("open", (str(REPO / "config" / "nearby.yaml"), "r", 0), recorded)  # not state: ignored
    assert recorded == [f"open {REPO / 'submissions.yaml'}", f"os.remove {REPO / 'logs' / 'intake.log'}"]
