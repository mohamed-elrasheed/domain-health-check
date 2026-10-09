"""The Google Business Profile: the listing with hours, phone number, reviews and map pin that shows on
Google Search and Maps. For a local business it often brings in more customers than the website.

Read from the ExternalContext the runner fetched; no requests here. A listing reaches these checks only
when matching.py has confirmed it is this business, by its website or its phone number. When no listing
can be confirmed, that is one not-checked row: we cannot tell "no profile" from "a profile we could not
match", and reporting another business's details would be worse than reporting none.

The star rating is never scored and never a finding: a 3.8 average is not a defect anyone can fix, and telling
an owner their reviews are bad is not a finding. Since 2026-10-09 it is requested for one line on page 1 only,
beside the same averages for the top-ranked nearby listings of the same type (layout.nearby_line).
"""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

from ..external import ExternalContext
from ..fetcher import PageContext
from ..matching import site_host
from ..models import LOCAL, CheckResult, Status
from .site._html import parse, visible_text

PROFILE = "Google Business Profile"
COMPLETENESS = "Profile completeness"
WEBSITE_LINK = "Profile website link"
REVIEWS = "Reviews"
PHONE = "Profile phone number"
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
PHONE_EXPLANATION = (
    "Customers find your phone number both on your website and on your Google listing. When the two differ, some "
    "callers reach a number you may not expect, and it is harder for them to tell that the listing is yours."
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
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True,
               certain: bool = True) -> CheckResult:
        return CheckResult(LOCAL, PROFILE, status, summary, PROFILE_EXPLANATION, fix, list(details), ran, certain)

    if external.place is None:
        why = external.errors.get("place", "")
        # Not being findable is the finding: a customer searching by name and place would not find it either.
        # We never claim no profile exists, and we do not spend more calls trying to prove it.
        if external.place_outcome == "not_found":
            # Never a top finding and never in the draft to the business: not finding a listing is not proof it is
            # missing, so it goes under "Worth checking", worded as what we could not do.
            return result(
                Status.WARN, "We could not find a Google Business Profile by name, town or phone. Businesses that "
                             "hide their address can be hard to find this way.",
                "Search for your business on Google Maps the way a customer would, by name and town. If it does not "
                f"come up, create or claim your free profile at {MANAGE} and make sure it shows your business name, "
                "your website and the area you serve.", [why], certain=False)
        if external.place_outcome == "unconfirmed":
            # Only say what we compared: without a phone number from the form, we never looked at the listing's.
            phone = " or list your phone number" if external.phone_compared else ""
            return result(
                Status.WARN, "We found a Google Business Profile with a similar name, but it does not link to your "
                             f"website{phone}, so we could not confirm it is yours.",
                f"If that listing is yours, sign in at {MANAGE} and add your website, so customers can tell it is "
                "you.", [why], certain=False)  # we do not know the listing is theirs
        if why.startswith("no business name"):
            return result(Status.WARN, "We did not look for your Google Business Profile, because we did not have "
                                       "your business name.", "Nothing to do based on this report.", [why], ran=False)
        return result(Status.WARN, "Google's business listings did not answer this time, so your profile is not part "
                                   "of this report.", "Nothing to do based on this report.", [why], ran=False)

    status = external.place.get("businessStatus", "")
    # The Places API place type, not the category the owner chose in Business Profile.
    place_type = (external.place.get("primaryTypeDisplayName") or {}).get("text", "")
    kind = external.place.get("primaryType", "")
    details = _listing_details(external) + [f"Business status: {status or 'not stated'}",
                                            f"Google place type: {place_type or 'not stated'}"
                                            + (f" ({kind})" if kind else ""),
                                            "This is Google's broad type for the listing, not the category you chose."]
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
                       f"Sign in at {MANAGE}, open your profile and add your {listed}. It takes a few minutes.",
                       details,
                       measure=(len(wanted) - len(missing)) / len(wanted))


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
    page = _page_name(urlsplit(linked).path)
    summary = (f"Your Google Business Profile links to your {page}." if page else
               "Your Google Business Profile links to your website.")
    return CheckResult(LOCAL, WEBSITE_LINK, Status.PASS, summary, LINK_EXPLANATION, details=details)


def _page_name(path: str) -> str:
    """Which page an inner link goes to, in words: "contact page", or "page at /our-work/". "" for the home
    page."""
    segments = [unquote(s) for s in path.split("/") if s]
    if not segments or segments[-1].lower() in ("index.html", "index.php", "home"):
        return ""
    last = segments[-1].lower()
    for word, name in (("contact", "contact page"), ("about", "about page"), ("services", "services page")):
        if word in last:
            return name
    return f"page at {path}"


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
                       f"under \"Ask for reviews\" at {MANAGE}.", details, measure=count / MIN_REVIEWS)


def check_reviews(external: ExternalContext) -> list[CheckResult]:
    return [evaluate_reviews(external)] if external.place is not None else []


# ---------- Profile phone number

PHONE_NUMBER = re.compile(r"(?<!\d)(?:\+?1[\s.\-]?)?\(?(\d{3})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)")


def digits(phone: str) -> str:
    """The ten digits of a US number, whatever its punctuation or +1; "" when it is not one."""
    only = re.sub(r"\D", "", phone or "")
    if len(only) == 11 and only.startswith("1"):
        only = only[1:]
    return only if len(only) == 10 else ""


def shown(number: str) -> str:
    return f"({number[:3]}) {number[3:6]}-{number[6:]}"


def page_phones(html: str) -> list[str]:
    """Every distinct phone number on the page a visitor can see: tel: links and numbers in the visible text, as
    ten digits, in page order."""
    found = []
    for node in parse(html).css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        if href.lower().startswith("tel:"):
            found.append(digits(unquote(href[4:])))
    found += [digits("".join(m.groups())) for m in PHONE_NUMBER.finditer(visible_text(html))]
    return list(dict.fromkeys(n for n in found if n))


def evaluate_phone(listing_phone: str, on_page: list[str], listing_details: list[str]) -> CheckResult:
    """listing_phone as the listing gives it; on_page as ten-digit numbers. Never a FAIL: both numbers can be
    real, and the owner may mean them to differ."""
    listed = digits(listing_phone)
    details = listing_details + [f"Phone on the profile: {shown(listed) if listed else 'none'}",
                                 "Phones on the home page: " + (", ".join(shown(n) for n in on_page) or "none")]

    def result(status: Status, summary: str, fix: str = "", ran: bool = True) -> CheckResult:
        return CheckResult(LOCAL, PHONE, status, summary, PHONE_EXPLANATION, fix, details, ran)

    if not listed:
        return result(Status.WARN, "Your Google Business Profile shows no phone number, so there was nothing to "
                                   "compare.", "Nothing to do based on this check.", ran=False)
    if not on_page:
        return result(Status.WARN, "Your home page shows no phone number, so there was nothing to compare with your "
                                   "Google Business Profile.", "Nothing to do based on this check.", ran=False)
    if listed in on_page:
        return result(Status.PASS, f"The phone number on your Google Business Profile, {shown(listed)}, is also on "
                                   "your home page.")
    numbers = " and ".join(shown(n) for n in on_page[:3])
    return result(Status.WARN, f"Your home page shows {numbers}, but your Google Business Profile shows "
                               f"{shown(listed)}.",
                  "If both numbers are yours and that is on purpose, nothing needs to change. Otherwise, sign in at "
                  f"{MANAGE} or edit your website so the two show the same number.")


def check_phone(external: ExternalContext, page: PageContext | object) -> list[CheckResult]:
    """Not checked without a confirmed listing or without the page; the listing's own row says why. Like the other
    profile checks, nothing at all when no profile lookup was attempted (no Places key)."""
    if not external.places_configured:
        return []
    if external.place is None:
        return [CheckResult(LOCAL, PHONE, Status.WARN, "We could not compare phone numbers, because we could not "
                            "confirm a Google Business Profile for this business.", PHONE_EXPLANATION,
                            "Nothing to do based on this check.", [], ran=False)]
    if not isinstance(page, PageContext):
        return [CheckResult(LOCAL, PHONE, Status.WARN, "We could not compare phone numbers, because we could not "
                            "load your home page.", PHONE_EXPLANATION, "Nothing to do based on this check.", [],
                            ran=False)]
    return [evaluate_phone(external.place.get("nationalPhoneNumber", ""), page_phones(page.visible_html),
                           _listing_details(external))]
