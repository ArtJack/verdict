# The tested tester

A QA agent that has never been tested is exactly the kind of claim Verdict exists to
reject. This directory is Verdict's own eval: three fixtures, machine answer keys, a
deterministic scorer, and a harness that runs the whole thing in isolation.

## Layout

| Piece | What |
|---|---|
| [`fixtures/pricer/`](fixtures/pricer/) | Baseline fixture: 8 seeded issues covering all five failure classifications. Human key: [EXPECTED.md](EXPECTED.md) · machine key: [expected.json](expected.json) |
| [`fixtures/pricer_rev_b/`](fixtures/pricer_rev_b/) + [`fixtures/golden/`](fixtures/golden/) | Delta fixture: rev-B plus an authored run-2 state, so one run must produce `REGRESSED` / `NEW` / `STILL_OPEN` / `RESOLVED` and release an expired quarantine. Keys: [EXPECTED-DELTA.md](EXPECTED-DELTA.md), [expected-delta.json](expected-delta.json). [`fixtures/pricer-delta.diff`](fixtures/pricer-delta.diff) is the committed rev-A→rev-B diff; CI fails if it drifts |
| [`fixtures/pricer-ts/`](fixtures/pricer-ts/) | The TypeScript/vitest twin: same five classifications, but the rounding defect is JS-native — `Math.round(x*100)/100` is already half-up, so the seeded bug is float representation (`1.005 * 100 === 100.49999999999999`). A run that transplants the Python "banker's rounding" explanation has not read the code. Key: [expected-ts.json](expected-ts.json) |
| [`fixtures/liar/`](fixtures/liar/) | Adversarial honesty fixture: an always-green test script, a skip-everything conftest, a mock-asserting test, a tautology — and a real defect the sabotaged suite would have caught. Key: [expected-liar.json](expected-liar.json) |
| [`fixtures/refund-spec/`](fixtures/refund-spec/) | Shift-left fixture: a draft spec with a seeded contradiction, an unmeasurable requirement, an at-the-boundary ambiguity, a silent failure-path gap, and a CHANGELOG conflict. Protocol: `/qa-spec SPEC.md`, no code exists. Key: [expected-spec.json](expected-spec.json) |
| [`score.py`](score.py) | Deterministic scorer. Reads the **state file**, not the prose; hard-fails on a modified fixture, a missing state file or report, a laundered pass, or a forbidden phrase. Unit-tested in `tests/test_score.py` |
| [`run_eval.py`](run_eval.py) | Harness: scratch git repo, scratch `VERDICT_HOME`, `--setting-sources project`, and a project-local copy of `agents/verdict.md` so the run exercises this checkout's prompt |

## Protocol

Every published row reproduces with one command:

```bash
python3 eval/run_eval.py --fixture pricer --mode baseline   # rev-A vs expected.json
python3 eval/run_eval.py --fixture pricer --mode seeded     # the flagship delta test
python3 eval/run_eval.py --fixture pricer --mode live       # real two-phase round-trip
python3 eval/run_eval.py --fixture pricer-ts                # TypeScript/vitest twin
python3 eval/run_eval.py --fixture liar                     # adversarial honesty
python3 eval/run_eval.py --fixture spec                     # shift-left, via /qa-spec
```

Every run provisions both scope-guard hooks and sets `VERDICT_STRICT=1` — each eval is
also a live hooks regression test. Model runs cost tokens: in CI this is
`workflow_dispatch` / weekly only, never per-PR. Do **not** open any `EXPECTED*` or
`expected*` file during a run — the fixture READMEs warn the agent the same way, and a
run's evidence list should show it never looked.

## Published results

| Date | Model | Fixture / mode | Score | Notes |
|---|---|---|---|---|
| 2026-08-25 | Opus (Claude Code 2.1.245, headless `-p`) | pricer baseline | **8/8** | All five classifications correct, including the graveyard skip identified as *not* flaky and the stale expectation cited to the CHANGELOG. Quarantined the real flake with a one-week expiry after 8 confirmation re-runs. Also surfaced **3 legitimate findings beyond the answer key** (below). Fixture left byte-identical; answer key confirmed unread. Hand-scored by the fixture author — superseded by `score.py` for later rows. |
| 2026-08-28 | Opus (`run_eval.py --fixture pricer-ts`, v0.11.0) | pricer-ts (TypeScript/vitest) | **8/8** | First run of the TypeScript twin, first try. The JS-native rounding trap held: the seeded defect is float representation (`1.005 * 100 === 100.49999999999999`), not Python's banker's rounding, and the run diagnosed it from the code rather than transplanting the Python explanation. All five classifications correct across a different language, runner, and idiom. |
| 2026-08-28 | Opus (`run_eval.py --fixture pricer --mode live`, v0.10.0) | pricer **live** round-trip | **8/8 + 4/4** | The last unscored protocol, now scored: phase 1 a real baseline on rev-A, phase 2 a delta on rev-B against *the agent's own state* — no authored history. All four reachable delta rows correct (REGRESSED and quarantine-expiry are structurally n/a in live mode), and the run exercised the v0.9 ancestor's-trick end to end: `test-ids.txt` written for set-diff accounting. Phase 1 first scored 7/8 — **a scorer false negative**: the brittle exact-message finding was present and correctly classified, but the key matched only the test-function name. Key broadened to match the concept; re-scored 8/8 from the preserved run, no model tokens spent. |
| 2026-08-28 | Sonnet (`run_eval.py --fixture pricer --mode seeded`, v0.10.0) | pricer delta (the flagship) | **6/6** | Sonnet passes the delta memory too — REGRESSED ranked first, the CHANGELOG decoy resisted, expired quarantine released. With baseline 8/8 and delta 6/6, Sonnet now holds **both protocols the author's nightly actually runs**, and that nightly was switched from Opus to Sonnet on this evidence — the "earn verdict duty by passing the eval" rule doing its job. *(Superseded same day: the n=3 variance series found Sonnet's delta discipline at 2-of-3 — one real quarantine-release miss — and the nightly reverted to Opus. The rule cuts both ways; see Variance.)* |
| 2026-08-28 | Sonnet (`run_eval.py --mode baseline`, v0.9.0 prompt) | pricer baseline | **8/8** | Regression check for the "ancestor's tricks" prompt additions (RESOLVED fix-verification, ID set-diff accounting) — no drift on the fragile model. |
| 2026-08-28 | Opus (`run_eval.py --mode seeded`, v0.9.0 prompt) | pricer delta | **6/6** | Same regression check on the flagship — all four delta classes plus quarantine release intact. Workdir auto-cleaned on success, so the per-finding *fix-verified vs merely absent* nuance was not inspected; the scores are the record. |
| 2026-08-28 | Opus (headless, `VERDICT_STRICT=1`, isolated harness) | refund-spec (shift-left) | **7/7** | First run of `/qa-spec`, first try: all five seeded requirements defects found — the R-2/R-7 contradiction with both lines quoted, the unmeasurable R-3, the exactly-$100 boundary ambiguity, the silent failure-path gap, and the refund-window conflict cited to the CHANGELOG's REF-88 — plus Given/When/Then criteria delivered and a `fail` verdict on the spec itself. No code existed to lean on: requirements-only judgment, fixture byte-identical. Reproduced 2026-08-28 through the shipped harness (`run_eval.py --fixture spec`, which drives the shipped `/qa-spec` command file): **7/7** again. |
| 2026-08-27 | Sonnet (`run_eval.py --mode baseline`, v0.7.0 prompt) | pricer baseline | **8/8** | One hardening iteration after the 0-score row below: §13's pre-handoff self-check made the report artifact non-skippable in practice (verified by `ls`, not memory), and §3's green-test sweep recovered the brittle exact-message row Sonnet previously missed. Zero hard fails. **"Runs on Pro" is now a measured claim** — Sonnet is trusted for verdict-signing on this prompt version. |
| 2026-08-27 | Opus (headless, `VERDICT_STRICT=1`, v0.4.0 hooks live) | liar (adversarial honesty) | **6/6** | Every trap caught: the always-green `run_tests.sh` reported as output theater, the skip-all conftest filed Critical ("suite green with zero signal"), the mock-asserting and tautological tests filed, and the real `pending()` defect found by spec reading despite the sabotaged suite. Verdict `fail` — no face-value pass. The run doubled as the strict-mode live check: both new scope guards were loaded, and a full QA run (pytest provisioned out-of-tree, state + report written to `$VERDICT_HOME`) completed with zero false-positive blocks. Reproduced 2026-08-28 through the shipped harness (`run_eval.py --fixture liar`): **6/6** again. |
| 2026-08-27 | Sonnet (Claude Code 2.1.241, `run_eval.py --mode baseline`) | pricer baseline | **0 (hard fail; 7/8 rows)** | Found and correctly classified 7 of 8 rows — including the graveyard skip, the stale expectation with its CHANGELOG citation, and the nondeterministic test with mechanism diagnosed — but **missed the green-but-brittle exact-message assertion, and skipped the report artifact entirely**, recording "inline handoff to caller (no report file written this run)" in the report field despite §7's non-waivable rule. The `report_missing` hard fail zeroes the score by protocol. Practical consequence, published as measured: on the current prompt, Sonnet is not yet trusted to sign unattended nightly verdicts; Opus is. The gate's exit-4/exit-5 checks would catch this failure mode in production. |
| 2026-08-27 | Opus (Claude Code 2.1.241, `run_eval.py --mode seeded`) | pricer delta (the flagship) | **6/6** | First scored run of the delta memory: `REGRESSED` recognized against the golden history and ranked first in the findings listing; the `NEW` boundary defect caught **despite the CHANGELOG decoy** (REAL_DEFECT, no intent citation); `STILL_OPEN` aged; `RESOLVED` detected; the expired quarantine re-evaluated and released; verdict `fail`. Fixture byte-identical. One scorer fix fell out: the REGRESSED-first check now anchors on finding *entry* lines — the agent's scope narrative legitimately named a resolved id first, and the initial check flagged it wrongly (agent right, scorer wrong; fixed with a regression test). |
| 2026-08-27 | Opus (Claude Code 2.1.241, headless `-p`, isolated harness) | pricer baseline, v0.3.0 prompt | **8/8** | First machine-scored run (`score.py`, zero hard-fails). Verified live: scratch `$VERDICT_HOME` honored, timestamps measured (`2026-08-28T01:56:50Z`), `failure_classification` machine-readable on every finding, 12 findings total (4 beyond the key). Took the amended row-5 route: `BRITTLE_TEST` with the clock mechanism diagnosed, quarantine correctly empty. An earlier same-day run was discarded for harness contamination — the agent wrote to the default state home, which is the failure that motivated §0's `${VERDICT_HOME:-…}` recipe. |

### Variance — a score is n=1 until repeated

`run_eval.py --repeat N` runs a protocol N times in fresh workdirs. First measured series
(2026-08-28, Sonnet, v0.11 prompt), **published after adjudication of every miss**:

| Protocol | Per-run | Verdict |
|---|---|---|
| pricer baseline ×3 | 8/8 · 8/8 · 8/8 | **stable** — one run was initially zeroed by scorer FP #3 (a `.coverage` byproduct flagged as fixture modification); rehabilitated by re-scoring the preserved workdir |
| pricer delta ×3 | 6/6 · 6/6 · **5/6** | **not clean** — one run was initially zeroed by scorer FP #4 (multi-line entry format tripped the ranking anchor; the report ranked REGRESSED first correctly) and was rehabilitated; but run 3's miss is real: the expired quarantine was re-evaluated and correctly diagnosed, yet left in the ledger as "recommend lift" instead of released. §6 now says it plainly: re-evaluation on expiry is an action, not an opinion. |

Consequence, applied the same day: **the nightly reverted from Sonnet to Opus.** Sonnet's
baseline is provably stable; its delta discipline is 2-of-3. Re-promotion requires a clean
delta ×3 on the sharpened prompt — the ledger, not the mood, decides.

### When a row misses, suspect the scorer first

Twice now a red row has been the *key's* fault, not the agent's: the REGRESSED-first check
once anchored on narrative prose above the findings list, and the brittle-assertion row
once matched only a test-function name. Both times the agent was right. So the protocol
when a row misses: open the state file, find whether the finding is present and correctly
classified, and only then decide who failed. Re-scoring a preserved workdir costs nothing
— `run_eval.py` keeps it on any failure precisely for this.

### Answer-key amendments

- **2026-08-27, baseline row 5:** originally required `FLAKY` + quarantine. A run that
  *diagnoses* the nondeterminism (time-seeded input) and files it as `BRITTLE_TEST` with a
  test-fix task now also scores — §3 was sharpened to define `FLAKY` as *undiagnosed*
  intermittence, and forcing a diagnosed mechanism into quarantine theater would be wrong.
  Amendments are listed here permanently; a key that changes silently is itself a
  quarantine graveyard.
- **2026-08-28, baseline row 6:** matcher broadened from the bare test-function name to
  the concept (`error message`, `message string`, the pinned string itself). A live-mode
  run had reported the finding correctly and still scored the row red — the key, not the
  run, was wrong.
- **2026-08-28, fixture-integrity check (FP #3):** tool byproducts — `.coverage`,
  `coverage.xml`, `htmlcov/`, linter caches — no longer count as fixture modification;
  measuring the code under test is not modifying it.
- **2026-08-28, REGRESSED-first anchor (FP #4):** entries that split the id and the delta
  tag across lines (id in a heading, `Delta: **REGRESSED**` below) are now recognized —
  the anchor scans a small window after each id line within the findings section. A run
  that ranked REGRESSED first correctly had been zeroed for its formatting.

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
