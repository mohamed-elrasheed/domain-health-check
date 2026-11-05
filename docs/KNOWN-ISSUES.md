# Known issues

Found by two independent audits (November 4 and 5, 2026, on two different models) and judged lower risk than the
fixes already shipped. None of them can send anything to a business: every failed or doubtful draft falls back
to the template, and a person reviews every report before it goes out. Each one moves to
[PROBLEM-LOG.md](PROBLEM-LOG.md) in the pull request that fixes it.

## Website text in a finding's summary
Passing checks no longer send a summary (PR #40), so most site text never reaches a model. A warning's own
summary can still quote the site, such as a page title that is too long, and a word in that title then counts as
"grounded" for the code check. Capping quoted site text inside summaries would close it.

## Smaller items
- `netguard.public` treats a name that fails to resolve as allowed, leaving the request to fail on its own. A
  transient DNS error followed by a private answer could slip through. Pinning the connection to the checked
  address would close this and DNS rebinding together.
- The sweep's client (`sweep/load.py`) does not use `netguard.PublicOnly`. The sweep is walled off from report
  code by a test, so the guard would need its own copy there. It only loads sites from our own lead list, so the
  exposure is small.
- The three reviews are the same model, prompt and input, so they are correlated rather than independent checks.
- "look again" with no subject still trips the re-check rule, which only costs a run.
- The README layout list does not yet name every newer module (intake, pipeline, watchdog, linkcheck, netguard).
