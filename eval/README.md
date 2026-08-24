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
| — | — | — | First published run pending; misses will be listed, not hidden. |

Honesty rule: results are published as measured. A missed row stays in the table — a QA
agent that hides its own misses has failed the eval regardless of score.
