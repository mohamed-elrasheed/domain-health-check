"""Sweeping one business: classify its listed addresses, visit the ones that could be its own, decide."""

from __future__ import annotations

from pathlib import Path

import httpx

from . import hosts
from typing import NamedTuple

from .faults import FLAGS, collapse, evaluate_visit, rank
from .footprint import Footprint
from .load import ATTEMPTS, RETRYABLE, LoadFailure, Pacer, attempt, fetch_page, visit_robots
from .models import Business, Fault, SweepResult, Visit, fault_from_dict, visit_from_dict
from .names import display_name


class Sweeper:
    """One sweep run. Each address is visited at most once per run, however many leads list it."""

    def __init__(self, http: httpx.Client, year: int, out: Path | None = None, browser=None,
                 pacer: Pacer | None = None, footprint: Footprint | None = None):
        self.http, self.year, self.out, self.browser = http, year, out, browser
        self.pacer = pacer or Pacer()
        self.footprint = footprint  # cache and cooldown; None in tests that fetch on purpose
        self._visited: dict[str, Visit] = {}
        self._checks: dict[str, dict[str, bool]] = {}  # on-screen checks made live, stored with the cache

    def sweep(self, business: Business) -> SweepResult:
        owned = [u for u in business.urls if hosts.kind(u) != "third-party"]
        elsewhere = [u for u in business.urls if hosts.kind(u) == "third-party"]
        visits = [self._visit(u, business) for u in dict.fromkeys(_normalize(u) for u in owned)]
        d = decide(owned, elsewhere, visits, business.hand_fault)
        result = SweepResult(business.id, business.name, business.trade, d.verdict, d.sentence, d.fault,
                             d.also_found, owned, elsewhere, visits, d.flags)
        for visit in visits:
            page = visit.page
            if page and hosts.kind(page.final_url) != "third-party":
                shown = collapse(page.visible_text) if page.rendered and page.visible_text else None
                found = display_name(page.html, business.name, shown)
                if found:
                    result.display_name, result.display_name_source = found
                    break
        return result

    def _visit(self, url: str, business: Business) -> Visit:
        if url not in self._visited:
            self._visited[url] = self._load(url, business)
        return self._visited[url]

    def _load(self, url: str, business: Business) -> Visit:
        """Remembered if we can, fetched only if we may. Raises footprint.Deferred when the domain is
        cooling down and nothing is stored."""
        if self.footprint is not None:
            hit = self.footprint.cached(url)
            if hit is not None:
                return self._from_cache(*hit, business)
            self.footprint.check(url)
        if self.out is not None:  # a fresh visit replaces the pictures of the last one
            for old in (self.out / business.id).glob("*.png"):
                old.unlink()
        visit = self._fetch(url, business)
        if self.footprint is not None:
            self.footprint.record(visit)
            self.footprint.store(visit, self._checks.get(url, {}))
        return visit

    def _from_cache(self, visit: Visit, checks: dict[str, bool], business: Business) -> Visit:
        """A stored visit, re-read with today's detectors. A claim about what is on screen stands only if a
        live browser checked it; anything new is set aside and listed as unchecked."""
        unchecked: list[str] = []

        def on_screen(text: str) -> bool:
            if text in checks:
                return checks[text]
            unchecked.append(text)
            return False

        if visit.page is not None and visit.page.rendered:
            visit.faults = confirm_on_screen(visit, self.year, on_screen, business.name)
        else:
            visit.faults = evaluate_visit(visit, self.year, business=business.name)
        visit.unchecked = unchecked
        return visit

    def _fetch(self, url: str, business: Business) -> Visit:
        visit = visit_robots(url, self.http, self.pacer)
        if visit.failure:
            visit.faults = evaluate_visit(visit, self.year, business=business.name)
            return visit
        try:
            if self.browser is None:
                visit.page = attempt(lambda: fetch_page(self.http, url), url, self.pacer, visit)
                visit.faults = evaluate_visit(visit, self.year, business=business.name)
            else:
                self._load_in_browser(url, business, visit)
        except LoadFailure as failure:
            visit.failure, visit.detail, visit.retry_after = failure.kind, failure.detail, failure.retry_after
            visit.faults = evaluate_visit(visit, self.year, business=business.name)
        return visit

    def _load_in_browser(self, url: str, business: Business, visit: Visit) -> None:
        for n in range(1, ATTEMPTS + 1):
            self.pacer.wait(url)
            visit.attempts += 1
            try:
                with self.browser.open(url) as opened:
                    visit.page = opened.page
                    checks = self._checks.setdefault(url, {})

                    def on_screen(text: str) -> bool:
                        checks[text] = opened.on_screen(text)
                        return checks[text]

                    visit.faults = confirm_on_screen(visit, self.year, on_screen, business.name)
                    if self.out is not None:
                        visit.screenshots = opened.capture(self.out / business.id,
                                                           visit.faults[0] if visit.faults else None)
                return
            except LoadFailure as failure:
                if failure.kind not in RETRYABLE or n == ATTEMPTS:
                    if n > 1:
                        failure.detail = f"{failure.detail} (on all {n} attempts)"
                    raise
                self.pacer.pause(5.0)


def confirm_on_screen(visit: Visit, year: int, on_screen, business: str = "") -> list:
    """Evaluate the visit, then check every fault that says visitors see something against what the browser
    actually shows. Text that is in the page but covered, clipped or hidden is set aside and the visit is
    evaluated again without it, until every remaining claim has been confirmed. A string in the HTML
    proves delivery, not effect."""
    hidden: set[str] = set()
    confirmed: set[str] = set()
    while True:
        found = evaluate_visit(visit, year, frozenset(hidden), business)
        pending = [f for f in found if f.on_screen and f.quote not in confirmed]
        if not pending:
            return found
        claim = pending[0]
        (confirmed if on_screen(claim.quote) else hidden).add(claim.quote)


def redecide(data: dict, business: Business) -> SweepResult:
    """A stored result.json decided again under today's rules, without fetching anything. The detectors
    are not rerun: the faults are the ones that visit found. Used when a domain is cooling down."""
    visits = [visit_from_dict(v) for v in data.get("visits", [])]
    d = decide(data.get("owned", []), data.get("elsewhere", []), visits, business.hand_fault)
    return SweepResult(business.id, business.name, business.trade, d.verdict, d.sentence, d.fault, d.also_found,
                       data.get("owned", []), data.get("elsewhere", []), visits, d.flags,
                       data.get("display_name", ""), data.get("display_name_source", ""))


def _normalize(url: str) -> str:
    return url if "//" in url else f"https://{url}"


class Decision(NamedTuple):
    verdict: str
    sentence: str
    fault: Fault | None
    also_found: list[str]  # codes of the lesser website faults
    flags: list[Fault]  # everything that is real but not a website job


def decide(owned: list[str], elsewhere: list[str], visits: list[Visit], hand_fault: Fault | None = None
           ) -> Decision:
    """The verdict and the line to read, plus flags. Pure, so it is tested without a network.

    The verdict answers one question: is there a website job here. Faults in faults.FLAGS (free webmail, a
    mismatched email domain, a misspelled day, an old copyright year) never change it; they come back as
    flags, most damaging first, whatever the verdict.

    A fault a person found and recorded on the lead competes with the detected ones by rank, and it keeps
    the lead weak rather than letting it drop to good or unver: the detectors not seeing it is not evidence
    it is gone. It is marked as found by hand, because hand notes go stale and Mo should look before
    reading one aloud. It does not apply when every listed address turned out to be someone else's."""
    if not owned:
        return Decision("none", _no_site(elsewhere), None, [], [])
    found = [f for v in visits for f in v.faults]
    forwarded = [v for v in visits if v.page and hosts.kind(v.page.final_url) == "third-party"]
    if hand_fault is not None and len(forwarded) < len(visits):
        found.append(hand_fault)
    found.sort(key=rank)
    flags = list({f.code: f for f in reversed(found) if f.code in FLAGS}.values())[::-1]
    faults = [f for f in found if f.code not in FLAGS]
    if faults:
        return Decision("weak", faults[0].sentence, faults[0], list(dict.fromkeys(f.code for f in faults[1:])),
                        flags)
    loaded = [v for v in visits if v.page]
    theirs = [v for v in loaded if hosts.kind(v.page.final_url) != "third-party"]
    if theirs:
        return Decision("good", "", None, [], flags)
    if loaded and len(loaded) == len(visits):
        away = hosts.host(loaded[0].page.final_url)
        return Decision("none", f"Their listed address, {hosts.host(loaded[0].url)}, forwards to {away}, which "
                                "they do not own.", None, [], [])
    reasons = "; ".join(f"{hosts.host(v.url)}: {v.detail}" for v in visits if v.failure)
    return Decision("unver", f"We could not see their site. {reasons}.", None, [], flags)


def _no_site(elsewhere: list[str]) -> str:
    if not elsewhere:
        return "We found no website and no listing link of any kind."
    names = list(dict.fromkeys(hosts.host(u).removeprefix("www.") for u in elsewhere))
    return f"We found no site they own. What is listed lives on {_join(names)}."


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" and {items[-1]}"
