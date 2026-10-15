# Verdict Template: Bug Report

Use when: a suspected defect needs to be reported clearly enough for an implementer to
reproduce, prioritize, and fix it.

## Template

```text
Title:

Failure Classification: REAL_DEFECT / STALE_EXPECTATION / BRITTLE_TEST / ENVIRONMENT / FLAKY
Classification Evidence:

Environment:
- Project:
- Build/branch/version:
- Device/browser/OS:
- User/account/data:
- Test environment:

Severity:
Priority:

Preconditions:

Steps to Reproduce:
1.
2.
3.

Expected Result:

Actual Result:

Reproducibility:
- Always / intermittent / once
- Reproduced count:

Impact:

Evidence:
- Screenshot/video/log/file/test output:

Suspected Area:

Regression Risk:

Notes:
```

## Quality Rules

- The title should describe the user-visible failure, not the suspected code cause.
- Steps must be numbered and reproducible from a clean starting point.
- Expected and actual results must be separate.
- Severity describes impact. Priority describes urgency/order of work.
- If evidence is incomplete, label the issue as a risk or `HYPOTHESIS:` instead of a
  confirmed bug.
- Include data, account, file, browser, branch, or environment details whenever they affect
  reproduction.
