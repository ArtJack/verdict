# QA report — rates · run 1 (baseline)

*root-cause investigation (baseline)*

**VERDICT: fail**

## Scope

- Range: `53377c8230115a1f388a6d213e841ee6c7f20873`
- Branch: `main` · measured 2026-09-03T16:11:07Z
- Isolation check: **pass** — No profile existed; created one this run. Verified by inspection that nothing under test can touch a live system: grep -rnE "import (os|sys|socket|requests|urllib|http|sqlite3|subprocess|boto|psycopg)|open\(|getenv|environ|connect\(" --include="*.py" . -> no matches. The only imports in the repo are the local modules themselves (rates.py:3-4, invoice.py:3, report.py:3, test_rates.py:1-3). Suite is pure arithmetic and string formatting; safe to execute.

Root-cause investigation of the single failing test in the `rates` freight-quoting repo at 53377c8 (main), plus the class question for the defect found. Baseline run: no prior state, no prior profile — both created this run. Whole repo is 6 Python files / 128 lines, so the §8.2 risk ranking is one line: the surface is small enough to read completely, and it was.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | fail | 1 | 0.11s | 1 failed, 5 passed in 0.01s |

Tests: passed 5, failed 1, collected 6
Test-id ledger: 6 ids · +6 / −0 (set-diff, not summary arithmetic)
Diff coverage: **unmeasurable** — no coverage_suite_cmd in the profile — set one that runs the suite under coverage.py (e.g. `.venv/bin/python -m coverage run -m pytest`) to measure which changed lines any test executed

## Risks

Every open finding is a money defect. The failing test is the visible 1-cent-per-quote under-charge; the invisible half is that the same conversion is written out three times and the other two copies are green only because their test data has no fractional cents. A fix aimed at the failing test alone leaves invoices and monthly revenue reports wrong, which is the more expensive of the two because nothing will fail when it happens.

## Findings — REGRESSED first (5 open of 5 tracked)

### RATES-F-001 — NEW — Critical/P0 — REAL_DEFECT

money.to_cents truncates instead of rounding half up, so quotes landing on a half cent under-charge by 1c
- python3 -m pytest -q -> '1 failed, 5 passed in 0.01s'; test_rates.py:13 AssertionError: assert 792 == 793
- money.py:6 `return int(amount * 100)` — int() truncates toward zero; the docstring at money.py:5 and the module docstring at money.py:1 both claim spec rule 1 (half up)
- README.md rule 1: '$5.425 is 543 cents, never 542'
- Measured: 7*0.775 -> float 5.425; (7*0.775)*100 -> exactly 542.5 (Decimal(542.5), not 542.4999...); int(542.5)=542, so the loss is the rounding mode, not float representation
- Counterfactual A (scratchpad/cf, isolated copy, PYTHONDONTWRITEBYTECODE=1, __pycache__ swept, module identity confirmed as .../scratchpad/cf/money.py): replaced money.py:6 with Decimal(str(amount))*100 quantized ROUND_HALF_UP -> '6 passed in 0.00s'
- Instrument control: original money.py:6 restored in the same scratch copy -> '1 failed, 5 passed' again
- Counterfactual C: naive round(amount*100) also yields 792 (round(542.5)=542, banker's rounding) -> a plain round() is NOT a valid fix
- Root cause: rates.quote (rates.py:10) computes freight = 7 * 0.775 = 5.425, then rates.py:11 calls money.to_cents(5.425); money.py:6 evaluates 5.425*100 -> exactly 542.5 and applies int(), which truncates to 542; + to_cents(2.50)=250 gives 792 where README rule 1 requires 543+250=793 → 28d5ea1 'feat: freight quoting, invoices, and monthly reporting' — git log -S 'int(amount * 100)' -- money.py names that commit as the only one that ever touched the expression; the same commit's message claims 'rounded to the nearest cent per the spec', so the defect was present from the first commit and mis-described in its own message
- Class: {"pattern": "grep -rn 'int(' and '\\* *100' --include='*.py' . ; grep -rn 'round|Decimal|floor|ROUND|quantize' --include='*.py' . -> no rounding primitive exists anywhere in the repo", "sites": ["mone

Chain, each link cited. SYMPTOM (counterfactual): `python3 -m pytest -q` -> `1 failed, 5 passed`; test_rates.py:13 `assert 792 == 793`. MECHANISM (counterfactual): rates.py:10 computes 7*0.775 -> 5.425; rates.py:11 passes it to money.to_cents; money.py:6 evaluates 5.425*100 -> exactly 542.5 (verified with Decimal: the float is exactly 542.5, not 542.4999...) and int() truncates it to 542; +250 handling = 792 vs the 793 README rule 1 requires. The loss is the rounding MODE, not float representation — that distinction matters, because it rules out 'floating point' as the answer and rules IN 'no rounding rule was ever implemented'. ORIGIN (archaeology): `git log -S 'int(amount * 100)' -- money.py` returns exactly one commit, 28d5ea1, the initial feature commit; the expression has never been edited since. CLASS (differential + reading): the shape exists at three sites and no rounding primitive exists anywhere in the repo — `grep -rn 'round|Decimal|floor|ROUND|quantize' --include='*.py' .` returns nothing. Proof strength: counterfactual, run in an isolated scratch copy with bytecode caching disabled and an instrument control (restoring the original made it fail again).

### RATES-F-002 — NEW — Critical/P1

invoice.line_total and report.monthly_total re-implement the same truncating conversion, so invoices and revenue reports silently under-report money
- invoice.py:8 `return int(unit_price * quantity * 100)` — does not call money.to_cents; invoice.py:3 imports only format_cents
- report.py:9 `return int(total * 100)` — same; report.py:3 imports only format_cents
- Direct calls against the repo as-is: invoice.line_total(1.475, 3) = 442 (spec: 443); report.monthly_total([10.005]) = 1000 (spec: 1001); report.monthly_total([1.115, 2.00]) = 311 (spec: 312)
- README.md rule 1: 'Everything customer-facing — quotes, invoices, reports — uses the same rule.'
- These two sites are green today: test_rates.py:29-31 uses 12.50x2 and test_rates.py:34-35 uses 10.00+20.00, both exact cents

This is the class link of RATES-F-001 filed as its own finding, because it has its own fix and its own blast radius. invoice.py and report.py import format_cents from money but re-implement the dollars->cents half themselves, so they are not fixed by fixing money.to_cents. Demonstrated wrong today against the unmodified repo: invoice.line_total(1.475, 3) = 442 vs 443; report.monthly_total([10.005]) = 1000 vs 1001. Filed Critical because it is customer-facing money (README rule 1 names invoices and reports explicitly), P1 rather than P0 because no test currently fails on it — which is precisely the reason it is dangerous.

### RATES-F-003 — NEW — Major/P1

Invoice and report tests use only whole-cent data, so the suite cannot detect the rounding rule being violated at those two sites
- test_rates.py:29-31 invoice.render([('Pallet', 12.50, 2)]) -> exact $25.00
- test_rates.py:34-35 report.render([10.00, 20.00]) -> exact $30.00
- Both pass while the underlying functions return the wrong value for half-cent input (see RATES-F-002)
- Boundary-value analysis on the rounding rule: the only boundary that matters (a result whose third decimal is exactly 5) was untested for quotes until 53377c8 and is still untested for invoices and reports

Pesticide-paradox finding (§8.5). Before 53377c8 the suite was 100% green and had never once exercised the rule the README puts first, because every test input produced a whole number of cents. The same blind spot still covers invoice and report. The missing technique is boundary-value analysis on the rounding boundary: a result whose third decimal is exactly 5, at each conversion site.

### RATES-F-004 — NEW — Minor/P2

rates.quote does its money arithmetic in float, contradicting spec rule 4 (integer cents throughout)
- rates.py:10 `freight = weight_kg * entry['rate']` — float x float; zones.py:4-6 stores rates as floats
- README.md rule 4: 'All monetary values move through the codebase as integer cents.'
- Measured bound: across weights 1..5000 for all three zones, every true half-cent product lands on or above .5 in float (4500 exactly on, 500 above, 0 below), so a half-up fix in to_cents is sufficient for the CURRENT rate table — but the guarantee is a property of these three rates, not of the design

Reported as a latent design risk, not a live defect, and the distinction is measured rather than assumed: I scanned weights 1..5000 across all three zone rates for products that are true half-cents, and none of them lose the boundary downward in float (4500 land exactly on .5, 500 land just above, 0 below). So a half-up fix in to_cents is sufficient for today's table. Add a rate with more decimal places and that guarantee is gone, and the failure mode would be a 1-cent error that appears for some weights and not others.

### RATES-F-005 — NEW — Minor/P3

format_cents renders negative amounts incorrectly ($-6.57 for -543 cents)
- money.py:10 `f"${cents // 100}.{cents % 100:02d}"` — Python floor division and modulo on negatives
- money.format_cents(-543) -> '$-6.57' (expected '-$5.43')
- README.md is silent on credits/refunds, so this is also a spec gap — see Needs human decision

Out of the failing test's path, found while reading money.py. Python's // and % floor toward negative infinity, so a credit of -543 cents renders as '$-6.57' rather than '-$5.43'. Whether negative amounts can occur is a spec question the README does not answer, which is why the policy decision is listed for the owner rather than filed as a higher severity.

## Release blockers

- RATES-F-001 — quotes landing on a half cent under-charge by 1 cent (money.py:6); customer-facing money is wrong against README rule 1
- RATES-F-002 — the same truncation at invoice.py:8 and report.py:9 makes invoices and revenue reports wrong for the same inputs, silently

## Verified intact

- {'invariant': 'The memoization added in 10d4607 is value-neutral: it changes no quote', 'evidence': "Counterfactual B — memoization removed in the scratch copy (zones.py lookup returning ZONES[zone] directly), money.py untouched -> identical outcome '1 failed, 5 passed'. The perf commit is not the trigger and not the cause."}
- {'invariant': 'The zone cache hands out copies; a caller mutating a returned entry cannot poison the table', 'evidence': "zones.py:18,21,22 wrap in dict(). Probe: a = lookup('west'); a['rate'] = 999.0; lookup('west')['rate'] -> 0.775; ZONES['west']['rate'] -> 0.775; quote(4,'west') -> 560."}
- {'invariant': 'Unknown zones still raise, and a failed lookup does not pollute the cache', 'evidence': "zones.py:19-20 checks membership before writing the cache. Probe: lookup('moon') -> KeyError('unknown zone: moon'); _CACHE afterwards contains only ['west']. test_rates.py::test_unknown_zone_is_an_error passes."}
- {'invariant': 'Whole-cent quoting arithmetic is correct', 'evidence': 'test_quote_west_whole_weight (4x0.775+2.50 = 560) and test_quote_east (2x1.125+3.00 = 525) pass; the handling-fee addition at rates.py:11 is right.'}

## Not tested

- The 'central' zone (zones.py:5) has no test at all — no quote case exercises rate 0.910
- Line coverage and changed-files coverage: no coverage tool is configured in this project; coverage is unmeasured, not estimated
- Suite quality: no mutation-testing tool is installed, so the strength of the 6 existing assertions is unmeasured
- invoice.render / report.render formatting beyond the two happy-path strings — no zero, negative, empty-list, or multi-line cases
- Large-value and precision-loss behaviour above float's exact-integer range
- Concurrency around the zone cache — the project is single-threaded as written and there is no harness

## Fix order

1. money.py:6 — replace int(amount*100) with an explicit half-up conversion (Decimal(str(amount)) quantized ROUND_HALF_UP, or floor(x*100 + 0.5) for non-negative amounts). NOT round(): round(542.5) is 542 under banker's rounding, proven by counterfactual C. This alone turns the suite green, which is exactly why it must not be the last step. 2. invoice.py:8 and report.py:9 — delete the local int(...*100) and call money.to_cents, so there is one conversion in the codebase. 3. Add half-cent boundary tests for invoice.line_total and report.monthly_total (RATES-F-003) before or alongside step 2, so step 2 is verified rather than assumed. 4. Add a 'central' zone quote case. 5. Decide and document the negative-amount policy, then fix money.py:10 (RATES-F-005). 6. Consider moving rates.quote to integer/Decimal arithmetic per spec rule 4 (RATES-F-004) — lowest priority, currently latent.

## Next run focus

- Re-run after the rounding fix and confirm all three conversion sites (money.py:6, invoice.py:8, report.py:9) go through one half-up helper — verify by re-injecting truncation at each site in a scratch copy and watching a guard fail
- Confirm new boundary tests exist for invoice.line_total and report.monthly_total with half-cent data (RATES-F-003)
- Add a 'central' zone quote case
- Decide the negative-amount policy (RATES-F-005) and record it in README.md

## Notes

Trigger / cause / latent condition, stated separately because they have different owners. TRIGGER: commit 53377c8 added the first non-whole-cent test case (test_rates.py:11-13). Cost of 'fixing' the trigger — reverting or relaxing the test — is that the defect stays and becomes invisible again. CAUSE: money.py:6 uses int() where the spec requires half-up rounding; introduced in 28d5ea1, whose own commit message claims the opposite. Cost if left: 1 cent lost on every quote whose freight lands on a half cent. LATENT CONDITION: the conversion is duplicated at invoice.py:8 and report.py:9, and no test anywhere used fractional-cent data, so a fully green suite proved nothing about the one rule the README puts first. Cost if left: the same defect survives the fix at two sites and re-enters at the next copy. The 'perf: memoize' commit (10d4607) is a decoy — counterfactual B removed the memoization entirely and the failure was unchanged. Diagnosis stops here per §3.5: naming the fix location is owed, writing the fix is not mine.

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
