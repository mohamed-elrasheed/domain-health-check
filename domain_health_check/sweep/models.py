"""What sweep records about one business."""

from __future__ import annotations

from dataclasses import dataclass, field

VERDICTS = ("none", "weak", "unver", "good")


@dataclass
class Fault:
    code: str  # one of faults.RANK
    sentence: str  # one sentence Mo can read aloud on a call, quoting what we found
    quote: str = ""  # the exact string found on the page, when there is one
    selector: str = ""  # CSS for the element that shows it, used to photograph the evidence
    on_screen: bool = False  # the sentence says visitors see quote; a browser confirms it before it stands
    found_by: str = "sweep"  # "hand" for a fault a person found and recorded on the lead


@dataclass
class Robots:
    url: str  # after redirects
    status: int
    text: str
    retry_after: str = ""  # the Retry-After header, when the site sent one


@dataclass
class Page:
    """The home page as one visit saw it."""
    requested_url: str
    final_url: str  # after redirects
    status: int
    redirect_chain: list[tuple[str, int]]
    html: str  # the DOM after scripts ran when rendered is True, otherwise the HTML as delivered
    rendered: bool = False
    visible_text: str = ""  # what the browser displayed, at phone and at desktop width; rendered pages only


@dataclass
class Visit:
    """What happened when we went to one listed address."""
    url: str
    robots: Robots | None = None
    page: Page | None = None
    failure: str = ""  # empty when the page loaded; see load.FAILURES
    detail: str = ""  # the failure in plain words, for the record
    attempts: int = 0
    faults: list[Fault] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)
    retry_after: str = ""  # the Retry-After header that came with a 429, if any
    cached_on: str = ""  # the date of the stored visit this came from, when nothing was fetched
    unchecked: list[str] = field(default_factory=list)  # on-screen claims no live browser has checked yet


@dataclass
class Business:
    id: str  # URL safe; also the folder name under sweep-output/
    name: str
    trade: str
    urls: list[str]
    hand_fault: Fault | None = None  # found by a person, recorded on the lead; used when sweep finds nothing


@dataclass
class SweepResult:
    id: str
    name: str
    trade: str
    verdict: str  # one of VERDICTS
    sentence: str  # the line to read aloud; for good, empty
    fault: Fault | None = None
    also_found: list[str] = field(default_factory=list)  # codes of lesser faults, for our own reference
    owned: list[str] = field(default_factory=list)  # listed addresses that could be their own site
    elsewhere: list[str] = field(default_factory=list)  # listings on platforms they do not own
    visits: list[Visit] = field(default_factory=list)
    flags: list[Fault] = field(default_factory=list)  # real, but not a website job; never change the verdict
    display_name: str = ""  # what the business calls itself on its own site, when we could read it
    display_name_source: str = ""  # where on their page that came from
    deferred_until: str = ""  # set when this is a stored result re-decided because the domain is cooling down


def fault_from_dict(data: dict) -> Fault:
    return Fault(**{k: v for k, v in data.items() if k in Fault.__dataclass_fields__})


def visit_from_dict(data: dict) -> Visit:
    """A Visit back from JSON (a cache entry or a result.json)."""
    fields = {k: v for k, v in data.items() if k in Visit.__dataclass_fields__}
    if fields.get("robots"):
        fields["robots"] = Robots(**{k: v for k, v in fields["robots"].items() if k in Robots.__dataclass_fields__})
    if fields.get("page"):
        page = {k: v for k, v in fields["page"].items() if k in Page.__dataclass_fields__}
        page.setdefault("html", "")
        page["redirect_chain"] = [tuple(hop) for hop in page.get("redirect_chain", [])]
        fields["page"] = Page(**page)
    fields["faults"] = [fault_from_dict(f) for f in fields.get("faults", [])]
    return Visit(**fields)
