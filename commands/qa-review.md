---
description: "Run a Verdict QA review for a feature, diff, bug, or project area."
argument-hint: "[feature, branch, diff range, or area to review]"
---

Use the `verdict` agent to run a QA review for:

`$ARGUMENTS`

Required flow:

1. Read state first (§6): if `state.json` exists this is a **delta run** — scope by
   `git diff <last_sha>..HEAD` and age all findings; if not, declare a baseline run and
   create the QA root plus a `profile.md` stub per §0/§6.
2. Assess risk on the changed surface: acceptance criteria, boundary values, failure
   classification for anything red, coverage direction on changed files.
3. Return: risks, test scenarios (technique named per §4), findings with evidence,
   blockers, automation candidates, and the `VERDICT:` line.

Verdict reports and specifies; it does not fix. Route fixes to the implementer.
