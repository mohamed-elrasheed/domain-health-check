"""The Google Business Profile: the listing with hours, phone number, reviews and map pin that shows on
Google Search and Maps. For a local business it often brings in more customers than the website.

Read from the ExternalContext the runner fetched; no requests here. A listing reaches these checks only
when matching.py has confirmed it is this business, by its website or its phone number. When no listing
can be confirmed, that is one not-checked row: we cannot tell "no profile" from "a profile we could not
match", and reporting another business's details would be worse than reporting none.

The star rating is never requested, scored or shown. A 3.8 average is not a defect anyone can fix, and
telling an owner their reviews are bad is not a finding.
"""

from __future__ import annotations

from ..external import ExternalContext
from ..matching import site_host
from ..models import LOCAL, CheckResult, Status

PROFILE = "Google Business Profile"
COMPLETENESS = "Profile completeness"
WEBSITE_LINK = "Profile website link"
REVIEWS = "Reviews"
MIN_REVIEWS = 5
MANAGE = "business.google.com"

PROFILE_EXPLANATION = (
    "Your Google Business Profile is the listing that shows your hours, phone number, reviews and location on "
    "Google Search and Maps. For a local business it often brings in more customers than the website itself. We "
    "only report on a listing when we can confirm it is yours, because another business's details would be worse "
    "than none."
)
COMPLETENESS_EXPLANATION = (
    "People often decide from the listing alone whether to call, visit or click through. A missing phone number, "
    "website or opening hours sends them to a competitor whose listing answers the question."
)
LINK_EXPLANATION = (
    "The website link on your profile is how people get from Google Maps to your site, and it is one of the ways "
    "Google connects your listing to your website."
)
REVIEWS_EXPLANATION = (
    "Reviews are one of the first things people look at when choosing a local business, and listings with more of "
    "them tend to show up higher on Google Maps."
)
STATUS_SUMMARY = {
    "CLOSED_TEMPORARILY": "Your Google Business Profile shows your business as temporarily closed.",
    "CLOSED_PERMANENTLY": "Your Google Business Profile shows your business as permanently closed, so Google may "
                          "tell customers you are no longer in business.",
}


def _listing_details(external: ExternalContext) -> list[str]:
    place = external.place or {}
    how = {"website": "its website is on your domain", "phone": "its phone number matches the one you gave us"}
    return [f"Listing: {place.get('displayName', {}).get('text', '(no name)')}",
            f"Confirmed as yours because {how.get(external.place_match, 'it matched')}"]


# ---------- Google Business Profile

def evaluate_profile(external: ExternalContext) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True) -> CheckResult:
        return CheckResult(LOCAL, PROFILE, status, summary, PROFILE_EXPLANATION, fix, list(details), ran)

    if external.place is None:
        why = external.errors.get("place", "")
        # Not being findable is the finding: a customer searching by name and place would not find it either.
        # We never claim no profile exists, and we do not spend more calls trying to prove it.
        if external.place_outcome == "not_found":
            return result(
                Status.WARN, "We could not find a Google Business Profile for this business by name and location. "
                             "Either there is not one, or it is not set up to be found.",
                "Search for your business on Google Maps the way a customer would, by name and town. If it does not "
                f"come up, create or claim your free profile at {MANAGE} and make sure it shows your business name, "
                "your website and the area you serve.", [why])
        if external.place_outcome == "unconfirmed":
            return result(
                Status.WARN, "We found a Google Business Profile with a similar name, but it does not link to your "
                             "website or list your phone number, so we could not confirm it is yours.",
                f"If that listing is yours, sign in at {MANAGE} and add your website, so customers can tell it is "
                "you.", [why])
        if why.startswith("no business name"):
            return result(Status.WARN, "We did not look for your Google Business Profile, because we did not have "
                                       "your business name.", "Nothing to do based on this report.", [why], ran=False)
        return result(Status.WARN, "Google's business listings did not answer this time, so your profile is not part "
                                   "of this report.", "Nothing to do based on this report.", [why], ran=False)

    status = external.place.get("businessStatus", "")
    details = _listing_details(external) + [f"Business status: {status or 'not stated'}"]
    if status == "OPERATIONAL":
        return result(Status.PASS, "Your business has a Google Business Profile, and it shows you as open.",
                      details=details)
    fix = f"If you are open, sign in at {MANAGE} and mark the business as open."
    return result(Status.WARN, STATUS_SUMMARY.get(status, "Your Google Business Profile does not say whether your "
                                                          "business is open."), fix, details)


def check_profile(external: ExternalContext) -> list[CheckResult]:
    return [evaluate_profile(external)] if external.places_configured else []


# ---------- Profile completeness

def evaluate_completeness(external: ExternalContext) -> CheckResult:
    place = external.place
    wanted = {"websiteUri": "website", "nationalPhoneNumber": "phone number", "regularOpeningHours": "opening hours"}
    missing = [label for key, label in wanted.items() if not place.get(key)]
    details = _listing_details(external) + [f"Missing: {label}" for label in missing]
    if not missing:
        return CheckResult(LOCAL, COMPLETENESS, Status.PASS, "Your Google Business Profile lists your website, "
                           "phone number and opening hours.", COMPLETENESS_EXPLANATION, details=details)
    listed = missing[0] if len(missing) == 1 else ", ".join(missing[:-1]) + f" and {missing[-1]}"
    return CheckResult(LOCAL, COMPLETENESS, Status.WARN, f"Your Google Business Profile is missing your {listed}.",
                       COMPLETENESS_EXPLANATION,
                       f"Sign in at {MANAGE}, open your profile and add your {listed}. It takes a few minutes.", details)


def check_completeness(external: ExternalContext) -> list[CheckResult]:
    return [evaluate_completeness(external)] if external.place is not None else []


# ---------- Profile website link

def evaluate_website_link(external: ExternalContext, domain: str) -> CheckResult:
    linked = external.place.get("websiteUri", "")
    details = _listing_details(external) + [f"Website on the profile: {linked or 'none'}"]
    fix = f"Sign in at {MANAGE} and set the website on your profile to https://{domain}/"
    if not linked:
        return CheckResult(LOCAL, WEBSITE_LINK, Status.WARN, "Your Google Business Profile does not link to your "
                           "website.", LINK_EXPLANATION, fix, details)
    if site_host(linked) != domain.removeprefix("www."):
        return CheckResult(LOCAL, WEBSITE_LINK, Status.WARN, f"Your Google Business Profile links to "
                           f"{site_host(linked)} rather than {domain}.", LINK_EXPLANATION, fix, details)
    return CheckResult(LOCAL, WEBSITE_LINK, Status.PASS, "Your Google Business Profile links to your website.",
                       LINK_EXPLANATION, details=details)


def check_website_link(external: ExternalContext, domain: str) -> list[CheckResult]:
    return [evaluate_website_link(external, domain)] if external.place is not None else []


# ---------- Reviews

def evaluate_reviews(external: ExternalContext) -> CheckResult:
    count = external.place.get("userRatingCount") or 0  # Google leaves the field out when there are none
    details = _listing_details(external) + [f"Number of reviews: {count}"]
    if count >= MIN_REVIEWS:
        return CheckResult(LOCAL, REVIEWS, Status.PASS, f"Your Google Business Profile has {count:,} reviews.",
                           REVIEWS_EXPLANATION, details=details)
    summary = ("Your Google Business Profile has no reviews yet." if count == 0 else
               f"Your Google Business Profile has {count} review{'s' if count != 1 else ''} so far.")
    return CheckResult(LOCAL, REVIEWS, Status.WARN, summary, REVIEWS_EXPLANATION,
                       "Ask a few happy customers to leave a review. Your profile has a share link for exactly this, "
                       f"under \"Ask for reviews\" at {MANAGE}.", details)


def check_reviews(external: ExternalContext) -> list[CheckResult]:
    return [evaluate_reviews(external)] if external.place is not None else []
