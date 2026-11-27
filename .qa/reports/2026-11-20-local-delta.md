# QA report — verdict · run 19 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `97e3da38880f07ea31464e53d0cb878f7f20e4bd..79c603bee93f08fd4ce366baa7c21be365268e8d` · 136 files changed, 22064 insertions(+), 12825 deletions(-)
- Branch: `qa/run-19` · measured 2026-11-20T10:21:45Z
- Harness: verdict-qa-mcp 0.94.0 · prompt 1bd07f7fdc6a · `/Users/artjack/Projects/verdict/.claude/worktrees/qa-run-19/src/verdict_mcp/harness.py`
- Judge: verdict-local · model `local:chat-120b` · 42 call(s), 46710 token(s) · 3 question(s) unanswered · no Claude tokens spent
- Evidence drift: 4 of 10 anchored open findings cite code that moved or changed since the evidence was written (VERDICT-F-82, VERDICT-F-84, VERDICT-F-85, VERDICT-F-74)
- Isolation check: **pass** — measured before the gates: no plaintext .env file at the checkout root. The profile's own isolation steps were not executed: this engine runs the profile's gates and reads code, and writes nothing outside the QA root

verdict-local: 24 function(s) in 8 file(s) read one at a time by chat-120b, each in isolation, over the range `97e3da38880f07ea31464e53d0cb878f7f20e4bd..79c603bee93f08fd4ce366baa7c21be365268e8d`. The harness measured the repository; the model answered bounded questions about single functions.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 335.33s | 3533 passed, 21 skipped in 329.60s (0:05:29) |
| `fixture_freshness` | pass | 0 | 0.11s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 3533, skipped 21, collected 3554
Test-id ledger: 3554 ids · +533 / −1 (set-diff, not summary arithmetic) — id lists truncated to 50 each
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable
  - 10 open finding(s) cite no test id, so the harness cannot fix-verify them
Diff coverage: 8536/10809 changed lines executed (79%) across 115 file(s); 50 test(s) touch the diff
  - production 7549/9207 (82%) · test code 987/1602 (62%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - 2046 of them only in a subprocess the suite spawned — measured, but no test to name
  - scripts/check_structure.py: unexercised lines 1-346 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - src/verdict_mcp/accept.py: unexercised lines 49, 55
  - src/verdict_mcp/backfill.py: unexercised lines 38, 48
  - src/verdict_mcp/braces.py: unexercised lines 196, 208-213, 215-216, 229, 233, 250-251, 258-259, 263, 269, 285-286, 292, 298-299, 306, 315, 317, 319, 326, 338-340, 351, 355, 359, 393-394, 419, 426, 435-436, 440, 442, 473, 532, 549, 551, 558, 685, 726, 786, 815, 881, 1091-1092, 1098, 1117-1118
  - src/verdict_mcp/browser.py: unexercised lines 109, 154, 157-162, 165, 168, 171, 192, 194-197, 202, 204-207, 209-213, 220, 223-229, 237, 239, 245-287, 290-310, 313-320, 324, 327-341, 346-373, 376-384, 386-408, 410, 413-414, 418, 435-461, 471-476, 480-481, 484-488, 490, 507-513, 521-532, 540-547, 553-568, 571-585, 587-602, 604-608, 610-613, 616, 629, 631-632, 634-635, 637-642, 644-649, 651-656, 658-667, 669-676, 680-683, 685-689, 692-695, 697-731, 748-750, 752-766, 771-773, 775-780, 783-795, 797-800, 815, 817-818, 835-846, 848-850, 853-872, 888-911, 927, 932-933, 936-937, 939-943, 945-949, 951-955, 959-974, 976-985, 994-998, 1007-1013, 1023-1040, 1043-1059, 1066-1073, 1085, 1090-1092, 1094-1095, 1098-1099, 1101-1102, 1106-1107, 1110-1111, 1115, 1119-1121, 1124-1126, 1128-1129, 1132-1133, 1135-1139, 1142, 1156-1164, 1174-1179, 1181-1182, 1185, 1187-1190, 1193-1195, 1199, 1202-1207, 1209-1213, 1215, 1221-1223, 1225-1232, 1261-1264, 1269-1272, 1276 — functions never entered: _Run.left, _Run.out_of_time, _Run.done, _Run.add, _Run.on, _Run.context, _Run.new_page, _Run.new_page.answer, _Run.src, _Run.goto
  - src/verdict_mcp/browser_config.py: unexercised lines 170, 216
  - src/verdict_mcp/browser_findings.py: unexercised lines 62-63, 75
  - src/verdict_mcp/browser_forms.py: unexercised lines 52, 68-69
  - src/verdict_mcp/browser_images.py: unexercised lines 24, 27-28, 31, 41, 44-45
  - src/verdict_mcp/browser_server.py: unexercised lines 29-36, 40-48, 54-55, 57-58, 60-63, 67-72, 75-89, 91-93 — functions never entered: _answers, wait_ready, start_server, stop_server
  - src/verdict_mcp/browser_source.py: unexercised lines 35-36, 51, 61-62, 84, 96-97, 101, 104-108, 131-135, 156-157
  - src/verdict_mcp/check.py: unexercised lines 39, 46
  - src/verdict_mcp/dupes.py: unexercised lines 33
  - src/verdict_mcp/ends.py: unexercised lines 74-75, 77-78, 80, 84, 86, 91-105, 135-139, 150, 152, 159-162, 164-168, 170, 197-198, 200, 206-207, 246-247, 255-258, 383, 390, 395, 410, 429, 443-447, 449, 464 — functions never entered: _hole_end
  - src/verdict_mcp/facts_coverage.py: unexercised lines 111, 143, 146, 264-265, 280-281, 284-286, 292, 296-297 — functions never entered: measure_diff_coverage
  - src/verdict_mcp/facts_reading.py: unexercised lines 82, 109, 112, 116, 119, 168, 174, 181
  - src/verdict_mcp/facts_verify.py: unexercised lines 108, 162, 180, 182, 203-206
  - src/verdict_mcp/finalize_carry.py: unexercised lines 42, 61, 94, 105
  - src/verdict_mcp/finalize_ids.py: unexercised lines 63, 134-137
  - src/verdict_mcp/finalize_merge.py: unexercised lines 103-104
  - src/verdict_mcp/finalize_write.py: unexercised lines 76-77, 189, 201, 210, 218, 225
  - src/verdict_mcp/focus.py: unexercised lines 117, 127
  - src/verdict_mcp/harness_common.py: unexercised lines 65-66, 83-84
  - src/verdict_mcp/hygiene_evidence.py: unexercised lines 49, 54-55, 87-88, 106, 131
  - src/verdict_mcp/hygiene_git.py: unexercised lines 46-47, 66, 80-81, 101, 108, 115, 124-125, 128-130
  - src/verdict_mcp/hygiene_js.py: unexercised lines 33, 89
  - src/verdict_mcp/hygiene_lines.py: unexercised lines 57, 61, 72, 170
  - src/verdict_mcp/hygiene_python.py: unexercised lines 52, 136, 190-191, 234
  - src/verdict_mcp/hygiene_reconcile.py: unexercised lines 37-38, 154, 203, 258
  - src/verdict_mcp/hygiene_scrub.py: unexercised lines 81, 90, 103-104
  - src/verdict_mcp/hygiene_secrets.py: unexercised lines 59-61, 106, 135, 139, 153
  - src/verdict_mcp/languages.py: unexercised lines 266
  - src/verdict_mcp/local_candidates.py: unexercised lines 16-18, 105-106, 132, 137-138, 154, 212, 234
  - src/verdict_mcp/local_carry.py: unexercised lines 82, 119
  - src/verdict_mcp/local_chunks.py: unexercised lines 130-131, 175
  - src/verdict_mcp/local_env.py: unexercised lines 20-24, 134-135, 163, 178-179, 181, 221-222, 247, 252, 255, 289
  - src/verdict_mcp/local_findings.py: unexercised lines 16-24, 75, 94-95, 189, 194-195, 197, 216
  - src/verdict_mcp/local_model.py: unexercised lines 73-74, 81, 131, 149-150
  - src/verdict_mcp/local_probes.py: unexercised lines 27-29, 156, 177-178, 197, 201-202, 231, 257-258, 264-265, 304, 320-321, 323, 363, 379-380, 385-386, 413, 444, 449, 453
  - src/verdict_mcp/local_quarantine.py: unexercised lines 15-16, 49, 111, 113
  - src/verdict_mcp/local_questions.py: unexercised lines 14-15, 194
  - src/verdict_mcp/local_skips.py: unexercised lines 17, 44-45, 85, 146
  - src/verdict_mcp/local_suite.py: unexercised lines 16-20, 64-66, 68, 70, 81-82, 126, 128, 136, 147, 195, 209-210, 212-213, 258-259, 276, 282, 296 — functions never entered: ids_in_report
  - src/verdict_mcp/local_summary.py: unexercised lines 15-18, 33-34
  - src/verdict_mcp/profile.py: unexercised lines 284
  - src/verdict_mcp/reach.py: unexercised lines 84, 131, 135-136, 165, 169, 173, 200-201, 212, 215-216, 242, 253, 256-257, 259, 263, 269, 271 — functions never entered: _default_export
  - src/verdict_mcp/regions.py: unexercised lines 119, 223, 251-252, 254
  - src/verdict_mcp/report_names.py: unexercised lines 32-33, 66-69, 118
  - src/verdict_mcp/report_render.py: unexercised lines 108, 159, 220-221
  - src/verdict_mcp/report_sections.py: unexercised lines 59, 97, 260
  - src/verdict_mcp/runner.py: unexercised lines 64, 67, 81, 83, 86, 88, 91, 96, 99, 503
  - src/verdict_mcp/runner_agent.py: unexercised lines 127
  - src/verdict_mcp/runner_env.py: unexercised lines 89
  - src/verdict_mcp/runner_escalate.py: unexercised lines 17, 33-34, 53-54, 56, 68, 71, 74-75, 107
  - src/verdict_mcp/runner_limits.py: unexercised lines 98, 100-101, 121-122
  - src/verdict_mcp/runner_local.py: unexercised lines 17-18, 94-95, 97, 114-115
  - src/verdict_mcp/runner_provision.py: unexercised lines 18-19, 60, 138-139, 151-152, 157, 173-174, 181-182, 239-240, 286-287, 289, 327-328, 330-331, 355, 377-378 — functions never entered: _raise
  - src/verdict_mcp/runner_stream.py: unexercised lines 20-21, 54-56
  - src/verdict_mcp/runner_sweep.py: unexercised lines 16-18, 67, 98, 105, 114, 119, 199-200, 214-215, 217, 220, 223, 226-228, 243, 245
  - src/verdict_mcp/sandbox.py: unexercised lines 201-204, 206, 214, 297-298, 324-325, 393-398, 457-458, 475-476, 517, 547-550, 552, 554-557 — functions never entered: _limit
  - src/verdict_mcp/small.py: unexercised lines 56-57, 63, 82, 84, 87, 92, 97, 100, 104, 106, 108, 110, 112-113, 115, 119, 204
  - src/verdict_mcp/testmarks.py: unexercised lines 118, 121, 138
  - tests/browser_site.py: unexercised lines 8, 10-16, 19, 30-31, 36, 39, 162, 167, 181-189, 192-193, 195-196, 198-199, 201-203, 205-207, 209-212, 215-216, 218-220, 222-225, 227-228 — functions never entered: build, _Recorder.log_message, _Recorder._record, _Recorder.do_GET, _Recorder.do_HEAD, _Recorder.do_POST, serve
  - tests/conftest.py: unexercised lines 24-25, 29-36
  - tests/test_accept.py: unexercised lines 154
  - tests/test_backfill.py: unexercised lines 4
  - tests/test_braces.py: unexercised lines 9-10, 12, 14-16, 19, 25, 30, 34, 41, 45, 47, 53, 70, 78, 87, 97, 153, 165, 176, 181, 217, 224, 229, 234, 238, 244, 257, 261, 267, 272, 276, 291, 297, 302
  - tests/test_braces_languages.py: unexercised lines 12-13, 15, 17-19, 22, 26, 32, 45, 52, 58, 65, 73, 109, 117, 122, 157, 163, 187, 194, 224, 229, 234, 257, 263, 279, 284, 304, 308, 324, 330, 353, 360, 381, 387, 399, 403, 429, 433, 441, 452, 460, 463, 473
  - tests/test_browser.py: unexercised lines 10, 12-16, 18, 20-26, 28, 33, 37, 41, 51, 58, 68, 73, 84, 91, 103, 119, 134, 149, 159, 171, 177, 181, 187, 198, 209-210, 213, 216, 220, 225, 237, 245, 254, 265-276, 279-280, 283-284, 286-290, 293-298, 301-307, 310-315, 318-325, 328-334, 337-342, 344-346, 348, 353-354, 359-361, 363-366, 368-370, 372-373, 377-378, 380-383, 385-386, 388-392, 395-401, 404 — functions never entered: site_run, _found, test_each_seeded_defect_is_found_on_its_page, test_no_clean_twin_is_flagged, test_no_write_reached_the_server_and_no_action_link_was_followed, test_every_finding_is_a_validator_clean_measurement, test_verdict_browse_writes_its_result_and_exits_zero, test_verdict_local_files_a_browser_finding_carries_it_unmeasured_and_resolves_it_measured, test_verdict_local_files_a_browser_finding_carries_it_unmeasured_and_resolves_it_measured.profile, test_verdict_local_files_a_browser_finding_carries_it_unmeasured_and_resolves_it_measured.run
  - tests/test_coverage_render.py: unexercised lines 6
  - tests/test_ends.py: unexercised lines 9-10, 12-14, 17, 21, 55, 60, 68, 73, 79, 98, 105, 126, 131
  - tests/test_escalate.py: unexercised lines 10, 169
  - tests/test_gitenv.py: unexercised lines 13-17, 19, 21, 23, 25, 29, 33, 38-39, 44-61, 65, 76, 103, 119-120, 128, 161, 173, 181, 185
  - tests/test_hygiene_lifecycle.py: unexercised lines 7
  - tests/test_languages.py: unexercised lines 9-10, 12, 14-16, 19, 32, 37, 40, 45, 53, 58, 61, 66, 73, 78, 83, 91, 98
  - tests/test_local_braces.py: unexercised lines 10-13, 15-17, 19, 21, 23, 26, 46, 53, 68, 76, 91, 111, 118, 136, 154, 160, 172
  - tests/test_local_delta.py: unexercised lines 26
  - tests/test_local_gate.py: unexercised lines 24, 107, 124
  - tests/test_local_languages.py: unexercised lines 11-14, 16-18, 20, 22, 24, 27, 38, 47, 54, 61, 73, 82, 92, 101, 110, 127, 134, 153, 166, 175
  - tests/test_reach.py: unexercised lines 9-10, 12-14, 16, 50, 57, 65, 84, 97, 105, 112
  - tests/test_regions.py: unexercised lines 9-10, 12-14, 17, 21, 42, 50, 56, 73, 79, 85, 102, 109, 119, 124, 135, 143, 152, 158
  - tests/test_replay.py: unexercised lines 134, 252
  - tests/test_sandbox.py: unexercised lines 17-22, 24, 26-27, 30, 33-35, 37, 40, 42, 45, 47, 50, 53, 63, 71, 85, 98, 113, 123, 135, 142, 157, 171, 183, 193, 202, 214, 240, 250, 255, 270, 278, 288, 305, 338-346, 349-350, 352-357, 359-362, 364-366, 369-374, 376, 378-379, 382-387, 389-391, 394-395, 410-411, 414, 425, 434, 449, 457, 490, 494, 513, 532-533, 555, 561, 579, 595, 604, 616-617, 630-631, 635, 646 — functions never entered: test_the_ci_machine_that_must_have_the_box_has_it, _home, test_inside_the_box_the_code_reaches_nothing_but_its_checkout_and_loopback, test_a_writable_home_does_not_reopen_the_credential_stores, test_a_gate_named_for_the_network_keeps_it_and_nothing_else
  - tests/test_small.py: unexercised lines 16
  - tests/test_small_probes.py: unexercised lines 26, 188, 190, 194-197, 199, 201-202 — functions never entered: test_in_the_box_a_probe_cannot_write_outside_its_copy
  - tests/test_suite_dialects.py: unexercised lines 14, 16, 18-19, 21, 62, 89, 101, 109, 114, 122, 133, 138, 144, 152, 159, 166, 173, 178, 183, 187, 197
  - tests/test_testmarks.py: unexercised lines 8-9, 11, 13-15, 18, 22, 36, 43, 60, 65, 77, 81, 94, 98, 113, 118
  - tests/test_verification.py: unexercised lines 14

## Risks

Every finding read here is a `hypothesis` unless a counterfactual proved it. This mode cannot see a defect that spans two functions, and it reads the suite only where the range touched it.

## Findings — REGRESSED first (10 open of 11 tracked · 1 accepted)

### VERDICT-F-21 — ACCEPTED — Major/P2 — age 4d

The run-history chain's anti-fabrication signal can still be shed by deleting data, and the gate then exits 0: 0.66.0 moved the ratchet into outcomes.json, but the anchor is itself unauthenticated, so removing one JSON key restores `unchained` with the whole track record intact
- Re-reported open per the contract; the fold to `accepted` is verdict-finalize's to write, never the tester's. .qa/accepted.json records it accepted by ArtJack on 2026-09-05 citing 'DECISIONS.md 2026-09-02'.
- Unchanged as a defect and untouched by this range: `git log 0892869..4dc006a --oneline -- src/verdict_mcp/gate.py src/verdict_mcp/state.py` shows gate.py was not touched at all and state.py only for the accepted-risk fold, not for authenticating the anchor.
- Not re-measured this run.
- _Accepted risk — 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to._

### VERDICT-F-74 — STILL_OPEN — Minor/P2 — age 76d

The `trigger-separated-from-cause` eval row scores the presence of the single word 'trigger', so a report that never separates trigger from cause earns the point - the same shape run 12 filed against the bytecode row
- STILL OPEN at HEAD (fresh evidence, this range changed eval/expected-cause.json but not this row's mechanism). eval/expected-cause.json:43-49 the row is `{"key":"trigger-separated-from-cause","type":"report_contains","terms_all":["trigger"]}` — a single keyword.
- eval/score.py:371-387 scores report_contains by plain substring: `missing = [t for t in terms if t.lower() not in lowered]`, point if none missing. With terms_all == ['trigger'], any report containing the word 'trigger' anywhere earns the point without separating trigger from cause.
- CHANGELOG 0.79.0 still records this as owed ('F-74 ... is scorer work owed to the eval'); the eval corpus was not run this run (no live API), so this is verified by reading the key + scorer, not by scoring a report.
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: eval/expected-cause.json:43 (now line 46), eval/score.py:371 (now line 391)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: the row asserts presence of one keyword rather than the discipline (a report that names a trigger without distinguishing it from the cause still scores). Scorer work owed.
- Class: {"pattern": "single-keyword report_contains row scores vocabulary not discipline", "sites": ["eval/expected-cause.json:43-49 \u2014 the only single-keyword report_contains row across the seven answer 

### VERDICT-F-80 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer/test_pricer.py:18 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-81 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer_rev_b/test_pricer.py:17 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-82 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: "not a git checkout: the directory reads the repository, so this needs one"
- tests/test_directory_policy.py:68 — skip marker with reason '"not a git checkout: the directory reads the repository, so this needs one"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Exercised and green: `test_directory_policy.test_no_shipped_file_carries_a_key_shaped_value`, `test_directory_policy.test_no_shipped_file_is_too_large_for_the_directory_to_read` — these run the cited lines and do not fail on the defect; the assertion to review, and where a regression test belongs
- Cited code moved since the evidence was written: tests/test_directory_policy.py:68 (now line 71)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-83 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_hooks.py:195 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- tests/test_hooks.py:219 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-84 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar
- tests/test_hooks.py:1246 — skip marker with reason '"no GNU tar here (macOS ships bsdtar'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1246 (now line 1279)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-85 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar, which has no --remove-files
- tests/test_hooks.py:1306 — skip marker with reason '"no GNU tar here (macOS ships bsdtar, which has no --remove-files'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- Cited code moved since the evidence was written: tests/test_hooks.py:1306 (now line 1339)
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-86 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: "needs a POSIX bash to measure against"
- tests/test_hooks_0903.py:1083 — skip marker with reason '"needs a POSIX bash to measure against"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-87 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

A test is skipped with no expiry: f"no {tool} here"
- tests/test_hooks_0903.py:1086 — skip marker with reason 'f"no {tool} here"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- Never measured — no `verification_test` declared
- _Carried by id, not re-read this run: the cited code did not move; the evidence is as last filed_
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

### VERDICT-F-88 — STILL_OPEN — Minor/P2 — BRITTLE_TEST — age 36d

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

- **VERDICT-Q-1** (asked run 15, 68d ago · about VERDICT-F-74) — VERDICT-F-74 (Minor): fix the single-keyword `trigger-separated-from-cause` scorer row, or record its acceptance with verdict-accept? It has been 'scorer work owed' since 0.79.0 and is the only single-keyword report_contains row across the seven answer keys.
- **VERDICT-Q-2** (asked run 15, 68d ago) — The re-baseline surface (~2,300 new/changed lines across src/verdict_mcp/small.py +1089, questions.py +326, anchors.py +169, clock.py +72, filed.py +99, reports.py +132, runner.py +470, harness.py +903, validate.py +314, plus eval/swebench.py +1311) was NOT audited this scoped run (caller scope was F-75 + run-14 next_run_focus). Schedule a dedicated baseline run over these modules before the next release that touches them?
- **VERDICT-Q-3** (asked run 15, 68d ago) — The profile's isolation check part (1) grep now matches the verdict-local local-model client (small.py) and will always 'fail' while that feature exists. Refine it to exclude the declared local-model client, or scope it to the test-execution path only?

_Answer with `verdict-answer verdict <Q-id> --answer "…"`; the next run reads the decision instead of asking again._

## Reading map (136 production modules, 85% covered overall)

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

- no agent ran: 36 bounded question(s) went to chat-120b — no exploratory charter, no archaeology, no adversarial reading of the suite
- the commit history: no origin was traced, and no `git log -S` was run
- 10 of 10 prior open finding(s) were carried unread, and 0 re-filed because the code they cite changed and no model looked at the change
- 8 file(s) and 24 function(s) were read; nothing else in the repository was
- claims the counterfactual could not reach — a probe that would not run leaves its finding a hypothesis, and an unproven severity is held at Minor for a reading and at Major for a failing test the model classified
- nothing outside the checkout was read — no database, no MCP tools, no production numbers — so a standing blocker that quotes one was NOT re-read
- 3 question(s) the model did not answer
- 712 candidate function(s) were never asked about: the cap of 24 function(s) was reached
- changed in the range and read by no question here, because none of it is program source: 11 configuration or data file(s), 9 document(s), 1 other file(s)
- 5 reading(s) this engine could not prove were listed as leads in the report, not filed — a lead is a question for a run that can judge it, not a finding

## Next run focus

- needs a model run — diff_over_limit: the range is larger than the caps this engine runs under; part of it was never read
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
- lead, unproven: .github/directory_branch.py:95 `plugin_tree` — Extra NUL sent to git update-index creates invalid empty entry when no files are kept
- lead, unproven: eval/backfill/faithful.py:38 `finding_of` — ID type mismatch causes StopIteration when finding ID is integer
- lead, unproven: eval/backfill/faithful.py:76 `main` — `--only` empty list ignored due to falsy check, causing all cases to be processed
- lead, unproven: eval/recall/build_cases.py:53 `main` — Missing '=' validation lets malformed run specs create cases with empty root paths
- lead, unproven: eval/recall/packet_recall.py:42 `_head` — Missing git error handling in _head leads to silent failure
- needs a model run — unexercised_changed_lines: 1875

## Notes

No Claude tokens were spent on this run. The verdict cannot improve on its own: a previous `fail` stays `fail`, and a previous `blocked` stays `blocked`, until something with judgment looks at it.

**Leads — read by a small model, not proven, not filed (5).** Each is a question for a run that can judge it; none is on the record.
- `scripts/check_structure.py:78` `git` — git() discards stdout on non‑zero exit when check=False (read as Major; the model did not answer with JSON)
- `scripts/check_structure.py:102` `is_shared_fake` — Off‑by‑one in is_shared_fake: directory itself not checked against SHARED_FAKE_DIRS (read as Major; probe_unsafe: argument 1 is not a literal (next(iter(m.SHARED_FAKE_DIRS))))
- `scripts/check_structure.py:185` `silent` — silent() misclassifies bare Name expression statements as non‑silent (read as Minor; probe_unsafe: argument 1 is not a literal (__import__('ast').Expr(value=__import__('ast').Name(id='x', ))
- `src/verdict_mcp/accept.py:210` `main` — Missing validation of --reason when using --revoke allows empty revocation reason (read as Minor; the model did not answer with JSON)
- `src/verdict_mcp/backfill.py:113` `_tree` — Silent failure of _tree returns empty list, hiding git errors (read as Major; the model did not answer with JSON)

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
