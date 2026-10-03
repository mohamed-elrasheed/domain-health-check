"""Whose address is it? Getting this right is what separates "none" from "weak".

A Facebook page, a Fresha or Booksy booking link, a DoorDash store or a scraper's listing page is not a
site the business owns, however much it looks like one. A free builder subdomain (name.wixsite.com) is
one they made and control, just not on a domain of their own, so it counts as a site with a fault.
"""

from __future__ import annotations

from urllib.parse import urlsplit

# Platforms whose pages a business can have but never owns. Matched as the host or any parent of it.
THIRD_PARTY = (
    # social
    "facebook.com", "fb.com", "fb.me", "instagram.com", "tiktok.com", "youtube.com", "x.com", "twitter.com",
    "linkedin.com", "pinterest.com", "nextdoor.com", "linktr.ee", "wa.me",
    # booking
    "fresha.com", "booksy.com", "vagaro.com", "styleseat.com", "schedulicity.com", "setmore.com",
    "squareup.com", "glossgenius.com", "schedulista.com", "acuityscheduling.com", "opentable.com", "resy.com",
    # food ordering
    "doordash.com", "grubhub.com", "ubereats.com", "seamless.com", "postmates.com", "netwaiter.com",
    "toasttab.com", "order.online", "menufy.com", "chownow.com", "slicelife.com", "beyondmenu.com",
    "clover.com", "allmenus.com", "menupages.com", "restaurantji.com", "restaurantguru.com", "sirved.com",
    "zmenu.com",
    # reviews and directories
    "yelp.com", "birdeye.com", "google.com", "g.page", "goo.gl", "maps.app.goo.gl", "apple.com", "bing.com",
    "mapquest.com", "tripadvisor.com", "thumbtack.com", "homeadvisor.com", "angi.com", "angieslist.com",
    "bbb.org", "yellowpages.com", "manta.com", "alignable.com", "chamberofcommerce.com", "houzz.com",
    "porch.com", "bark.com", "carfax.com", "mechanicadvisor.com", "edan.io", "waze.com",
)

# Free website builders. A live site on one of these is the business's own work on someone else's domain.
BUILDERS = (
    "wixsite.com", "mechanicnet.com", "business.site", "godaddysites.com", "squarespace.com",
    "weebly.com", "wordpress.com", "square.site", "webflow.io", "carrd.co", "site123.me", "jimdosite.com",
    "mystrikingly.com", "ueniweb.com",
)


def host(url: str) -> str:
    if "//" not in url:
        url = f"https://{url}"
    return (urlsplit(url).hostname or "").lower().rstrip(".")


def _under(name: str, suffixes: tuple[str, ...]) -> str | None:
    """The suffix name is, or is a subdomain of, if any."""
    return next((s for s in suffixes if name == s or name.endswith(f".{s}")), None)


def builder(url: str) -> str | None:
    """The free builder the address is a subdomain of, if any."""
    name = host(url)
    if name == "sites.google.com":  # Google Sites puts every site under one host, by path
        return name
    found = _under(name, BUILDERS)
    return found if found and name != found and name != f"www.{found}" else None


def kind(url: str) -> str:
    """"owned" (a domain that could be theirs), "builder" (a free builder subdomain) or "third-party"."""
    name = host(url)
    if not name:
        return "third-party"
    if builder(url):
        return "builder"
    if _under(name, THIRD_PARTY):
        return "third-party"
    return "owned"


def same_site(a: str, b: str) -> bool:
    """Whether two URLs or hosts are the same site, treating www.example.com and example.com as one."""
    def bare(value: str) -> str:
        return host(value).removeprefix("www.")
    return bare(a) == bare(b) != ""
