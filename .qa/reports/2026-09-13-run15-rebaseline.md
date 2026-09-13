# QA report — verdict · run 15 (re-baseline)

**VERDICT: pass with risks**

## Scope

- Range: `4dc006ad4bda31a5548de01648ad4e4a5d7a0427..4a918d8b4b786991cdbe45bde13bd9f3a8e9dc7e` · 88 files changed, 16835 insertions(+), 1727 deletions(-)
- Branch: `claude/new-session-bab9af` · measured 2026-09-13T04:44:37Z
- Harness: verdict-qa-mcp 0.88.0 · prompt 451a01dbac29 · `/Users/artjack/Projects/verdict/.claude/worktrees/new-session-bab9af/src/verdict_mcp/harness.py`
- Evidence drift: not measured — the previous state carries no evidence anchors — it was written by a verdict-finalize older than 0.83.0; this run anchors, the next measures
- Isolation check: **pass** — Profile 3-part check + guard-armed control, all measured this run. (1) `grep -rlE "requests\.|httpx|urlopen|boto3|psycopg|DATABASE_URL" tests/ src/` NOW matches src/verdict_mcp/small.py:89 and tests/test_small.py:195 — both non-live: small.py:89 is the new verdict-local local-model HTTP client (Model.ask), and tests inject FakeModel (test_small.py:74) / Flaky(small.Model) (:143) instead of calling it, while test_the_run_refuses_without_an_endpoint (:166) proves the run refuses with no endpoint; test_small.py:195 is the string literal 'httpx' inside a deterministic_kind assertion, not a call. So the suite makes no real network/DB/credential call. (2) pyproject.toml:93 testpaths=["tests"] — eval/fixtures seeded defects not collected; all 1172 ids under tests/. (3) After the facts gate run, `git status --porcelain` shows only `M .qa/test-ids.txt` (written by verdict-facts) and `?? .qa/findings/` (this run's finding files) — the checkout was never written to. CONTROL the guard is armed: live bash guard (VERDICT_STRICT=1) DENIES `git commit -am wip` (rc 2, names the checkout) and ALLOWS `cat README.md` (rc 0). NOTE: the profile's part-(1) grep heuristic is now stale — it flags the intentional verdict-local client; it needs scoping (see questions).

Re-baseline, run 15, over 4dc006a..4a918d8 (88 files, +16,835/-1,727; run_type/reason from verdict-facts: 're-baseline' / 'previous run was 7 days ago'). Caller scope: re-verify VERDICT-F-75 first, then run 14's next_run_focus as far as the run allows. I re-verified all 11 open findings from run 14's backlog by effect or by reading; I did NOT sweep the ~2,300 lines of new/changed product code for new defects — that is named in not_tested and next_run_focus.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 139.47s | 1172 passed in 138.99s (0:02:18) |
| `fixture_freshness` | pass | 0 | 0.1s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 1172, collected 1172
Test-id ledger: 1172 ids · +293 / −9 (set-diff, not summary arithmetic) — id lists truncated to 50 each
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable · 1 not run (tests cited in prose only, none declared as `verification_test`)
  - 10 open finding(s) cite no test id, so the harness cannot fix-verify them
  - nothing was run for VERDICT-F-26: each cites tests only in prose and declares none as `verification_test` — a node id in prose is text, not a citation; declare it to make the measurement count
Diff coverage: 3710/5656 changed lines executed (66%) across 51 file(s); 50 test(s) touch the diff
  - production 1971/3538 (56%) · test code 1739/2118 (82%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - 379 of them only in a subprocess the suite spawned — measured, but no test to name
  - eval/pin_check.py: unexercised lines 59, 72, 78, 80, 84, 109, 117, 121, 150, 158, 170-171, 258-259, 279, 287-288
  - eval/run_eval.py: unexercised lines 48, 59, 64-66, 148-261, 294-303, 305-308, 338-344, 385-392, 396, 398-406, 422, 428, 434, 459, 470-475, 481-527, 545-559, 570-573, 575-583, 585-586, 594-607 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/score.py: unexercised lines 215, 243, 280-281
  - eval/swebench.py: unexercised lines 38, 40-51, 53-58, 60-63, 65-66, 68-69, 74, 86, 94, 100, 113-114, 117, 119, 121-123, 125, 131, 138-139, 141-142, 144, 147-148, 151-152, 157, 159-170, 173-177, 180, 183, 191, 200, 226-230, 235-242, 245-248, 253-258, 261-262, 265-270, 272, 275, 279-287, 290, 292-300, 303-308, 311-312, 315, 320, 323, 329-330, 332-336, 338-350, 352, 360-363, 365-371, 373, 375-379, 381-382, 386, 388, 390, 393, 396, 409, 413, 427, 433-435, 438-439, 441, 443-444, 447, 452-474, 479, 481, 484-489, 492-496, 499, 501-504, 506-508, 511, 559-560, 563-564, 567, 579-580, 583-588, 590-600, 602-604, 607-614, 617-619, 621-631, 636, 640-642, 644-647, 649-668, 670-673, 676, 678-684, 686-687, 690, 698-699, 705, 709-716, 719, 721-728, 733-734, 738-739, 741-746, 761, 778, 786, 790, 801, 821, 829, 832, 834-837, 840, 872, 874, 879, 888-890, 922-932, 935, 938-940, 943-957, 960-964, 968-973, 975-978, 980-983, 985-987, 989-990, 992-994, 996-1003, 1006-1007, 1009-1016, 1019-1024, 1027-1032, 1035, 1039-1045, 1047-1049, 1052, 1055-1061, 1064-1073, 1076, 1079, 1081, 1083-1084, 1088, 1092-1116, 1119-1123, 1126-1142, 1145, 1147-1149, 1152, 1157-1166, 1169, 1173, 1177, 1198, 1234, 1236, 1249-1255, 1258-1268, 1270-1273, 1276-1277, 1281-1307, 1310-1311 — functions never entered: sh, git, now_utc, dataset_rows, row_for, cmd_select, instances, spec_for, workdir, mirror_of
  - eval/sweep.py: unexercised lines 1-225 (no test executed it, and no subprocess the suite spawned recorded a line of it)
  - eval/usage.py: unexercised lines 19, 21-24, 26, 30, 37, 42, 60, 80, 90, 102
  - hooks/report_open_findings.py: unexercised lines 44-45
  - src/verdict_mcp/__init__.py: unexercised lines 15, 19-25
  - src/verdict_mcp/accept.py: unexercised lines 48, 52
  - src/verdict_mcp/anchors.py: unexercised lines 72-73, 104, 154
  - src/verdict_mcp/filed.py: unexercised lines 90-91
  - src/verdict_mcp/gate.py: unexercised lines 45-46, 52
  - src/verdict_mcp/harness.py: unexercised lines 894, 926, 966, 993, 996, 1000, 1003, 1039, 1045, 1052, 1100, 1113, 1118, 1544, 1601-1604, 2380-2381, 2398-2401, 2444, 2496, 2498 — functions never entered: measure_diff_coverage
  - src/verdict_mcp/issues.py: unexercised lines 44
  - src/verdict_mcp/questions.py: unexercised lines 56, 70, 96-98, 105-106, 120, 169, 173, 201-203, 214, 260, 282-283, 302-303, 311-312, 314-315, 318-320, 326
  - src/verdict_mcp/reports.py: unexercised lines 40-41, 47, 67-68, 93-94, 104, 111-112, 122-123, 125
  - src/verdict_mcp/runner.py: unexercised lines 62-63, 367, 448-449, 451, 492, 539-540, 565, 589, 593, 600, 607, 612, 661-662, 664, 667, 670, 673-675, 690, 692
  - src/verdict_mcp/server.py: unexercised lines 30-31, 153-154, 159
  - src/verdict_mcp/small.py: unexercised lines 30, 32-44, 46-62, 64-66, 71, 78, 82-83, 85, 89-95, 98, 107-108, 116, 128-129, 137, 140, 143, 148, 172, 196, 213, 229, 254, 257, 270, 313, 337, 339-340, 343, 349, 356, 360, 371-372, 374, 380, 391, 406-407, 412-413, 417, 427, 454, 458, 462, 468, 483-485, 489-490, 493, 495-501, 504, 510-515, 517, 520, 526-532, 534-535, 538, 545-546, 549, 558, 565-566, 580, 598-606, 609, 629, 633-639, 641-647, 649, 660, 663, 689, 692-697, 700, 707-712, 714-716, 719, 725, 739, 756-761, 771-774, 777-785, 792, 796-799, 801, 814, 836-837, 856, 860-869, 871, 874-875, 877-881, 884, 894, 896-900, 902-904, 906-907, 909-911, 913, 915-923, 926, 929-933, 935-937, 947-954, 957-958, 961, 963, 966, 993-994, 996-997, 999, 1002, 1005, 1014, 1016-1025, 1028, 1039, 1070, 1078-1082, 1084, 1088-1089 — functions never entered: Model.ask, gate_of, failures_of, rerun_failures, ids_in_report, test_files, brittle_findings, source_of_test, changelog_excerpt, classify
  - src/verdict_mcp/validate.py: unexercised lines 273, 304, 323, 376, 381-382, 391, 393, 744-745, 777-778, 780, 782
  - tests/test_anchors.py: unexercised lines 11-12, 14-18, 20, 23, 31, 36, 46, 52, 60, 74, 84, 96, 114, 151, 165, 177, 191, 206, 231, 241, 261, 277, 291, 302, 308
  - tests/test_artifact_check.py: unexercised lines 91
  - tests/test_census.py: unexercised lines 149
  - tests/test_clock.py: unexercised lines 9-11, 13, 15, 17-18, 21, 37, 44, 48, 54, 60, 72, 78, 84, 90
  - tests/test_filed.py: unexercised lines 11-16, 18-21, 23-24, 27, 30, 40, 45, 56, 61, 69, 79, 96, 105, 124, 140, 153, 160, 186, 202, 237, 251, 268, 292, 298
  - tests/test_gate.py: unexercised lines 530
  - tests/test_harness.py: unexercised lines 11, 551, 569, 803, 819, 824, 978, 1037
  - tests/test_hooks.py: unexercised lines 89, 109, 124, 860, 877-878, 996, 1039, 1058, 1066, 1068, 1087, 1089, 1101
  - tests/test_limits.py: unexercised lines 10-12, 14-18, 20-21, 24, 31, 37, 42, 54, 61, 87, 100, 109
  - tests/test_pin_check.py: unexercised lines 11-13, 94, 113, 143, 162, 175, 207, 246, 270, 282
  - tests/test_questions.py: unexercised lines 11-15, 17-21, 23-25, 28, 34, 39, 47, 57, 64, 79, 87, 100, 121, 132, 156, 164, 171, 187
  - tests/test_reading_map.py: unexercised lines 12-14, 16-18, 20-23, 27, 32, 47, 55, 73, 87, 121, 126
  - tests/test_release_workflow.py: unexercised lines 57
  - tests/test_report_names.py: unexercised lines 9, 11-12, 15, 21, 30, 41
  - tests/test_reports.py: unexercised lines 9-10, 12-13, 15, 21, 27, 34, 50, 57, 64, 70
  - tests/test_runner.py: unexercised lines 371, 394, 411, 424, 432, 460
  - tests/test_score.py: unexercised lines 454, 460, 465, 501, 520, 536
  - tests/test_session_env.py: unexercised lines 11-13, 15-19, 22, 26, 34, 47, 58, 67, 80, 91, 99, 106, 114, 140, 153, 163
  - tests/test_skills.py: unexercised lines 10-11, 13-15, 19, 29, 37, 45, 61, 68
  - tests/test_small.py: unexercised lines 9-10, 12, 14-17, 19, 34, 42, 53, 63, 74, 77, 80, 85, 89, 103, 109, 116-117, 124, 130, 142, 158, 166, 173, 178, 185, 191, 201, 210, 216, 223, 232, 239, 245, 269, 279, 293, 305, 318, 339, 352, 370, 376, 391, 400
  - tests/test_swebench.py: unexercised lines 10-12, 14, 16-18, 20, 39, 48, 53, 62, 69, 87, 94, 104, 134, 139, 154, 165, 183, 211-212, 216, 232, 236
  - tests/test_sweep.py: unexercised lines 10-15, 17-19, 21-23, 26, 31, 60, 72, 76, 98, 110, 117, 148
  - tests/test_template.py: unexercised lines 10-12, 14, 16, 18, 21, 27, 35, 58, 82, 100, 110
  - tests/test_usage.py: unexercised lines 11-13, 15-17, 20, 25, 34, 46, 66, 80, 85, 96, 106, 112
  - tests/test_verification.py: unexercised lines 103, 129, 139, 154, 173, 183, 217, 478

## Risks

The Critical release blocker VERDICT-F-75 is RESOLVED and fix-verified by counterfactual (old hook allows every git-disarm shape, HEAD hook denies all six mutating verbs, real git confirms the mutations, controls still deny). No open Blocker/Critical/Major remains. Residual: (1) VERDICT-F-74 Minor open (a scorer row that scores the word 'trigger', not the discipline); (2) a large new-code surface unaudited this scoped run; (3) the profile's isolation grep is stale against the new verdict-local feature (isolation still holds in fact — the suite injects fakes and refuses without an endpoint).

## Findings — REGRESSED first (1 open of 12 tracked · 1 accepted)

### VERDICT-F-75 — RESOLVED — Critical/P1 — age 8d

The bash guard reads a git flag or sub-verb name ANYWHERE in the argument list, whatever role it plays there, so one ordinary token disarms the check for every mutating verb: `git commit -m "--dry-run"` really commits and `git branch -D <branch> list` really deletes, both with the guard's blessing
- FIXED in 0.80.0 (79f313c). hooks/enforce_bash_scope.py:530 `_git_operands` now splits (flags, operands) walking argv as git does — an option value is consumed (`-m`,`--message`,`-F`,`-C` and bundled `-am`), so a token in a value position can no longer be read as a flag. :585 the `--dry-run` exemption is a flag in a flag's position and `--check` only for apply/am; :595 the read-only sub-verb must be operands[0]; :591 a mutating flag outranks a listing flag.
- COUNTERFACTUAL BY EFFECT (scratchpad/probe_f75.py): old hook at 4dc006a vs new hook at HEAD, each piped a PreToolUse Bash event with VERDICT_STRICT=1, plus real git run in a throwaway repo under mktemp (never this checkout). For every acceptance-axis verb the OLD hook ALLOWED (rc 0) and the NEW hook DENIES (rc 2): `git commit -m --dry-run` (git commits [main]--dry-run), `git stash push -m --dry-run`, `git branch -D keepme list` (git deletes keepme), `git tag -d v9 list`, `git worktree remove <wt> list`, `git notes add -m x list`, `git commit -am --dry-run`, `git push origin main --check`, `git branch list`, `git branch -M keepme renamed`.
- CONTROL rows (guard armed, not blanket-denying): plainly-denied mutators still DENY under both hooks — `git commit -am wip`, `git stash`, `git reset --hard HEAD`. And a genuine dry run still ALLOWS under the new hook — `git commit --allow-empty --dry-run -m x` -> rc 0. Zero mismatches across 20 rows.
- GUARD TEST at HEAD: tests/test_hooks.py GIT_SHAPES (:996-1036) asserts each shape against the guard AND against real git in a throwaway checkout in two columns (test_the_guard_agrees_with_the_git_that_would_run + test_real_git_changes_what_this_matrix_claims); both in the 1172-passing suite. Cited param passes at HEAD; the guard test did not exist at 4dc006a (previous_sha), so no harness fail->pass block exists — the fix is verified by the counterfactual above.
- Root cause: _check_git decided read-only-ness by set membership over a flat token list; membership is a property of the string, role is a property of position. 0.80.0 replaced the flat scan with a position-aware operand split.
- Class: {"pattern": "role-blind token membership decides a whole command's classification", "sites": ["hooks/enforce_bash_scope.py:487 (was) \u2014 now :585 flag-position dry-run", "hooks/enforce_bash_scope.p

RESOLVED and fix-verified by counterfactual. The Critical release blocker of run 14 is closed: the guard now parses git argv positionally, so an allowed token in a value or trailing-operand position no longer stands the authorization decision down. Proven by running the pre-fix hook (4dc006a) and the HEAD hook side by side against the same commands with real-git effect measured in a throwaway repo — old allows every disarm shape, new denies all six mutating verbs, controls still deny and a real --dry-run still passes. No harness verification block: the guarding matrix test postdates the previous SHA, so a fail->pass measurement is structurally unavailable; the counterfactual carries it.

### VERDICT-F-58 — RESOLVED — Major/P2 — age 10d

The instrument control §3 prescribes for the stale-bytecode fault cannot fire in the ordering that produced VERDICT-F-50: re-running an injection you already watched fail reads FAIL while the shadowed bytecode is still what runs
- FIXED in the agent contract (0.87.0/0.88.0 rewrite of §3). agents/verdict.md:242-248: 'the check that can is an instrument control, and its DIRECTION is the whole check: put the original source back and re-run. If the failure you injected persists on clean source, you are measuring the cache. Re-running an injection you have already watched fail proves nothing in the ordering that produced VERDICT-F-50 — the stale bytecode IS that injection, so it fails again on it and the control cannot fail. A control that passed because the fault was excluded by other means (subprocess arms, the cache already swept) has not been exercised; say which it was.'
- The fix reverses the control direction (clean-source re-run, not injection re-run) and names the subprocess/cache-swept exclusion — exactly the datum run-14 next_run_focus[5] said to supply.
- LIVE DEMONSTRATION this run: the corrected control was exercised in the F-60 re-injection (scratchpad/reinject_f60.sh step 3) — after watching the injected mutation fail, I restored clean source, swept cache, re-ran, and the suite passed (8/8), which is the direction that can actually fail if the instrument is stale. Verified by reading + this exercise; no unit test guards contract prose (fix_verified: false).
- Root cause: §3's prescribed control ('re-run the injection you watched fail') cannot fail because stale bytecode re-runs the same injection. The contract now prescribes the opposite direction (restore clean source and re-run) and requires naming when the fault was excluded by other means.

RESOLVED. The agent contract's §3 instrument control now runs in the direction that can fail — restore clean source and re-run — and requires the tester to say when a control passed only because the fault was excluded by other means. Confirmed by reading the corrected prose and by exercising the corrected control in this run's F-60 re-injection.

### VERDICT-F-78 — RESOLVED — Major/P2 — BRITTLE_TEST — age 8d

Two of the four release-workflow tests read the job text including COMMENTS, so the sha256 check that VERDICT-F-73's fix rests on can be deleted and replaced by a comment that merely names it, and all four tests stay green
- FIXED in this range. tests/test_release_workflow.py: all four tests now read `_commands(_registry_job())` (the comment-stripping filter) — three changed from raw `_registry_job()` (git diff 4dc006a..HEAD shows test_the_download_is_checksummed_before_it_runs:40, test_a_registry_failure_is_visible:52, test_the_job_holds_no_more_than_it_needs:67). A new instrument-control test_the_comment_filter_is_what_every_test_reads (:57) asserts a commented check satisfies none of them.
- RE-INJECTION BY EFFECT: copied release.yml + the test to a scratch tree, commented out the real `sha256sum -c -` line (line 144) leaving a comment that still NAMES the check, ran `pytest test_the_download_is_checksummed_before_it_runs` -> 1 failed: `AssertionError: the checksum is declared but never checked`. At run 14 (4dc006a) that same mutation left all four tests green.
- GUARD: test_the_comment_filter_is_what_every_test_reads and the four hardened tests are in the 1172-passing suite.
- Root cause: `_commands()` (comment filter) existed but was applied by only the `latest` test; the two security-relevant assertions read the raw job, so a commented line satisfied `"sha256sum -c" in job`. Fix: every test reads `_commands()`, plus an instrument-control test.

RESOLVED, fix-verified by re-injection. The supply-chain check (F-73) is now genuinely guarded: commenting the checksum makes the guarding test fail, which it did not at run 14.

### VERDICT-F-21 — ACCEPTED — Major/P2 — age 4d

The run-history chain's anti-fabrication signal can still be shed by deleting data, and the gate then exits 0: 0.66.0 moved the ratchet into outcomes.json, but the anchor is itself unauthenticated, so removing one JSON key restores `unchained` with the whole track record intact
- Re-reported open per the contract; the fold to `accepted` is verdict-finalize's to write, never the tester's. .qa/accepted.json records it accepted by ArtJack on 2026-09-05 citing 'DECISIONS.md 2026-09-02'.
- Unchanged as a defect and untouched by this range: `git log 0892869..4dc006a --oneline -- src/verdict_mcp/gate.py src/verdict_mcp/state.py` shows gate.py was not touched at all and state.py only for the accepted-risk fold, not for authenticating the anchor.
- Not re-measured this run.
- _Accepted risk — 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to._

### VERDICT-F-26 — RESOLVED — Minor/P2 — age 11d

Fix verification picks its test by scraping any pytest node id out of a finding's prose evidence, so a mis-scraped id that fails at HEAD force-reopens a correctly-resolved finding over the tester's judgment
- FIXED in 0.84.0 by redesign: a prose-scraped node id is NEVER run. src/verdict_mcp/harness.py:645-657 marks a `first_cited` (prose) pick `selected_by:'unselectable'` and runs nothing; :761-772 a fail at HEAD refuses a resolution only for a CHOSEN test; :773-784 a fail->pass on a prose-only test is `not_weighed`. Only an explicit `verification_test` (or added_this_run) is weighed (:462).
- DEMONSTRATED by this run's own facts.json: F-26 cites test_the_state_validator_keeps_checking_after_a_malformed_entry only in prose; facts.verification['VERDICT-F-26'] = selected_by 'unselectable', at_previous/at_head 'unavailable', 'not run: 1 test cited in prose, none declared as verification_test'. The mis-scrape can no longer reopen a finding because prose ids are never executed.
- GUARD: tests/test_verification.py at HEAD has six tests for this — test_a_node_id_scraped_from_prose_is_never_run, test_a_single_prose_citation_is_not_run_either, test_the_collected_citation_wins_over_the_scraped_one, test_an_explicit_citation_leads_whatever_the_prose_says, test_a_prose_pick_among_several_is_not_run_at_all, test_a_prose_pick_that_arrives_by_hand_still_confirms_nothing; all in the 1172 suite.
- Verified by reading + the facts demonstration, not by re-injection (fix_verified: false). The next_run_focus[3] decision was taken: prose is no longer authoritative for selection.
- Root cause: selection scraped any node id from prose and ran it; 0.84.0 makes prose citations unselectable (nothing runs) and weighs only an explicitly-declared verification_test.

RESOLVED by the 0.84.0 verification redesign. A node id merely quoted in prose is never run, so it can no longer force-reopen a correctly-resolved finding — demonstrated on F-26 itself in this run's facts. Verified by reading the harness and six guard tests; not re-injected.

### VERDICT-F-60 — RESOLVED — Minor/P2 — age 10d

Eleven rules shipped in 0.74.0 survive mutation against the whole suite, including the only call site of the `__pycache__` sweep, the whole UTF-8 stderr fix, both `_ago` boundaries and `run_date`'s offset normalisation
- The two real survivors run 14 named ((8) one-minute, (9) age_h==1.05) now have guarding tests: tests/test_harness.py:1037 test_one_minute_is_a_minute_not_seconds and :1023 test_the_retry_marker_says_the_age_it_recorded[1.05-1.1 hours ago-1 hour ago]; (8) is also pinned in eval/pinned_mutants.json ('0.80.2 S4 sweep, F-60 (8): one minute reads as seconds').
- RE-INJECTION BY EFFECT (scratchpad/reinject_f60.sh, isolated: git-archive HEAD scratch tree, PYTHONPATH ahead of the editable install verified via harness.__file__ inside the scratch, PYTHONDONTWRITEBYTECODE=1, __pycache__ swept between arms). CONTROL clean = 8 passed. Inject `minutes < 1`->`minutes < 2`: test_one_minute_is_a_minute_not_seconds FAILS (1 min reads as seconds). RESTORE clean, re-run = 8 passed (the corrected §3 control direction). Inject `age_h >= 1.05`->`age_h > 1.05`: test_the_retry_marker_says_the_age_it_recorded[1.05-...] FAILS.
- The remaining survivors are correctly disposed of per run 14's lesson: (10) run_date's `.replace("Z",...)` is an EQUIVALENT mutant (datetime.fromisoformat parses naive stamps; a -07:00 stamp has no Z), struck from the survivor list; (6) and (7) are the UTF-8 stderr / Windows-only behaviour a macOS suite structurally cannot observe (not_tested this run).
- Root cause: the 0.74.0 rules were pinned by a hand-written catalogue that missed these lines; the two real boundaries now have tests and (8) is a pinned mutant. (10) is equivalent; (6)(7) are platform-unmeasurable here.

RESOLVED. The two survivors worth a test — the _ago one-minute and 1.05-hour boundaries — now have guarding tests, fix-verified by isolated re-injection of both (clean control passes, each mutation flips its test, clean-source re-run passes again). The equivalent mutant (10) is struck; the Windows-only (6)(7) are recorded as platform-unmeasurable.

### VERDICT-F-65 — RESOLVED — Minor/P2 — age 10d

The pinned-mutant catalogue is assembled from the finding list, not from the code, so its kill rate is a rate over the rules somebody remembered to list
- FIXED in 0.80.2 by building the code-enumerated view F-65 asked for. eval/sweep.py (new, commit 5612e9d 'a code-enumerated sweep for F-65') docstring: 'A code-enumerated mutation sweep over named functions... take every line of a named function, break it every way eval/mutate.py's operators know, run the whole suite, and list what survives — so the denominator is the code, not a memory of it.' It cites VERDICT-F-65 by name.
- RUN and acted upon: eval/sweeps/2026-09-06-f65.json holds 155 enumerated mutants; commit cd1ddcc '0.80.2: the first sweep's survivors — 22 real, judged one by one, seven pinned'. The code-enumerated denominator found 22 real survivors the hand-written catalogue could not have, which is precisely F-65's point.
- Nuance recorded: eval/pinned_mutants.json (175 entries, all finding-labelled) remains a regression PIN-list by design; the resolution is that the code-enumerated MEASUREMENT (sweep.py) now exists alongside it. Verified by reading the tool + artifact + commits; the sweep was not re-run this run (a full campaign is the standing not_tested), so fix_verified: false.
- Root cause: pin_check.py's catalogue is hand-written from findings, so its kill rate measured only remembered rules. 0.80.2 adds eval/sweep.py, a code-enumerated campaign whose denominator is the function's lines.

RESOLVED. The code-enumerated sweep F-65 named as missing was built (eval/sweep.py), run over 155 mutants, and its 22 real survivors judged and partly pinned. The regression catalogue stays finding-derived by design; the measurement that answers 'would a test notice a change anywhere in this function' now exists. Read, not re-run.

### VERDICT-F-66 — RESOLVED — Minor/P3 — age 10d

The 'class that did not exist before' is two of three, not three: the catalogue's third call-site mutant shares its anchor line with H3 and produces H3's behaviour with an unused call bolted on
- FIXED in 0.80.0. CHANGELOG.md:632-638: 'VERDICT-F-66 — the mislabelled call-site entry is gone. Of the three catalogue entries presented as "a class that did not exist before", one was another entry's behaviour with a discarded call bolted on. It is replaced by a real one: verdict-finalize's only call to check_artifacts, whose deletion left all eight of that check's tests green. The call site now has a test of its own.'
- eval/pinned_mutants.json now carries the legitimate replacement '0.80.0 C18 F-66: the post-finalize artifact check is never called (its body...)' alongside the two genuine F-57 call-site mutants ('the bytecode sweep's only call site is deleted', 'the UTF-8 stderr pin is never called by the bash guard'); the H3-duplicating entry is gone.
- Verified by reading CHANGELOG + the catalogue; the campaign was not re-run this run (fix_verified: false).
- Root cause: one of three 'call-site class' catalogue entries duplicated H3's anchor with a discarded call; 0.80.0 removed it and added a real call-site mutant (check_artifacts) with its own test.

RESOLVED. The mislabelled call-site catalogue entry is gone and replaced by a genuine one (verdict-finalize's only call to check_artifacts) that has its own test. Read, not re-run.

### VERDICT-F-76 — RESOLVED — Minor/P2 — age 8d

The same role-blind membership test denies read-only git commands the sub-verb set was written to allow: `git branch --show-current`, `git branch -v`, `git tag --list` and `git config --get-regexp` are all refused as checkout mutations
- FIXED in 0.80.0. _GIT_READONLY_FLAGS (hooks/enforce_bash_scope.py:116-126) now holds the dashed read-only spellings per verb, checked at :597-598 after mutating flags are ruled out.
- COUNTERFACTUAL (scratchpad/probe_f75.py): OLD hook at 4dc006a DENIED and NEW hook ALLOWS: `git branch --show-current`, `git branch -v`, `git tag --list`, `git config --get-regexp user`, `git branch --list keepme`. `git stash list` allowed under both. Real-git effect: all no-op (read-only), confirming these are genuine false positives the fix removed.
- GUARD: the same GIT_SHAPES matrix asserts these five shapes as denied=False (must ALLOW) in the same table as the F-75 deny rows (tests/test_hooks.py:1022-1033); green in the 1172 suite.
- Root cause: read-only spellings were stored as sub-verbs matched anywhere; 0.80.0 split them into position-checked sub-verbs and per-verb read-only FLAG sets.

RESOLVED, fix-verified by counterfactual — the friction side of F-75. The read-only spellings the old membership test wrongly refused now pass, while the mutating forms are still denied (verified in the same probe as F-75).

### VERDICT-F-77 — RESOLVED — Minor/P3 — age 8d

Every non-dash argument of a generic mutator is treated as a path, so a mode or owner operand is resolved against the cwd: `chmod +x <scratch>/x.sh` is denied because `+x` resolves to `<checkout>/+x` - and so is `chmod +x .qa/x.sh`, inside the QA root the agent may write
- FIXED in 0.80.0. _MODE_FIRST = {chmod,chown,chgrp,install} (hooks/enforce_bash_scope.py:68); the _MUTATORS branch (:817-823) drops the first operand for these before treating the rest as paths.
- COUNTERFACTUAL (scratchpad/probe_f77.py): OLD hook at 4dc006a DENIED all of `chmod +x <scratch>/x.sh`, `chmod +x <checkout>/.qa/x.sh`, `chmod 755 <scratch>/x.sh`, `chown nobody <scratch>/x.sh`; NEW hook ALLOWS all four. CONTROL: `chmod 777 <checkout>/src/verdict_mcp/state.py` still DENIES under both — the file behind the mode is still a target.
- GUARD: tests/test_hooks.py::test_a_mode_operand_is_not_a_path (:1101) asserts the four allows incl. `.qa/x.sh`, and that a chmod of src/ still denies; green in the 1172 suite.
- Root cause: chmod/chown's first operand is a mode/owner, not a path; the generic mutator loop resolved it against the cwd. 0.80.0 skips the first operand for _MODE_FIRST commands.

RESOLVED, fix-verified by counterfactual. A chmod inside the QA root the tester may write is now allowed, and a chmod of the code under test is still denied.

### VERDICT-F-79 — RESOLVED — Minor/P3 — age 8d

The import census matches `from`/`import` as text over added lines, so prose in a module docstring is reported as an undeclared dependency - this range's only census lead is a sentence
- FIXED in 0.80.0. src/verdict_mcp/census.py:_PY_IMPORT is now anchored `^[ \t]{0,8}(?:from|import)[ \t]+([A-Za-z_]\w*)(?=[ \t]*(?:$|[.,;]|\bimport\b|\bas\b|#))` with a comment naming VERDICT-F-79.
- REGEX DIFFERENTIAL BY EFFECT (python, both regexes over the docstring line): OLD `^\s*(?:from|import)\s+([A-Za-z_]\w*)` matched the English word 'a' from `from a `releases/latest` URL, ...` and `from a module we downloaded`; NEW regex matches neither, while both still catch real imports (import os -> os; from pathlib import Path -> pathlib; import re,sys -> re; indented import json -> json; from collections.abc import Mapping -> collections).
- No unit test cited: this is a census heuristic; verified by the regex differential rather than by a collected test.
- Root cause: the import census matched from/import as loose text; docstring prose beginning 'from a ...' scored the article 'a' as a dependency. 0.80.0 anchors the pattern and requires a real import tail.

RESOLVED, fix-verified by regex differential. The census no longer reads docstring prose as an undeclared dependency; real imports are still detected.

### VERDICT-F-74 — STILL_OPEN — Minor/P2 — age 8d

The `trigger-separated-from-cause` eval row scores the presence of the single word 'trigger', so a report that never separates trigger from cause earns the point - the same shape run 12 filed against the bytecode row
- STILL OPEN at HEAD (fresh evidence, this range changed eval/expected-cause.json but not this row's mechanism). eval/expected-cause.json:43-49 the row is `{"key":"trigger-separated-from-cause","type":"report_contains","terms_all":["trigger"]}` — a single keyword.
- eval/score.py:371-387 scores report_contains by plain substring: `missing = [t for t in terms if t.lower() not in lowered]`, point if none missing. With terms_all == ['trigger'], any report containing the word 'trigger' anywhere earns the point without separating trigger from cause.
- CHANGELOG 0.79.0 still records this as owed ('F-74 ... is scorer work owed to the eval'); the eval corpus was not run this run (no live API), so this is verified by reading the key + scorer, not by scoring a report.
- Never measured — no `verification_test` declared
- Root cause: the row asserts presence of one keyword rather than the discipline (a report that names a trigger without distinguishing it from the cause still scores). Scorer work owed.
- Class: {"pattern": "single-keyword report_contains row scores vocabulary not discipline", "sites": ["eval/expected-cause.json:43-49 \u2014 the only single-keyword report_contains row across the seven answer 

STILL_OPEN. The scorer row is unchanged in mechanism at HEAD — one keyword, plain substring — so a report that never separates trigger from cause still earns the point. An instance, not a pattern (the only single-keyword report_contains row), hence Minor. Verified by reading; the eval was not run (no live API here).


## Accepted risks (1)

_The maintainer's decision, recorded with `verdict-accept`, never the tester's: each is a real defect whose fix was declined, with the reason and where the decision is written down. Out of the open counts and the release blockers; not out of sight._

- **VERDICT-F-21** (Major/P2, age 4d) — accepted 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to.


## Track record

78 findings tracked across this project's history · 60 settled, 18 still undecided.

| Confidence claimed | Held up | of those, measured | Withdrawn | Rate |
|---|---|---|---|---|
| proven | 54 | 0 | 0 | 100% |
| probable | 3 | 0 | 0 | _not yet_ |
| unstated | 3 | 0 | 0 | _not yet_ |

| Proof method | Held up | of those, measured | Withdrawn | Rate |
|---|---|---|---|---|
| counterfactual | 1 | 0 | 0 | _not yet_ |

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

- **VERDICT-Q-1** (asked run 15, 0d ago · about VERDICT-F-74) — VERDICT-F-74 (Minor): fix the single-keyword `trigger-separated-from-cause` scorer row, or record its acceptance with verdict-accept? It has been 'scorer work owed' since 0.79.0 and is the only single-keyword report_contains row across the seven answer keys.
- **VERDICT-Q-2** (asked run 15, 0d ago) — The re-baseline surface (~2,300 new/changed lines across src/verdict_mcp/small.py +1089, questions.py +326, anchors.py +169, clock.py +72, filed.py +99, reports.py +132, runner.py +470, harness.py +903, validate.py +314, plus eval/swebench.py +1311) was NOT audited this scoped run (caller scope was F-75 + run-14 next_run_focus). Schedule a dedicated baseline run over these modules before the next release that touches them?
- **VERDICT-Q-3** (asked run 15, 0d ago) — The profile's isolation check part (1) grep now matches the verdict-local local-model client (small.py) and will always 'fail' while that feature exists. Refine it to exclude the declared local-model client, or scope it to the test-execution path only?

_Answer with `verdict-answer verdict <Q-id> --answer "…"`; the next run reads the decision instead of asking again._

## Reading map (62 production modules, 83% covered overall)

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

- The re-baseline code surface: ~2,300 new/changed lines across src/verdict_mcp/small.py (+1089, verdict-local), questions.py (+326), anchors.py (+169), clock.py (+72), filed.py (+99), reports.py (+132), runner.py (+470), harness.py (+903), validate.py (+314), and eval/swebench.py (+1311). The caller scoped this run to F-75 + run-14's next_run_focus; these modules were read only where a carried finding pointed into them (harness verification logic, census.py, small.py's isolation match). They are covered by the 1172-test suite and CI but were NOT independently QA-audited for new defects this run.
- The Windows half of the CI matrix (ubuntu + windows x py3.10 + py3.13). Not testable on this machine. VERDICT-F-60's (6)/(7) UTF-8-stderr/Windows behaviour is structurally unobservable here and was read, not run.
- The eval corpus and every prompt-scored row, including VERDICT-F-74's. No model was run: the eval needs live API calls this environment excludes. F-74 is verified by reading the key + scorer, not by scoring a report.
- A code-enumerated mutmut/sweep campaign over src/verdict_mcp/harness.py (owed since run 11). eval/sweep.py now exists (F-65) but a full campaign is hours and was not run; the F-60 boundaries were re-injected individually instead.
- The 155-mutant code-enumerated sweep (eval/sweeps/2026-09-06-f65.json) was read, not re-run; F-65's resolution rests on the tool + artifact + commits, not a fresh sweep.
- The pinned sha256 in .github/workflows/release.yml (mcp-publisher v1.8.1) was NOT verified against the upstream artifact — Security-Pass is disabled and the profile forbids running the release workflow. Shape verified; value taken on trust.
- The Action's `run` mode (--dangerously-skip-permissions, bot commit) and both publish workflows end to end. Forbidden by the profile; reviewed by reading only.
- `git push` reachability through a smuggled `--dry-run` token — no remote to push to and pushing is forbidden; the other five verbs were proven in a throwaway repo. NOTE: at HEAD `git push origin main --check` is denied by the guard (probe_f75.py), so the 0.80.0 fix closes the shape run 14 left open.
- bsdtar: `_gnu_tar()` resolves to Homebrew gtar here; macOS stock /usr/bin/tar (bsdtar) was not swept this run (run 13's F-67 covered it, resolved).

## Fix order

1. Nothing blocks a release: F-75 and every other run-14 finding is closed. 2. VERDICT-F-74 — decide fix-or-accept (Minor). 3. Baseline the new modules before the next release that changes them. 4. Update the profile isolation heuristic.

## Next run focus

- Baseline the re-baseline surface: a dedicated run over src/verdict_mcp/small.py (verdict-local), questions.py, anchors.py, clock.py, filed.py, reports.py, and eval/swebench.py — none has had an independent QA pass. Weight small.py (the local-model client with a real urlopen and env-file reading) and questions.py (a new second-pen control surface) first.
- Settle VERDICT-F-74: change eval/expected-cause.json:43-49 to score the discipline, or verdict-accept it. Carrying it a run longer is the one option that costs something and settles nothing (the same logic that closed F-26 this run).
- Run the code-enumerated campaign over harness.py via eval/sweep.py (now proven) — scope it to the date/verification/outcome functions, ~90s/mutant, or it will not be run again.
- Refine the profile's isolation part-(1) grep so it stops flagging the verdict-local client (small.py) as a network dependency, or replace it with a suite-level no-live-call assertion.

## Notes

Verdict is `pass with risks`, not `pass`: the gates are green and no Critical/Major is open, but a re-baseline that re-verified the prior backlog without auditing ~2,300 new lines cannot honestly claim clean coverage (principle 7). 10 of 11 open findings resolved this run; F-21 stays accepted (untouched). Six resolutions are fix-verified by effect (F-75/76/77/79/60 by counterfactual, F-78 by re-injection); four are verified by reading the redesigned code + guard tests (F-26/58/65/66) with fix_verified:false, because a full re-injection/campaign was out of scope or needs live tooling. No harness `verification` block exists for the resolved guard findings: their guarding tests postdate the previous SHA (4dc006a), so a fail->pass measurement is structurally unavailable — the counterfactuals carry them, recorded in each finding's evidence and scratchpad probes.

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
