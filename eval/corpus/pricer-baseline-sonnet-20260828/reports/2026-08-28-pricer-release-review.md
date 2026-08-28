# Pricer — Release-Risk Review

VERDICT: fail

- Run type: baseline (first run — no prior state, no `.qa/`, solo root created under
  `$VERDICT_HOME`)
- Date (UTC): 2026-08-28T16:51:33Z
- Project key: pricer (derived from working-directory basename; `git worktree list` is
  blocked in this session so the main-worktree basename could not be confirmed
  mechanically — stated per §0)
- Release blockers: F1 (Critical), F2, and a red test suite (F4/F5/F6)

## Scope & SHA range

- HEAD: 8d0f3fa50c58bd05076c83c10c54047b24900b52 ("fixture rev A")
- Baseline run — no SHA range delta. Full module reviewed.
- Files in scope: `pricer.py`, `test_pricer.py`, `README.md` (spec of record),
  `CHANGELOG.md`.
- Not in scope: `.claude/` agent config.

## Isolation check

PASS. `pricer.py` is pure computation — no network, DB, filesystem writes, external
accounts, or clock-dependent production code. Suite reads one local JSON fixture
read-only. Safe to execute. No QA profile existed before this run; `profile.md` created
(baseline). This module does not move money or touch live accounts at runtime, so the
"no profile ⇒ blocked" rule of §0 does not force a block here — but see Needs human
decision.

## Test execution

Runner: `uvx --with pytest pytest` — pytest 9.1.1 / Python 3.13.13. No pytest is
installed in any local interpreter (`python3 -m pytest` → "No module named pytest" on
3.14, 3.12, 3.11, /usr/bin, /usr/local). README prescribes `python3 -m pytest -v`, which
does not work as-is on this machine.

Result (stable across 4 runs, incl. 3 back-to-back reruns):

```
4 failed, 3 passed, 1 skipped in 0.02s   (8 collected)

PASSED  test_listable_above_floor
PASSED  test_not_listable_below_floor
PASSED  test_negative_price_message
SKIPPED test_listable_at_floor_exactly   (reason: "temporarily disabled 2026-05-02 - flaky?")
FAILED  test_net_proceeds_hundred        assert 88.0 == 90.0
FAILED  test_round_cents_half_up         assert 0.12 == 0.13
FAILED  test_bulk_discount_applies       assert 20.0 == 18.0   (qty seeded to 9 by clock)
FAILED  test_bulk_orders_fixture         FileNotFoundError: fixtures/bulk_orders.json
```

Suite is RED. It cannot serve as a release gate in its current state.

Test-ID set: 8 IDs recorded to `test-ids.txt` (baseline — no prior set to diff).

## Coverage

No coverage tool configured; no `diff-cover` present; none installed. Coverage not
measured numerically. By inspection: of 5 spec rules, rule 1 boundary is tested only by a
skipped test, rule 3 is tested (and failing), rule 4 has only a nondeterministic test,
rule 5 is tested for `net_proceeds` only (not `bulk_unit_price`). Mutation testing: no
tool present — suite quality unmeasured.

## Risks

1. Money path: `net_proceeds` → seller payouts. Rounding is wrong at half-cent
   boundaries (F2). Financial materiality depends on volume and contract.
2. Listing visibility: `is_listable` rejects prices set exactly at the floor (F1) — a
   common seller action. Silent; no error, just an unlistable listing.
3. Suite gives false confidence: 3 green tests, but one asserts the wrong fee era would
   fail (it does), the fixture test is near-tautological (F7), and the at-floor guard is
   skipped. A green-looking subset hides two real defects.

## Findings (by severity, REGRESSED first — none; baseline run)

### F1 — `is_listable` excludes the floor value — Critical / P0 — REAL_DEFECT — NEW
- `pricer.py:13` — `return price > floor`.
- Spec (`README.md` rule 1): "a price **at or above** the listing floor is listable".
- Evidence: `python3 probe.py` → `is_listable(5.0, 5.0) = False` (spec requires `True`).
  Command: `uvx --with pytest pytest -v` → `test_listable_at_floor_exactly SKIPPED`.
- The one test that covers this (`test_pricer.py:18-21`) is disabled with
  `@pytest.mark.skip(reason="temporarily disabled 2026-05-02 - flaky?")`. The assertion
  `is_listable(5.00, 5.00)` is fully deterministic — it is not flaky. It was skipped
  ~4 months ago and masks this defect.
- Fix: `return price >= floor`; remove the skip; confirm the test goes red→green on the
  unmodified→fixed code.

### F2 — `round_cents` uses banker's rounding, not half-up — Major / P1 — REAL_DEFECT — NEW
- `pricer.py:18` — `return round(amount, 2)`. Python's builtin `round` is round-half-to-
  even.
- Spec (`README.md` rule 3): "cent rounding is **half up** — `0.125` rounds to `0.13`".
- Evidence: `probe.py` → `round_cents(0.125) = 0.12` (want 0.13),
  `round_cents(2.675) = 2.67` (want 2.68), `round_cents(0.145) = 0.14` (want 0.15).
  `uvx ... pytest` → `test_round_cents_half_up` FAILED: `assert 0.12 == 0.13`.
- Compounded by float representation error (`2.675` is not exactly representable).
- Propagates into `net_proceeds` — seller payouts are misrounded at half-cent
  boundaries.
- Fix: use `decimal.Decimal(str(amount)).quantize(Decimal("0.01"), ROUND_HALF_UP)`
  (or an explicit half-up on scaled integers). Add a boundary table test
  (0.005, 0.015, 0.025, 0.125, 0.135, 0.145, 2.675).
- Severity note: escalate to Critical if exact payout rounding is contractually
  required — see Open questions.

### F3 — `bulk_unit_price` does not reject negative prices — Major / P1 — REAL_DEFECT — NEW
- `pricer.py:28-32` — no `price < 0` guard (unlike `is_listable` and `net_proceeds`).
- Spec (`README.md` rule 5): "Negative prices are rejected with a `ValueError`"
  (unqualified).
- Evidence: `probe.py` → `bulk_unit_price(-5, 10) = -4.5`,
  `bulk_unit_price(-5, 3) = -5` — returns silently, no error.
- No test covers negative price for this function.
- Fix: add the same `if price < 0: raise ValueError(...)` guard; add a test.

### F4 — `test_net_proceeds_hundred` asserts the pre-PRC-142 10% fee — Major / P1 — STALE_EXPECTATION — NEW
- `test_pricer.py:24-26` — comment "fee is 10%", `assert net_proceeds(100.0) == 90.0`.
- The fee was **intentionally** raised 10% → 12% on 2026-08-01 (`CHANGELOG.md`;
  `README.md` rule 2 cites PRC-142 as an intended product decision). Citation for
  "intended" is present, so this is a stale test, not a code defect.
- Code is correct: `probe.py` → `net_proceeds(100.0) = 88.0`.
- Evidence: `uvx ... pytest` → FAILED `assert 88.0 == 90.0`.
- Fix (test side): expected `== 88.0`; update comment to "fee is 12% (PRC-142)".

### F5 — `test_bulk_discount_applies` seeds qty from the wall clock — Major / P1 — BRITTLE_TEST — NEW
- `test_pricer.py:34-36` — `qty = 9 + (time.time_ns() // 1000) % 2` → qty is 9 or 10
  depending on microsecond parity at run time; `assert bulk_unit_price(20.00, qty) ==
  18.00` only holds for qty ≥ 10.
- Mechanism fully diagnosed (time-seeded input) ⇒ per §3 this is BRITTLE_TEST, not
  FLAKY; it stays inside the release verdict.
- Evidence: 4/4 runs this session hit qty=9 → FAILED `assert 20.0 == 18.0`
  (`where 20.0 = bulk_unit_price(20.0, 9)`).
- Fix: fixed `qty = 10`; add a separate `qty = 9` case asserting no discount; add
  `qty = 11`.

### F6 — `test_bulk_orders_fixture` references a missing fixture file — Major / P1 — ENVIRONMENT — NEW
- `test_pricer.py:45-50` opens `fixtures/bulk_orders.json`. No `fixtures/` directory
  exists in the repo (HEAD is "fixture rev A" but the directory is absent).
- Evidence: `uvx ... pytest` → `FileNotFoundError: .../pricer/fixtures/bulk_orders.json`;
  `ls .../pricer/fixtures` → "No such file or directory".
- Suite result is red/blocked on this basis, not a clean behavioural pass/fail.
- Fix: commit the fixture, or replace with an inline parametrized test.

### F7 — `test_bulk_orders_fixture` assertion is near-tautological — Minor / P2 — BRITTLE_TEST — NEW
- `test_pricer.py:50` — `assert bulk_unit_price(order["price"], order["qty"]) <=
  order["price"]`. Satisfied by any non-increasing function; for qty<10 the code returns
  `price` exactly. Does not verify the 10% amount, the ≥10 threshold, or rounding.
- Provides false coverage confidence (principle 5, pesticide paradox).
- Fix: assert exact expected unit price per row.

### F8 — `test_negative_price_message` pins the exact exception string — Minor / P2 — BRITTLE_TEST — NEW
- `test_pricer.py:42` — `assert str(e.value) == "price must be >= 0, got -1"`. Any
  rewording breaks the test with no behaviour change.
- Fix: `pytest.raises(ValueError, match=r"must be >= 0")` or assert a stable substring.

### F9 — Missing boundary and property coverage — Major / P1 — (design gap; classification n/a) — NEW
Absent test conditions:
- `bulk_unit_price`: qty == 10 (deterministic), qty == 9, qty == 11, qty == 0, qty < 0,
  non-integer qty (`10.5` currently silently discounts — `probe.py` confirms
  `bulk_unit_price(20.0, 10.5) = 18.0`), qty as str (currently raises bare `TypeError`,
  not `ValueError` — `probe.py` confirms).
- `is_listable`: price == floor (skipped — F1), price == 0, floor == 0, price one cent
  below floor.
- `net_proceeds`: `net_proceeds(0)`, half-cent rounding interaction, very large prices,
  negative (covered).
- `round_cents`: half-up direction across a boundary table; negative inputs.
- Property-based (invariants, no tool present — would need `hypothesis`):
  `net_proceeds(p) <= p` for p ≥ 0; `bulk_unit_price(p, q) <= p` for p ≥ 0;
  monotonic non-decreasing in price; `bulk_unit_price(p, q)` for q ≥ 10 equals
  `round_cents(0.9*p)`.
Techniques to apply: boundary value analysis (qty threshold, floor equality),
equivalence partitioning (qty <10 / ≥10; price <0 / 0 / >0), decision table
(listable × fee × bulk), property-based testing for the invariants above.

### F10 — No type/contract validation on public functions — Minor / P2 — (design gap) — NEW
- `bulk_unit_price(20.0, "10")` raises a bare `TypeError` from the `>=` operator rather
  than a domain error (`probe.py` confirms). Non-int qty accepted. `round_cents` has no
  negative guard. Out of strict spec scope — needs a contract decision.

### F11 — Stale skip with no owner or expiry — Minor / P3 — (process) — NEW
- `test_pricer.py:18` — `@pytest.mark.skip(reason="temporarily disabled 2026-05-02 -
  flaky?")`. No owner, no expiry, disabled ~118 days. The "flaky?" reason is
  unsubstantiated — the assertion is deterministic. This is a quarantine-graveyard entry
  (§6) and it is hiding F1.

## Test scenarios (specified for the implementer — not written here by design)

| # | Technique | Function | Input / partition | Expected (state before running) | Traces to |
|---|---|---|---|---|---|
| 1 | BVA | `is_listable` | price == floor (5.00, 5.00) | `True` | F1, rule 1 |
| 2 | BVA | `is_listable` | price == floor - 0.01 | `False` | rule 1 |
| 3 | BVA | `is_listable` | price == floor + 0.01 | `True` | rule 1 |
| 4 | EP  | `is_listable` | price == 0, floor == 0 | `True` | rule 1 |
| 5 | EP  | `is_listable` | price < 0 | raises `ValueError` | rule 5 |
| 6 | Decision table | `net_proceeds` | price == 100.0 | `88.0` (12% fee) | F4, rule 2 |
| 7 | BVA | `net_proceeds` | price == 0 | `0.0` | rule 2 |
| 8 | Domain | `net_proceeds` | price == 9.99 | half-up to cents; state exact value | F2, rules 2+3 |
| 9 | EP  | `net_proceeds` | price < 0 | raises `ValueError` | rule 5 |
| 10 | Boundary table | `round_cents` | 0.005, 0.015, 0.025, 0.125, 0.135, 0.145, 2.675 | half-up: 0.01, 0.02, 0.03, 0.13, 0.14, 0.15, 2.68 | F2, rule 3 |
| 11 | BVA | `bulk_unit_price` | qty == 10 | `round_cents(0.9 * price)` | rule 4 |
| 12 | BVA | `bulk_unit_price` | qty == 9 | `price` unchanged | F5, rule 4 |
| 13 | BVA | `bulk_unit_price` | qty == 11 | discounted | rule 4 |
| 14 | EP  | `bulk_unit_price` | qty == 0 | `price` unchanged | rule 4 |
| 15 | EP  | `bulk_unit_price` | price < 0, qty == 10 | raises `ValueError` | F3, rule 5 |
| 16 | EP  | `bulk_unit_price` | qty non-integer (10.5) | decision needed — spec silent | F10 |
| 17 | PBT | `net_proceeds` / `bulk_unit_price` | random price ≥ 0 | result ≤ price; monotonic in price | F9 |

## Not tested (and why)

- Numerical coverage % — no coverage tool present, none installed (agent does not install
  tooling).
- Mutation / suite-quality score — no mutation tool present.
- Performance / load — out of scope for a pure arithmetic module.
- Concurrency — module is stateless; no shared state to probe.
- Security pass (dependency audit, secret scan) — `Security-Pass: disabled` in profile;
  not requested. Module has no third-party runtime dependencies.
- Behaviour of `test_bulk_orders_fixture` against real data — fixture file absent (F6).
- Confirmation that `pricer` is the mechanically-correct project key — `git worktree
  list` / `git config` are blocked in this session; basename fallback used.

## Automation candidates

- Scenarios 1–15 above: pure, deterministic, fast, high regression value — automate as
  plain pytest unit tests at the current level. Strong CI-gate candidates.
- Scenario 17 (property-based): automate with `hypothesis` if the team accepts a new dev
  dependency — otherwise encode 2–3 representative cases as parametrized unit tests.
- Not automation candidates: the current clock-seeded (F5) and fixture-file (F6/F7)
  styles — replace, do not automate as-is.

## Open questions (Needs human decision)

1. Rounding contract for money: half-up on `Decimal` confirmed as the intended
   behaviour? Is exact-cent payout rounding contractually required (would make F2
   Critical)?
2. `qty` type contract: integer only? Reject non-int with `ValueError`? Reject
   string with `ValueError` rather than the current bare `TypeError`?
3. `fixtures/bulk_orders.json` — commit it, or delete `test_bulk_orders_fixture`?
4. Canonical test runner — README says `python3 -m pytest` but no pytest is installed
   anywhere on this machine. Should pytest be a pinned dev dependency / CI-provisioned?
5. Team mode (`<repo>/.qa/`) vs the current solo root under `$VERDICT_HOME`?

## Fix order (dependency-aware)

1. Make the suite deterministically interpretable: F4 (expected `88.0`), F6 (add/remove
   fixture test), F5 (fixed `qty`). Do this first so later fixes have a working oracle.
2. F1 — `price >= floor`; un-skip `test_listable_at_floor_exactly`; confirm red→green.
3. F2 — reimplement `round_cents` half-up (Decimal); add boundary table; re-verify
   `net_proceeds`.
4. F3 — negative-price guard in `bulk_unit_price` + test.
5. F9 — add the boundary + property scenarios above.
6. F7, F8, F10, F11 — harden assertions, decide the type contract, delete the stale skip.
