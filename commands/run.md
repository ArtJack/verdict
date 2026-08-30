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
4. **Gate your own run, and paste the result verbatim.** Before the handoff, run:

   ```
   python3 <plugin-root>/src/verdict_mcp/gate.py <project> \
       --require-harness --min-run-number <the run_number you just wrote> --format text
   ```

   `<plugin-root>` is the path §0 resolved. Do **not** type `$CLAUDE_PLUGIN_ROOT` into the
   shell — it is substituted into these files as text and is not an environment variable,
   so bash expands it to nothing and the command becomes `python3 /src/...`.

   Report its exit code and reason as the first line of your handoff, unedited. This is
   not ceremony — it is the only check that reads what you *actually left on disk* rather
   than what you meant to leave, and it has caught every one of these in a real run:

   - **exit 6** — the state was hand-written. You skipped `verdict-facts` /
     `verdict-finalize` and composed the numbers instead of measuring them. The run is not
     finished: redo it through the harness. Do not explain the 6 away.
   - **exit 5** — `run_number` did not advance, so nothing you did reached disk.
   - **exit 4** — no usable state at all.
   - **1 / 3 / 0** — a real verdict (fail / blocked / pass) on a run that is admissible.

   A haiku-model run of this very command wrote to the default state root while
   `$VERDICT_HOME` pointed elsewhere, invented a project key, skipped the harness, and
   still produced a confident, plausible-looking `FAIL`. Every downstream guard would have
   caught it; none of them fired, because nothing invoked them. This step is what invokes
   them.

5. Close with the §13 handoff — verdict, counts by severity, top findings, artifact path.

If the caller wants a specific job rather than the daily pass, point them at the command
that owns it and stop: `/qa-status` (read the memory, run nothing) · `/qa-cause` (trace a
failure to its root cause) · `/qa-flake` (classify an intermittent failure) ·
`/qa-spec` (judge a spec before code exists) · `/qa-release` (the release gate) ·
`/qa-bug` (turn a report into a structured finding).

Verdict reports and specifies; it never fixes. Route fixes to the implementer.
