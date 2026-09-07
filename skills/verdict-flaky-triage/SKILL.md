---
name: verdict-flaky-triage
description: Classify an intermittent test failure with evidence — REAL_DEFECT, STALE_EXPECTATION, BRITTLE_TEST, ENVIRONMENT or FLAKY — and decide quarantine with a mandatory expiry. Use when a test fails one run in five, when CI is "just flaky", or before anyone skips a test.
---

# Verdict: flaky-test triage

"The test is flaky" is a conclusion, not an observation. The default drift is to assume the
test is stale and rubber-stamp a regression; the job is to say what the failure *means*
before anyone acts on it.

**In Claude Code with the Verdict plugin, use `/verdict:flake <test id>`.** This skill is
the same procedure for agents that cannot run it.

## Procedure

1. **Reproduce first.** Run the exact test at least three times from a clean state and
   record a per-run outcome table. The same result every run is not flaky — classify it
   as what it is.
2. **Hunt the mechanism before reaching for quarantine:** clock- or time-seeded inputs,
   test ordering, shared state, network, fixture races, concurrency, a cached property
   read before the value it caches. A diagnosed mechanism is `BRITTLE_TEST`: file the
   test-fix task and keep the finding inside the verdict — no quarantine.
3. **Classify into exactly one**, stating the evidence:
   - `REAL_DEFECT` — the code is wrong. File it; do not fix it.
   - `STALE_EXPECTATION` — behaviour changed on purpose and the test was not updated.
     Needs a citation that the change was intended (commit, changelog, requirement);
     without one it is a `REAL_DEFECT`. This is the classification most likely to be
     wrong in your favour — hold it to the highest bar.
   - `BRITTLE_TEST` — depends on an incidental detail (ordering, timing, formatting,
     internals). A finding in its own right.
   - `ENVIRONMENT` — infra, clock, missing fixture or tool. Report `blocked`, not red or
     green.
   - `FLAKY` — passes and fails without a code change, cause not yet diagnosed.
4. **Quarantine is diagnosis deferred, with an expiry.** A `FLAKY` entry is
   `{test_id, first_seen, fail_count, run_count, quarantined_until}` in the judgment's
   `flaky_quarantine`; one to two weeks; excluded from the verdict, never from the report.
   On expiry the entry is re-evaluated as an action: release it and say why, or
   re-quarantine with fresh run evidence and a new date. "Recommend lifting" while the
   entry stays is a dodge. A test skipped "temporarily" with no expiry is a graveyard entry
   — flag it.
5. **Record it** through the harness (`verdict-facts` → the finding file and
   `judgment.json` → `verdict-finalize`; see `verdict-release-risk`) and report: the
   classification, the run-outcome table, and exactly what the re-evaluation must check.

Verdict reports and specifies; it never fixes. Route the fix to the implementer, then
verify it (`verdict-verify-fix`).
