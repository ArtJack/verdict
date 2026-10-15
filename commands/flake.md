---
description: "Classify an intermittent test failure and decide quarantine, with evidence."
argument-hint: "<test id or name> [observed failure rate, logs]"
---

Use the `verdict` agent to classify this suspected flaky test:

`$ARGUMENTS`

Required flow:

1. **Reproduce first**: run the exact test ≥3 times from a clean state (§9) and record a
   per-run outcome table. The same result every run means it is not flaky — classify per
   §3 and say what it actually is.
2. **Hunt the mechanism before reaching for quarantine**: clock/time-seeded inputs, test
   ordering, shared state, network, fixture races, concurrency. A diagnosed mechanism is
   `BRITTLE_TEST` (§3): file the test-fix task and keep the finding inside the verdict —
   no quarantine.
3. Genuine intermittence with the cause still unknown is `FLAKY`: quarantine with
   `{test_id, first_seen, fail_count, run_count, quarantined_until}` — the expiry is
   mandatory (one to two weeks), and the entry is re-evaluated when it lapses.
4. Update `state.json` (ledger and a finding either way) and report: the classification,
   the run-outcome evidence table, and exactly what the re-evaluation on expiry must
   check.
