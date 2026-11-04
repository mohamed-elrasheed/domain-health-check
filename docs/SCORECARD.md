# Scorecard

Every number here comes from a real run on mizangroupllc.com, our own site, between November 3 and 4, 2026, or
from the test suite. One site and one set of facts is a small sample, and the false claims in the eval were
planted by us. The other consented sites are being run next, and their results will be added here.

## The report

| Measure | Result |
|---|---|
| Checks in a full report | 38: 30 pass, 4 warn, 0 fail, 4 not checked |
| Score | 98 out of 100 |
| Requests made, every one logged | 92 |
| Visits to the website | one page view, plus one browser view of the same page, plus capped link checks |

## AI-written message to the owner (`agents.py`)

| Measure | Result |
|---|---|
| Good drafts passing every gate, Sonnet reviewing | 5 of 5 |
| Same, with Haiku reviewing (before the switch) | 1 of 10, mostly false alarms |
| Planted false claims caught (eval) | 10 of 10, all three reviews agreeing each time |
| Caught by the code check alone | 1 of 10 (nine were worded to get past it, so the eval measures the AI review) |
| False alarm on the untouched draft | none |
| Cost per draft (one writer call, three review calls) | about 7 cents |
| Cost of the full eval | about 40 cents |

## Findings agent (`ask.py`)

| Measure | Result |
|---|---|
| Eval, 7 questions graded by code | 7 of 7 |
| A real question, "Why is DNSSEC off, and who can fix it?" | 3 lookups, about 2 cents |
| Cost of the full eval | about 9 cents |

## Engineering

| Measure | Result |
|---|---|
| Tests | 1,251, network blocked, Python 3.11 and 3.13 in CI |
| Published vulnerabilities found by pip-audit and fixed | 62 across 5 packages |
| Secret scan | gitleaks on the full history, on every pull request |
| Problems documented with cause, fix and evidence | see [PROBLEM-LOG.md](PROBLEM-LOG.md) |

## How to reproduce

```
domain-health-check report <domain> --no-pdf --ai
python scripts/redraft.py reports/<domain>/<date>/ai.json --times 5
python scripts/eval_review.py reports/<domain>/<date>/ai-redraft.json
python scripts/eval_ask.py reports/<domain>/<date>
```

Each needs a recorded submission for the domain and `ANTHROPIC_API_KEY` in `.env`.
