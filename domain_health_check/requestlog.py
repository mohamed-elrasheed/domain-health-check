"""Every request a report makes, for the record.

A report promises a small, stated footprint, so it keeps a list of everything it actually asked anyone for:
each HTTP request (the page fetch, the registry, PageSpeed, Places), each DNS query, the TLS handshake, and every
request the browser made while rendering the page. The list goes into report.json and requests.log beside the
report. API keys are masked before anything is recorded: nothing from .env is ever written down.

Recording is switched on by runner.run_checks for one report at a time. Outside it, record() does nothing, so
code that makes requests can always call it.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

_lock = threading.Lock()
_active: list[Request] | None = None
SECRET_PARAMS = re.compile(r"(?i)([?&](?:key|api_key|apikey|token)=)[^&#]*")


@dataclass
class Request:
    at: str  # UTC, to the second
    source: str  # page, browser, rdap, pagespeed, places, dns, tls
    method: str  # GET, HEAD, POST, QUERY (DNS), CONNECT (TLS)
    target: str  # the URL, "name TYPE" for DNS, or "host:443" for TLS
    outcome: str = ""  # the status code, or what went wrong

    def as_dict(self) -> dict:
        return asdict(self)

    def line(self) -> str:
        return "\t".join((self.at, self.source, self.method, self.target, self.outcome))


def mask(url: str) -> str:
    return SECRET_PARAMS.sub(r"\1<key>", url)


def record(source: str, method: str, target: str, outcome: object = "") -> Request | None:
    with _lock:
        if _active is None:
            return None
        entry = Request(datetime.now(timezone.utc).isoformat(timespec="seconds"), source, method, mask(target),
                        str(outcome))
        _active.append(entry)
        return entry


def settle(entry: Request | None, outcome: object) -> None:
    """Fill in the outcome of a request recorded before it finished."""
    if entry is not None:
        with _lock:
            entry.outcome = str(outcome)


@contextmanager
def recording() -> Iterator[list[Request]]:
    """Collect every request made inside the block. One report at a time."""
    global _active
    with _lock:
        _active = []
        collected = _active
    try:
        yield collected
    finally:
        with _lock:
            _active = None


def httpx_hooks(source: str) -> dict:
    """event_hooks for an httpx client: every request is recorded as it is sent, its status as it arrives.
    A request that fails outright keeps an empty outcome, which the caller may settle."""
    def on_request(request) -> None:
        request.extensions["requestlog"] = record(source, request.method, str(request.url))

    def on_response(response) -> None:
        settle(response.request.extensions.get("requestlog"), response.status_code)

    return {"request": [on_request], "response": [on_response]}
