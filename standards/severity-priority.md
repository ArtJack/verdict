# Verdict Standard: Severity and Priority

Use when: classifying bugs, release blockers, and QA risks.

## Severity

Severity describes user or system impact.

- `Blocker`: prevents release or prevents a critical user flow from working. No reasonable
  workaround exists.
- `Critical`: causes data loss, security/privacy exposure, payment or financial error,
  broken authentication/authorization, severe calculation/reporting error, or outage-level
  failure.
- `Major`: important feature is broken or unreliable, but a workaround exists or the impact
  is limited to a non-critical path.
- `Minor`: small functional defect, confusing behavior, layout issue, or edge case with low
  user/business impact.
- `Trivial`: typo, cosmetic issue, or low-impact polish problem.

## Priority

Priority describes urgency and work ordering.

- `P0`: fix immediately; blocks release or active production use.
- `P1`: fix before release or before the affected workflow is considered done.
- `P2`: schedule soon; important but not release blocking.
- `P3`: backlog; low urgency.

## Classification Rules

- Severity and priority are related but not the same.
- A high-severity issue can be lower priority if it is impossible in production or outside
  current scope.
- A low-severity issue can be higher priority if it affects a high-visibility release or
  stakeholder demo.
- Release blockers are usually `Blocker/P0`, `Critical/P0`, or `Critical/P1`.
- If unsure, state the uncertainty and what evidence would change the classification.

## Bug Report Requirement

Every confirmed bug includes both fields, each with a short reason:

```text
Severity:  (reason)
Priority:  (reason)
```
