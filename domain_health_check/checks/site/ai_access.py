"""Can AI search tools read the home page?

  * AI search access: ChatGPT, Claude and Perplexity can search the web to answer a question and show the
    websites they used. Each sends its own robot, and a robots.txt rule can tell that robot to stay away,
    which can keep the site out of that tool's answers.

The robots and what each is for are listed, with the company's own documentation, in config/ai_crawlers.yaml.
Only robots whose role is search count. A training robot (one that collects pages to train AI models) can be
blocked without affecting search, and owners often block it on purpose, so a block on one is listed in the
technical details and never counted against the site.

robots.txt is read by robots.py, the same reader the Search engine blocking check uses for Googlebot. This
check reads the robots.txt file the report already fetched and makes no request of its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

from ... import robots as robots_txt
from ...fetcher import FetchedFile, FetchError, PageContext
from ...models import SITE, CheckResult, Status

AI_ACCESS = "AI search access"
PATH = Path(__file__).parent.parent.parent.parent / "config" / "ai_crawlers.yaml"
ROLES = ("search", "training")
MISSING = (404, 410)  # no robots.txt at all: nothing tells any robot to stay away

EXPLANATION = (
    "Tools such as ChatGPT, Claude and Perplexity can search the web to answer a question, and they show the "
    "websites they used. Each tool sends its own search robot to read websites, and the robots.txt file (a "
    "short file of instructions for robots) can tell it to stay away. A website that tells these robots to "
    "stay away is less likely to appear in those answers."
)


@dataclass(frozen=True)
class Crawler:
    token: str  # the name robots.txt uses, as the company documents it
    company: str
    role: str  # search or training


@lru_cache(maxsize=4)
def load(path: Path | None = None) -> tuple[Crawler, ...]:
    """The enabled robots from config/ai_crawlers.yaml. Every entry needs a source or a reason it is disabled,
    never both and never neither, so nothing from memory ships."""
    data = yaml.safe_load((path or PATH).read_text(encoding="utf-8")) or {}
    crawlers = []
    for entry in data.get("crawlers") or []:
        if not isinstance(entry, dict):
            raise ValueError(f"ai_crawlers.yaml: every robot is a mapping, not {entry!r}")
        token, company, role = (str(entry.get(k) or "").strip() for k in ("token", "company", "role"))
        source, disabled = (str(entry.get(k) or "").strip() for k in ("source", "disabled"))
        if not token or not company or role not in ROLES:
            raise ValueError(f"ai_crawlers.yaml: every robot needs a token, a company and a role of "
                             f"{' or '.join(ROLES)}, not {entry!r}")
        if bool(source) == bool(disabled):
            raise ValueError(f"ai_crawlers.yaml: {token} needs either a source to cite or the reason it is "
                             f"disabled, not both and not neither")
        if source:
            crawlers.append(Crawler(token, company, role))
    return tuple(crawlers)


def _names(crawlers: list[Crawler]) -> str:
    """'OpenAI (OAI-SearchBot)', '... and ...' style list for a summary."""
    parts = [f"{c.company} ({c.token})" for c in crawlers]
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


def evaluate_ai_access(robots_text: str, crawlers: tuple[Crawler, ...] | None = None) -> CheckResult:
    """Judge a robots.txt file that was read (status 200). Pure: no request, no file other than the config."""
    crawlers = load() if crawlers is None else crawlers
    search = [c for c in crawlers if c.role == "search"]
    rules = {c.token: robots_txt.blocking_rule(robots_text, c.token, "/") for c in crawlers}
    blocked = [c for c in search if rules[c.token]]
    details = [f"{c.token} ({c.company}, {c.role}): " + (f"blocked by {rules[c.token]}" if rules[c.token]
                                                         else "allowed") for c in crawlers]
    training_blocked = [c for c in crawlers if c.role == "training" and rules[c.token]]
    if training_blocked:
        details.append(f"Your robots.txt file asks {_names(training_blocked)} not to collect your pages for "
                       "training AI models. That does not affect whether you appear in AI search answers.")

    if not blocked:
        return CheckResult(
            SITE, AI_ACCESS, Status.PASS,
            "Your robots.txt file lets the AI search tools we check read your home page.",
            EXPLANATION, "", details,
        )
    allowed = len(search) - len(blocked)
    return CheckResult(
        SITE, AI_ACCESS, Status.WARN,
        f"Your robots.txt file tells {len(blocked)} of {len(search)} AI search robots to stay away from your "
        f"home page: {_names(blocked)}.",
        EXPLANATION,
        "Some owners choose this on purpose. If you did not, ask your web developer to remove the robots.txt "
        "rules that block these search robots. The technical details show each rule.",
        details,
        measure=allowed / len(search) if search else None,
    )


def check_ai_access(page: PageContext | FetchError) -> list[CheckResult]:
    """Runs even when the home page could not be loaded: robots.txt alone answers the question."""
    robots: FetchedFile | None = page.robots
    if robots is not None and robots.status in MISSING:
        return [CheckResult(
            SITE, AI_ACCESS, Status.PASS,
            "Your website has no robots.txt file, so nothing tells AI search tools to stay away.",
            EXPLANATION, "", [f"robots.txt: {robots.url} (status {robots.status})"],
        )]
    if robots is None or robots.status != 200:
        where = f"{robots.url} (status {robots.status})" if robots else "not read"
        return [CheckResult(
            SITE, AI_ACCESS, Status.WARN,
            "We could not read your robots.txt file, so we could not check whether AI search tools may read "
            "your website.",
            EXPLANATION, "Nothing to do based on this report.", [f"robots.txt: {where}"], ran=False,
        )]
    return [evaluate_ai_access(robots.text)]
