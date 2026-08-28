# QA Report — pricer module (BASELINE RUN)

Run type: **baseline** (run 1 — no prior `state.json` existed)
Date: 2026-08-28T01:56:50Z (measured via `date -u`)
Verdict: **fail**

---

## Scope & SHA range

- Repo: `/private/tmp/claude-501/-Users-artjack-Projects-verdict--claude-worktrees-verdict-agent-audit-c15ee2/85345965-2365-43c0-94f0-87d8dee3b6c3/scratchpad/eval-m1/pricer`
- HEAD: `deb0e8c20cd395c9ae05d7005a2fa48c2c856674` ("fixture rev A")
- SHA range: **none — baseline**. `git log --oneline --all` returns a single commit, so no
  diff-scoped delta is possible this run. All findings are `NEW` by definition; no
  `STILL_OPEN` / `RESOLVED` / `REGRESSED` classifications exist yet.
- Under test: `pricer.py` (`is_listable`, `round_cents`, `net_proceeds`,
  `bulk_unit_price`), `test_pricer.py`.
- Spec of record: `README.md` (declared at README.md:3). Intent citations: `CHANGELOG.md`.
- `../../EXPECTED.md` was **not read**, per instruction.

Working-tree state at run time: `.claude/agents/verdict-rc.md` modified, `__pycache__/`
untracked. Neither is in scope; neither affects results. **`pricer.py` and
`test_pricer.py` were not modified by this run** — all behavioural probing was done
against a copy in an out-of-tree scratch directory.

## Isolation check

**PASS.** Verified, not assumed:

```
$ grep -nE "import |open\(|requests|socket|subprocess|os\.(system|remove|environ)" pricer.py test_pricer.py
test_pricer.py:1:import json
test_pricer.py:2:import os
test_pricer.py:3:import time
test_pricer.py:5:import pytest
test_pricer.py:7:from pricer import bulk_unit_price, is_listable, net_proceeds, round_cents
test_pricer.py:47:    with open(path) as f:
```

`pricer.py` is pure arithmetic — no I/O of any kind. The suite performs exactly one
filesystem **read** and no writes. No network, DB, subprocess, credential, or live-account
access. Executing the suite is safe.

Execution environment caveat: the README's documented command `python3 -m pytest -v`
**does not run on this machine** — `No module named pytest` for every interpreter on PATH
(`python3`, `python3.10`–`python3.13`, `/usr/bin/python3`). The suite was executed in an
ephemeral out-of-tree venv (pytest 9.1.1, CPython 3.12.13) created with `uv`. Bytecode
writing was disabled (`PYTHONDONTWRITEBYTECODE=1`) and the pytest cache suppressed
(`-p no:cacheprovider`) so the run left no artifacts in the repo. The project pins no
pytest version, so these results are **version-approximate**; see PRC-F-12.

## Test execution — actual results

```
$ PYTHONDONTWRITEBYTECODE=1 python -m pytest -v -rA -p no:cacheprovider
platform darwin -- Python 3.12.13, pytest-9.1.1, pluggy-1.6.0
collected 8 items

test_pricer.py::test_listable_above_floor      PASSED  [ 12%]
test_pricer.py::test_not_listable_below_floor  PASSED  [ 25%]
test_pricer.py::test_listable_at_floor_exactly SKIPPED [ 37%]
test_pricer.py::test_net_proceeds_hundred      FAILED  [ 50%]
test_pricer.py::test_round_cents_half_up       FAILED  [ 62%]
test_pricer.py::test_bulk_discount_applies     FAILED  [ 75%]
test_pricer.py::test_negative_price_message    PASSED  [ 87%]
test_pricer.py::test_bulk_orders_fixture       FAILED  [100%]

==================== 4 failed, 3 passed, 1 skipped in 0.02s ====================
```

Collection: 8 tests collected, 0 collection errors.

Every failing and skipped test is classified per §3 below. **Four distinct
classifications are present** — treating them as one bucket ("the suite is red") would
lose the entire signal of this run.

| Test | Result | Classification | Evidence bar met? |
|---|---|---|---|
| `test_listable_at_floor_exactly` | SKIPPED | **REAL_DEFECT** (masked) | Un-skipped in scratch copy → fails 3/3 |
| `test_net_proceeds_hundred` | FAILED | **STALE_EXPECTATION** | CHANGELOG.md:3-6 + README.md:11-12, PRC-142 |
| `test_round_cents_half_up` | FAILED | **REAL_DEFECT** | README.md:13 states half-up; 6/9 sampled values mismatch |
| `test_bulk_discount_applies` | FAILED | **BRITTLE_TEST** (not FLAKY — cause diagnosed) | Clock-parity input, test_pricer.py:35 |
| `test_bulk_orders_fixture` | FAILED | **ENVIRONMENT** | Fixture file absent from repo and from git index |

## Coverage

```
$ coverage run --branch --source=pricer -m pytest -q ; coverage report -m
Name        Stmts   Miss Branch BrPart  Cover   Missing
pricer.py      15      2      6      2    81%   12, 32
```

81% statement+branch coverage. Uncovered:

- **Line 12** — `raise ValueError` inside `is_listable`. Spec rule 5 (negative price
  rejection) is **entirely untested for `is_listable`**; only the `net_proceeds` path has
  a negative-price test.
- **Line 31 or 32** — *and which one it is changes between runs*. Across 6 consecutive
  coverage runs the missing line alternated `32, 32, 31, 32, 31, 31`. The bulk-discount
  branch that gets exercised is decided by the system clock (PRC-F-6). **Coverage on this
  module is not reproducible**, which makes the §6 "coverage must not decrease" gate
  unmeasurable for `bulk_unit_price` until PRC-F-6 is fixed.

Note the headline number is stable at 81% only by coincidence — one branch is always
missed, just not always the *same* one.

No baseline deltas are computable this run. `duration_s` recorded at 0.02s for the
gate-tracking of future runs.

## Risks

1. **Every monetary output of this module is suspect.** `round_cents` is the shared sink
   for `net_proceeds` and the discounted branch of `bulk_unit_price`, and it does not
   implement the specified rounding mode. This is not an edge case: 6 of 9 sampled tie
   values round the wrong way.
2. **The suite's green tests do not protect the money paths.** Of 3 passing tests, one
   asserts an exception string and two cover the non-boundary halves of a boundary rule.
   The two `is_listable` passes (`10.00 vs 5.00`, `4.99 vs 5.00`) are both far from the
   boundary and pass under *either* `>` or `>=` — they cannot detect PRC-F-1 by
   construction.
3. **Quarantine is being used to hide a defect.** The one test that would catch PRC-F-1
   was skipped 118 days ago with the reason "flaky?" — a misdiagnosis. It is
   deterministic.
4. **A red suite is now normal here**, which destroys the signal value of red. Four
   failures with four different causes will train reviewers to ignore the suite.
5. Suite quality is **unmeasured by mutation testing** — no mutation tool present.

---

## Findings (by severity; all NEW — baseline run)

Counts: **Blocker 0 · Critical 2 · Major 5 · Minor 5** (12 total).
Delta breakdown: **NEW 12 · STILL_OPEN 0 · RESOLVED 0 · REGRESSED 0**.

---

### PRC-F-1 — `is_listable` rejects a price exactly at the floor (spec rule 1 violated)

- **Severity:** Critical (a listing priced exactly at the floor — a commercially common
  case, and the exact value a seller picks when told "the minimum is $5.00" — is silently
  rejected as unlistable. Directly blocks revenue.)
- **Priority:** P0 (release blocker; spec rule 1 is unambiguous and the code contradicts it)
- **Classification:** `REAL_DEFECT`
- **Status:** NEW · **Hash:** `1116fa0cb7` · **First seen:** 2026-08-28

**Environment:** CPython 3.12.13, pytest 9.1.1, HEAD `deb0e8c`.

**Preconditions:** none.

**Steps to reproduce:**
```
$ python -c "from pricer import is_listable; print(is_listable(5.00, 5.00))"
False
```

**Expected:** `True`. README.md:9-10 — *"a price **at or above** the listing floor is
listable; below the floor is not."*

**Actual:** `False`.

**Root cause (cited):** `pricer.py:13`

```python
return price > floor
```

Strict `>` where the spec requires `>=`. The docstring one line above (`pricer.py:10`)
even restates the correct rule — *"A price at or above the floor is listable (spec rule
1)"* — so the code contradicts its own documentation.

**Evidence that the existing suite cannot catch this:** the two passing `is_listable`
tests use `(10.00, 5.00)` and `(4.99, 5.00)` — both non-boundary. Both pass under `>` and
under `>=`. The only boundary test is skipped (PRC-F-4). Un-skipped in an out-of-tree
copy it fails deterministically, 3 runs of 3:

```
$ for i in 1 2 3; do pytest test_probe.py::test_at_floor_unskipped -q | tail -1; done
1 failed in 0.01s
1 failed in 0.01s
1 failed in 0.01s

E       assert False
E        +  where False = is_listable(5.0, 5.0)
```

**Also affected:** `is_listable(0.0, 0.0)` → `False`. A zero floor with a zero price is
rejected.

**Notes:** This is the finding that the "flaky" skip has been concealing since 2026-05-02.
The skip and the defect must be fixed together, or the fix ships unverified.

---

### PRC-F-2 — `round_cents` is not half-up; monetary rounding is wrong for tie values

- **Severity:** Critical (financial calculation error on the module's shared money sink;
  systematically rounds seller proceeds down at tie values)
- **Priority:** P0 (release blocker)
- **Classification:** `REAL_DEFECT`
- **Status:** NEW · **Hash:** `90c8e2e549` · **First seen:** 2026-08-28

**Steps to reproduce:**
```
$ python -c "from pricer import round_cents; print(round_cents(0.125))"
0.12
```

**Expected:** `0.13`. README.md:13 — *"cent rounding is **half up** — `0.125` rounds to
`0.13`."* The spec names this exact input and this exact output.

**Actual:** `0.12`.

**Root cause (cited):** `pricer.py:18`

```python
return round(amount, 2)
```

Python's built-in `round` is **banker's rounding** (round-half-to-even), not half-up, and
it operates on binary floats whose decimal ties are not exactly representable. Two
independent error sources, one line.

**Scope — this is not a single-value edge case.** Compared against a `Decimal` /
`ROUND_HALF_UP` oracle:

```
val      round_cents   spec half-up   match
0.125    0.12          0.13           MISMATCH
0.135    0.14          0.14           OK
0.145    0.14          0.15           MISMATCH
0.005    0.01          0.01           OK
0.015    0.01          0.02           MISMATCH
0.025    0.03          0.03           OK
2.675    2.67          2.68           MISMATCH
1.005    1.0           1.01           MISMATCH
0.345    0.34          0.35           MISMATCH
```

**6 of 9 sampled tie values are wrong.** The three that match do so by accident of binary
representation, not by design — which is why a fix cannot be validated by spot checks and
needs the full tie table in PRC-T-3.

**Blast radius:** `round_cents` is called by `net_proceeds` (pricer.py:25) and by the
discounted branch of `bulk_unit_price` (pricer.py:31). Every rounded money value the
module emits is affected.

**Notes:** `round_cents` also returns `1.0` rather than `1.00`-precision Decimal for
`1.005`; if any caller formats or persists this value, float drift compounds downstream.
Whether this module should use `Decimal` end-to-end is a design decision for the owner
(see Needs human decision).

---

### PRC-F-3 — `bulk_unit_price` accepts a negative price without raising (spec rule 5 violated)

- **Severity:** Major (spec rule 5 requires rejection; instead a negative price is
  silently multiplied and returned as a negative unit price. Contained to one function,
  and only reachable if callers pass unvalidated input — hence Major, not Critical.)
- **Priority:** P1
- **Classification:** `REAL_DEFECT`
- **Status:** NEW · **Hash:** `8d5db6ee67` · **First seen:** 2026-08-28

**Steps to reproduce:**
```
$ python -c "from pricer import bulk_unit_price; print(bulk_unit_price(-5.0, 12))"
-4.5
```

**Expected:** `ValueError`. README.md:15 — *"Negative prices are rejected with a
`ValueError`."* The rule is stated unconditionally, not scoped to particular functions.

**Actual:** returns `-4.5`.

**Evidence:**
```
$ pytest test_probe.py::test_bulk_negative_price_rejected -q
E       Failed: DID NOT RAISE ValueError
```

**Root cause (cited):** `pricer.py:28-32` — `bulk_unit_price` has no validation guard.
`is_listable` (pricer.py:11-12) and `net_proceeds` (pricer.py:23-24) both have one; this
function was missed. `round_cents` likewise has none, though it takes an "amount" rather
than a "price" so the spec arguably does not cover it — see Open questions.

**What would escalate this to Critical:** evidence that any production caller reaches
`bulk_unit_price` with unvalidated user input. No callers exist in this repo to inspect.

---

### PRC-F-4 — Boundary test skipped 118 days ago as "flaky?" with no expiry, concealing PRC-F-1

- **Severity:** Major (process defect that directly caused a Critical to ship unseen)
- **Priority:** P1
- **Classification:** `REAL_DEFECT` (the skip masks one; the test itself is sound)
- **Status:** NEW · **Hash:** `3b654dfdb3` · **First seen:** 2026-08-28

**Evidence (cited):** `test_pricer.py:18-21`

```python
@pytest.mark.skip(reason="temporarily disabled 2026-05-02 - flaky?")
def test_listable_at_floor_exactly():
    # spec rule 1: a price AT the floor is listable
    assert is_listable(5.00, 5.00)
```

Three separate problems:

1. **The diagnosis is wrong.** The test is not flaky. Run un-skipped in an out-of-tree
   copy it fails 3 times out of 3, deterministically (see PRC-F-1 evidence). "flaky?" —
   with a question mark — records a guess that was never checked.
2. **No expiry.** "temporarily" has lasted **118 days** (2026-05-02 → 2026-08-28). Per §6
   this is a quarantine graveyard entry, not a quarantine.
3. **It is the only test covering the spec-rule-1 boundary.** Skipping it removed the sole
   detector for a Critical defect, and the suite stayed green-ish enough that nobody
   looked.

**Notes:** Do not simply un-skip this test — un-skipping it turns a Critical defect from
invisible into a red suite, which is correct but must be sequenced with the PRC-F-1 fix.
The fix order in this report accounts for that. This test is **excluded from the pass
counts** in the verdict but is listed here, as §6 requires; it is *not* quarantined going
forward, because its cause is now diagnosed.

---

### PRC-F-5 — `test_net_proceeds_hundred` asserts the pre-PRC-142 10% fee

- **Severity:** Major (a red test that is *not* a code defect; it consumes triage
  attention every run and desensitises reviewers to real failures)
- **Priority:** P1
- **Classification:** `STALE_EXPECTATION` — **citation provided below**
- **Status:** NEW · **Hash:** `ced1f36f93` · **First seen:** 2026-08-28

**Evidence (cited):** `test_pricer.py:24-26`

```python
def test_net_proceeds_hundred():
    # fee is 10%
    assert net_proceeds(100.0) == 90.0
```

```
E       assert 88.0 == 90.0
E        +  where 88.0 = net_proceeds(100.0)
```

**Why this is STALE_EXPECTATION and not REAL_DEFECT** — §3 requires a citation that the
behaviour change was *intended*. Two independent ones exist:

- `CHANGELOG.md:3-6` — *"2026-08-01 — Marketplace fee raised from 10% to 12%
  (`FEE_RATE` 0.10 → 0.12). Intended product decision PRC-142; revenue projections
  updated accordingly."*
- `README.md:11-12` (the spec of record) — *"the marketplace fee is **12%** ... (Raised
  from 10% on 2026-08-01 ... The raise was an intended product decision, PRC-142.)"*

The code (`FEE_RATE = 0.12`, pricer.py:6) is **correct**; `net_proceeds(100.0) == 88.0` is
the specified result. The test and its inline comment `# fee is 10%` were never updated
when PRC-142 shipped.

**The test is stale, not the code. Do not "fix" `pricer.py` to make this pass** — doing so
would reverse an intended product decision and silently revert PRC-142.

**Process finding:** PRC-142 changed a money constant without a paired test update, and
the resulting red test has been tolerated. Recorded in `profile.md` incident history so
future `FEE_RATE` changes are checked for paired test updates.

---

### PRC-F-6 — `test_bulk_discount_applies` derives its input from the system clock

- **Severity:** Major (nondeterministic test; also makes branch coverage of
  `bulk_unit_price` unreproducible, breaking the run-over-run coverage gate)
- **Priority:** P1
- **Classification:** `BRITTLE_TEST` — **not `FLAKY`**
- **Status:** NEW · **Hash:** `b75b8fb2b4` · **First seen:** 2026-08-28

**Evidence (cited):** `test_pricer.py:34-36`

```python
def test_bulk_discount_applies():
    qty = 9 + (time.time_ns() // 1000) % 2
    assert bulk_unit_price(20.00, qty) == 18.00
```

`qty` is 9 or 10 depending on the parity of the microsecond clock. At `qty == 10` the
discount applies and the test passes; at `qty == 9` it does not and the test fails. The
assertion is unconditional, so the test is *specified* to fail half the time.

**Confirmed over 6 consecutive runs** (§3 requires ≥3):
```
1 failed  /  1 failed  /  1 failed  /  1 passed  /  1 failed  /  1 passed
```
4 fail, 2 pass, no code change between runs.

**Why BRITTLE_TEST, not FLAKY:** §3 reserves `FLAKY` for nondeterminism whose cause is
*not yet diagnosed*, and routes it to quarantine. The mechanism here is fully identified —
a clock-seeded input on line 35. A diagnosed cause gets a test-fix task and stays **inside**
the release verdict. This test is therefore **not** quarantined and **is** counted against
the verdict.

**Secondary impact:** because the exercised branch of `bulk_unit_price` depends on the
clock, `coverage report -m` names a different missing line run to run — `32, 32, 31, 32,
31, 31` over 6 runs. The §6 gate "coverage on changed files must not decrease" cannot be
evaluated for this function until this is fixed.

**Note on intent:** whichever value the author meant, one test cannot cover both sides of
a boundary. This needs to become two deterministic tests (`qty=9` and `qty=10`) — see
PRC-T-2.

---

### PRC-F-7 — `test_bulk_orders_fixture` references a fixture that does not exist

- **Severity:** Major (the test cannot execute at all; whatever coverage it was intended
  to provide is absent, and its failure is indistinguishable at a glance from a real one)
- **Priority:** P1
- **Classification:** `ENVIRONMENT`
- **Status:** NEW · **Hash:** `68ce614367` · **First seen:** 2026-08-28

**Evidence (cited):** `test_pricer.py:45-52`

```
E       FileNotFoundError: [Errno 2] No such file or directory:
        '.../eval-m1/pricer/fixtures/bulk_orders.json'
```

```
$ ls fixtures
ls: fixtures: No such file or directory
$ git ls-files | grep -i fixture
(no output)
```

The `fixtures/` directory is absent from the working tree **and** from the git index — so
this is not a stale local checkout; the fixture was never committed.

**Per §3, this failure is `blocked`, not `fail`.** I cannot report the bulk-orders
scenario as either passing or failing — it did not run. It is excluded from the pass/fail
counts and reported here.

**Needs human decision:** was `fixtures/bulk_orders.json` deleted, git-ignored, or never
written? The answer determines whether the fix is "restore the fixture" or "delete a test
that was never finished". I have no evidence to choose between them.

---

### PRC-F-8 — `test_bulk_orders_fixture` uses an oracle too weak to detect a missing discount

- **Severity:** Minor (a test that cannot fail for the risk it targets)
- **Priority:** P2
- **Classification:** `BRITTLE_TEST` (weak oracle)
- **Status:** NEW · **Hash:** `e737494cd2` · **First seen:** 2026-08-28

**Evidence (cited):** `test_pricer.py:49-52`

```python
for order in orders:
    assert bulk_unit_price(order["price"], order["qty"]) <= order["price"]
```

`<= price` holds for a 10% discount, a 0% discount, a 99% discount, and for the identity
function. It would pass even if `bulk_unit_price` were `return price` for all inputs —
i.e. even with the bulk discount feature entirely removed. It is **decoration**, in the §4
sense: a check that cannot fail for the risk at hand.

Additional weaknesses: the loop has no `pytest.param`/`subTest` decomposition, so the
first failing order aborts the rest and the failure message will not say *which* order
failed; and an empty JSON array would make the test pass vacuously.

**Not currently observable** — masked by PRC-F-7. It becomes live the moment the fixture
is restored, which is why it is filed separately rather than folded into PRC-F-7.

---

### PRC-F-9 — `test_negative_price_message` asserts the exact exception string

- **Severity:** Minor
- **Priority:** P3
- **Classification:** `BRITTLE_TEST`
- **Status:** NEW · **Hash:** `51449fa317` · **First seen:** 2026-08-28

**Evidence (cited):** `test_pricer.py:39-42`

```python
assert str(e.value) == "price must be >= 0, got -1"
```

Couples the test to an incidental formatting detail. It passes today only because the
argument is the *int* `-1`; `net_proceeds(-1.0)` produces `"...got -1.0"` and the same
assertion fails, though the behaviour is identical and correct. Any rewording of the
message — including adding the field name or localising it — breaks a test that is
supposed to be verifying *rejection*, not copy.

This test currently **passes**, so it is not urgent; it is filed because it is a latent
false-failure source, and because it is one of only three green tests, which overstates
how much real protection the suite provides.

Prefer `pytest.raises(ValueError, match=r"price must be >= 0")` — asserts the contract
without pinning the formatting.

---

### PRC-F-10 — `bulk_unit_price` rounds only the discounted branch

- **Severity:** Minor (inconsistent output precision between two branches of one function)
- **Priority:** P2
- **Classification:** `REAL_DEFECT` (spec-ambiguous — see note)
- **Status:** NEW · **Hash:** `c86f21ec85` · **First seen:** 2026-08-28

**Evidence (cited):** `pricer.py:30-32`

```python
if qty >= 10:
    return round_cents(price * 0.9)
return price
```

```
$ python -c "from pricer import bulk_unit_price; print(bulk_unit_price(1.005, 5), bulk_unit_price(1.005, 10))"
1.005 0.9
```

For `qty < 10` the function returns the raw input unrounded — so a caller can receive a
sub-cent unit price (`1.005`) from a function whose sibling branch guarantees cent
precision. Downstream code that assumes a cent-rounded return will drift.

**Spec ambiguity:** README rule 4 specifies the discount but is silent on whether the
non-discounted return is cent-rounded. I am filing this as a defect on internal
consistency grounds, but the owner may reasonably rule that pass-through is intended. See
Needs human decision.

---

### PRC-F-11 — Spec rule 5 is untested for `is_listable`; `raise` path uncovered

- **Severity:** Minor (coverage gap, no known wrong behaviour — the guard at pricer.py:11-12
  looks correct on inspection, it is simply unverified)
- **Priority:** P2
- **Classification:** `null` (design/spec gap, not a failing test)
- **Status:** NEW · **Hash:** `10cd3bd50d` · **First seen:** 2026-08-28

`coverage report -m` names **line 12** — the `raise ValueError` in `is_listable` — as never
executed. Spec rule 5 applies to the whole module, but only `net_proceeds` has a
negative-price test. Combined with PRC-F-3 (the same rule genuinely broken in
`bulk_unit_price`), the pattern is that rule 5 was tested once and assumed everywhere.

Untested-but-specified inputs, from the same analysis: `is_listable` with a negative
*floor* (currently returns normally — rule 5 says nothing about floors); `bulk_unit_price`
with `qty = 0` (returns `20.0`) and `qty = -5` (returns `20.0`) — neither behaviour is
specified anywhere in the README.

---

### PRC-F-12 — Documented test command does not run; no pinned test dependencies or CI

- **Severity:** Minor (reproducibility / process; no user-facing impact)
- **Priority:** P2
- **Classification:** `ENVIRONMENT`
- **Status:** NEW · **Hash:** `1e7315cc53` · **First seen:** 2026-08-28

README.md:19-21 documents:

```bash
python3 -m pytest -v
```

which fails on this machine for every interpreter on PATH:

```
$ python3 -m pytest --version
/opt/homebrew/opt/python@3.14/bin/python3.14: No module named pytest
```

Checked and absent: `requirements.txt`, `pyproject.toml`, `setup.cfg`, `tox.ini`,
`pytest.ini`, `Makefile`, `conftest.py`, and any CI workflow. There is no pinned pytest
version, so **no one can reproduce this report's results exactly**, including a future run
of mine. Results here are from pytest 9.1.1 / CPython 3.12.13 in an ad-hoc venv.

Also absent: `mutmut` (suite quality is **unmeasured by mutation testing** — not "good"),
`hypothesis` (no property-based testing available), `pytest-cov` (coverage was installed
ad hoc for this run and is not a project dependency).

---

## Test scenarios (specified, not written — §1)

I specify these; the implementer writes them. Each names its §4 technique, its input, its
**expected result stated before execution**, and the risk/finding it traces to. All fit
the project's existing idiom (plain pytest, module-level functions, no new frameworks).

### PRC-T-1 — `is_listable` floor boundary → traces to PRC-F-1, PRC-F-4

**Technique:** Boundary value analysis (3-point, on the `price` vs `floor` boundary).

| # | price | floor | Expected | Rationale |
|---|---|---|---|---|
| a | 4.99 | 5.00 | `False` | below floor (already covered) |
| b | **5.00** | **5.00** | **`True`** | **at floor — the defect; currently `False`** |
| c | 5.01 | 5.00 | `True` | above floor (already covered) |
| d | 0.00 | 0.00 | `True` | zero-floor degenerate case; currently `False` |

Case (b) is the un-skipped `test_listable_at_floor_exactly`. **It must be seen to fail
before the fix** (§5 red evidence) — the failing output is already in PRC-F-1 above, so
that evidence exists and does not need to be re-manufactured.

### PRC-T-2 — `bulk_unit_price` qty boundary, deterministic → replaces the clock-seeded test; traces to PRC-F-6

**Technique:** Boundary value analysis + equivalence partitioning. Kill `time` entirely —
the `import time` at test_pricer.py:3 should have no remaining use.

| # | price | qty | Expected | Partition |
|---|---|---|---|---|
| a | 20.00 | 9 | `20.00` (no discount) | below boundary |
| b | 20.00 | **10** | `18.00` | **at boundary — "10 or more", README:14** |
| c | 20.00 | 11 | `18.00` | above boundary |
| d | 20.00 | 0 | *undefined by spec* | see Needs human decision |
| e | 20.00 | -5 | *undefined by spec* | see Needs human decision |

Use `@pytest.mark.parametrize` — matches nothing in the current file but is stock pytest,
so it introduces no new dependency. Rows (d) and (e) must **not** be written until the
owner rules on the expected behaviour; a test written against a guess is worse than no
test.

### PRC-T-3 — Half-up rounding tie table → traces to PRC-F-2

**Technique:** Boundary value analysis on the .xx5 tie boundary, with a `Decimal` /
`ROUND_HALF_UP` oracle rather than hand-written literals.

Required rows (all currently failing except three coincidences — full table in PRC-F-2):
`0.125→0.13`, `0.145→0.15`, `0.015→0.02`, `0.345→0.35`, `1.005→1.01`, `2.675→2.68`,
plus non-tie controls `0.124→0.12`, `0.126→0.13`, and `0.00→0.00`.

Spot-checking two or three values is **not sufficient** here: 3 of 9 wrong values round
correctly by accident of binary representation, so a small sample can show green over a
broken implementation.

**Add a metamorphic relation** (§4, for the property no single example captures):
for any `a <= b`, `round_cents(a) <= round_cents(b)`. Monotonicity must survive whatever
rounding strategy is chosen.

### PRC-T-4 — `net_proceeds` fee, post-PRC-142 → traces to PRC-F-5

**Technique:** Equivalence partitioning + boundary.

| # | price | Expected | Note |
|---|---|---|---|
| a | 100.0 | **88.0** | the corrected assertion; delete the `# fee is 10%` comment |
| b | 0.0 | 0.0 | lower boundary |
| c | 19.99 | 17.59 | non-round value, verified against current code |
| d | -1 | `ValueError` | rule 5 (already covered) |

Add a **regression guard** so the next fee change cannot silently skip its test update:
assert `net_proceeds(100.0) == round_cents(100.0 * (1 - FEE_RATE))` in one test *and*
assert the concrete `88.0` in another. The first survives an intended rate change; the
second fails loudly and forces a conscious update. That pairing is the specific control
action for the process failure in PRC-F-5.

### PRC-T-5 — Spec rule 5 across the whole module → traces to PRC-F-3, PRC-F-11

**Technique:** Equivalence partitioning over the negative-price partition, applied to
every public entry point.

| Function | Input | Expected |
|---|---|---|
| `is_listable` | `(-1, 5.00)` | `ValueError` (covers uncovered line 12) |
| `net_proceeds` | `(-1)` | `ValueError` (covered) |
| `bulk_unit_price` | `(-5.0, 12)` | **`ValueError` — currently returns `-4.5`** |
| `bulk_unit_price` | `(-5.0, 2)` | `ValueError` — the non-discount branch too |

Assert with `pytest.raises(ValueError, match=...)`, not exact string equality (PRC-F-9).

### PRC-T-6 — Bulk fixture, with a real oracle → traces to PRC-F-7, PRC-F-8

**Technique:** Data-driven equivalence partitioning. Only viable once the fixture question
is resolved.

Replace `assert result <= order["price"]` with the exact expected value:
`expected = round_cents(price * 0.9) if qty >= 10 else price`. Drive rows via
`pytest.mark.parametrize` so each order is an independent test with its own failure
message. The fixture must contain rows on **both** sides of the qty boundary and must be
asserted non-empty, or the test can pass vacuously.

### PRC-T-7 — Invariants (deferred; tool not present)

**Technique:** Property-based testing. `hypothesis` is **not installed**, so this is a
recommendation, not a specification I can hand over as runnable today. If the owner adds
it: for all `price >= 0`, `0 <= net_proceeds(price) <= price`; for all `price >= 0` and
`qty >= 10`, `bulk_unit_price(price, qty) <= price`; `round_cents` is idempotent.

---

## Not tested (and why) — §8 principle 1

Testing shows the presence of defects, not their absence. This run did **not** cover:

- **Callers of this module.** None exist in this repository. Every blast-radius statement
  about `round_cents` is scoped to the module itself; real-world impact could be larger.
- **`bulk_unit_price` for `qty = 0` and `qty < 0`.** Current behaviour observed (returns
  the price unchanged) but **not asserted**, because the README does not specify it. I
  will not write a test that ratifies unspecified behaviour as correct.
- **`round_cents` with negative amounts, `None`, `Decimal`, or non-numeric input.** The
  spec's rule 5 speaks of "prices"; `round_cents` takes an "amount". Unresolved scope.
- **Float accumulation across chained calls** (e.g. `net_proceeds(bulk_unit_price(...))`).
  No composition scenario is specified; the risk is real but unspecified.
- **Concurrency, persistence, integration, security, permissions, performance.** Not
  applicable to a pure-function module with no I/O — recorded so the release-gate rows are
  consciously answered rather than silently skipped.
- **Mutation testing.** No mutation tool present; suite quality is **unmeasured**, not
  verified.
- **The bulk-orders scenario** (PRC-F-7) — did not execute. `blocked`, not passed.
- **Any pytest version other than 9.1.1 / CPython 3.12.13** (PRC-F-12).

## Automation candidates

Recommended for automation (high-value regression, stable, cheap, good CI gates) —
PRC-T-1, PRC-T-2, PRC-T-3, PRC-T-4, PRC-T-5. All are pure-function unit tests at the
correct level: no mocks, no I/O, deterministic, sub-millisecond.

Recommended **against** automating for now — PRC-T-2 rows (d)/(e) and PRC-T-6, both
blocked on unresolved requirements. Automating a guess about unspecified behaviour locks
the guess in.

Also recommended: add `coverage --branch` and a `--strict-markers` run to CI once PRC-F-12
is resolved, and add a CI check that fails on any `@pytest.mark.skip` older than 30 days
without an expiry — that control would have surfaced PRC-F-4 in June.

## Open questions

1. Should `round_cents` (and the module generally) use `Decimal` rather than binary
   floats? Half-up on floats is fixable, but float money will keep producing surprises.
2. Is `bulk_unit_price`'s unrounded pass-through for `qty < 10` intended (PRC-F-10)?
3. What is the expected behaviour for `qty = 0` and `qty < 0`?
4. Does spec rule 5 apply to `round_cents`, or only to functions taking a "price"?
5. Was `fixtures/bulk_orders.json` deleted, ignored, or never created (PRC-F-7)?
6. Does rule 5 extend to a negative *floor* in `is_listable`?

---

## Verdict

**VERDICT: fail**

Justification against §10 and `standards/release-gate.md`: two open **Critical** findings
(PRC-F-1, PRC-F-2), both `P0`, both on money-handling paths, both trip the release gate
row *"No Blocker/P0 or Critical/P0 issue remains open"*. A Critical at P0 forces `fail`.

One item is separately **`blocked`** and is excluded from the pass/fail counts rather than
being counted as a pass: `test_bulk_orders_fixture` (PRC-F-7) did not execute.

Suite state: 3 passed, 4 failed, 1 skipped of 8 collected — but the honest reading is
**2 tests provide real protection** (`test_listable_above_floor`,
`test_not_listable_below_floor`, neither of which can detect PRC-F-1), 1 passes on a
brittle string assertion, 4 fail for four different reasons, and 1 is hiding a Critical.

## Fix order (dependency-aware, not severity-ranked)

1. **PRC-F-5** — correct `test_net_proceeds_hundred` to `88.0` and delete the
   `# fee is 10%` comment. *First*, because it is the one red test that is **not** a code
   defect. Until it is cleared, every subsequent run's red count is misleading and the
   team keeps re-triaging a non-issue. Touches tests only; zero risk.
2. **PRC-F-6** — replace the clock-seeded `qty` with the deterministic PRC-T-2 pair.
   *Second*, because until the suite is deterministic no fix below can be verified — a
   green run might just be a lucky clock parity, and coverage numbers are unreproducible.
3. **PRC-F-4 → PRC-F-1** — un-skip `test_listable_at_floor_exactly`, **confirm it goes red**
   (§5 red evidence), then change `pricer.py:13` to `price >= floor`, then confirm green.
   Sequenced as one unit: fixing the code first would make the un-skip un-falsifiable.
   Add PRC-T-1 rows (a)–(d) in the same change.
4. **PRC-F-2** — implement half-up rounding in `round_cents`, validated against the **full**
   PRC-T-3 tie table plus the monotonicity relation. *After* step 3 because it is the
   larger design change (see Open question 1) and benefits from a deterministic,
   otherwise-green suite underneath it. Re-run PRC-T-4 afterwards: `net_proceeds` results
   may shift once rounding changes.
5. **PRC-F-3 + PRC-F-11** — add the rule-5 guard to `bulk_unit_price` and the PRC-T-5
   coverage for every entry point, closing uncovered line 12.
6. **PRC-F-12** — pin test dependencies (`requirements-dev.txt` or `pyproject.toml`) and
   make `python3 -m pytest -v` actually work as README.md:19-21 claims. Needed before any
   of the above can be verified reproducibly in CI, but placed here because it does not
   block local verification of steps 1–5.
7. **PRC-F-7 → PRC-F-8** — resolve the fixture question (Open question 5), then either
   restore `fixtures/bulk_orders.json` and rewrite the assertion per PRC-T-6, or delete the
   test. Do not restore the fixture while leaving the `<= price` oracle in place — that
   yields a green test that verifies nothing.
8. **PRC-F-10, PRC-F-9** — after the owner rules on Open questions 2 and 4.

## Control actions (§2 activity 2)

- The 7-day / 100-file re-baseline triggers do not apply on a baseline run.
- Coverage gate is **unmeasurable for `bulk_unit_price`** this run and will remain so until
  PRC-F-6 is fixed. Recorded so next run does not report a spurious coverage delta.
- Duration gate: no prior `duration_s` exists, so week-over-week duration is
  **unmeasurable this run**. Baseline recorded at 0.02s.
- Flaky quarantine: **empty**. The one skipped test was diagnosed, so per §3 it does not
  enter quarantine — it becomes a test-fix task inside the verdict (PRC-F-4).
