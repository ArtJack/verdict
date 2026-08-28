# Answer key — delta eval (run 3 on `pricer_rev_b`)

**Do not read this file during an eval run.** This key scores the flagship behavior — the
delta report — not defect-finding from scratch. `eval/run_eval.py` prepares the history;
the agent then runs against `fixtures/pricer_rev_b/` and must classify what *changed*.

Two modes:

- **`seeded` (default, one model run):** the harness plants the authored run-2 state from
  [`fixtures/golden/`](fixtures/golden/) as QA history. All four delta classes are
  reachable at once.
- **`live` (two model runs):** phase 1 is a real baseline on rev-A, phase 2 a delta run on
  rev-B against phase 1's own state — the true round-trip. Rows that need three-state
  history (REGRESSED, quarantine expiry) are unreachable and score `n/a`.

| Row | What rev-B seeds | Expected (seeded) | Expected (live) |
|---|---|---|---|
| regressed-rounding | `round_cents` is banker's again; golden history recorded it **resolved** in run 2 | `REGRESSED`, `REAL_DEFECT` — ranked first in the report | n/a (real history says STILL_OPEN) |
| new-bulk-threshold | `qty >= 10` became `qty > 10` — exactly-10 orders lose the discount; spec rule 4 says "10 or more"; no intent citation anywhere | `NEW`, `REAL_DEFECT` | `NEW`, `REAL_DEFECT` |
| still-open-floor | `is_listable` still rejects the at-floor price; its test still skip-quarantined | `STILL_OPEN` with grown age | `STILL_OPEN` |
| resolved-env-fixture | `fixtures/bulk_orders.json` now exists (and the tautological assertion became a real one) | `RESOLVED` | `RESOLVED` |
| quarantine-released-on-expiry | the flake is deterministic now; the golden quarantine entry expired 2026-08-26 | entry re-evaluated on expiry and **released** — not left as a graveyard | n/a (phase-1 quarantine has not expired) |
| verdict | two open REAL_DEFECTs | `fail` | `fail` |

Suite-level expectations, both modes: the report ranks `REGRESSED` first when one exists;
the fixture tree is left byte-identical; the report never contains "no bugs found"; the
state file is written with `run_number` advanced.

Traps worth naming: the CHANGELOG's 2026-08-30 "test maintenance" entry legitimately
explains the stale-fee fix and the fixture addition — it says nothing about the `qty`
threshold, so the bulk-discount failures have **no** intent citation and must be
`REAL_DEFECT`/`NEW`, not `STALE_EXPECTATION`. And the de-flaked `test_bulk_discount_applies`
is now red for a *code* reason — releasing it from quarantine and then blaming the test
would be wrong twice.

Scoring is mechanical: `python3 eval/score.py --qa-root <root> --expected
eval/expected-delta.json --mode seeded|live --fixture-dir <checkout>`. A modified fixture,
a missing state file or report, or a "no bugs found" is an automatic overall fail.
