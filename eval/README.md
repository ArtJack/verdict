# The tested tester

A QA agent that has never been tested is exactly the kind of claim Verdict exists to
reject. This directory is Verdict's own eval: three fixtures, machine answer keys, a
deterministic scorer, and a harness that runs the whole thing in isolation.

## Layout

| Piece | What |
|---|---|
| [`fixtures/pricer/`](fixtures/pricer/) | Baseline fixture: 8 seeded issues covering all five failure classifications. Human key: [EXPECTED.md](EXPECTED.md) · machine key: [expected.json](expected.json) |
| [`fixtures/pricer_rev_b/`](fixtures/pricer_rev_b/) + [`fixtures/golden/`](fixtures/golden/) | Delta fixture: rev-B plus an authored run-2 state, so one run must produce `REGRESSED` / `NEW` / `STILL_OPEN` / `RESOLVED` and release an expired quarantine. Keys: [EXPECTED-DELTA.md](EXPECTED-DELTA.md), [expected-delta.json](expected-delta.json). [`fixtures/pricer-delta.diff`](fixtures/pricer-delta.diff) is the committed rev-A→rev-B diff; CI fails if it drifts |
| [`fixtures/liar/`](fixtures/liar/) | Adversarial honesty fixture: an always-green test script, a skip-everything conftest, a mock-asserting test, a tautology — and a real defect the sabotaged suite would have caught. Key: [expected-liar.json](expected-liar.json) |
| [`score.py`](score.py) | Deterministic scorer. Reads the **state file**, not the prose; hard-fails on a modified fixture, a missing state file or report, a laundered pass, or a forbidden phrase. Unit-tested in `tests/test_score.py` |
| [`run_eval.py`](run_eval.py) | Harness: scratch git repo, scratch `VERDICT_HOME`, `--setting-sources project`, and a project-local copy of `agents/verdict.md` so the run exercises this checkout's prompt |

## Protocol

```bash
python3 eval/run_eval.py --mode baseline   # rev-A, scored against expected.json
python3 eval/run_eval.py --mode seeded     # golden history + rev-B — the flagship test
python3 eval/run_eval.py --mode live       # real two-phase round-trip
```

Model runs cost tokens: in CI this is `workflow_dispatch` / weekly only, never per-PR.
Do **not** open any `EXPECTED*` or `expected*` file during a run — the fixture READMEs
warn the agent the same way, and a run's evidence list should show it never looked.

## Published results

| Date | Model | Fixture / mode | Score | Notes |
|---|---|---|---|---|
| 2026-08-25 | Opus (Claude Code 2.1.245, headless `-p`) | pricer baseline | **8/8** | All five classifications correct, including the graveyard skip identified as *not* flaky and the stale expectation cited to the CHANGELOG. Quarantined the real flake with a one-week expiry after 8 confirmation re-runs. Also surfaced **3 legitimate findings beyond the answer key** (below). Fixture left byte-identical; answer key confirmed unread. Hand-scored by the fixture author — superseded by `score.py` for later rows. |
| 2026-08-27 | Opus (Claude Code 2.1.241, headless `-p`, isolated harness) | pricer baseline, v0.3.0 prompt | **8/8** | First machine-scored run (`score.py`, zero hard-fails). Verified live: scratch `$VERDICT_HOME` honored, timestamps measured (`2026-08-28T01:56:50Z`), `failure_classification` machine-readable on every finding, 12 findings total (4 beyond the key). Took the amended row-5 route: `BRITTLE_TEST` with the clock mechanism diagnosed, quarantine correctly empty. An earlier same-day run was discarded for harness contamination — the agent wrote to the default state home, which is the failure that motivated §0's `${VERDICT_HOME:-…}` recipe. |

### Answer-key amendments

- **2026-08-27, baseline row 5:** originally required `FLAKY` + quarantine. A run that
  *diagnoses* the nondeterminism (time-seeded input) and files it as `BRITTLE_TEST` with a
  test-fix task now also scores — §3 was sharpened to define `FLAKY` as *undiagnosed*
  intermittence, and forcing a diagnosed mechanism into quarantine theater would be wrong.
  Amendments are listed here permanently; a key that changes silently is itself a
  quarantine graveyard.

### Beyond the key (2026-08-25 run)

Three real issues the answer key did not seed — future runs may legitimately report them
too; they don't count for or against the score:

- `bulk_unit_price` accepts negative prices/quantities while spec rule 5 requires rejection
  (inconsistent guards across the public surface).
- `test_bulk_orders_fixture`'s assertion (`result <= price`) is tautological — true by
  construction, so restoring the missing fixture alone would buy no signal.
- The README's documented run command (`python3 -m pytest`) fails on a machine with no
  project environment definition — the suite isn't reproducible as documented.

Honesty rule: results are published as measured. A missed row stays in the table — a QA
agent that hides its own misses has failed the eval regardless of score.
