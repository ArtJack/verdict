# Verdict Template: Regression Checklist

Use when: a change may affect existing behavior and the caller needs release confidence.

## Template

```text
Regression Area:
Change Under Test:
Build/branch/version:
Tester:
Date:

Smoke Checks:
- [ ] App/service starts successfully
- [ ] Critical page/API loads
- [ ] User can complete the primary happy path
- [ ] No obvious console/log errors

Changed Area Checks:
- [ ]
- [ ]
- [ ]

Adjacent Flow Checks:
- [ ]
- [ ]
- [ ]

Data/State Checks:
- [ ]
- [ ]

Permissions/Security Checks:
- [ ]
- [ ]

Integration Checks:
- [ ]
- [ ]

Error Handling Checks:
- [ ]
- [ ]

Known Risks:
-

Blocked/Not Tested:
-

Regression Verdict:
- pass / pass with risks / blocked / fail
```

## Usage Rules

- Start with the changed area, then test adjacent flows that share data, APIs, components,
  permissions, or background jobs.
- Include one smoke path even when the change is small.
- Mark items as blocked or not tested instead of silently omitting them.
- If a check fails, create a bug report or release blocker.
