# QA report — verdict · run 17 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `1e8fd9d7edd5a4c2c9c32906ff97ae37f8b83038..863c6232a296463a4bdd53bd39d8c563a67fd3d7` · 101 files changed, 20051 insertions(+), 3042 deletions(-)
- Branch: `qa/run-17` · measured 2026-10-30T08:04:17Z
- Harness: verdict-qa-mcp 0.93.0 · prompt 1bd07f7fdc6a · `/Users/artjack/Projects/verdict.worktrees/qa-run-17/src/verdict_mcp/harness.py`
- Judge: verdict-local · model `local:chat-120b` · 52 call(s), 60542 token(s) · 4 question(s) unanswered · no Claude tokens spent
- Evidence drift: 4 of 10 anchored open findings cite code that moved or changed since the evidence was written (VERDICT-F-82, VERDICT-F-84, VERDICT-F-85, VERDICT-F-74)
- Isolation check: **pass** — measured before the gates: no plaintext .env file at the checkout root. The profile's own isolation steps were not executed: this engine runs the profile's gates and reads code, and writes nothing outside the QA root

verdict-local: 24 function(s) in 6 file(s) read one at a time by chat-120b, each in isolation, over the range `1e8fd9d7edd5a4c2c9c32906ff97ae37f8b83038..863c6232a296463a4bdd53bd39d8c563a67fd3d7`. The harness measured the repository; the model answered bounded questions about single functions.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 290.62s | 3016 passed, 1 skipped in 290.20s (0:04:50) |
| `fixture_freshness` | pass | 0 | 0.08s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 3016, skipped 1, collected 3017
Test-id ledger: 3017 ids · +324 / −2 (set-diff, not summary arithmetic) — id lists truncated to 50 each
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable
  - 10 open finding(s) cite no test id, so the harness cannot fix-verify them
Diff coverage: 5181/6513 changed lines executed (80%) across 57 file(s); 50 test(s) touch the diff
  - production 2963/3782 (78%) · test code 2218/2731 (81%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - 344 of them only in a subprocess the suite spawned — measured, but no test to name
  - .github/directory_branch.py: unexercised lines 90, 134-136
  - eval/backfill/faithful.py: unexercised lines 1-103 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/recall/build_cases.py: unexercised lines 1-63 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/recall/packet_recall.py: unexercised lines 1-189 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/recall/plain_arm.py: unexercised lines 26, 28-35, 37-42, 44-46, 48, 81, 86, 89, 101, 106-107, 111, 118, 128, 135-136, 139, 142, 150-151, 157, 176, 186-187, 196, 201, 210, 214, 216, 220, 232, 236, 241, 243-247, 249, 251, 254, 273-274, 285-292, 295-296, 298-308, 310-316, 321-323, 325, 328-329 — functions never entered: replay_all
  - eval/recall/score_recall.py: unexercised lines 25, 27-32, 34-35, 38, 43, 54, 64, 78, 94, 96, 99, 101, 111, 113, 119, 123-124, 130, 138, 144-145, 153, 178, 192, 208-209, 218, 226-227 — functions never entered: located
  - hooks/enforce_bash_scope.py: unexercised lines 871, 882
  - hooks/enforce_run_contract.py: unexercised lines 131, 136-138
  - src/verdict_mcp/backfill.py: unexercised lines 19, 21-28, 30-33, 36-42, 45-46, 48-56, 59, 61, 64, 91, 102, 108, 114, 124, 141-142, 145, 154, 158, 163-164, 177, 182, 196, 202, 205, 208, 214-220, 225-226, 234-235, 242, 252-255, 262, 275, 282-283, 286, 303, 328, 331, 335-336, 349, 357, 362, 366, 376, 380, 382, 413, 423-424, 427, 430, 439, 442, 451-452, 459, 506, 518-519, 538-539, 542, 546-547, 564, 572-573, 577-578, 587, 589, 595-596, 617-618
  - src/verdict_mcp/check.py: unexercised lines 24, 26-32, 34-44, 46-50, 52, 64-66, 69, 74, 83, 86-87, 100, 107, 111, 130, 133-134, 139, 143, 151, 161, 168-169, 177, 181, 196, 200-201, 213-214, 218-219, 223-224, 236, 242-246, 268-269
  - src/verdict_mcp/dupes.py: unexercised lines 32, 155, 157-167, 209-210, 224-225, 236-237, 251-252, 300 — functions never entered: search
  - src/verdict_mcp/escalate.py: unexercised lines 63, 65, 67, 76-77, 84-85, 176-177
  - src/verdict_mcp/focus.py: unexercised lines 85, 120
  - src/verdict_mcp/gaps.py: unexercised lines 112, 189-192, 201, 218, 221, 225, 231-232, 236-238, 251-252, 264, 276, 287
  - src/verdict_mcp/gate.py: unexercised lines 46-48, 446, 475, 524-525
  - src/verdict_mcp/harness.py: unexercised lines 980, 1240-1241, 1244, 1877, 1896, 1929, 1940, 3633-3634
  - src/verdict_mcp/hygiene.py: unexercised lines 1075, 1079, 1090, 1188
  - src/verdict_mcp/profile.py: unexercised lines 212, 226, 230-232, 250, 265-268
  - src/verdict_mcp/readfirst.py: unexercised lines 91-92, 133, 181
  - src/verdict_mcp/replay.py: unexercised lines 143-144, 236-237, 242-243, 251, 283, 338-340, 348-350, 360-361, 374-375, 387, 477-479, 542-543, 557, 597-598, 616, 618, 639-640, 673
  - src/verdict_mcp/runner.py: unexercised lines 72, 979-980, 982, 1026-1027, 1046-1047, 1049, 1070-1071, 1085, 1088, 1091-1092, 1124, 1187, 1399-1400
  - src/verdict_mcp/small.py: unexercised lines 75, 309, 1131, 2253-2254, 2279, 2284, 2287, 2321
  - src/verdict_mcp/state.py: unexercised lines 977, 982-983
  - tests/conftest.py: unexercised lines 13-14, 19, 21
  - tests/test_backfill.py: unexercised lines 3-5, 7, 9-11, 13, 17, 20-21, 23, 27, 33, 38, 44, 54, 59, 67, 81, 93, 105, 113, 122, 149, 160, 174, 189, 200, 211, 221, 231, 241, 249, 263, 270, 283, 296, 315, 328, 338, 358, 375
  - tests/test_check.py: unexercised lines 3-4, 6-7, 9, 24, 27, 31, 37, 40, 61, 70, 86, 102, 112, 124
  - tests/test_coverage_render.py: unexercised lines 3-4, 6, 9, 40, 47
  - tests/test_directory_branch.py: unexercised lines 11-15, 17, 19-20, 22-24, 28, 31, 35-36, 40, 52, 67, 74, 78, 81, 91-103, 106, 118, 128, 142, 150
  - tests/test_directory_policy.py: unexercised lines 128
  - tests/test_dupes.py: unexercised lines 8, 10-11, 13, 20, 33, 44, 51, 57, 67, 77, 92, 104, 126, 143, 155, 167, 176, 185, 207
  - tests/test_escalate.py: unexercised lines 3-5, 7, 9-11, 14, 22, 35-36, 40, 47, 70, 79, 84, 94, 111, 124, 129-130, 133-141, 143, 147, 154, 161-162, 164, 169-170, 172, 174-175, 177-178, 181, 190, 194, 208, 214, 221, 227, 235, 242, 249, 262, 276, 282, 296, 306, 314, 328, 332, 344, 351, 361, 367
  - tests/test_focus.py: unexercised lines 3, 5-7, 9, 25, 34, 51, 60, 73, 91, 113
  - tests/test_gaps.py: unexercised lines 3, 5-7, 9, 19, 30, 33, 46, 57, 61, 70, 75, 92, 106, 113, 127, 135, 143, 157, 167, 178, 185, 194, 213, 228, 237, 251, 261, 268
  - tests/test_gate_policy.py: unexercised lines 8-11, 13, 15-18, 21, 25-26, 35-36, 42, 57, 69, 71-72, 75, 84-85, 94, 103, 109, 116, 122, 128, 137, 154, 171, 188, 193-194, 211, 225, 231, 255, 277, 292, 309, 322, 325, 327, 333, 339, 354
  - tests/test_harness.py: unexercised lines 1153
  - tests/test_hooks.py: unexercised lines 384
  - tests/test_hygiene.py: unexercised lines 1159, 1163, 1184, 1194, 1206, 1222, 1237, 1256, 1267
  - tests/test_limits.py: unexercised lines 101
  - tests/test_local_delta.py: unexercised lines 431-432, 435, 444, 471, 498, 751, 777, 1200, 1216, 1230, 1242, 1253, 1265, 1280
  - tests/test_local_gate.py: unexercised lines 234
  - tests/test_news.py: unexercised lines 8, 10-11, 14, 19, 37, 51, 63, 77, 89, 122
  - tests/test_plain_arm.py: unexercised lines 3-5, 7-8, 10, 14, 18, 29, 37, 45, 54, 66, 77, 95
  - tests/test_premeasure.py: unexercised lines 3-5, 7-8, 11, 16, 31, 40, 58, 64
  - tests/test_profile.py: unexercised lines 82, 90
  - tests/test_readfirst.py: unexercised lines 3, 5-7, 9, 25, 35, 42, 59, 70, 86, 96, 108, 122, 143
  - tests/test_recall_bench.py: unexercised lines 3-5, 7-8, 10, 18, 33, 55, 69, 79
  - tests/test_replay.py: unexercised lines 9-13, 15, 17-21, 23-24, 26-27, 32, 48, 59, 65, 75-76, 80, 84, 92, 109, 123, 134, 149, 162, 178, 188, 203, 221, 230, 239, 248, 253, 263, 270, 310, 332, 348, 364, 395, 403, 413, 427, 432, 444, 469, 481, 485, 497, 502, 510, 520, 524, 538, 546, 561, 570, 585, 605, 619, 636, 652, 676, 692, 711, 721, 736
  - tests/test_run_bill.py: unexercised lines 19, 23, 178, 191, 195
  - tests/test_runner.py: unexercised lines 576, 585, 595
  - tests/test_runner_agent.py: unexercised lines 10-13, 15, 17-18, 22-27, 29-30, 33, 47, 56, 60, 64, 76, 86, 98, 106, 120
  - tests/test_small.py: unexercised lines 437, 482, 505, 523, 528, 541, 552, 565
  - tests/test_stop_hook.py: unexercised lines 273, 305, 309, 323, 342, 353-354, 366, 368
  - tests/test_team_root_ignores.py: unexercised lines 12-16, 18, 20, 23, 28, 30, 34, 44, 64, 78, 83, 105

## Risks

Every finding read here is a `hypothesis` unless a counterfactual proved it. This mode cannot see a defect that spans two functions, and it reads the suite only where the range touched it.

## Findings — REGRESSED first (10 open of 11 tracked · 1 accepted)

### VERDICT-F-21 — ACCEPTED — Major/P2 — age 4d

The run-history chain's anti-fabrication signal can still be shed by deleting data, and the gate then exits 0: 0.66.0 moved the ratchet into outcomes.json, but the anchor is itself unauthenticated, so removing one JSON key restores `unchained` with the whole track record intact
- Re-reported open per the contract; the fold to `accepted` is verdict-finalize's to write, never the tester's. .qa/accepted.json records it accepted by ArtJack on 2026-09-05 citing 'DECISIONS.md 2026-09-02'.
- Unchanged as a defect and untouched by this range: `git log 0892869..4dc006a --oneline -- src/verdict_mcp/gate.py src/verdict_mcp/state.py` shows gate.py was not touched at all and state.py only for the accepted-risk fold, not for authenticating the anchor.
- Not re-measured this run.
- _Accepted risk — 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to._

### VERDICT-F-74 — STILL_OPEN — Minor/P2 — age 55d

The `trigger-separated-from-cause` eval row scores the presence of the single word 'trigger', so a report that never separates trigger from cause earns the point - the same shape run 12 filed against the bytecode row
- STILL OPEN at HEAD (fresh evidence, this range changed eval/expected-cause.json but not this row's mechanism). eval/expected-cause.json:43-49 the row is `{"key":"trigger-separated-from-cause","type":"report_contains","terms_all":["trigger"]}` — a single keyword.
- eval/score.py:371-387 scores report_contains by plain substring: `missing = [t for t in terms if t.lower() not in lowered]`, point if none missing. With terms_all == ['trigger'], any report containing the word 'trigger' anywhere earns the point without separating trigger from cause.
- CHANGELOG 0.79.0 still records this as owed ('F-74 ... is scorer work owed to the eval'); the eval corpus was not run this run (no live API), so this is verified by reading the key + scorer, not by scoring a report.
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: eval/expected-cause.json:43 (now line 46), eval/score.py:371 (now line 391)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: the row asserts presence of one keyword rather than the discipline (a report that names a trigger without distinguishing it from the cause still scores). Scorer work owed.
- Class: {"pattern": "single-keyword report_contains row scores vocabulary not discipline", "sites": ["eval/expected-cause.json:43-49 \u2014 the only single-keyword report_contains row across the seven answer 

### VERDICT-F-80 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer/test_pricer.py:18 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-81 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer_rev_b/test_pricer.py:17 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-82 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: "not a git checkout: the directory reads the repository, so this needs one"
- tests/test_directory_policy.py:68 — skip marker with reason '"not a git checkout: the directory reads the repository, so this needs one"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Exercised and green: `test_directory_policy.test_no_shipped_file_carries_a_key_shaped_value`, `test_directory_policy.test_no_shipped_file_is_too_large_for_the_directory_to_read` — these run the cited lines and do not fail on the defect; the assertion to review, and where a regression test belongs
- Cited code moved since the evidence was written: tests/test_directory_policy.py:68 (now line 71)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-83 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_hooks.py:195 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- tests/test_hooks.py:219 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-84 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar
- tests/test_hooks.py:1246 — skip marker with reason '"no GNU tar here (macOS ships bsdtar'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1246 (now line 1279)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-85 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar, which has no --remove-files
- tests/test_hooks.py:1306 — skip marker with reason '"no GNU tar here (macOS ships bsdtar, which has no --remove-files'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1306 (now line 1339)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-86 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: "needs a POSIX bash to measure against"
- tests/test_hooks_0903.py:1083 — skip marker with reason '"needs a POSIX bash to measure against"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-87 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

A test is skipped with no expiry: f"no {tool} here"
- tests/test_hooks_0903.py:1086 — skip marker with reason 'f"no {tool} here"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-88 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 15d

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

- **VERDICT-Q-1** (asked run 15, 47d ago · about VERDICT-F-74) — VERDICT-F-74 (Minor): fix the single-keyword `trigger-separated-from-cause` scorer row, or record its acceptance with verdict-accept? It has been 'scorer work owed' since 0.79.0 and is the only single-keyword report_contains row across the seven answer keys.
- **VERDICT-Q-2** (asked run 15, 47d ago) — The re-baseline surface (~2,300 new/changed lines across src/verdict_mcp/small.py +1089, questions.py +326, anchors.py +169, clock.py +72, filed.py +99, reports.py +132, runner.py +470, harness.py +903, validate.py +314, plus eval/swebench.py +1311) was NOT audited this scoped run (caller scope was F-75 + run-14 next_run_focus). Schedule a dedicated baseline run over these modules before the next release that touches them?
- **VERDICT-Q-3** (asked run 15, 47d ago) — The profile's isolation check part (1) grep now matches the verdict-local local-model client (small.py) and will always 'fail' while that feature exists. Refine it to exclude the declared local-model client, or scope it to the test-execution path only?

_Answer with `verdict-answer verdict <Q-id> --answer "…"`; the next run reads the decision instead of asking again._

## Reading map (82 production modules, 87% covered overall)

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

- no agent ran: 42 bounded question(s) went to chat-120b — no exploratory charter, no archaeology, no adversarial reading of the suite
- the commit history: no origin was traced, and no `git log -S` was run
- 10 of 10 prior open finding(s) were carried unread, and 0 re-filed because the code they cite changed and no model looked at the change
- 6 file(s) and 24 function(s) were read; nothing else in the repository was
- claims the counterfactual could not reach — a probe that would not run leaves its finding a hypothesis, and an unproven severity is held at Minor for a reading and at Major for a failing test the model classified
- nothing outside the checkout was read — no database, no MCP tools, no production numbers — so a standing blocker that quotes one was NOT re-read
- 4 question(s) the model did not answer
- 704 candidate function(s) were never asked about: the cap of 24 function(s) was reached
- 9 reading(s) this engine could not prove were listed as leads in the report, not filed — a lead is a question for a run that can judge it, not a finding

## Next run focus

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
- Settle VERDICT-F-74: change eval/expected-cause.json:43-49 to score the discipline, or verdict-accept it. Carrying it a run longer is the one option that costs something and settles nothing (the same logic that closed F-26 this run).
- Run the code-enumerated campaign over harness.py via eval/sweep.py (now proven) — scope it to the date/verification/outcome functions, ~90s/mutant, or it will not be run again.
- Refine the profile's isolation part-(1) grep so it stops flagging the verdict-local client (small.py) as a network dependency, or replace it with a suite-level no-live-call assertion.

## Notes

No Claude tokens were spent on this run. The verdict cannot improve on its own: a previous `fail` stays `fail`, and a previous `blocked` stays `blocked`, until something with judgment looks at it.

**Leads — read by a small model, not proven, not filed (9).** Each is a question for a run that can judge it; none is on the record.
- `.github/directory_branch.py:95` `plugin_tree` — Extra NUL sent to git update-index creates invalid empty entry when no files are kept (read as Major; probe failed on the original: SyntaxError: invalid syntax)
- `eval/backfill/faithful.py:38` `finding_of` — ID type mismatch causes StopIteration when finding ID is integer (read as Critical; the model did not answer with JSON)
- `eval/backfill/faithful.py:76` `main` — `--only` empty list ignored due to falsy check, causing all cases to be processed (read as Minor; the model did not answer with JSON)
- `eval/recall/build_cases.py:53` `main` — Missing '=' validation lets malformed run specs create cases with empty root paths (read as Major; the model did not answer with JSON)
- `eval/recall/packet_recall.py:42` `_head` — Missing git error handling in _head leads to silent failure (read as Major; the model did not answer with JSON)
- `eval/recall/plain_arm.py:114` `interpreter` — Regex matches later python path instead of interpreter token, returning incorrect interpreter (read as Major; the proof budget was spent)
- `eval/recall/plain_arm.py:144` `read_findings` — Fallback to result_text even when findings file exists but is empty (read as Major; the proof budget was spent)
- `eval/recall/plain_arm.py:187` `usage_rows` — Fallback branch hard‑codes model name "claude‑opus" instead of using actual model (read as Major; the proof budget was spent)
- `eval/recall/plain_arm.py:211` `isolated_tree` — Missing git rev-parse return code check yields misleading shared‑git‑dir error (read as Major; the proof budget was spent)

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
