"""Sweeping one business: classify its listed addresses, visit the ones that could be its own, decide."""

from __future__ import annotations

from pathlib import Path

import httpx

from . import hosts
from .faults import evaluate_visit, rank
from .load import ATTEMPTS, RETRYABLE, LoadFailure, Pacer, attempt, fetch_page, visit_robots
from .models import Business, Fault, SweepResult, Visit


class Sweeper:
    """One sweep run. Each address is visited at most once per run, however many leads list it."""

    def __init__(self, http: httpx.Client, year: int, out: Path | None = None, browser=None,
                 pacer: Pacer | None = None):
        self.http, self.year, self.out, self.browser = http, year, out, browser
        self.pacer = pacer or Pacer()
        self._visited: dict[str, Visit] = {}

    def sweep(self, business: Business) -> SweepResult:
        owned = [u for u in business.urls if hosts.kind(u) != "third-party"]
        elsewhere = [u for u in business.urls if hosts.kind(u) == "third-party"]
        visits = [self._visit(u, business.id) for u in dict.fromkeys(_normalize(u) for u in owned)]
        verdict, sentence, fault, also = decide(owned, elsewhere, visits)
        return SweepResult(business.id, business.name, business.trade, verdict, sentence, fault, also,
                           owned, elsewhere, visits)

    def _visit(self, url: str, lead_id: str) -> Visit:
        if url not in self._visited:
            self._visited[url] = self._load(url, lead_id)
        return self._visited[url]

    def _load(self, url: str, lead_id: str) -> Visit:
        visit = visit_robots(url, self.http, self.pacer)
        if visit.failure:
            visit.faults = evaluate_visit(visit, self.year)
            return visit
        try:
            if self.browser is None:
                visit.page = attempt(lambda: fetch_page(self.http, url), url, self.pacer, visit)
                visit.faults = evaluate_visit(visit, self.year)
            else:
                self._load_in_browser(url, lead_id, visit)
        except LoadFailure as failure:
            visit.failure, visit.detail = failure.kind, failure.detail
            visit.faults = evaluate_visit(visit, self.year)
        return visit

    def _load_in_browser(self, url: str, lead_id: str, visit: Visit) -> None:
        for n in range(1, ATTEMPTS + 1):
            self.pacer.wait(url)
            visit.attempts += 1
            try:
                with self.browser.open(url) as opened:
                    visit.page = opened.page
                    visit.faults = confirm_on_screen(visit, self.year, opened.on_screen)
                    if self.out is not None:
                        visit.screenshots = opened.capture(self.out / lead_id,
                                                           visit.faults[0] if visit.faults else None)
                return
            except LoadFailure as failure:
                if failure.kind not in RETRYABLE or n == ATTEMPTS:
                    if n > 1:
                        failure.detail = f"{failure.detail} (on all {n} attempts)"
                    raise
                self.pacer.pause(5.0)


def confirm_on_screen(visit: Visit, year: int, on_screen) -> list:
    """Evaluate the visit, then check every fault that says visitors see something against what the browser
    actually shows. Text that is in the page but covered, clipped or hidden is set aside and the visit is
    evaluated again without it, until every remaining claim has been confirmed. A string in the HTML
    proves delivery, not effect."""
    hidden: set[str] = set()
    confirmed: set[str] = set()
    while True:
        found = evaluate_visit(visit, year, frozenset(hidden))
        pending = [f for f in found if f.on_screen and f.quote not in confirmed]
        if not pending:
            return found
        claim = pending[0]
        (confirmed if on_screen(claim.quote) else hidden).add(claim.quote)


def _normalize(url: str) -> str:
    return url if "//" in url else f"https://{url}"


def decide(owned: list[str], elsewhere: list[str], visits: list[Visit]
           ) -> tuple[str, str, Fault | None, list[str]]:
    """(verdict, sentence, fault, codes of the lesser faults). Pure, so it is tested without a network."""
    if not owned:
        return "none", _no_site(elsewhere), None, []
    faults = sorted((f for v in visits for f in v.faults), key=rank)
    if faults:
        return "weak", faults[0].sentence, faults[0], list(dict.fromkeys(f.code for f in faults[1:]))
    loaded = [v for v in visits if v.page]
    theirs = [v for v in loaded if hosts.kind(v.page.final_url) != "third-party"]
    if theirs:
        return "good", "", None, []
    if loaded and len(loaded) == len(visits):
        away = hosts.host(loaded[0].page.final_url)
        return "none", f"Their listed address, {hosts.host(loaded[0].url)}, forwards to {away}, which they do " \
                       "not own.", None, []
    reasons = "; ".join(f"{hosts.host(v.url)}: {v.detail}" for v in visits if v.failure)
    return "unver", f"We could not see their site. {reasons}.", None, []


def _no_site(elsewhere: list[str]) -> str:
    if not elsewhere:
        return "We found no website and no listing link of any kind."
    names = list(dict.fromkeys(hosts.host(u).removeprefix("www.") for u in elsewhere))
    return f"We found no site they own. What is listed lives on {_join(names)}."


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" and {items[-1]}"
