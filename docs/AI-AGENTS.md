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
 3. Review x3     Sonnet   every claim against the facts, three separate calls ── any fails? template goes out
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
| Sonnet writes, Sonnet reviews in separate calls | Haiku reviewed first, at a twentieth of the price, and passed 1 good draft in 10, mostly on false alarms. Sonnet passed 2 in 5 and every flag it raised was a real mistake. Each review is a fresh call that never sees the draft call, so the writer still never grades its own work. Opus is next if Sonnet ever is not enough. |
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

## Changing a prompt

After the first `--ai` run, try prompt changes against the saved facts instead of running the report again:

```
python scripts/redraft.py reports/mizangroupllc.com/<date>/ai.json
```

It runs the draft, the code check and the three reviews on the facts in that log, prints the result, and saves it as
`ai-redraft.json`. The website is never contacted, so testing a prompt does not spend the report's one-visitor
footprint, and it takes seconds instead of a full run.

One result is a sample of one. To measure how often drafts pass, make ten (about 30 cents):

```
python scripts/redraft.py reports/mizangroupllc.com/<date>/ai.json --times 10
```

The saved file keeps every attempt. Its top-level draft is the first one that passed, which is the one to plant
claims in with the eval below.

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

The third run, on the tuned version, cut the flags from nine to two and the cost from four cents to under three.
Both flags were real: the draft dropped the report's own hedge ("in some cases") and called a Google tool free, which
the data never says. The draft prompt now says to keep the data's hedges and add no details of its own about a term
or a tool.

The fourth run, still on the third run's prompts, passed two of three reviews. The one failure was the same added
detail: the draft called PageSpeed Insights "Google's free tool" again. A model can repeat a mistake after being
told not to, so the code check now rejects "free", "no cost" and "costs nothing" unless the report itself says so.
That rule costs nothing to run and never relies on a review catching it.

The fifth try, a redraft from the saved facts with the hedge rule and the "free" rule, passed two of three
reviews again. Every claim was supported. The failing review read "explain a term in the same sentence" literally,
while the draft explained each term in the sentence right after it, which reads naturally. Both prompts now allow
the same sentence or the one right after it, and a test keeps the two prompts on the same rule. The review also
caught "DS record" left unexplained, which was a real miss and stays a failure.

The sixth try passed two of three reviews once more, on a different nitpick: the draft grouped two checks as
"browser security settings" and said DNSSEC signs "address records", narrower than the data's "DNS records". Each
try now fails one review on a new detail, which says the drafts are close and the models vary from run to run. Two
changes follow. The draft prompt says to describe each finding in its own summary and explanation's words, with no
labels of its own, which tightens the writer instead of loosening the reviewer. And `redraft.py --times 10` now
measures the pass rate over ten drafts, because one pass or fail is a sample of one. Production still never
retries: a failed draft sends the template.

Ten drafts from the same facts then passed one time in ten, at about 28 cents for all ten. The failures were mostly
the reviewer's, not the writer's. Four of the ten flagged "Slow pages lose visitors, and speed is a small factor in
Google rankings", which is the check's own explanation word for word. One flagged Cloudflare as a competitor,
though the check's fix names it. Several reasons said a sentence was acceptable and then failed it anyway. A few
catches were real: a draft said the unchecked items were listed "where they matter" when it listed none, and one
called a Content Security Policy "a list". The finding is that Haiku is not steady enough for this judgment, so
`redraft.py --review-model` now measures another reviewer on the same facts before the default changes.

Five drafts with Sonnet as the reviewer passed two. The three reviews agreed with each other almost every time,
and every flag was a real mistake by the writer: two drafts promised to say "below" which checks were not checked
and never did, and two used "DS record" without explaining it. Sonnet is now the reviewer. Both mistakes are fixed
where they start. The code check rejects any mention of checks that were not checked, since the report already
lists them, and the DNSSEC check's own fix now explains a DS record in plain words, which also helps the owner
reading the report itself.

The first run also showed the facts were sending why the run was incomplete, which held a file path from this computer. The
facts no longer include those reasons, and a check that passed now sends only its name and summary, which cuts the
tokens sent. That run cost about four cents: one Sonnet call with 8,782 tokens in and 1,695 out, and three Haiku
calls with 27,804 in and 6,175 out.

## The findings agent

`agents.py` is a fixed workflow on purpose: a business owner reads what it writes, so no model decides what
happens next. `ask.py` is an agent: Mo asks a question about a saved report, and the model decides which tools to
call, reads the results, and decides when it has enough.

```
domain-health-check ask reports/mizangroupllc.com/<date> "Why is DNSSEC off, and who can fix it?"
```

```
question ──> Sonnet ──> wants a tool? ── yes ──> code runs it on the saved folder ──> result back to Sonnet ─┐
                 ▲                                                                                          │
                 └──────────────────────────── up to 8 rounds ──────────────────────────────────────────────┘
                 │ no
                 ▼
          answer + "Sources:" ──> code checks every source was really looked up ──> printed for Mo, logged
```

| Tool | Reads |
|---|---|
| `get_overview` | domain, date, score, reading, complete or not, platform, number of requests |
| `list_checks` | every check, its status and one-line summary |
| `get_check` | one check in full: explanation, fix, technical details, certain or not, who can fix it |
| `get_prices` | who can fix a check and the matching lines from the published price lists |
| `search_requests` | up to 30 matching lines of the request log |

| In this code | The security idea |
|---|---|
| Five read-only tools, no network, no path argument, nothing that writes | Least privilege. Safety comes from what the agent can reach, not from what it is told. A fooled model can only answer wrongly. |
| Tool results treated as data | Injection defense. The report quotes the website's own text, and that text never becomes an instruction with power behind it. |
| `MAX_STEPS = 8` | Resource limits. A model that loops is stopped, the way a rate limit stops a script. |
| Sources checked by code, at the depth claimed | Integrity check. Each source says (list) or (full). A (full) source must have been opened with `get_check` or `get_prices`, a (list) source must at least have been listed, and every dollar amount must come from a price line the agent read. |
| `ask.jsonl` | Audit logging. Every question, every tool call and every answer. |
| Answers go to Mo only | Data classification. Prices and the request log are fine for the operator, never for the customer message. |

The first real eval passed 5 of 7, and both failures were ours: the agent listed every check, answered which
ones warn correctly, and cited them, but the source check only counted a check opened in full. The list shows a
check's status and summary and nothing else, so it is a real source for "which checks warn" and not for a fix or
a price. Sources now carry their depth, (list) or (full), and code holds each one to it. The answers themselves
were right in all seven, and a real question
("Why is DNSSEC off, and who can fix it?") took three lookups and about two cents.

`scripts/eval_ask.py <folder>` builds questions whose answers code already knows from the report (which checks
warn, the score, which were not checked, the request count, who can fix a finding, and one question the report
cannot answer), asks the agent each one, and grades the answers with code rather than another model.

## Cost

Prices checked 2026-11-04 (per million tokens): Opus 5.5 $4 in and $20 out, Sonnet 5.5 $2 in and $10 out, Haiku
5.5 $0.10 in and $0.50 out. With Sonnet writing and reviewing, a draft costs about 7 to 8 cents.
`agents.PRICES` holds them for the estimate printed in each review email. The bill in the Console is the real
number, and any thinking the models do is billed as output.
