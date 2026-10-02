# Next build step: the site-health half

The security half is done. This step roughly doubles the report's value and is the cheapest
work left. Read with `CLAUDE.md` and `docs/REPORT-SPEC.md`; neither is superseded.

## Rules that do not change

- Every check reads from the shared `PageContext`. **No check makes its own HTTP request.**
- Keep the pure `evaluate_*` / impure fetch split, so tests run with sockets blocked.
- Register each check in `runner._checks_for` as an explicit `(category, name, lambda)` tuple.
- Category string for all of these: `Site health`.
- `CheckResult` keeps its four text fields. `summary`, `explanation`, `fix`, `details`.
- Voice: plain English, second person, no em-dashes, no exclamation marks, American English,
  team voice ("we"), **no contractions**.

## Dependency

Add `selectolax`. It is the only new one. No browser, no Lighthouse, no Playwright.

## Fixtures — already saved, do not fetch

```
tests/fixtures/mizangroupllc.com/home.html      real homepage, 97 KB
tests/fixtures/mizangroupllc.com/robots.txt
tests/fixtures/mizangroupllc.com/sitemap.xml
```

Build a `PageContext` from these in a pytest fixture and write every test against it.
`tests/conftest.py` blocks sockets, so a test that reaches the network fails loudly. That is intended.

## The checks

New package `domain_health_check/checks/site/`. One module per theme, public `check_*` returning
`list[CheckResult]`.

| Check | Weight | PASS when |
|---|---|---|
| **Search engine blocking** | **3** | No `noindex` in the robots meta tag or `X-Robots-Tag` header, and `robots.txt` does not `Disallow: /` |
| Page title | 2 | Present, 15 to 60 characters, not the domain alone |
| Meta description | 2 | Present, 70 to 160 characters |
| Canonical tag | 2 | Present, absolute, resolves to the final URL |
| Main heading | 2 | Exactly one `h1`, not empty |
| Mobile viewport | 2 | `<meta name="viewport">` present with `width=device-width` |
| Structured data matches the page | 2 | Every price and URL in JSON-LD also appears in the rendered page text |
| Heading order | 1 | No level skipped (no `h3` before an `h2`) |
| Image alt text | 1 | 90% or more of `<img>` have a non-empty, non-filename `alt` |
| Social preview | 1 | `og:title`, `og:description`, `og:image` all present |
| Sitemap and robots | 1 | Both return 200, sitemap is valid XML, and is referenced from `robots.txt` |
| Page weight | 1 | HTML under 150 KB, and under 5 seconds to first byte |
| Redirect chain | 1 | Two hops or fewer from the requested URL to the final URL |

**Search engine blocking is weight 3 and is the most valuable check in the whole tool.** A site
shipped with `noindex` left on from staging is invisible in Google and the owner usually does not know.

**Structured data matches the page** is the differentiator. Almost nobody checks it. Mizan's own
`/services` shipped retired URLs and superseded prices in JSON-LD while the visible page was correct,
which means Google can surface prices a business no longer charges.

## Scoring

`scoring.py` does not exist yet. Create it per `docs/REPORT-SPEC.md`:

- `WEIGHTS: dict[str, int]` keyed by check **name**. Weights never live on `CheckResult`.
- `earned = sum(weight * {PASS: 1.0, WARN: 0.5, FAIL: 0.0}[status])`
- `possible = sum(weight for every check that ran)`
- Checks that could not run are excluded from **both** sides. A timeout must not look like a failure.
- Nothing about the score is tunable to make a report look worse.

## Not in this step

PageSpeed Insights, Google Business Profile and multi-page crawling are later and are specified
separately. Do not pull in Lighthouse or Playwright here.
