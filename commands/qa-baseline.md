---
description: "Initialize Verdict for this repo: QA root, project profile, and a baseline run."
argument-hint: "[solo|team] [notes about risk areas, live services, money/data touched]"
---

Use the `verdict` agent to initialize QA for this repository:

`$ARGUMENTS`

Required flow:

1. Resolve the QA root per the agent's §0: `team` → create `<repo>/.qa/` (committed, shared
   baseline); `solo` or unspecified → `$VERDICT_HOME/<project-key>/` (default
   `~/.claude/verdict`), with `<project-key>` derived mechanically per §0 — main-worktree
   basename, never the current directory name.
2. Create `profile.md` in the QA root: what this project does, what it touches (money, live
   accounts, user data, external services), the isolation check to run before any command,
   commands that are forbidden, the real test/lint/coverage commands from the project's own
   Makefile/CI, and known risk areas or incident history from `$ARGUMENTS`.
3. Run a **baseline run**: execute the project's own test gates, record suite counts and
   durations, file findings with stable IDs, and write `state.json` and the first report +
   INDEX row.
4. Return: verdict, findings by severity, what was not covered, and the artifact paths.

A baseline run reports no deltas — say so explicitly. Every later run is a delta against
this state.
