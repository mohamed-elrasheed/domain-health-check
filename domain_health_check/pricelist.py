"""Which rung each check's findings sit on, and the matching lines from the public price list.

Three rungs: self (the owner can do it, and the finding's own fix says how), tuneup (work on the current site)
and rebuild (a new site). The rungs, the price lines and the check-to-rung map all live in one file,
config/pricelist.yaml, which mirrors https://www.mizangroupllc.com/digital word for word. Nothing here writes a
price: a rung either points at lines in that file or at none.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

PATH = Path(__file__).parent.parent / "config" / "pricelist.yaml"
RUNGS = ("self", "tuneup", "rebuild")  # the order the last page lists them in


@dataclass(frozen=True)
class PriceLine:
    item: str
    price: str

    def __str__(self) -> str:
        return f"{self.item}: {self.price}"


@dataclass(frozen=True)
class Rung:
    key: str
    label: str
    intro: str
    prices: tuple[PriceLine, ...]


@dataclass(frozen=True)
class PriceList:
    source: str
    prices: dict[str, PriceLine]
    rungs: dict[str, Rung]
    checks: dict[str, str]  # check name -> rung key

    def rung_of(self, check: str) -> Rung | None:
        key = self.checks.get(check)
        return self.rungs[key] if key else None


def parse(data: dict) -> PriceList:
    """Raises ValueError for a rung that is not one of the three, or a price key the file does not define."""
    prices = {key: PriceLine(str(line["item"]), str(line["price"])) for key, line in data["prices"].items()}
    if set(data["rungs"]) != set(RUNGS):
        raise ValueError(f"the rungs must be exactly {', '.join(RUNGS)}, not {', '.join(data['rungs'])}")
    rungs = {}
    for key in RUNGS:
        spec = data["rungs"][key]
        unknown = [p for p in spec.get("prices") or [] if p not in prices]
        if unknown:
            raise ValueError(f"rung {key} names price lines that are not in the list: {', '.join(unknown)}")
        rungs[key] = Rung(key, spec["label"], spec["intro"], tuple(prices[p] for p in spec.get("prices") or []))
    checks = {str(name): str(rung) for name, rung in data["checks"].items()}
    wrong = sorted(f"{name}: {rung}" for name, rung in checks.items() if rung not in rungs)
    if wrong:
        raise ValueError(f"checks with a rung that does not exist: {', '.join(wrong)}")
    return PriceList(data["source"], prices, rungs, checks)


@lru_cache(maxsize=1)
def load(path: Path = PATH) -> PriceList:
    return parse(yaml.safe_load(path.read_text(encoding="utf-8")))
