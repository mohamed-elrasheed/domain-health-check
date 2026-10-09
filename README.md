# domain-health-check

A command-line tool that runs health checks on a list of domains and writes a plain-English report
for each one, suitable for handing to a non-technical client. It produces the free report offered at
[mizangroupllc.com/digital](https://www.mizangroupllc.com/digital).

Every check returns **PASS**, **WARN** or **FAIL**, with an explanation of why it matters and what to do about it.
FAIL means something is broken today, never just a risk: a certificate error that shows visitors a browser
security warning, a domain expiring within 30 days, no mail servers, or a site telling Google not to list it. Everything
else that could be better, including missing HSTS, CSP or DMARC, is a WARN.

> **Scope.** Full reports run only on domains submitted through the form at
> [mizangroupllc.com/digital](https://www.mizangroupllc.com/digital); the submission is the consent, and a
> report is never sent to anyone who did not ask for one. Separately, `sweep` looks at the publicly visible
> home page of a local business while we research prospects for our own services. That is the same single
> page view any visitor or search engine makes, its result goes to us and never to the business, and it
> never produces or sends a report.
> Each report touches public DNS and registry (RDAP) records, one TLS handshake, and a single page
> view: the home page plus the `robots.txt` and sitemap files search engines read, the same footprint
> as one ordinary visitor. It honors `robots.txt` and never opens the sitemaps a sitemap index lists.
> A report also loads the home page once more in a standard browser, and says so in the report: the checks an
> owner verifies by looking at their own screen (main heading, heading order, image descriptions, structured
> data against the page) are judged on what a visitor sees, counting only elements on screen at phone or
> desktop width. The other site checks read the page as search engines and link previews do. `sweep` keeps the
> single view: it runs on sites that never asked us to look.
> It does **not** port-scan, probe paths, test for vulnerabilities, touch a login, crawl other pages,
> or send email. Every request
> identifies itself with the User-Agent `domain-health-check/0.1 (+https://www.mizangroupllc.com/digital)`
> so anyone reading their server logs can see who it was and why.

## What it checks and why

### Website security

| Check | PASS | WARN | FAIL |
|---|---|---|---|
| **SSL certificate**: expiry, hostname match, issuer | valid for 30+ days | expires in under 30 days, or site unreachable | any error that shows visitors a browser security warning: expired, not yet valid, self-signed, untrusted issuer, wrong hostname |
| **TLS version** | TLS 1.2 or 1.3 | older than TLS 1.2 | |
| **HSTS** | `max-age` of at least 180 days | missing, short `max-age` or malformed | |
| **Content-Security-Policy** | present | missing, or report-only | |
| **X-Content-Type-Options** | `nosniff` | missing or other value | |

- **SSL/TLS.** TLS encrypts the connection between a visitor and the website, and the certificate
  proves the site is really who it claims to be. A certificate is issued by a trusted certificate
  authority (the *issuer*), is valid only for the names written on it (*hostname match*), and has an
  expiry date. When any of those is wrong, browsers show a full-page warning.
- **HSTS (HTTP Strict Transport Security).** A response header that tells browsers: "only ever
  connect to me over HTTPS." It stops attackers on public Wi-Fi from downgrading visitors to an
  unencrypted connection.
- **Content-Security-Policy.** Tells the browser which sources of scripts and content to trust, so
  injected malicious code won't run.
- **X-Content-Type-Options: nosniff.** Stops browsers guessing a file's type, which could otherwise
  make an innocent-looking file run as code.

### Domain & DNS

| Check | PASS | WARN | FAIL |
|---|---|---|---|
| **Domain registration** (RDAP) | 60+ days until expiry | under 60 days, or no data available | under 30 days, or expired |
| **Nameservers** (NS) | two or more | only one, or none | |
| **DNSSEC** (DS record) | DS record present | not enabled | |

- **RDAP (Registration Data Access Protocol).** The modern, JSON-based replacement for WHOIS. The
  tool looks up which registry runs the domain's TLD in [IANA's bootstrap file](https://data.iana.org/rdap/dns.json),
  then asks that registry for the domain's expiry date. A missed renewal takes the website and
  email offline and can let someone else register the name.
- **NS records.** Name the servers that answer every DNS question about the domain. Two or more
  means one can fail without taking everything down.
- **DNSSEC.** Adds digital signatures to DNS answers so they can't be forged. The parent zone
  (e.g. `.com`) vouches for the domain by publishing a **DS (Delegation Signer)** record, which is a
  fingerprint of the domain's signing key. No DS record means DNSSEC isn't switched on. (A DS record
  shows DNSSEC is enabled. It doesn't fully validate every signature.)

### Email security

| Check | PASS | WARN | FAIL |
|---|---|---|---|
| **MX** | mail servers listed, or a "null MX" | | no MX records |
| **SPF** | one record ending `-all` or `~all` (or using `redirect=`) | `?all`, no `all`, missing, more than one record, or `+all` | |
| **DKIM** | a key found on a selector | only revoked keys, or none found | |
| **DMARC** | `p=quarantine` or `p=reject` | `p=none`, missing, duplicated, or invalid | |

- **MX records.** Where to deliver email for the domain. A "null MX" (`0 .`) is the correct way to
  say a domain never receives mail.
- **SPF (Sender Policy Framework).** A TXT record listing the servers allowed to send email for
  the domain. It ends with a rule for everyone else: `-all` (reject), `~all` (mark suspicious),
  `?all` (no opinion), or `+all` (allow anyone, which is dangerous). Only one SPF record is allowed.
- **DKIM (DomainKeys Identified Mail).** The sending server signs each email. The public key lives
  in DNS at `<selector>._domainkey.<domain>`. The *selector* is a label chosen by the email
  provider, so it can't be discovered and has to be configured. Common ones: `google` (Google
  Workspace), `selector1`/`selector2` (Microsoft 365), `fm1`–`fm3` (Fastmail). If you don't
  configure any, those are tried.
- **DMARC.** A TXT record at `_dmarc.<domain>` that tells receivers what to do with mail failing
  SPF and DKIM: `p=none` (just report), `p=quarantine` (spam folder) or `p=reject` (refuse).

### Site health

No check makes a request of its own. All of them read the one page view, except the link and icon checks,
whose few extra requests the fetch layer makes first (see below). A check with nothing to
measure (no images, no structured data, a page built entirely by scripts) is marked as not run and
left out of the score rather than passed.

| Check | PASS | WARN | FAIL |
|---|---|---|---|
| **Search engine blocking** | no `noindex`, and robots.txt lets Googlebot in | | `noindex` in the page or `X-Robots-Tag`, or robots.txt blocks Googlebot from `/` |
| **Page title** | 15 to 60 characters | missing, too short, too long, or just the domain | |
| **Meta description** | 70 to 160 characters | missing, too short or too long | |
| **Canonical tag** | present and on the same site | missing, relative, or another site | |
| **Main heading** | exactly one non-empty `h1` | none, several, or empty | |
| **Mobile viewport** | `width=device-width` | missing, or present without it | |
| **Structured data matches the page** | every JSON-LD price is in the page text and every same-site URL is linked or in the sitemap | a value that is not, or invalid JSON-LD | |
| **Heading order** | no level skipped | an `h3` before an `h2`, and so on | |
| **Image alt text** | 90% or more of `<img>` have a real description | below 90% | |
| **Social preview** | `og:title`, `og:description`, `og:image` | any missing | |
| **Sitemap and robots** | both found, sitemap valid, listed in robots.txt | any of those not true | |
| **Page weight** | HTML under 150 KB and first byte under 5 seconds | either over | |
| **Redirect chain** | two redirects or fewer | more than two | |
| **Broken links** | every link to another page on the site that we verified works | one ends in an error, a timeout or more than 3 redirects | |
| **Links to other sites** | the same, for links to other sites | the same; never a FAIL, since the owner does not control those sites | |
| **Mixed content** | everything on the secure page loads over https | an image, script, stylesheet, font or framed page over plain http | |
| **Favicon** | the site's own icon resolves to an image | no icon, or a website builder's standard icon | |

- **Search engine blocking** is the most valuable check here: a site launched with `noindex` left
  on from staging is invisible in Google, and nothing on the page looks wrong. robots.txt is read the
  way Google reads it (`*` and `$` wildcards, longest rule wins) by `robots.py`, the same reader that
  decides whether we may load a page ourselves. Python's `robotparser` only does this from 3.14.
- **Structured data matches the page** catches JSON-LD that still carries retired URLs or old prices
  after the visible page was updated. Each match in the details says which evidence it rested on:
  page text, a page link, or the sitemap.
- Measured on the HTML as delivered, before scripts run. Page weight is the HTML document alone;
  images, scripts and styles are not loaded. A sitemap index is recorded but never followed.
- **Broken links** and **Links to other sites** are the one place the report requests anything beyond the page:
  each link on the consented page, once, under the cap in CLAUDE.md (at most 80, HEAD and GET only when HEAD is
  refused, 3 redirects, no response bodies). That is `linkcheck.py`, which sweep can never reach.
- **Mixed content** reads the resource list of the page as the browser loaded it, so files a script adds count.
- **Favicon** resolves the icon the way a browser does, in at most two requests. It can also flag a website
  builder's standard icon, but only from entries in `config/platforms.yaml` that cite a source. None is listed
  yet, so for now it reports a missing icon and nothing else.

### Speed (optional, from Google PageSpeed Insights)

Runs only when `PAGESPEED_API_KEY` is set. With no key, these rows do not appear and cost nothing.
Mobile is tested three times and desktop once, all four at the same time. Each raw response is cached
for 24 hours in `.cache/pagespeed/` (gitignored), then deleted. We only ask Google to test a page we were able, and allowed, to load
ourselves.

| Check | PASS | WARN | FAIL | Not run |
|---|---|---|---|---|
| **Real-world loading speed** | Chrome field data `FAST` | `AVERAGE` or `SLOW` | | Google publishes no field data for the page (the usual case for a small business) |
| **Mobile speed** | Lighthouse performance 90+ | below 90 | | score null or missing |
| **Accessibility** | Lighthouse accessibility 90+ | below 90 | | score null or missing |
| **Best practices** | Lighthouse best-practices 90+ | below 90 | | score null or missing |

- Bands are Google's own, so the report agrees with any other tool the owner runs. Lab results move
  between runs (one live check returned 64, 79 and 80 for the same page minutes apart), so the band
  comes from the median of three mobile runs, and the spread goes in the details: "Three runs
  returned 64, 79 and 80 on 2 October 2026".
- The mobile speed finding leads with largest contentful paint in seconds ("takes about 4.7 seconds to
  show its main content"), which moves far less than the score and means more to an owner. A score is
  never a bare number in a summary.
- `categories.*.score` is 0 to 1 and arrives as either a float or an int. Lighthouse's `seo` category
  is not scored: the site checks above already measure the same things directly.
- Whole-site field data (`originLoadingExperience`) is labeled as the whole site, never as the page.
- A timeout, an API error or a skipped test is one "Google speed test" row that did not run, and is
  left out of the score.

### Google Business Profile (optional, from Google Places)

Runs only when `PLACES_API_KEY` is set and the business name is known (`--business-name`, or
`business_name` in `domains.yaml`). The `/digital` form submits it as `business-name`, with the optional
`city` beside it; the phone number arrives in one of the form's unnamed `field-N` slots.

| Check | Weight | PASS | WARN | Not run |
|---|---|---|---|---|
| **Google Business Profile** | 3 | a confirmed listing marked open | closed; not findable by name and place; or a similar listing that does not link back | no business name given, or the API did not answer |
| **Profile completeness** | 3 | website, phone and opening hours all listed | any missing | |
| **Profile website link** | 3 | links to the domain we checked | missing, or another site | |
| **Reviews** | 3 | 5 or more | fewer | |
| **Profile phone number** | 2 | the listing's number is on the home page | the home page shows other numbers only | |
| **Tap to call** | 2 | every phone number on the home page is a tap-to-call link | a number is plain text | |
| **Contact form** | 2 | the contact form says where it sends | its action is empty, "#" or a script address | |

- **A wrong match is worse than none.** A listing is used only when its name closely matches and its
  website is on the submitted domain, or its phone is the submitted number. A search for one real
  business returned a different one with a near-identical name; a shared word is never enough.
- Not being findable is the finding: "We could not find a Google Business Profile for this business by
  name and location. Either there is not one, or it is not set up to be found." It never claims the
  business has no profile, and no extra calls are spent trying to prove it.
- The star rating is never requested, scored or shown. Field masks are billed by their most expensive
  field: the search asks only for ids and names, and details are fetched for at most three name matches.

## Setup

Requires Python 3.10+ (developed on 3.14). Runtime dependencies: `dnspython`, `httpx`, `PyYAML`, `selectolax` and `weasyprint`.

```powershell
git clone https://github.com/mohamed-elrasheed/domain-health-check.git
cd domain-health-check
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -c requirements.lock -e ".[dev]"
```

Every dependency is pinned. `pyproject.toml` pins the direct ones and `requirements.lock` pins everything they
pull in, so a report run today and one run next month use the same code. Installing with `-c requirements.lock`
is how CI installs; plain `pip install -e ".[dev]"` also works but lets the indirect packages float.

To include the speed checks, copy `.env.example` to `.env` and add a PageSpeed Insights API key.
`.env` is gitignored; the tool reads it at startup and never overrides a variable already set.

Then create your own domain list. `domains.yaml` is gitignored, so real client domains never end
up in the repository:

```powershell
Copy-Item domains.example.yaml domains.yaml   # macOS/Linux: cp domains.example.yaml domains.yaml
```

```yaml
domains:
  - name: example.com
    dkim_selectors: [google]
  - name: example.org
    dkim_selectors: [selector1, selector2]
  - example.net            # no selectors: the common ones are tried
```

## Usage

```powershell
# First, record that the owner asked (source: form, email, in-person or own)
domain-health-check record-submission example.com --source form --email owner@example.com
domain-health-check record-submission example.com --source in-person --received 2026-10-01

domain-health-check report example.com                  # check one domain
domain-health-check report                              # check everything in domains.yaml
domain-health-check report -c other.yaml -o out         # different config file / report folder
domain-health-check report example.com --no-pdf         # Markdown only, no PDF
domain-health-check report example.com --email          # PDF, emailed to you for review (needs SMTP_* in .env)
python -m domain_health_check --help
```

A report runs only for a domain with a recorded submission. Records live in `submissions.yaml` (gitignored,
since they hold email addresses); a form or email submission must carry the address it came from. Without a
record the report refuses and prints the `record-submission` command to add one. A domain on the lead list is
refused whatever the record says. Every run is appended to `logs/report-runs.log` (gitignored) with the record
it ran on.

Every report is written to its own folder, `reports/<domain>/<date>/` (gitignored):

| File | What it is |
|---|---|
| `report.pdf` | The report for the owner, after a human has reviewed it. `--no-pdf` skips it. |
| `report.md` | The same report as Markdown. Both are rendered from the same data, never one from the other. |
| `report.json` | Every result with its status and details, whether the run was complete, and if not, why. |
| `requests.log` | Every request the run made, one per line: time, source, method, target, outcome. |

`requests.log` covers the page fetch (robots.txt, the home page, the sitemap), every request the browser made
while rendering the page, each link verified, the icon, RDAP, the TLS handshake, each DNS query, and the PageSpeed
and Places calls. API keys
are masked before anything is written. Every PDF page is stamped with the package version and the run date, so
a report in someone's inbox says exactly which code produced it.

Every run is kept. A new report goes in a new dated folder and never deletes an older one: a second report on the
same domain later is how we show what changed. Two runs on the same day share a folder, and the later one replaces
the earlier.

### Sweep (our own prospecting)

`sweep` is a separate command with its own entry point, not a mode of the report. It reads a lead list,
classifies each business, and writes the result for us alone:

```powershell
pip install -e ".[sweep]"; playwright install chromium     # once, for screenshots
domain-health-check-sweep leads.json                        # every lead
domain-health-check-sweep leads.json --trade barber         # one trade: auto, barber, cleaning, landscaping, food
domain-health-check-sweep leads.json --only some-lead-id    # specific leads
domain-health-check-sweep leads.json --no-browser           # HTML as delivered, no screenshots
domain-health-check-sweep leads.json --force                # ignore the cache and the cooldown (another visit)
```

The verdict answers one question, is there a website job here:

| Verdict | Meaning |
|---|---|
| `none` | No site they own. A Facebook page, a booking link, a delivery app or a directory listing does not count. |
| `weak` | A site of their own with a specific, nameable fault. |
| `unver` | Every attempt failed or was blocked. The reason is recorded, because it decides what to do next. |
| `good` | No website job. |

A `weak` verdict comes with the single most damaging fault, as one sentence quoting the page: a domain that does
not exist, a certificate warning, a robots.txt that answers with a server error or keeps Google off the home page,
a live link to a staging address, template placeholders a visitor can actually see, no mobile layout, a free
builder subdomain (with the vendor's copyright when it is theirs in the footer), the template's demo or stock
pictures, or a contact form with nowhere to send. A fault someone found by hand and recorded on the lead competes
by rank and is marked as found by hand.

Everything real that is not a website job is a flag, and never changes the verdict: a free webmail contact
address on a site with its own domain, a contact address on a different domain, a misspelled day in the hours,
an old copyright year. A `good` site with flags is a tune-up or business email job, not a rebuild.

Each business costs one visit: robots.txt, then the home page, which `sweep` honors, loads once in a browser at
phone width, photographs at 390 by 844 and again at 1280 wide, and closes. Nothing else is requested, nothing is
sent, and no report or PDF is written. A visit is cached for seven days, and no domain is fetched again within
seven days of the last fetch; a re-run inside that window re-reads the stored page. A 429 backs the domain off for
30 days, or longer if its `Retry-After` asks. Output goes to `sweep-output/<lead-id>/`, the cooldown state to
`sweep-output/_state.json` and cached pages to `sweep-output/_cache/`, all gitignored. The lead list and everything
under `sweep-output/` describe real businesses and must never be committed.

The two modes are kept apart in code: `tests/test_sweep_wall.py` fails if anything `sweep` imports can reach
registry, DNS, TLS, report, PDF or mail code, and runs a sweep in a fresh interpreter to check what actually loaded.

### The lead board export

Every sweep run regenerates `sweep-output/board.json` (gitignored), the contract with the lead board, for every
lead in the list: verdict and hand verdict, the fault with its source (`detector` or `hand`, a hand fault always
carrying the date it was observed) and date, flags, the name from their own site and whether it is confirmed,
screenshot and preview links, whether hours are confirmed, and the last and next fetch dates. A lead sweep could
not reach keeps its last known values and gets `blocked_until`. `demand` and `demand_term` stay null until there
is a keyword volume export. The field list is fixed in `domain_health_check/sweep/board.py` and pinned by a test;
nothing typed on the board (notes, call status) is ever copied into it. `--board-only` regenerates it without
sweeping. The board is built only from `leads.json` at the repository root with every `leads-*.patch` there fully
applied; otherwise the run says why, leaves `board.json` untouched and exits with status 2. Screenshots are published to the private previews repository under `_shots/<lead-id>/`, never to this one.

### Previews (proposal pages)

`domain-health-check-preview <lead-id>` writes a proposal page for one lead into a separate, private
repository (`../mizan-previews` by default), served at `preview.mizangroupllc.com/<lead-id>/`. It puts the
business's current site, as `sweep` photographed it, beside the site we would build, both at phone width, then
their own numbers and details. Every page opens with "A proposal for <business>, prepared by Mizan Group LLC.
Not an official site.", carries `noindex, nofollow`, and the repository disallows all crawling. Facts we do not
have are shown as missing, never guessed. `--push` commits and pushes the lead's folder. Nothing about a prospect
is ever written into this repository; it sits behind the same wall test as `sweep`.

There is one proposed-site template per trade (auto repair, barbershop, cleaning, landscaping, restaurant), all
typographic and phone first, with no pictures. Cleaning and landscaping businesses usually come to the customer,
so their pages show the town rather than a street address that may be someone's home; a lead with
`"visits": "storefront"` (a dry cleaner) shows its address and directions instead. The name on the pages is the
one the business uses on its own site, or our lead name exactly as recorded, never one made by trimming ours.

### The automated pipeline

`domain-health-check intake` reads new submissions to the form on /digital through the Webflow API, records each
as consent (`source: form`, with the email, business name, city and phone exactly as submitted), runs the report
with those details, and emails **mo@mizangroupllc.com only** the PDF, the exit code, anything incomplete and a
draft message to the business. The subject starts with `REVIEW BEFORE SENDING`. The draft is never sent by the
tool: nothing here can email anyone but that one address, which is hard-coded, and `mailer.send` refuses any
message addressed to anyone else.

- A domain on the lead list is skipped and logged, never run.
- Each submission is processed once (`logs/intake-seen.json`, marked before the run starts).
- A request with no website emails Mo a notice; any failure, in reading the form or in a run, emails Mo the error.
- `WEBFLOW_API_TOKEN` in `.env` is a Webflow token with read access to forms only. It is never printed or logged.
- `--submissions-file PATH` reads a saved API response instead of Webflow, for testing.

Scheduled with Windows Task Scheduler (run from Command Prompt; the tasks run while you are logged in):

```
schtasks /Create /TN "Mizan\domain-health-check intake" /SC HOURLY /MO 1 /TR "cmd /c cd /d C:\Users\melra\projects\domain-health-check && .venv\Scripts\domain-health-check.exe intake >> logs\intake-task.log 2>&1" /F
schtasks /Create /TN "Mizan\domain-health-check sweep" /SC WEEKLY /D MON /ST 08:00 /TR "cmd /c cd /d C:\Users\melra\projects\domain-health-check && .venv\Scripts\domain-health-check-sweep.exe >> logs\sweep-task.log 2>&1" /F
```

### PDF output

Every run renders the same report as a branded PDF with WeasyPrint. Both formats are built from the same report
object, so they cannot disagree. WeasyPrint needs the Pango libraries, which pip cannot install:

- **Windows:** install MSYS2, then Pango inside it. The tool finds `C:\msys64\ucrt64\bin` on its own;
  if MSYS2 lives elsewhere, set `WEASYPRINT_DLL_DIRECTORIES` in `.env`.
  ```powershell
  winget install --id MSYS2.MSYS2 -e
  C:\msys64\usr\bin\bash.exe -lc "pacman -S --noconfirm --needed mingw-w64-ucrt-x86_64-pango"
  ```
- **macOS:** `brew install pango`
- **Debian/Ubuntu:** `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`

Without Pango the Markdown report is still written and the run exits with code `2`.

The exit code says whether the run did its job, not what it found:

| Code | Meaning |
|---|---|
| `0` | A complete report was written. FAIL findings are findings, so they still exit `0`. |
| `2` | The run could not do what was asked: a configuration error, a refused domain, or a requested PDF that could not be written. |
| `3` | A report was written but is not complete: the browser could not load the page, PageSpeed did not run, or a check crashed. The reasons are printed and recorded in `report.json`. A report that exits `3` is not sent. |

## Sample output

*Made-up results for illustration.*

```
Checking example.com...

example.com
  PASS  SSL certificate               Valid for another 64 days, issued by Example Certificate Authority.
  PASS  TLS version                   Uses TLS 1.3, the newest and most secure version.
  PASS  HSTS (always use HTTPS)       Browsers are told to always use HTTPS for 365 days.
  WARN  Content Security Policy       No Content Security Policy is set.
  PASS  X-Content-Type-Options        The nosniff protection is switched on.
  WARN  Domain registration           The domain registration expires in 41 days.
  PASS  Nameservers                   2 nameservers are listed.
  WARN  DNSSEC                        DNSSEC is not switched on for this domain.
  PASS  Mail servers (MX)             2 mail server(s) are listed.
  PASS  SPF (approved senders)        SPF is set up and flags email from unlisted servers as suspicious (~all).
  PASS  DKIM (email signatures)       DKIM signing keys are published (selector: google).
  WARN  DMARC (anti-spoofing policy)  No DMARC record was found.
  8 pass, 4 warn, 0 fail
  Report: reports\example.com\2026-09-27\report.md
```

An excerpt from the matching Markdown report:

```markdown
# Domain health report: example.com

*Checked on 27 September 2026 at 09:30 UTC*

## Summary

**No urgent problems.** 4 item(s) could be improved.

| Area | Check | Result | What we found |
|---|---|---|---|
| Email security | DMARC (anti-spoofing policy) | ⚠️ Could be improved | No DMARC record was found. |
...

## What to fix

### ⚠️ DMARC (anti-spoofing policy)

**What we found:** No DMARC record was found.

**Why it matters:** DMARC tells other mail systems what to do with emails that claim to be from
you but fail the SPF and DKIM checks: deliver, send to spam, or reject. Without an enforcing
policy, scammers can send emails that appear to come from your domain.

**How to fix it:** Add a TXT record at _dmarc.<your domain> such as
`v=DMARC1; p=none; rua=mailto:dmarc@<your domain>`, review the reports for a few weeks, then
tighten the policy to p=quarantine and finally p=reject.
```

## Running the tests

```powershell
pytest
```

The tests never touch real domains: every DNS lookup, TLS handshake and HTTP request is replaced
with fake data, and a fixture in `tests/conftest.py` makes any real network connection fail the test.
A test also checks that `domains.example.yaml` only contains reserved example domains.

The browser and PDF tests need Chromium (`playwright install chromium`) and Pango. Without them those tests
skip on a developer's machine. CI (`.github/workflows/ci.yml`) runs `ruff check .` and then `pytest` on Python
3.10 and 3.13 with both installed and `DHC_NO_SKIPS=1`, which turns any skip into a failure, so the browser
tests always run there.

## Project layout

```
domain_health_check/
  cli.py            command-line entry point
  config.py         loads and validates domains.yaml
  runner.py         runs every check for a domain
  fetcher.py        the one page view: robots.txt, home page, sitemap, User-Agent, timeouts, size caps
  robots.py         robots.txt as RFC 9309 and Google read it, for our access and for Googlebot's
  external.py       outside services fetched once per report (PageSpeed Insights), with a 24-hour cache
  scoring.py        the weighted 0 to 100 score
  layout.py         what each report section says, shared by both formats
  report.py         Markdown report, and keeping only the latest per domain
  pdf.py            PDF report (WeasyPrint), from the same report object
  mailer.py         emails a finished report to the reviewer, never to the site owner
  assets/           logo and Plus Jakarta Sans (SIL Open Font License)
  terminal.py       coloured terminal summary
  dns_utils.py      thin dnspython wrapper
  checks/
    tls.py          SSL certificate and TLS version
    http_headers.py HSTS, CSP, X-Content-Type-Options (reads the fetched page)
    rdap.py         domain registration expiry
    dns_records.py  NS and MX
    dnssec.py       DS record
    email_auth.py   SPF, DKIM, DMARC
    site/           site health, read from the fetched page
      indexing.py         search engine blocking, canonical tag, sitemap and robots
      content.py          title, meta description, headings, image alt text
      structured_data.py  JSON-LD against the visible page
      sharing.py          social preview (Open Graph)
      delivery.py         mobile viewport, page weight, redirect chain
    pagespeed.py    real-world speed, mobile speed, accessibility, best practices
tests/
```

## Limitations

- Checks the bare domain (`example.com`), not `www.` or other subdomains.
- The TLS check reports the best protocol version the server offered. It doesn't test whether older
  versions are *also* still enabled, because that would take repeated connection attempts.
- The SPF check doesn't count DNS lookups (SPF has a limit of 10).
- DKIM can only be confirmed for selectors you know about.

## License

[MIT](LICENSE)
