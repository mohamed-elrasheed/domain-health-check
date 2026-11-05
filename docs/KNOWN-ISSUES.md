# Known issues

Found by two independent audits (November 4 and 5, 2026, on two different models) and judged lower risk than the
fixes already shipped. None of them can send anything to a business: every failed or doubtful draft falls back
to the template, and a person reviews every report before it goes out. Each one moves to
[PROBLEM-LOG.md](PROBLEM-LOG.md) in the pull request that fixes it.

## Website text can widen what the code check accepts
`facts()` sends every passing check's summary, and some quote the site itself (the page title, the main heading).
`code_check` treats the whole facts JSON as grounded, so a number, a capitalized word or "free" that appears in a
site's own heading also passes the number, capitals and cost rules. The site text also reaches the models, which
are told to treat it as data. Fix: send passing checks as name and status only, cap quoted site text, and build
the grounded set from code-written fields.

## The code check has small gaps
- Numbers are grounded against the facts' timestamp, so "within 14 days" can pass because 14 appears in the date.
- `" -- "` passes the dash rule; "immediately", "right away" and "as soon as possible" pass the timing rule; "we
  will look at it next month" passes the re-check rule.
- The same check listed twice in different words is not caught.
- A few rules fire on normal English: "your free report", "error-free", a site title such as "My Bakery" (first
  person), "look again", "not checked by Google".

Effect today: a wasted model call or a template sent instead of a draft. Fix each with a test, then rerun
`scripts/redraft.py --times 5` on the saved sites to confirm the pass rates hold.

## Smaller items
- `agents.run` calls `facts()` and writes its log outside a catch-all, so its "never raises" promise depends on
  the report having been written first. Wrap the whole body.
- `netguard.public` treats a name that fails to resolve as allowed, leaving the request to fail on its own. A
  transient DNS error followed by a private answer could slip through. Pinning the connection to the checked
  address would close this and DNS rebinding together.
- The sweep's client (`sweep/load.py`) does not use `netguard.PublicOnly`. It only loads sites from our own lead
  list, so the exposure is small.
- The three reviews are the same model, prompt and input, so they are correlated rather than independent checks.
- Some docstrings and the README layout list predate the editor and the newer modules.
