---
name: verdict-spec-review
description: Judge a specification, issue or PRD for testability before any code exists — inventory the requirements, find the untestable, contradictory, unbounded and silent ones with a verbatim quote each, and rewrite the core as Given/When/Then acceptance criteria. Use when a spec is about to be implemented.
---

# Verdict: spec review, before code

The cheapest defects to fix are the ones caught before code exists. No code is required and
none is judged.

**In Claude Code with the Verdict plugin, use `/verdict:spec <path>`.** This skill is the
same procedure for agents that cannot run it.

## Procedure

1. **Inventory the requirements.** Number every testable claim (R-1, R-2 …). A sentence
   that cannot fail a test is not a requirement — that is itself a finding.
2. **File findings**, each with a severity and a verbatim quote of the offending line:
   - **Untestable / unmeasurable** — "fast", "reliable", "user-friendly", "handles all edge
     cases" without a number or an observable behaviour.
   - **Contradictions** — requirements that cannot both hold; quote both lines.
   - **Undefined boundaries** — behaviour exactly at the limit, rounding direction,
     inclusive vs exclusive ranges, empty and zero cases, time zones, calendar vs business
     days. Name the boundary each ambiguity hides.
   - **Silent gaps** — failure paths, permission cases, partial or concurrent operations
     the spec never mentions.
   - **Conflicts with recorded history** — a changelog, ADR or earlier decision that
     contradicts the spec; cite it.
3. **Write acceptance criteria.** Rewrite the core requirements as Given/When/Then, precise
   enough that the criterion *is* the test — implementer-ready.
4. **Park the questions only a person can settle** (which reading of an ambiguity is the
   spec?) as `questions` in the judgment rather than deciding them yourself; the
   maintainer answers with `verdict-answer`, and the next run reads the answer.
5. **Verdict on the spec:** `pass` means implementable and testable as written; anything
   less says exactly what change would earn it.

Spec findings are real findings: file them through the harness like any other
(`verdict-facts` → `<qa-root>/findings/<ID>.json`, evidence citing `SPEC.md:line`,
`failure_classification: null` → `verdict-finalize`), so they age, resolve and regress as
the spec is revised.

Verdict reports and specifies; it never fixes. Route the fix to the implementer, then
verify it (`verdict-verify-fix`).
