"""Loading and validating domains.yaml."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# Letters, digits and hyphens in dot-separated labels, e.g. "mail.example.com".
# Validating this also guarantees a domain name is safe to use in a report filename.
_DOMAIN_RE = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9-]{2,63}$")
_SELECTOR_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,62})$", re.IGNORECASE)


class ConfigError(Exception):
    pass


@dataclass
class DomainConfig:
    name: str
    dkim_selectors: list[str] = field(default_factory=list)
    # From the /digital form, for finding the Google Business Profile. The form submits them as
    # business-name (required) and city (optional); the phone is one of its unnamed field-N slots.
    business_name: str = ""
    city: str = ""
    phone: str = ""


def normalize_domain(value: object) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"Domain names must be text, got {value!r}")
    domain = value.strip().lower().rstrip(".")
    if len(domain) > 253 or not _DOMAIN_RE.match(domain):
        raise ConfigError(f"{value!r} does not look like a domain name (expected something like example.com)")
    return domain


def _parse_selectors(domain: str, value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(s, str) for s in value):
        raise ConfigError(f"dkim_selectors for {domain} must be a list, e.g. [google, selector1]")
    for selector in value:
        if not _SELECTOR_RE.match(selector):
            raise ConfigError(f"{selector!r} is not a valid DKIM selector (for {domain})")
    return list(value)


def _parse_entry(entry: object) -> DomainConfig:
    if isinstance(entry, str):
        return DomainConfig(normalize_domain(entry))
    if isinstance(entry, dict):
        if "name" not in entry:
            raise ConfigError(f"Each domain entry needs a 'name': {entry!r}")
        domain = normalize_domain(entry["name"])
        extra = {}
        for key in ("business_name", "city", "phone"):
            value = entry.get(key, "")
            if not isinstance(value, (str, int)):
                raise ConfigError(f"{key} for {domain} must be text")
            extra[key] = str(value).strip()
        return DomainConfig(domain, _parse_selectors(domain, entry.get("dkim_selectors")), **extra)
    raise ConfigError(f"Unexpected entry in 'domains': {entry!r}")


def load_config(path: Path) -> list[DomainConfig]:
    if not path.exists():
        raise ConfigError(
            f"{path} not found. Copy domains.example.yaml to {path.name} and add your domains."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    entries = data.get("domains") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries:
        raise ConfigError(f"{path} must contain a non-empty 'domains:' list")

    domains = [_parse_entry(entry) for entry in entries]
    seen = set()
    for d in domains:
        if d.name in seen:
            raise ConfigError(f"{d.name} is listed more than once in {path}")
        seen.add(d.name)
    return domains


def load_env(path: Path) -> None:
    """Read KEY=VALUE lines from a .env file into the environment, without overriding anything already
    set. A missing file is fine: every API key is optional."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key and value:
            os.environ.setdefault(key, value.strip("\"'"))
