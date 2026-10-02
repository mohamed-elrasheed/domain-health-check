# Step 3: speed and Google Business Profile

Comes after `docs/NEXT-SEO.md`. Read with `CLAUDE.md` and `docs/REPORT-SPEC.md`.

Two external data sources. Both are free at our volume. Both are **optional** — with no API key
configured, their checks do not run at all.

## The architectural problem, and the seam

`CLAUDE.md` says a check must never make its own HTTP request. These checks need external APIs, so
do not weaken that rule. Add a second context fetched once in `runner`, beside `PageContext`:

```python
@dataclass
class ExternalContext:
    psi_mobile: dict | None = None      # raw PageSpeed Insights response
    psi_desktop: dict | None = None
    place: dict | None = None           # raw Places API Place Details response
    errors: dict[str, str] = field(default_factory=dict)   # source -> why it is missing
```

`runner` populates it, checks read from it, `evaluate_*` stays pure. A `None` means **did not run**,
never a failure. Per `REPORT-SPEC.md`, a check that could not run is excluded from both sides of the
score. A missing API key must not cost the client points.

## 1. PageSpeed Insights

`GET https://www.googleapis.com/pagespeedonline/v5/runPagespeed`

Parameters: `url`, `strategy` (`mobile` or `desktop`), repeated `category`
(`performance`, `accessibility`, `best-practices`), `key`.

**An API key is now mandatory.** Keyless requests return HTTP 429 with
`quota_limit_value: "0"` — verified 2026-10-01, not assumed. Create a Google Cloud project, enable
the PageSpeed Insights API, make an API key. Free tier is 25,000 requests a day, about 240 a minute.

Read the key from the environment. Never commit it.

### Traps, all of which will bite

- **`lighthouseResult.categories.*.score` is a float from 0 to 1, not 0 to 100.** The reference page
  says 0–100 and the JSON says otherwise. Multiply by 100 and round.
- **`score` can be `null`** when a category errors. Treat null as did-not-run.
- **Calls take 20 to 90 seconds.** Use a long timeout and run mobile and desktop concurrently. A
  timeout is did-not-run, not a WARN.
- **`loadingExperience` is absent for low-traffic sites.** It is real Chrome user data and Google
  only publishes it above a traffic threshold. When it is missing, say
  "your site does not yet get enough traffic for Google to publish real-world speed data" and score
  nothing. **Do not report that as a problem.** Most of our prospects will be in this bucket.
- **`originLoadingExperience` is the whole domain, not the page.** Do not present one as the other.
- **Lab scores move between runs** on the same URL. Never put a lab number in a sentence that implies
  precision, and never compare two runs as if a 4-point move meant something.

### What to score

| Check | Weight | Source |
|---|---|---|
| Real-world loading speed | 2 | `loadingExperience.overall_category`. Skip entirely when absent |
| Mobile speed | 1 | `lighthouseResult.categories.performance.score`, mobile strategy |
| Accessibility | 1 | `categories.accessibility.score` |
| Best practices | 1 | `categories['best-practices'].score` |

**Do not score Lighthouse's `seo` category.** Step 2 already checks titles, descriptions, canonicals
and viewport directly. Counting both double-weights the same findings and inflates the score's swing.

Bands: 90 and above good, below 90 could be improved (a slow page is never broken, so never a FAIL; see
CLAUDE.md). Below 50 is Google's lowest band and the wording says so. These are Google's own
bands, so our report agrees with any other tool the client runs.

### Caching

PSI is slow and nondeterministic. Cache the raw response per `(domain, strategy)` for 24 hours. The
cache is deleted once it expires, so a later report is always a fresh call, not a replay.

## 2. Google Business Profile

`POST https://places.googleapis.com/v1/places:searchText` to resolve the business, then
`GET https://places.googleapis.com/v1/places/{id}` with a field mask.

Pricing verified 2026-10-01: field masks are tiered, and every field worth having —
`websiteUri`, `nationalPhoneNumber`, `regularOpeningHours`, `rating`, `userRatingCount` — sits in the
Enterprise tier, which carries **1,000 free calls a month**. `displayName`, `businessStatus` and
`primaryType` are Pro (5,000 free). At a handful of leads a week this never leaves the free tier, but
one field pulls the whole response up to its tier's price, so keep the mask tight and deliberate.

### This needs a form change first

Places searches by **name and location**, not by domain. The `/digital` form currently collects the
person's name, email, phone, website and a description. It does not collect the **business name** or
**city or ZIP**, so there is nothing to search with.

Add those two fields to the form. Until then this half cannot run, and it should report
did-not-run rather than guessing a match from the domain.

### Matching rules — be strict

A wrong match is worse than no match. Only accept a result when the business name is a close match
**and** at least one of these corroborates: the `websiteUri` host equals the submitted domain, or
`nationalPhoneNumber` equals the submitted phone. Otherwise report that we could not confidently find
their listing, and say so plainly. **Never show a client another business's reviews.**

### What to score

| Check | Weight | PASS when |
|---|---|---|
| Google Business Profile exists | 3 | A confident match was found and `businessStatus` is `OPERATIONAL` |
| Profile completeness | 2 | `websiteUri`, `nationalPhoneNumber` and `regularOpeningHours` all present |
| Website link matches | 2 | `websiteUri` host equals the domain we checked |
| Reviews | 1 | `userRatingCount` of 5 or more |

Weight 3 on existence is correct. For a barbershop in Centreville, no Google Business Profile costs
more customers than every header in this tool combined.

**Do not score the rating value.** A 3.8 average is not a defect we can fix, and telling an owner
their reviews are bad is not a finding, it is an insult.

## Fixtures

Save one real response of each into `tests/fixtures/` and write every test against the saved JSON.
`tests/conftest.py` blocks sockets. Before writing the field mapping, look at a real response and
confirm the shape — do not write it from the reference page, which is wrong about the score scale.

## Voice reminder

Plain English, second person, no em-dashes, no exclamation marks, American English, team voice,
no contractions. A speed score is not an emergency. Write it like it is not.
