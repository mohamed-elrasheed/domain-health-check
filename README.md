# domain-health-check

A command-line tool that runs health checks on a list of domains and writes a plain-English report
for each one, suitable for handing to a non-technical client. It produces the free report offered at
[mizangroupllc.com/digital](https://www.mizangroupllc.com/digital).

Every check returns **PASS**, **WARN** or **FAIL**, with an explanation of why it matters and what to do about it.
FAIL means something is broken today, never just a risk: an expired certificate or one issued for another
name, a domain expiring within 30 days, no mail servers, or a site telling Google not to list it. Everything
else that could be better, including missing HSTS, CSP or DMARC, is a WARN.

> **Scope.** We only run these checks on domains submitted through the form at
> [mizangroupllc.com/digital](https://www.mizangroupllc.com/digital); the submission is the consent.
> Each report touches public DNS and registry (RDAP) records, one TLS handshake, and a single page
> view: the home page plus the `robots.txt` and sitemap files search engines read, the same footprint
> as one ordinary visitor. It honors `robots.txt` and never opens the sitemaps a sitemap index lists.
> It does **not** port-scan, probe paths, test for vulnerabilities, touch a login, crawl other pages,
> or send email. Every request
> identifies itself with the User-Agent `domain-health-check/0.1 (+https://www.mizangroupllc.com/digital)`
> so anyone reading their server logs can see who it was and why.

## What it checks and why

### Website security

| Check | PASS | WARN | FAIL |
|---|---|---|---|
| **SSL certificate**: expiry, hostname match, issuer | valid for 30+ days | expires in under 30 days, untrusted issuer, or site unreachable | expired, or issued for a different name |
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

All of these read the one page view; none makes a request of its own. A check with nothing to
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

- **Search engine blocking** is the most valuable check here: a site launched with `noindex` left
  on from staging is invisible in Google, and nothing on the page looks wrong. robots.txt is read the
  way Google reads it (`*` and `$` wildcards, longest rule wins) by `robots.py`, the same reader that
  decides whether we may load a page ourselves. Python's `robotparser` only does this from 3.14.
- **Structured data matches the page** catches JSON-LD that still carries retired URLs or old prices
  after the visible page was updated. Each match in the details says which evidence it rested on:
  page text, a page link, or the sitemap.
- Measured on the HTML as delivered, before scripts run. Page weight is the HTML document alone;
  images, scripts and styles are not loaded. A sitemap index is recorded but never followed.

### Speed (optional, from Google PageSpeed Insights)

Runs only when `PAGESPEED_API_KEY` is set. With no key, these rows do not appear and cost nothing.
Mobile and desktop are tested at the same time, and each raw response is cached for 24 hours in
`.cache/pagespeed/` (gitignored). We only ask Google to test a page we were able, and allowed, to load
ourselves.

| Check | PASS | WARN | FAIL | Not run |
|---|---|---|---|---|
| **Real-world loading speed** | Chrome field data `FAST` | `AVERAGE` or `SLOW` | | Google publishes no field data for the page (the usual case for a small business) |
| **Mobile speed** | Lighthouse performance 90+ | below 90 | | score null or missing |
| **Accessibility** | Lighthouse accessibility 90+ | below 90 | | score null or missing |
| **Best practices** | Lighthouse best-practices 90+ | below 90 | | score null or missing |

- Bands are Google's own, so the report agrees with any other tool the owner runs. Lab scores move
  a few points between runs, so summaries name the band and the number stays in the details.
- `categories.*.score` is 0 to 1 and arrives as either a float or an int. Lighthouse's `seo` category
  is not scored: the site checks above already measure the same things directly.
- Whole-site field data (`originLoadingExperience`) is labeled as the whole site, never as the page.
- A timeout, an API error or a skipped test is one "Google speed test" row that did not run, and is
  left out of the score.

## Setup

Requires Python 3.10+ (developed on 3.14). Runtime dependencies: `dnspython`, `httpx`, `PyYAML`, `selectolax` and `weasyprint`.

```powershell
git clone https://github.com/mohamed-elrasheed/domain-health-check.git
cd domain-health-check
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

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
domain-health-check                        # check everything in domains.yaml
domain-health-check example.com            # check one domain without a config file
domain-health-check -c other.yaml -o out   # different config file / report folder
domain-health-check --no-color             # plain output (also honours NO_COLOR)
domain-health-check example.com --pdf      # also write the report as a PDF
domain-health-check example.com --email    # PDF, emailed to you for review (needs SMTP_* in .env)
python -m domain_health_check --help
```

Reports are written to `reports/<domain>-<date>.md`, plus `.pdf` with `--pdf` (gitignored). Only the
latest report per domain is kept: writing a new one deletes that domain's older reports. A stale scan is
misleading, and the check is cheap to run again.

### PDF output

`--pdf` renders the same report as a PDF with WeasyPrint. Both formats are built from the same report
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

The exit code is `0` when nothing is broken, `1` if any check FAILed, and `2` for a configuration
error or a requested PDF that could not be written, which makes the tool easy to use from a scheduled task.

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
  Report: reports\example.com-2026-09-27.md
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
