"""Which hosted website builder serves a page, from what the report already fetched, and which icon addresses
are a builder's default rather than the owner's own. Both read config/platforms.yaml; neither makes a request.

On a hosted builder (Webflow, Wix, Squarespace, Shopify, GoDaddy Website Builder) the platform sets the response
headers, so the owner and their developer usually cannot change them. Signals, any one of which is enough:
the platform's own response headers, its <meta name="generator">, attributes it writes on the page, and the
hosts the page loads its own assets from (scripts, stylesheets, images, fonts: not links to other sites).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import yaml
from selectolax.parser import HTMLParser

PATH = Path(__file__).parent.parent / "config" / "platforms.yaml"


@dataclass(frozen=True)
class Platform:
    name: str
    generator: tuple[str, ...]
    headers: tuple[str, ...]
    attributes: tuple[str, ...]
    hosts: tuple[str, ...]
    default_icons: tuple[str, ...]


@dataclass(frozen=True)
class Detected:
    name: str
    evidence: str  # what gave it away, for the technical details


@lru_cache(maxsize=1)
def load(path: Path = PATH) -> tuple[list[Platform], dict[str, tuple[str, ...]]]:
    """(hosted builders, every default icon fragment by platform name)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    hosted = [Platform(name, *(tuple(s.lower() for s in spec.get(key) or [])
                               for key in ("generator", "headers", "attributes", "hosts", "default_icons")))
              for name, spec in data["platforms"].items()]
    icons = {p.name: p.default_icons for p in hosted}
    icons.update({name: tuple(spec.get("default_icons") or []) for name, spec in data["default_icons_only"].items()})
    return hosted, icons


def asset_urls(html: str, base: str) -> list[str]:
    """Where the page loads its own assets from: scripts, stylesheets, images, sources and icons."""
    tree = HTMLParser(html)
    found = []
    for node in tree.css("script[src], img[src], source[src]"):  # not iframes: an embed is someone else's page
        found.append(node.attributes.get("src") or "")
    for node in tree.css("img[srcset], source[srcset]"):
        found += [part.strip().split(" ")[0] for part in (node.attributes.get("srcset") or "").split(",")]
    for node in tree.css("link[href]"):
        rel = (node.attributes.get("rel") or "").lower()
        if any(word in rel for word in ("stylesheet", "icon", "preload", "modulepreload")):
            found.append(node.attributes.get("href") or "")
    return [urljoin(base, u) for u in found if u and not u.startswith(("data:", "blob:"))]


def evaluate_platform(headers: dict[str, str], html: str, assets: list[str]) -> Detected | None:
    """The first builder with any signal, or None. headers have lowercased keys."""
    hosted, _ = load()
    tree = HTMLParser(html)
    generators = [(node.attributes.get("content") or "").lower() for node in tree.css("meta[name]")
                  if (node.attributes.get("name") or "").lower() == "generator"]
    hosts = {(urlsplit(u).hostname or "").lower() for u in assets}
    for p in hosted:
        generator = next((gen for gen in generators if any(g in gen for g in p.generator)), None)
        if generator:
            return Detected(p.name, f"generator tag: {generator}")
        header = next((h for h in headers for prefix in p.headers if h.startswith(prefix)), None)
        if header:
            return Detected(p.name, f"response header: {header}")
        if (headers.get("server") or "").lower() == p.name.lower():
            return Detected(p.name, f"response header: server: {headers['server']}")
        attribute = next((a for a in p.attributes if tree.css_first(f"[{a}]") is not None), None)
        if attribute:
            return Detected(p.name, f"page attribute: {attribute}")
        host = next((h for h in sorted(hosts) for suffix in p.hosts if h == suffix or h.endswith("." + suffix)), None)
        if host:
            return Detected(p.name, f"assets load from {host}")
    return None


def detect(page) -> Detected | None:
    """The builder serving a fetched PageContext, from its delivered page, its rendered page and the resources
    the browser loaded for it."""
    assets = asset_urls(page.html, page.final_url) + asset_urls(page.rendered_html, page.final_url)
    assets += [url for url, kind in page.resources if kind != "iframe"]
    return evaluate_platform(page.headers, page.html, assets)


def default_icon(*urls: str) -> str | None:
    """The platform whose default icon any of these addresses is, or None."""
    _, icons = load()
    for url in urls:
        lowered = url.lower()
        for name, fragments in icons.items():
            if any(fragment in lowered for fragment in fragments):
                return name
    return None
