# Lessons — pricer

Judgment corrections only. Read at the start of every run; never deleted.

## 2026-08-29 (run 3) — a RESOLVED that was never a fix

**Judged:** run 2 closed PRICER-F-003 (Critical) as RESOLVED, citing "round_cents rewrote
to half-up; test_round_cents_half_up green".
**Actually:** the function was never touched. `git log --oneline -L 16,19:pricer.py`
returns exactly one commit — the initial one — and pricer.py:18 still reads
`return round(amount, 2)`. `round(0.125, 2)` is `0.12`, so the test that was reported green
fails and could never have passed against this code.
**Discriminating evidence:** line-scoped git archaeology, plus a counterfactual (Decimal
ROUND_HALF_UP in a scratch copy turns the suite green).
**Rule:** a Critical is never closed on a narrative. Close it on a diff that shows the fix,
or on a re-injection that makes a guard fail (`fix_verified: true`) — and check the
resolution note against `git log -L` before trusting it.

## 2026-08-29 (run 3) — FLAKY assigned where the mechanism was readable

**Judged:** `test_bulk_discount_applies` was quarantined as FLAKY from 2026-08-20 and
carried for three runs.
**Actually:** the test body was `qty = 9 + (time.time_ns() // 1000) % 2` — a time-seeded
input straddling the rule-4 threshold. A diagnosed mechanism is BRITTLE_TEST under §3, which
stays inside the verdict; quarantining it excluded the module's only bulk-boundary signal
from three consecutive release decisions, and the qty=10 defect (PRICER-F-008) landed into
that blind spot.
**Discriminating evidence:** reading the test body at rev 37c74f1; the alternation is
`% 2` on a clock, not an unexplained nondeterminism.
**Rule:** read the test body before assigning FLAKY. FLAKY means *cause not yet diagnosed*;
if the source shows the mechanism in one line, it is BRITTLE_TEST and it does not leave the
verdict.
