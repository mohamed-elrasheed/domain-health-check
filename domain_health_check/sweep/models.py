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


@dataclass
class Robots:
    url: str  # after redirects
    status: int
    text: str


@dataclass
class Page:
    """The home page as one visit saw it."""
    requested_url: str
    final_url: str  # after redirects
    status: int
    redirect_chain: list[tuple[str, int]]
    html: str  # the DOM after scripts ran when rendered is True, otherwise the HTML as delivered
    rendered: bool = False


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


@dataclass
class Business:
    id: str  # URL safe; also the folder name under sweep-output/
    name: str
    trade: str
    urls: list[str]


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
