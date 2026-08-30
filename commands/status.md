---
description: "Read-only QA status from the stored state — no run, no writes, no agent."
argument-hint: "[project key or path (default: this repository)]"
---

Report the current QA status for: `$ARGUMENTS` (default: this repository) — **without
running anything**. This is a read of the tester's memory, not a QA run, and it needs no
subagent.

1. Resolve the QA root per the verdict agent's §0 (team `.qa/` first, then the solo home
   `${VERDICT_HOME:-~/.claude/verdict}/<key>`) and read `state.json`,
   `reports/INDEX.md`, and `profile.md` where present. If the `mcp__verdict__*` tools are
   connected, prefer them over raw file reads.
2. Summarize: last verdict, when, and the SHA range · run number and type · open findings
   by severity with ages, REGRESSED first · release blockers · quarantine entries with
   their expiry status · the `not_tested` list · `next_run_focus`.
3. Call out staleness: a last run older than 7 days gets a "stale — run `/verdict:run`"
   line, not a silently reheated verdict.
4. **Write nothing.** No state update, no report file, no INDEX row.
