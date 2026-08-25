# The tested tester

A QA agent that has never been tested is exactly the kind of claim Verdict exists to reject.
This directory is Verdict's own eval: a small fixture app with **seeded defects covering all
five failure classifications**, and an answer key.

## Protocol

1. Open a Claude Code session in `eval/fixtures/pricer/` (or point the agent at it).
2. Run `/qa-review the pricer module` — nothing else. Do **not** open `eval/EXPECTED.md`
   during the run (the fixture README warns the agent the same way).
3. Compare the report against [EXPECTED.md](EXPECTED.md): 8 rows, found + correctly
   classified = 1 point each.

## What the fixture seeds

One of each: a boundary `REAL_DEFECT` no test catches (its test is skip-quarantined with no
expiry), a failing test that is a `STALE_EXPECTATION` with an intent citation available in
the CHANGELOG, a failing test that is a genuine `REAL_DEFECT` (banker's vs half-up
rounding), a `FLAKY` test (nondeterministic input), a green-but-`BRITTLE_TEST` (exact error
message assertion), and an `ENVIRONMENT` error (missing fixture file). The verdict itself is
scored: excluding the flake, separating environment from defect, and routing the stale
expectation to a test update rather than a code fix.

## Published results

| Date | Model | Score | Notes |
|---|---|---|---|
| 2026-08-25 | Opus (`--model opus`, Claude Code 2.1.245, headless `-p`) | **8/8** | All five classifications correct, including the graveyard skip identified as *not* flaky (re-verified deterministically) and the stale expectation cited to the CHANGELOG. Quarantined the real flake with a one-week expiry after 8 confirmation re-runs. Also surfaced **3 legitimate findings beyond the answer key** (see below). Fixture left byte-identical (pytest provisioned out-of-tree); answer key confirmed unread via the report's evidence list. Scored by the fixture author — an independent re-run is welcome. |

### Beyond the key

The 2026-08-25 run also reported three real issues the answer key did not seed — future runs
may legitimately report them too, and they don't count for or against the 8-row score:

- `bulk_unit_price` accepts negative prices/quantities while spec rule 5 requires rejection
  (inconsistent guards across the public surface).
- `test_bulk_orders_fixture`'s assertion (`result <= price`) is tautological — true by
  construction, so restoring the missing fixture alone would buy no signal.
- The README's documented run command (`python3 -m pytest`) fails on a machine with no
  project environment definition — the suite isn't reproducible as documented.

Honesty rule: results are published as measured. A missed row stays in the table — a QA
agent that hides its own misses has failed the eval regardless of score.
