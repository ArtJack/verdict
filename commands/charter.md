---
description: "Open a timeboxed exploratory-testing charter with a risk focus."
argument-hint: "[area or risk to explore] [timebox, default 45m]"
---

Use the `verdict` agent to run an exploratory-testing charter for:

`$ARGUMENTS`

Verdict must use the bundled template and the project profile:

- `${CLAUDE_PLUGIN_ROOT}/templates/exploratory-charter.md`
- The QA root's `profile.md` — its isolation rules govern every probe (§0 in full force).

Required flow:

1. **Charter before exploring**: mission, timebox, risk focus — seeded from the profile's
   risk clusters and incident history (§8 principle 4: defects cluster), personas/data,
   areas. A charter without a named risk is a stroll, not a mission.
2. **Explore within §0**: every probe must be non-mutating; anything uncertain is treated
   as mutating and returned as a risk instead of run.
3. **Capture observations as evidence while exploring** — commands and outputs recorded
   in the moment, never reconstructed afterwards (§9).
4. **Convert on close**: repeatable failures → bug reports with §3 classification; stable
   discoveries → scripted regression candidates (§11); unresolved threads →
   `next_run_focus` so the next delta run inherits them.
5. Close with the §13 handoff; the session gets its own report file per §7.
