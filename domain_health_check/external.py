"""Data from outside services, fetched once per report beside the PageContext.

Checks still never make requests: runner calls fetch_external once and the
checks read the ExternalContext it returns. Every source is optional. With no
API key configured, its checks do not run at all, and a missing key never
costs a client points.

PageSpeed Insights is the only source so far. Lab scores move between runs (a
measured spread was 14 points for the score and 7% for largest contentful
paint), so mobile runs three times and the checks use the median; desktop runs
once. All four calls go out at the same time. Calls take 20 to 90 seconds and
return most of a megabyte, so the read is capped, and each raw response is
cached for 24 hours, then deleted: a later report is always a fresh call, and
we keep no data we have no use for.

The API key travels as a query parameter. It is never cached, logged or put in
an error message.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from .fetcher import USER_AGENT

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_CATEGORIES = ("performance", "accessibility", "best-practices")  # not seo: the site checks cover it
MOBILE_RUNS = 3
PSI_TIMEOUT_SECONDS = 120  # a measured call took 23.6 s; Google documents up to about 90
PSI_MAX_BYTES = 10_000_000  # a measured mobile response was 738 KB
CACHE_DIR = Path(".cache") / "pagespeed"
CACHE_SECONDS = 24 * 60 * 60


@dataclass
class ExternalContext:
    psi_mobile: list[dict] = field(default_factory=list)  # raw responses, one per run that succeeded
    psi_desktop: dict | None = None  # one run; None means did not run
    place: dict | None = None  # Places API details, once PLACES_API_KEY is configured
    errors: dict[str, str] = field(default_factory=dict)  # source -> why it is missing

    @property
    def pagespeed_configured(self) -> bool:
        """False when there is no key, in which case the speed checks show nothing at all."""
        return bool(self.psi_mobile) or any(source.startswith("psi_mobile") for source in self.errors)


class SourceError(Exception):
    pass


def fetch_external(
    domain: str, url: str | None, skipped: str = "", *, transport: httpx.BaseTransport | None = None,
) -> ExternalContext:
    """url is the page to test, normally PageContext.final_url. When it is None, nothing is called and
    skipped says why: we do not ask Google to load a page we could not, or were asked not to, load
    ourselves. transport is for tests."""
    context = ExternalContext()
    key = os.environ.get("PAGESPEED_API_KEY", "").strip()
    if not key:
        return context
    if url is None:
        context.errors.update({"psi_mobile": skipped, "psi_desktop": skipped})
        return context

    _prune_cache()
    jobs = [("mobile", run) for run in range(1, MOBILE_RUNS + 1)] + [("desktop", 1)]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=PSI_TIMEOUT_SECONDS, transport=transport) as client:
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            futures = {job: pool.submit(_pagespeed, client, domain, url, *job, key) for job in jobs}
        for (strategy, run), future in futures.items():
            try:
                data = future.result()
            except SourceError as exc:
                source = f"psi_mobile_{run}" if strategy == "mobile" else "psi_desktop"
                context.errors[source] = str(exc).replace(key, "<key>")
                continue
            if strategy == "mobile":
                context.psi_mobile.append(data)
            else:
                context.psi_desktop = data
    return context


def _cache_path(domain: str, strategy: str, run: int) -> Path:
    return CACHE_DIR / f"{domain}-{strategy}-{run}.json"


def _prune_cache() -> None:
    if CACHE_DIR.is_dir():
        for path in CACHE_DIR.iterdir():
            if time.time() - path.stat().st_mtime >= CACHE_SECONDS:
                path.unlink(missing_ok=True)


def _pagespeed(client: httpx.Client, domain: str, url: str, strategy: str, run: int, key: str) -> dict:
    cached = _cache_path(domain, strategy, run)
    if cached.exists() and time.time() - cached.stat().st_mtime < CACHE_SECONDS:
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except ValueError:
            pass  # a damaged cache file is ignored and replaced

    label = f"{strategy} run {run}" if strategy == "mobile" else strategy
    params = [("url", url), ("strategy", strategy), ("key", key)] + [("category", c) for c in PSI_CATEGORIES]
    chunks: list[bytes] = []
    size = 0
    try:
        with client.stream("GET", PSI_ENDPOINT, params=params) as response:
            for chunk in response.iter_bytes():
                chunks.append(chunk)
                size += len(chunk)
                if size > PSI_MAX_BYTES:
                    raise SourceError(f"{label}: response larger than {PSI_MAX_BYTES:,} bytes")
    except httpx.TimeoutException:
        raise SourceError(f"{label}: no answer within {PSI_TIMEOUT_SECONDS} seconds") from None
    except httpx.HTTPError as exc:
        raise SourceError(f"{label}: {type(exc).__name__}") from None  # the message can carry the URL and key

    try:
        data = json.loads(b"".join(chunks))
    except ValueError:
        raise SourceError(f"{label}: HTTP {response.status_code}, response was not JSON") from None
    if response.status_code != 200:
        message = data.get("error", {}).get("message", "") if isinstance(data, dict) else ""
        raise SourceError(f"{label}: HTTP {response.status_code} {message}".strip())

    cached.parent.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps(data), encoding="utf-8")
    return data
