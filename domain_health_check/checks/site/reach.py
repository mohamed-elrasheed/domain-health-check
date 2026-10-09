"""Can customers reach you? Two checks on the page itself: tap to call, and the contact form.

Tap to call reads the rendered home page: a phone number a visitor can see should be a tel: link, so tapping it on a
phone starts the call. The contact form is looked for on the home page, then on the one page the site's own
"contact" link points to (loaded by the runner through fetcher.fetch_contact_page, report mode only). The form is
never submitted. What we judge is where it says it sends: a real address passes. An empty address, "#", or a
script URL warns, unless the report recognized the platform the site runs on, whose own script usually sends the
form; then we cannot tell without submitting it, and say so instead of guessing.
"""

from __future__ import annotations

from urllib.parse import unquote, urljoin, urlsplit

from selectolax.parser import HTMLParser, Node

from ...fetcher import PageContext, same_site
from ...models import SITE, CheckResult, Status
from ..business_profile import PHONE_NUMBER, digits, shown
from ._editor import where
from ._html import parse, visible_text

TAP_TO_CALL = "Tap to call"
CONTACT_FORM = "Contact form"

TAP_EXPLANATION = (
    "Most visitors to a small business website are on a phone. When the phone number is a link, one tap starts the "
    "call; when it is plain text, the visitor has to copy or retype it, and some will not."
)
FORM_EXPLANATION = (
    "A contact or quote form is how many visitors get in touch. A form that does not say where to send what people "
    "type can take their message and deliver it nowhere, with no sign to them or to you that it was lost."
)
FORM_WORDS = ("contact", "quote", "estimate", "message", "enquiry", "inquiry")


# ---------- Tap to call

def numbers_in(html: str) -> tuple[list[str], list[str]]:
    """(numbers in the visible text, numbers in tel: links), each as ten digits, in page order."""
    tree = parse(html)
    linked = [digits(unquote((n.attributes.get("href") or "").strip()[4:])) for n in tree.css("a[href]")
              if (n.attributes.get("href") or "").strip().lower().startswith("tel:")]
    text = [digits("".join(m.groups())) for m in PHONE_NUMBER.finditer(visible_text(html))]
    return list(dict.fromkeys(n for n in text if n)), list(dict.fromkeys(n for n in linked if n))


def evaluate_tap_to_call(in_text: list[str], linked: list[str], editor: str = "") -> CheckResult:
    details = ["Numbers on the home page: " + (", ".join(shown(n) for n in in_text) or "none in the text"),
               "Numbers that are tap-to-call (tel:) links: " + (", ".join(shown(n) for n in linked) or "none")]

    def result(status: Status, summary: str, fix: str = "", ran: bool = True) -> CheckResult:
        return CheckResult(SITE, TAP_TO_CALL, status, summary, TAP_EXPLANATION, fix, details, ran)

    if not in_text and not linked:
        return result(Status.WARN, "Your home page shows no phone number, so there was nothing to check.",
                      "Nothing to do based on this check.", ran=False)
    plain = [n for n in in_text if n not in linked]
    if not plain:
        number = shown((linked or in_text)[0])
        return result(Status.PASS, f"Your phone number, {number}, starts a call when tapped on a phone.")
    numbers = " and ".join(shown(n) for n in plain[:2])
    pronoun = "it" if len(plain) == 1 else "them"
    return result(Status.WARN, f"Your home page shows {numbers}, but tapping {pronoun} on a phone does not start a "
                               "call.",
                  f"{where(editor)}, make the phone number on your home page a link that starts a call when someone "
                  "taps it.")


def check_tap_to_call(page: PageContext) -> list[CheckResult]:
    return [evaluate_tap_to_call(*numbers_in(page.visible_html), editor=page.editor)]


# ---------- Contact form

def _fields(form: Node) -> list[Node]:
    return [n for n in form.css("input, textarea, select")
            if (n.attributes.get("type") or "").lower() not in ("hidden", "submit", "button", "image", "reset")]


def is_contact_form(form: Node) -> bool:
    """A form someone uses to get in touch: a message box, or a name and an email or phone, or a form that calls
    itself contact, quote or estimate. Never a search box, a login, or a newsletter sign-up with one email field."""
    fields = _fields(form)
    types = [(n.attributes.get("type") or "text").lower() for n in fields if n.tag == "input"]
    names = " ".join((n.attributes.get("name") or "").lower() for n in fields)
    if form.attributes.get("role") == "search" or "search" in types or "password" in types:
        return False
    if any(n.tag == "textarea" for n in fields):
        return True
    label = " ".join((form.attributes.get(k) or "").lower() for k in ("id", "class", "name", "action", "aria-label"))
    if any(word in label for word in FORM_WORDS):
        return len(fields) > 1
    return len(fields) >= 2 and ("email" in types or "tel" in types or "email" in names or "phone" in names)


def contact_forms(html: str) -> list[Node]:
    return [form for form in HTMLParser(html).css("form") if is_contact_form(form)]


def contact_link(html: str, base: str) -> str:
    """Where the site's own "contact" link points, or "" when it has none. Same site only, never the page itself."""
    for node in parse(html).css("a[href]"):
        href = (node.attributes.get("href") or "").strip()
        url = urljoin(base, href).split("#")[0]
        text = " ".join(node.text(separator=" ").split()).lower()
        if ("contact" in text or "contact" in urlsplit(url).path.lower()) and same_site(url, base) and \
                url.rstrip("/") != base.split("#")[0].rstrip("/") and urlsplit(url).scheme in ("http", "https"):
            return url
    return ""


def form_target(form: Node, page_url: str) -> tuple[str, str]:
    """("real", address) when the form says where it sends, else ("empty" | "fragment" | "script", raw)."""
    raw = (form.attributes.get("action") or "").strip()
    if not raw:
        return "empty", raw
    if raw.startswith("#"):
        return "fragment", raw
    if raw.lower().startswith("javascript:"):
        return "script", raw
    return "real", urljoin(page_url, raw)


def evaluate_contact_form(target: tuple[str, str] | None, where_found: str, editor: str = "",
                          looked: list[str] = ()) -> CheckResult:
    """target is form_target() of the first contact form found, None when there is none. where_found names the
    page it is on, in words. editor is the platform the report recognized, "" when none."""
    details = [f"Looked on: {', '.join(looked)}" if looked else "Looked on: your home page",
               "We never submit a form; we read where it says it sends."]

    def result(status: Status, summary: str, fix: str = "", ran: bool = True) -> CheckResult:
        return CheckResult(SITE, CONTACT_FORM, status, summary, FORM_EXPLANATION, fix, details, ran)

    if target is None:
        return result(Status.WARN, "We did not find a contact form on your home page or your contact page, so there "
                                   "was nothing to check.", "Nothing to do based on this check.", ran=False)
    kind, value = target
    if kind == "real":
        details.append(f"Form sends to: {value}")
        return result(Status.PASS, f"The contact form on {where_found} says where to send what people type.")
    details.append(f"Form action: {value!r}" if value else "Form action: none")
    if editor:
        details.append(f"The page runs on {editor}, whose own script usually sends this kind of form.")
        return result(Status.WARN, f"The contact form on {where_found} is sent by your {editor} site's own script, so "
                                   "we could not tell where it goes without submitting it, which we never do.",
                      "Nothing to do based on this check. To be sure, send yourself a test message through it.",
                      ran=False)
    return result(Status.WARN, f"The contact form on {where_found} does not say where to send what people type, so "
                               "messages may go nowhere.",
                  f"{where(editor)}, check that the contact form is connected to your email, then send yourself a test "
                  "message through it.")


def check_contact_form(page: PageContext) -> list[CheckResult]:
    looked = ["your home page"]
    forms = contact_forms(page.visible_html)
    if forms:
        return [evaluate_contact_form(form_target(forms[0], page.final_url), "your home page", page.editor, looked)]
    if page.contact_page is not None:
        looked.append(page.contact_page.url)
        forms = contact_forms(page.contact_page.text)
        if forms:
            return [evaluate_contact_form(form_target(forms[0], page.contact_page.url), "your contact page",
                                          page.editor, looked)]
    return [evaluate_contact_form(None, "", page.editor, looked)]
