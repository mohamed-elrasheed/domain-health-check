"""Which rung each check's findings sit on, and the matching lines from our public price lists.

Five rungs, in the order the last page lists them: self (the owner can do it, and the finding's own fix says
how), tuneup (work on the current site), email (domain and email settings, not website work), rebuild (a new
site) and platform (set by a hosted website builder, so not priced). The rungs, the price lines and the
check-to-rung map all live in one file, config/pricelist.yaml, which mirrors our /digital and /services pages
word for word. Nothing here writes a price: a rung either points at lines in that file or at none.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PATH = Path(__file__).parent.parent / "config" / "pricelist.yaml"
RUNGS = ("self", "tuneup", "email", "rebuild", "platform")  # the order the last page lists them in
SHOWS = ("fix", "prices", "summary")


@dataclass(frozen=True)
class PriceLine:
    page: str  # which of our pages publishes it: digital or services
    item: str
    price: str

    def __str__(self) -> str:
        return f"{self.item}: {self.price}"


@dataclass(frozen=True)
class Rung:
    key: str
    label: str
    intro: str
    shows: str  # what the last page puts beside each finding: its fix, the price lines, or its summary
    column: str
    prices: tuple[PriceLine, ...]
    once: bool = False  # the price lines are printed once, under the group heading, rather than on each row


@dataclass(frozen=True)
class PriceList:
    pages: dict[str, str]
    prices: dict[str, PriceLine]
    rungs: dict[str, Rung]
    checks: dict[str, str]  # check name -> rung key
    platform_checks: frozenset[str]

    def rung_of(self, check: str, platform: str = "") -> Rung | None:
        """The rung for a check, moved to platform when a hosted builder sets what the check measures."""
        if platform and check in self.platform_checks:
            return self.rungs["platform"]
        key = self.checks.get(check)
        return self.rungs[key] if key else None


def parse(data: dict) -> PriceList:
    """Raises ValueError for anything the last page could not render honestly: a rung that is not one of the
    five, a price line from a page we do not name, a rung that shows prices with none to show (or names prices
    it would never show), or a check on a rung that does not exist."""
    pages = dict(data["pages"])
    prices = {}
    for key, line in data["prices"].items():
        if line["page"] not in pages:
            raise ValueError(f"price line {key} is from {line['page']}, which is not one of {', '.join(pages)}")
        prices[key] = PriceLine(str(line["page"]), str(line["item"]), str(line["price"]))
    if tuple(data["rungs"]) != RUNGS:
        raise ValueError(f"the rungs must be exactly {', '.join(RUNGS)}, in that order, not {', '.join(data['rungs'])}")
    rungs = {}
    for key in RUNGS:
        spec = data["rungs"][key]
        named = list(spec.get("prices") or [])
        unknown = [p for p in named if p not in prices]
        if unknown:
            raise ValueError(f"rung {key} names price lines that are not in the list: {', '.join(unknown)}")
        if spec["shows"] not in SHOWS:
            raise ValueError(f"rung {key} shows {spec['shows']!r}; it must show one of {', '.join(SHOWS)}")
        placement = spec.get("price_line")
        if bool(named) != (placement in ("once", "per finding")):
            raise ValueError(f"rung {key} must say where its price lines go (price_line: once or per finding) exactly "
                             "when it names any")
        if (spec["shows"] == "prices") != (placement == "per finding"):
            raise ValueError(f"rung {key} shows prices on each row exactly when its price_line is per finding")
        rungs[key] = Rung(key, spec["label"], spec["intro"], spec["shows"], spec["column"],
                          tuple(prices[p] for p in named), placement == "once")
    checks = {str(name): str(rung) for name, rung in data["checks"].items()}
    wrong = sorted(f"{name}: {rung}" for name, rung in checks.items() if rung not in rungs or rung == "platform")
    if wrong:
        raise ValueError(f"checks with a rung that does not exist or cannot be assigned: {', '.join(wrong)}")
    platform_checks = frozenset(data.get("platform_checks") or [])
    if not platform_checks <= set(checks):
        raise ValueError(f"platform_checks names unknown checks: {', '.join(sorted(platform_checks - set(checks)))}")
    return PriceList(pages, prices, rungs, checks, platform_checks)


@lru_cache(maxsize=1)
def load(path: Path = PATH) -> PriceList:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
