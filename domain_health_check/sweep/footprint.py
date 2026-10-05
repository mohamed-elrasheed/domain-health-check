"""How often we touch a business's site, and what we remember instead of asking again.

The promise is one page view, the same any visitor makes. A visitor does not come back four times in a
week, and when we did, one site started answering 429. So, on top of the per-request pacing in load.py:

  * Cache. Every visit is kept for COOLDOWN_DAYS, keyed by URL and date. A re-run inside that window
    re-evaluates the stored page with today's detectors and requests nothing. Browser checks of what is on
    screen are stored with it; a claim no live browser ever checked is set aside, never assumed.
  * Cooldown. No domain is fetched again within COOLDOWN_DAYS of the last fetch. Same weekday next week is
    allowed, so the weekly rotation lands on time.
  * 429. Being rate limited is a signal, not just a failure: the domain is backed off for BACKOFF_DAYS, or
    longer if its Retry-After asks, and the date it is safe to try again is recorded.

--force is the only way past any of this. State lives in sweep-output/_state.json and cached pages in
sweep-output/_cache/, both gitignored with the rest of sweep-output/. Cached pages are their content, so
anything older than the cooldown window is deleted at the start of each run.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import hosts
from .models import Visit, visit_from_dict

COOLDOWN_DAYS = 7
BACKOFF_DAYS = 30
RATE_LIMITED = re.compile(r"\bHTTP 429\b")


def domain(url: str) -> str:
    return hosts.host(url).removeprefix("www.")


def _retry_after_days(value: str, today: date) -> int:
    """Retry-After in whole days: either seconds or an HTTP date. 0 when absent or unreadable."""
    value = (value or "").strip()
    if value.isdigit():
        return math.ceil(int(value) / 86400)
    try:  # the one HTTP-date format servers send: "Wed, 21 Oct 2026 07:28:00 GMT"
        when = datetime.strptime(value, "%a, %d %b %Y %H:%M:%S GMT").replace(tzinfo=timezone.utc)
    except ValueError:
        return 0
    return max(0, (when.date() - today).days)


class Deferred(Exception):
    def __init__(self, url: str, until: date, reason: str):
        super().__init__(f"{domain(url)} is cooling down until {until.isoformat()} ({reason})")
        self.url, self.until, self.reason = url, until, reason


class Footprint:
    def __init__(self, folder: Path, today: date, force: bool = False):
        self.folder, self.today, self.force = folder, today, force
        self.state_path = folder / "_state.json"
        self.cache = folder / "_cache"
        self.state: dict[str, dict] = {}
        if self.state_path.exists():
            self.state = json.loads(self.state_path.read_text(encoding="utf-8"))
        else:
            self._bootstrap()
        self._prune()

    # ---------- cooldown

    def check(self, url: str) -> None:
        """Raise Deferred if this domain must not be fetched today."""
        if self.force:
            return
        entry = self.state.get(domain(url))
        if entry and date.fromisoformat(entry["retry_after"]) > self.today:
            raise Deferred(url, date.fromisoformat(entry["retry_after"]), entry["reason"])

    def record(self, visit: Visit, on: date | None = None) -> None:
        """Note a fetch of visit.url. A 429 anywhere in it backs the domain off."""
        on = on or self.today
        if visit.failure and RATE_LIMITED.search(visit.detail):
            days = max(BACKOFF_DAYS, _retry_after_days(visit.retry_after, on))
            reason = f"rate limited us with HTTP 429; backed off {days} days"
        else:
            days, reason = COOLDOWN_DAYS, "fetched"
        self.state[domain(visit.url)] = {"last_fetch": on.isoformat(),
                                         "retry_after": (on + timedelta(days)).isoformat(), "reason": reason}
        self.save()

    def save(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state, indent=2, sort_keys=True), encoding="utf-8")

    def _bootstrap(self) -> None:
        """First run with no state: count the visits already on record in sweep-output, dated by when each
        result was written, so a domain we just visited is not visited again because the file is new."""
        for result in sorted(self.folder.glob("*/result.json")):
            written = datetime.fromtimestamp(result.stat().st_mtime).date()
            try:
                visits = json.loads(result.read_text(encoding="utf-8")).get("visits", [])
            except ValueError:
                continue
            for raw in visits:
                visit = Visit(raw["url"], failure=raw.get("failure", ""), detail=raw.get("detail", ""),
                              retry_after=raw.get("retry_after", ""))
                known = self.state.get(domain(visit.url))
                if known is None or known["last_fetch"] <= written.isoformat():
                    self.record(visit, on=written)
        if self.state:
            self.save()

    # ---------- cache

    def _entry(self, url: str, day: date) -> Path:
        return self.cache / day.isoformat() / f"{hashlib.sha256(url.encode()).hexdigest()[:20]}.json"

    def cached(self, url: str) -> tuple[Visit, dict[str, bool]] | None:
        """The latest stored visit to url inside the cooldown window, with its on-screen checks."""
        if self.force:
            return None
        for back in range(COOLDOWN_DAYS):
            path = self._entry(url, self.today - timedelta(back))
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                visit = visit_from_dict(data["visit"])
                visit.cached_on = data["date"]
                return visit, data.get("checks", {})
        return None

    def store(self, visit: Visit, checks: dict[str, bool]) -> None:
        path = self._entry(visit.url, self.today)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = asdict(visit)
        data.pop("faults")  # always recomputed with the current detectors
        path.write_text(json.dumps({"url": visit.url, "date": self.today.isoformat(), "visit": data,
                                    "checks": checks}), encoding="utf-8")

    def _prune(self) -> None:
        oldest = (self.today - timedelta(COOLDOWN_DAYS - 1)).isoformat()
        if self.cache.is_dir():
            for day in self.cache.iterdir():
                if day.is_dir() and day.name < oldest:
                    shutil.rmtree(day)
