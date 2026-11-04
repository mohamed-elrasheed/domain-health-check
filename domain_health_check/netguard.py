"""Never contact a private network address on a submitter's say-so.

Anyone can submit a domain, and the report follows the page's links, redirects and scripts. Without this, a page
linking to http://192.168.1.1/ (or a domain whose DNS points at 127.0.0.1) would make the computer running the
report send requests into its own network, and whatever came back could land in the report. Found by an
independent audit on November 4, 2026.

PublicOnly wraps the real transport, so every request, including each redirect hop, is checked against what its
host resolves to: loopback, private, link-local, reserved and multicast addresses are refused. browser_guard does
the same for the browser's requests. A refusal never reaches the network.

Limit, stated rather than hidden: the address is checked when the request starts, and the connection resolves the
name again, so a DNS answer that changes between the two (rebinding) could still slip through. Pinning the
connection to the checked address would close that; it is not done here.
"""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

Resolver = Callable[..., list]


class PrivateAddress(httpx.ConnectError):
    """A request refused because its host is, or resolves to, a non-public address."""


def public(host: str, resolve: Resolver = socket.getaddrinfo) -> bool:
    """True only when host is a public address or a name every one of whose addresses is public. A name that does
    not resolve is left to the request itself to fail, as it would for any visitor."""
    host = (host or "").strip("[]")
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_global
    except ValueError:
        pass
    try:
        found = resolve(host, None)
    except (OSError, UnicodeError):
        return True
    addresses = {info[4][0].split("%")[0] for info in found}
    return bool(addresses) and all(ipaddress.ip_address(a).is_global for a in addresses)


class PublicOnly(httpx.BaseTransport):
    def __init__(self, inner: httpx.BaseTransport | None = None, resolve: Resolver = socket.getaddrinfo):
        self.inner = inner or httpx.HTTPTransport()
        self.resolve = resolve

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if not public(request.url.host, self.resolve):
            raise PrivateAddress(f"refused: {request.url.host} is a private network address", request=request)
        return self.inner.handle_request(request)

    def close(self) -> None:
        self.inner.close()


def browser_guard(resolve: Resolver = socket.getaddrinfo):
    """A Playwright route handler: web requests to private addresses are aborted, everything else goes on."""
    def route(r) -> None:
        parts = urlsplit(r.request.url)
        if parts.scheme in ("http", "https", "ws", "wss") and not public(parts.hostname or "", resolve):
            r.abort()
        else:
            r.continue_()
    return route
