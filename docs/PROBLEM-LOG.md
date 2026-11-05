# Problem log

Every real problem this project hit, what caused it, what we changed, and what the change fixed, with the
evidence. Newest first. Each fix adds its entry in the same pull request, so this file never falls behind the code.

A problem counts when it produced a wrong result, a false alarm, a security risk or a wasted run. The numbers are
from real runs on mizangroupllc.com, our own site, unless an entry says otherwise.

## Running it for real (November 4)

### Two lists made every message say each finding twice (PR #41)
- **Problem:** measured over 15 drafts, the first outside site passed every gate about 60% of the time, and nearly
  every failure was the editor's: the steps repeated what the findings had just explained, or a finding had no
  step of its own. Prompt rules ("do not repeat the finding in the step") never fully held.
- **Cause:** the layout. The message listed the findings, then listed the steps, so every finding was named twice,
  and a step shared by two findings left the second one without a step.
- **What we did:** one list. Each bullet is the finding, why it matters, then "What to do:" and its step, with
  code's who-can-do-it label. The writer gives every finding its own step, starting with the action; a step that
  uses the same place as the one before says so in a few words. The code check rejects a finding with no step.
- **First measurement: 0 of 10, all for one cause.** Two WordPress fixes end with the same "if your site has no
  SEO plugin" sentence, and with one step per finding the writer copied it into both; the code check rejected all
  10 before any review (18 cents in all). Code now drops a sentence a later step repeats word for word, since that
  is a job code can do exactly.
- **What it fixed:** to be measured on 10 more redrafts against the 60% baseline.

### The code check's gaps and false alarms, and website text reaching the models (PR #40)
- **Problem:** both audits listed small code-check gaps: "--" passed the dash rule; "right away" and "as soon as
  possible" passed the timing rule; "we will check it next month" passed the re-check rule; the same check listed
  twice in different words passed; any number in the run's timestamp counted as "in the report". And rules fired
  on normal English: "error-free", "this free report", a page title such as "My Bakery", "not checked by Google".
  Separately, every passing check sent its summary to the models, and those often quote the site itself (its page
  title, its main heading), which anyone can write and which widened what the code check accepted.
- **What we did:** closed each gap and each false alarm, with a test for every one. Passing and unchecked checks
  now send only their name and status. The timestamp is left out of what counts as grounded. `agents.run` now
  catches everything by construction.
- **What it fixed:** the code check alone now catches 3 of the 10 planted false claims, up from 1, before any
  model call is paid for. Pass rates held: on the same saved facts this branch passed 2 of 5 and main 3 of 5 on
  the first outside site (variation, with the same failure reasons on both), and 5 of 5 on the second. Measuring 15
  drafts instead of 5 also corrected the scorecard: the first site passes about 60%, not the 80% one run showed.

### Three ways the hourly run could fail quietly or lose a request (PR #39)
- **Problem:** both audits found them. A damaged `logs/intake-seen.json` crashed every hourly run, and the crash
  reached only stderr. The AI step had no total limit: five calls at 120 seconds with two retries each could take
  half an hour, past the 20-minute watchdog, which kills the process with a submission already marked seen and
  never reported. And a paid call that stopped early dropped its token counts, so the email could say no AI calls
  were made.
- **What we did:** the seen file is written to a temporary file and swapped in, with the previous version kept
  as a backup; a damaged one stops intake with a clear error instead of reading as empty (empty would re-run every
  submission ever received). A crash inside intake now emails the reviewer and raises an alert. The AI step has a
  6-minute budget checked between steps, and each call is capped at 60 seconds with one retry. The watchdog's
  default rose to 45 minutes to cover the worst case of three reports and still end before the next hour. A failed
  but billed call keeps its token counts.
- **What it fixed:** tests prove each of these. Mo: if `INTAKE_TIME_LIMIT_MINUTES` is set in `.env`, raise it to 45
  or clear it.

### The DMARC finding said its point twice in every message (PR #35)
- **Problem:** a fresh report with PR #34's copy, then five redrafts: 0 of 5. Every draft passed the code check,
  and four passed all three reviews. The editor failed all of them for the same pair: the summary "forged emails
  are still delivered" and the explanation's "scammers can send emails that appear to come from your domain".
- **Cause:** the check's own copy put the consequence in both the summary and the shared explanation.
- **What we did:** the explanation now says only what DMARC is and does. The consequence lives in each case's
  summary; the no-record summary gained it in PR #36, after it was found missing from #35.
- **What it fixed:** the next fresh report's draft passed every gate, and 4 of 5 redrafts did too: 5 of 6 in all,
  up from 0 of 5. The one failure was a real catch: a step that named no one to ask.

### A clean site's message had nothing to say (PR #33)
- **Problem:** with the verdicts and the "needs action" line gone, the clean site's message read only "nothing is
  broken; see the report". Every draft passed the code check and all three reviews, and the editor failed 5 of 5:
  it never said what matters or gave a step.
- **Cause:** the message led only with findings the report ranks as costing customers. Email protection and
  security settings never rank there, so a site whose only findings are those led with nothing.
- **What we did:** when nothing ranks that high, code leads with the report's own first three confirmed findings,
  in the report's order. The model still never chooses what to lead with.
- **What it fixed:** the next redraft passed 1 of 5, up from 0 of 5, and the messages now lead with real findings.
  The remaining flags were mostly in the DMARC check's own copy: DKIM named but never explained, and a fix that
  starts from "the DMARC reports" without saying what they are or who reads them. PR #34 fixes both at the source.

### An independent audit found a FAIL that could vanish, from a rule we added that day (PR #31)
- **Problem:** an independent audit of the whole workflow found that the code check enforced only the report's
  top findings, not everything the message must lead with, which also includes anything broken today. A draft
  that listed nothing could hide a FAIL, and PR #30's closing line would then have told the owner nothing needed
  action. The audit proved it with a probe: a missing mail server, and a message saying none needed action.
- **Also from the audit:** the writer's prompt still said "if the website is in good shape, say so plainly"
  (which the code check rejects) and "say so" for checks that were not checked (which the code check also
  rejects), so the prompt invited failures.
- **What we did:** the code check requires every check in lead_with, with a test using a FAIL outside the top
  findings. The "needs action" line is gone (see the next entry). The two contradicting prompt lines are removed.
  The audit's other findings are listed in the pull request and fixed in their own pull requests.
- **What it fixed:** a broken check can no longer be left out of the message.

### A clean site invited the writer to sum it up (PR #30)
- **Problem:** the last consented site has nothing broken and nothing the report ranks as worth doing first, so the
  message had only its short version. Redrafted 5 times, it passed 1 of 5. Three drafts filled the space with a
  verdict of their own ("doing well overall", "in sound shape"), and all three reviews failed each one. The fifth
  passed the reviews, and the editor failed it for not saying whether the owner needs to do anything, and for
  giving the count twice.
- **Cause:** the prompt asked for "how the website is doing overall", which invites a verdict, and the score and
  reading already are one. Adding each new phrase to the code check (PR #29) would never end.
- **What we did:** the prompt no longer asks how the site is doing; the score and the reading are the judgment,
  and the writer adds none, nor a count. When there is nothing to lead with, code's closing line says what the
  report's own count says: "None of them needs action now, and the report explains each one." The code check also
  rejects "doing well", "sound shape" and "good condition" as a backstop.
- **What it fixed:** the verdicts stopped, and the code line was wrong. On the next redraft all three reviews
  rejected "None of them needs action now" in 5 of 5 drafts, rightly: this site's DMARC is in monitoring-only mode,
  so forged email is still delivered, and the report recommends fixing it. The reviewers judged a line they were
  told was code's, and they were right to. PR #31 removes it.

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

### A second audit: a redirect to someone else's site, and the TLS check's own connection (PR #38)
- **Problem:** a second independent audit (November 5, on a different model, told what the first had found) found
  two holes. A submitted domain whose home page redirects to another website got that other site checked in
  full: rendered with a screenshot, its links verified, its contact page loaded, and sent to Google's speed test.
  A throwaway domain pointed at a competitor would get us a report on a site whose owner never asked. And the
  TLS check opens its own connection, outside PR #32's guard, so a domain pointing at a private address would
  have had its certificate read.
- **What we did:** when the home page lands on a different website, nothing more is fetched, rendered, verified
  or sent to Google, and the report says why. A move within the same site (www, https, a subdomain) is fine. The
  TLS check refuses private addresses before it connects.
- **What it fixed:** tests prove the off-site stop, the same-site moves still allowed, and that the TLS check
  never opens a socket to a private address.
### Anyone could make us report the same site every hour (PR #37)
- **Problem:** the independent audit (November 4) found no limit on repeat submissions. The pipeline deduped by
  form submission id only, so a bot submitting one domain 50 times would have made about 100 requests to that
  site each time, plus paid Google and Anthropic calls. CLAUDE.md requires deduping and rate limiting.
- **What we did:** a domain reported in the last 14 days gets no second report; the reviewer gets a "REPEAT
  REQUEST" notice and can run one by hand. At most 3 reports run per hourly pass; the rest stay unseen and run on
  the next pass, so a burst spreads over hours instead of one long run.
- **Found by a second audit before merging:** skipped submissions (no website, a repeat) counted against the cap,
  so a pile of junk could starve a real request for hours; and the guard looked only for a report folder, which a
  run that failed partway never wrote. Now only submissions that reach a report count, and the guard also reads
  the run log, which is written before a run starts. The 14-day window uses UTC dates, like the folders.
- **What it fixed:** tests show a recent domain is never run, an old one still is, a burst of four runs as two
  then two, junk does not use up the cap, and a crashed run still counts as recent.

### A submitted page could make the report contact our own network (PR #32)
- **Problem:** an independent audit (November 4) found that nothing stopped the report from following a link,
  redirect or script to a private address. Anyone can submit a domain, so a page linking to `http://192.168.1.1/`,
  or a domain whose DNS points at 127.0.0.1, would have made the PC running the report send requests into its own
  network, and the answers could reach the report and the AI facts. This is server-side request forgery.
- **What we did:** `netguard.py`. Every HTTP request the report makes, including each redirect hop, goes through a
  transport that refuses loopback, private, link-local, reserved and multicast addresses before anything is sent.
  The browser aborts the same requests. A refused link is reported as not verified, never contacted.
- **Limit:** the address is checked when a request starts; a DNS answer that changes before the connection
  (rebinding) is not yet covered. Stated in the module.
- **What it fixed:** tests prove a private redirect hop and a private link never reach the network.

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
