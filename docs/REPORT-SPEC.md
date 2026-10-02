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
5. Everything we checked        full results, grouped by category
6. What happens next
```

Sections 3 and 4 are a re-cut of the same findings, not new content. A finding appears in exactly one of
them, and may also appear in the top three.

### 1. Header

Domain, date checked, and the score with a one-line reading of it. Nothing else — no logo wall, no
preamble about who we are. That goes in the email, not the report.

### 2. The top three

Three findings, maximum. Chosen by weight (below), then by severity. If fewer than three things are
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

| Weight | Meaning | Examples |
|---|---|---|
| 3 | Costs money, loses mail, or breaks trust | certificate expired or expiring soon, no SPF, no DMARC, domain expiring, no MX |
| 2 | Real but not urgent | HSTS missing, DNSSEC off, single nameserver, no canonical, missing title or meta description |
| 1 | Polish | CSP, X-Content-Type-Options, alt text, Open Graph tags, page weight |

```
earned  = sum(weight × {PASS: 1.0, WARN: 0.5, FAIL: 0.0}[status])
possible = sum(weight for every check that ran)
score   = round(100 × earned / possible)
```

Checks that could not run (the WARN-on-exception path in `runner`) are excluded from both sides. A
timeout must not look like a failure.

**Two rules about the score.** It must not be tuned to come out low so the report looks urgent, and it
must not be tuned to come out high so the owner feels good. If a site is in good shape the number says so
and we have still demonstrated competence. Manufacturing a problem is the one thing that cannot be
walked back.

Band the number for the one-line reading: 90+ "in good shape", 70–89 "a few things worth fixing",
50–69 "several things need attention", below 50 "needs work in a few areas". Plain descriptions, no
grades, no colours, no emoji.

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

Markdown stays canonical. PDF renders **from** the markdown — one source, one renderer. The PDF adds the
letterhead and nothing else; if the two can disagree, the design is wrong.

## Do not

- Pad a clean report.
- Put a "book a call" gate in front of the findings.
- Hide the passes.
- Let the score be adjustable to make a report look worse.
- Send a FAIL that has not been read by a human. A confident wrong finding costs more than the lead was
  worth, and it is the one mistake this whole offer cannot survive.
