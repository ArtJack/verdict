# QA report — verdict · run 2 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `85aeb65e356f651242e2746ebbfba72e6ce584bc..062feed6da03225dcaef39673a636a5df8e56f4b` · 107 files changed, 11567 insertions(+), 103 deletions(-)
- Branch: `main` · measured 2026-08-30T09:16:54Z
- Isolation check: **pass**

This is run 2 and a declared re-baseline, not a delta. Two independent §6 triggers fired: the diff from the stored SHA spans 107 files and 11,567 lines, past both the ~100-file and ~10,000-line thresholds. The stored SHA 85aeb65 is still in the repository, so the previous run's four findings were each re-checked against real history rather than assumed stale.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 32.26s | 336 passed in 32.03s |
| `fixture_freshness` | fail | 1 | 0.03s | pricer-delta.diff /tmp/fresh.diff differ: char 21, line 1 |

Tests: passed 336, collected 336
Test-id ledger: 336 ids · +50 / −0 (set-diff, not summary arithmetic)

## Risks

What replaces them is smaller in number and similar in kind — both new Majors are guards that exist and do not run. fixture_freshness, the gate protecting the tamper-evidence anchor, failed this run, and it failed on dirt: `git diff --no-index` compares directories literally and does not honour .gitignore, so a .pytest_cache left in eval/fixtures/pricer/ doubles the diff and presents as tampering of the one file the profile forbids regenerating. The tree is clean; the gate is not hermetic. Separately, the Action has no require-harness input at all, so exit 6 — the check this plugin's own documentation names as the thing that catches a fabricated run — cannot be switched on in CI, including in Verdict's own PR gate. The CLI has the guard; the unattended path does not.

The third item is the same shape and is why this run needed a repair before it could measure anything: the repository's own committed profile had no front-matter gates block, so the first verdict-facts invocation ran zero gates. The package shipped the feature and the repo never adopted it. That the run said so out loud, in one line, rather than reporting a clean sweep of nothing, is the system working — but three findings in a row are now 'the mechanism is present and not wired in', and that is worth reading as a pattern rather than as three coincidences.

## Findings — REGRESSED first (4 open of 9 tracked)

### VERDICT-F-5 — NEW — Major/P1 — BRITTLE_TEST

fixture_freshness, the tamper-evidence gate, false-fails on gitignored build artifacts: `git diff --no-index` does not honour .gitignore
- gate `fixture_freshness` exited 1 this run: 'pricer-delta.diff /tmp/fresh.diff differ: char 21, line 1' (see facts.json gates.fixture_freshness)
- anchor eval/fixtures/pricer-delta.diff is 78 lines; the freshly generated /tmp/fresh.diff is 156 lines
- the 62 extra leading lines are all eval/fixtures/pricer/.pytest_cache/* and __pycache__ entries, absent from pricer_rev_b
- `git status --porcelain eval/fixtures/` is clean and .gitignore lists `__pycache__/` and `.pytest_cache/` — so the tree is untampered; `git diff --no-index` compares two directories literally and ignores .gitignore
- `ls -a eval/fixtures/pricer/` shows .pytest_cache and __pycache__ present; `git ls-files eval/fixtures/pricer/` lists only the 4 source files
- impact: any run of the fixture's own tests (or any tool that imports it) permanently reddens the gate, and it reddens as apparent tampering of a file the profile explicitly forbids regenerating — the operator is steered into a wall

### VERDICT-F-6 — NEW — Major/P2

The GitHub Action exposes no `require-harness` input, so gate exit 6 — the anti-fabrication check — is unreachable in CI, including this repo's own qa-gate.yml
- action.yml `inputs:` (lines 10-49) has no require-harness entry; the gate step builds ARGS from PROJECT, FAIL_ON, FINDINGS, MAX_AGE_HOURS, MIN_RUN_NUMBER only (action.yml:129-131)
- action.yml:56 documents the exit-code output as '0/1/3/4/5' — 6 is not listed
- src/verdict_mcp/gate.py:116-121 implements exit 6 and verdict-run defaults it ON (runner.py:137 --no-require-harness is opt-out), so the CLI path has the guard and the CI path cannot
- .github/workflows/qa-gate.yml passes only max-age-hours, so Verdict's own PR gate would accept hand-written state
- commands/run.md and README.md:392 both name `verdict-gate --require-harness` as the check that catches a fabricated run — the documented guard is absent exactly where runs are unattended

### VERDICT-F-9 — NEW — Major/P2

verdict-finalize crashes with a raw AttributeError when judgment.json's `prose` is a string rather than an object; validate_judgment does not check the field
- hit live in this run: `verdict-finalize --qa-root .qa --judgment .qa/judgment.json` exited on `File "src/verdict_mcp/harness.py", line 909, in render_report / if prose.get("scope"): / AttributeError: 'str' object has no attribute 'get'`
- render_report(state, prose: dict | None) at harness.py:884 calls prose.get() six times (lines 909, 930, 960, 973, 984) with no type guard and no default-to-{} for a non-dict
- validate_judgment (src/verdict_mcp/validate.py:95-183) checks verdict, not_tested, isolation_check, findings, ids, severity, priority, status, classification, evidence, confidence, fix_verified and computed-field collisions — but never mentions `prose`
- the crash lands at harness.py:822, after validate_judgment returned clean and after merge() ran: state.json was never written and .qa/run-in-progress.json was left in place
- agents/verdict.md:383 does document the object shape (scope, risks, fix_order, notes, findings), so this is an unvalidated contract, not an undocumented one
- why it matters beyond ergonomics: the docstring at validate.py:96-107 states this function exists to catch the author's mistake 'at the boundary where its author still stands'. A crashed finalize with no state on disk is precisely the situation in which a model is tempted to hand-write state.json — the failure mode enforce_run_contract.py and gate exit 6 exist to police.

### VERDICT-F-1 — RESOLVED — Major/P1

Scope guards use abspath not realpath; a symlink inside .qa/ escapes the QA root (both write and bash guards)
- hooks/qa_paths.py:26 now resolves with os.path.realpath and names VERDICT-F-1 in its docstring
- re-injection probe, write guard: a .qa/-resident symlink to /fictional-escape-target under VERDICT_STRICT=1 returned exit 2 (blocked); previously 0
- re-injection probe, bash guard: `echo x > <qa>/.qa/pwn` through the same symlink returned exit 2 (blocked)
- both regression tests exist and are collected: tests/test_hooks.py:106 test_write_blocks_symlink_escape_from_inside_qa and tests/test_hooks.py:127 test_bash_blocks_symlink_escape_from_inside_qa, the latter asserting rc == 2
- note on probe design: a first probe pointing the symlink at /tmp returned 0 from the bash guard — correctly, because /tmp is an explicit scratch allowance (enforce_bash_scope.py:60-91), not an escape. The finding is closed on the non-scratch probe.

### VERDICT-F-2 — RESOLVED — Major/P2

qa-gate.yml gates PRs on committed .qa/ state, but .qa/ is untracked; gate takes the no-state path (exit 4)
- `git ls-files .qa` now returns profile.md, reports/2026-08-28-baseline.md, reports/INDEX.md, state.json and test-ids.txt — the state is tracked
- the diff 85aeb65..HEAD lists .qa/state.json and .github/workflows/qa-gate.yml as additions (A), so both were committed in this range
- .gitignore still does not exclude .qa/, consistent with team mode
- residual, not a reopen: the gate now finds state, but cannot require it be harness-produced — filed separately as VERDICT-F-6

### VERDICT-F-7 — NEW — Minor/P2

Verdict's own committed .qa/profile.md carried no front-matter gates block, so verdict-facts measured zero gates on this repository
- first verdict-facts invocation this run reported profile_notes: '.qa/profile.md has no front-matter block; gates must come from --gate' and no_gates: 'no gates ran ...'
- the profile recorded the same commands in prose under '## Real commands', which is the retyping step src/verdict_mcp/profile.py:1-33 exists to delete
- the feature shipped in the package but was never applied to the repository's own profile — the state file committed at 85aeb65 predates it and was never migrated
- repaired this run: a gates block (suite, fixture_freshness) and test_ids_cmd were added to .qa/profile.md, after which both gates ran and were timed (facts.json gates.*)
- mitigating: verdict-facts said so loudly rather than silently reporting a clean run — the no_gates note is why this was caught in one command

### VERDICT-F-8 — NEW — Minor/P3 — BRITTLE_TEST

Three mutation-tool tests assert only inside a `for mutant in generate(source)` loop and pass vacuously if generate() ever returns nothing
- tests/test_mutate.py:32 test_mutants_keep_the_file_parseable has no assert or pytest.raises at all — its check is the `compile()` call inside the loop body
- tests/test_mutate.py:25-30 test above it likewise asserts only per-iteration
- an AST sweep of tests/ found exactly one test function with neither assert nor raises, and it is this one — so the suite is otherwise clean on this axis
- if generate() regressed to returning [], all three tests stay green while the mutation engine is producing no mutants — the tool that measures suite quality would be unmeasured itself

### VERDICT-F-3 — RESOLVED — Minor/P2

addopts='-q' plus CI's '-q' equals -qq: no countable summary line, and --collect-only -q emits counts instead of test IDs
- .github/workflows/ci.yml:35 now runs `uv run --group dev python -m pytest tests/` with no -q, so addopts='-q' is not doubled
- this run's suite gate parsed a summary line directly: '336 passed in 32.03s', counts_dialect 'pytest'
- test-ID collection with `-o addopts=` produced 336 named IDs (facts.json test_ids.status 'measured'), not per-file counts
- pyproject.toml:36 still sets addopts='-q'; the fix removed the second -q rather than the first, which is the correct half to remove

### VERDICT-F-4 — RESOLVED — Minor/P3

Orphaned .qa/test-ids.txt present with no state.json (partial prior run); closed by this baseline
- state.json and test-ids.txt are both present, both tracked, and both rewritten by this run's harness
- stays closed


## Track record

9 findings tracked across this project's history · 3 settled, 6 still undecided.

| Confidence claimed | Held up | Withdrawn | Rate |
|---|---|---|---|
| unstated | 3 | 0 | _not yet_ |

*A rate appears once a row has 30 settled outcomes. Settled means fix-verified or regressed (it held up) against withdrawn (it did not); a finding merely resolved is not evidence either way.*

## Release blockers

_None._

## Not tested

- Windows and Python 3.10 CI matrix legs — unreproducible on this macOS host; the cp1252 encoding guards in runner.py/gate.py are unexercised here
- Agent prompt behaviour via live-model eval (eval/run_eval.py) — costs API calls; agents/verdict.md changed substantially in this range and its regressions are only visible through the eval corpus
- The Action's experimental `run` mode end-to-end (uses --dangerously-skip-permissions and can commit .qa/; forbidden by the profile)
- The Action's gate mode as GitHub actually executes it — action.yml was read, not run
- Coverage and mutation score against this repository — no coverage tool configured, and eval/run_mutation.py was not run over src/
- MCP server end-to-end over stdio with a real client (src/verdict_mcp/server.py)
- The two SessionStart/Stop hooks (report_open_findings.py, enforce_run_contract.py) under a real Claude Code session — read and reasoned about, not fired
- Assertion bodies of the 336 tests were swept structurally for missing assertions, not individually audited for correctness of expectation
- The 52M of registered git worktrees under .claude/worktrees/ (two live worktrees on other branches) — out of scope at HEAD

## Fix order

1. **VERDICT-F-5** — make `fixture_freshness` hermetic. It is red now, and a red trust-anchor gate that cries tamper trains the reader to ignore it.
2. **VERDICT-F-6** — add the `require-harness` input and switch it on in `qa-gate.yml`. This is the guard that catches the failure mode the plugin's own docs lead with.
3. **VERDICT-F-9** — validate `prose` in `validate_judgment`; it is a two-line check that converts a traceback into a sentence.
4. **VERDICT-F-8** — assert a non-zero mutant count in the three loop tests.
F-7 is already repaired in the QA root and needs no code change, though the 'ran zero gates' case may deserve a louder exit.

## Next run focus

- VERDICT-F-5: is fixture_freshness hermetic — does it still pass after running pytest inside eval/fixtures/pricer/, and was pricer-delta.diff left byte-identical?
- VERDICT-F-6: does action.yml accept require-harness, does qa-gate.yml set it, and does a state with facts.json removed actually exit 6 through the Action's code path?
- VERDICT-F-8: do the three test_mutate.py loop tests now assert a non-zero mutant count?
- VERDICT-F-9: does validate_judgment reject a string `prose` by name, and does render_report survive one?
- Confirm F-1/F-2/F-3 stay closed — re-run the two symlink probes and check ci.yml has not regained -q
- First true ID set-diff opportunity against the 336-ID ledger this run wrote (this run's diff was a re-baseline, so every ID reads as added)
- Audit whether .qa/facts.json and .qa/judgment.json should be committed: the CI gate needs facts.json present for --require-harness to pass on a fresh checkout, and neither is in .gitignore today
- Run eval/run_eval.py or the corpus scorer against agents/verdict.md — the largest unmeasured surface in this range

## Notes

The caller's three claims all hold, and all three are now closed on evidence rather than assertion. F-1 is fixed in code (qa_paths.py resolves with realpath) and closed on an active re-injection probe: a symlink planted inside .qa/ pointing at a non-scratch target is now blocked (exit 2) by both the write and the bash guard, and both regression tests exist. Worth recording that the first probe returned 0 from the bash guard because it pointed at /tmp, which is a deliberate scratch allowance — the guard was right and the probe was wrong; the finding is closed on the corrected one. F-2 is fixed: .qa/ is tracked. F-3 is fixed: CI dropped its second -q, and this run parsed '336 passed' straight off the summary line. F-4 stays closed.

Verdict is pass with risks. The suite is green at 336 passed in 32s, up from 106, with one structurally vacuous test; isolation holds; nothing here blocks a release. Two Majors are open and neither is in the shipped runtime path — they are in the machinery that is supposed to catch the next problem.

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
