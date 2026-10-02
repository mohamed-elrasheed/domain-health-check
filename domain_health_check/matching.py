"""Deciding whether a Google Places result is the business that submitted the form.

A wrong match is worse than no match: it would show a client another
business's details. A listing is accepted only when its name is a close match
and at least one independent fact corroborates it: the listing's website is on
the submitted domain, or its phone number is the submitted one. A name alone is
never enough. A real search for one business returned a different one whose
name shared a single word with it.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from urllib.parse import urlsplit

LEGAL_SUFFIXES = {"llc", "pllc", "inc", "incorporated", "co", "company", "corp", "corporation", "ltd", "limited",
                  "lp", "llp"}
SIMILAR = 0.9  # for small spelling differences, such as "Example Flooring" and "Example Floorings"


def name_tokens(name: str) -> list[str]:
    words = re.sub(r"[^\w\s]", "", name.lower().replace("&", " and ")).split()
    return [w for w in words if w not in LEGAL_SUFFIXES and w != "the"]


def names_match(submitted: str, listed: str) -> bool:
    """Equal once legal suffixes and punctuation are gone, one name containing the other whole (when the shorter
    has at least two words), or a near-identical spelling. A single shared word is not a match."""
    a, b = name_tokens(submitted), name_tokens(listed)
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    if len(shorter) >= 2 and f" {' '.join(shorter)} " in f" {' '.join(longer)} ":
        return True
    return SequenceMatcher(None, " ".join(a), " ".join(b)).ratio() >= SIMILAR


def phone_digits(phone: str) -> str:
    """The last ten digits, so (555) 010-0100, 555.010.0100 and +1 555 010 0100 compare equal."""
    return re.sub(r"\D", "", phone or "")[-10:]


def site_host(url: str) -> str:
    host = urlsplit(url if "//" in url else f"//{url}").hostname or ""
    return host.removeprefix("www.")


def corroboration(details: dict, domain: str, phone: str) -> str | None:
    """How the listing is confirmed to be this business: "website", "phone", or None."""
    if details.get("websiteUri") and site_host(details["websiteUri"]) == domain.removeprefix("www."):
        return "website"
    listed = phone_digits(details.get("nationalPhoneNumber", ""))
    if len(listed) == 10 and listed == phone_digits(phone):
        return "phone"
    return None
