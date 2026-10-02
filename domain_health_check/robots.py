"""robots.txt, read the way RFC 9309 and Google read it.

One reader for both questions this tool asks: may *we* load a page (fetcher.py),
and may *Google* crawl it (the search engine blocking check).

  * The group for the crawler's product token if there is one, otherwise *.
    Repeated groups for the same token are merged.
  * The longest matching rule wins, and Allow wins a tie.
  * * matches any run of characters and a trailing $ anchors the end.
  * An empty Disallow allows everything, and /robots.txt itself is always allowed.

Before Python 3.14, urllib.robotparser does none of the middle three: on 3.11
and 3.13 it reads "Disallow: /*" as allowing everything. This project supports
3.10 and later, so it reads robots.txt itself and behaves the same on all of them.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit


def groups(text: str) -> dict[str, list[tuple[str, str]]]:
    """{product token (lowercased): [(allow|disallow, pattern), ...]}."""
    found: dict[str, list[tuple[str, str]]] = {}
    agents: list[str] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        field, value = (part.strip() for part in line.split(":", 1))
        field = field.lower()
        if field == "user-agent":
            if in_rules:  # a user-agent line after rules starts a new group
                agents, in_rules = [], False
            token = value.split("/", 1)[0].strip().lower()  # "Googlebot/2.1" names the Googlebot group
            agents.append(token)
            found.setdefault(token, [])
        elif field in ("allow", "disallow") and agents:
            in_rules = True
            for agent in agents:
                found[agent].append((field, value))
    return found


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = "".join(".*" if c == "*" else re.escape(c) for c in body) + ("$" if anchored else "")
    return re.match(regex, path) is not None


def blocking_rule(text: str, token: str, url_or_path: str = "/") -> str | None:
    """The rule that keeps the crawler named token away from url_or_path, or None if it may go."""
    parts = urlsplit(url_or_path)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    if path == "/robots.txt":
        return None
    by_agent = groups(text)
    token = token.lower()
    rules = by_agent[token] if token in by_agent else by_agent.get("*", [])
    best: tuple[tuple[int, bool], str, str] | None = None
    for directive, pattern in rules:
        if pattern and _matches(pattern, path):  # an empty Disallow allows everything
            key = (len(pattern), directive == "allow")
            if best is None or key > best[0]:
                best = (key, directive, pattern)
    return f"Disallow: {best[2]}" if best and best[1] == "disallow" else None
