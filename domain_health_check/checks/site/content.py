"""What the page says about itself: title, description, headings and image descriptions.

These are the findings an owner can usually fix from their website builder
without a developer, so the fixes say where to look.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from ...fetcher import PageContext
from ...models import SITE, CheckResult, Status
from ._html import collapse, headings, inside, meta, parse

TITLE = "Page title"
DESCRIPTION = "Meta description"
MAIN_HEADING = "Main heading"
HEADING_ORDER = "Heading order"
ALT_TEXT = "Image alt text"

TITLE_MIN, TITLE_MAX = 15, 60
DESCRIPTION_MIN, DESCRIPTION_MAX = 70, 160
ALT_TEXT_PASS_SHARE = 0.9
LISTED = 10  # how many offending items the details list before summarizing the rest

TITLE_EXPLANATION = (
    "The page title is the clickable headline shown for your site in Google search results and on the browser "
    "tab. It is often the first thing a potential customer reads about you."
)
DESCRIPTION_EXPLANATION = (
    "The meta description is the short summary Google often shows under your title in search results. A clear "
    "one or two sentences helps people decide to click."
)
MAIN_HEADING_EXPLANATION = (
    "The main heading, the largest headline on the page, tells visitors and search engines what the page is "
    "about. Search engines give it extra weight."
)
HEADING_ORDER_EXPLANATION = (
    "Search engines read your headings as an outline to understand how your content is organized, and people "
    "using screen readers move around the page by that outline."
)
ALT_TEXT_EXPLANATION = (
    "Without a written description, search engines cannot tell what your pictures show, and screen readers have "
    "nothing to read aloud to people with visual impairments. That description is called alt text. Purely "
    "decorative images can be left blank on purpose, so a few gaps can be fine."
)


def _more(items: list[str]) -> list[str]:
    return items[:LISTED] + ([f"...and {len(items) - LISTED} more"] if len(items) > LISTED else [])


# ---------- Placeholder text left over from a website template

# A right-length title or description can still be a template's demo copy: a real auto repair shop's description
# read "Take payments online with a scalable platform that grows with your perfect business" and passed on length.
DEMO_PHRASES = (
    "lorem ipsum", "just another wordpress site", "my wordpress blog", "take payments online",
    "scalable platform that grows", "your site description", "site description goes here", "your tagline here",
    "site tagline", "this is a sample", "sample page", "hello world", "add your description", "edit this text",
    "your company name", "insert text here", "this is your site", "powered by wordpress",
)
STOPWORDS = {
    "about", "also", "best", "been", "from", "have", "here", "home", "into", "just", "like", "make", "more", "need",
    "only", "other", "over", "page", "site", "some", "than", "that", "their", "them", "then", "there", "they", "this",
    "very", "website", "welcome", "were", "what", "when", "where", "which", "will", "with", "your", "yours", "ours",
    "offer", "offers", "service", "services", "official",
}
MIN_TERMS, MIN_CONTEXT = 4, 3  # below these there is too little text to judge, so nothing is flagged


def terms(text: str) -> set[str]:
    """Meaningful words, cut to five letters so "floors" and "flooring" meet."""
    return {w[:5] for w in re.findall(r"[a-z]+", text.lower()) if len(w) >= 4 and w not in STOPWORDS}


def placeholder(text: str, context: list[str], min_terms: int = MIN_TERMS) -> str | None:
    """"template" for a known demo phrase; "unrelated" when the text shares no meaningful word with the rest of
    the page (title, headings, description) and both sides have enough words to judge; otherwise None."""
    lowered = text.lower()
    if any(phrase in lowered for phrase in DEMO_PHRASES):
        return "template"
    own, around = terms(text), terms(" ".join(context))
    if len(own) >= min_terms and len(around) >= MIN_CONTEXT and not own & around:
        return "unrelated"
    return None


PLACEHOLDER_SUMMARY = {
    "template": "Your home page {what} looks like placeholder text left over from a website template, not a "
                "description of your business.",
    "unrelated": "Your home page {what} shares no words with your page's title or headings, so it may be "
                 "placeholder text rather than a description of your business.",
}


# ---------- Page title

def evaluate_title(title: str | None, final_url: str, context: list[str] = ()) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), certain: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, TITLE, status, summary, TITLE_EXPLANATION, fix, list(details), certain=certain,
                           measure=measure)

    fix = (
        "In your website builder, open the home page settings and look for \"SEO title\" or \"page title\". "
        f"Aim for {TITLE_MIN} to {TITLE_MAX} characters naming your business and what you do, for example "
        "\"Smith Plumbing, 24-hour plumber in Austin\"."
    )
    if not title:
        return result(Status.WARN, "Your home page has no title.", fix)

    details = [f"Title: {title}", f"Length: {len(title)} characters"]
    host = (urlsplit(final_url).hostname or "").removeprefix("www.")
    if title.lower().rstrip("/").removeprefix("https://").removeprefix("http://").removeprefix("www.") == host:
        return result(Status.WARN, "Your home page title is just your web address.", fix, details)
    kind = placeholder(title, list(context), min_terms=2)
    if kind:
        return result(Status.WARN, PLACEHOLDER_SUMMARY[kind].format(what="title"), fix, details,
                      certain=kind == "template")  # no shared words is a maybe; a demo phrase is not
    if len(title) < TITLE_MIN:
        return result(Status.WARN, f"Your home page title is very short ({len(title)} characters).", fix, details,
                      measure=len(title) / TITLE_MIN)  # a matter of degree, not absent
    if len(title) > TITLE_MAX:
        return result(Status.WARN, f"Your home page title is {len(title)} characters long, so Google will likely "
                                   "cut it off in search results.", fix, details, measure=TITLE_MAX / len(title))
    return result(Status.PASS, f"Your home page title is \"{title}\", a good length at {len(title)} characters.",
                  details=details)


def _headings_text(tree) -> list[str]:
    return [text for level, text in headings(tree) if level <= 3]


def check_title(page: PageContext) -> list[CheckResult]:
    tree = parse(page.html)
    node = tree.css_first("head > title")
    context = _headings_text(tree) + meta(tree, "description")
    return [evaluate_title(collapse(node.text()) if node else None, page.final_url, context)]


# ---------- Meta description

def evaluate_description(descriptions: list[str], context: list[str] = ()) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), certain: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, DESCRIPTION, status, summary, DESCRIPTION_EXPLANATION, fix, list(details),
                           certain=certain, measure=measure)

    fix = (
        "In your website builder, open the home page settings and look for \"SEO description\" or \"meta "
        f"description\". Write one or two sentences, {DESCRIPTION_MIN} to {DESCRIPTION_MAX} characters, saying "
        "what you do and where."
    )
    description = next((d for d in descriptions if d), "")
    if not description:
        return result(Status.WARN, "Your home page has no meta description, so Google picks its own text to show.",
                      fix)

    details = [f"Description: {description}", f"Length: {len(description)} characters"]
    if len(descriptions) > 1:
        details.append(f"Note: the page has {len(descriptions)} description tags; we measured the first.")
    kind = placeholder(description, list(context))
    if kind:
        return result(Status.WARN, PLACEHOLDER_SUMMARY[kind].format(what="description"), fix, details,
                      certain=kind == "template")
    if len(description) < DESCRIPTION_MIN:
        return result(Status.WARN, f"Your home page description is short ({len(description)} characters), so it "
                                   "may not tell searchers enough.", fix, details,
                      measure=len(description) / DESCRIPTION_MIN)
    if len(description) > DESCRIPTION_MAX:
        return result(Status.WARN, f"Your home page description is {len(description)} characters long, so Google "
                                   "will likely cut it off in search results.", fix, details,
                      measure=DESCRIPTION_MAX / len(description))
    return result(Status.PASS, f"Your home page description is a good length at {len(description)} characters.",
                  details=details)


def check_description(page: PageContext) -> list[CheckResult]:
    tree = parse(page.html)
    node = tree.css_first("head > title")
    context = ([collapse(node.text())] if node else []) + _headings_text(tree)
    return [evaluate_description(meta(tree, "description"), context)]


# ---------- Main heading

def evaluate_main_heading(h1_texts: list[str]) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, MAIN_HEADING, status, summary, MAIN_HEADING_EXPLANATION, fix, list(details),
                           measure=measure)

    fix = (
        "In your website builder, make sure the page has exactly one headline set as \"Heading 1\" (H1) that "
        "says what your business does. Other headlines on the page should use Heading 2 or smaller."
    )
    details = [f"Heading 1: {text or '(empty)'}" for text in h1_texts]
    if not h1_texts:
        return result(Status.WARN, "Your home page has no main heading.", fix)
    if len(h1_texts) > 1:
        return result(Status.WARN, f"Your home page has {len(h1_texts)} main headings instead of one.", fix, details,
                      measure=1 / len(h1_texts))  # there is a main heading, just not only one
    if not h1_texts[0]:
        return result(Status.WARN, "Your home page main heading is empty.", fix, details)
    return result(Status.PASS, f"Your home page has one main heading: \"{h1_texts[0]}\".", details=details)


def check_main_heading(page: PageContext) -> list[CheckResult]:
    return [evaluate_main_heading([text for level, text in headings(parse(page.html)) if level == 1])]


# ---------- Heading order

def evaluate_heading_order(levels: list[int]) -> CheckResult:
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, HEADING_ORDER, status, summary, HEADING_ORDER_EXPLANATION, fix, list(details), ran,
                           measure=measure)

    if not levels:
        return result(Status.PASS, "Your home page has no headings, so there is no order to check.", ran=False)
    skips, previous = [], None
    for position, level in enumerate(levels, start=1):
        if previous is None and level > 2:  # the first heading may be an h1 or an h2
            skips.append(f"Heading {position} of {len(levels)} is an h{level} at the start of the page, before any "
                         f"h{level - 1}")
        elif previous is not None and level > previous + 1:
            skips.append(f"Heading {position} of {len(levels)} is an h{level} directly after an h{previous}")
        previous = level
    details = [f"Order: {' '.join(f'h{level}' for level in levels)}"]
    if skips:
        noun = "place" if len(skips) == 1 else "places"
        return result(
            Status.WARN, f"Your home page skips a heading level in {len(skips)} {noun}.",
            "In your website builder, change the skipped headings so each level follows the one above it: Heading 2 "
            "under Heading 1, Heading 3 under Heading 2. The look can stay the same; only the heading level changes.",
            details + _more(skips), measure=(len(levels) - len(skips)) / len(levels),
        )
    return result(Status.PASS, f"Your {len(levels)} headings are in order, with no levels skipped.", details=details)


def check_heading_order(page: PageContext) -> list[CheckResult]:
    return [evaluate_heading_order([level for level, _ in headings(parse(page.html))])]


# ---------- Image alt text

IMAGE_FILE = re.compile(r"(?i)^[\w\-. ()]+\.(jpe?g|png|gif|webp|svg|avif|bmp|tiff?|heic)$")
SIZE_SUFFIX = re.compile(r"-\d+x\d+$")  # WordPress names resized copies photo-300x200.jpg
# Lazy-loading plugins put a placeholder in src and the real address in one of these.
LAZY_SOURCES = ("data-src", "data-lazy-src", "data-original", "data-lazy")


def image_address(attributes: dict) -> str:
    """The real address of an image. A data: URI in src is a lazy-load placeholder, not the picture."""
    for key in ("src",) + LAZY_SOURCES:
        value = (attributes.get(key) or "").strip()
        if value and not value.startswith("data:"):
            return value
    return ""


def alt_problem(alt: str | None, address: str) -> str | None:
    """Why alt text is not a real description, or None when it is one."""
    alt = collapse(alt)
    if not alt:
        return "no alt text"
    stem = SIZE_SUFFIX.sub("", urlsplit(address).path.rsplit("/", 1)[-1].rsplit(".", 1)[0])
    if IMAGE_FILE.match(alt) or (stem and alt.lower() == stem.lower()):
        return f"alt text is only the file name (\"{alt}\")"
    return None


def useful_alt(alt: str | None, address: str) -> bool:
    return alt_problem(alt, address) is None


def evaluate_alt_text(images: list[tuple[str, str | None]], rendered: bool = False) -> CheckResult:
    """images is [(address, alt)] for every <img>, including lazy-loaded ones below the fold. rendered: the
    images come from the page after a browser ran it, with any a visitor cannot see already left out."""
    def result(status: Status, summary: str, fix: str = "", details=(), ran: bool = True,
               measure: float | None = None) -> CheckResult:
        return CheckResult(SITE, ALT_TEXT, status, summary, ALT_TEXT_EXPLANATION, fix, list(details), ran,
                           measure=measure)

    if not images:
        return result(Status.PASS, "Your home page has no images, so there is no alt text to check.", ran=False)
    problems = [(address, alt_problem(alt, address)) for address, alt in images]
    lacking = [f"{address or '(no address)'}: {problem}" for address, problem in problems if problem]
    described = len(images) - len(lacking)
    counted = ("We counted every image a visitor can see once the page has run its scripts, including ones that "
               "only load when a visitor scrolls down." if rendered else "We counted every image in the page as "
               "delivered, including ones that only load when a visitor scrolls down and any the page hides.")
    details = [f"{described} of {len(images)} images have a real description. {counted}"]
    if described / len(images) < ALT_TEXT_PASS_SHARE:
        return result(
            Status.WARN, f"{len(lacking)} of the {len(images)} images on your home page have no real description.",
            "In your website builder, open each image listed under Fix it yourself and fill in its alt text "
            "(sometimes called \"image description\") with a short phrase describing the picture the way you would "
            "describe it to someone over the phone. Images that are purely decorative can stay blank.",
            details + _more(lacking), measure=described / len(images),
        )
    return result(Status.PASS, f"{described} of the {len(images)} images on your home page have a description.",
                  details=details + _more(lacking))


def check_alt_text(page: PageContext) -> list[CheckResult]:
    images = [
        (image_address(node.attributes), node.attributes.get("alt"))
        for node in parse(page.html).css("img")
        if not inside(node, "noscript")  # a copy for visitors without JavaScript, not a second image
    ]
    return [evaluate_alt_text(images, rendered=page.rendered)]

