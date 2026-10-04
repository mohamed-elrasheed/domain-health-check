"""The faults sweep can name, each a pure function of what one visit saw.

Every detector here was written for a fault first found by hand on a real local business site. They take
the robots.txt and the home page we already have and make no requests, so tests run them on handwritten
HTML. Each returns a Fault whose sentence states what we found and quotes it. No adjectives, no advice:
the quote does the work.

RANK orders them by how much each costs the business. A sweep reports only the first one it finds.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser, Node

from .. import robots as robots_txt
from . import hosts
from .models import Fault, Page, Robots, Visit

RANK = (
    "nxdomain",  # the listed address leads nowhere
    "certificate",  # visitors get a browser security warning
    "robots-error",  # robots.txt answers 5xx, so Google stops crawling
    "google-blocked",  # robots.txt keeps Google off the home page
    "staging-link",  # a live link points at a temporary development address
    "placeholder",  # template placeholders showing on the live page
    "no-viewport",  # no mobile layout at all
    "builder-host",  # the live site is on a free builder subdomain
    "demo-images",  # the template's demo or stock pictures
    "stock-photos",  # no photo of their own anywhere: found by hand, since no detector can tell
    "contact-form",  # a contact form with nowhere to send messages
    "free-mail",  # a Gmail, Yahoo, AOL or Hotmail contact address on a site with its own domain
    "email-mismatch",  # a contact address on a different domain from the site
    "weekday-typo",  # a misspelled day in the business hours
    "stale-copyright",  # copyright year two or more years behind
    "hidden-label",  # a template label only in alt, title or aria-label: real, but nobody sees it
)


# Real, and worth knowing, but not a website job: a business email setup, a tune-up. These never change the
# verdict, which answers one question only (is there a website job here). They are reported as flags, and a
# good site with flags is its own list: the rung between the free report and a new website.
FLAGS = frozenset({"free-mail", "email-mismatch", "weekday-typo", "stale-copyright"})


def rank(fault: Fault) -> int:
    """Position in RANK. A hand-found fault with a code RANK does not know goes after every known one."""
    return RANK.index(fault.code) if fault.code in RANK else len(RANK)


def evaluate_visit(visit: Visit, year: int, hidden: frozenset[str] = frozenset(), business: str = ""
                   ) -> list[Fault]:
    """Every fault one visit shows, most damaging first. hidden holds strings a browser found in the page but
    not on screen (covered, clipped, scrolled out of reach); they never count as something visitors see."""
    faults: list[Fault] = []
    if visit.failure == "nxdomain":
        faults.append(nxdomain(visit.url))
    elif visit.failure == "certificate":
        faults.append(certificate(visit.url, visit.detail))
    if visit.robots:
        faults.extend(evaluate_robots(visit.robots))
    if visit.page and hosts.kind(visit.page.final_url) != "third-party":
        faults.extend(evaluate_page(visit.page, year, hidden, business))
    return sorted(faults, key=rank)


def evaluate_page(page: Page, year: int, hidden: frozenset[str] = frozenset(), business: str = "") -> list[Fault]:
    """Every fault on the home page. business is the name on the lead, used to tell the business's own
    copyright line from a vendor's."""
    tree = HTMLParser(page.html)
    # What the browser actually displayed, when we have it. Text that is in the page but hidden (display:
    # none, a collapsed block) is delivered, not seen, and a sentence that says visitors see it must be true.
    shown = collapse(page.visible_text) if page.rendered and page.visible_text else None
    text = shown if shown is not None else visible_text(tree)
    found = [
        staging_links(tree, page.final_url),
        placeholders(tree, page.rendered, shown, hidden),
        missing_viewport(tree),
        builder_host(page.final_url, text, business, hidden),
        demo_images(tree, page.final_url),
        dead_contact_form(tree, page.final_url),
        free_mail(tree, page.final_url, text, hidden),
        email_mismatch(tree, page.final_url, text, hidden),
        misspelled_weekday(text, hidden),
        stale_copyright(text, year),
    ]
    return sorted((f for f in found if f), key=rank)


# ---------- reading the page

INVISIBLE = ["script", "style", "template", "noscript", "svg"]
READABLE_ATTRIBUTES = ("alt", "title", "aria-label")


def collapse(text: str | None) -> str:
    return " ".join((text or "").split())


def _visible_tree(tree: HTMLParser) -> HTMLParser:
    copy = HTMLParser(tree.html or "")
    copy.strip_tags(INVISIBLE)
    return copy


def visible_text(tree: HTMLParser) -> str:
    visible = _visible_tree(tree)
    return collapse(visible.body.text(separator=" ")) if visible.body else ""


def _readable_strings(tree: HTMLParser, shown: str | None = None) -> tuple[list[str], list[str]]:
    """(text a visitor sees, alt/title/aria-label values a screen reader or search engine reads). Scripts and
    styles are left out, so template code inside them never counts. Given shown, the text the browser
    displayed, a text node counts only if it appears there: hidden text is not text a visitor sees."""
    visible = _visible_tree(tree)
    if visible.body is None:
        return [], []
    texts = [collapse(node.text(deep=False)) for node in visible.body.traverse(include_text=True)
             if node.tag == "-text"]
    shown = shown.lower() if shown is not None else None  # text-transform changes case, not content
    texts = [t for t in texts if t and (shown is None or t.lower() in shown)]
    labels = [collapse(node.attributes.get(name)) for node in visible.body.traverse() for name in READABLE_ATTRIBUTES]
    return texts, [t for t in labels if t]


def _same_page(url: str, page_url: str) -> bool:
    def bare(value: str) -> str:
        parts = urlsplit(value)
        return urlunsplit((parts.scheme, (parts.hostname or "").removeprefix("www."), parts.path or "/", "", ""))
    return bare(url) == bare(page_url)


def _shorten(text: str, limit: int = 70) -> str:
    return text if len(text) <= limit else text[:limit - 3].rstrip() + "..."


# ---------- before the page: the listed address and robots.txt

def nxdomain(url: str) -> Fault:
    name = hosts.host(url)
    return Fault("nxdomain", f"The address in their listings, {name}, does not exist, so anyone who clicks it "
                             "reaches an error instead of their business.", quote=name)


# What a browser shows as a full-page security warning. Anything else our client could not verify (a missing
# intermediate certificate, say) a browser may well accept, so load.py records it as unverified instead.
CERTIFICATE_WARNINGS = {
    "expired": "has expired", "not yet valid": "is not valid yet", "self-signed": "is self-signed",
    "self signed": "is self-signed", "hostname mismatch": "is for a different address",
    "doesn't match": "is for a different address", "does not match": "is for a different address",
}


def certificate(url: str, detail: str) -> Fault:
    reason = next((words for key, words in CERTIFICATE_WARNINGS.items() if key in detail.lower()),
                  "is not trusted")
    name = hosts.host(url)
    return Fault("certificate", f"Visitors to {name} get a browser security warning before the page opens, "
                                f"because its certificate {reason}.", quote=detail)


def evaluate_robots(robots: Robots) -> list[Fault]:
    """A 5xx robots.txt and a Disallow that keeps Google off the home page. A 429 is not here: it answers the
    client that asked, so all it shows is that the site rate-limited us, not what it tells Google."""
    if robots.status >= 500:
        return [Fault("robots-error", f"Their robots.txt file answers with a server error (HTTP {robots.status}), "
                                      "and Google stops crawling the whole site while it does.",
                      quote=f"HTTP {robots.status}")]
    if 200 <= robots.status < 300:
        rule = robots_txt.blocking_rule(robots.text, "googlebot", "/")
        if rule:
            return [Fault("google-blocked", f"Their robots.txt file tells Google not to read the home page: "
                                            f"\"{rule}\".", quote=rule)]
    return []


# ---------- on the page

def builder_host(final_url: str, text: str = "", business: str = "",
                 hidden: frozenset[str] = frozenset()) -> Fault | None:
    """A live site on a free builder subdomain. When the page's copyright line names someone else, which on
    a builder is the vendor, the sentence quotes that too: the site does not even carry their name."""
    if not hosts.builder(final_url):
        return None
    name = hosts.host(final_url)
    line = vendor_copyright(text, business)
    if line and line not in hidden:
        return Fault("builder-host", f"Their site lives on a free builder address, {name}, and its footer copyright "
                                     f"reads \"{line}\", not their own name.", quote=line, on_screen=True)
    return Fault("builder-host", f"Their site lives on a free builder address, {name}, not on a domain of "
                                 "their own.", quote=name)


# Words that say what a business does rather than who it is, so they cannot identify its copyright line.
GENERIC_NAME_WORDS = {
    "the", "and", "of", "llc", "inc", "co", "company", "group", "auto", "automotive", "care", "repair",
    "service", "services", "center", "centre", "shop", "motors", "garage", "barber", "barbers", "barbershop",
    "grooming", "hair", "salon", "cleaning", "clean", "maid", "maids", "lawn", "landscaping", "landscape",
    "tree", "mowing", "kitchen", "cafe", "restaurant", "bakery", "pizza", "grill", "bbq", "korean", "thai",
}
COPYRIGHT_LINE = re.compile(r"(?i)(?:©|\(c\)|copyright)\s*[^|]{0,80}?(?=\s*(?:all rights|\||$|\.\s))")


def distinctive_words(business: str) -> set[str]:
    """The words in a business name that identify it: "example" in "Example Auto Care", not "auto" or "care"."""
    words = {w for w in re.findall(r"[a-z0-9]+", business.lower().replace("'", "")) if len(w) >= 3}
    return words - GENERIC_NAME_WORDS


def vendor_copyright(text: str, business: str) -> str | None:
    """The page's copyright line when it never names the business, or None. Judged only when the name has
    a distinctive word to look for."""
    distinctive = distinctive_words(business)
    if not distinctive:
        return None
    lines = [collapse(m.group(0)).rstrip(" ,.-") for m in COPYRIGHT_LINE.finditer(text)]
    lines = [line for line in lines if re.search(r"(19|20)\d{2}", line)]
    if not lines or any(w in line.lower().replace("'", "") for line in lines for w in distinctive):
        return None
    return lines[-1]


# A {{name}} that a template engine never filled in. Inside script or style it is code, not a placeholder.
CURLY = re.compile(r"\{\{\s*[^{}<>\n]{1,80}?\s*\}\}")
# Labels website vendors put where the owner's content was meant to go, matched as a whole string.
VENDOR_LABELS = ("main dish image", "restaurant about us section image", "shop photo", "cat-landing",
                 "core page")
LOREM = re.compile(r"(?i)\blorem ipsum\b[^.]{0,40}")
# Before scripts run, these frameworks leave {{ }} in the HTML on purpose and fill it in the browser.
CLIENT_TEMPLATES = re.compile(r"(?i)\b(ng-app|ng-version|v-cloak|v-app|x-data|data-ng-[a-z]+)\b")


def placeholders(tree: HTMLParser, rendered: bool, shown: str | None = None,
                 hidden: frozenset[str] = frozenset()) -> Fault | None:
    texts, labels_read = _readable_strings(tree, shown)
    strings = texts + labels_read
    curly_allowed = rendered or not CLIENT_TEMPLATES.search(tree.html or "")
    # The sentence says visitors see this code, so only displayed text counts, never an attribute.
    curly = [m for s in texts for m in CURLY.findall(s) if m not in hidden] if curly_allowed else []
    if curly:
        distinct = list(dict.fromkeys(curly))
        shown = " and ".join(f"\"{c}\"" for c in distinct[:2])
        more = f", in {len(curly)} places in all" if len(curly) > min(len(distinct), 2) else ""
        return Fault("placeholder", f"The live home page shows unfinished template code to visitors: {shown}{more}.",
                     quote=distinct[0], on_screen=True)
    displayed = list(dict.fromkeys(s for s in texts if s.lower() in VENDOR_LABELS and s not in hidden))
    labels = displayed or list(dict.fromkeys(s for s in labels_read if s.lower() in VENDOR_LABELS))
    labels = [label for label in labels if label not in hidden] if displayed else labels
    if labels:
        quoted = " and ".join(f"\"{label}\"" for label in labels[:2])
        noun = "labels" if len(labels) > 1 else "label"
        if displayed:
            return Fault("placeholder", f"The live home page still shows the template's own {noun} {quoted}.",
                         quote=labels[0], on_screen=True)
        # Only in alt, title or aria-label: real, but not on screen, and the sentence must not imply it is.
        return Fault("hidden-label", f"The live home page still carries the template's own {noun} {quoted} in "
                                    "its hidden image and link descriptions, which screen readers read aloud.",
                     quote=labels[0])
    lorem = next((m.group(0).strip() for s in strings for m in [LOREM.search(s)] if m), None)
    if lorem:
        return Fault("placeholder", f"The live home page still carries the template's filler text "
                                    f"\"{_shorten(lorem, 50)}\".", quote="Lorem ipsum")
    return None


def missing_viewport(tree: HTMLParser) -> Fault | None:
    if any((node.attributes.get("name") or "").strip().lower() == "viewport" for node in tree.css("meta[name]")):
        return None
    if tree.body is None or not visible_text(tree):
        return None  # nothing to lay out; an empty shell is not evidence of anything
    return Fault("no-viewport", "The home page has no mobile layout, so a phone shows the full desktop page "
                                "shrunk to fit the screen.")


# Copyright 2019, (c) 2015-2024, © 2000-26, © 2024 and so on. In a range, the year that counts is the last
# one, and a two-digit end year belongs to the start year's century.
COPYRIGHT = re.compile(
    r"(?i)(?:©|\(c\)|copyright)\s*(?:©\s*)?(?:((?:19|20)\d{2})\s*(?:-|–|—|to)\s*)?((?:19|20)\d{2}|\d{2})\b")


def _copyright_year(match: re.Match) -> int | None:
    start, end = match.group(1), match.group(2)
    if len(end) == 4:
        return int(end)
    return int(start[:2] + end) if start else None  # "© 26" alone is not a year we can read


def stale_copyright(text: str, year: int) -> Fault | None:
    """A copyright year two or more years behind. A page with several copyright lines (the theme's and the
    business's) is judged on the latest, and a page with none says nothing either way."""
    found = [(y, collapse(m.group(0))) for m in COPYRIGHT.finditer(text) if (y := _copyright_year(m))]
    if not found:
        return None
    latest, quote = max(found)
    if year - latest < 2:
        return None
    return Fault("stale-copyright", f"The copyright line on the home page reads \"{quote}\".", quote=quote)


FREE_MAIL = {"gmail.com": "Gmail", "yahoo.com": "Yahoo", "aol.com": "AOL", "hotmail.com": "Hotmail"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")


# Addresses that are never a business's contact: placeholders, and the platforms' own error reporting.
NOT_CONTACT_DOMAINS = {"example.com", "example.org", "example.net", "domain.com", "yourdomain.com", "mysite.com",
                       "email.com", "company.com", "sentry.io", "wixpress.com", "godaddy.com", "squarespace.com",
                       "wix.com"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg")  # logo@2x.png looks like an address


def contact_addresses(tree: HTMLParser, text: str, hidden: frozenset[str] = frozenset()) -> list[tuple[str, bool]]:
    """(address, shown on the page) for every contact address: the ones in the text first, then mailto
    links, which count even when their text only says "Email us"."""
    shown = [a for a in EMAIL.findall(text) if a not in hidden]
    linked = [(node.attributes.get("href") or "")[7:].split("?")[0].strip()
              for node in tree.css('a[href^="mailto:"]')]
    found = [(a, True) for a in shown] + [(a, False) for a in linked]
    return [(a, on_screen) for a, on_screen in found if "@" in a and not a.lower().endswith(IMAGE_SUFFIXES)
            and a.rsplit("@", 1)[-1].lower() not in NOT_CONTACT_DOMAINS]


def email_mismatch(tree: HTMLParser, page_url: str, text: str, hidden: frozenset[str] = frozenset()
                   ) -> Fault | None:
    """A contact address on a domain other than the site's: two identities where there should be one.
    Free webmail is free_mail's finding, not this one."""
    if hosts.kind(page_url) != "owned":
        return None
    site = hosts.host(page_url).removeprefix("www.")
    for address, on_screen in contact_addresses(tree, text, hidden):
        domain = address.rsplit("@", 1)[-1].lower()
        if domain in FREE_MAIL or domain == site or domain.endswith(f".{site}") or site.endswith(f".{domain}"):
            continue
        return Fault("email-mismatch", f"The contact address on the home page is \"{address}\", on {domain}, a "
                                       f"different domain from the site, {site}.", quote=address,
                     on_screen=on_screen, selector="" if on_screen else f'a[href^="mailto:{address}"]')
    return None


def free_mail(tree: HTMLParser, page_url: str, text: str, hidden: frozenset[str] = frozenset()) -> Fault | None:
    """A free webmail contact address on a site that has its own domain: the domain is already paid for,
    and the address that could carry it does not."""
    if hosts.kind(page_url) != "owned":
        return None
    site = hosts.host(page_url).removeprefix("www.")
    for address, on_screen in contact_addresses(tree, text, hidden):
        provider = FREE_MAIL.get(address.rsplit("@", 1)[-1].lower())
        if provider:
            return Fault("free-mail", f"The contact address on the home page is \"{address}\", a free {provider} "
                                      f"address, on a site that has its own domain, {site}.", quote=address,
                         on_screen=on_screen, selector="" if on_screen else f'a[href^="mailto:{address}"]')
    return None


WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
# Real words close enough to a weekday to look like a typo of one.
NOT_WEEKDAY_TYPOS = {"today", "someday", "holiday", "holidays", "birthday", "payday", "midday", "everyday",
                     "weekday", "weekdays", "workday", "doomsday", "heyday", "mayday", "sundae", "sundry", "sunny",
                     "monkey", "saturn", "friendly", "thirsty", "tuesdays", "monday's"}
HOURS_CONTEXT = re.compile(r"(?i)\b\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|\b\d{1,2}:\d{2}\b|\bclosed\b")


def _distance(a: str, b: str) -> int:
    """Levenshtein distance."""
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        previous, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (ca != cb))
    return row[-1]


def misspelled_weekday(text: str, hidden: frozenset[str] = frozenset()) -> Fault | None:
    """A capitalized word within two letters of a weekday, starting with the same letter, sitting among
    business hours (a time, "closed", or another day within 80 characters)."""
    for match in re.finditer(r"\b[A-Z][A-Za-z]{4,10}\b", text):
        word = match.group(0)
        lower = word.lower()
        if lower in WEEKDAYS or lower in NOT_WEEKDAY_TYPOS or lower.rstrip("s") in WEEKDAYS or word in hidden:
            continue
        day = next((d for d in WEEKDAYS if d[0] == lower[0] and abs(len(d) - len(lower)) <= 2
                    and _distance(lower, d) <= 2), None)
        if day is None:
            continue
        window = text[max(0, match.start() - 80):match.end() + 80]
        if not (HOURS_CONTEXT.search(window) or any(d in window.lower() for d in WEEKDAYS if d != day)):
            continue
        return Fault("weekday-typo", f"The business hours on the home page spell {day.capitalize()} as "
                                     f"\"{word}\".", quote=word, on_screen=True)
    return None


# Lazy-loading plugins put a placeholder in src and the real address in one of these.
IMAGE_SOURCES = ("src", "data-src", "data-lazy-src", "data-original", "data-lazy")
SRCSETS = ("srcset", "data-srcset")
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
PHOTO = re.compile(r"(?i)\.(jpe?g|webp|png)(\b|$)")
STOCK_FOLDERS = {"stock", "stock-photos", "stock-images", "demo", "demos", "demo-content", "demo-data",
                 "demo-images", "dummy", "dummy-content", "dummy-images", "sample-data",
                 "getty", "istock", "shutterstock", "adobestock"}  # builder libraries, e.g. /isteam/getty/<id>
PLACEHOLDER_FOLDERS = {"placeholder", "placeholders"}
WIX_STOCK = ("11062b_", "nsplsh_")  # Wix's own media library and its Unsplash imports


# Not a picture of anything: fonts, icons, logos, spacers, maps.
NOT_A_PICTURE = re.compile(r"(?i)(\.(svg|gif|ico|woff2?|ttf|otf|eot)$|logo|icon|favicon|sprite|spacer|blank|"
                           r"transparent)")


def picture_key(url: str) -> str:
    """One key per picture, however many sizes it is served in: no query, and no resizing instructions
    (builders put them after "/:/" or "/v1/")."""
    parts = urlsplit(url)
    path = re.split(r"/:/|/v1/", parts.path, maxsplit=1)[0]
    return f"{(parts.hostname or '').lower()}{path}"


def _not_a_picture(url: str) -> bool:
    parts = urlsplit(url)
    return bool(NOT_A_PICTURE.search(parts.path.rstrip("/").rsplit("/", 1)[-1])) or \
        (parts.hostname or "").endswith("maps.googleapis.com")


def images(tree: HTMLParser, page_url: str) -> list[list[str]]:
    """Every distinct picture on the page, each as the addresses it loads from. For an <img> that means the
    lazy-load attributes before src (a data: URI in src is a placeholder, not the picture), every size in its
    srcset and the sources of its <picture>. Backgrounds count too, from style attributes and from <style>
    blocks, where builders put their hero images. The same picture at several sizes counts once."""
    pictures: dict[str, list[str]] = {}

    def add(values) -> None:
        resolved = [urljoin(page_url, v.strip()) for v in values if v and v.strip() and
                    not v.strip().startswith("data:")]
        resolved = [u for u in resolved if not _not_a_picture(u)]
        if resolved:
            known = pictures.setdefault(picture_key(resolved[0]), [])
            known.extend(u for u in resolved if u not in known)

    def srcset(node: Node) -> list[str]:
        return [c.strip().split(" ")[0] for key in SRCSETS for c in (node.attributes.get(key) or "").split(",")
                if c.strip()]

    for img in tree.css("img"):
        lazy = [img.attributes.get(k) for k in IMAGE_SOURCES[1:] if img.attributes.get(k)]
        addresses = (lazy[:1] or [img.attributes.get("src")]) + srcset(img)
        if img.parent is not None and img.parent.tag == "picture":
            addresses += [a for source in img.parent.css("source") for a in srcset(source)]
        add(addresses)
    css = [node.attributes.get("style") or "" for node in tree.css("[style]")]
    css += [node.text() for node in tree.css("style")]
    for block in css:
        for match in CSS_URL.finditer(block):
            add([match.group(1)])
    return list(pictures.values())


def _vendor_demo_host(url: str, page_url: str) -> str | None:
    name = hosts.host(url)
    if name and not hosts.same_site(name, page_url) and any(
            "demo" in label or "theme" in label for label in name.split(".")[:-1]):
        return name
    return None


def _stock(url: str) -> bool:
    parts = urlsplit(url)
    segments = [s.lower() for s in parts.path.split("/") if s]
    folders = segments[:-1]
    if any(s in STOCK_FOLDERS for s in folders):
        return True
    if any(s in PLACEHOLDER_FOLDERS for s in folders) and PHOTO.search(parts.path):
        return True
    return hosts.host(url).endswith("wixstatic.com") and any(
        s.startswith(WIX_STOCK) and PHOTO.search(s) for s in segments)


def _some_of(n: int, total: int) -> tuple[str, str]:
    """("2 of the 5 images on the home page", "are"), with "all" and "the one" where they read better."""
    if total == 1:
        return "The one image on the home page", "is"
    if n == total:
        return f"All {total} images on the home page", "are"
    return f"{n} of the {total} images on the home page", "is" if n == 1 else "are"


def demo_images(tree: HTMLParser, page_url: str) -> Fault | None:
    """Pictures the owner never replaced. Any image served from the theme vendor's own demo site counts:
    nobody chooses to hotlink a vendor's demo server. A builder's stock library is different, since owners
    pick a stock picture on purpose, so it counts only when stock makes up at least half the pictures."""
    every = images(tree, page_url)
    demo = []
    for image in every:
        found = next((h for h in (_vendor_demo_host(a, page_url) for a in image) if h), None)
        if found:
            demo.append(found)
    if demo:
        name = max(set(demo), key=demo.count)
        subject, verb = _some_of(len(demo), len(every))
        return Fault("demo-images", f"{subject} {verb} still served from the theme vendor's demo site, {name}.",
                     quote=name)
    stock = [next(a for a in image if _stock(a)) for image in every if any(_stock(a) for a in image)]
    if stock and 2 * len(stock) >= len(every):
        subject, verb = _some_of(len(stock), len(every))
        example = _shorten(picture_key(stock[0]))
        return Fault("demo-images", f"{subject} {verb} from the website builder's stock library, for example "
                                    f"\"{example}\".", quote=stock[0])
    return None


# Hosts that only ever serve a site while it is being built.
STAGING_SUFFIXES = ("temporary.site", "mystagingwebsite.com", "wpengine.com", "flywheelstaging.com",
                    "flywheelsites.com", "kinsta.cloud", "ngrok.io", "ngrok-free.app", "ngrok.app", "dev.cc")
STAGING_PREFIXES = ("staging.", "staging-", "stage.", "dev.", "test.")
LOCAL_SUFFIXES = (".local", ".test", ".localhost")


def staging_host(url: str) -> str | None:
    name = hosts.host(url)
    if not name:
        return None
    if name in ("localhost", "127.0.0.1") or name.endswith(LOCAL_SUFFIXES):
        return name
    if any(name == s or name.endswith(f".{s}") for s in STAGING_SUFFIXES):
        return name
    if name.startswith(STAGING_PREFIXES) and name.count(".") >= 2:
        return name
    return None


def staging_links(tree: HTMLParser, page_url: str) -> Fault | None:
    for node, attribute in [(n, "href") for n in tree.css("a[href]")] + \
                           [(n, "action") for n in tree.css("form[action]")] + \
                           [(n, "src") for n in tree.css("iframe[src]")]:
        target = urljoin(page_url, (node.attributes.get(attribute) or "").strip())
        name = staging_host(target)
        if not name or hosts.same_site(name, page_url):
            continue
        label = collapse(node.text(separator=" ")) if node.tag == "a" else ""
        label = label or collapse(node.attributes.get("aria-label") or node.attributes.get("title"))
        where = f"The \"{_shorten(label, 40)}\" link" if label else "A link"
        return Fault("staging-link", f"{where} on the home page points at {name}, a temporary development "
                                     "address, not their live site.", quote=name,
                     selector=f"{node.tag}[{attribute}*=\"{name}\"]")
    return None


def dead_contact_form(tree: HTMLParser, page_url: str) -> Fault | None:
    """A contact form (it asks for a message or an email address) with nowhere to send it: no action, an
    empty one, "#", or this same page by GET, on a page that runs no script at all.

    The last condition is the one that makes this provable. Website builders (Squarespace, GoDaddy, Wix,
    Webflow, Duda) and most hand-built forms submit with a script and carry no action, so in a rendered page
    a missing action is normal and proves nothing. Only when there is no script to pick the form up does the
    markup decide where a message goes. A form that posts back to its own page is a normal server-side
    pattern and is left alone."""
    if tree.css_first("script"):
        return None
    for form in tree.css("form"):
        if not form.css_first("textarea, input[type=email]"):
            continue
        if (form.attributes.get("role") or "").lower() == "search" or form.css_first("input[type=search]"):
            continue
        if "action" not in form.attributes:
            return Fault("contact-form", "The contact form on the home page has no address to send messages to: "
                                         "its form tag has no action at all, and the page runs no script that "
                                         "could send it.", quote="<form>", selector="form")
        action = (form.attributes.get("action") or "").strip()
        method = (form.attributes.get("method") or "get").strip().lower()
        if action in ("", "#") or action.startswith("#") or (method == "get" and _same_page(
                urljoin(page_url, action), page_url)):
            return Fault("contact-form", "The contact form on the home page has no address to send messages to: "
                                         f"its form tag reads action=\"{action}\", and the page runs no script that "
                                         "could send it.", quote=f"action=\"{action}\"", selector="form")
    return None
