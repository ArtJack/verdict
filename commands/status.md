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
3. Call out staleness — **in commits, not only in hours.** A verdict ages two ways and
   the clock only catches one of them. Compare `last_run.git_sha` to the current `HEAD`:
   - `HEAD` is that commit → the verdict describes the code in front of you.
   - `HEAD` is *n* commits ahead → say so first, before the findings: "measured *n*
     commits ago — these may already be fixed." This repository's own state once named
     three open Major findings that had all been fixed and merged four hours earlier;
     the seven-day rule could not see it, because the state had not aged, the code had
     moved.
   - the recorded commit is not in `HEAD`'s history → **do not call that divergence
     yet.** Ancestry is not content. A squash merge replaces a branch with a new
     commit carrying the identical tree, so the commit a state was written on stops
     being an ancestor the moment its PR lands — while the code stays byte-identical.
     Compare trees before you speak: if some commit in `HEAD`'s history has the tree
     the state recorded, the distance to it is the honest answer. Only when no commit
     carries that content does the verdict describe code this branch never had.
   - the commit is not in this repository at all (shallow clone, different repo) → say
     the comparison could not be made. Never guess a distance.
   A last run older than 7 days still gets its "stale — run `/verdict:run`" line. Neither
   signal substitutes for the other, and neither is a silently reheated verdict.
4. **Write nothing.** No state update, no report file, no INDEX row.
