---
description: "Run Verdict. The front door: reads the tester's memory and picks the right pass — baseline, delta, or a scoped review."
argument-hint: "[optional: what to review — a branch, diff range, feature, or area]"
---

Run Verdict on this repository, scoped to:

`$ARGUMENTS`

This is the one command a newcomer should need (`/verdict:run`). **Route first, then run** — the state
already knows which pass is correct, so do not ask the caller to know it:

1. Resolve the QA root per §0 (team `.qa/` first, then
   `${VERDICT_HOME:-~/.claude/verdict}/<key>`) and read `state.json`. Report which root
   you resolved and how, in one line, before anything else.
2. Choose the pass from what you found, and **say which you chose and why**:
   - **No state** → a baseline run. Create the QA root and a `profile.md` stub per §0/§6,
     including its front-matter block, and say plainly that this is run 1 with no history
     to compare against.
   - **State exists, no arguments** → today's delta pass: scope by
     `git diff <last_sha>..HEAD`, address the previous run's `next_run_focus` item by
     item, re-evaluate expired quarantine entries, age every finding
     (`NEW / STILL_OPEN / RESOLVED / REGRESSED`, REGRESSED ranked first).
   - **State exists, arguments given** → a delta pass narrowed to what the caller named.
     Narrowing scope is legitimate; **narrowing the artifact is not** (§7), and everything
     outside the narrowed scope goes to `not_tested` rather than going unmentioned.
   - **A §6 re-baseline trigger trips** — older than 7 days, ~100 files, ~10,000 lines, or
     a stored SHA this repository does not contain → *declare* the re-baseline. Never
     fabricate a diff against a commit that is gone.
3. Run it through the harness (§6): `verdict-facts` → your `judgment.json` →
   `verdict-finalize`. The gates come from the profile; you do not retype commands.
4. Close with the §13 handoff — verdict, counts by severity, top findings, artifact path.

If the caller wants a specific job rather than the daily pass, point them at the command
that owns it and stop: `/qa-status` (read the memory, run nothing) · `/qa-cause` (trace a
failure to its root cause) · `/qa-flake` (classify an intermittent failure) ·
`/qa-spec` (judge a spec before code exists) · `/qa-release` (the release gate) ·
`/qa-bug` (turn a report into a structured finding).

Verdict reports and specifies; it never fixes. Route fixes to the implementer.
