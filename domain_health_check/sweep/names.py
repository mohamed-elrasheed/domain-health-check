"""What a business calls itself on its own site.

Our lead name comes from listings ("Example Garage Auto Care (Fuel)"); the business may call itself
something else on its own header ("Example Fuel"). A proposal should use their name, so sweep reads it from
the page it already loaded: the header first (logo alt text, then short text), then the holder named in the
footer's copyright line. A candidate counts only if it shares a distinctive word with our lead name, which
keeps "Home", "Menu" and a vendor's copyright out. We never make a name by trimming ours, and a name read
here is confirmed with the owner on the call before anything goes live under it.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

from .faults import COPYRIGHT_LINE, collapse, distinctive_words

MAX_WORDS = 8
MAX_CHARS = 60
HEADER = "header, [role=banner]"
FOOTER = "footer, [role=contentinfo]"
CLASS_HINT = {"header": re.compile(r"(?i)(^|[\s_-])(header|masthead|navbar|brand|logo)"),
              "footer": re.compile(r"(?i)(^|[\s_-])footer")}


def _region(tree: HTMLParser, kind: str) -> Node | None:
    found = tree.css_first(HEADER if kind == "header" else FOOTER)
    if found is not None:
        return found
    for node in tree.css("[class], [id]"):
        if CLASS_HINT[kind].search(f"{node.attributes.get('class') or ''} {node.attributes.get('id') or ''}"):
            return node
    return None


def _fits(text: str, words: set[str], shown: str | None) -> bool:
    lower = text.lower()
    return (0 < len(text) <= MAX_CHARS and len(text.split()) <= MAX_WORDS
            and any(re.search(rf"\b{re.escape(w)}\b", lower) for w in words)
            and (shown is None or lower in shown))


def _holder(line: str) -> str:
    """The name in a copyright line: "Copyright © 2015-2026 Example Fuel. All rights reserved" -> "Example Fuel"."""
    line = re.sub(r"(?i)copyright|\(c\)|©|all rights reserved\.?", " ", line)
    line = re.sub(r"\b(19|20)\d{2}\b(\s*[-–—]\s*((19|20)\d{2}|\d{2}))?", " ", line)
    return collapse(line).strip(" .,|-–")


def display_name(html: str, business: str, shown: str | None = None) -> tuple[str, str] | None:
    """(name, where on their page it came from), or None when the page does not name them recognizably."""
    words = distinctive_words(business)
    if not words:
        return None
    tree = HTMLParser(html)
    tree.strip_tags(["script", "style", "template", "noscript"])
    shown = shown.lower() if shown else None
    header = _region(tree, "header")
    if header is not None:
        for img in header.css("img[alt]"):
            alt = collapse(img.attributes.get("alt"))
            if _fits(alt, words, None):  # alt text is not displayed, so it is not checked against shown
                return alt, "their site header (logo description)"
        for node in header.traverse(include_text=True):
            if node.tag == "-text":
                text = collapse(node.text(deep=False))
                if _fits(text, words, shown):
                    return text, "their site header"
    footer = _region(tree, "footer")
    if footer is not None:
        for match in COPYRIGHT_LINE.finditer(collapse(footer.text(separator=" "))):
            holder = _holder(match.group(0))
            if _fits(holder, words, shown):
                return holder, "their site footer (copyright line)"
    return None
