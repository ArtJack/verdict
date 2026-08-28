# Answer key — pricer fixture

**Do not read this file during an eval run.** It defines what a perfect QA pass on
`fixtures/pricer/` finds. Score = items correctly found AND correctly classified.

| # | Where | What a perfect run reports | Required classification |
|---|---|---|---|
| 1 | `pricer.py` `is_listable` | Boundary defect: spec rule 1 says a price **at** the floor is listable; `price > floor` rejects the exact-floor case | `REAL_DEFECT` (found by boundary value analysis — no failing test reveals it, see #2) |
| 2 | `test_pricer.py` `test_listable_at_floor_exactly` | Quarantine graveyard: skipped "temporarily" since 2026-05-02 with no expiry — and it is the exact test that would catch #1 | Finding in its own right (skip hides a real defect; quarantine must have expiry) |
| 3 | `test_pricer.py` `test_net_proceeds_hundred` | Fails (88.0 ≠ 90.0). CHANGELOG documents the 10%→12% fee raise as intended (PRC-142) | `STALE_EXPECTATION` — **with the CHANGELOG citation**; without a citation this must be filed as `REAL_DEFECT` |
| 4 | `pricer.py` `round_cents` / `test_round_cents_half_up` | Fails (0.12 ≠ 0.13). Spec rule 3 requires half-up; `round()` is banker's rounding | `REAL_DEFECT` (the test asserts the spec; the code is wrong) |
| 5 | `test_pricer.py` `test_bulk_discount_applies` | Passes or fails depending on `(time.time_ns() // 1000) % 2` (microsecond parity of the wall clock) — qty is 9 or 10 | `FLAKY` (confirmed by ≥3 runs; quarantined with expiry) **or** `BRITTLE_TEST` with the time-seeded mechanism explicitly diagnosed and a test-fix task filed — naming the nondeterminism is the skill scored. An undiagnosed "fails sometimes" scores 0. *(Amended 2026-08-27: §3 now defines FLAKY as undiagnosed intermittence; a diagnosed mechanism is BRITTLE_TEST. A run that already names the mechanism should not be forced into quarantine theater.)* |
| 6 | `test_pricer.py` `test_negative_price_message` | Passes, but asserts the exact human-readable message string — an incidental detail | `BRITTLE_TEST` (green tests can still be findings) |
| 7 | `test_pricer.py` `test_bulk_orders_fixture` | Errors: `fixtures/bulk_orders.json` does not exist | `ENVIRONMENT` (missing fixture — not a code defect; suite is neither green nor red on this basis) |
| 8 | Suite-level | The run is not "4 failed" at face value: each red test means something different, and the verdict must exclude the flake, count the graveyard, and separate environment from defect | Correct verdict: `fail` (open REAL_DEFECTs #1 and #4), with #3 routed to a test-update task, not a code fix |

## Scoring

- **8/8**: every row found with the required classification.
- A row found but misclassified scores 0 for that row (classification IS the skill).
- Reporting "no bugs found" or fixing any defect in place is an automatic overall fail.
