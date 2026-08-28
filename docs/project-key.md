# The project key — normative spec

The project key names a project's QA root (`$VERDICT_HOME/<key>/` in solo mode) and its
`project` field in `state.json`. If the key drifts, the delta memory fragments: two roots
for one repo means every run is a false baseline. This page is the single source of truth;
the agent's §0 carries the recipe, and `verdict_mcp.project_key` (from v0.5.0) is the
reference implementation. If they ever disagree, this document wins.

## Derivation

```bash
key=$(basename "$(git worktree list --porcelain | head -1 | cut -c10-)" | tr 'A-Z' 'a-z')
```

The **main worktree's directory basename, lowercased**. `git worktree list --porcelain`
lists the main worktree first regardless of which linked worktree you run it from;
`cut -c10-` strips the leading `worktree ` prefix. Then:

1. Strip a trailing `.git` (bare repos).
2. Replace every character outside `[a-z0-9._-]` with `-`.
3. If the git command fails (not a repository), fall back to the basename of the project
   directory, lowercased — and say so in the report.

Never append branch names, worktree names, or component names. A sub-scope ("the pricing
module", "the nightly branch") belongs inside the report, not in the key.

## Decision table

| Situation | Key | Why |
|---|---|---|
| Normal repo `/Users/a/Projects/Sales` | `sales` | main worktree basename, lowercased |
| Linked worktree `.../Sales/.claude/worktrees/qa-nightly` | `sales` | porcelain line 1 is the main worktree — the current directory name lies |
| Detached HEAD | unchanged | `git worktree list` does not depend on HEAD; only `last_run.git_branch` records `(detached)` |
| Bare repo `/srv/app.git` | `app` | first porcelain line is the bare path; `.git` suffix stripped |
| Not a git repository | directory basename, lowercased | stated explicitly in the report |
| Submodule | the submodule's own directory name | `git worktree list` runs in the submodule's repo — it is its own project |
| Repo renamed after a baseline exists | the **old** key | recorded key is authoritative (below) |
| `$VERDICT_HOME` set | root = `$VERDICT_HOME/<key>` | agent and MCP server honor the same variable |

## The recorded key is authoritative

Once a QA root exists, derivation only *finds* it — it never overrides it:

- A root already present under the derived key is used as-is.
- If the derived key has no root, but some existing root's `profile.md` names this repo in
  its `Repo-Path:` or `Repo-Remote:` header, that root is used and the mismatch is reported
  (the repo was renamed or moved). The agent never mints a second root for the same repo.
- Renaming a key is a human decision. The agent surfaces it under "Needs human decision";
  the migration runbook below is the human's procedure.

For this to work, every `profile.md` starts with a machine-checkable header:

```markdown
# QA Profile — <key>

**Project-Key:** `<key>`
**Repo-Path:** `/absolute/path/to/main/worktree`
**Repo-Remote:** `<git remote get-url origin, or "none">`
```

## Team mode and worktrees

In team mode the QA root is `<repo>/.qa/`, committed with the code. A committed `.qa/`
appears in every worktree of the branch that carries it — state follows the branch. That is
the intended semantics (the baseline travels with the code under review), not a bug. Solo
mode is per-repo, not per-branch, by design: the main-worktree key gives all worktrees of a
repo one shared memory.

## Migration runbook (renaming a key)

Example: healing a drifted `sales-main` root whose correct key is `sales`.

1. Confirm no QA run is in flight for the project.
2. Back up the root **outside** the state home (a backup inside `$VERDICT_HOME` would be
   listed as a project itself):
   `cp -a "$VERDICT_HOME/sales-main" ~/.claude/verdict-backups/sales-main-<date>`
3. `mv "$VERDICT_HOME/sales-main" "$VERDICT_HOME/sales"`
4. In `state.json`: set `"project": "sales"`. Do **not** touch finding `id`s, `hash`es, or
   any unknown keys — ID stability outranks cosmetic consistency.
5. In `profile.md`: update the key, and add the `Project-Key:` / `Repo-Path:` /
   `Repo-Remote:` header if missing.
6. Leave historical `reports/INDEX.md` rows as written — history is history. New rows use
   the new key.
7. Verify: `list_projects` shows the new key; `get_verdict("<new>")` resolves;
   `get_verdict("<old>")` returns the unknown-project error listing the new key.
