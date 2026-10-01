"""Reading the fetched page the way a search engine reads the HTML it receives.

Everything here works on the HTML as delivered, before any scripts run. That is
what we measured, and findings say so when it matters.
"""

from __future__ import annotations

import re

from selectolax.parser import HTMLParser, Node

INVISIBLE = ["script", "style", "template", "noscript"]


def parse(html: str) -> HTMLParser:
    return HTMLParser(html)


def collapse(text: str | None) -> str:
    return " ".join((text or "").split())


def meta(tree: HTMLParser, key: str, attribute: str = "name") -> list[str]:
    """content of every <meta {attribute}="{key}">, matching the key without regard to case."""
    return [
        collapse(node.attributes.get("content"))
        for node in tree.css(f"meta[{attribute}]")
        if (node.attributes.get(attribute) or "").strip().lower() == key
    ]


def text_with_alt(node: Node) -> str:
    """Visible text of an element, counting image alt text the way search engines do."""
    alts = " ".join(img.attributes.get("alt") or "" for img in node.css("img"))
    return collapse(f"{node.text(separator=' ')} {alts}")


def visible_text(html: str) -> str:
    tree = HTMLParser(html)
    tree.strip_tags(INVISIBLE)
    return collapse(tree.body.text(separator=" ") if tree.body else "")


HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


def headings(tree: HTMLParser) -> list[tuple[int, str]]:
    """(level, text) for every h1 to h6, in document order. A comma selector would group them by
    tag instead, so we walk the tree."""
    return [(int(node.tag[1]), text_with_alt(node)) for node in tree.root.traverse() if node.tag in HEADING_TAGS]


def inside(node: Node, tag: str) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag == tag:
            return True
        parent = parent.parent
    return False


def word_count(text: str) -> int:
    return len(re.findall(r"\w+", text))
