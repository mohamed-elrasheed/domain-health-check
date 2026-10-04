"""sweep-output/board.json: the contract between sweep and the lead board.

The shape is fixed. FIELDS is the whole of it, in order, and tests/test_sweep_board.py fails if an entry
carries anything else. A field is added only by agreement with the board, never in passing.

What flows this way is what sweep measured: verdicts, faults, flags, names read from their sites,
screenshots, fetch dates. What Mo typed (notes, call status, the hand-written flaw on each lead) lives in the
board and flows the other way; nothing here copies it. The two exceptions the contract names are the hand
verdict and a fault recorded on the lead as found by hand, which carries the date it was observed.

Field rules:

    fault            the line to read: the website fault for weak, the absence for none; null otherwise
    fault_source     "detector" or "hand"
    fault_observed   detector: the latest fetch of the lead's sites; hand: the date on the lead (required)
    flags            codes of what is real but not a website job (see faults.FLAGS)
    demand, demand_term   null until the Keyword Planner export exists
    screenshot_*     published copies in the private previews repository, or null
    preview          the proposal page, when one has been generated, or null
    hours_confirmed  the lead's hours carry a "checked" date from the call
    last_fetch       the latest fetch of the lead's sites; next_fetch the earliest date sweep may fetch again
    blocked_until    set when sweep could not reach the lead: the date it will try again. A lead it could not
                     reach keeps its last known values from the previous board rather than turning to unver.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from . import hosts
from .footprint import domain

FIELDS = (
    "id", "display_name", "display_name_confirmed", "verdict", "hand_verdict", "fault", "fault_source",
    "fault_observed", "flags", "demand", "demand_term", "screenshot_phone", "screenshot_desktop", "preview",
    "hours_confirmed", "last_fetch", "next_fetch", "blocked_until",
)
# Kept from the previous board when sweep could not reach a lead this time.
LAST_KNOWN = ("display_name", "verdict", "fault", "fault_source", "fault_observed", "flags", "screenshot_phone",
              "screenshot_desktop", "last_fetch")
UNREACHED = "unver"


def entry(lead: dict, result: dict | None, state: dict[str, dict], shots: dict[str, str | None],
          preview: str | None, previous: dict | None, today: date) -> dict:
    owned = [url for _, url in _links(lead) if hosts.kind(url) != "third-party"]
    fetched = [state[d] for d in {domain(u) for u in owned} if d in state]
    last_fetch = max((s["last_fetch"] for s in fetched), default=None)
    next_fetch = max((s["retry_after"] for s in fetched), default=None)
    backed_off = any("429" in s["reason"] for s in fetched)

    verdict = result["verdict"] if result else None
    fault = fault_source = fault_observed = None
    if result and verdict in ("weak", "none"):
        fault = result["sentence"]
        hand = lead.get("hand_fault")
        if result.get("fault") and result["fault"].get("found_by") == "hand" and hand:
            fault_source, fault_observed = "hand", hand["found"]
        else:
            fault_source, fault_observed = "detector", last_fetch or today.isoformat()

    hours = lead.get("hours") or {}
    row = {
        "id": lead["id"],
        "display_name": lead.get("display_name") or (result or {}).get("display_name") or lead["n"],
        "display_name_confirmed": bool(lead.get("display_name") and lead.get("display_name_confirmed")),
        "verdict": verdict,
        "hand_verdict": lead.get("v"),
        "fault": fault,
        "fault_source": fault_source,
        "fault_observed": fault_observed,
        "flags": [f["code"] for f in (result or {}).get("flags", [])],
        "demand": None,
        "demand_term": None,
        "screenshot_phone": shots.get("phone"),
        "screenshot_desktop": shots.get("desktop"),
        "preview": preview,
        "hours_confirmed": bool(hours.get("checked")),
        "last_fetch": last_fetch,
        "next_fetch": next_fetch,
        "blocked_until": next_fetch if verdict == UNREACHED or backed_off else None,
    }
    if verdict == UNREACHED and previous and previous.get("verdict") not in (None, UNREACHED):
        for field in LAST_KNOWN:
            row[field] = previous[field]
    return {field: row[field] for field in FIELDS}


def _links(lead: dict) -> list[tuple[str, str]]:
    return [tuple(link) if isinstance(link, (list, tuple)) else ("", link) for link in lead.get("links", [])]


def build(leads: list[dict], out: Path, published: dict[str, dict[str, str | None]],
          previews: dict[str, str | None], now: datetime) -> dict:
    """The whole board from what is on disk: each lead's latest result.json, the cooldown state, what is
    published in the previews repository, and the previous board for leads sweep could not reach."""
    state_path = out / "_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    previous_path = out / "board.json"
    previous = {}
    if previous_path.exists():
        previous = {row["id"]: row for row in json.loads(previous_path.read_text(encoding="utf-8")).get("leads", [])}
    rows = []
    for lead in leads:
        result_path = out / lead["id"] / "result.json"
        result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else None
        rows.append(entry(lead, result, state, published.get(lead["id"], {}), previews.get(lead["id"]),
                          previous.get(lead["id"]), now.date()))
    return {"generated": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "leads": rows}


def write(board: dict, out: Path) -> Path:
    path = out / "board.json"
    out.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(board, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
