"""board.json, the contract with the lead board. Invented leads only."""

from __future__ import annotations

import json
import subprocess
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from domain_health_check.preview import shots
from domain_health_check.sweep import board, cli

TODAY = date(2026, 10, 4)
NOW = datetime(2026, 10, 4, 18, 0, tzinfo=timezone.utc)
CONTRACT = ["id", "display_name", "display_name_confirmed", "verdict", "hand_verdict", "fault", "fault_source",
            "fault_observed", "flags", "demand", "demand_term", "screenshot_phone", "screenshot_desktop",
            "preview", "hours_confirmed", "last_fetch", "next_fetch", "blocked_until"]
LEAD = {"id": "example-garage", "n": "Example Garage Auto Care (Fuel)", "cat": "auto", "v": "weak",
        "flaw": "MO TYPED THIS NOTE", "notes": "MO TYPED THIS TOO", "call_status": "called twice",
        "links": [["Site", "https://examplegarage.wixsite.com/home"], ["Yelp", "https://www.yelp.com/biz/x"]]}
STATE = {"examplegarage.wixsite.com": {"last_fetch": "2026-10-04", "retry_after": "2026-10-11", "reason": "fetched"}}
WEAK = {"verdict": "weak", "sentence": "Their site lives on a free builder address.",
        "fault": {"code": "builder-host", "found_by": "sweep"}, "flags": [{"code": "free-mail", "sentence": "x"}],
        "display_name": "Example Fuel"}


def row(lead=LEAD, result=WEAK, state=STATE, shot=None, preview=None, previous=None):
    return board.entry(lead, result, state, shot or {}, preview, previous, TODAY)


def test_the_shape_is_the_contract():
    assert list(board.FIELDS) == CONTRACT
    assert list(row()) == CONTRACT


def test_a_detector_fault():
    r = row(shot={"phone": shots.url("example-garage", "phone"), "desktop": None},
            preview="https://preview.mizangroupllc.com/example-garage/")
    assert r["verdict"] == "weak" and r["hand_verdict"] == "weak"
    assert (r["fault"], r["fault_source"], r["fault_observed"]) == (WEAK["sentence"], "detector", "2026-10-04")
    assert r["flags"] == ["free-mail"]
    assert r["demand"] is None and r["demand_term"] is None
    assert r["screenshot_phone"] == "https://preview.mizangroupllc.com/_shots/example-garage/phone.png"
    assert r["screenshot_desktop"] is None
    assert (r["last_fetch"], r["next_fetch"], r["blocked_until"]) == ("2026-10-04", "2026-10-11", None)


def test_the_name_read_from_their_site_is_unconfirmed_until_the_lead_says_so():
    assert (row()["display_name"], row()["display_name_confirmed"]) == ("Example Fuel", False)
    lead = {**LEAD, "display_name": "Example Fuel Garage", "display_name_confirmed": True}
    assert (row(lead)["display_name"], row(lead)["display_name_confirmed"]) == ("Example Fuel Garage", True)
    no_name = {**WEAK, "display_name": ""}
    assert row(result=no_name)["display_name"] == LEAD["n"]  # ours, exactly, never trimmed


def test_a_hand_fault_carries_its_observed_date():
    lead = {**LEAD, "hand_fault": {"code": "stock-photos", "sentence": "Stock photos.", "found": "2026-09-01"}}
    result = {**WEAK, "sentence": "Stock photos.", "fault": {"code": "stock-photos", "found_by": "hand"}}
    r = row(lead, result)
    assert (r["fault"], r["fault_source"], r["fault_observed"]) == ("Stock photos.", "hand", "2026-09-01")


def test_a_hand_fault_without_a_date_is_refused(tmp_path):
    path = tmp_path / "leads.json"
    path.write_text(json.dumps([{**LEAD, "hand_fault": {"code": "stock-photos", "sentence": "Stock photos."}}]))
    with pytest.raises(ValueError, match="date it was observed"):
        cli.read_leads(path)


def test_good_and_none():
    good = row(result={"verdict": "good", "sentence": "", "fault": None, "flags": []})
    assert good["fault"] is None and good["fault_source"] is None and good["fault_observed"] is None
    lead = {**LEAD, "links": [["Facebook", "https://www.facebook.com/x"]]}
    none = row(lead, {"verdict": "none", "sentence": "We found no site they own.", "fault": None, "flags": []}, {})
    assert (none["fault"], none["fault_source"], none["fault_observed"]) == ("We found no site they own.", "detector",
                                                                           "2026-10-04")
    assert none["last_fetch"] is None and none["next_fetch"] is None and none["blocked_until"] is None


def test_a_lead_sweep_could_not_reach_keeps_its_last_known_values():
    previous = row()
    unreached = {"verdict": "unver", "sentence": "We could not see their site.", "fault": None, "flags": []}
    state = {"examplegarage.wixsite.com": {"last_fetch": "2026-10-11", "retry_after": "2026-10-18",
                                           "reason": "fetched"}}
    r = row(result=unreached, state=state, previous=previous)
    assert r["verdict"] == "weak" and r["fault"] == WEAK["sentence"] and r["last_fetch"] == "2026-10-04"
    assert r["blocked_until"] == "2026-10-18" and r["next_fetch"] == "2026-10-18"


def test_unreached_with_nothing_known_is_unver_and_blocked():
    unreached = {"verdict": "unver", "sentence": "We could not see their site.", "fault": None, "flags": []}
    state = {"examplegarage.wixsite.com": {"last_fetch": "2026-10-04", "retry_after": "2026-11-03",
                                           "reason": "rate limited us with HTTP 429; backed off 30 days"}}
    r = row(result=unreached, state=state)
    assert r["verdict"] == "unver" and r["blocked_until"] == "2026-11-03" and r["fault"] is None


def test_hours_are_confirmed_only_with_a_checked_date():
    assert row()["hours_confirmed"] is False
    assert row({**LEAD, "hours": {"mon": [["08:00", "17:00"]]}})["hours_confirmed"] is False
    assert row({**LEAD, "hours": {"mon": [["08:00", "17:00"]], "checked": "2026-10-04"}})["hours_confirmed"] is True


def test_nothing_mo_typed_flows_out(tmp_path):
    (tmp_path / "example-garage").mkdir()
    (tmp_path / "example-garage" / "result.json").write_text(json.dumps(WEAK))
    (tmp_path / "_state.json").write_text(json.dumps(STATE))
    path = board.write(board.build([LEAD], tmp_path, {}, {}, NOW), tmp_path)
    text = path.read_text(encoding="utf-8")
    assert "MO TYPED" not in text and "called twice" not in text
    data = json.loads(text)
    assert data["generated"] == "2026-10-04T18:00:00Z" and list(data) == ["generated", "leads"]


def test_build_uses_the_previous_board_for_unreached_leads(tmp_path):
    (tmp_path / "example-garage").mkdir()
    result = tmp_path / "example-garage" / "result.json"
    result.write_text(json.dumps(WEAK))
    (tmp_path / "_state.json").write_text(json.dumps(STATE))
    board.write(board.build([LEAD], tmp_path, {}, {}, NOW), tmp_path)
    result.write_text(json.dumps({"verdict": "unver", "sentence": "x", "fault": None, "flags": []}))
    [r] = board.build([LEAD], tmp_path, {}, {}, NOW)["leads"]
    assert r["verdict"] == "weak" and r["blocked_until"] == "2026-10-11"


# ---------- screenshots go to the private previews repository only

def test_publish_copies_keeps_and_forgets(tmp_path):
    out, previews = tmp_path / "sweep-output", tmp_path / "mizan-previews"
    (out / "a").mkdir(parents=True)
    (out / "a" / "phone.png").write_bytes(b"phone a")
    old = previews / "public" / "_shots" / "gone"
    old.mkdir(parents=True)
    (old / "phone.png").write_bytes(b"a lead no longer on the list")
    kept = previews / "public" / "_shots" / "b" / "phone.png"
    kept.parent.mkdir(parents=True)
    kept.write_bytes(b"b, from a visit that reached them")
    published = shots.publish(out, previews, ["a", "b"])
    assert published["a"] == {"phone": shots.url("a", "phone"), "desktop": None}
    assert published["b"]["phone"] == shots.url("b", "phone") and kept.read_bytes().startswith(b"b, from")
    assert not old.exists()
    assert "Disallow: /_shots/" in (previews / "public" / "robots.txt").read_text()


def test_no_screenshot_is_ever_committed_to_this_repository():
    tracked = subprocess.run(["git", "ls-files", "*.png", "*.jpg", "*.jpeg", "*.webp"], capture_output=True,
                             text=True, cwd=Path(__file__).parent.parent).stdout.split()
    assert all(path.startswith("domain_health_check/assets/") for path in tracked), tracked
