# domain-health-check

A command-line tool that runs **passive, public** health checks on a list of domains and writes a
plain-English report for each one, suitable for handing to a non-technical client.

Every check returns **PASS**, **WARN** or **FAIL**, with an explanation of why it matters and what to do about it.

> **Passive lookups only.** This tool reads information that domains already publish to the whole
> internet: DNS records, public registry (RDAP) data, and a single ordinary HTTPS request to the home
> page, exactly what a browser does when someone visits. It does **not** port-scan, probe, fuzz,
> brute-force, log in, or send email. Even so, only check domains you own or have permission to assess.

## What it checks and why

### Website security

| Check | PASS | WARN | FAIL |
|---|---|---|---|
| **SSL certificate**: expiry, hostname match, issuer | valid for 30+ days | expires in under 30 days, or site unreachable | expires in under 7 days, expired, wrong hostname, or untrusted |
| **TLS version** | TLS 1.2 or 1.3 | | older than TLS 1.2 |
| **HSTS** | `max-age` of at least 180 days | short `max-age` or malformed | header missing |
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
| **Domain registration** (RDAP) | 60+ days until expiry | under 60 days, or no data available | under 14 days, or expired |
| **Nameservers** (NS) | two or more | only one | none |
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
| **MX** | mail servers listed, or a "null MX" | no MX records | |
| **SPF** | one record ending `-all` or `~all` (or using `redirect=`) | `?all`, or no `all` | missing, more than one record, or `+all` |
| **DKIM** | a key found on a selector | only revoked keys, or none found on the common selectors | none found on the selectors you configured |
| **DMARC** | `p=quarantine` or `p=reject` | `p=none` | missing, duplicated, or invalid |

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

## Setup

Requires Python 3.10+ (developed on 3.14). Runtime dependencies: `dnspython` and `PyYAML`.

```powershell
git clone https://github.com/mohamed-elrasheed/domain-health-check.git
cd domain-health-check
py -m venv .venv
.\.venv\Scripts\Activate.ps1        # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
```

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
python -m domain_health_check --help
```

Reports are written to `reports/<domain>-<date>.md` (gitignored).

The exit code is `0` when nothing failed, `1` if any check FAILed, and `2` for a configuration
error, which makes the tool easy to use from a scheduled task.

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
  FAIL  DMARC (anti-spoofing policy)  No DMARC record was found.
  8 pass, 3 warn, 1 fail
  Report: reports\example.com-2026-09-27.md
```

An excerpt from the matching Markdown report:

```markdown
# Domain health report: example.com

*Checked on 27 September 2026 at 09:30 UTC*

## Summary

**1 item(s) need action soon**, and 3 could be improved.

| Area | Check | Result | What we found |
|---|---|---|---|
| Email security | DMARC (anti-spoofing policy) | ❌ Needs action | No DMARC record was found. |
...

## What to fix

### ❌ DMARC (anti-spoofing policy)

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
  report.py         Markdown report
  terminal.py       coloured terminal summary
  dns_utils.py      thin dnspython wrapper
  checks/
    tls.py          SSL certificate and TLS version
    http_headers.py HSTS, CSP, X-Content-Type-Options
    rdap.py         domain registration expiry
    dns_records.py  NS and MX
    dnssec.py       DS record
    email_auth.py   SPF, DKIM, DMARC
tests/
```

## Limitations

- Checks the bare domain (`example.com`), not `www.` or other subdomains.
- The TLS check reports the best protocol version the server offered. It doesn't test whether older
  versions are *also* still enabled, because that would take repeated connection attempts.
- The SPF check doesn't count DNS lookups (SPF has a limit of 10).
- DKIM can only be confirmed for selectors you know about.
