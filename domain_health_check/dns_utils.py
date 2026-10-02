"""A thin wrapper around dnspython.

DNS (the Domain Name System) is the internet's public directory. Anyone can ask
"what are the mail servers for example.com?" and get an answer. The DNS-based
checks in this tool only read what the domain owner has already published for
the whole world to see.

The rest of the code only ever sees plain strings, which also makes the checks
easy to test with fake DNS data.
"""

from __future__ import annotations

import dns.exception
import dns.resolver

TIMEOUT_SECONDS = 5.0


class DNSLookupError(Exception):
    """The lookup itself failed (timeout, broken nameservers), as opposed to 'no such record'."""


def _resolve(name: str, rdtype: str):
    try:
        return dns.resolver.resolve(name, rdtype, lifetime=TIMEOUT_SECONDS)
    except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
        # The name doesn't exist, or exists but has no records of this type.
        return None
    except dns.exception.DNSException as exc:
        raise DNSLookupError(f"{rdtype} lookup for {name} failed: {exc}") from exc


def domain_exists(name: str) -> bool | None:
    """False when DNS says the name does not exist at all (NXDOMAIN), True when it does, None when we could not
    tell. Every other lookup reads NXDOMAIN as "no records", which is why this question is asked separately."""
    try:
        dns.resolver.resolve(name, "SOA", lifetime=TIMEOUT_SECONDS)
    except dns.resolver.NXDOMAIN:
        return False
    except dns.resolver.NoAnswer:
        return True
    except dns.exception.DNSException:
        return None
    return True


def lookup(name: str, rdtype: str) -> list[str]:
    """Return every record of `rdtype` at `name` as text, or [] if there are none."""
    answer = _resolve(name, rdtype)
    return [] if answer is None else [record.to_text() for record in answer]


def lookup_txt(name: str) -> list[str]:
    """Return TXT records as plain strings.

    A single TXT record can be split into several 255-byte chunks on the wire;
    they are joined back together here, as the SPF/DKIM/DMARC specs require.
    """
    answer = _resolve(name, "TXT")
    if answer is None:
        return []
    return [b"".join(record.strings).decode("utf-8", errors="replace") for record in answer]
