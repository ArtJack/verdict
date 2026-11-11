# QA report — verdict · run 18 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `863c6232a296463a4bdd53bd39d8c563a67fd3d7..97e3da38880f07ea31464e53d0cb878f7f20e4bd` · 33 files changed, 4122 insertions(+), 5102 deletions(-)
- Branch: `qa/run-18` · measured 2026-11-11T20:22:03Z
- Harness: verdict-qa-mcp 0.93.1 · prompt 1bd07f7fdc6a · `/Users/artjack/Projects/verdict/.claude/worktrees/wizardly-rubin-319a27/src/verdict_mcp/harness.py`
- Judge: verdict-local · model `local:chat-120b` · 21 call(s), 21724 token(s) · 1 question(s) unanswered · no Claude tokens spent
- Evidence drift: 4 of 10 anchored open findings cite code that moved or changed since the evidence was written (VERDICT-F-82, VERDICT-F-84, VERDICT-F-85, VERDICT-F-74)
- Isolation check: **pass** — measured before the gates: no plaintext .env file at the checkout root. The profile's own isolation steps were not executed: this engine runs the profile's gates and reads code, and writes nothing outside the QA root

verdict-local: 15 function(s) in 1 file(s) read one at a time by chat-120b, each in isolation, over the range `863c6232a296463a4bdd53bd39d8c563a67fd3d7..97e3da38880f07ea31464e53d0cb878f7f20e4bd`. The harness measured the repository; the model answered bounded questions about single functions.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 318.95s | 3021 passed, 1 skipped in 318.44s (0:05:18) |
| `fixture_freshness` | pass | 0 | 0.08s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 3021, skipped 1, collected 3022
Test-id ledger: 3022 ids · +5 / −0 (set-diff, not summary arithmetic)
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable
  - 10 open finding(s) cite no test id, so the harness cannot fix-verify them
Diff coverage: 35/42 changed lines executed (83%) across 1 file(s); 5 test(s) touch the diff
  - production 0/0 · test code 35/42 (83%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - tests/test_ci_surfaces.py: unexercised lines 55, 58, 75, 85, 94, 103, 114

## Risks

Every finding read here is a `hypothesis` unless a counterfactual proved it. This mode cannot see a defect that spans two functions, and it reads the suite only where the range touched it.

## Findings — REGRESSED first (10 open of 11 tracked · 1 accepted)

### VERDICT-F-21 — ACCEPTED — Major/P2 — age 4d

The run-history chain's anti-fabrication signal can still be shed by deleting data, and the gate then exits 0: 0.66.0 moved the ratchet into outcomes.json, but the anchor is itself unauthenticated, so removing one JSON key restores `unchained` with the whole track record intact
- Re-reported open per the contract; the fold to `accepted` is verdict-finalize's to write, never the tester's. .qa/accepted.json records it accepted by ArtJack on 2026-09-05 citing 'DECISIONS.md 2026-09-02'.
- Unchanged as a defect and untouched by this range: `git log 0892869..4dc006a --oneline -- src/verdict_mcp/gate.py src/verdict_mcp/state.py` shows gate.py was not touched at all and state.py only for the accepted-risk fold, not for authenticating the anchor.
- Not re-measured this run.
- _Accepted risk — 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to._

### VERDICT-F-74 — STILL_OPEN — Minor/P2 — age 67d

The `trigger-separated-from-cause` eval row scores the presence of the single word 'trigger', so a report that never separates trigger from cause earns the point - the same shape run 12 filed against the bytecode row
- STILL OPEN at HEAD (fresh evidence, this range changed eval/expected-cause.json but not this row's mechanism). eval/expected-cause.json:43-49 the row is `{"key":"trigger-separated-from-cause","type":"report_contains","terms_all":["trigger"]}` — a single keyword.
- eval/score.py:371-387 scores report_contains by plain substring: `missing = [t for t in terms if t.lower() not in lowered]`, point if none missing. With terms_all == ['trigger'], any report containing the word 'trigger' anywhere earns the point without separating trigger from cause.
- CHANGELOG 0.79.0 still records this as owed ('F-74 ... is scorer work owed to the eval'); the eval corpus was not run this run (no live API), so this is verified by reading the key + scorer, not by scoring a report.
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: eval/expected-cause.json:43 (now line 46), eval/score.py:371 (now line 391)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: the row asserts presence of one keyword rather than the discipline (a report that names a trigger without distinguishing it from the cause still scores). Scorer work owed.
- Class: {"pattern": "single-keyword report_contains row scores vocabulary not discipline", "sites": ["eval/expected-cause.json:43-49 \u2014 the only single-keyword report_contains row across the seven answer 

### VERDICT-F-80 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer/test_pricer.py:18 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-81 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer_rev_b/test_pricer.py:17 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-82 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: "not a git checkout: the directory reads the repository, so this needs one"
- tests/test_directory_policy.py:68 — skip marker with reason '"not a git checkout: the directory reads the repository, so this needs one"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Exercised and green: `test_directory_policy.test_no_shipped_file_carries_a_key_shaped_value`, `test_directory_policy.test_no_shipped_file_is_too_large_for_the_directory_to_read` — these run the cited lines and do not fail on the defect; the assertion to review, and where a regression test belongs
- Cited code moved since the evidence was written: tests/test_directory_policy.py:68 (now line 71)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-83 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_hooks.py:195 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- tests/test_hooks.py:219 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-84 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar
- tests/test_hooks.py:1246 — skip marker with reason '"no GNU tar here (macOS ships bsdtar'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1246 (now line 1279)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-85 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar, which has no --remove-files
- tests/test_hooks.py:1306 — skip marker with reason '"no GNU tar here (macOS ships bsdtar, which has no --remove-files'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1306 (now line 1339)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-86 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: "needs a POSIX bash to measure against"
- tests/test_hooks_0903.py:1083 — skip marker with reason '"needs a POSIX bash to measure against"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-87 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: f"no {tool} here"
- tests/test_hooks_0903.py:1086 — skip marker with reason 'f"no {tool} here"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-88 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 27d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_mcp_tools.py:324 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode


## Accepted risks (1)

_The maintainer's decision, recorded with `verdict-accept`, never the tester's: each is a real defect whose fix was declined, with the reason and where the decision is written down. Out of the open counts and the release blockers; not out of sight._

- **VERDICT-F-21** (Major/P2, age 4d) — accepted 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to.


## Track record

87 findings tracked across this project's history · 60 settled, 27 still undecided.

| Confidence claimed | Held up | of those, measured | Withdrawn | Rate |
|---|---|---|---|---|
| proven | 54 | 0 | 0 | 100% |
| probable | 3 | 0 | 0 | _not yet_ |
| unstated | 3 | 0 | 0 | _not yet_ |

*A rate appears once a row has 30 settled outcomes. Settled means fix-verified or regressed (it held up) against withdrawn (it did not); a resolution nobody checked at all settles nothing.*

*`held up` covers two things and they are not equal: a re-injection the harness measured, and one the tester asserted where no measurement contradicts it. The `measured` column is the first kind. Read them apart.*

*22 of those confirmations were settled before `outcome_basis` was recorded and are neither kind. They are counted in `held up` and in no other column, because calling them the tester's word would be a claim of its own.*

## Release blockers

_None._

## Verified intact

- The full suite is green at HEAD: `uv run --group dev python -m pytest tests/` -> 1172 passed in 138.99s (facts.json gates.suite, exit 0). Test count rose 888->1172 (+284; id set-diff +293/-9, the 9 removals are renamed/renumbered parametrizations, not feature loss).
- The fixture-freshness gate holds: python3 eval/fixture_freshness.py -> OK, pricer-delta.diff still describes the fixture pair (facts.json gates.fixture_freshness, exit 0).
- The bash guard is armed and correctly scoped at HEAD: DENIES `git commit -am wip` / `git stash` / `git reset --hard HEAD` and ALLOWS `cat README.md` and a genuine `git commit --dry-run` (scratchpad/probe_f75.py control rows).
- The corrected §3 instrument control (F-58's fix) is operable: in the F-60 re-injection I restored clean source, swept cache, re-ran, and the suite passed (8/8) — the control direction that can actually fail on a stale instrument (scratchpad/reinject_f60.sh step 3).
- The suite makes no live network/DB/credential call despite the new verdict-local HTTP client: tests inject FakeModel/Flaky and the run refuses without an endpoint (test_small.py:74,143,166).

## Needs human decision (3 parked)

- **VERDICT-Q-1** (asked run 15, 59d ago · about VERDICT-F-74) — VERDICT-F-74 (Minor): fix the single-keyword `trigger-separated-from-cause` scorer row, or record its acceptance with verdict-accept? It has been 'scorer work owed' since 0.79.0 and is the only single-keyword report_contains row across the seven answer keys.
- **VERDICT-Q-2** (asked run 15, 59d ago) — The re-baseline surface (~2,300 new/changed lines across src/verdict_mcp/small.py +1089, questions.py +326, anchors.py +169, clock.py +72, filed.py +99, reports.py +132, runner.py +470, harness.py +903, validate.py +314, plus eval/swebench.py +1311) was NOT audited this scoped run (caller scope was F-75 + run-14 next_run_focus). Schedule a dedicated baseline run over these modules before the next release that touches them?
- **VERDICT-Q-3** (asked run 15, 59d ago) — The profile's isolation check part (1) grep now matches the verdict-local local-model client (small.py) and will always 'fail' while that feature exists. Refine it to exclude the declared local-model client, or scope it to the test-execution path only?

_Answer with `verdict-answer verdict <Q-id> --answer "…"`; the next run reads the decision instead of asking again._

## Reading map (82 production modules, 88% covered overall)

| Module | Covered | Statements | Open findings | Last cited |
|---|---|---|---|---|
| `eval/backfill/faithful.py` | 0% | None | 0 | never |
| `eval/corpus/pricer-baseline-sonnet-20260828/probe.py` | 0% | None | 0 | never |
| `eval/fixtures/liar/qstats.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer/pricer.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer_clean/pricer.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer_clean/probe.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer_rev_b/pricer.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/invoice.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/money.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/rates.py` | 0% | None | 0 | never |

Never cited by any finding, least covered first: `eval/backfill/faithful.py`, `eval/corpus/pricer-baseline-sonnet-20260828/probe.py`, `eval/fixtures/liar/qstats.py`, `eval/fixtures/pricer/pricer.py`, `eval/fixtures/pricer_clean/pricer.py`, `eval/fixtures/pricer_clean/probe.py`, `eval/fixtures/pricer_rev_b/pricer.py`, `eval/fixtures/rates/commits/01-initial/invoice.py`, `eval/fixtures/rates/commits/01-initial/money.py`, `eval/fixtures/rates/commits/01-initial/rates.py`

## Not tested

- no agent ran: 17 bounded question(s) went to chat-120b — no exploratory charter, no archaeology, no adversarial reading of the suite
- the commit history: no origin was traced, and no `git log -S` was run
- 10 of 10 prior open finding(s) were carried unread, and 0 re-filed because the code they cite changed and no model looked at the change
- 1 file(s) and 15 function(s) were read; nothing else in the repository was
- claims the counterfactual could not reach — a probe that would not run leaves its finding a hypothesis, and an unproven severity is held at Minor for a reading and at Major for a failing test the model classified
- nothing outside the checkout was read — no database, no MCP tools, no production numbers — so a standing blocker that quotes one was NOT re-read
- 1 question(s) the model did not answer
- 5 reading(s) this engine could not prove were listed as leads in the report, not filed — a lead is a question for a run that can judge it, not a finding

## Next run focus

- needs a model run — unexercised_changed_lines: 7
- lead, unproven: tests/test_ci_surfaces.py:34 `test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with` — test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with may assert something incidental: It asserts 
- lead, unproven: tests/test_ci_surfaces.py:42 `test_the_eval_job_cannot_report_green_without_a_key` — test_the_eval_job_cannot_report_green_without_a_key may assert something incidental: It asserts exact substrings ('shell
- lead, unproven: tests/test_ci_surfaces.py:90 `test_no_workflow_grants_write_at_the_top` — test_no_workflow_grants_write_at_the_top may assert something incidental: The test relies on a strict regex that assumes
- lead, unproven: tests/test_ci_surfaces.py:111 `test_nothing_that_can_publish_runs_off_a_tag` — test_nothing_that_can_publish_runs_off_a_tag may assert something incidental: asserts the exact string "if: startsWith(g
- lead, unproven: tests/test_ci_surfaces.py:124 `test_each_major_held_back_is_ignored_from_that_major_up` — test_each_major_held_back_is_ignored_from_that_major_up may assert something incidental: relies on exact string formatti
- needs a model run — diff_over_limit: the range is larger than the caps this engine runs under; part of it was never read
- needs a model run — unexercised_changed_lines: 1332
- lead, unproven: .github/directory_branch.py:95 `plugin_tree` — Extra NUL sent to git update-index creates invalid empty entry when no files are kept
- lead, unproven: eval/backfill/faithful.py:38 `finding_of` — ID type mismatch causes StopIteration when finding ID is integer
- lead, unproven: eval/backfill/faithful.py:76 `main` — `--only` empty list ignored due to falsy check, causing all cases to be processed
- lead, unproven: eval/recall/build_cases.py:53 `main` — Missing '=' validation lets malformed run specs create cases with empty root paths
- lead, unproven: eval/recall/packet_recall.py:42 `_head` — Missing git error handling in _head leads to silent failure
- needs a model run — unexercised_changed_lines: 1875
- lead, unproven: eval/external.py:152 `sh` — sh() fails to run string commands because it doesn't invoke a shell or split the command
- lead, unproven: eval/external.py:230 `checkout_at` — Ancestor tags are not deleted, contradicting docstring that tags must be physically absent
- lead, unproven: eval/external.py:262 `container` — Container function passes whole command string as single argv entry, breaking commands with spaces
- lead, unproven: eval/external.py:280 `run_withheld` — Combined '-rA' flag and file list into one argument breaks pytest invocation
- lead, unproven: eval/external.py:458 `transcripts_of` — transcripts_of returns [] for falsy session_id with since=None, omitting existing transcripts
- Baseline the re-baseline surface: a dedicated run over src/verdict_mcp/small.py (verdict-local), questions.py, anchors.py, clock.py, filed.py, reports.py, and eval/swebench.py — none has had an independent QA pass. Weight small.py (the local-model client with a real urlopen and env-file reading) and questions.py (a new second-pen control surface) first.

## Notes

No Claude tokens were spent on this run. The verdict cannot improve on its own: a previous `fail` stays `fail`, and a previous `blocked` stays `blocked`, until something with judgment looks at it.

**Leads — read by a small model, not proven, not filed (5).** Each is a question for a run that can judge it; none is on the record.
- `tests/test_ci_surfaces.py:34` `test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with` — test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with may assert something incidental: It asserts the exact presence of "--python 3.9" and specific test file names in a CI YAML s (read as Minor; an opinion about a passing test)
- `tests/test_ci_surfaces.py:42` `test_the_eval_job_cannot_report_green_without_a_key` — test_the_eval_job_cannot_report_green_without_a_key may assert something incidental: It asserts exact substrings ('shell: bash' before 'run: |' and 'ANTHROPIC_API_KEY is not set') which depend on spec (read as Minor; an opinion about a passing test)
- `tests/test_ci_surfaces.py:90` `test_no_workflow_grants_write_at_the_top` — test_no_workflow_grants_write_at_the_top may assert something incidental: The test relies on a strict regex that assumes a specific indentation and format for the top‑level permissions block, so harml (read as Minor; an opinion about a passing test)
- `tests/test_ci_surfaces.py:111` `test_nothing_that_can_publish_runs_off_a_tag` — test_nothing_that_can_publish_runs_off_a_tag may assert something incidental: asserts the exact string "if: startsWith(github.ref, 'refs/tags/v')" in the job definition, which depends on specific form (read as Minor; an opinion about a passing test)
- `tests/test_ci_surfaces.py:124` `test_each_major_held_back_is_ignored_from_that_major_up` — test_each_major_held_back_is_ignored_from_that_major_up may assert something incidental: relies on exact string formatting of pyproject.toml and dependabot.yml via regex, so harmless changes break the (read as Minor; an opinion about a passing test)

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
