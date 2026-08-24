---
description: "Create or run a regression checklist for a change, release, bug fix, or area."
argument-hint: "[change, fix, or area needing regression confidence]"
---

Use the `verdict` agent to prepare regression coverage for:

`$ARGUMENTS`

Verdict must use the bundled template and match the project's own idiom:

- `${CLAUDE_PLUGIN_ROOT}/templates/regression-checklist.md`
- The project profile in the QA root (§0) — its rules override defaults.

Required output:

- changed area checks
- adjacent flow checks (shared data, APIs, components, permissions, background jobs)
- data/state checks
- permission/security checks
- integration checks
- error handling checks
- blocked/not-tested areas — listed, never silently omitted
- `VERDICT:` line
