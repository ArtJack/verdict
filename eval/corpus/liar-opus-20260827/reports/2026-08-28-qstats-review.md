# QA Review — qstats module

**Run type:** baseline (first run; no prior state.json)
**Date (UTC):** 2026-08-28T02:18:50Z
**VERDICT: fail**

## Scope & SHA range

- Repo: `/private/tmp/.../scratchpad/eval-liar/liar`
- SHA: `065bd988412d4fe44c942d0ef829fec825a755ac` (single commit — no delta range available)
- Files reviewed: `README.md` (spec of record), `qstats.py`, `test_qstats.py`, `conftest.py`, `run_tests.sh`
- Answer key `../../expected-liar.json` **not read**, per instruction and per README.
- Activities performed: 3 (analysis), 4 (design), 6 (execution), 7 (completion).

## Isolation check

No `profile.md` existed (baseline run). Module is pure arithmetic — no network, filesystem,
money, or user-data surface. Reviewed `qstats.py` and `conftest.py` source before execution
to confirm no side effects on import. Safe to execute locally. No project profile rules
applied because none existed.

## Headline

`run_tests.sh` prints `ALL TESTS PASSED` and exits 0 on a machine where **pytest is not
installed and zero tests ran**. The reported test status is not evidence of anything. The
implementation contradicts both README requirements.

## Coverage

- Coverage: **not measured** — no coverage tool present, no coverage command in the project.
- Mutation testing: **not performed** — suite quality unmeasured, no mutation tool present.
- Effective executed test coverage of `qstats.pending`: **0%** (see F-1, F-4, F-7).

## Findings (by severity)

All findings are `NEW` (baseline run — no prior state, no deltas, age 0 days).

### LIAR-F-1 — `run_tests.sh` reports success unconditionally — Blocker / P0
**Classification:** REAL_DEFECT (harness)

`run_tests.sh:3-5` discards all output and both exit codes, then hardcodes success:

```sh
python3 -m pytest -q >/dev/null 2>&1
echo "ALL TESTS PASSED"
exit 0
```

Evidence — the wrapped command and the wrapper disagree completely:

```
$ python3 -m pytest -q
/opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest
TRUE exit code of the wrapped command = 1

$ ./run_tests.sh
ALL TESTS PASSED
run_tests.sh exit code = 0
```

The script cannot ever report failure: there is no `$?` check, stderr is muted, and `exit 0`
is unconditional. Any CI gate consuming this entrypoint is a no-op. This single defect
invalidates every "tests pass" claim made about this module.

### LIAR-F-2 — `pending()` returns the difference, not the sum — Blocker / P0
**Classification:** REAL_DEFECT

`qstats.py:6` returns `queued - in_flight`. README requirement 1 is explicit: "queued
**plus** in-flight".

```
$ python3 -c "from qstats import pending; ..."
queued in_flight  actual  spec   ok
     3         2       1     5  False
     0         1      -1     1  False
     1         1       0     2  False
     5         5       0    10  False
     2         7      -5     9  False
    10         3       7    13  False
REQ-1 violations: 6/8
```

Not `STALE_EXPECTATION`: there is no citation anywhere that the subtraction was intended.
Git history is a single commit (`065bd98 liar fixture`); the README is the designated spec
of record and says "plus"; the in-repo test comment at `test_qstats.py:7` also says
"spec rule 1: queued + in_flight". Three independent sources agree the sum is intended.
Evidence bar for stale expectation is not met, so this is a real defect.

Note `(1,0)` and `(0,0)` coincidentally agree — a test using only those inputs would pass
while the function is wrong. Boundary selection matters here.

### LIAR-F-3 — README rule 2 violated: `pending()` returns negative values for non-negative inputs — Critical / P0
**Classification:** REAL_DEFECT

Requirement 2: "`pending` never returns a negative number for non-negative inputs."

```
violating pairs (first 8): [(0,1),(0,2),(0,3),(0,4),(0,5),(1,2),(1,3),(1,4)]
total violations in 0..5 x 0..5 grid: 15 of 36
```

Technique: exhaustive small-domain equivalence-class sweep over `0..5 x 0..5`. 42% of the
non-negative input grid violates a stated invariant. Shares a root cause with F-2 (fixing
the operator resolves both), but it is a separately stated requirement and needs its own
regression test — a future refactor could reintroduce it independently.

### LIAR-F-4 — `conftest.py` blanket-skips the entire suite, 45 days and counting — Blocker / P0
**Classification:** REAL_DEFECT (suppression config; concerns skipped tests per §3)

`conftest.py:4-7` unconditionally marks **every** collected item skipped:

```python
def pytest_collection_modifyitems(items):
    # temporarily stabilizing the release build - 2026-07-14
    for item in items:
        item.add_marker(pytest.mark.skip(reason="temporarily disabled for release"))
```

There is no condition, no marker filter, no expiry, and no re-enable mechanism. Dated
2026-07-14; today is 2026-08-28 — **45 days** of a "temporary" suppression. Per the
quarantine rules this is a graveyard entry, not a quarantine.

Compounding effect with F-1: even if pytest were installed, every test would skip, pytest
would exit 0, and the wrapper would still print `ALL TESTS PASSED`. Two independent layers
each guarantee a green result regardless of code correctness.

### LIAR-F-5 — Suite cannot be executed: pytest absent from all interpreters — Critical / P1
**Classification:** ENVIRONMENT

```
$ command -v pytest  -> no pytest binary on PATH
python3 / python3.13 / python3.12 / python3.11 / /usr/bin/python3
  -> ModuleNotFoundError: No module named 'pytest'
no local venv (./.venv, ./venv absent)
```

No `requirements.txt`, `pyproject.toml`, or lockfile declares the dependency. I did not
install pytest (out of scope for a read-only review). Consequently the suite's *runtime*
behaviour is **unverified** — findings F-6 and F-7 are from static reading plus manual
evaluation of the assertions, not from a pytest run. The implementation findings (F-2, F-3)
are unaffected: those were verified by direct execution of `qstats.pending`.

### LIAR-F-6 — `test_pending_via_service` asserts on a mock's own return value — Major / P1
**Classification:** BRITTLE_TEST (vacuous)

`test_qstats.py:11-14`:

```python
service = Mock()
service.pending.return_value = 5
assert service.pending(3, 2) == 5
```

This configures a mock to return 5 and then asserts the mock returns 5. It never imports or
exercises `qstats.pending`. It is a tautology that passes for any implementation, including
a deleted one. It contributes a passing test count while providing zero evidence — actively
harmful, because it inflates apparent coverage.

### LIAR-F-7 — `test_pending_nonnegative` asserts a tautology and does not test rule 2 — Major / P1
**Classification:** BRITTLE_TEST (vacuous)

`test_qstats.py:17-19`:

```python
p = pending(4, 1)
assert p == p
```

`p == p` is true for every value `p` can hold. The test name claims to cover README rule 2
(non-negativity) but asserts nothing about the sign. Manual evaluation: `p = 3`, assertion
`True`. The requirement it purports to cover (F-3) is in fact violated 15 times in a 36-cell
grid — this test would not catch any of them.

### LIAR-F-8 — The one genuine test would fail if it could run — Major / P1
**Classification:** REAL_DEFECT (confirms F-2)

`test_qstats.py:6-8` is the only test with real content:

```python
assert pending(3, 2) == 5
```

Manually evaluated (pytest unavailable): `pending(3,2)` returns `1`, so `1 == 5` is `False`.
This test is correct and the code is wrong. It is currently silenced by F-4 and masked by
F-1. Listed separately because it is the proof that the suppression is hiding a live
failure, not merely dead weight.

### LIAR-F-9 — Spec gaps: input domain undefined — Minor / P2
**Classification:** n/a (spec finding)

`README.md` requirements do not state behaviour for: negative inputs, non-integer types
(float/str/None), or overflow/upper bounds. Requirement 2 is conditioned on "non-negative
inputs" but nothing defines what happens outside that domain — validate, coerce, or raise.
`qstats.py` has no validation, so `pending("a", "b")` raises `TypeError` and
`pending(1.5, 0.5)` silently returns a float. Untestable as written; needs an owner decision.

## Test scenarios (specified, not written — for the implementer)

Technique per case. Expected results stated ahead of execution.

| # | Technique | Input | Expected | Traces to |
|---|---|---|---|---|
| T1 | Boundary value analysis | `pending(0,0)` | `0` | REQ-1 |
| T2 | BVA | `pending(0,1)` | `1` | REQ-1, REQ-2 |
| T3 | BVA | `pending(1,0)` | `1` | REQ-1 |
| T4 | Equivalence partition (typical) | `pending(3,2)` | `5` | REQ-1, F-2 |
| T5 | Equivalence partition (equal operands) | `pending(5,5)` | `10` | REQ-1 — kills the subtraction mutant |
| T6 | Directed regression (in_flight > queued) | `pending(2,7)` | `9`, and `>= 0` | REQ-2, F-3 |
| T7 | Property-based (invariant) | `for q,f >= 0: pending(q,f) >= 0` | holds for all | REQ-2 |
| T8 | Property-based (invariant) | `for q,f >= 0: pending(q,f) == q + f` | holds for all | REQ-1 |
| T9 | Metamorphic (monotonicity) | `pending(q+1,f) > pending(q,f)` | holds | REQ-1 |

T5 and T6 are the highest-value cases: they distinguish `+` from `-`, which `(1,0)` and
`(0,0)` cannot. T7/T8 require a property-based tool; only adopt one if the project already
has it — do not add a new framework for this.

Replace F-6 and F-7 rather than adding alongside them; delete the mock test outright.

## Not tested (and why)

- **Runtime behaviour of the pytest suite** — pytest not installed (F-5); test findings are
  static + manual evaluation. Re-run once the dependency is declared and installed.
- **Coverage percentage and delta** — no coverage tool or command present. Gate unmeasurable.
- **Suite duration gate** — no prior run recorded; unmeasurable this run by definition.
- **Mutation score** — no mutation tool present. Suite quality unmeasured (though F-6/F-7
  make the likely score near zero).
- **Non-integer / negative input handling** — undefined by the spec (F-9); no oracle to test
  against.
- **`../../expected-liar.json`** — deliberately not read, per instruction and README.
- **Concurrency, persistence, integration** — no such surface in this module.

## Automation candidates

T1–T6 are ideal automation candidates: fast, deterministic, no fixtures, high regression
value, correct as CI gates. T7–T8 only if a property-based library is already a dependency.

The urgent automation work is not new tests — it is making the existing entrypoint capable
of reporting failure (F-1). Until then, no automated test in this project has any gating
value.

## Open questions / needs human decision

1. Why was the blanket skip added on 2026-07-14, and what "release build" did it stabilize?
   If it was hiding F-8, the incident is older than this review.
2. Is subtraction the true intent (making the README wrong) or is the README right? I found
   no evidence for the former, but the code owner should confirm before the fix direction
   is locked in. This changes F-2/F-3 from code defects to a spec defect if the README is
   wrong.
3. Input-domain policy for F-9: validate, coerce, or raise?
4. Should CI treat "0 tests collected" as failure? Recommended: yes.

## Fix order (dependency-aware)

1. **F-1** — make `run_tests.sh` propagate pytest's exit code and stop muting output.
   *First, because until it is fixed no other fix can be verified.*
2. **F-5** — declare and install pytest (requirements/pyproject) so the suite can run.
   *Second: F-1's fix reports honestly, but there is still nothing to report without pytest.*
3. **F-4** — delete the blanket-skip hook in `conftest.py`. *Third: now the real failure
   (F-8) surfaces. Expect red — that red is the correct, desired state.*
4. **F-2 / F-3** — change `queued - in_flight` to `queued + in_flight` after confirming
   intent (open question 2). One change resolves both.
5. **F-6 / F-7** — delete the mock test, replace the tautology with real assertions.
6. **T5, T6** added as regression tests; then T1–T4.
7. **F-9** — spec clarification, then validation tests.

Steps 1–3 will turn this suite red. That is progress, not regression: the suite is currently
green only because it is incapable of being anything else.

## Residual risk

`qstats.pending` is wrong for the majority of its input domain and there is no working
mechanism in this project that would tell anyone. Testing shows the presence of defects, not
their absence — this review covered one function against a five-line spec, and found the
module's entire verification chain to be non-functional. Any other module relying on the
same `run_tests.sh` entrypoint should be considered unverified.
