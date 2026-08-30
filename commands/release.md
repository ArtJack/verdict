---
description: "Run the release QA gate before calling feature or project work done."
argument-hint: "[release, feature, or merge candidate]"
---

Use the `verdict` agent to run the release QA gate for:

`$ARGUMENTS`

Verdict must use the bundled release gate standard:

`${CLAUDE_PLUGIN_ROOT}/standards/release-gate.md`

Required output:

- `VERDICT:` pass / pass with risks / blocked / fail — an open Blocker forces fail
- Scope reviewed (and SHA range if state exists)
- Release blockers
- Known risks and what was NOT tested
- Regression status (changed areas, adjacent flows, integrations, data/state)
- Findings by severity, REGRESSED first
- Automation candidates
- Recommended implementer tasks, ordered
- Evidence: commands run and exact output excerpts

The caller owns the ship decision. Verdict provides the quality evidence and the verdict.
