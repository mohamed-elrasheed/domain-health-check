"""Data from outside services, fetched once per report beside the PageContext.

Checks still never make requests: runner calls fetch_external once and the
checks read the ExternalContext it returns. Every source is optional. With no
API key configured, its checks do not run at all, and a missing key never
costs a client points.

Google Places finds the business's Google Business Profile (two calls: a
text search, then details for a listing whose name matches). Field masks
are billed by their most expensive field, so both are kept tight, and the
star rating is never requested: it is never scored. A listing is only
accepted when matching.py can corroborate it; another business's details
are worse than none.

PageSpeed Insights: lab scores move between runs (a
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

from . import matching
from .fetcher import USER_AGENT

PSI_ENDPOINT = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"
PSI_CATEGORIES = ("performance", "accessibility", "best-practices")  # not seo: the site checks cover it
MOBILE_RUNS = 3
PSI_TIMEOUT_SECONDS = 120  # a measured call took 23.6 s; Google documents up to about 90
PSI_MAX_BYTES = 10_000_000  # a measured mobile response was 738 KB
CACHE_DIR = Path(".cache") / "pagespeed"
CACHE_SECONDS = 24 * 60 * 60

PLACES_SEARCH = "https://places.googleapis.com/v1/places:searchText"
PLACES_DETAILS = "https://places.googleapis.com/v1/places/{}"
SEARCH_MASK = "places.id,places.displayName"  # Pro tier
DETAILS_MASK = "id,displayName,businessStatus,websiteUri,nationalPhoneNumber,regularOpeningHours,userRatingCount"
PLACES_RESULTS = 5
MAX_DETAILS = 3  # details calls are billed at the Enterprise tier: never more than this per report
PLACES_TIMEOUT_SECONDS = 20


@dataclass(frozen=True)
class Business:
    """What the /digital form tells us about the business, for finding its Google Business Profile."""
    name: str
    city: str = ""
    phone: str = ""


@dataclass
class ExternalContext:
    psi_mobile: list[dict] = field(default_factory=list)  # raw responses, one per run that succeeded
    psi_desktop: dict | None = None  # one run; None means did not run
    place: dict | None = None  # Places details for a confirmed match; None means not found or did not run
    place_match: str = ""  # how the match was confirmed: "website" or "phone"
    errors: dict[str, str] = field(default_factory=dict)  # source -> why it is missing

    @property
    def places_configured(self) -> bool:
        """False when there is no Places key, in which case the profile checks show nothing at all."""
        return self.place is not None or "place" in self.errors

    @property
    def pagespeed_configured(self) -> bool:
        """False when there is no key, in which case the speed checks show nothing at all."""
        return bool(self.psi_mobile) or any(source.startswith("psi_mobile") for source in self.errors)


class SourceError(Exception):
    pass


def fetch_external(
    domain: str, url: str | None, skipped: str = "", *, business: Business | None = None,
    transport: httpx.BaseTransport | None = None,
) -> ExternalContext:
    """url is the page to test, normally PageContext.final_url. When it is None, PageSpeed is not called and
    skipped says why: we do not ask Google to load a page we could not, or were asked not to, load
    ourselves. The Places lookup does not touch the website, so it runs either way. transport is for tests."""
    context = ExternalContext()
    places_key = os.environ.get("PLACES_API_KEY", "").strip()
    if places_key:
        with httpx.Client(timeout=PLACES_TIMEOUT_SECONDS, transport=transport) as client:
            _find_place(client, context, domain, business, places_key)
    key = os.environ.get("PAGESPEED_API_KEY", "").strip()
    if not key:
        return context
    if url is None:
        context.errors.update({"psi_mobile": skipped, "psi_desktop": skipped})
        return context

    _prune_cache()
    jobs = [("mobile", run) for run in range(1, MOBILE_RUNS + 1)] + [("desktop", 1)]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=PSI_TIMEOUT_SECONDS, transport=transport) as client:
        failed = _run_jobs(client, context, domain, url, key, jobs)
        # A mobile run that failed gets one more try, so the median really is the middle of three when it can be.
        # Whatever still fails is recorded, and the checks say how many runs the figure came from.
        retry = [job for job in failed if job[0] == "mobile"]
        if retry:
            _run_jobs(client, context, domain, url, key, retry)
    return context


def _run_jobs(client: httpx.Client, context: ExternalContext, domain: str, url: str, key: str,
              jobs: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """Run PageSpeed jobs concurrently into context. Returns the jobs that failed."""
    failed = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {job: pool.submit(_pagespeed, client, domain, url, *job, key) for job in jobs}
    for (strategy, run), future in futures.items():
        source = f"psi_mobile_{run}" if strategy == "mobile" else "psi_desktop"
        try:
            data = future.result()
        except SourceError as exc:
            context.errors[source] = str(exc).replace(key, "<key>")
            failed.append((strategy, run))
            continue
        context.errors.pop(source, None)  # a retry that succeeded clears the first attempt's error
        if strategy == "mobile":
            context.psi_mobile.append(data)
        else:
            context.psi_desktop = data
    return failed


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


def _places_get(client: httpx.Client, method: str, url: str, key: str, mask: str, body: dict | None = None) -> dict:
    try:
        response = client.request(method, url, json=body, headers={"X-Goog-Api-Key": key, "X-Goog-FieldMask": mask})
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError(type(exc).__name__) from None  # the message can carry the request
    if response.status_code != 200:
        message = data.get("error", {}).get("message", "") if isinstance(data, dict) else ""
        raise SourceError(f"HTTP {response.status_code} {message}".strip())
    return data


def _find_place(client: httpx.Client, context: ExternalContext, domain: str, business: Business | None,
                key: str) -> None:
    """Search, then fetch details for name matches until one is corroborated. Records only counts about
    other businesses, never their names."""
    if business is None or not business.name.strip():
        context.errors["place"] = "no business name was given, so we did not search"
        return
    query = f"{business.name} {business.city}".strip()
    try:
        found = _places_get(client, "POST", PLACES_SEARCH, key, SEARCH_MASK,
                            {"textQuery": query, "pageSize": PLACES_RESULTS}).get("places", [])
        candidates = [p for p in found if matching.names_match(business.name, p.get("displayName", {}).get("text", ""))]
        for candidate in candidates[:MAX_DETAILS]:
            details = _places_get(client, "GET", PLACES_DETAILS.format(candidate["id"]), key, DETAILS_MASK)
            how = matching.corroboration(details, domain, business.phone)
            if how:
                context.place, context.place_match = details, how
                return
    except SourceError as exc:
        context.errors["place"] = f"Places: {exc}".replace(key, "<key>")
        return
    if not candidates:
        context.errors["place"] = (f'no listing named like "{business.name}" among {len(found)} search results for '
                                   f'"{query}"')
    else:
        context.errors["place"] = (f'{len(candidates)} listing(s) named like "{business.name}", but none links to '
                                   f"{domain} or lists the phone number we were given, so we did not use any of them")
