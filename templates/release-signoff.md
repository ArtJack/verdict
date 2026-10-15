# Verdict Template: Release QA Sign-Off

Use when: a clear quality decision is needed before calling work done or ready to ship.

## Template

```text
Release/Feature:
Project:
Build/branch/version:
Date:
QA Owner:

QA Verdict:
- pass / pass with risks / blocked / fail

Scope Reviewed:
-

Acceptance Criteria Status:
- [ ] All critical acceptance criteria covered
- [ ] Ambiguous criteria documented
- [ ] Out-of-scope behavior documented

Smoke Status:
- [ ] Critical happy path passed
- [ ] Startup/load checks passed
- [ ] No blocker console/log errors

Regression Status:
- [ ] Changed areas checked
- [ ] Adjacent flows checked
- [ ] Critical integrations checked
- [ ] Data/state behavior checked

Defect Status:
- Blockers:
- Critical:
- Major:
- Minor:

Automation Status:
- Existing automated checks run:
- New automation candidates:
- Manual-only checks:

Known Risks:
-

Release Blockers:
-

Recommended Implementer Tasks:
-

Evidence:
- Commands:
- Files:
- Screenshots/logs:
- Test reports:

Final Sign-Off:
- signed off / signed off with risks / not signed off
```

## Gate Rules

- `fail`: one or more Blocker defects or failed critical flows. An open Blocker forces
  `fail`.
- `blocked`: QA cannot make a decision because required environment, data, build, or
  requirements are missing.
- `pass with risks`: no release blocker, but there are documented gaps, untested areas, or
  non-blocking defects.
- `pass`: critical acceptance criteria, smoke, and relevant regression checks passed with no
  known blocker — and the not-tested list is stated.
