---
description: "Run today's delta QA pass against the stored baseline (the daily driver)."
argument-hint: "[optional focus areas or constraints for today's pass]"
---

Use the `verdict` agent to run a delta QA pass on this repository:

`$ARGUMENTS`

Required flow:

1. Read `<qa-root>/state.json` first (§6). **No state → stop and say so.** A delta run
   without a baseline is a contradiction — direct the caller to `/qa-baseline` instead of
   silently auditing from scratch.
2. Scope strictly by `git diff <state.last_sha>..HEAD` and report the SHA range in the
   header. Trip the §6 re-baseline triggers honestly — older than 7 days, ~100 files,
   ~10,000 lines, or an unresolvable stored SHA — and *declare* a re-baseline rather than
   faking a diff.
3. Address every item in the previous run's `next_run_focus` explicitly: done, still open,
   or why not.
4. Re-evaluate every quarantine entry whose `quarantined_until` has passed: release it,
   re-quarantine with fresh evidence and a new expiry, or reclassify per §3.
5. Age all findings and report `NEW / STILL_OPEN / RESOLVED / REGRESSED` — REGRESSED
   ranked first, always.
6. Gate on deltas (§6): coverage direction on changed files, duration vs recorded
   `duration_s`, silent test-count drops, collection errors.
7. Close with the §13 handoff; write state, report, and the INDEX row as always.
