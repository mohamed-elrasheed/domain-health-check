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

Three confirmed findings, maximum, chosen by the owner-cost ladder below, not by score weight. A finding we
could not confirm (one that says "may") never appears here; it goes in "Worth checking" near the end. If
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
  present, viewport present, template placeholder text, Google Business Profile findable.
- Graded: alt text (images described ÷ images), heading order (headings in order ÷ headings), title and
  description length, social preview tags, structured data matches, page weight, Google's speed and
  accessibility scores, redirect hops, profile completeness, review count, days left before a certificate
  or domain expires.

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
