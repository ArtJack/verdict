# QA report — verdict · run 20 (delta)

**VERDICT: pass with risks**

## Scope

- Range: `79c603b..88f54dc` · 22 files changed, 7867 insertions(+), 431 deletions(-)
- Branch: `qa/run-20` · measured 2026-11-27T06:56:24Z
- Harness: verdict-qa-mcp 0.94.0 · prompt 1bd07f7fdc6a · `/Users/artjack/.claude/verdict-ops/verdict-pinned/src/verdict_mcp/harness.py`
- Judge: verdict-local · model `local:chat-120b` · 54 call(s), 80717 token(s) · 2 question(s) unanswered · no Claude tokens spent
- Evidence drift: 4 of 10 anchored open findings cite code that moved or changed since the evidence was written (VERDICT-F-82, VERDICT-F-84, VERDICT-F-85, VERDICT-F-74)
- Isolation check: **pass** — measured before the gates: no plaintext .env file at the checkout root. The profile's own isolation steps were not executed: this engine runs the profile's gates and reads code, and writes nothing outside the QA root

verdict-local: 24 function(s) in 6 file(s) read one at a time by chat-120b, each in isolation, over the range `79c603b..88f54dc`. The harness measured the repository; the model answered bounded questions about single functions.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 355.04s | 3563 passed, 23 skipped in 350.23s (0:05:50) |
| `fixture_freshness` | pass | 0 | 0.09s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 3563, skipped 23, collected 3586
Test-id ledger: 3586 ids · +32 / −0 (set-diff, not summary arithmetic)
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable
  - 10 open finding(s) cite no test id, so the harness cannot fix-verify them
Diff coverage: 401/467 changed lines executed (86%) across 10 file(s); 50 test(s) touch the diff
  - production 231/246 (94%) · test code 170/221 (77%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - 61 of them only in a subprocess the suite spawned — measured, but no test to name
  - src/verdict_mcp/local_refuted.py: unexercised lines 41-42, 171, 173, 207-208, 241, 345-346
  - src/verdict_mcp/sandbox.py: unexercised lines 580, 582, 586-588
  - src/verdict_mcp/small.py: unexercised lines 121
  - tests/test_backfill.py: unexercised lines 11, 19, 195-196
  - tests/test_local_refuted.py: unexercised lines 9-12, 14-17, 19, 21-22, 24, 47, 50, 62, 68, 78, 84, 95, 108, 123, 144, 201, 218, 227, 230, 248, 271, 273, 277, 299
  - tests/test_replay.py: unexercised lines 377, 379, 676, 680
  - tests/test_sandbox.py: unexercised lines 434-435, 438-439, 442, 444-445, 448-450, 464, 476 — functions never entered: test_sandbox_exec_says_it_could_not_start_a_program_in_one_line_and_exits_71

## Risks

Every finding read here is a `hypothesis` unless a counterfactual proved it. This mode cannot see a defect that spans two functions, and it reads the suite only where the range touched it.

## Findings — REGRESSED first (10 open of 11 tracked · 1 accepted)

### VERDICT-F-21 — ACCEPTED — Major/P2 — age 4d

The run-history chain's anti-fabrication signal can still be shed by deleting data, and the gate then exits 0: 0.66.0 moved the ratchet into outcomes.json, but the anchor is itself unauthenticated, so removing one JSON key restores `unchained` with the whole track record intact
- Re-reported open per the contract; the fold to `accepted` is verdict-finalize's to write, never the tester's. .qa/accepted.json records it accepted by ArtJack on 2026-09-05 citing 'DECISIONS.md 2026-09-02'.
- Unchanged as a defect and untouched by this range: `git log 0892869..4dc006a --oneline -- src/verdict_mcp/gate.py src/verdict_mcp/state.py` shows gate.py was not touched at all and state.py only for the accepted-risk fold, not for authenticating the anchor.
- Not re-measured this run.
- _Accepted risk — 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to._

### VERDICT-F-74 — STILL_OPEN — Minor/P2 — age 83d

The `trigger-separated-from-cause` eval row scores the presence of the single word 'trigger', so a report that never separates trigger from cause earns the point - the same shape run 12 filed against the bytecode row
- STILL OPEN at HEAD (fresh evidence, this range changed eval/expected-cause.json but not this row's mechanism). eval/expected-cause.json:43-49 the row is `{"key":"trigger-separated-from-cause","type":"report_contains","terms_all":["trigger"]}` — a single keyword.
- eval/score.py:371-387 scores report_contains by plain substring: `missing = [t for t in terms if t.lower() not in lowered]`, point if none missing. With terms_all == ['trigger'], any report containing the word 'trigger' anywhere earns the point without separating trigger from cause.
- CHANGELOG 0.79.0 still records this as owed ('F-74 ... is scorer work owed to the eval'); the eval corpus was not run this run (no live API), so this is verified by reading the key + scorer, not by scoring a report.
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: eval/expected-cause.json:43 (now line 46), eval/score.py:371 (now line 391)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: the row asserts presence of one keyword rather than the discipline (a report that names a trigger without distinguishing it from the cause still scores). Scorer work owed.
- Class: {"pattern": "single-keyword report_contains row scores vocabulary not discipline", "sites": ["eval/expected-cause.json:43-49 \u2014 the only single-keyword report_contains row across the seven answer 

### VERDICT-F-80 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer/test_pricer.py:18 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-81 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer_rev_b/test_pricer.py:17 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-82 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "not a git checkout: the directory reads the repository, so this needs one"
- tests/test_directory_policy.py:68 — skip marker with reason '"not a git checkout: the directory reads the repository, so this needs one"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Exercised and green: `test_directory_policy.test_no_shipped_file_carries_a_key_shaped_value`, `test_directory_policy.test_no_shipped_file_is_too_large_for_the_directory_to_read` — these run the cited lines and do not fail on the defect; the assertion to review, and where a regression test belongs
- Cited code moved since the evidence was written: tests/test_directory_policy.py:68 (now line 71)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-83 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_hooks.py:195 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- tests/test_hooks.py:219 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-84 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar
- tests/test_hooks.py:1246 — skip marker with reason '"no GNU tar here (macOS ships bsdtar'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1246 (now line 1279)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-85 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar, which has no --remove-files
- tests/test_hooks.py:1306 — skip marker with reason '"no GNU tar here (macOS ships bsdtar, which has no --remove-files'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1306 (now line 1339)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-86 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "needs a POSIX bash to measure against"
- tests/test_hooks_0903.py:1083 — skip marker with reason '"needs a POSIX bash to measure against"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-87 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: f"no {tool} here"
- tests/test_hooks_0903.py:1086 — skip marker with reason 'f"no {tool} here"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-88 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 43d

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

- **VERDICT-Q-1** (asked run 15, 75d ago · about VERDICT-F-74) — VERDICT-F-74 (Minor): fix the single-keyword `trigger-separated-from-cause` scorer row, or record its acceptance with verdict-accept? It has been 'scorer work owed' since 0.79.0 and is the only single-keyword report_contains row across the seven answer keys.
- **VERDICT-Q-2** (asked run 15, 75d ago) — The re-baseline surface (~2,300 new/changed lines across src/verdict_mcp/small.py +1089, questions.py +326, anchors.py +169, clock.py +72, filed.py +99, reports.py +132, runner.py +470, harness.py +903, validate.py +314, plus eval/swebench.py +1311) was NOT audited this scoped run (caller scope was F-75 + run-14 next_run_focus). Schedule a dedicated baseline run over these modules before the next release that touches them?
- **VERDICT-Q-3** (asked run 15, 75d ago) — The profile's isolation check part (1) grep now matches the verdict-local local-model client (small.py) and will always 'fail' while that feature exists. Refine it to exclude the declared local-model client, or scope it to the test-execution path only?

_Answer with `verdict-answer verdict <Q-id> --answer "…"`; the next run reads the decision instead of asking again._

## Reading map (137 production modules, 85% covered overall)

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

- no agent ran: 43 bounded question(s) went to chat-120b — no exploratory charter, no archaeology, no adversarial reading of the suite
- the commit history: no origin was traced, and no `git log -S` was run
- 10 of 10 prior open finding(s) were carried unread, and 0 re-filed because the code they cite changed and no model looked at the change
- 6 file(s) and 24 function(s) were read; nothing else in the repository was
- claims the counterfactual could not reach — a probe that would not run leaves its finding a hypothesis, and an unproven severity is held at Minor for a reading and at Major for a failing test the model classified
- nothing outside the checkout was read — no database, no MCP tools, no production numbers — so a standing blocker that quotes one was NOT re-read
- 2 question(s) the model did not answer
- 125 candidate function(s) were never asked about: the cap of 24 function(s) was reached
- changed in the range and read by no question here, because none of it is program source: 6 configuration or data file(s), 5 document(s), 1 other file(s)
- 12 reading(s) this engine could not prove were listed as leads in the report, not filed — a lead is a question for a run that can judge it, not a finding

## Next run focus

- needs a model run — diff_over_limit: the range is larger than the caps this engine runs under; part of it was never read
- needs a model run — unexercised_changed_lines: 66
- lead, unproven: src/verdict_mcp/sandbox.py:540 `run` — run() always forces capture_output=True, ignoring caller's capture_output setting
- lead, unproven: src/verdict_mcp/small.py:327 `mint` — Validator uses wrong directory path, mismatching write target
- lead, unproven: tests/test_local_refuted.py:58 `checkout` — checkout fails on empty file set due to missing --allow-empty flag
- lead, unproven: tests/test_local_refuted.py:62 `claim` — Hard‑coded line number always 19 misleads callers
- lead, unproven: tests/test_local_refuted.py:68 `test_a_null_claim_on_a_member_declared_non_null_is_set_aside_with_its_declaration` — Refuter reports the declaration line instead of the claim line, misleading the location of the issue
- needs a model run — unexercised_changed_lines: 2273
- lead, unproven: scripts/check_structure.py:78 `git` — git() discards stdout on non‑zero exit when check=False
- lead, unproven: scripts/check_structure.py:102 `is_shared_fake` — Off‑by‑one in is_shared_fake: directory itself not checked against SHARED_FAKE_DIRS
- lead, unproven: scripts/check_structure.py:185 `silent` — silent() misclassifies bare Name expression statements as non‑silent
- lead, unproven: src/verdict_mcp/accept.py:210 `main` — Missing validation of --reason when using --revoke allows empty revocation reason
- lead, unproven: src/verdict_mcp/backfill.py:113 `_tree` — Silent failure of _tree returns empty list, hiding git errors
- needs a model run — unexercised_changed_lines: 7
- lead, unproven: tests/test_ci_surfaces.py:34 `test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with` — test_ci_runs_the_hook_tests_on_the_interpreter_a_stock_mac_starts_them_with may assert something incidental: It asserts 
- lead, unproven: tests/test_ci_surfaces.py:42 `test_the_eval_job_cannot_report_green_without_a_key` — test_the_eval_job_cannot_report_green_without_a_key may assert something incidental: It asserts exact substrings ('shell
- lead, unproven: tests/test_ci_surfaces.py:90 `test_no_workflow_grants_write_at_the_top` — test_no_workflow_grants_write_at_the_top may assert something incidental: The test relies on a strict regex that assumes
- lead, unproven: tests/test_ci_surfaces.py:111 `test_nothing_that_can_publish_runs_off_a_tag` — test_nothing_that_can_publish_runs_off_a_tag may assert something incidental: asserts the exact string "if: startsWith(g
- lead, unproven: tests/test_ci_surfaces.py:124 `test_each_major_held_back_is_ignored_from_that_major_up` — test_each_major_held_back_is_ignored_from_that_major_up may assert something incidental: relies on exact string formatti
- needs a model run — unexercised_changed_lines: 1332

## Notes

No Claude tokens were spent on this run. The verdict cannot improve on its own: a previous `fail` stays `fail`, and a previous `blocked` stays `blocked`, until something with judgment looks at it.

**Leads — read by a small model, not proven, not filed (12).** Each is a question for a run that can judge it; none is on the record.
- `src/verdict_mcp/sandbox.py:540` `run` — run() always forces capture_output=True, ignoring caller's capture_output setting (read as Major; probe failed on the original: FileNotFoundError: [Errno 2] No such file or directory: 'python')
- `src/verdict_mcp/small.py:327` `mint` — Validator uses wrong directory path, mismatching write target (read as Major; the model did not answer with JSON)
- `tests/test_local_refuted.py:58` `checkout` — checkout fails on empty file set due to missing --allow-empty flag (read as Blocker; probe_unsafe: argument 1 is not a literal (m.Path('/tmp/checkout_empty')))
- `tests/test_local_refuted.py:62` `claim` — Hard‑coded line number always 19 misleads callers (read as Minor; fix_unsafe: introduces `inspect`, a name the function never uses)
- `tests/test_local_refuted.py:68` `test_a_null_claim_on_a_member_declared_non_null_is_set_aside_with_its_declaration` — Refuter reports the declaration line instead of the claim line, misleading the location of the issue (read as Minor; the line to flip (112) is outside test_a_null_claim_on_a_member_declared_non_null_is_set_aside_with_its_declaration)
- `tests/test_local_refuted.py:78` `test_the_null_rule_needs_the_projects_own_nullable_setting` — Missing <Nullable> setting treated as enabled, causing false null reference warnings (read as Major; the line to flip (143) is outside test_the_null_rule_needs_the_projects_own_nullable_setting)
- `tests/test_local_refuted.py:88` `test_only_a_non_null_type_with_a_value_counts_as_declared_non_null` — Refuter returns empty dict instead of None for non‑null declarations (read as Blocker; the proof budget was spent)
- `tests/test_local_refuted.py:117` `test_a_name_declared_nullable_anywhere_keeps_the_claim_unless_the_receiver_is_typed` — Off‑by‑one line number reported for Ticket.AssignedTo declaration (read as Minor; the proof budget was spent)
- `tests/test_local_refuted.py:201` `test_claims_a_declaration_does_not_answer_are_left_alone` — Refuter misclassifies any claim with the word "null" as a null‑claim, causing false refutation failures (read as Blocker; the proof budget was spent)
- `tests/test_local_refuted.py:222` `test_null_claims_in_other_languages_are_not_touched` — Refuter.check returns empty list instead of None for non‑C# languages (read as Minor; the proof budget was spent)
- `tests/test_local_refuted.py:259` `test_a_gate_compiles_the_folder_or_the_project_it_names` — compiling_gate fails to match Windows-style backslash paths (read as Major; the proof budget was spent)
- `tests/test_local_refuted.py:299` `test_the_reports_list_of_set_aside_claims_is_capped_and_says_so` — set_aside_text caps list at 24 items instead of 25, yielding wrong line count and truncation message (read as Minor; the proof budget was spent)

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
