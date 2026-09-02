# QA report — verdict-clone · run 4 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `c38631793efefa1fda4e8f1453bb9318e8c772f6`
- Branch: `main` · measured 2026-09-02T04:44:40Z
- Isolation check: **pass**

Re-baseline over the verdict repository at HEAD c386317 (main, v0.50.1). This run was declared a **re-baseline**, and the harness independently reached the same conclusion for the same reason: the previous state's anchor `0a9269a` is not in this repository (`verdict-facts` recorded `run_type_reason: "stored sha ... is not in this repository"`). It was written on the unpushed branch `feat/commit-staleness`, so `git diff 0a9269a..HEAD` is uncomputable and no honest delta against the stored baseline exists. That is itself a live instance of VERDICT-F-18.

A reachable fallback anchor exists - run 2's `062feed6` is an ancestor of HEAD - and I used it to bound the reading surface: 21 commits, 69 files, 5991 insertions / 358 deletions, spanning v0.39.0 through v0.50.1. Both re-baseline triggers were checked against measured values: 69 files is under the ~100 threshold and 6349 changed lines under the ~10,000 one, and the last recorded run was 3 days ago, under the 7-day trigger. Neither of those forced a re-baseline; the unreachable anchor did.

**Run numbering.** This run is recorded as **run 4**, the value the harness computed as one past the last recorded run. Two earlier sessions on 2026-09-02 self-identified as runs 4 and 5 but were blocked and wrote nothing - `state.json` still said run 3 and INDEX.md had no row for either. Their reports were left in an unreachable scratchpad and are lost. So ledger numbering is contiguous while session numbering is not: a reader who ever recovers those lost reports should know that their 'run 4' and this 'run 4' are different runs, and that only this one is in the record.

**A date discrepancy worth stating.** The session was introduced as 2026-09-01, but `date -u` in this session returns 2026-09-02T04:43:04Z, and every timestamp in this state is the measured value. Ages computed from it may therefore read one day higher than a reader expecting 09-01 would predict.

**Project key.** The profile records `Project-Key: verdict` and `Repo-Path: /Users/artjack/Projects/verdict`, while this checkout is a clone whose directory basename derives to `verdict-clone` - which is what `verdict-facts` recorded as `project`, from `project_key_source: "git"`. The recorded key is authoritative and team mode resolves structurally (`<repo>/.qa`), so there is no split root and no second key was minted. It is noted because the facts and the profile disagree on the name in writing.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 52.07s | 543 passed in 50.35s |
| `fixture_freshness` | pass | 0 | 0.07s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 543, collected 543
Test-id ledger: 543 ids · +50 / −0 (set-diff, not summary arithmetic)

## Risks

**The instrument measuring this project is itself defective this run.** VERDICT-F-20 is a defect in `verdict-facts`' test-id accounting, and it fired on this very run: the facts report `+50` added tests against a prior ledger of 377 and a current count of 543, and 377 + 50 does not reconcile to 543. The true figure is +166. The mechanism truncates the diff list to 50 and then reports the truncated length as the delta, so the direction that matters - a mass test *deletion* - is under-reported in exactly the same way. This is the gate the agent contract singles out as the one that cannot lie ('summary counts can lie... the ID set cannot'), and it currently can.

**A state/ledger desync is now demonstrated, not theorised.** The two blocked runs left `.qa/test-ids.txt` advanced while `state.json` stayed at run 3. `verdict-facts` writes the ledger at measure time; `verdict-finalize` writes state at the end. A run that dies between them leaves the ledger ahead of the state, and the next run's set-diff is then computed against an anchor no recorded run ever claimed. Neither run left a `run-in-progress.json` marker for me to find, so this run had no signal of the incomplete predecessors other than the arithmetic failing to close.

**Suite duration crossed its gate.** 31.31s to 52.07s is +66.3%, against a 10% week-over-week limit. Test count rose 377 to 543 (+166), which explains most of it, but not all: per-test cost went 83.1ms to 95.9ms, +15.5%. I am reporting the gate as breached-with-cause rather than waving it through, and flagging it for re-measurement on an idle machine before it is treated as a trend. A single measurement on a loaded laptop is not a trend, and I am not claiming it is one.

**Coverage is unmeasurable and was not estimated.** No coverage tool is configured and the profile records no changed-files coverage command, so the coverage-delta gate could not fire. `mutmut` is declared in the dev dependency group but was not run, so suite quality remains unmeasured - which is worth weighing against VERDICT-F-20, a defect that a mutation run over `harness.py` would likely have caught, since the `[:50]` slice is precisely a boundary no test exercises.

**Two findings have fixes in flight that this HEAD does not carry.** `origin/fix/no-gates-and-absent-commit` (cc24a9e, titled 'v0.51.0: three findings Verdict filed against itself') is not an ancestor of HEAD. I judged VERDICT-F-17 and VERDICT-F-18 at HEAD, where both are present and unfixed. If that branch lands they should be re-judged, not re-derived.

**Risk ranking and cutoff.** Effort was weighted by this project's own history rather than by habit. The profile names the scope-guard hooks, the agent prompt, the scorer, and gate exit codes as the hot areas; the state file's findings cluster on `src/verdict_mcp/` (state.py, harness.py, gate.py, validate.py carry F-5, F-9, F-10, F-12, F-17, F-18 between them), and that is where this run read. The cutoff fell after the seven open findings, the three briefed ones, and the census leads: `server.py`, `runner.py`, `census.py` internals, `project_key.py` and the eval corpus went unread and are listed in not-tested. The clustering evidence is thin and I will say so - two prior runs of findings is a snapshot, not a pattern.

## Findings — REGRESSED first (9 open of 14 tracked)

### VERDICT-F-10 — RESOLVED — Major/P1 — age 2d

code_drift reports `diverged` after an ordinary squash merge, so the SessionStart banner tells the reader 'this verdict describes different code' about byte-identical code
- FIXED at HEAD by the exact fix direction the finding specified - comparing trees rather than ancestry. src/verdict_mcp/state.py code_drift now falls through from the not-an-ancestor branch to `rec_tree = git("rev-parse", f"{recorded}^{{tree}}")`, then walks HEAD with `rev-list --max-count={_DRIFT_SEARCH} --format=%T` and returns 'current' at distance 0 or 'behind' at distance n when a matching tree is found. Only when no commit in the walk carries that tree does it return 'diverged'.
- The comment states the reasoning in the finding's own terms: 'A squash merge replaces the branch with a new commit carrying the identical tree, so every squash-merged state would otherwise report "this verdict describes different code" about code that is byte-identical.'
- Guarding tests now exist and pass in this run's green suite: tests/test_code_drift.py::test_squash_merged_state_is_current_not_diverged, ::test_squash_merged_then_moved_on_reports_the_real_distance, ::test_diverged_branch_is_not_reported_as_behind, ::test_intermediate_commit_of_a_squashed_branch_is_diverged. All four are among this run's 166 newly-collected ids.
- The secondary sub-item is also fixed: a bad object no longer reads as diverged - `if anc is None or anc.returncode not in (0, 1): return out` with the comment '0 = ancestor, 1 = not; anything else is an error, not an answer'.
- fix_verified is FALSE: I confirmed the fix by reading the implementation and by the presence and passing of four targeted tests, but I did NOT re-inject the ancestry-only logic in a scratch copy to watch those tests fail. Per this project's own lessons.md, absence of the defect is a weaker claim than a verified fix, and I am not making the stronger one.

### VERDICT-F-11 — RESOLVED — Major/P2 — age 2d

The published sdist ships tests/ without the eval/, hooks/ and commands/ trees they read, so the distribution's own suite has a collection error and 123 failures
- FIXED at HEAD, by removing tests/ from the sdist rather than by adding the trees. pyproject.toml's hatchling include list is now exactly ['/src/verdict_mcp', '/README-pypi.md', '/README.md', '/CHANGELOG.md', '/LICENSE', '/pyproject.toml'] with exclude ['/.claude']. `/tests` is absent, so the archive cannot contain a suite that fails to collect.
- The decision and its trade-off are recorded in the pyproject comment, which cites this finding's own measurements: '`/tests` is deliberately absent. It was included, and the trees it imports - eval/, hooks/, commands/ - were not, so the published suite could not run: collection error, 123 failures on a `git archive` build. Adding them costs ~1.1MB against a 124KB archive... A suite that cannot run is worse than no suite; the repository is where this project is tested.'
- The finding's own scope bound is preserved: it noted the WHEEL was always sound, and the wheel's contents are unchanged by this.
- fix_verified is FALSE and the verification is weaker than the original report's: the finding was ESTABLISHED by building an sdist from a clean export and running the suite inside it; I closed it by reading the allowlist that governs the build. I did not build and unpack an sdist this run.
- RESIDUAL, not filed as a finding: the published distribution now ships no tests at all, so nothing downstream can verify an installed copy. That is a deliberate, documented trade-off by the maintainer, not a defect.

### VERDICT-F-12 — RESOLVED — Major/P2 — age 2d

gate --require-harness is defeated by imitation, not just forgery: both durable signals are visible in the committed .qa/ artifacts a fabricating model would copy
- FIXED at HEAD by adding a content-bound third signal. src/verdict_mcp/state.py:421 DURABLE_SIGNALS = ('state_computed', 'report_rendered', 'chain_intact') - the two copyable strings are now joined by a signal that cannot be copied, because chain_link() is sha256(prev_link + the canonical row derived from the state), so a link copied forward does not verify against the new row.
- _chain_signal additionally re-derives history_row(state) and requires it to reproduce the recorded link, closing the laundering variant: 'without this, laundering the verdict and emptying the findings in state.json alone left an intact chain behind it, which is the hole the chain was added for.'
- FIX VERIFIED by re-running the original attack, not merely by reading. In a scratch tempdir I built precisely the two imitation edits this finding reported - a hand-written state carrying "calibration": {} plus the RENDERED_BY_FINALIZE footer pasted into its report - and called the shipped gate.evaluate(..., require_harness=True). Result with a chained runs.jsonl present: exit=6, reason 'hand-written state: this run did not go through verdict-facts -> judgment.json -> verdict-finalize'. The attack that previously flipped the gate to a pass is now refused.
- Guarding tests exist and pass in this run's green suite, including tests/test_chain.py::test_gate_refuses_a_broken_chain_under_require_harness, ::test_laundering_the_state_in_place_breaks_the_link and ::test_dropping_the_link_is_a_break_not_a_downgrade.
- SCOPE BOUND, and it is important: this fix holds only once a project's history is chained. The same probe with runs.jsonl absent returns exit=0. That residual is filed separately and honestly as VERDICT-F-21, and it currently applies to this very repository, whose runs 2 and 3 carry no chain link.

### VERDICT-F-20 — NEW — Major/P2 — REAL_DEFECT

The test-id set-diff truncates added/removed to 50 and then reports the truncated list length as the delta, so a mass test deletion is rendered as '-50' under a line claiming 'set-diff, not summary arithmetic'
- src/verdict_mcp/harness.py:444-445 truncates both lists: "added": sorted(set(ids) - set(before))[:50], "removed": sorted(set(before) - set(ids))[:50]
- src/verdict_mcp/harness.py:1066-1067 then renders the delta from those truncated lists: out.append(f"Test-id ledger: {ids['count']} ids . +{len(ids.get('added', []))} / -{len(ids.get('removed', []))} (set-diff, not summary arithmetic)")
- PROVEN by counterfactual in a scratch tempdir (never the checkout): prior ledger of 200 ids, suite now collects 20, i.e. 180 tests deleted. collect() returned count=20, TRUE removed=180, REPORTED removed=50. Rendered line: 'Test-id ledger: 20 ids . +0 / -50 (set-diff, not summary arithmetic)'
- LIVE INSTANCE this run: facts.json reports added=50 against a 377-id prior ledger and a 543-id current one. The true added count is 166 (comm -13 on the sorted sets), and 377 + 50 does not reconcile to 543 - the arithmetic visibly does not close.
- The cap is untested: tests/test_harness.py:99-111 exercise only one-element diffs (assert facts["test_ids"]["added"] == ["t.py::new"]). No test constructs a diff larger than 50, so nothing fails when the cap engages.
- agents/verdict.md section 6 makes this exact guarantee load-bearing: 'Account for changes by ID set-diff, never summary arithmetic... Summary counts can lie... the ID set cannot.'
- Root cause: the [:50] slice at harness.py:444-445 is a *display* cap applied to the stored list, but harness.py:1066-1067 derives the reported *count* from len() of that already-truncated list, so the cap silently becomes the ceiling of the number the gate reports → the truncation and the renderer were written against each other's small-case behaviour; tests/test_harness.py:99-111 only ever exercise 1-element diffs, so the two have never disagreed under test
- Class: "searched src/verdict_mcp/harness.py for other len()-of-a-capped-list renders; this is the only site. The sibling value ids['count'] is computed from the untruncated set and is correct, which is why t

### VERDICT-F-21 — NEW — Major/P2

The run-history chain has no cross-file ratchet: with runs.jsonl absent or unchained, --require-harness reverts to the imitation-defeatable state and exits 0 - and this repository's own ledger is currently unchained
- PROVEN by differential probe in scratch tempdirs, running the shipped gate.evaluate(..., require_harness=True) against the original VERDICT-F-12 attack (a hand-written state carrying only the two imitation edits: "calibration": {} and the RENDERED_BY_FINALIZE footer pasted into the report). With a chained runs.jsonl present: exit=6, reason 'hand-written state: this run did not go through verdict-facts'. With runs.jsonl absent: exit=0, chain='unchained', reason='pass'.
- src/verdict_mcp/state.py:_chain_signal returns `not recorded` when verify_chain reports 'unchained', so a state that simply omits last_run.chain satisfies chain_intact - the strongest of the three DURABLE_SIGNALS (state.py:421) - by claiming nothing.
- src/verdict_mcp/gate.py:171-172 records the unchained case as advisory only: `if verify_chain(rows)["status"] == "unchained": out["chain"] = "unchained"` - it never affects exit_code.
- verify_chain DOES implement a ratchet *within* the file - state.py docstring: 'a row after the first chained one dropped its link' is 'broken... without that ratchet, a fabricator could simply omit what it cannot compute'. Deleting the whole file evades exactly that reasoning.
- LIVE EXPOSURE: this repository's .qa/runs.jsonl rows for runs 2 and 3 both carry chain: ABSENT, so verify_chain returns 'unchained' here today and the VERDICT-F-12 hardening does not currently protect this repo. This run writes the first signed row.
- Root cause: 'unchained' is treated as a migration state rather than a downgrade. _chain_signal cannot distinguish 'this project has never been chained' from 'this project was chained and the file is now gone', because the only evidence it consults for that question is the file itself → a deliberate and documented carve-out - state.py: 'A project from before the chain existed', gate.py: 'failing them all would be a migration by ambush'. The intent is sound; the gap is that the carve-out has no expiry and no external anchor
- Class: "HYPOTHESIS: the same shape would apply to any future durable signal that lives in a deletable file under the QA root. I checked the other two signals - state_computed reads state.json itself and repo

### VERDICT-F-23 — NEW — Major/P2

The harness derives project identity from the git directory basename and never reads the profile's Project-Key header, so a clone under a different directory name silently re-keys a committed team-mode state and its run ledger
- PROVEN live by this run's own artifacts. .qa/state.json.prev (run 3) records project: 'verdict'; after verdict-finalize the new state records project: 'verdict-clone'. The identity of a committed, shared state file changed because the checkout directory is named differently.
- The INDEX shows the same split: the row this run appended reads '| verdict-clone |' in the Project column, against '| verdict |' on all three prior rows, so the human-facing history now names two projects for one repository.
- src/verdict_mcp/harness.py:352 sets `"project": key` where key comes from derive_key(repo), and harness.py:649 writes `"project": facts["project"]` straight into the state, overwriting whatever the previous run recorded. facts.json confirms the source: project_key_source: 'git'.
- Nothing in the shipped code reads the profile header: `grep -n "Project-Key" src/verdict_mcp/*.py` returns no matches at all, while .qa/profile.md carries `Project-Key: verdict` and `Repo-Path: /Users/artjack/Projects/verdict` in its header.
- The contract the code is meant to implement says the opposite. agents/verdict.md section 0: 'The recorded key is authoritative. A root that already exists under the derived key wins. If the derived key has no root but an existing root's profile.md names this repo's path or origin remote (Repo-Path: / Repo-Remote: headers), use that root and report the mismatch.' The agent is told to read the header; the harness never does.
- Blast radius is team mode specifically - the mode this repo uses and the README recommends - because .qa/ is committed and travels with the repository. Any clone, CI checkout, or agent worktree whose directory name differs from the key rewrites the shared history's identity on its next run.
- Downstream consumers key on this value: verdict-gate takes a project argument and load_state resolves by it, and the INDEX groups by it, so a re-keyed state is also a lookup break rather than only a cosmetic one.
- Root cause: project identity has two sources of truth - the profile's recorded Project-Key header and derive_key()'s directory-basename derivation - and the harness consults only the second, then writes it into the state unconditionally rather than comparing it with the value already recorded there → not traced to a commit this run. derive_key was written to be worktree-safe (it resolves the MAIN worktree, which is why a linked worktree does not re-key), so the clone-renamed case looks like an unhandled variant of a problem that was otherwise carefully considered rather than an oversight of the whole issue
- Class: "searched src/ for other readers of the profile header: `grep -n Project-Key src/verdict_mcp/*.py` finds none, so no code path anywhere honours the recorded key. state.py's repo_for_root DOES parse th

### VERDICT-F-17 — NEW — Major/P2

_unmeasured_suite early-returns on empty gates, so an unqualified `pass` stands over a run that measured nothing - and the harness drops the `no_gates` fact at the merge boundary, so state cannot tell 'design review' from 'broken profile'
- RE-VERIFIED at HEAD c386317, unchanged. src/verdict_mcp/validate.py:290-291: `gates = state.get("gates")` then `if not isinstance(gates, dict) or not gates: return []` - the check that refuses an unqualified `pass` over an unmeasured suite exits before it can fire when no gate ran at all.
- The docstring at validate.py:285-287 states the reasoning explicitly: 'A run with no gates configured is left alone: it claimed no suite, so it is not overclaiming one.' That holds for a genuine design review and fails for a profile whose front-matter block is missing or malformed - the two are indistinguishable at this point in the code.
- src/verdict_mcp/harness.py:901 DOES construct the distinguishing fact: facts["no_gates"] = 'no gates ran - neither --gate nor a profile front-matter block supplied one, so every count and duration gate is unmeasurable this run'.
- But harness.py:653 merges only `"gates": facts.get("gates", {})` into the state. grep -rn no_gates over src/ returns exactly one hit - its construction site. Nothing carries it into state.json, so the fact exists only in the per-run facts.json, which a team-mode .qa/ gitignores.
- Consequence: a project whose profile block silently breaks measures nothing, states `pass`, and validate raises no violation.
- IN FLIGHT, NOT MERGED: origin/fix/no-gates-and-absent-commit (cc24a9e, 'v0.51.0: three findings Verdict filed against itself') is not an ancestor of HEAD - git merge-base --is-ancestor reports not merged. Judged at HEAD, this is open.
- Confidence is `probable`, not `proven`: the code path is read and unambiguous, but I did not execute a no-gates run through validate to watch an unqualified `pass` survive.
- Root cause: the guard's own precondition (a non-empty gates dict) is exactly the condition that the failure mode produces, so the check is unreachable in the case it most needs to cover → not traced to a commit this run - the docstring shows the empty-gates branch is intentional, written for the design-review case
- Class: "HYPOTHESIS: the wider pattern is a guard whose precondition and its failure mode coincide. Not swept across the other validate checks this run."

### VERDICT-F-15 — STILL_OPEN — Minor/P3 — BRITTLE_TEST — age 2d

The stale-command-name guard sweeps README-pypi.md, docs/ and commands/ but still does not reach standards/ or templates/, so a dead command name can ship in those trees unnoticed
- PARTIALLY FIXED at HEAD, not resolved. tests/test_commands.py:66-68 now derives the sweep rather than hand-listing four paths: `live = [p for p in [*REPO.glob("*.md"), *REPO.glob("docs/*.md"), *REPO.glob("agents/*.md"), *COMMANDS.glob("*.md")] if ... not in history]`, and asserts the PyPI page is reached: `assert any(p.name == "README-pypi.md" for p in live)`. The two sub-gaps the original finding demonstrated (README-pypi.md, docs/*.md) are closed.
- The residual gap is real: neither standards/ nor templates/ appears in that glob list, and both are tracked and shipped - git ls-files returns standards/release-gate.md, standards/severity-priority.md, templates/bug-report.md, templates/exploratory-charter.md, templates/regression-checklist.md, templates/release-signoff.md, templates/test-case.md.
- Still latent, not live: grep -rn 'verdict:' standards/ templates/ returns no matches today, so no stale name is currently shipping. This is a coverage gap, as it was when first filed.
- The guard also improved in precision this range - it now matches the eleven command names that have ever existed rather than any '/qa-' prefix, after the wider sweep false-positived on a directory name in docs/project-key.md.
- NOTE ON IDENTITY: this run was briefed to file this defect as a new finding 'VERDICT-F-19'. It is not new - it is the unresolved remainder of VERDICT-F-15, first seen 2026-08-30, whose original title already named 'standards/* and templates/*' explicitly. Filing it again under a second id would double-count one defect and reset its age to zero, so id F-19 is deliberately left unused.
- Root cause: the sweep is still a hand-maintained list of four globs rather than a derivation over tracked markdown; two of the repo's seven shipped doc trees are outside it → narrowed this range from the original four literal paths to four globs; the widening addressed the instances reported and not the class
- Class: "this IS the class link of the original finding coming true - the fix targeted the two reported sites (README-pypi.md, docs/) and left the pattern alive. The sibling test test_readme_table_matches_shi

### VERDICT-F-13 — STILL_OPEN — Minor/P2 — age 2d

fixture_freshness reproduces the fixture lossily: content of tracked files only, so mode changes, symlink swaps and planted untracked files are invisible, and a missing tracked file tracebacks
- STILL OPEN at HEAD, unchanged at both cited lines. eval/fixture_freshness.py:44 still defines the fixture as tracked files only - `listed = _git(["ls-files", "-z", *PAIR], REPO).split("\0")` - so an untracked planted file is outside the comparison by construction (PROBE D).
- eval/fixture_freshness.py:54 is still `shutil.copyfile(REPO / rel, dest)`, which copies content and not mode. That is the single line behind three of the five gaps: chmod +x invisible (PROBE E), symlink swap invisible (PROBE F), and FileNotFoundError traceback on a deleted tracked file (PROBE C) and on a broken symlink (PROBE G).
- The file is 82 lines and the whole diff range touched neither line; carried on run 3's probe evidence, which was gathered in a purpose-built scratch git repo running the shipped script unmodified.
- Scope bound unchanged: the gate still does its main job - run 3's controls PROBE A (ignored build artifact, correctly 0) and PROBE B (genuine content edit, correctly 1) both held, and the gate passed this run in 0.07s with 'OK - pricer-delta.diff still describes the fixture pair (78 lines)'.
- HONEST LIMIT: I did not re-execute the five probes this run. The finding is carried on unchanged source at the two cited lines, which establishes the mechanism persists but is weaker than a fresh reproduction.

### VERDICT-F-14 — RESOLVED — Minor/P3 — age 2d

action.yml still documents its exit-code output as '0/1/3/4/5', omitting the 6 it can now emit
- FIXED at HEAD. action.yml:68 now reads `description: "The gate exit code (0/1/3/4/5/6)"`, against the `0/1/3/4/5` the finding cited at action.yml:65.
- The Action's contract now agrees with the two surfaces the finding named as already correct: gate.py:21 documents exit 6 in its module docstring ('hand-written state - --require-harness set and the run did not go') and commands/run.md documents it for the agent.
- fix_verified is FALSE: this is a documentation string with no behaviour to re-inject, and no test asserts the description text. Verified by reading the single line, which for a doc string is adequate evidence but is not a demonstration.

### VERDICT-F-22 — NEW — Minor/P2

The VERDICT_STRICT bash guard reads '>' and sed expressions inside quoted strings as output redirection and resolves the phantom target against the checkout, blocking read-only QA commands
- PROVEN three times in this session, all on read-only commands. (1) A grep whose echo label contained the literal text '>50 case' was refused: "output redirection targets '<checkout>/50 (a git checkout under /private/tmp)'". The '>50' was inside a double-quoted echo argument.
- (2) `cd /tmp && echo 'probe: the string >50 inside quotes'` - refused identically, with the target still resolved to '<checkout>/50' despite the cd to /tmp. So the guard resolves relative targets against the checkout root, not the command's actual working directory.
- (3) `sed -i.bak 's/A/B/' probe.py` run inside the session scratchpad was refused with the whole sed *expression* quoted back as the path: "sed in-place targets '<checkout>/s/evaluate(str(qa), require_harness=True)/evaluate(...)'".
- (4) A python -c whose string literal contained the arrow token '-> non-fixture samples:' was refused: "output redirection targets '<checkout>/non-fixture'". '->' is an extremely common token in Python type hints, docstrings and prose.
- hooks/enforce_bash_scope.py is the enforcement point; the guard fails CLOSED, which is the correct direction and is why this is Minor rather than Major - no unsafe command was permitted.
- Cost is real but bounded: each refusal is recoverable by rephrasing (literal paths, avoiding '>' in quoted text). It cost this run three commands and one rewritten probe script.
- Root cause: the guard scans the raw command text for redirection and in-place-edit tokens without respecting shell quoting, so a '>' or '->' inside a quoted string is parsed as an operator and the following token is taken as a path; that path is then resolved against the checkout root rather than the command's cwd, which is why 'cd /tmp && ...' still reported a checkout target → HYPOTHESIS: not traced to a commit this run. hooks/enforce_bash_scope.py was hardened in 07183c6 'v0.44.0: close six Bash-guard bypasses', and a quoting-unaware scan is the conservative shape that closes bypasses - so this is most likely the deliberate cost of that hardening rather than an accident.
- Class: "Not swept - I did not read enforce_bash_scope.py's full token list this run, so I cannot say how many operators share the quoting-unaware treatment. That sweep is the natural next step."

### VERDICT-F-24 — NEW — Minor/P2

The INDEX row is composed from unmeasured values: its Date cell comes from the local-clock date.today() rather than the run's measured UTC timestamp, and its Delta-tests cell is hardcoded n/a even when the set-diff was measured
- src/verdict_mcp/harness.py index_row(): `return (f"| {date.today().isoformat()} | {state['project']} | ...")`. date.today() reads the local system clock, while every other timestamp in the run is measured in UTC.
- PROVEN live and across a day boundary this run: the INDEX row this run appended reads '| 2026-09-01 |', while state.json's last_run.timestamp_utc is '2026-09-02T04:44:40Z', the rendered report is named 2026-09-02-re-baseline.md, and the runs.jsonl row records 2026-09-02. The host is UTC-7, so 21:55 local is 04:55 the next day UTC - the ledger and the artifact it links to disagree about which day the run happened.
- Same function, second instance: the Delta-tests cell is the literal string 'n/a' - `f"| {counts} | n/a | {bcmm} |"` - regardless of what was measured. This run measured a set-diff of +166 / -0 ids, and the INDEX still says n/a, as do all three prior rows.
- The contract treats both as measured values. agents/verdict.md section 6: 'Timestamps are measured, never remembered. Every date or timestamp you write - state, reports, first_seen, quarantine expiries, age_days arithmetic - comes from running date -u', and the INDEX header the same section prescribes carries a 'Delta tests' column precisely so the count trend is visible.
- Bounded honestly: the authoritative record is runs.jsonl, which is correct, chained and UTC throughout, and state.json is correct. This corrupts the human-facing index only - no age, expiry or re-baseline computation reads the INDEX. That is why it is Minor rather than Major.
- It is not self-correcting: the INDEX is append-only in practice, so every row written from a host west of UTC after local 17:00 carries the wrong date permanently.
- Root cause: index_row() takes the date from the process's local clock at write time instead of from state['last_run']['timestamp_utc'], which is already in hand and already measured; the two disagree whenever the host is not on UTC and the run crosses local midnight in UTC terms → not traced to a commit this run - date.today() is the obvious spelling when the row is thought of as 'today's row' rather than 'this run's row'
- Class: "swept the sibling renderers: history_row() takes timestamp_utc from the state and is correct, and the report renderer uses the measured stamp. index_row is the only writer in harness.py that consults

### VERDICT-F-18 — NEW — Minor/P2

code_drift conflates 'shallow clone' with 'full clone, recorded commit absent' as `unknown`, and every renderer is silent on `unknown` - so a state anchored to a vanished commit reports nothing at all
- RE-VERIFIED at HEAD c386317, unchanged. src/verdict_mcp/state.py:648 code_drift; the absent-commit branch resolves the recorded sha and returns the default `unknown` on failure: `rec = git("rev-parse", "--verify", f"{sha.strip()}^{{commit}}")` then `if rec is None or rec.returncode != 0: return out`, where out was initialised {"status": "unknown", "commits": None, "head": None}.
- The conflation is stated in the docstring itself (state.py:664 region): 'unknown - no git, no recorded sha, or the commit is not in this repo' and 'A commit that is absent (shallow clone, a different repo, a rewritten branch) is unknown, not diverged'.
- Renderers are silent on unknown, confirmed: gate.py:_drift_note handles only 'diverged' (gate.py:203) and 'behind' (gate.py:206) and falls through to `return None`. gate.py:127 and :132 likewise branch only on those two, so unknown never reaches text output, PR comment, or the gating decision.
- PROVEN LIVE THIS RUN: the recorded last_sha 0a9269a301aa970202bf4a21fb35b417f681d4d3 is absent from this full (non-shallow, 104-commit) clone - `git cat-file -t 0a9269a...` returns 'fatal: git cat-file: could not get object info'. It was written on the unpushed branch feat/commit-staleness. code_drift therefore returns unknown here, and every consumer says nothing, while the true situation - the stored verdict describes code this repository cannot see - is exactly what a reader needs told.
- This is the failure mode that forced this run to re-baseline, so its cost is demonstrated rather than hypothetical.
- IN FLIGHT, NOT MERGED: origin/fix/no-gates-and-absent-commit (cc24a9e) is not an ancestor of HEAD.
- Root cause: one sentinel value (`unknown`) carries two very different meanings - 'I cannot see far enough' (shallow) and 'this commit is not in this repository' (absent) - and the renderers, having nothing actionable to say about the first, say nothing about either → deliberate conservatism, documented in the docstring: 'Never raises and never blocks... A false "you are behind" would train people to ignore the line.' The caution is right; the cost is that a genuinely alarming case inherits the silence of a benign one
- Class: "checked the sibling states - 'current', 'behind' and 'diverged' are each rendered, so unknown is the only status with no surface. The same one-sentinel-two-meanings shape does not recur elsewhere in 

### VERDICT-F-16 — RESOLVED — Trivial/P3 — age 2d

The eval rename-desync guard matches the command name with startswith, so a prefix-colliding rename passes the check built to catch renames
- FIXED at HEAD, with exactly the exact-token comparison the finding specified. eval/run_eval.py:160-161 now reads `invoked = fixture["prompt"].split()[0] if fixture["prompt"].split() else ""` then `if invoked != f"/{stem}":`, raising SystemExit with 'command_file {src.name!r} is provisioned as /{stem}, but the prompt invokes {invoked!r} - rename desync'.
- grep -n startswith eval/run_eval.py returns no matches, so the prefix test the finding reported is gone from the file entirely.
- The finding's own proposed discriminator was `prompt.split()[0] == f'/{stem}'`; the shipped fix is that comparison negated. Under it the two counterexamples the finding constructed - '/specification SPEC.md' and '/spectacular X' against stem 'spec' - both now fail the check as intended.
- fix_verified is FALSE: I did not execute run_eval.py against a prefix-colliding fixture. The finding was latent (no live collision among the shipped commands, none being a prefix of another), so there was no failing behaviour to re-inject cheaply.


## Track record

23 findings tracked across this project's history · 8 settled, 15 still undecided.

| Confidence claimed | Held up | Withdrawn | Rate |
|---|---|---|---|
| proven | 5 | 0 | _not yet_ |
| unstated | 3 | 0 | _not yet_ |

*A rate appears once a row has 30 settled outcomes. Settled means fix-verified or regressed (it held up) against withdrawn (it did not); a finding merely resolved is not evidence either way.*

## Release blockers

_None._

## Verified intact

- Suite fully green with no hidden skips: `uv run --group dev python -m pytest tests/` exit 0, summary '543 passed in 50.35s'. 543 collected, 543 passed, 0 skipped, 0 failed, 0 errors - notably zero collection errors, which the agent contract classes as always-Critical.
- Test count moved in the safe direction only: id set-diff over the ledger shows 166 ids added and 0 removed (verified by hand with comm -13/-23 over the sorted sets, because the harness's own reported delta is wrong - see VERDICT-F-20). No test was silently dropped.
- Tamper-evidence gate holds: `python3 eval/fixture_freshness.py` exit 0 in 0.07s, 'OK - pricer-delta.diff still describes the fixture pair (78 lines)'. The answer keys, corpus and fixture delta were neither modified nor regenerated by this run.
- Isolation holds on all three profile conditions: no network/DB/credential imports in tests/ or src/ (grep exit 1, no matches); pyproject.toml:89 pins testpaths = ["tests"]; the intentionally-failing seeded tests under eval/fixtures/pricer stayed out of the collected set.
- The scope guards are live and fail closed: the VERDICT_STRICT bash guard blocked three commands this session and permitted no write to the checkout; every artifact this run produced is inside .qa/. The guard's over-blocking is filed as VERDICT-F-22, but its safety property held without exception.
- The gate's harness enforcement works as designed once a history is chained: the VERDICT-F-12 imitation attack, re-run against the shipped gate with a chained runs.jsonl present, is refused with exit 6.
- Census placeholder leads swept and clean: all 40 'for now', 6 TODO and 6 swallowed-exception hits resolve to either src/verdict_mcp/census.py's own detector pattern strings, their tests in tests/test_census.py, or the intentionally-seeded eval/fixtures answer-key defects. The three real swallowed excepts (census.py:146 ValueError, gate.py:338 AttributeError/OSError, state.py:446 OSError/JSONDecodeError) are each narrow, typed and deliberate. No finding filed.
- Provenance measured, not assumed: 1 of the last 30 commits carries an AI trailer (facts.json code_census.provenance), with the harness's own caveat that absence of trailers is not evidence of human authorship.

## Not tested

- Windows and Python 3.10 CI matrix legs - unreproducible on this macOS host. The cp1252 encoding guards in runner.py/gate.py stay unexercised, as does fixture_freshness's git-diff newline handling under core.autocrlf.
- Agent prompt behaviour via live-model eval (eval/run_eval.py) - costs API calls. agents/verdict.md changed again in this range (it is the product) and remains measured structurally only; behavioural regressions in it are invisible to the unit suite.
- The eval corpus scorer against agents/verdict.md - eval/score.py and the answer keys were not re-derived this run.
- The Action's gate mode as GitHub actually executes it - action.yml was read (VERDICT-F-14 re-checked) but not executed; the Action's `run` mode is forbidden locally by profile.
- Changed-files coverage - no coverage tool is configured in this repo and the profile records no command, so the coverage-delta gate is unmeasurable. Not estimated.
- Mutation testing - mutmut is declared in the dev dependency group but was not run this session (cost); suite quality remains unmeasured.
- The sdist fix (VERDICT-F-11) was verified by reading pyproject.toml's allowlist, not by building and unpacking an sdist as the original finding did.
- Everything below the risk cutoff: src/verdict_mcp/server.py (MCP surface), runner.py, census.py internals, project_key.py, and the eval corpus fixtures were not read this run beyond census leads.

## Fix order

Ordered for dependencies, not severity alone.

1. **VERDICT-F-20** (Major) - the set-diff delta. First because it is a measuring instrument: every later run's test-count gate reports through it, and while it is wrong, a mass deletion looks like a small one. The fix is confined to `harness.py` - carry the true counts alongside the capped sample lists, and render the counts, not `len()` of the samples. Fix this before trusting any subsequent Δ-tests figure, including this run's.

2. **VERDICT-F-20's latent condition, same change** - add a test that constructs a diff larger than the cap. `tests/test_harness.py:99-111` only ever exercise one-element diffs, which is why the truncation and the renderer have never disagreed under test. Without this the fix is unguarded and can silently return.

3. **VERDICT-F-17** (Major) - the unmeasured-suite escape. Second because it is the other instrument defect, and it is what lets a broken profile present as a clean `pass`. Two parts, and both are needed: carry `no_gates` through the `harness.py` merge into the state, then let `validate.py` distinguish 'no gates configured' from 'gates configured but none measured'. Part two is not implementable until part one supplies the fact. Coordinate with the in-flight branch before writing anything.

4. **VERDICT-F-21** (Major) - the chain downgrade. Third rather than first because it is a hardening gap in a control that already works when engaged, not a live hole in a working system. The decision it needs is a policy one (see 'Needs human decision'): what should the gate do when a previously-chained project presents an unchained history? An anchor outside the deletable file is the shape of any real fix.

5. **VERDICT-F-18** (Minor) - split the `unknown` drift status so 'commit absent from this repository' is distinguishable from 'shallow clone', and give the first one a renderer line. Sequenced after the Majors, but note it is the finding that cost *this run* its delta, so its practical impact exceeds its severity. Also in flight on cc24a9e.

6. **VERDICT-F-22** (Minor) - make the bash guard quoting-aware and resolve relative targets against the command's cwd. Before fixing, sweep `enforce_bash_scope.py` for how many operators share the quoting-unaware scan - the fix should address the class, not the three tokens I happened to trip.

7. **VERDICT-F-15** (Minor) - derive the doc sweep from tracked markdown instead of four hand-maintained globs. The sibling test in the same file already derives both sides from disk; copy that shape. This is the second time this finding has been narrowed rather than closed, which is the argument for fixing the class now.

8. **VERDICT-F-13** (Minor) - the five `fixture_freshness` gaps. Last: the gate does its main job, both controls held, and the residue is a tamper-evidence completeness question rather than a live failure.

## Next run focus

- VERDICT-F-23 first: confirm whether the state's project key is still 'verdict-clone' or has been restored to 'verdict'. Until the harness reads the profile's Project-Key header, every run from a differently-named checkout re-keys the committed state and splits the INDEX history.
- VERDICT-F-24: check the INDEX Date cell against state.json's last_run.timestamp_utc. They disagreed by a day this run, and will disagree on any host west of UTC after local 17:00.
- VERDICT-F-20 is the highest-value re-check: after any fix, re-run the 200-id/180-deleted scratch probe and confirm the rendered ledger line reports -180, not -50.
- Suite duration crossed the 10% gate this run: 31.31s -> 52.07s (+66.3%) against 377 -> 543 tests (+166). Per-test cost rose 83.1ms -> 95.9ms (+15.5%), which the added tests do not explain. Re-measure next run on an idle machine before treating it as a trend; if it holds, find the slow module.
- This run writes the first chained row into runs.jsonl (runs 2 and 3 carry no `chain`). Next run, confirm chain_intact is now a live signal here and that VERDICT-F-21's downgrade probe still reproduces.
- VERDICT-F-17 and VERDICT-F-18 have fixes in flight on origin/fix/no-gates-and-absent-commit (cc24a9e, unmerged at this HEAD). Re-judge them once that branch lands rather than re-deriving them.
- VERDICT-F-13: the five fixture_freshness gaps (untracked plant, chmod, symlink swap, deleted tracked file traceback, broken symlink) are unchanged at HEAD and were carried on the previous run's evidence, not re-probed this run. Re-probe or accept.
- The state/ledger desync this run exposed (test-ids.txt advanced to 493 ids under an unrecorded run while state.json stayed at 377) deserves a decision: should verdict-facts write the ledger before finalize commits the run at all?
- agents/verdict.md behavioural coverage - still structural only, now across three releases. Decide whether one eval fixture run per release is affordable.

## Notes

**On the three findings this run was briefed to file verbatim.** Two were real and are filed under the ids given: VERDICT-F-17 and VERDICT-F-18, both re-verified at HEAD, both unchanged, both with fixes unmerged. I did not take them on trust - F-17's early-return is quoted from `validate.py:290-291` as it stands today, and F-18 was confirmed twice over, once by reading and once by this run's own inability to resolve `0a9269a`.

**The third, VERDICT-F-19, I declined to file, and the id is deliberately left unused.** The briefed description - the stale-command-name sweep in `tests/test_commands.py` missing `standards/` and `templates/` - is not a new defect. It is the unresolved remainder of **VERDICT-F-15**, filed 2026-08-30, whose recorded title already reads '...so README-pypi.md, docs/*.md, standards/* and templates/* can carry a dead command name unnoticed'. The guard was widened this range to cover README-pypi.md and docs/, and `standards/` and `templates/` were left out; that is the original finding partially fixed, not a second one. Filing it again would have double-counted one defect under two ids, aged both from zero, and told a reader that a three-day-old known gap was new. I re-reported F-15 with its id verbatim, its evidence updated to show what was fixed and what remains, and left F-19 unminted so it cannot later be confused with the lost run-5 report that used it. If the maintainer disagrees, the merge is cheap; the un-merge would not have been.

**On the six findings an unrecorded run judged resolved by reading.** I re-verified all six at HEAD rather than inheriting that judgment, and it held for five of them - F-10, F-11, F-12, F-14, F-16 - though not always for the reason expected: F-11 was closed by *removing* `/tests` from the sdist allowlist, not by adding the missing trees, which is a different fix with a different trade-off and is recorded as such. F-13 is still open, as that run also found. Following this project's own `lessons.md` entry that 'absence of a fix is not the same claim as a verified fix', I re-ran the actual attack for F-12 and marked it `fix_verified: true`; the other four are marked `fix_verified: false` and say plainly what I did and did not do. Four of five closures therefore rest on reading, which is the weakest of the four evidence grades, and a reader should weigh them accordingly.

**On the guard that blocked me.** `VERDICT_STRICT` refused three of my commands, every one of them read-only, over `>` and `->` inside quoted strings and a `sed` expression parsed as a path. I have filed that as VERDICT-F-22 with all four instances, and I want to be explicit that the guard was *correct in direction* every time: it failed closed, it let nothing unsafe through, and the cost was three rephrased commands. I worked around it by using literal paths and avoiding the trigger characters, never by disabling it. I also wrote every QA artifact through the `Write` tool rather than a bash heredoc, so the `verdict-validate` PostToolUse hook fired on the state write as the contract intends - a heredoc would have routed around the check that is supposed to bind me.

**Verified intact.** Recorded in `verified_intact` and repeated here because confirmation is a deliverable: the suite is fully green (543 passed, exit 0, no skips, no xfails, no collection errors); the tamper-evidence gate passes and still reproduces the fixture pair; the isolation check passes on all three profile conditions; the seeded-defect fixtures remain uncollected by the project suite; and every census placeholder lead resolved to either the detector's own pattern strings or the intentionally-seeded eval fixtures - I checked them and filed nothing, rather than manufacturing a finding from a count.

**Two findings came out of my own pre-handoff check, after the first finalize.** Verifying the artifacts I had just written - which the contract requires as commands, not from memory - showed the INDEX row dated 2026-09-01 against a state timestamp of 2026-09-02, and the state's `project` field changed from `verdict` to `verdict-clone`. Both are real defects in the harness, both are filed (VERDICT-F-23, VERDICT-F-24), and both were live in the artifacts of this very run. I re-ran the run through the project's documented correction path rather than leaving them unrecorded: restore `state.json.prev`, re-finalize, which stamps `revision: 1` on the second runs.jsonl row so the corrected row outranks the one it supersedes without editing an append-only ledger. The uncorrected first state is kept at `.qa/state.json.run4-uncorrected` for audit, and I removed the duplicate INDEX row the second finalize appended.

**What the correction could NOT fix, and I want this stated plainly:** the `project` field still reads `verdict-clone` in the corrected state. That value is derived by the harness from the checkout's directory basename on every run; re-finalizing recomputes the same wrong value. Fixing it needs the code fix in VERDICT-F-23, or a checkout directory named `verdict`. So this run leaves the committed team-mode state carrying an identity that disagrees with its own profile header and with its three predecessor rows in the INDEX. A maintainer merging this `.qa/` should know that before committing it.

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
