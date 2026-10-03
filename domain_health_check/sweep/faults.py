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
    "robots-error",  # robots.txt answers 5xx or 429, so Google stops crawling
    "google-blocked",  # robots.txt keeps Google off the home page
    "staging-link",  # a live link points at a temporary development address
    "placeholder",  # template placeholders showing on the live page
    "no-viewport",  # no mobile layout at all
    "builder-host",  # the live site is on a free builder subdomain
    "demo-images",  # the template's demo or stock pictures
    "contact-form",  # a contact form with nowhere to send messages
    "stale-copyright",  # copyright year two or more years behind
)


def rank(fault: Fault) -> int:
    return RANK.index(fault.code)


def evaluate_visit(visit: Visit, year: int) -> list[Fault]:
    """Every fault one visit shows, most damaging first."""
    faults: list[Fault] = []
    if visit.failure == "nxdomain":
        faults.append(nxdomain(visit.url))
    elif visit.failure == "certificate":
        faults.append(certificate(visit.url, visit.detail))
    if visit.robots:
        faults.extend(evaluate_robots(visit.robots))
    if visit.page and hosts.kind(visit.page.final_url) != "third-party":
        faults.extend(evaluate_page(visit.page, year))
    return sorted(faults, key=rank)


def evaluate_page(page: Page, year: int) -> list[Fault]:
    tree = HTMLParser(page.html)
    found = [
        staging_links(tree, page.final_url),
        placeholders(tree, page.rendered),
        missing_viewport(tree),
        builder_host(page.final_url),
        demo_images(tree, page.final_url),
        dead_contact_form(tree, page.final_url),
        stale_copyright(visible_text(tree), year),
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


def _readable_strings(tree: HTMLParser) -> list[str]:
    """Every piece of text a visitor can see or a screen reader reads: text nodes, then alt, title and
    aria-label values. Scripts and styles are left out, so template code inside them never counts."""
    visible = _visible_tree(tree)
    if visible.body is None:
        return []
    texts = [collapse(node.text(deep=False)) for node in visible.body.traverse(include_text=True)
             if node.tag == "-text"]
    for node in visible.body.traverse():
        for name in READABLE_ATTRIBUTES:
            texts.append(collapse(node.attributes.get(name)))
    return [t for t in texts if t]


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
    if robots.status == 429 or robots.status >= 500:
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

def builder_host(final_url: str) -> Fault | None:
    if not hosts.builder(final_url):
        return None
    name = hosts.host(final_url)
    return Fault("builder-host", f"Their site lives on a free builder address, {name}, not on a domain of "
                                 "their own.", quote=name)


# A {{name}} that a template engine never filled in. Inside script or style it is code, not a placeholder.
CURLY = re.compile(r"\{\{\s*[^{}<>\n]{1,80}?\s*\}\}")
# Labels website vendors put where the owner's content was meant to go, matched as a whole string.
VENDOR_LABELS = ("main dish image", "restaurant about us section image", "shop photo", "cat-landing",
                 "core page")
LOREM = re.compile(r"(?i)\blorem ipsum\b[^.]{0,40}")
# Before scripts run, these frameworks leave {{ }} in the HTML on purpose and fill it in the browser.
CLIENT_TEMPLATES = re.compile(r"(?i)\b(ng-app|ng-version|v-cloak|v-app|x-data|data-ng-[a-z]+)\b")


def placeholders(tree: HTMLParser, rendered: bool) -> Fault | None:
    strings = _readable_strings(tree)
    curly_allowed = rendered or not CLIENT_TEMPLATES.search(tree.html or "")
    curly = [m for s in strings for m in CURLY.findall(s)] if curly_allowed else []
    if curly:
        distinct = list(dict.fromkeys(curly))
        shown = " and ".join(f"\"{c}\"" for c in distinct[:2])
        more = f", in {len(curly)} places in all" if len(curly) > min(len(distinct), 2) else ""
        return Fault("placeholder", f"The live home page shows unfinished template code to visitors: {shown}{more}.",
                     quote=distinct[0])
    labels = list(dict.fromkeys(s for s in strings if s.lower() in VENDOR_LABELS))
    if labels:
        shown = " and ".join(f"\"{label}\"" for label in labels[:2])
        noun = "labels" if len(labels) > 1 else "label"
        return Fault("placeholder", f"The live home page still carries the template's own {noun} {shown}.",
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


# Copyright 2019, (c) 2015-2024, © 2024 and so on. In a range, the year that counts is the last one.
COPYRIGHT = re.compile(
    r"(?i)(?:©|\(c\)|copyright)\s*(?:©\s*)?(?:(?:19|20)\d{2}\s*(?:-|–|—|to)\s*)?((?:19|20)\d{2})\b")


def stale_copyright(text: str, year: int) -> Fault | None:
    """A copyright year two or more years behind. A page with several copyright lines (the theme's and the
    business's) is judged on the latest, and a page with none says nothing either way."""
    found = [(int(m.group(1)), collapse(m.group(0))) for m in COPYRIGHT.finditer(text)]
    if not found:
        return None
    latest, quote = max(found)
    if year - latest < 2:
        return None
    return Fault("stale-copyright", f"The copyright line on the home page reads \"{quote}\".", quote=quote)


# Lazy-loading plugins put a placeholder in src and the real address in one of these.
IMAGE_SOURCES = ("src", "data-src", "data-lazy-src", "data-original", "data-lazy")
SRCSETS = ("srcset", "data-srcset")
CSS_URL = re.compile(r"url\(\s*['\"]?([^'\")]+)['\"]?\s*\)")
PHOTO = re.compile(r"(?i)\.(jpe?g|webp|png)(\b|$)")
STOCK_FOLDERS = {"stock", "stock-photos", "stock-images", "demo", "demos", "demo-content", "demo-data",
                 "demo-images", "dummy", "dummy-content", "dummy-images", "sample-data"}
PLACEHOLDER_FOLDERS = {"placeholder", "placeholders"}
WIX_STOCK = ("11062b_", "nsplsh_")  # Wix's own media library and its Unsplash imports


def images(tree: HTMLParser, page_url: str) -> list[list[str]]:
    """Every image on the page, each as the real addresses it can load from: the lazy-load attributes
    before src (a data: URI in src is a placeholder, not the picture), every size in its srcset, and the
    sources of its <picture>. A CSS background image is one image. Counted per image, not per address."""
    def resolve(values) -> list[str]:
        out = []
        for value in values:
            value = (value or "").strip()
            if value and not value.startswith("data:"):
                out.append(urljoin(page_url, value))
        return out

    def srcset(node: Node) -> list[str]:
        return [c.strip().split(" ")[0] for key in SRCSETS for c in (node.attributes.get(key) or "").split(",")
                if c.strip()]

    found: list[list[str]] = []
    for img in tree.css("img"):
        lazy = [img.attributes.get(k) for k in IMAGE_SOURCES[1:] if img.attributes.get(k)]
        addresses = lazy[:1] or [img.attributes.get("src")]
        addresses += srcset(img)
        if img.parent is not None and img.parent.tag == "picture":
            addresses += [a for source in img.parent.css("source") for a in srcset(source)]
        resolved = list(dict.fromkeys(resolve(addresses)))
        if resolved:
            found.append(resolved)
    for node in tree.css("[style]"):
        found.extend([address] for address in resolve(
            m.group(1) for m in CSS_URL.finditer(node.attributes.get("style") or "")))
    return found


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


def demo_images(tree: HTMLParser, page_url: str) -> Fault | None:
    every = images(tree, page_url)
    demo_hosts = [next(h for h in hits if h) for hits in
                  ([_vendor_demo_host(a, page_url) for a in image] for image in every) if any(hits)]
    if demo_hosts:
        name = max(set(demo_hosts), key=demo_hosts.count)
        return Fault("demo-images", f"The home page is still showing the theme vendor's demo pictures, "
                                    f"{len(demo_hosts)} of its {len(every)} images served from {name}.",
                     quote=name)
    stock = [next(a for a in image if _stock(a)) for image in every if any(_stock(a) for a in image)]
    if stock:
        example = _shorten(hosts.host(stock[0]) + urlsplit(stock[0]).path)
        return Fault("demo-images", f"{len(stock)} of the {len(every)} images on the home page are the website "
                                    f"builder's stock pictures, for example \"{example}\".", quote=stock[0])
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


# Form tools that submit with a script, whatever the action attribute says.
SCRIPTED_FORM = re.compile(
    r"(?i)wpcf7|wpforms|gform|elementor|hs-form|hbspt|ninja|nf-form|formidable|frm_|fluentform|forminator|"
    r"w-form|wix|sqs|squarespace|mc4wp|mailchimp|jotform|et_pb|fusion-form|caldera|happyforms|kadence|ajax|"
    r"netlify|formspree|getform|wsform|contact-form|data-wf-|turnstile")


def _attributes(node: Node) -> str:
    return " ".join(f"{k}={v or ''}" for k, v in node.attributes.items())


def dead_contact_form(tree: HTMLParser, page_url: str) -> Fault | None:
    """A contact form (it asks for a message or an email address) whose action is missing, empty, "#",
    or this same page by GET. A form that posts back to its own page is a normal server-side pattern and is
    left alone, as is any form a known form tool submits with a script."""
    for form in tree.css("form"):
        if not form.css_first("textarea, input[type=email]"):
            continue
        if (form.attributes.get("role") or "").lower() == "search" or form.css_first("input[type=search]"):
            continue
        wrapper = _attributes(form.parent) if form.parent is not None else ""
        if "onsubmit" in form.attributes or SCRIPTED_FORM.search(f"{_attributes(form)} {wrapper}"):
            continue
        if "action" not in form.attributes:
            return Fault("contact-form", "The contact form on the home page has no address to send messages to: "
                                         "its form tag has no action at all.", quote="<form>", selector="form")
        action = (form.attributes.get("action") or "").strip()
        method = (form.attributes.get("method") or "get").strip().lower()
        if action in ("", "#") or action.startswith("#") or (method == "get" and _same_page(
                urljoin(page_url, action), page_url)):
            return Fault("contact-form", "The contact form on the home page has no address to send messages to: "
                                         f"its form tag reads action=\"{action}\".", quote=f"action=\"{action}\"",
                         selector="form")
    return None
