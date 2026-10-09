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
import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import httpx
import yaml

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
# The anonymous comparison on page 1: the top-ranked listings of the same Google place type within 10 miles. Only their
# review counts and ratings are requested, never a name, and only averages are kept.
PLACES_NEARBY = "https://places.googleapis.com/v1/places:searchNearby"
NEARBY_MASK = "places.id,places.rating,places.userRatingCount"
NEARBY_METERS = 16_093  # 10 miles
NEARBY_RESULTS = 4  # three others, plus room for the business's own listing
NEARBY_COUNT = 3
NEARBY_TRADES = Path(__file__).parent.parent / "config" / "nearby.yaml"  # categories specific enough to compare
MAX_PHONE_DETAILS = 2  # details calls for listings found by phone, on top of MAX_DETAILS
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
    place_match: str = ""  # how the match was confirmed: always "website" (a listing counts only by its website)
    place_step: str = ""  # which search found it: "name and town as submitted", "name, ZIP and state", "name alone",
    # or "phone"
    # What the search came to: "found", "not_found" (no listing by that name and place), "unconfirmed" (a similar
    # name that does not link back to the domain or phone), or "" when it did not run (no key, no name, an error).
    place_outcome: str = ""
    phone_compared: bool = False  # whether we had a phone number to compare listings against
    # The top-ranked nearby listings of the same type, as averages only: {"place_type", "count", "reviews", "rating"}.
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
    """One Nearby Search for the business's own Google place type around its own listing. Logged like every Places call
    (requestlog source "places"); a failure leaves the comparison out rather than sinking the report."""
    place = context.place or {}
    kind = place.get("primaryType")
    where = place.get("location") or {}
    if not kind or "latitude" not in where or "longitude" not in where:
        context.errors["nearby"] = "the listing has no Google place type or location, so we did not compare"
        return
    if kind not in nearby_trades():  # a broad category would compare the business with whatever shares the label
        context.errors["nearby"] = (f"the listing's Google place type ({kind}) is not a specific trade, so we did not "
                                    "compare")
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
    place_type = (place.get("primaryTypeDisplayName") or {}).get("text") or ""
    context.nearby = {"place_type": place_type, **averages}


def _search(client: httpx.Client, key: str, query: str) -> list[dict]:
    """One Text Search. includePureServiceAreaBusinesses: a business that hides its address (it goes to its
    customers) is left out of Text Search unless this is set, and was, for our own listing, until it was."""
    return _places_get(client, "POST", PLACES_SEARCH, key, SEARCH_MASK,
                       {"textQuery": query, "pageSize": PLACES_RESULTS,
                        "includePureServiceAreaBusinesses": True}).get("places", [])


def _confirm(client: httpx.Client, context: ExternalContext, key: str, candidates: list[dict], domain: str,
             budget: list[int], checked: set[str], step: str) -> bool:
    """Fetch details for each candidate until one has its website on the submitted domain; True when one does.
    A phone number alone never confirms a listing. budget caps details calls across every step."""
    for candidate in candidates:
        if budget[0] <= 0:
            return False
        budget[0] -= 1
        checked.add(candidate.get("id"))
        details = _places_get(client, "GET", PLACES_DETAILS.format(candidate["id"]), key, DETAILS_MASK)
        if matching.corroboration(details, domain, "") == "website":
            context.place, context.place_match, context.place_outcome = details, "website", "found"
            context.place_step = step
            _find_nearby(client, context, key)
            return True
    return False


@lru_cache(maxsize=1)
def nearby_trades() -> frozenset[str]:
    return frozenset(yaml.safe_load(NEARBY_TRADES.read_text(encoding="utf-8"))["trades"])


def _find_place(client: httpx.Client, context: ExternalContext, domain: str, business: Business | None,
                key: str) -> None:
    """Search in order until a listing is confirmed, stopping at the first. Every search includes service-area
    businesses, and a listing counts only when its website is on the submitted domain:

      1. business name plus the town or ZIP exactly as submitted;
      2. when that value is a 5-digit ZIP or empty: business name plus the ZIP and its state, the state read from
         Google's own answer for the ZIP (one more search, made only for this step);
      3. business name alone;
      4. the submitted phone number.

    A step whose query would repeat an earlier one is skipped. Every request is logged like any other. Records only
    counts about other businesses, never their names."""
    if business is None or not business.name.strip():
        context.errors["place"] = "no business name was given, so we did not search"
        return
    name, town = business.name.strip(), business.city.strip()
    tried: list[tuple[str, str, int]] = []  # (step, query, results)
    named: dict[str, dict] = {}  # name-matching candidates across every step, by id
    budget = [MAX_DETAILS + MAX_PHONE_DETAILS]  # details calls are billed at the Enterprise tier

    def step(label: str, query: str, by_name: bool = True) -> bool:
        if not query or query in (q for _, q, _ in tried):
            return False
        found = _search(client, key, query)
        tried.append((label, query, len(found)))
        pool = []
        for place in found:
            matches = matching.names_match(name, place.get("displayName", {}).get("text", ""))
            if matches:
                named.setdefault(place.get("id"), place)
            if (matches or not by_name) and place.get("id") not in context_checked:
                pool.append(place)
        return _confirm(client, context, key, pool, domain, budget, context_checked, label)

    context_checked: set[str] = set()
    try:
        if step("name and town as submitted", f"{name} {town}".strip()):
            return
        if not town or ZIP.fullmatch(town):
            state = _state_for_zip(client, key, town) if town else ""
            if step("name, ZIP and state", " ".join(part for part in (name, town, state) if part)):
                return
        if step("name alone", name):
            return
        if matching.phone_digits(business.phone) and step("phone", business.phone.strip(), by_name=False):
            return
    except SourceError as exc:
        context.errors["place"] = f"Places: {exc}".replace(key, "<key>")
        return
    searched = "; ".join(f'{label} "{query}": {count} result{"s" if count != 1 else ""}'
                         for label, query, count in tried)
    if not named:
        context.place_outcome = "not_found"
        context.errors["place"] = f'no listing named like "{name}" was confirmed by its website ({searched})'
    else:
        context.place_outcome = "unconfirmed"
        many = len(named) != 1
        context.errors["place"] = (f'{len(named)} listing{"s are" if many else " is"} named like "{name}", but '
                                   f'{"none links" if many else "it does not link"} to {domain}, so we did not use '
                                   f'{"any of them" if many else "it"} ({searched})')


ZIP = re.compile(r"\d{5}")
STATE_IN_ADDRESS = re.compile(r",\s*([A-Z]{2})\s+\d{5}\b")


def _state_for_zip(client: httpx.Client, key: str, zip_code: str) -> str:
    """The state a ZIP is in, from Google's own answer for it ("Centreville, VA 20121, USA" gives VA), or "" when
    Google does not return the ZIP itself. One Text Search, logged like the others."""
    found = _places_get(client, "POST", PLACES_SEARCH, key, "places.displayName,places.formattedAddress,places.types",
                        {"textQuery": zip_code, "pageSize": 1}).get("places", [])
    for place in found:
        if "postal_code" in (place.get("types") or []) and place.get("displayName", {}).get("text") == zip_code:
            match = STATE_IN_ADDRESS.search(place.get("formattedAddress") or "")
            if match:
                return match.group(1)
    return ""
