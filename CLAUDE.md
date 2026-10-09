# domain-health-check

A CLI and small service that runs health checks on a domain and writes a plain-English
PASS / WARN / FAIL report for a non-technical business owner. It is the free report offered at
https://www.mizangroupllc.com/digital by Mizan Digital Services.

The reader is a small business owner, not an engineer. Every finding says what we found, why it matters,
and what to do about it.

## Scope policy — not negotiable

Two modes. The wall between them is the point.

**`report` — consent only.** Only ever produce a report for a domain someone submitted through the form on
/digital. Consent comes from the submission. A report is never sent to anyone who did not ask for one, and a
human reviews every one before it goes out.

Report mode may verify the links found on the consented page with a capped
set of HEAD requests (GET only when HEAD is refused), at most 80 URLs, one
request each, no more than 3 redirect hops, no response bodies stored,
same-origin and external alike. This is verification of the submitted page,
not discovery. Sweep mode never does this. The one-fetch rule stays
unchanged for sweep. Every link verification request is written to
requests.log like any other request. When the home page has no contact form,
report mode may also load the one page the site's own contact link points
to, once, to read where its contact form sends. The form is never submitted,
and that request is logged too. Sweep never does this.

**`sweep` — our own prospecting.** Loads the publicly visible home page of a local business and classifies it
(no site / weak site / could not open / fine) for our own lead list. Same footprint as one visitor. Its output
goes to us and never to the business. It must not call the report path, write a report, or send anything.
`sweep` is research; `report` is a deliverable. Keep them separable in code, and keep that provable in tests.

| Allowed | Detail |
|---|---|
| Registry and DNS (`report` only) | RDAP, DNS records, MX, SPF/DKIM/DMARC, CT logs, TLS handshake. Never touches their web server. |
| One page view (both modes) | GET the homepage, `robots.txt`, `sitemap.xml`. Same footprint as any visitor. |

Never, without written authorization: port scans, directory or path probing, vulnerability checks,
anything touching a login, or multi-page crawling. That is not an audit.

**Do not describe this tool as "passive".** Activity was never the question — consent and footprint are.
The word currently appears in the `USER_AGENT` string in `checks/http_headers.py`, the `pyproject.toml`
description, and the README. Replace all three with an accurate description of scope. The User-Agent one
matters most: it lands in other people's server logs.

The User-Agent must name Mizan and carry a URL, so anyone reading their logs can see who it was and why:

```
domain-health-check/<version> (+https://www.mizangroupllc.com/digital)
```

Other operating rules, enforced in the fetch layer rather than in individual checks: honor `robots.txt`,
one page fetch per report and per sweep visit (absolute for sweep; in report mode the exceptions are the
second view of the same page in a browser, which every report makes, the capped link verification, and the one
contact page, all described under `report` above), rate-limit per domain, dedupe repeat submissions. A human reviews every report
before it is sent — an automated FAIL that turns out to be wrong costs more than the lead was worth.

## Existing architecture — follow it, do not redesign it

```
domain_health_check/
├── cli.py          # renders a DomainReport
├── config.py       # domains.yaml -> DomainConfig
├── models.py       # Status, CheckResult, DomainReport
├── runner.py       # run_checks(DomainConfig) -> DomainReport. Returns data, never prints
├── fetcher.py      # the one page view -> PageContext
├── external.py     # outside services (PageSpeed, Places) -> ExternalContext
├── robots.py       # robots.txt as RFC 9309 reads it, for us and for Googlebot
├── scoring.py      # WEIGHTS and the 0 to 100 score
├── pricelist.py    # config/pricelist.yaml: each check's rung and the published price lines
├── layout.py       # what each report section says, shared by both formats
├── report.py       # DomainReport -> markdown
├── pdf.py          # DomainReport -> PDF (WeasyPrint)
├── mailer.py       # sends a finished report to Mo, never to the site owner
├── terminal.py     # DomainReport -> console
├── dns_utils.py
└── checks/         # each public check_* returns list[CheckResult]
```

These decisions are settled. Do not "improve" them:

**`CheckResult` has four text fields on purpose.** `summary` is one sentence of what we found.
`explanation` is why it matters, in plain English. `fix` is the action, empty when there is nothing to do.
`details` is the technical specifics for whoever implements the fix. Do not flatten these into one
message field — the split is what makes the report readable by an owner and actionable by their developer.

**`runner.run_checks` returns a `DomainReport` and prints nothing.** The CLI and the API both call it.
If you are tempted to add an `if api:` branch there, the split is wrong.

**Checks are registered in `_checks_for` as explicit `(category, name, lambda)` tuples.** This stays
readable at twenty entries. Do not replace it with a decorator registry or plugin discovery.

**Each check is wrapped so one failed lookup degrades to a WARN** rather than sinking the whole report.
Preserve that.

**`evaluate_*` functions are pure and separate from fetching.** Keep that seam — it is what makes the
tests work without network access.

## The one structural change needed

`checks/http_headers.fetch_headers` does its own request and discards the response body. The site-health
checks need that body. Eleven checks each fetching the homepage means eleven requests for one page, which
breaks the footprint rule by accident.

Promote it to `fetcher.py` returning a shared context, fetch once in `runner`, and pass it to every check
that needs the page. `http_headers` becomes a consumer; its `evaluate_*` functions do not change.

```python
@dataclass
class PageContext:
    requested_url: str
    final_url: str                        # after redirects
    redirect_chain: list[tuple[str, int]]
    status: int
    headers: dict[str, str]               # lowercased keys
    html: str
    byte_size: int                        # HTML document only, decompressed
    elapsed_ms: int                       # first request to last byte
    ttfb_ms: int                          # first request to final response headers
    robots: FetchedFile | None            # url, status, text, truncated
    sitemap: FetchedFile | None           # never follows a <sitemapindex>
```

`fetcher.py` owns robots.txt, the User-Agent, per-domain rate limiting, timeout, redirect cap and a
max-bytes guard. **A check must never make its own HTTP request.**

Use `httpx` for this rather than `urllib`: `response.history` gives the redirect chain, which is itself
one of the checks, and streaming makes the byte cap for page weight straightforward.

## Checks

| Half | Checks | Status |
|---|---|---|
| Domain health | SSL/TLS, HSTS, CSP, X-Content-Type-Options, domain expiry via RDAP, nameserver redundancy, DNSSEC, MX, SPF, DKIM, DMARC | built |
| Site health | title, meta description, headings, canonical, Open Graph tags, image alt text, JSON-LD, robots/sitemap, viewport, redirect chain, page weight, broken links, mixed content, favicon | built |

Site health needs no browser: `httpx` + `selectolax` on the one fetched page covers all of it. Speed and
mobile scoring need Lighthouse or Playwright and are a separate, heavier step — do not pull them in early.

**One check worth prioritising: does the structured data match the visible page?** Almost nobody checks
whether the prices and URLs in a site's JSON-LD still match what the page says. Mizan's own site failed
this — `/services` was publishing retired URLs and superseded prices in JSON-LD while the page itself read
correctly, which means Google can surface prices a business no longer charges.

## Adding a check

1. New module in `checks/`. Site checks go in `checks/site/`.
2. A public `check_*(…) -> list[CheckResult]`. Read from `PageContext`; make no network calls.
3. Keep the pure `evaluate_*` / impure fetch split, so the logic is testable without a socket.
4. Register it in `runner._checks_for` with its category and display name.
5. Add a fixture under `tests/` and a test. `tests/conftest.py` blocks sockets, so a test that tries to
   reach the network will fail loudly — that is intended, work from saved HTML.

## Writing findings

- Plain English. No jargon in `summary` or `explanation` without a one-line gloss; jargon belongs in `details`.
- `fix` is addressed to the owner and tells them what to ask for, not how to do it themselves.
- Do not manufacture urgency. A WARN that is cosmetic should read as cosmetic.
- **FAIL means broken today, never a risk.** Only: any certificate error that puts a browser security
  warning in front of visitors (expired, not yet valid, self-signed, untrusted issuer, wrong hostname), a
  domain that does not resolve or expires within 30 days, no MX records where mail was set up, and noindex,
  or a robots.txt that blocks Google or answers 5xx or 429.
  Everything else is WARN, including missing HSTS, CSP, nosniff, DNSSEC, SPF and DMARC, and every
  speed band. A report with risks and nothing broken says zero need action.
- Never promise to run the checks again. Re-checks belong to the paid care plan, not the free report.
- No ranking language inside a check's copy ("the most urgent item", "the most important"). A single check
  cannot know what else the report contains; ordering is the report's job.
- No em-dashes, no exclamation marks, American English. Team voice ("we"), never "I".

## Measurement traps

These produced wrong findings in a real audit. Encode them, do not rediscover them.

- A marker string in the HTML proves delivery, not effect. A CSS rule can ship and still lose a specificity
  fight. If you check whether something is applied, check the computed result.
- Check every element of a set, not the first one. One passing row says nothing about the other twenty-seven.
- Exclude `STYLE`, `SCRIPT`, `TITLE`, `META`, `LINK`, zero-dimension nodes and elements with children from
  any computed-style or contrast sweep, or you invent failures that do not exist.
- Lazy-loaded images below the fold do not load on first paint. Say which number you measured.
- A relative `Location` header on a 301 is valid. Assert the resolved destination, not the raw header.
- Lazy-load plugins put a placeholder in `src` and the real URL in `data-src` or `srcset`. Any test reading
  an image's filename must resolve the real source first, or it compares against the placeholder and
  reports the opposite of the truth. This produced a live report claiming 19 of 31 images had useful alt
  text when the real answer was 0 of 31.
- One PageSpeed lab run is noise. The same page returned 64, 79 and 80 minutes apart. Band on the median
  of three, and lead with largest contentful paint, which moves far less.

## Data, fixtures and retention

- **The only website whose content may be committed is Mizan's own.** Every other fixture is synthetic:
  handwritten HTML reproducing the conditions under test, never a real page. `reports/` stays ignored.
  Someone submitting their address to a form is not consenting to their page being published in a
  public repository. The same goes for commit messages and test comments: never name another domain or
  describe its findings.
- **The same rule governs previews.** A proposal page we generate for a prospect carries their name and may
  show a screenshot of their current site. It lives on our own domain, is marked as a proposal rather than
  their site, carries `noindex` and a `robots.txt` disallow, and its link goes to that business and nobody
  else. Never commit a prospect's page content or screenshot to the repository.
- **We keep every report run, each in its own `reports/<domain>/<date>/` folder.** A second report on the
  same domain later is how we show what changed, so nothing deletes an older run automatically. Each report
  states its run date, so an old one cannot pass for current. `reports/` stays gitignored. Cached PageSpeed
  responses are still deleted after 24 hours.

## Do not

- Reintroduce the word "passive".
- Let a check make its own HTTP request.
- Flatten `CheckResult`'s four text fields into one.
- Replace `_checks_for` with a decorator or plugin registry.
- Parse one report format to produce another. `report.py` (Markdown) and `pdf.py` both render the
  `DomainReport` through `layout.py`, so they cannot disagree. Parsing Markdown into a PDF once dropped
  an entire finding without an error.
- Add Celery or Redis. FastAPI `BackgroundTasks` plus SQLite is right for this volume; a broker is
  maintenance cost with no payoff.
- Commit a real `domains.yaml`, or the `reports/` output. `domains.example.yaml` is the one that ships.

## Repo standards

Python 3.10+, MIT. `pip install -e ".[dev]"`. pytest with sockets blocked at the fixture level. Add ruff
and a GitHub Actions workflow running both.

This repo is public and doubles as a portfolio piece, so the check structure, the tests and CI are part of
the deliverable, not overhead.
