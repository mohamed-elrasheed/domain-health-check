# Report spec

What `report.py` produces, and why it is shaped this way. Read with CLAUDE.md.

## The reader

A small business owner who did not go looking for this. They submitted their web address, and two
business days later a report arrived. They will give it ninety seconds before deciding whether it is
useful or noise.

They are not an engineer. They may forward it to one.

So the report has to work on three levels, in this order:

1. **Thirty seconds** — a score and the three things that matter.
2. **Three minutes** — the full findings, grouped, each with what it means.
3. **For whoever implements it** — the technical specifics, out of the owner's way.

The existing `CheckResult` already maps to levels 2 and 3: `summary` and `explanation` for the owner,
`fix` for the action, `details` for the implementer. Do not flatten that. This spec adds level 1 and the
closing section.

## Structure

```
1. Header            domain, date, score
2. The top three     the three findings most worth acting on
3. What you can fix yourself
4. What needs a developer
5. Worth checking    findings we could not confirm, in honest wording
6. Everything we checked        full results, grouped by category
7. What happens next
8. Findings and our published prices    the last page
```

Sections 3 and 4 are a re-cut of the same findings, not new content. A finding appears in exactly one of
them, and may also appear in the top three.

### 1. Header

Domain, date checked, and the score with a one-line reading of it. Nothing else — no logo wall, no
preamble about who we are. That goes in the email, not the report.

### 2. The top three

**The owner-cost ladder.** Rank findings by what the problem costs the business. Within a tier, confirmed
before uncertain, then broken before risky.

1. Customers cannot reach the site: unreachable, certificate warning, 5xx, search engines blocked.
2. Google cannot understand the site: main heading, description, title, alt text, heading order, canonical,
   sitemap.
3. Customers cannot find the business locally: Google Business Profile missing, not findable, not linked.
4. The site is slow enough that people leave: largest contentful paint, page weight.
5. Email can be spoofed: SPF, DKIM, DMARC, MX.
6. Hardening: HSTS, CSP, nosniff, DNSSEC.

Weight still decides the score. It was the wrong proxy for what to read first: on a real report it
opened with two email records while the missing main heading and 31 undescribed images sat below them.

At most three findings, ranked by **points lost** (weight × how wrong it is), with the ladder's tier
breaking ties. A category is not a cost: a tier-2 finding that is 90% right costs almost nothing, a tier-3
finding that is 0% right costs its whole weight. Only confirmed, customer-facing (tiers 1 to 4) findings that
are materially wrong (less than half right) qualify, and three is a maximum, not a quota: never pad it.

The filter and the sort are two different measures doing two different jobs, deliberately. "Less than half
right" decides what qualifies; points lost decides the order among what qualifies. A heavy finding at 0.55
right can lose more points than a light one at 0.3 and still be left out. That is intended: this section is
"worth doing", and a mostly-right thing is not worth leading with however heavy it is. It still appears in
the fix sections below. The mismatch is not a bug; do not "fix" it by dropping the filter. A
finding we could not confirm (one that says "may") never appears here; it goes in "Worth checking" near the
end. The one-line reading counts the same list, so the two cannot disagree. If
fewer than three things are
wrong, show fewer. If nothing is wrong, this section says so plainly and the report is short — see
"When nothing is wrong".

Each one gets: what we found, why it matters, what to do. Two or three sentences. No technical detail
here at all.

### 3. What you can fix yourself

A finding belongs here if the owner can do it from their website's admin screen without touching DNS,
server configuration or code. Page titles, meta descriptions, alt text on images, a missing favicon.

**Give these away properly** — with enough detail that they can actually do it. It feels like leaving
money on the table and it is not. The owner who fixes four things themselves is the one who refers you,
and the one who comes back when something needs a professional.

### 4. What needs a developer

Everything requiring DNS records, server headers, certificate work, redirects or code. SPF, DKIM, DMARC,
HSTS, CSP, canonical tags, structured data.

Say what needs doing, not how. This section is where the work is, so it is also where the pricing link
belongs — one line, at the end of the section, not shouted.

### 5. Everything we checked

The full list, grouped by the existing categories: Website security, Domain and DNS, Email security, and
(once built) Site health. Every check appears, including the passes.

**Show the passes.** A report that only lists problems looks like a sales document. A report that says
"your certificate is valid for 312 days — nothing to do" is the one that gets believed when it does flag
something.

Technical specifics stay in `details`, visually subordinate.

### 6. What happens next

Three short lines:

- What they can do with this report (fix it themselves, send it to their developer, or ask us).
- How to reach us — reply to this email, or the quote form. **No "book a call" gate.** Techno Dream
  requires a consultation before you learn anything; not requiring one is the advantage, so do not
  rebuild their funnel.
- **No free re-check.** The first report is the free thing. Do not promise to run these checks again at
  no charge. An earlier draft of this spec did, and it was wrong: it committed Mizan to unbounded unpaid
  work for people who may never become clients, with no way to track what was owed to whom.

Re-checking is a **feature of the paid relationship**, not a giveaway. Monthly re-checks belong to care
plan clients, and saying so turns an ongoing cost into a reason to buy. If the closing mentions it at
all, it mentions it that way.

### 7. Findings and our published prices

The last page, on a page of its own. Every confirmed finding again, grouped by its **rung**, `self` first:

| Rung | Means | The page shows |
|---|---|---|
| `self` | The owner can do it from their website builder, Google Business Profile or domain registrar. | The finding's own fix, one or two sentences. |
| `tuneup` | Work on the site they have now: headers, redirects, speed, structured data. | The published hourly rate on /digital. |
| `email` | Email and domain settings (MX, SPF, DKIM, DMARC, nameservers, DNSSEC). Tech services, not website work. | The finding's own fix. /services publishes no line for this yet, so there is no price. |
| `rebuild` | The problem is the site itself, not a setting on it. | The three published build packages. |
| `platform` | Set by a hosted website builder the report recognized: HSTS, Content Security Policy and nosniff only. | What we found, under "Set by your website platform", with the sentence "This is set by your website platform, not by you or a developer. We list it for completeness and do not charge for it." |

Rungs, rung labels and every price line come from one file, `config/pricelist.yaml`, which mirrors our /digital
and /services pages word for word. A test compares each line with a saved copy of the page it names, so the file
cannot drift from it unnoticed. Nothing in the report writes a price of its own. A check with no rung stops the
report rather than guessing one.

`platform` is never assigned in that file. A finding reaches it only when `platform.py` recognizes Webflow, Wix,
Squarespace, Shopify or GoDaddy Website Builder from what the report already fetched: the response headers, the
generator tag, attributes on the page, and the hosts its own assets load from (`config/platforms.yaml`). Nothing
is requested to find out. When no builder is recognized those three findings stay `tuneup`. The rung never changes
the score.

A finding we could not confirm is never priced. When nothing confirmed is left to list, the page says so in one
sentence and nothing else. No urgency, no "limited time", and no recommendation beyond the rung: the owner can take
any of it to whoever they like.

## The score

One number, 0 to 100, from weights rather than a flat count, so a missing alt tag cannot drown an expired
certificate.

**Weights** live in a map keyed by check name, in `scoring.py` — not on `CheckResult`. Checks stay
ignorant of scoring; a check should never know what it is worth.

Each check's weight is its tier on the owner-cost ladder (see "The top three"), so the score and the
order of the report rank problems the same way. The ladder lives in `ladder.py` and is read by both.

| Tier | Weight | What it costs the owner |
|---|---|---|
| 1 | 5 | Customers cannot reach the site |
| 2 | 4 | Google cannot understand the site |
| 3 | 3 | Customers cannot find the business locally |
| 4 | 2 | The site is slow enough that people leave |
| 5 | 1 | Email can be spoofed |
| 6 | 1 | Hardening |

An earlier table weighted email records at 3 and a missing main heading at 1. That was the same wrong
proxy the old ordering used.

```
credit   = PASS: 1.0
           FAIL: 0.0
           WARN, graded (a matter of degree): the check's own measure, 0 to 1
           WARN, binary (present or absent): tier 1-2: 0.0, tier 3-4: 0.25, tier 5-6: 0.5
earned   = sum(weight × credit)
possible = sum(weight for every result that counts)
score    = round(100 × earned / possible)
```

**Why a confirmed absence earns nothing.** Half credit was correct when WARN meant "this might be a
problem". It is not correct now. Uncertain findings moved to "Worth checking", so every WARN left in the
main list is a confirmed, observed defect. A meta description either exists or it does not. There is no
partial credit for sort-of-having-one. Confirmed-absent scores zero.

**Binary and graded.** Each check declares which it is through its result: a graded finding carries a
measure of how much of the thing is right, a binary one does not.

- Binary: main heading present, meta description present, canonical present, title present, sitemap
  present, viewport present, template placeholder text, Google Business Profile findable, mixed content,
  favicon.
- Graded: alt text (images described ÷ images), heading order (headings in order ÷ headings), title and
  description length, social preview tags, structured data matches, page weight, Google's speed and
  accessibility scores, redirect hops, profile completeness, review count, days left before a certificate
  or domain expires, broken links (links that work ÷ links verified, separately for the site and for other
  sites).

### Checks added for links, mixed content and the icon

| Check | Tier | Weight | Rung | WARN when |
|---|---|---|---|---|
| Broken links | 4 | 2 | `self` | a link to another page on the site ends in an error status, a timeout, or more than 3 redirects |
| Links to other sites | 6 | 1 | `self` | the same, for a link to someone else's site. Never FAIL: the owner does not control that site |
| Mixed content | 4 | 2 | `self` | the secure page loads an image, script, stylesheet, font or framed page over plain http |
| Favicon | 6 | 1 | `self` | no icon resolves to an image, or the icon is a website builder's standard one (only from entries in `config/platforms.yaml` that cite a source; none yet) |

None of them can FAIL. Links are verified under the capped rule in CLAUDE.md (at most 80, HEAD then GET only when
HEAD is refused, 3 hops, no bodies), and every request is in `requests.log`. A status that usually means automated
checks are turned away (401, 403, 429, 999) is reported as not verified, never as broken. The icon takes at most
two requests: the first icon the page names, then `/favicon.ico`.

"Heading order skipped in 2 places" and "no main heading at all" are not the same site, and proportional
credit says so without a special case: 31 of 31 images undescribed scores zero, 14 of 40 does not.

**Left out of both sides:** checks that could not run (the WARN-on-exception path in `runner`; a timeout
must not look like a failure), INFO results (a fact, not a grade), and findings we could not confirm. A
maybe neither costs nor earns points.

**Two rules about the score.** It must not be tuned to come out low so the report looks urgent, and it
must not be tuned to come out high so the owner feels good. If a site is in good shape the number says so
and we have still demonstrated competence. Manufacturing a problem is the one thing that cannot be
walked back.

The one-line reading tracks what was found, not the score band: fifteen warnings is not "a few". When
something is broken it says how many things are. When nothing is, it says so plainly ("Nothing on your
site is broken. Here is what is costing you customers."), which is more credible than a manufactured
failure and true. Plain descriptions, no grades, no colours, no emoji.

## When nothing is wrong

It will happen, and it is a good outcome, not an awkward one. The report says so in one line, lists the
passes, and ends. Do not pad it. Do not go looking for something to flag.

A clean report sent to someone who expected a sales pitch is worth more than a long one.

## Voice

- Plain English. Jargon only in `details`.
- Second person. "Your certificate expires on 3 November", not "the certificate was found to expire".
- No manufactured urgency. A cosmetic WARN reads as cosmetic. No "critical", "urgent" or "immediately"
  unless something is genuinely about to break.
- No em-dashes, no exclamation marks, American English. Team voice, never "I".
- Never imply we scanned anything we did not. The report describes public records and one page view.

## Exit codes

The exit code says whether the run did its job, not what the report found.

- `0`: a complete report was written.
- `2`: the run could not do what was asked: a configuration error, a refused domain, or a PDF that could not be written.
- `3`: a report was written but is incomplete, and the reasons are printed and recorded in `report.json`.

A FAIL finding no longer exits `1`. It is a finding, and a complete report that contains one exits `0`.

## Formats

Both formats render **from the `DomainReport` object**, through the same `layout.py` that decides what
each section says. The PDF adds the letterhead and nothing else; if the two can disagree, the design is
wrong. An earlier version of this section said the PDF renders from the Markdown. That was wrong:
regex-parsing Markdown into a PDF silently lost an entire finding.

## Do not

- Pad a clean report.
- Put a "book a call" gate in front of the findings.
- Hide the passes.
- Let the score be adjustable to make a report look worse.
- Send a FAIL that has not been read by a human. A confident wrong finding costs more than the lead was
  worth, and it is the one mistake this whole offer cannot survive.
