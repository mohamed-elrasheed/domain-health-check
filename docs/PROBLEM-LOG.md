# Problem log

Every real problem this project hit, what caused it, what we changed, and what the change fixed, with the
evidence. Newest first. Each fix adds its entry in the same pull request, so this file never falls behind the code.

A problem counts when it produced a wrong result, a false alarm, a security risk or a wasted run. The numbers are
from real runs on mizangroupllc.com, our own site, unless an entry says otherwise.

## Running it for real (November 4)

### The fourth site: praise caught by the reviews, now caught by code (PR #29)
- **Problem:** the last consented site ran clean (26 pass, 6 warn, 0 fail). The draft said "the site is in healthy
  shape overall", which the report never says. All three reviews failed it, so the review email carried the
  template, as designed.
- **What we did:** "healthy shape", "good shape" and "in good health" join the phrases the code check rejects,
  beside "great shape" and "very good". A phrase a program can match no longer waits for three model calls.
- **What it fixed:** that draft now fails in the code check, before any review is paid for. The gates worked on
  their first run on this site: the unstated praise never reached the reviewer's inbox as the AI draft.

### A pointer to our price list read as a sales push (PR #27)
- **Problem:** with "costing you customers" gone (PR #26 worked: 0 of 5 drafts said it), every draft passed the
  code check and all three reviews, and the editor failed 4 of 5 on one line carried over from a check's fix:
  "Adding one is also part of a tune-up on our price list." Three also split the meta description and link
  preview into two steps that both said to look in the SEO plugin's settings.
- **Cause:** the WordPress fixes name the tune-up on purpose, for the owner reading the PDF beside our price list.
  In a short helpful email it is the one line that sells. The writer copied it because the fix said it.
- **What we did:** the PDF keeps the line. The writer leaves out any mention of our price list or paid work, and
  the code check rejects "price list" and "tune-up". Two fixes that send the owner to the same place become one
  step. The main heading explanation no longer says "search engines" twice.
- **What it fixed:** the next redraft passed **4 of 5** through the code check, all three reviews and the editor. The one failure was a real catch: it explained the meta description twice. In production that draft would have sent the template.

### Told not to quote a phrase, the writer said it in other words (PR #26)
- **Problem:** after PR #25 told the writer not to quote the report's heading ("Here is what is costing you
  customers"), 6 of 6 drafts still said the findings were "costing you customers" in their own words. The new code
  rule caught every one before any review ran, so each failure cost about 2 cents instead of 9.
- **Also found:** the editor passed a hand-written message on the same report 5 of 5, so the editor is fair and
  the remaining failures are the writer's.
- **What we did:** the writer no longer sees the phrase. The reading in its facts says "could be better" instead;
  the PDF heading is unchanged. A model reliably repeats what is in its input, so the fix is to keep the phrase out
  of the input, not to add a rule against it. The code rule stays as the backstop.
- **What it fixed:** 0 of 5 drafts said it on the next redraft. The failures moved on to the price-list line (PR #27).

### A fresh report fixed the old copy and showed what was left (PR #25)
- **Problem:** with the new wording in a fresh report, the first draft and five redrafts still passed the editor 0
  of 6, though every draft passed the code check and all three reviews. The old flags were gone ("tune-up"
  unexplained, "could be better" on every item). New ones were left.
- **Cause:** three were real and came from our own text. The image finding said "none of the 30 images has a
  useful description" and then "of these, 3 logo images and 2 linked images need a real description", which reads
  as if only 5 matter. The WordPress step was labeled "You can do this yourself" but handed the no-plugin case to
  someone else. And the writer quoted the report's heading, "Here is what is costing you customers", beside
  "nothing is broken". The rest were judgment calls about length and definitions, made again on every run.
- **What we did:** the image summary stays one fact, and the fix says where to start with the counts ("starting
  with the 3 logo images and the 2 images inside links"). The WordPress step says how to add a plugin, so the
  label holds. The writer does not quote the report's heading or describe the findings in vague terms, and the
  code check rejects "costing you". `scripts/eval_editor.py` runs the editor on a message a person has already
  judged, so we can tell whether the remaining failures are the writer's or the editor's before changing either.
- **What it fixed:** the editor passed a hand-written message on the same report 5 of 5, so it is fair and the remaining work was the writer's. The image and WordPress flags stopped.

### A redraft cannot test a change to the report's own wording (PR #24)
- **Problem:** after PR #23, five more redrafts passed 0 of 5 and still showed the old wording: "this job belongs
  with a tune-up" and the two-group image counts.
- **Cause:** `redraft.py` re-runs the model from the facts saved in `ai.json` when the report ran, and those facts
  hold each check's text as it read then. A prompt change shows up in a redraft; a change to a check's copy shows
  up only in a new report. The prompt changes did work: "could be better" now appears once, not on every item.
- **Also found:** the image check said "decorative images can be left blank" in both its explanation and its fix,
  so every message that used both said it twice, and "a few gaps can be fine" sat beside "none of the images".
- **What we did:** the explanation no longer repeats the point the fix makes. The writer keeps each finding to
  its summary and the one or two sentences that say why it matters. A copy change is measured on a fresh report.
- **What it fixed:** the decorative-image point stopped repeating once a fresh report carried the new copy.

### The editor's first real test: 0 of 5, and most causes were in our own copy (PR #23)
- **Problem:** five redrafts of a client's message, now limited to three findings, passed 0 of 5. Two failed a
  review on "SEO plugin" left unexplained. Three passed every review and failed the editor, each for things a
  person would also change before sending.
- **Cause:** most of it came from the report's own wording, not the model. The WordPress fixes said "this job
  belongs with a tune-up" with no explanation, beside a "You can do this yourself" label. The image finding gave
  two counts that read as two groups when together they meant every image. Fixes pointed to "the technical
  details", which are in the attached report, not the message. And the writer was told to say "could be better"
  for each item, so it said it on every one.
- **What we did:** fixed the copy at the source, so the PDF reads better too: "SEO plugin" is explained, the
  tune-up line says what it is, and the image finding says "None of the N images has a useful description" when
  that is the case. The writer says "could be better" once, in the short version, does not repeat a finding in
  its step, and points to the attached report for technical details. A new code rule rejects the same sentence
  in two items.
- **Also fixed:** two earlier entries named client sites, which this file must never do. Both now say "a client".
- **What it fixed:** "could be better" now appears once instead of on every item. The copy fixes showed up on the next fresh report, after a redraft of saved facts turned out not to test them (PR #24). The editor did its job on its first real test: every
  reason it gave was something a person would change before sending.

### A draft that passed every check was still too long to send (PR #20)
- **Problem:** a client's draft passed the code check and all three reviews, then listed all 13 warnings
  under "What we would look at first" and gave the same PageSpeed step twice, once for speed and once for
  accessibility, because both checks share a fix. Every sentence was true, so nothing caught it.
- **Cause:** the writer was allowed to list every warning, and no rule looked for repeats. The reviewers judge
  whether each sentence is true, not whether the whole message is short and useful.
- **What we did:** code now decides what the message leads with: the report's top findings, at most three, plus
  anything broken today. Code adds one line saying how many more the attached report lists. The code check rejects
  any other check and any step said twice.
- **What it fixed:** the message stays a priority list, and the full detail stays in the PDF. Judging the whole
  message for clarity is now the editor's job (PR #21): a fifth model call, after the three reviews, that reads
  the whole message as a busy owner would and must pass.

### The review email failed, and so did the email reporting it (PR #20)
- **Problem:** the scheduled run could not send the review (`SMTPServerDisconnected`), and the failure email went
  the same way. The only trace was a line in `logs/intake.log`. The cause was the Google app password, replaced the
  same day.
- **What we did:** any email to the reviewer that fails is also written to `logs/ALERT.txt` and, with `NTFY_TOPIC`
  set, sent as a phone notification through ntfy, a channel that does not depend on email. The notification names
  only the kind of failure.
- **What it fixed:** an email outage is now loud instead of silent.

### A run hung and never said why (PR #20)
- **Problem:** a run started a report and never logged a result. The process was still running
  13 minutes later and had to be ended by hand.
- **What we did:** every intake run has a time limit (20 minutes by default). Past it, the run writes where every
  thread was stuck to `logs/intake-hang.log`, raises an alert, and exits with code 4.
- **What it fixed:** a hang can no longer sit unnoticed, and the next one leaves the evidence of its cause.

### The PC move lost the scheduled task and the PDF libraries (setup)
- **Problem:** after moving to a new PC, the hourly intake task no longer existed and the PDF failed with
  `cannot load library 'libgobject-2.0-0'`.
- **What we did:** recreated the task from the README line and installed Pango through MSYS2, as the README says.
- **What it fixed:** the next run wrote the PDF and emailed the review.

## Findings agent

### Grading a right answer as wrong (PR #17)
- **Problem:** the findings agent eval passed 6 of 7. The failed answer said "the website platform sets the
  Content Security Policy", which is right, but the eval wanted the exact label "Set by your website platform".
- **Also found:** the same answer pointed out that the check's fix ("ask your web developer to add a header")
  clashes with the platform label. It was right. On a hosted builder the platform controls that header, the report
  already hides that fix from the owner, but the agent's lookup tool still returned it.
- **What we did:** the eval grades a label by its key words. For a platform-set check, `get_check` now adds a note
  that the report does not show that fix to the owner.
- **What it fixed:** right answers that paraphrase a label pass, and the agent cannot present a fix the owner
  cannot carry out as their next step.

### The source check was first too strict, then too loose (PR #16)
- **Problem:** the first real eval passed 5 of 7. The agent answered "which checks warn" and "which were not
  checked" correctly from the list of checks, and was flagged for citing checks it had not opened one by one.
- **First fix, rejected:** count everything in the list as read. That was too loose: the list shows only a check's
  name, status and summary, so it supports "which checks warn" but not a fix, a detail or a price.
- **What we did:** every source now states its depth, `(list)` or `(full)`, and code holds it to that depth. A
  `(full)` source must have been opened. Every dollar amount must come from a price line the agent read.
- **What it fixed:** the next eval passed 6 of 7, and the one failure was the grading problem above. CLAUDE.md
  now says not to loosen this rule to make an eval pass.

## Draft and review workflow

### The cheap reviewer failed good drafts (PRs #13 and #14)
- **Problem:** with Haiku reviewing, 1 of 10 drafts passed. Most failures were false alarms. Four of the ten flagged
  "Slow pages lose visitors, and speed is a small factor in Google rankings", which is the speed check's own
  explanation word for word. One called Cloudflare a competitor, though the check's own fix names it. Several
  reviews said a sentence was acceptable and then failed it.
- **What we did:** added `redraft.py --review-model` to measure another reviewer on the same facts before changing
  anything (PR #13). Sonnet passed 2 of 5, and every flag was a real mistake by the writer, so Sonnet became the
  reviewer (PR #14). Each review is a separate call, so the writer still never grades its own work.
- **What it fixed:** false alarms stopped. The cost went from under 1 cent to about 7 cents per draft.

### Two real writing mistakes the better reviewer found (PR #14)
- **Problem:** 2 of 5 drafts promised "Some checks were not checked, and we say which below" and never listed them.
  2 of 5 used "DS record" without explaining it.
- **What we did:** the code check rejects any mention of checks that were not checked, since the report already
  lists them. The DNSSEC check's own fix now explains a DS record in plain words, which also helps the owner
  reading the PDF.
- **What it fixed:** the next run passed **5 of 5**. The eval then caught **10 of 10** planted false claims with all
  three reviews agreeing each time, the untouched draft passed, and the eval cost about 40 cents.

### One pass or fail is a sample of one (PR #12)
- **Problem:** every run failed one review on a different small detail ("browser security settings", "address
  records"). Fixing one wording at a time could go on forever.
- **What we did:** `redraft.py --times N` drafts N times and reports the pass rate. The writer must describe each
  finding in the report's own words, with no labels of its own.
- **What it fixed:** the 10-draft run exposed the reviewer problem above, which single runs had hidden.

### The writer and the reviewer read the same rule differently (PR #11)
- **Problem:** the rule said "explain a term in the same sentence". The draft explained terms in the next sentence,
  which reads naturally, and one reviewer failed it.
- **What we did:** both prompts say "the same sentence or the one right after it", and a test keeps the two prompts
  on the same wording.
- **What it fixed:** that false failure stopped. A term never explained still fails.

### "Google's free tool" (PR #10)
- **Problem:** two runs in a row called PageSpeed Insights free, which the report never says.
- **What we did:** the code check rejects "free", "no cost" and "costs nothing" unless the report says them.
- **What it fixed:** a rule a program can check exactly no longer depends on a review catching it, and it costs
  nothing to run.

### Dropped hedges, and testing a prompt cost a site visit (PR #6)
- **Problem:** a draft turned the report's "could, in some cases, be run as code" into a flat claim. Every prompt
  change meant running the whole report again, which visits the website.
- **What we did:** the prompt says to keep the report's hedges. `scripts/redraft.py` re-runs the draft and reviews
  from the facts saved in `ai.json`, without contacting the website.
- **What it fixed:** prompt testing takes seconds, costs only model calls, and never spends the report's
  one-visitor footprint.

### The first real run failed every review (PR #5)
- **Problem:** 0 of 3 reviews passed, with nine flags. Our prompt asked the model to write "Thank you for asking"
  and "the report is attached", lines that are not in the data, and the reviewer then flagged them as
  unsupported. Drafts also added praise and ranking ("very good shape", "most likely to notice"), timing advice
  ("no rush"), steps asking the owner to change settings their platform controls, and unexplained terms.
- **What we did:** code writes the greeting, the opening and the signature. The prompt bans praise, ranking and
  timing advice, and the code check catches the common phrases. Code rejects a next step for a check the platform
  sets. The review accepts a short, accurate definition of a term.
- **What it fixed:** the next run had 2 flags instead of 9, and cost under 3 cents instead of 4.

### The facts sent to the AI held a file path from this computer (PR #5)
- **Problem:** the reasons a run was incomplete went into the facts, and one contained a local file path.
- **What we did:** the facts no longer include those reasons. A check that passed sends only its name and summary.
- **What it fixed:** nothing about the machine reaches the model, and fewer tokens are sent.

### A run used old code (process)
- **Problem:** the second real run was made before the tuning pull request was merged, so it tested the old
  prompts and cost money for no new information.
- **What we did:** every run step now starts with `git pull` after the merge.
- **What it fixed:** each run measures the code it is meant to measure.

### The report could not finish its browser check (setup)
- **Problem:** the first run was marked incomplete because Playwright's Chromium was not installed on the PC.
- **What we did:** `playwright install chromium`. CI already fails on any skipped browser test (`DHC_NO_SKIPS=1`).
- **What it fixed:** the next report was complete.

## Security and supply chain

### Real API keys pasted outside `.env` (November 3)
- **Problem:** real keys were pasted into `.env.example`, which is committed, and into a chat.
- **What we did:** removed them before any commit, rotated all five keys, and set the rule that keys live only in
  `.env`. A scan of 100 commits found no real secrets. gitleaks now scans the full history on every pull request
  (PR #7).
- **What it fixed:** a key pushed by mistake now fails the pull request. A pushed key is still exposed on a public
  repository, so rotating it stays the rule.

### 62 published vulnerabilities in our pinned packages (PR #7)
- **Problem:** pip-audit found 62 vulnerabilities across five pins: Pillow (39), pypdf (18), certifi, brotli and
  dnspython. The fixed Pillow and dnspython need Python 3.11, and Python 3.10 reached end of life on October 1, 2026.
- **What we did:** upgraded all five, moved the floor to Python 3.11, and added pip-audit to CI on every pull
  request and every Monday. Dependabot watches the GitHub Actions.
- **What it fixed:** pip-audit reports no known vulnerabilities, and a new one fails CI instead of going unnoticed.
  Dependabot opened its first two update pull requests (#8, #9) the same night.

## Earlier, from real audits

These are recorded in CLAUDE.md under "Measurement traps", where the checks encode them.

- **Lazy-loaded images:** a live report said 19 of 31 images had useful alt text when the real answer was 0 of 31,
  because the test read a placeholder filename. Checks now resolve the real image source first.
- **Structured data out of date:** Mizan's own `/services` page published retired URLs and old prices in its
  structured data while the page read correctly. That became the "Structured data matches the page" check.
- **PageSpeed noise:** the same page scored 64, 79 and 80 minutes apart. Speed is banded on the median of three
  runs, led by largest contentful paint.
- **One format parsed into another:** parsing Markdown into a PDF once dropped a whole finding without an error.
  Both formats now render from the same report data through `layout.py`.
