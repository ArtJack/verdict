# QA report — verdict · run 16 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `4a918d8b4b786991cdbe45bde13bd9f3a8e9dc7e..1e8fd9d7edd5a4c2c9c32906ff97ae37f8b83038` · 133 files changed, 30487 insertions(+), 3838 deletions(-)
- Branch: `claude/verdict-azure-migration-d0f6ac` · measured 2026-10-15T05:00:39Z
- Harness: verdict-qa-mcp 0.90.5 · prompt 8365d3aefd6f · `/Users/artjack/Projects/verdict/.claude/worktrees/verdict-azure-migration-d0f6ac/src/verdict_mcp/harness.py`
- Judge: verdict-local · model `local:chat-120b` · host `100.82.62.40` · 40 call(s), 41700 token(s) · 1 question(s) unanswered · no Claude tokens spent
- Evidence drift: 1 of 1 anchored open findings cite code that moved or changed since the evidence was written (VERDICT-F-74)
- Isolation check: **pass** — local mode reads the checkout and runs the suite gate; it writes nothing outside the QA root

verdict-local: 24 function(s) in 6 file(s) read one at a time by chat-120b, each in isolation, over the range `4a918d8b4b786991cdbe45bde13bd9f3a8e9dc7e..1e8fd9d7edd5a4c2c9c32906ff97ae37f8b83038`. The harness measured the repository; the model answered bounded questions about single functions.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 241.17s | 2694 passed, 1 skipped in 240.76s (0:04:00) |
| `fixture_freshness` | pass | 0 | 0.08s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 2694, skipped 1, collected 2695
Test-id ledger: 2695 ids · +1525 / −2 (set-diff, not summary arithmetic) — id lists truncated to 50 each
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable
  - 1 open finding(s) cite no test id, so the harness cannot fix-verify them
Diff coverage: 8018/9893 changed lines executed (81%) across 73 file(s); 50 test(s) touch the diff
  - production 4120/4841 (85%) · test code 3898/5052 (77%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - 1188 of them only in a subprocess the suite spawned — measured, but no test to name
  - eval/external.py: unexercised lines 37, 39-51, 53-55, 57, 60-65, 68-74, 79, 85-87, 89, 96, 98, 105, 137, 148, 151, 155, 160, 164-165, 170, 172-180, 183-187, 190, 197, 204, 206-213, 215, 218, 222, 251, 261-263, 266, 273, 276, 286, 288-292, 294-303, 305-310, 313, 320, 332, 336, 389, 393, 401, 411, 414-423, 425-440, 447, 452, 462-464, 467, 497, 499-500, 502, 505-511, 514-518, 521, 525-528, 530-549, 554, 559, 566-573, 575-578, 582, 584-585, 587, 590-592, 595-617, 619-622, 629, 634, 638, 641, 645, 652, 655, 659, 663, 706-709, 712, 715-718, 720, 722-732, 735, 738-740, 743, 753-754, 756-767, 770-772, 775-786, 788-790, 793-795, 799-800 — functions never entered: now_utc, load_instances, instance, mirror_of, container, validate, prepare, tester_models, arm_env, _kill
  - eval/fixtures/pricer_clean/test_pricer.py: unexercised lines 1 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/pin_check.py: unexercised lines 83, 159
  - eval/run_eval.py: unexercised lines 61, 63, 93-94, 152, 179, 183, 186, 201, 207, 211, 224, 376, 383-386, 388, 391-398, 400-404, 407, 409-411, 414-415, 420, 422-426, 463, 479, 483, 492-493, 507, 519, 584-585, 588, 597-598, 604, 607-608, 611, 620, 623-625, 628, 726, 735, 740, 743, 745, 753, 757-760, 762 — functions never entered: run_agent, run_once, main
  - eval/run_mutation.py: unexercised lines 50, 59, 64, 92, 98-103, 105-109, 113, 118 — functions never entered: run_one
  - eval/swebench.py: unexercised lines 46-47, 64, 66, 71-73, 889, 941, 955, 1086, 1088, 1102-1105, 1108, 1117, 1128, 1147, 1150, 1154, 1158, 1186, 1196, 1217, 1242-1243, 1245-1246, 1259, 1293, 1305, 1313, 1323, 1330, 1345-1346, 1354, 1356, 1358, 1361, 1392, 1414, 1417-1418, 1423, 1433, 1459, 1463, 1467, 1472, 1485, 1508-1510, 1521-1524, 1528, 1569, 1579, 1600-1601, 1697, 1799, 1804, 1874, 1917
  - eval/sweep.py: unexercised lines 180-183 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/usage.py: unexercised lines 12, 15-16
  - eval/usage_census.py: unexercised lines 29, 31-37, 39-43, 47-49, 52, 55-56, 59, 74, 108, 132, 138, 145, 148-149, 153, 161, 179, 185, 211, 231-232
  - hooks/enforce_bash_scope.py: unexercised lines 845, 864, 887, 914, 916, 1125, 1131, 1134, 1177-1178, 1183-1185, 1215, 1605-1606, 1649, 1657, 1675, 1678-1679, 1691, 1696, 1767, 1775, 1796, 1808, 1967-1968, 1972-1975, 1983-1984, 1988, 2021, 2043, 2093, 2311, 2319, 2323
  - hooks/enforce_run_contract.py: unexercised lines 100-101, 109-110
  - hooks/enforce_write_scope.py: unexercised lines 51, 54, 68
  - hooks/report_open_findings.py: unexercised lines 286-287
  - src/verdict_mcp/accept.py: unexercised lines 47, 51
  - src/verdict_mcp/census.py: unexercised lines 155, 164-166, 168, 171-172
  - src/verdict_mcp/harness.py: unexercised lines 1378-1379, 2216-2217, 2435, 3325
  - src/verdict_mcp/hygiene.py: unexercised lines 390-391, 410, 424-425, 445, 452, 459, 468-469, 472-474, 536, 545, 558-559, 583-585, 630, 659, 663, 677, 1048, 1131, 1185-1186, 1229, 1241, 1297, 1577, 1582-1583, 1615-1616, 1634, 1659, 1697-1698, 1814, 1863, 1918
  - src/verdict_mcp/runner.py: unexercised lines 761-762, 864-865, 1047-1049, 1051-1052, 1054, 1056-1058
  - src/verdict_mcp/server.py: unexercised lines 358-361, 364
  - src/verdict_mcp/small.py: unexercised lines 72, 74-77, 81-82, 181-182, 189, 239, 344, 349-350, 366, 402, 658, 679-680, 699, 703-704, 759-760, 763-768, 770, 806, 913, 944, 949, 953, 1124, 1425, 1462, 1500, 1562, 1564, 1808, 1827-1828, 1926, 2021-2022, 2050, 2065-2066, 2068, 2154-2156, 2165, 2284, 2298-2299, 2302, 2359-2361, 2383, 2388, 2392, 2430-2432, 2525-2526, 2735
  - src/verdict_mcp/state.py: unexercised lines 79-80, 84-85
  - src/verdict_mcp/usage.py: unexercised lines 96, 152-153, 171-172, 227-228
  - src/verdict_mcp/validate.py: unexercised lines 803
  - tests/test_agent_contract.py: unexercised lines 190, 196
  - tests/test_census.py: unexercised lines 11, 187, 194, 211, 226, 243-244, 251
  - tests/test_ci_surfaces.py: unexercised lines 11-12, 14-18, 21, 29, 40, 46
  - tests/test_diff_coverage.py: unexercised lines 191
  - tests/test_directory_policy.py: unexercised lines 22-25, 27, 29, 35-36, 41, 60, 63, 67-68, 72, 87, 96-97, 106, 113, 122
  - tests/test_external.py: unexercised lines 10-13, 15, 17-19, 21, 32, 37, 64-69, 74, 89, 100, 114, 120, 125, 131, 149, 159, 177, 184, 188, 196, 212, 220, 236, 247, 260
  - tests/test_fixture_hygiene.py: unexercised lines 21-26, 28, 30-32, 34-36, 41, 61, 68, 73, 83, 90, 113, 119, 130, 144, 147-157, 160, 162-164, 166, 169-170, 172-174, 176-177, 180, 189, 202, 213, 223, 234, 246, 269
  - tests/test_harness.py: unexercised lines 1127
  - tests/test_hooks_0903.py: unexercised lines 17-25, 27, 29, 32, 39, 42, 54, 59, 67-75, 78-79, 85, 88-89, 92, 95, 102, 108, 115, 118, 124-125, 144-145, 155, 163, 192, 195, 214, 216, 219, 238, 252-253, 259, 270, 287-288, 293, 307, 335, 365-367, 376-378, 387, 414, 435-437, 445-447, 455, 496, 520, 532-533, 535, 546-547, 549, 562, 569, 581-583, 591-593, 603-604, 619, 632-634, 642-644, 652, 664, 679-681, 690-692, 699, 710, 725, 737-739, 747-749, 753-754, 767, 775, 789, 806-808, 815-817, 827, 849, 875-877, 886-888, 898, 918, 932-934, 944-946, 952, 960, 1056, 1068, 1080, 1083, 1086, 1089, 1091, 1106, 1108, 1121, 1142-1145, 1157-1158, 1160
  - tests/test_hooks_links.py: unexercised lines 16-21, 23, 25-27, 30-37, 40, 51-52, 70, 77-79, 88-89
  - tests/test_hooks_pens.py: unexercised lines 11-15, 17, 19-21, 24, 36-41, 44, 58, 73-75, 81-83, 88-89, 98-100, 111-112, 119-120
  - tests/test_hygiene.py: unexercised lines 8-16, 18, 20-21, 24, 29, 42, 46, 58, 61, 71, 79, 86, 95, 102, 111, 123, 133, 141, 152, 157, 163, 178, 193, 205, 222, 252, 274, 291, 310, 324, 333, 343, 356, 378, 393-394, 414-415, 432, 438, 449, 467, 481, 493, 504, 513, 518, 526, 534, 556, 572, 578, 583, 591, 600, 609, 617, 626, 633, 639, 647, 654, 660, 665, 668, 674, 685, 702, 728, 739, 760, 777, 794, 811, 821, 832, 841, 853, 866, 878, 894, 902, 915, 924, 940, 950, 961-966, 969-970, 1003, 1014, 1027, 1047, 1069, 1087, 1108, 1141
  - tests/test_hygiene_evidence.py: unexercised lines 11-12, 14-15, 17, 19, 24, 44, 64, 70, 78, 87, 96, 107, 117, 125, 139, 149, 161, 171, 192, 211
  - tests/test_hygiene_facts.py: unexercised lines 9, 11, 13-15, 17, 20, 27, 33, 40, 46, 53-55, 61-62, 73, 76, 80, 88, 97, 107, 114, 130, 147, 149, 152, 159, 165-166, 172, 174, 180, 192, 206
  - tests/test_hygiene_identity.py: unexercised lines 10, 12, 14-15, 17, 20, 24, 28, 35, 57, 71, 91, 100, 104, 109, 116, 130
  - tests/test_hygiene_lifecycle.py: unexercised lines 7-8, 11, 16, 22, 31, 36, 39, 43, 50, 59, 67, 73, 85, 100, 116, 130, 152, 170, 183, 196, 206, 216, 227, 241, 252, 260, 262, 264-265, 267, 270, 282, 286, 308, 322, 332, 354, 369, 383, 390, 404, 424, 440, 459, 471, 490, 509, 521, 540
  - tests/test_hygiene_state.py: unexercised lines 14-15, 17, 19-20, 22, 24, 27, 37, 46, 50, 56, 75, 88, 113, 128, 142, 151, 165, 181, 192, 208, 244
  - tests/test_listing_render.py: unexercised lines 19-20, 22, 24-25, 29-30, 33, 38, 53, 57, 60, 64, 66, 69-70, 74, 84
  - tests/test_local_delta.py: unexercised lines 15-20, 22, 24-27, 29-32, 35, 38, 47, 51, 62, 68-69, 72, 106, 110, 118, 141, 157, 182, 201, 226, 242, 257, 268, 279, 295, 310, 320, 340, 348, 370, 386, 406, 429, 438, 451, 458, 472, 497, 531, 534, 547, 569-570, 573, 576, 579, 583, 602, 613, 624, 640, 660, 662, 666, 688, 702, 733, 756, 764, 786, 807, 833, 845, 874, 878, 882, 891, 905, 931, 962, 966, 990, 1014, 1049, 1062
  - tests/test_local_gate.py: unexercised lines 15-18, 20-22, 24, 26-28, 30-31, 34, 55, 66, 74, 90, 105, 124, 133, 140, 162, 182, 194, 214, 224, 234, 240, 252, 277, 288, 299, 306, 334
  - tests/test_mcp_cli.py: unexercised lines 8-9, 11, 14, 19, 26
  - tests/test_mutate.py: unexercised lines 69
  - tests/test_pin_check.py: unexercised lines 96, 122-123, 126, 133
  - tests/test_qa_root_links.py: unexercised lines 22-26, 28, 30-33, 35, 37-38, 43, 47, 69, 73, 78-79, 81-82, 85-87, 90-91, 98-99, 108-109, 123-124, 132, 139, 149-150, 156-157, 164, 176, 185-186, 188-189, 191-194, 197-198, 209, 226, 230, 250, 272-273, 282-283, 292, 310, 318-320, 323-324, 326-329, 332, 334-335, 338, 351, 360-361, 363, 376-377, 392-393 — functions never entered: _NoModel.__getattr__, test_a_junction_is_a_link_on_windows
  - tests/test_questions.py: unexercised lines 87
  - tests/test_report_containment.py: unexercised lines 11-14, 16, 18-19, 22, 26, 30, 34, 48, 60, 69-70, 73-82, 85-90, 93, 98, 105, 115, 120
  - tests/test_run_bill.py: unexercised lines 12-17, 19-21, 23-24, 27, 34, 39, 44, 49, 57, 63, 69, 74, 85, 121, 134, 146, 156, 167, 176, 190
  - tests/test_run_eval_task_note.py: unexercised lines 9-10, 12-14, 17, 23
  - tests/test_runner.py: unexercised lines 483, 497, 506, 513, 528, 542
  - tests/test_runner_env.py: unexercised lines 12-17, 19, 21-22, 24, 31, 38, 43, 51-56, 58-59, 62, 74, 95
  - tests/test_score.py: unexercised lines 555, 586
  - tests/test_session_start.py: unexercised lines 160, 172, 183, 188, 201, 207-208, 214, 216, 222, 226, 231, 243, 249, 258, 265
  - tests/test_skills.py: unexercised lines 29
  - tests/test_small.py: unexercised lines 158, 189
  - tests/test_small_probes.py: unexercised lines 16-20, 22, 24-27, 29-32, 36, 40, 43, 47, 72, 91, 97, 102, 122, 141, 154, 186, 217, 256, 263, 289, 313, 327, 347, 355, 367-368, 372, 387, 396, 416, 426, 437, 461, 472, 475, 492, 502, 513, 518, 526, 530, 534 — functions never entered: _refuse_subprocess.boom, test_probes_off_means_no_counterfactual_is_ever_called.never, test_a_gate_with_no_python_disables_proving_and_says_so.never
  - tests/test_stop_hook.py: unexercised lines 201, 213, 218, 233, 248, 261, 270, 279
  - tests/test_swebench_plain.py: unexercised lines 12-21, 23, 25-27, 29-31, 33, 42, 49, 71, 77, 85, 106, 109, 124, 128, 153, 175, 186, 218, 223, 249, 261, 271, 317, 336, 357-358, 369, 399, 408, 418, 425, 429, 436-446, 450-451, 454, 458-459, 486-487, 497-498, 512, 538, 584, 616-617, 620-622, 625-628, 630, 649, 652, 657-658, 660, 663, 685, 722, 739
  - tests/test_sweep.py: unexercised lines 122, 128, 145, 165, 176, 191, 231, 262, 285
  - tests/test_usage_census.py: unexercised lines 11-13, 15-17, 20, 26, 37, 54, 69, 77, 85, 94
  - tests/test_validate.py: unexercised lines 28-32
  - tests/test_validate_hook_scope.py: unexercised lines 9-13, 15-16, 19, 28, 36, 43, 51, 59

## Risks

Every finding read here is a `hypothesis` unless a counterfactual proved it. This mode cannot see a defect that spans two functions, and it reads the suite only where the range touched it.

## Findings — REGRESSED first (10 open of 11 tracked · 1 accepted)

### VERDICT-F-21 — ACCEPTED — Major/P2 — age 4d

The run-history chain's anti-fabrication signal can still be shed by deleting data, and the gate then exits 0: 0.66.0 moved the ratchet into outcomes.json, but the anchor is itself unauthenticated, so removing one JSON key restores `unchained` with the whole track record intact
- Re-reported open per the contract; the fold to `accepted` is verdict-finalize's to write, never the tester's. .qa/accepted.json records it accepted by ArtJack on 2026-09-05 citing 'DECISIONS.md 2026-09-02'.
- Unchanged as a defect and untouched by this range: `git log 0892869..4dc006a --oneline -- src/verdict_mcp/gate.py src/verdict_mcp/state.py` shows gate.py was not touched at all and state.py only for the accepted-risk fold, not for authenticating the anchor.
- Not re-measured this run.
- _Accepted risk — 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to._

### VERDICT-F-74 — STILL_OPEN — Minor/P2 — age 40d

The `trigger-separated-from-cause` eval row scores the presence of the single word 'trigger', so a report that never separates trigger from cause earns the point - the same shape run 12 filed against the bytecode row
- STILL OPEN at HEAD (fresh evidence, this range changed eval/expected-cause.json but not this row's mechanism). eval/expected-cause.json:43-49 the row is `{"key":"trigger-separated-from-cause","type":"report_contains","terms_all":["trigger"]}` — a single keyword.
- eval/score.py:371-387 scores report_contains by plain substring: `missing = [t for t in terms if t.lower() not in lowered]`, point if none missing. With terms_all == ['trigger'], any report containing the word 'trigger' anywhere earns the point without separating trigger from cause.
- CHANGELOG 0.79.0 still records this as owed ('F-74 ... is scorer work owed to the eval'); the eval corpus was not run this run (no live API), so this is verified by reading the key + scorer, not by scoring a report.
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: eval/expected-cause.json:43 (now line 46), eval/score.py:371 (now line 391)
- _Re-reported by id (`still_open`): looked at, still there; the evidence is as last filed_
- Root cause: the row asserts presence of one keyword rather than the discipline (a report that names a trigger without distinguishing it from the cause still scores). Scorer work owed.
- Class: {"pattern": "single-keyword report_contains row scores vocabulary not discipline", "sites": ["eval/expected-cause.json:43-49 \u2014 the only single-keyword report_contains row across the seven answer 

### VERDICT-F-80 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer/test_pricer.py:18 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-81 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer_rev_b/test_pricer.py:17 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-82 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: "not a git checkout: the directory reads the repository, so this needs one"
- tests/test_directory_policy.py:68 — skip marker with reason '"not a git checkout: the directory reads the repository, so this needs one"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-83 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_hooks.py:195 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- tests/test_hooks.py:219 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-84 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar
- tests/test_hooks.py:1246 — skip marker with reason '"no GNU tar here (macOS ships bsdtar'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-85 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar, which has no --remove-files
- tests/test_hooks.py:1306 — skip marker with reason '"no GNU tar here (macOS ships bsdtar, which has no --remove-files'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-86 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: "needs a POSIX bash to measure against"
- tests/test_hooks_0903.py:1083 — skip marker with reason '"needs a POSIX bash to measure against"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-87 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: f"no {tool} here"
- tests/test_hooks_0903.py:1086 — skip marker with reason 'f"no {tool} here"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.

### VERDICT-F-88 — NEW — Minor/P2 — BRITTLE_TEST

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_mcp_tools.py:324 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

A skipped test with no expiry silently removes coverage. Either give the skip an expiry date or delete the test deliberately.


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

- **VERDICT-Q-1** (asked run 15, 32d ago · about VERDICT-F-74) — VERDICT-F-74 (Minor): fix the single-keyword `trigger-separated-from-cause` scorer row, or record its acceptance with verdict-accept? It has been 'scorer work owed' since 0.79.0 and is the only single-keyword report_contains row across the seven answer keys.
- **VERDICT-Q-2** (asked run 15, 32d ago) — The re-baseline surface (~2,300 new/changed lines across src/verdict_mcp/small.py +1089, questions.py +326, anchors.py +169, clock.py +72, filed.py +99, reports.py +132, runner.py +470, harness.py +903, validate.py +314, plus eval/swebench.py +1311) was NOT audited this scoped run (caller scope was F-75 + run-14 next_run_focus). Schedule a dedicated baseline run over these modules before the next release that touches them?
- **VERDICT-Q-3** (asked run 15, 32d ago) — The profile's isolation check part (1) grep now matches the verdict-local local-model client (small.py) and will always 'fail' while that feature exists. Refine it to exclude the declared local-model client, or scope it to the test-execution path only?

_Answer with `verdict-answer verdict <Q-id> --answer "…"`; the next run reads the decision instead of asking again._

## Reading map (66 production modules, 86% covered overall)

| Module | Covered | Statements | Open findings | Last cited |
|---|---|---|---|---|
| `eval/corpus/pricer-baseline-sonnet-20260828/probe.py` | 0% | None | 0 | never |
| `eval/fixtures/liar/qstats.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer/pricer.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer_clean/pricer.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer_clean/probe.py` | 0% | None | 0 | never |
| `eval/fixtures/pricer_rev_b/pricer.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/invoice.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/money.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/rates.py` | 0% | None | 0 | never |
| `eval/fixtures/rates/commits/01-initial/report.py` | 0% | None | 0 | never |

Never cited by any finding, least covered first: `eval/corpus/pricer-baseline-sonnet-20260828/probe.py`, `eval/fixtures/liar/qstats.py`, `eval/fixtures/pricer/pricer.py`, `eval/fixtures/pricer_clean/pricer.py`, `eval/fixtures/pricer_clean/probe.py`, `eval/fixtures/pricer_rev_b/pricer.py`, `eval/fixtures/rates/commits/01-initial/invoice.py`, `eval/fixtures/rates/commits/01-initial/money.py`, `eval/fixtures/rates/commits/01-initial/rates.py`, `eval/fixtures/rates/commits/01-initial/report.py`

## Not tested

- no agent ran: 34 bounded question(s) went to chat-120b — no exploratory charter, no archaeology, no adversarial reading of the suite
- the commit history: no origin was traced, and no `git log -S` was run
- 1 of 1 prior open finding(s) were carried unread, and 0 re-filed because the code they cite changed and no model looked at the change
- 6 file(s) and 24 function(s) were read; nothing else in the repository was
- claims the counterfactual could not reach — a probe that would not run leaves its finding a hypothesis, and an unproven severity is held at Minor
- nothing outside the checkout was read — no database, no MCP tools, no production numbers — so a standing blocker that quotes one was NOT re-read
- 1 question(s) the model did not answer
- 927 candidate function(s) were never asked about: the cap of 24 function(s) was reached
- 5 reading(s) this engine could not prove were listed as leads in the report, not filed — a lead is a question for a run that can judge it, not a finding

## Next run focus

- needs a model run — diff_over_limit: the range is larger than the caps this engine runs under; part of it was never read
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

**Leads — read by a small model, not proven, not filed (5).** Each is a question for a run that can judge it; none is on the record.
- `eval/external.py:152` `sh` — sh() fails to run string commands because it doesn't invoke a shell or split the command (read as Major; fix_unsafe: introduces `shell`, a name the function never uses)
- `eval/external.py:230` `checkout_at` — Ancestor tags are not deleted, contradicting docstring that tags must be physically absent (read as Major; the model did not answer with JSON)
- `eval/external.py:262` `container` — Container function passes whole command string as single argv entry, breaking commands with spaces (read as Major; probe_unsafe: argument 2 is not a literal (__import__('pathlib').Path('.')))
- `eval/external.py:280` `run_withheld` — Combined '-rA' flag and file list into one argument breaks pytest invocation (read as Major; probe_unsafe: argument 2 is not a literal (m.Path('.')))
- `eval/external.py:458` `transcripts_of` — transcripts_of returns [] for falsy session_id with since=None, omitting existing transcripts (read as Major; probe_unsafe: argument 1 is not a literal (m.Path('.')))

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
