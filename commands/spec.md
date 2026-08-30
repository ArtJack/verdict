---
description: "Shift-left review: judge a spec, issue, or PRD for testability — before code exists."
argument-hint: "<path to spec/issue/PRD, or pasted requirement text>"
---

Use the `verdict` agent to review this specification for testability:

`$ARGUMENTS`

This is §2 activities 1–4: the cheapest defects to fix are the ones caught before code
exists. No code is required, and none is judged. Required flow:

1. **Inventory the requirements.** Number every testable claim found (R-1, R-2 …). A
   sentence that cannot fail a test is not a requirement — that is itself a finding.
2. **Findings**, each with §10 severity and a verbatim quote of the offending line(s):
   - **Untestable / unmeasurable** — "fast", "reliable", "user-friendly", "handles all
     edge cases" without a number or an observable behavior.
   - **Contradictions** — requirements that cannot both hold; quote *both* lines in the
     evidence.
   - **Undefined boundaries** — behavior at exactly-the-limit, rounding direction,
     inclusive vs exclusive ranges, empty/zero cases, timezone and calendar-vs-business
     days. Name the §4 boundary each ambiguity hides.
   - **Silent gaps** — failure paths, permission cases, partial/concurrent operations the
     spec never mentions.
   - **Conflicts with recorded history** — a CHANGELOG, ADR, or state entry that
     contradicts the spec; cite it.
3. **Acceptance criteria.** Rewrite the core requirements as Given/When/Then, precise
   enough that the criterion IS the test (§5 ATDD) — implementer-ready.
4. Close with the §13 handoff and a verdict **on the spec**: `pass` means "implementable
   and testable as written"; anything less says exactly what change would earn it.

Spec findings are real findings: write them to `state.json` with normal IDs (their
evidence cites `SPEC.md:line`, `failure_classification: null`) — they age, resolve, and
regress like any other finding as the spec is revised. Report and INDEX row per §7, as
always.
