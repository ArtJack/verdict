# Verdict Standard: Release Gate Checklist

Use when: about to call a feature done, merge work, ship, or hand work over as complete.

## When the Gate Applies

Ask Verdict for a release QA review before "done" when the change affects user-visible
behavior, data, integrations, auth, permissions, payments, imports, exports, notifications,
reporting, or critical project workflows.

## Required Checks

```text
Release Gate:
- [ ] Acceptance criteria are testable and covered
- [ ] Critical happy path is covered
- [ ] Negative and validation paths are considered
- [ ] Boundary values are considered where inputs/ranges exist
- [ ] Permission/security implications are considered
- [ ] Data persistence/import/export behavior is considered
- [ ] Integration behavior is considered
- [ ] Error handling and recovery are considered
- [ ] Regression impact is reviewed
- [ ] Existing automated checks were run or consciously skipped with reason
- [ ] No Blocker/P0 or Critical/P0 issue remains open
- [ ] Known risks are documented
- [ ] Automation candidates are identified
- [ ] QA verdict is recorded
```

## Output

Verdict returns exactly one of:

- `pass`
- `pass with risks`
- `blocked`
- `fail`

The caller owns the final ship decision. Verdict provides quality evidence and release
risk — an open Blocker forces `fail`, and a `pass` always names what was not tested.
