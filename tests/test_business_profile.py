"""Google Business Profile: matching, the Places client and the four checks.

Every listing here is synthetic, written in the response shape confirmed against the live Places API (New) on
2 October 2026: displayName is {"text", "languageCode"}, nationalPhoneNumber is "(555) 010-0100", userRatingCount
is an int, and a field with no value is left out. No real business's listing is committed."""

import json

import httpx
import pytest

from domain_health_check import external, runner, scoring
from domain_health_check.checks import business_profile as bp
from domain_health_check.config import DomainConfig
from domain_health_check.external import Business, ExternalContext
from domain_health_check.matching import corroboration, names_match, phone_digits
from domain_health_check.models import LOCAL, Status

KEY = "places-test-key"


def listing(place_id="p1", name="Example Plumbing", website="https://www.example.com/", phone="(555) 010-0100",
            status="OPERATIONAL", reviews=27, hours=True) -> dict:
    data = {"id": place_id, "displayName": {"text": name, "languageCode": "en"}, "businessStatus": status}
    if website:
        data["websiteUri"] = website
    if phone:
        data["nationalPhoneNumber"] = phone
    if hours:
        data["regularOpeningHours"] = {"openNow": True, "periods": [{"open": {"day": 1, "hour": 8, "minute": 0},
                                       "close": {"day": 1, "hour": 17, "minute": 0}}],
                                       "weekdayDescriptions": ["Monday: 8:00 AM – 5:00 PM"]}
    if reviews:
        data["userRatingCount"] = reviews
    return data


# ---------- matching

@pytest.mark.parametrize("submitted, listed, match", [
    ("Example Plumbing LLC", "Example Plumbing", True),
    ("Smith & Sons Plumbing", "Smith and Sons Plumbing, Inc.", True),
    ("Example Floors", "Example Floors Springfield", True),          # whole name inside a longer one
    ("Example Plumbing", "Exampel Plumbing", True),                      # a typo
    ("Example Group", "Example general construction", False),             # a near miss: one shared word
    ("Example", "Example general construction", False),                      # a single word is never enough
    ("Example Plumbing", "Example Bakery", False),
    ("", "Example Plumbing", False),
])
def test_names_match(submitted, listed, match):
    assert names_match(submitted, listed) is match


def test_phone_and_website_corroboration():
    assert phone_digits("+1 (555) 010-0100") == phone_digits("555.010.0100") == "5550100100"
    assert corroboration(listing(), "example.com", "") == "website"
    assert corroboration(listing(website="https://other.test/"), "example.com", "555-010-0100") == "phone"
    assert corroboration(listing(website="https://other.test/"), "example.com", "") is None
    assert corroboration(listing(website="", phone="(555) 999-0000"), "example.com", "555-010-0100") is None


# ---------- the Places client

def places_api(search, details, seen=None, status=200):
    """A fake Places API: search returns `search`, details returns details[place_id]."""
    def handle(request):
        if seen is not None:
            seen.append(request)
        if status != 200:
            return httpx.Response(status, json={"error": {"code": status, "message": f"denied for {KEY}"}})
        if request.url.path.endswith(":searchText"):
            return httpx.Response(200, json={"places": search} if search else {})
        return httpx.Response(200, json=details[request.url.path.rsplit("/", 1)[-1]])
    return httpx.MockTransport(handle)


@pytest.fixture
def with_places_key(monkeypatch):
    monkeypatch.setenv("PLACES_API_KEY", KEY)


def find(transport, business=Business("Example Plumbing", "Springfield", "")):
    return external.fetch_external("example.com", None, business=business, transport=transport)


def test_no_key_no_call():
    seen = []
    context = find(places_api([], {}, seen))
    assert seen == [] and not context.places_configured


def test_lookalike_is_skipped_and_the_confirmed_listing_is_used(with_places_key):
    search = [{"id": "near", "displayName": {"text": "Example Plumbing Supply", "languageCode": "en"}},
              {"id": "real", "displayName": {"text": "Example Plumbing", "languageCode": "en"}}]
    details = {"near": listing("near", "Example Plumbing Supply", website="https://supply.test/", phone=""),
               "real": listing("real")}
    seen = []
    context = find(places_api(search, details, seen))
    assert context.place["id"] == "real" and context.place_match == "website"
    search_call, *detail_calls = seen
    assert search_call.method == "POST" and search_call.headers["X-Goog-Api-Key"] == KEY
    assert search_call.headers["X-Goog-FieldMask"] == "places.id,places.displayName"
    # The rating is requested for one line on page 1 only (layout.nearby_line); it is never scored or a finding.
    assert "rating" in detail_calls[0].headers["X-Goog-FieldMask"].split(",")
    # Service-area businesses (no public address) are left out of Text Search unless this is set.
    assert json.loads(search_call.content) == {"textQuery": "Example Plumbing Springfield", "pageSize": 5,
                                               "includePureServiceAreaBusinesses": True}


def test_name_match_without_corroboration_is_rejected(with_places_key):
    search = [{"id": "x", "displayName": {"text": "Example Plumbing", "languageCode": "en"}}]
    context = find(places_api(search, {"x": listing("x", website="https://other.test/", phone="(555) 999-0000")}))
    assert context.place is None and context.place_outcome == "unconfirmed" and not context.phone_compared
    assert "does not link to example.com, so" in context.errors["place"]


def test_no_name_match_records_counts_not_other_businesses(with_places_key):
    search = [{"id": "a", "displayName": {"text": "Unrelated Bakery", "languageCode": "en"}}]
    context = find(places_api(search, {}))
    assert context.place is None and context.place_outcome == "not_found"
    assert "among 1 search results" in context.errors["place"]
    assert "Unrelated Bakery" not in context.errors["place"]


def test_detail_calls_are_capped(with_places_key):
    search = [{"id": f"p{i}", "displayName": {"text": "Example Plumbing", "languageCode": "en"}} for i in range(5)]
    details = {f"p{i}": listing(f"p{i}", website="https://other.test/", phone="") for i in range(5)}
    seen = []
    find(places_api(search, details, seen))
    assert len(seen) == 1 + external.MAX_DETAILS


def test_no_business_name_does_not_search(with_places_key):
    seen = []
    context = find(places_api([], {}, seen), business=None)
    assert seen == [] and context.errors["place"].startswith("no business name")


def test_api_error_is_recorded_without_the_key(with_places_key):
    context = find(places_api([], {}, status=403))
    assert context.errors["place"].startswith("Places: HTTP 403") and KEY not in context.errors["place"]


# ---------- the checks

def found(**overrides) -> ExternalContext:
    return ExternalContext(place=listing(**overrides), place_match="website")


def test_operational_profile_passes():
    [result] = bp.check_profile(found())
    assert result.status is Status.PASS and result.category == LOCAL
    assert "Confirmed as yours because its website is on your domain" in result.details


@pytest.mark.parametrize("status, phrase", [("CLOSED_TEMPORARILY", "temporarily closed"),
                                            ("CLOSED_PERMANENTLY", "permanently closed")])
def test_closed_profile_warns(status, phrase):
    [result] = bp.check_profile(found(status=status))
    assert result.status is Status.WARN and phrase in result.summary


def test_not_findable_is_worth_checking_and_claims_nothing_more():
    context = ExternalContext(place_outcome="not_found", errors={"place": 'no listing named like "X" among 0 results'})
    [result] = bp.check_profile(context)
    assert result.ran and result.status is Status.WARN and not result.certain  # "Worth checking", never a top finding
    assert result.summary == ("We could not find a Google Business Profile by name, town or phone. Businesses that "
                              "hide their address can be hard to find this way.")
    assert "does not have" not in result.summary and "no profile" not in result.summary.lower()
    assert bp.check_completeness(context) == bp.check_website_link(context, "example.com") == bp.check_reviews(context) == []


def test_unconfirmed_similar_listing_is_a_finding_without_its_details():
    context = ExternalContext(place_outcome="unconfirmed",
                              errors={"place": "1 listing(s) named like ..., but none links to example.com"})
    [result] = bp.check_profile(context)
    assert result.ran and result.status is Status.WARN and "similar name" in result.summary
    assert "phone" not in result.summary  # no phone was given, so none was compared


def test_phone_is_mentioned_only_when_one_was_compared():
    context = ExternalContext(place_outcome="unconfirmed", phone_compared=True, errors={"place": "x"})
    assert "or list your phone number" in bp.check_profile(context)[0].summary


def test_api_error_is_not_checked():
    [result] = bp.check_profile(ExternalContext(errors={"place": "Places: HTTP 500"}))
    assert not result.ran


def test_no_places_key_means_no_rows():
    context = ExternalContext()
    assert bp.check_profile(context) == []


def test_completeness():
    assert bp.check_completeness(found())[0].status is Status.PASS
    [result] = bp.check_completeness(found(hours=False, phone=""))
    assert result.status is Status.WARN and result.summary.endswith("missing your phone number and opening hours.")


def test_website_link():
    assert bp.check_website_link(found(), "example.com")[0].status is Status.PASS
    [other] = bp.check_website_link(found(website="https://old-site.test/"), "example.com")
    assert other.status is Status.WARN and "old-site.test rather than example.com" in other.summary
    [none] = bp.check_website_link(found(website=""), "example.com")
    assert "does not link to your website" in none.summary


def test_reviews_count_only_never_the_rating():
    assert bp.check_reviews(found(reviews=27))[0].status is Status.PASS
    [few] = bp.check_reviews(found(reviews=2))
    assert few.status is Status.WARN and "2 reviews so far" in few.summary
    [zero] = bp.check_reviews(found(reviews=0))
    assert "no reviews yet" in zero.summary
    rated = found()
    rated.place["rating"] = 3.8  # even if Google sent it, it is never shown or scored
    for r in bp.check_profile(rated) + bp.check_reviews(rated) + bp.check_completeness(rated):
        assert "3.8" not in r.summary + " ".join(r.details) and "rating" not in r.summary.lower()


def test_weights():
    # Tier 3 of the ladder: customers cannot find the business locally.
    assert [scoring.WEIGHTS[n] for n in (bp.PROFILE, bp.COMPLETENESS, bp.WEBSITE_LINK, bp.REVIEWS)] == [3, 3, 3, 3]


def test_runner_passes_the_business_from_the_config(monkeypatch):
    seen = {}

    def fake(domain, url, skipped, business=None):
        seen["business"] = business
        return ExternalContext()
    monkeypatch.setattr(runner.external, "fetch_external", fake)
    config = DomainConfig("example.com", business_name="Example Plumbing", city="Springfield", phone="555-010-0100")
    runner._fetch_external(config, runner.FetchError("https://example.com/", "x"))
    assert seen["business"] == Business("Example Plumbing", "Springfield", "555-010-0100")



def test_a_listing_found_only_by_phone_is_used_when_it_confirms(with_places_key):
    """The form's business name can differ from the listing's: the phone search finds it, and its phone confirms it."""
    seen = []
    listing_by_phone = {**listing("by-phone", name="Totally Different Name", website="",
                                  phone="(555) 010-0100")}

    def handle(request):
        seen.append(request)
        if request.url.path.endswith(":searchText"):
            query = json.loads(request.content)["textQuery"]
            places = [] if "Example" in query else [{"id": "by-phone", "displayName": {"text": "Totally Different Name"}}]
            return httpx.Response(200, json={"places": places})
        return httpx.Response(200, json=listing_by_phone)
    context = find(httpx.MockTransport(handle), Business("Example Plumbing", "Springfield", "555-010-0100"))
    assert context.place["id"] == "by-phone" and context.place_match == "phone"
    queries = [json.loads(r.content)["textQuery"] for r in seen if r.url.path.endswith(":searchText")]
    assert queries == ["Example Plumbing Springfield", "555-010-0100"]


def test_not_found_by_name_or_phone_says_both_were_tried(with_places_key):
    context = find(places_api([], {}), Business("Example Plumbing", "Springfield", "555-010-0100"))
    assert context.place_outcome == "not_found"
    assert "and 0 for the phone number" in context.errors["place"]


def test_not_found_never_reaches_the_top_or_the_draft():
    from datetime import datetime, timezone

    from domain_health_check import layout, mailer
    from domain_health_check.models import SITE, CheckResult, DomainReport
    [not_found] = bp.check_profile(ExternalContext(place_outcome="not_found", errors={"place": "x"}))
    heading = CheckResult(SITE, "Main heading", Status.WARN, "Your home page has no main heading.", "Why.", "Fix.", [])
    report = DomainReport("example.com", datetime(2026, 10, 9, tzinfo=timezone.utc), [not_found, heading])
    assert [r.name for r in layout.worth_doing(report)] == ["Main heading"]
    assert not_found in layout.worth_checking(report)
    assert "Google Business Profile" not in mailer.draft_to_business(report)


def test_the_google_place_type_is_in_the_technical_details(with_places_key):
    place = {**listing("real"), "primaryType": "service", "primaryTypeDisplayName": {"text": "Services"}}
    [result] = bp.check_profile(ExternalContext(place=place, place_match="website"))
    assert "Google place type: Services (service)" in result.details
    assert "This is Google's broad type for the listing, not the category you chose." in result.details
    assert not any("categor" in d.lower() and "not the category you chose" not in d for d in result.details)
