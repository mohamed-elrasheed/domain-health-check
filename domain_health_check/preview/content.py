"""What a proposal says, worked out from a lead record. Pure: no files, no network.

The lead record is the board's: n (name), cat (trade), town, addr, ph, rating, links, and optionally
display_name, numbers and hours (see HOURS below).

The name on the pages is what the business calls itself, never one we made up: display_name on the lead
(set from their own site, confirmed on the call), else the name sweep read from their header or footer,
else our lead name exactly as recorded. A name is never made by deleting words from ours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

TRADES = {
    "auto": ("Auto repair", "auto"),
    "barber": ("Barbershop", "barber"),
    "clean": ("Cleaning", "clean"),
    "land": ("Landscaping", "land"),
    "food": ("Restaurant", "food"),
}

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = {"mon": "Monday", "tue": "Tuesday", "wed": "Wednesday", "thu": "Thursday", "fri": "Friday",
             "sat": "Saturday", "sun": "Sunday"}
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

# The hours field, filled in during the sales call:
#
#   "hours": {
#     "mon": [["08:00", "18:00"]],                     one or more [open, close] pairs, 24-hour local time
#     "wed": [["08:00", "12:00"], ["13:00", "18:00"]], a split day is two pairs
#     "sat": [["08:00", "14:00"]],
#     "sun": [],                                       an empty list means closed that day
#     "checked": "2026-10-04",                          when the owner confirmed them
#     "note": "Walk-ins welcome"                        optional, shown under the hours
#   }
#
# A day that is missing is unknown, which is not the same as closed. A close time earlier than the open time
# runs past midnight. The same shape maps directly onto schema.org openingHoursSpecification when the site
# is built for real.


class LeadError(ValueError):
    pass


@dataclass
class Hours:
    rows: list[tuple[str, str]]  # (days, times), e.g. ("Monday to Friday", "8:00 am to 6:00 pm")
    note: str = ""
    complete: bool = False  # every day of the week is known


@dataclass
class Proposal:
    lead_id: str
    name: str  # our lead name, exactly as recorded
    display_name: str  # what they call themselves: used in the proposal line and on the proposed site
    trade: str  # "Auto repair"
    template: str  # which site template to use
    town: str
    state: str
    address: str
    phone: str
    numbers: list[tuple[str, str]]  # (big, small): ("69", "reviews on Yelp")
    hours: Hours | None  # None: not known yet
    maps_url: str = ""
    current_host: str = ""  # the address of the site they have today
    extra: dict = field(default_factory=dict)


def proposal(lead: dict, current_host: str = "", read_name: str = "") -> Proposal:
    """read_name is the name sweep read from their own page, if any."""
    try:
        lead_id, name, cat = lead["id"], lead["n"].strip(), lead["cat"]
    except KeyError as exc:
        raise LeadError(f"the lead has no {exc.args[0]!r}") from None
    if cat not in TRADES:
        raise LeadError(f"no template for trade {cat!r} yet")
    trade, template = TRADES[cat]
    address = (lead.get("addr") or "").strip()
    maps = next((url for label, url in lead.get("links", []) if label == "Maps"), "")
    return Proposal(
        lead_id=lead_id, name=name, display_name=(lead.get("display_name") or read_name or name).strip(),
        trade=trade, template=template, town=(lead.get("town") or "").strip(), state=_state(address),
        address=address, phone=(lead.get("ph") or "").strip(),
        numbers=[tuple(n) for n in lead["numbers"]] if lead.get("numbers") else rating_numbers(lead.get("rating", "")),
        hours=hours(lead.get("hours")), maps_url=maps, current_host=current_host,
    )


STATES = {"VA": "Virginia", "MD": "Maryland", "DC": "Washington, DC"}


def _state(address: str) -> str:
    match = re.search(r",\s*([A-Z]{2})\s+\d{5}", address)
    return STATES.get(match.group(1), match.group(1)) if match else ""


SOURCE = r"(?:\s*\(([^)]+)\))?"
RATING_PART = re.compile(r"(?:(\d(?:\.\d)?)\s*/\s*)?(\d+)(\s*reviews?)?" + SOURCE)


def rating_numbers(rating: str) -> list[tuple[str, str]]:
    """The board's rating string as the numbers set large on the page.

    "69 reviews (Yelp)"                      -> [("69", "reviews on Yelp")]
    "5.0 / 56 (Carfax)"                      -> [("5.0", "stars on Carfax"), ("56", "reviews on Carfax")]
    "30 reviews (Yelp) / 4.6 / 21 (Birdeye)" -> the Yelp count, then the Birdeye stars and count
    "rating not found"                       -> []
    """
    numbers: list[tuple[str, str]] = []
    for part in re.split(r"\)\s*/\s*", rating):
        part = part if part.endswith(")") or "(" not in part else part + ")"
        match = RATING_PART.search(part)
        if not match:
            continue
        stars, count, _, source = match.groups()
        on = f" on {source.strip()}" if source and source.strip().lower() != "aggregated" else ""
        if stars:
            numbers.append((stars, f"stars{on}"))
        numbers.append((count, f"{'review' if count == '1' else 'reviews'}{on}"))
    return numbers


def _clock(value: str) -> str:
    match = TIME.match(value)
    if not match:
        raise LeadError(f"hours: {value!r} is not a 24-hour time like 08:00")
    hour, minute = int(match.group(1)), match.group(2)
    if (hour, minute) == (12, "00"):
        return "noon"
    suffix = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}:{minute} {suffix}"


def _day_times(spans) -> str:
    if spans == []:
        return "Closed"
    if not isinstance(spans, list) or not all(isinstance(s, list) and len(s) == 2 for s in spans):
        raise LeadError(f"hours: {spans!r} should be a list of [open, close] pairs, or [] for closed")
    return ", ".join(f"{_clock(a)} to {_clock(b)}" for a, b in spans)


def hours(record: dict | None) -> Hours | None:
    """The hours block, days with the same times grouped: "Monday to Friday", "8:00 am to 6:00 pm".
    None when no day is known yet."""
    if not record:
        return None
    unknown = set(record) - set(DAYS) - {"checked", "note"}
    if unknown:
        raise LeadError(f"hours: unknown keys {sorted(unknown)}")
    known = [(day, _day_times(record[day])) for day in DAYS if day in record]
    if not known:
        return None
    rows: list[tuple[list[str], str]] = []
    for day, times in known:
        if rows and rows[-1][1] == times and DAYS.index(day) == DAYS.index(rows[-1][0][-1]) + 1:
            rows[-1][0].append(day)
        else:
            rows.append(([day], times))
    label = lambda days: DAY_NAMES[days[0]] if len(days) == 1 else (
        f"{DAY_NAMES[days[0]]} and {DAY_NAMES[days[1]]}" if len(days) == 2 else
        f"{DAY_NAMES[days[0]]} to {DAY_NAMES[days[-1]]}")
    return Hours([(label(days), times) for days, times in rows], (record.get("note") or "").strip(),
                 complete=len(known) == len(DAYS))
