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

from . import matching, requestlog
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
DETAILS_MASK = ("id,displayName,businessStatus,websiteUri,nationalPhoneNumber,regularOpeningHours,userRatingCount,"
                "rating,location,primaryType,primaryTypeDisplayName")
# The anonymous comparison on page 1: the top-ranked listings of the same primary type within 10 miles. Only their
# review counts and ratings are requested, never a name, and only averages are kept.
PLACES_NEARBY = "https://places.googleapis.com/v1/places:searchNearby"
NEARBY_MASK = "places.id,places.rating,places.userRatingCount"
NEARBY_METERS = 16_093  # 10 miles
NEARBY_RESULTS = 4  # three others, plus room for the business's own listing
NEARBY_COUNT = 3
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
    # What the search came to: "found", "not_found" (no listing by that name and place), "unconfirmed" (a similar
    # name that does not link back to the domain or phone), or "" when it did not run (no key, no name, an error).
    place_outcome: str = ""
    phone_compared: bool = False  # whether we had a phone number to compare listings against
    # The top-ranked nearby listings of the same type, as averages only: {"category", "count", "reviews", "rating"}.
    # None when it did not run or found fewer than three.
    nearby: dict | None = None
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
        with httpx.Client(timeout=PLACES_TIMEOUT_SECONDS, transport=transport,
                          event_hooks=requestlog.httpx_hooks("places")) as client:
            _find_place(client, context, domain, business, places_key)
    key = os.environ.get("PAGESPEED_API_KEY", "").strip()
    if not key:
        return context
    if url is None:
        context.errors.update({"psi_mobile": skipped, "psi_desktop": skipped})
        return context

    _prune_cache()
    jobs = [("mobile", run) for run in range(1, MOBILE_RUNS + 1)] + [("desktop", 1)]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=PSI_TIMEOUT_SECONDS, transport=transport,
                      event_hooks=requestlog.httpx_hooks("pagespeed")) as client:
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


def prune_cache(now: float | None = None) -> list[Path]:
    """Delete cached PageSpeed responses older than CACHE_SECONDS. Returns what was deleted. The report
    command calls this at the start of every run, whether or not PageSpeed is used, so the 24-hour rule
    holds even when no new response is fetched."""
    now = time.time() if now is None else now
    removed = []
    if CACHE_DIR.is_dir():
        for path in sorted(CACHE_DIR.iterdir()):
            if path.is_file() and now - path.stat().st_mtime >= CACHE_SECONDS:
                path.unlink(missing_ok=True)
                removed.append(path)
    return removed


def _prune_cache() -> None:
    prune_cache()


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


def nearby_averages(listings: list[dict], own_id: str) -> dict | None:
    """Averages over the first three listings that are not the business's own, in Google's ranking order, or None
    when there are fewer than three. Only counts and ratings: no other business is identified."""
    others = [p for p in listings if p.get("id") != own_id][:NEARBY_COUNT]
    if len(others) < NEARBY_COUNT:
        return None
    rated = [p["rating"] for p in others if isinstance(p.get("rating"), (int, float))]
    if not rated:
        return None
    return {"count": NEARBY_COUNT, "reviews": sum(p.get("userRatingCount") or 0 for p in others) / NEARBY_COUNT,
            "rating": sum(rated) / len(rated)}


def _find_nearby(client: httpx.Client, context: ExternalContext, key: str) -> None:
    """One Nearby Search for the business's own primary type around its own listing. Logged like every Places call
    (requestlog source "places"); a failure leaves the comparison out rather than sinking the report."""
    place = context.place or {}
    kind = place.get("primaryType")
    where = place.get("location") or {}
    if not kind or "latitude" not in where or "longitude" not in where:
        context.errors["nearby"] = "the listing has no primary category or location, so we did not compare"
        return
    body = {"includedPrimaryTypes": [kind], "maxResultCount": NEARBY_RESULTS, "rankPreference": "POPULARITY",
            "locationRestriction": {"circle": {"center": {"latitude": where["latitude"],
                                                          "longitude": where["longitude"]},
                                               "radius": NEARBY_METERS}}}
    try:
        found = _places_get(client, "POST", PLACES_NEARBY, key, NEARBY_MASK, body).get("places", [])
    except SourceError as exc:
        context.errors["nearby"] = f"Places nearby: {exc}".replace(key, "<key>")
        return
    averages = nearby_averages(found, place.get("id", ""))
    if averages is None:
        context.errors["nearby"] = f"fewer than {NEARBY_COUNT} other listings of this type within 10 miles"
        return
    category = (place.get("primaryTypeDisplayName") or {}).get("text") or ""
    context.nearby = {"category": category, **averages}


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
                context.place, context.place_match, context.place_outcome = details, how, "found"
                _find_nearby(client, context, key)
                return
    except SourceError as exc:
        context.errors["place"] = f"Places: {exc}".replace(key, "<key>")
        return
    if not candidates:
        context.place_outcome = "not_found"
        context.errors["place"] = (f'no listing named like "{business.name}" among {len(found)} search results for '
                                   f'"{query}"')
    else:
        context.place_outcome = "unconfirmed"
        context.phone_compared = bool(matching.phone_digits(business.phone))
        phone = " or lists the phone number we were given" if context.phone_compared else ""
        if len(candidates) == 1:
            context.errors["place"] = (f'1 listing is named like "{business.name}", but it does not link to '
                                       f"{domain}{phone}, so we did not use it")
        else:
            context.errors["place"] = (f'{len(candidates)} listings are named like "{business.name}", but none '
                                       f"links to {domain}{phone}, so we did not use any of them")
