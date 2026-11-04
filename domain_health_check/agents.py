"""Two AI steps after the checks: one model drafts the note to the business, a second checks it. Off by default.

The workflow is fixed, not autonomous. Code runs the checks and draws the chart; the models only ever see the
finished record, and they cannot fetch, browse or send anything.

    checks (code)  ->  facts (code)  ->  draft (Sonnet)  ->  voice lint (code)  ->  review x3 (Haiku)  ->  Mo

The draft goes to Mo only if the code lint finds nothing and all three reviews pass. Anything else, including any
error, falls back to the template in mailer.draft_to_business, and Mo sees why. There is no retry loop: a draft
that fails is a finding about the prompt, not something to roll the dice on again.

Nothing leaves this machine unless AI_DRAFTS=on. The report data goes to Anthropic's API when it is on, so it stays
off until the privacy page says so. The models see the domain and the findings, never the person's name, email or
phone: the greeting and the sign-off are added here, in code.

Run it on a saved report:  AI_DRAFTS=on python -m domain_health_check.agents reports/<domain>/<date>/report.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

# Model IDs from Anthropic's model list, the current Sonnet and Haiku as of 2026-11-03.
DRAFT_MODEL = "claude-sonnet-5-5"
REVIEW_MODEL = "claude-haiku-5-5"
REVIEW_RUNS = 3  # every one must pass
GATE = "AI_DRAFTS"
OUTCOME_FILE = "ai-draft.json"

# What the models see from report.json. Not the requests log, not the technical details, not who asked.
RESULT_FIELDS = ("category", "name", "status", "summary", "explanation", "fix", "ran", "certain", "rung")

WHO = {"self": "You can do this yourself.", "us": "We can help with this."}


def enabled() -> bool:
    return os.environ.get(GATE, "").strip().lower() == "on"


def facts(record: dict) -> dict:
    """The part of report.json a model may see. Every claim in the draft must trace back to something in here."""
    return {
        "domain": record["domain"],
        "checked_at": record["checked_at"],
        "website_loaded": record.get("website_loaded"),
        "score": record.get("score"),
        "reading": record.get("reading"),
        "incomplete": list(record.get("incomplete") or []),
        "results": [{k: r.get(k) for k in RESULT_FIELDS} for r in record["results"]],
    }


# ---------- what each model must return. The API holds the model to these shapes (structured outputs).

class Step(BaseModel):
    action: str = Field(description="One plain sentence: what to do, taken from a finding's fix.")
    who: Literal["self", "us"] = Field(description="self if the fix's rung is 'self', otherwise us.")


class Draft(BaseModel):
    bottom_line: str = Field(description="One or two sentences. Lead with the reading. Broken things first.")
    missing: list[str] = Field(description="Up to five short sentences, one per finding worth knowing about.")
    next_steps: list[Step] = Field(description="Up to three steps, in the order the results list them.")


class Review(BaseModel):
    passed: bool
    reason: str = Field(description="One to three sentences for a technical reader.")
    unsupported_claims: list[str] = Field(description="Exact quotes from the draft the record does not back.")
    voice_problems: list[str] = Field(description="Exact quotes from the draft that break a voice rule.")


DRAFT_SYSTEM = """You write the short note that goes with a free website health report from Mizan Digital Services.
The reader is a small business owner, not an engineer.

Use only the record you are given. Do not add facts, numbers, causes, competitors, prices or anything you know
from elsewhere. If the record does not say it, do not write it.

Rules:
- Plain words. If a technical term is unavoidable, say what it means in the same sentence.
- bottom_line first: start from the record's reading. A FAIL means broken today. A WARN means it could be better,
  never that it is broken or dangerous. INFO and PASS are not problems.
- missing: only WARN and FAIL results, in the order they appear in the record. Say what we found, not what might
  happen.
- If a result has ran false or certain false, say we could not check it, or leave it out. Never present it as
  found.
- next_steps: up to three, taken from the fix of a FAIL or WARN result. who is self when that result's rung is
  "self", otherwise us.
- Never promise to run the checks again. Never mention prices.
- Team voice, "we", never "I". American English. No contractions.
- Never use a dash as punctuation, an exclamation mark, an ellipsis, or a word in all capitals that is not in the
  record. Never use these words: critical, urgent, alarming, huge, amazing.
- Do not write a greeting or a sign off. They are added for you."""

REVIEW_SYSTEM = """You check a draft note against the record it was written from. You do not rewrite it.

Check every sentence of the draft:
1. Is it backed by the record? Every fact, number and status must appear there. A WARN described as broken,
   dangerous or failing is unsupported. A result with ran false or certain false described as found is
   unsupported.
2. Voice: no dash used as punctuation, no exclamation mark, no ellipsis, no contractions, no "I", no prices, no
   promise to run the checks again, no words in all capitals that are not in the record, none of the words
   critical, urgent, alarming, huge or amazing.
3. Does each next step's who match the rung of the result it came from (self for rung "self", us for anything
   else)?

passed is true only if you found nothing in 1, 2 or 3. Quote the exact words for anything you flag.
If you are not sure a sentence is backed by the record, treat it as unsupported. A wrong pass is worse than a
wrong fail."""


# ---------- the code check. Cheap, exact, and it runs before any review is paid for.

BANNED = ("critical", "urgent", "alarming", "huge", "amazing")
CONTRACTION = re.compile(r"(?i)n['’]t\b|['’](re|ll|ve|m|d)\b|\b(it|that|there|here|what|who)['’]s\b|\blet['’]s\b")
RECHECK = re.compile(r"(?i)(run|check)\w* (these checks |the checks |it )?again|re-?check|re-?run")
DASH = re.compile(r"[—–]|\s-\s|\s--\s")
CAPS = re.compile(r"\b[A-Z]{2,}\b")
NUMBER = re.compile(r"\d+(?:[.,]\d+)?")


def draft_texts(d: Draft) -> list[str]:
    return [d.bottom_line, *d.missing, *(s.action for s in d.next_steps)]


def voice_lint(d: Draft, f: dict) -> list[str]:
    """Rule breaks a regex can prove. Numbers and all-caps words must appear in the record: a model that invents
    "12 broken links" or shouts "WARNING" is caught here without asking another model."""
    known = json.dumps(f, ensure_ascii=False)
    numbers, caps = set(NUMBER.findall(known)), set(CAPS.findall(known))
    problems = []
    for text in draft_texts(d):
        if DASH.search(text):
            problems.append(f"dash used as punctuation: {text}")
        if "!" in text:
            problems.append(f"exclamation mark: {text}")
        if "..." in text or "…" in text:
            problems.append(f"ellipsis: {text}")
        if CONTRACTION.search(text):
            problems.append(f"contraction: {text}")
        if re.search(r"\bI\b", text):
            problems.append(f"first person singular: {text}")
        if "$" in text:
            problems.append(f"price: {text}")
        if RECHECK.search(text):
            problems.append(f"promise to run the checks again: {text}")
        for word in BANNED:
            if re.search(rf"(?i)\b{word}\b", text):
                problems.append(f"banned word {word!r}: {text}")
        for word in CAPS.findall(text):
            if word not in caps:
                problems.append(f"all capitals not in the record {word!r}: {text}")
        for number in NUMBER.findall(text):
            if number not in numbers:
                problems.append(f"number not in the record {number!r}: {text}")
    if len(d.missing) > 5 or len(d.next_steps) > 3:
        problems.append("too many items: up to five missing and three next steps")
    return problems


# ---------- the two model calls

def _ask(client, model: str, system: str, user: str, shape: type[BaseModel], max_tokens: int, usage: dict):
    resp = client.messages.parse(model=model, max_tokens=max_tokens, system=system,
                                 messages=[{"role": "user", "content": user}], output_format=shape)
    used = usage.setdefault(model, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    used["calls"] += 1
    used["input_tokens"] += resp.usage.input_tokens
    used["output_tokens"] += resp.usage.output_tokens
    if resp.parsed_output is None:
        raise ValueError(f"{model} returned no parsed output (stop reason {resp.stop_reason})")
    return resp.parsed_output


def draft(f: dict, client, usage: dict) -> Draft:
    return _ask(client, DRAFT_MODEL, DRAFT_SYSTEM, "Record:\n" + json.dumps(f, indent=1, ensure_ascii=False),
                Draft, 2000, usage)


def review(f: dict, d: Draft, client, usage: dict) -> Review:
    user = ("Record:\n" + json.dumps(f, indent=1, ensure_ascii=False)
            + "\n\nDraft:\n" + d.model_dump_json(indent=1))
    return _ask(client, REVIEW_MODEL, REVIEW_SYSTEM, user, Review, 1500, usage)


# ---------- the outcome Mo sees

@dataclass
class Outcome:
    passed: bool
    body: str = ""  # the note without greeting or sign off; empty unless passed
    reasons: list[str] = field(default_factory=list)  # why it failed, for Mo
    flagged: list[str] = field(default_factory=list)  # exact lines the lint or a reviewer flagged
    draft: dict | None = None
    reviews: list[dict] = field(default_factory=list)
    usage: dict = field(default_factory=dict)
    models: dict = field(default_factory=lambda: {"draft": DRAFT_MODEL, "review": REVIEW_MODEL})

    def tokens(self) -> str:
        return ", ".join(f"{m}: {u['calls']} calls, {u['input_tokens']} in, {u['output_tokens']} out"
                         for m, u in self.usage.items()) or "none"


def render(d: Draft) -> str:
    lines = [d.bottom_line, ""]
    if d.missing:
        lines += ["What we found:", *(f"- {m}" for m in d.missing), ""]
    if d.next_steps:
        lines += ["What to do next:"]
        lines += [f"{n}. {s.action} {WHO[s.who]}" for n, s in enumerate(d.next_steps, 1)]
    return "\n".join(lines).strip()


def ai_draft(record: dict, client=None) -> Outcome:
    """Draft, lint, review three times. Never raises: any error is a failed outcome and the template is used."""
    usage: dict = {}
    try:
        if client is None:
            import anthropic  # only with the [ai] extra, and only when the gate is on
            client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
        f = facts(record)
        d = draft(f, client, usage)
        out = Outcome(passed=False, draft=d.model_dump(), usage=usage)
        lint = voice_lint(d, f)
        if lint:  # no review is paid for a draft the code already rejects
            out.reasons, out.flagged = ["The code check found rule breaks."], lint
            return out
        for _ in range(REVIEW_RUNS):
            r = review(f, d, client, usage)
            out.reviews.append(r.model_dump())
            if not r.passed or r.unsupported_claims or r.voice_problems:
                out.reasons.append(r.reason)
                out.flagged += [*r.unsupported_claims, *r.voice_problems]
        if out.reasons:
            return out
        out.passed, out.body = True, render(d)
        return out
    except Exception as exc:  # the API, the network, a malformed record: the template takes over
        return Outcome(passed=False, reasons=[f"{type(exc).__name__}: {exc}"], usage=usage)


def save(outcome: Outcome, folder: Path) -> Path:
    """ai-draft.json beside report.json: the draft, every review and the token counts, for the eval log."""
    path = folder / OUTCOME_FILE
    path.write_text(json.dumps(asdict(outcome), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: AI_DRAFTS=on python -m domain_health_check.agents reports/<domain>/<date>/report.json")
        return 2
    if not enabled():
        print(f"{GATE} is not on, so nothing was sent. Set {GATE}=on to run the draft and review.")
        return 2
    path = Path(args[0])
    outcome = ai_draft(json.loads(path.read_text(encoding="utf-8")))
    saved = save(outcome, path.parent)
    print("PASSED" if outcome.passed else "DID NOT PASS, the template would be used")
    print(outcome.body or "\n".join(["Why:", *outcome.reasons, "Flagged:", *outcome.flagged]))
    print(f"Tokens: {outcome.tokens()}")
    print(f"Saved {saved}")
    return 0 if outcome.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
