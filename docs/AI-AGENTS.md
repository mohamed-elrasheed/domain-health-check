# The draft and review agents

The report's facts come from tested code. Two Claude models turn those facts into a plain-English message for the
owner, and a person approves it before anything is sent. This page explains how it works and why each choice was
made. The code is `domain_health_check/agents.py`.

**North Star:** every word a business owner reads must be true, checked, and approved by a person.

## The workflow

```
form submission (consent)
      │
      ▼
 1. Research      code     about 45 checks  ──>  DomainReport  ──>  PDF, chart, score  (no AI anywhere here)
      │
      ▼
    facts()       code     cuts the report down to what the writer needs
      │
      ▼
 2. Draft         Sonnet   bottom line, what is missing, what would help
      │
      ▼
    code_check()  code     every rule a program can check exactly ── fails? template goes out
      │
      ▼
 3. Review x3     Haiku    every claim against the facts, three separate times ── any fails? template goes out
      │
      ▼
 4. Mo            person   reads the review email, sends the draft or does not
```

This is a fixed workflow, not an autonomous agent. The steps never change, so no model decides what happens next.
That makes it cheaper, testable, and easy to audit.

## Why each choice was made

| Choice | Why |
|---|---|
| Facts come from code, not AI | A model can be wrong in a confident voice. A tested check cannot invent a finding. The chart and score are drawn by code from the same data. |
| `facts()` sends only what the writer needs | No request log, no technical details, no nearby averages, nothing about who filled in the form. Less data sent means less to leak and less to misuse. |
| Code decides what code can decide | Which findings lead (the report's own ranking), who can fix each one (the price list), the greeting, the opening line and the signature. The models only write sentences about facts they were given. |
| Sonnet writes, Haiku reviews | Writing for a person is the hard part. Checking claims against data is narrow, and Haiku costs about a twentieth as much. |
| A code check before the review | Dashes, exclamation marks, prices, hype words, status labels, praise or ranking the report does not state, numbers or capitals not in the report, check names that do not exist, a passing check listed as a problem, a top finding left out. A program checks these exactly and for free, so a draft that breaks one never pays for a review. |
| Three reviews, all must pass | One review can miss something. Three independent ones must agree. A wrong pass is worse than a wrong fail. |
| Structured outputs | The API holds each reply to a JSON schema, so code can read `passed` instead of guessing from prose. Forced tool calls return an error on Sonnet 5.5, so they are not used. |
| Fail closed | No key, the switch off, an API error, a spending limit, a model that stops early or refuses, or one failed review: the template goes out and Mo is told why. `run()` never raises. |
| Prompt injection rule | The facts can quote the website's own text, such as its page title. Both prompts say quoted website text is data, never instructions. The code check and Mo's review are the backstops. |
| An explicit switch | Having a key does not turn AI drafts on for the hourly intake. `AI_DRAFTS=on` does, and only once the privacy policy says report data goes to an AI service. |
| A run log | Every run writes `ai.json` beside `report.json`: the facts sent, the draft, every review and the token counts. It is the audit trail and the input to the eval. It stays out of git with `reports/`. |

## The same ideas in security terms

If you know Security+ or Network+, you already know this design. Only the names changed.

| In this code | The security idea | Why it is the same |
|---|---|---|
| `facts()` sends only what is needed | Least privilege, data minimization | Give a process only the access and data its job needs. |
| Code check, then three AI reviews, then Mo | Defense in depth | Layers that fail differently. A rule a program can check exactly never relies on a model. |
| The writer never reviews its own work | Separation of duties | The person who writes the check does not sign it. |
| Any error sends the template | Fail closed (fail secure) | When a control breaks, deny by default rather than let anything through. |
| `AI_DRAFTS=on` | Default deny, change control | Off unless someone turns it on on purpose, after the policy is updated. |
| Structured outputs, `_parse_draft` | Input validation | Never trust the shape of data that crosses a boundary, even your own model's. |
| Quoted website text treated as data | Injection attacks | The same reason you never build a SQL query from raw form input. |
| `ai.json` run log | Audit logging, accountability | Every run can be traced: what went in, what came out, who passed it. |
| Spend limit on its own workspace, key in `.env` | Resource limits, secret management | A key is a credential. It lives in one place, never in code or chat, and has a ceiling. |
| Mo approves every message | Human in the loop | Automation recommends, a person authorizes. |

## Running it

```
pip install -e ".[ai]"
```

Put the key in `.env` (never in `.env.example`, never in a chat):

```
ANTHROPIC_API_KEY=...
```

Try it by hand on a domain with a recorded submission. `--ai` is the decision for that one run:

```
domain-health-check report mizangroupllc.com --no-pdf --ai
```

It prints whether the draft passed, why, what it cost, and the message itself if it passed. The run is kept in
`reports/<domain>/<date>/ai.json`.

Turn it on for the hourly intake only after the privacy policy and the /digital form say report data goes to an AI
service:

```
AI_DRAFTS=on
```

## Measuring it

```
python scripts/eval_review.py reports/mizangroupllc.com/<date>/ai.json
python scripts/eval_review.py reports/mizangroupllc.com/<date>/ai.json --model claude-sonnet-5-5
```

The eval plants ten false claims in a real draft, one at a time: a passing check called broken, a warning called
fine, a check that does not exist, a wrong score, an invented measurement, a promise to look again, a competitor, a
price in words, a warning made urgent, and a guess about something that was not checked. Nine are worded to slip
past the code check, so the eval measures the AI reviewer. It also reviews the untouched draft as a control, since
a reviewer that fails everything would catch everything too. Results are saved as `eval-<model>.json`.

## What the first real run taught

The first run on mizangroupllc.com (November 4, 2026) failed all three reviews, and the template went out, which is
the design working. The reviews flagged three kinds of problem:

| Flagged | Cause | Fix |
|---|---|---|
| "Thank you for asking..." and "The full report is attached" were called unsupported | Our design: the prompt told the model to write lines that are not in the data, then the review checked them against the data | Code writes the opening now. The model writes only the bottom line, what is missing and what would help |
| "very good shape" and "the one visitors are most likely to notice" | Praise and ranking the report never states | The prompt bans them, and the code check catches the common phrases before a review is paid for |
| "DS record", "header" and "WARN" used without a plain explanation | Technical terms and status labels in owner text | The prompt says to explain each term from the check's own explanation, and the code check rejects status labels |

A second run, still on the first version, added two more lessons. The draft asked the owner to add security
settings that their website platform controls, so code now rejects any step for a check the platform sets. And the
review called a plain definition of "DS record" unsupported because the data does not define it, which clashed with
the rule to explain every term. The review now accepts a short, accurate definition that makes no claim about the
website, and the draft prefers plain words ("whoever manages your domain") to technical names.

The first run also showed the facts were sending why the run was incomplete, which held a file path from this computer. The
facts no longer include those reasons, and a check that passed now sends only its name and summary, which cuts the
tokens sent. That run cost about four cents: one Sonnet call with 8,782 tokens in and 1,695 out, and three Haiku
calls with 27,804 in and 6,175 out.

## Cost

Prices checked 2026-11-03 (per million tokens): Sonnet 5.5 $2 in and $10 out, Haiku 5.5 $0.10 in and $0.50 out.
`agents.PRICES` holds them for the estimate printed in each review email. The bill in the Console is the real
number, and any thinking the models do is billed as output.
