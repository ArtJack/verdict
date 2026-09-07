---
name: verdict-verify-fix
description: Prove that a fix fixed the defect — re-run the guarding test at the previous commit and at HEAD, re-inject the defect in an isolated scratch copy, and let the harness record fix_verified from measurement, never from a claim. Use after you (the coding agent) fixed a finding and before you call it done.
---

# Verdict: verify a fix, don't claim it

The coding agent fixes; Verdict verifies. Absence of a failure is not evidence of a fix — a
test that never demonstrated the defect cannot demonstrate its absence. The verified kind is
the only kind that counts as evidence the finding was real.

**In Claude Code with the Verdict plugin, use the `verdict` agent (`/verdict:run` after the
fix lands).** This skill is the same procedure for agents that cannot run it.

## What the harness measures for you

Give the finding a **declared test**: `verification_test` in its file
(`<qa-root>/findings/<ID>.json`) set to a collected test id from `<qa-root>/test-ids.txt`
— the test that fails on the defect and passes on the fix. On the next
`verdict-facts --repo . --qa-root <root>`, the harness re-runs that test at the previous
run's commit (in a scratch worktree, the test file copied from HEAD, the old source first
on `PYTHONPATH`, bytecode swept) and at HEAD:

- fail → pass: the finding resolves `fix_verified: true`, outcome `confirmed (measured)`;
- still fails at HEAD: the resolution is **refused** — the finding stays open;
- pass at both, error, no runnable test: not verifiable, said so, nothing changes.

A prose value ("no test covers this") is refused: declare a collected id, or omit the
field and write in the evidence that no test guards this — which is a finding about the
suite, and often the first thing to fix.

## When you re-inject by hand

Only in a **scratch copy** of the tree, never the checkout. Three controls, all measured
because each one produced a false green once:

1. **The copy must run its own code.** An editable install's `.pth` names the original
   checkout; put the scratch source first (`PYTHONPATH=<scratch>/src`) and confirm:
   `python -c "import <pkg>; print(<pkg>.__file__)"` must print a path inside the scratch.
   (0 of 4 injected defects caught without this, 4 of 4 with it.)
2. **The copy must run the code it has now.** CPython validates bytecode by mtime in whole
   seconds plus size, so a same-size injection within a second re-runs the old bytecode.
   `PYTHONDONTWRITEBYTECODE=1`, delete `__pycache__` between injections. (4 of 5 caught
   with the cache in place, 5 of 5 swept.)
3. **Run the control in the failing direction:** put the original source back and re-run.
   If the injected failure persists on clean source, you are measuring the cache.

Then report: the test id, the result at each commit, the control's result. `fix_verified`
is the one judgment field that feeds the tester's track record, so it costs a
demonstration.

## What you may not do

Edit, weaken, skip or delete a test to make the suite green; mark your own fix verified
without the measurement; close a finding by not mentioning it.

Verdict reports and specifies; it never fixes — you did, and this is how the fix becomes
evidence rather than a claim.
