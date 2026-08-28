# Changelog

Plugin and `verdict-mcp` share one version line; `.claude-plugin/plugin.json` and
`pyproject.toml` are bumped together.

## 0.5.0 — 2026-08-27 · "close the loop"

The tester's memory becomes a machine surface CI can trust.

- **`verdict-gate` CLI**: an exit-code release gate over the state — `0` pass · `1` fail ·
  `2` usage · `3` blocked · `4` no state (the tester never ran) · `5` stale
  (`--max-age-hours`, `--min-run-number`). Stdlib-only and runnable as a bare script;
  formats: `text`, `json`, `github-comment` (sticky marker), `github-output`.
- **GitHub Action** ([action.yml](action.yml)): gate mode with zero installs, zero keys,
  zero model — reads committed `.qa/` state, sets job status, maintains one sticky PR
  comment with the REGRESSED-first findings table. Experimental run mode executes a
  headless Verdict pass first, on `anthropic-api-key` or a subscription
  `claude-oauth-token` (self-hosted runners), with `anthropic-base-url` passthrough;
  optional `.qa/` commit-back.
- **MCP `get_report` + `get_profile`**: report content (path-guarded to the QA root,
  symlink-safe, 512 KB cap) and the profile — consumers can quote the evidence, not just
  link it.
- **Stdlib core extracted**: `verdict_mcp.state` (loading/resolution/ordering, shared by
  server and gate) and `verdict_mcp.project_key` — the reference implementation of
  [docs/project-key.md](docs/project-key.md), tested against its decision table
  (worktrees, detached HEAD, bare repos, non-git).
- **Loop race closed**: the documented driver asserts `run_number` advanced
  (`--min-run-number` as a CLI); [docs/nightly.md](docs/nightly.md) ships the
  cron/systemd/subscription-token recipe for nightly runs on your own machine.

## 0.4.0 — 2026-08-27 · "the tested tester, for real"

The security control and the flagship behavior are now tested — by machines.

- **Strict-mode Bash guard** ([hooks/enforce_bash_scope.py](hooks/enforce_bash_scope.py)):
  under `VERDICT_STRICT=1`, the obvious Bash write channels — output redirection, `tee`,
  `sed -i`, `rm`/`mv`/`cp` and friends, mutating `git` verbs — are denied when the target
  lies outside the QA root. A deny-heuristic, not a sandbox; the README states exactly
  which.
- **Hook test suite** ([tests/test_hooks.py](tests/test_hooks.py)): traversal escapes,
  `$VERDICT_HOME`, strict/non-strict matrix, chained commands, unresolved variables,
  fail-open on garbage input. Both hooks now share one path predicate
  ([hooks/qa_paths.py](hooks/qa_paths.py)) that honors `$VERDICT_HOME`.
- **Deterministic eval scorer** ([eval/score.py](eval/score.py) + machine answer keys):
  scores the state file, not the prose; hard-fails on a modified fixture, missing
  state/report, a laundered pass, or a forbidden phrase. Unit-tested like any other code.
- **Delta eval** — the flagship finally has a test:
  [fixtures/pricer_rev_b](eval/fixtures/pricer_rev_b) plus an authored golden run-2
  history; one run must produce `REGRESSED` (ranked first), `NEW`, `STILL_OPEN`,
  `RESOLVED`, and release an expired quarantine, against a CHANGELOG decoy that tries to
  launder the new defect. The committed rev-A→rev-B diff is CI-checked for drift.
- **Adversarial honesty fixture** ([fixtures/liar](eval/fixtures/liar)): an always-green
  test script, a skip-everything conftest, a mock-asserting test, a tautology — and the
  real defect they hide.
- **Eval harness** ([eval/run_eval.py](eval/run_eval.py)): isolated scratch repo, scratch
  `VERDICT_HOME`, `--setting-sources project`; `baseline` | `seeded` | `live` modes.
- **CI**: pytest matrix (3.10/3.13 × ubuntu/windows) and delta-diff freshness on every
  push; model-run evals are weekly/dispatch-only and never gate a PR.

## 0.3.0 — 2026-08-27 · "trust the memory"

Correctness release: everything the delta memory depends on is now specified mechanically
instead of by prose that drifted in practice.

- **Project key is derived, not guessed.** §0 now carries a mechanical rule (main-worktree
  basename, lowercased, sanitized) with a normative decision table in
  [docs/project-key.md](docs/project-key.md) — running from a git worktree no longer mints a
  variant key and fragments the baseline (observed live before this fix). Once a QA root
  exists, its recorded key is authoritative; repo renames are surfaced as a human decision,
  never healed by minting a second root.
- **`$VERDICT_HOME` honored by the agent**, matching the MCP server, so state can be
  relocated (and evals isolated) — resolved operationally in §0 via
  `${VERDICT_HOME:-$HOME/.claude/verdict}`, because an agent cannot know an environment
  variable without asking the shell (caught live by the eval harness).
- **`FLAKY` vs `BRITTLE_TEST` boundary sharpened** (§3): FLAKY is *undiagnosed*
  intermittence and quarantine is diagnosis deferred; a diagnosed mechanism (time-seeded
  input, order dependence) is a brittle test with a fix task, inside the verdict. The
  baseline answer key accepts both routes for the seeded flake, amendment documented.
- **`failure_classification` is part of the finding shape** (§6 + schema): machine
  consumers — the eval scorer, the gate — read the field, never the prose.
- **Timestamps are measured, never remembered.** Every date the agent writes comes from
  `date -u` — fabricated `T00:00:00Z` timestamps had been corrupting age/expiry math.
- **Corrupted `state.json` is preserved**, renamed `state.json.corrupt-<date>`, filed as a
  finding, and followed by a declared re-baseline — never silently overwritten.
- **The report artifact is non-waivable.** A caller may narrow scope; no caller may talk the
  agent out of writing the report file.
- **Profile stub on every baseline run**, with a machine-checkable header
  (`Project-Key` / `Repo-Path` / `Repo-Remote`) — baselines reached via `/qa-review` no
  longer skip profile creation.
- **Write-collision detection**: state is re-read immediately before the final write; a
  moved `run_number` aborts the write and reports the collision.
- **Duration gate is measurable**: gates and tests may record `duration_s` (additive,
  schema stays v1); the week-over-week duration gate cites it or declares itself
  unmeasurable.
- **`hash` vs `id` semantics fixed in prose**: `hash` recognizes a finding across runs;
  `id` is minted once and never renumbered.
- **INDEX gains a Blocker column** (`Findings (B/C/M/m)`) for new indexes; existing files
  keep their header per the match-columns rule.
- **MCP server**: severity ranking is case-insensitive; Windows drive paths (`C:/…`,
  `C:\…`) are recognized as paths; solo key lookup falls back to lowercase.
- Previous-run `next_run_focus` items must now be explicitly addressed each run.

## 0.2.2 — 2026-08-26

- Test design: 24-technique catalog with risk triggers ([docs/test-design.md](docs/test-design.md)).

## 0.2.1 — 2026-08-26

- Docs: the fix loop — Verdict as gate, never actor.

## 0.2.0 — 2026-08-25

- `verdict-mcp`: read-only MCP server over the QA state (verdicts, findings, quarantine,
  history).

## 0.1.0 — 2026-08-24

- Initial release: skeptical QA agent with memory — baseline → delta runs, five-class
  failure classification, flaky quarantine with expiry, four-verdict contract, write-scope
  hook, seeded-defect eval with published answer key (first published run 8/8).
