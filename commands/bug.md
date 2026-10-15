---
description: "Turn a bug report, symptom, log, or user complaint into a structured QA bug report."
argument-hint: "[symptom, log excerpt, failing test, or complaint]"
---

Use the `verdict` agent to process this bug or suspected defect:

`$ARGUMENTS`

Verdict must use the bundled template and standard:

- `${CLAUDE_PLUGIN_ROOT}/templates/bug-report.md`
- `${CLAUDE_PLUGIN_ROOT}/standards/severity-priority.md`

Required output:

- failure classification per §3 (REAL_DEFECT / STALE_EXPECTATION / BRITTLE_TEST /
  ENVIRONMENT / FLAKY) with the evidence stated before the classification
- structured bug report
- severity with reason · priority with reason
- confidence per §9 (`proven` / `probable` / `hypothesis`) — stated now, because it is
  scored later against what the finding turns out to do
- reproduction gaps (what is still needed for a clean repro)
- release impact
- regression checks the fix must not break
- recommended implementer tasks

If evidence is incomplete, file it as `HYPOTHESIS:` — not as a confirmed bug.
