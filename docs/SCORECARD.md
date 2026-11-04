# Scorecard

Numbers come from real runs between November 3 and 4, 2026: mizangroupllc.com, our own site, and a consented
outside business's site (not named here; its owner agreed in writing). The rest come from the test suite. The
false claims in the eval were planted by us. The remaining consented site is being run next.

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
| Cost per draft with the editor (five calls) | about 9 cents |

## The editor, on an outside business's report

The editor reads the whole message as a busy owner would, after the three reviews, and must pass it too.

| Measure | Result |
|---|---|
| Drafts passing all five gates, first rounds | 0 of 16 |
| Editor on a message a person judged ready to send | 5 of 5 passed, so the editor is fair |
| Drafts passing all five gates, after fixing the causes (PRs #23 to #27) | 4 of 5 |
| The one failure | a real catch: the meta description explained twice. Production sends the template |
| What the fixes were | mostly our own report copy, plus keeping one phrase out of the writer's input |
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
| Tests | 1,273, network blocked, Python 3.11 and 3.13 in CI |
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
