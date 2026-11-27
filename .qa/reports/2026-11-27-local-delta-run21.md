# QA report — verdict · run 21 (delta)

**VERDICT: pass with risks**

## Scope

- Range: `88f54dc..d163e8c` · 39 files changed, 3599 insertions(+), 5804 deletions(-)
- Branch: `qa/run-21` · measured 2026-11-27T18:01:47Z
- Harness: verdict-qa-mcp 0.95.0 · prompt 619dd69832f4 · `/Users/artjack/Projects/verdict/.claude/worktrees/qa-run-21/src/verdict_mcp/harness.py`
- Judge: verdict-local · model `local:chat-120b` · 49 call(s), 78812 token(s) · 5 question(s) unanswered · no Claude tokens spent
- Evidence drift: 4 of 10 anchored open findings cite code that moved or changed since the evidence was written (VERDICT-F-82, VERDICT-F-84, VERDICT-F-85, VERDICT-F-74)
- Isolation check: **pass** — measured before the gates: no plaintext .env file at the checkout root. The profile's own isolation steps were not executed: this engine runs the profile's gates and reads code, and writes nothing outside the QA root

verdict-local: 24 function(s) in 6 file(s) read one at a time by chat-120b, each in isolation, over the range `88f54dc..d163e8c`. The harness measured the repository; the model answered bounded questions about single functions.

## Gates

| Gate | Result | Exit | Duration | Summary |
|---|---|---|---|---|
| `suite` | pass | 0 | 409.75s | 3643 passed, 23 skipped in 403.64s (0:06:43) |
| `fixture_freshness` | pass | 0 | 0.1s | fixture_freshness: OK — pricer-delta.diff still describes the fixture pair (78 lines) |

Tests: passed 3643, skipped 23, collected 3666
Test-id ledger: 3666 ids · +80 / −0 (set-diff, not summary arithmetic) — id lists truncated to 50 each
Fix verification: 0 verified · 0 refused (cited test still fails at HEAD) · 0 measured but not verifiable
  - 10 open finding(s) cite no test id, so the harness cannot fix-verify them
Diff coverage: 935/1120 changed lines executed (83%) across 18 file(s); 50 test(s) touch the diff
  - production 504/536 (94%) · test code 431/584 (74%) — read production first; a test file's fixtures and `def` lines never carry a test context, so the blended number moves with the shape of the diff
  - 81 of them only in a subprocess the suite spawned — measured, but no test to name
  - src/verdict_mcp/census.py: unexercised lines 385-386, 446
  - src/verdict_mcp/census_aliases.py: unexercised lines 36, 83, 91-92, 128, 151
  - src/verdict_mcp/local_skip_close.py: unexercised lines 39-42, 107, 118-119, 132, 201
  - src/verdict_mcp/repro_shape.py: unexercised lines 35-37, 45-47, 57-58, 71-72, 84
  - src/verdict_mcp/runner_env.py: unexercised lines 170
  - src/verdict_mcp/small.py: unexercised lines 97, 101
  - tests/test_census.py: unexercised lines 264, 270, 285, 294, 300, 307, 314, 322, 333, 338, 345, 351, 362, 372, 379, 389, 393, 403, 409, 417, 425, 434, 441, 461, 472
  - tests/test_census_aliases.py: unexercised lines 10-12, 14, 16-19, 22, 30, 44, 53, 66, 77, 95, 103, 109, 118
  - tests/test_ci_surfaces.py: unexercised lines 11, 20, 134, 141, 154, 166, 186
  - tests/test_local_skip_close.py: unexercised lines 12-14, 16-24, 27, 32, 36, 38-39, 42, 47, 75, 80, 84, 89, 95, 115, 127, 142, 152, 164, 175, 189, 197, 202, 209, 223, 249, 269, 276, 295, 305
  - tests/test_replay.py: unexercised lines 830, 835
  - tests/test_repro_shape_note.py: unexercised lines 10-14, 16, 18-22, 24-26, 29, 38, 47, 58, 62, 72, 80, 87, 93-94, 103, 109, 119
  - tests/test_session_env.py: unexercised lines 12, 16, 179, 182, 191-192, 200-201, 209-210, 218-219, 225-226, 233-234
  - tests/test_skip_markers.py: unexercised lines 16-20, 22-24, 26, 71, 75, 88, 93, 101, 114, 131, 143, 153

## Risks

Every finding read here is a `hypothesis` unless a counterfactual proved it. This mode cannot see a defect that spans two functions, and it reads the suite only where the range touched it.

## Findings — REGRESSED first (1 open of 11 tracked · 1 accepted)

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

### VERDICT-F-80 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer/test_pricer.py:18 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: the suite collects nothing under the top-level directory of eval/fixtures/pricer/test_pricer.py (this run's test-id ledger, every gate green), and each cited line is a decorator, which pytest collects and then skips — a skip outside the suite removes no coverage it has
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-81 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: reason="temporarily disabled 2026-05-02 - flaky?"
- eval/fixtures/pricer_rev_b/test_pricer.py:17 — skip marker with reason 'reason="temporarily disabled 2026-05-02 - flaky?"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: the suite collects nothing under the top-level directory of eval/fixtures/pricer_rev_b/test_pricer.py (this run's test-id ledger, every gate green), and each cited line is a decorator, which pytest collects and then skips — a skip outside the suite removes no coverage it has
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-82 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "not a git checkout: the directory reads the repository, so this needs one"
- tests/test_directory_policy.py:68 — skip marker with reason '"not a git checkout: the directory reads the repository, so this needs one"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_directory_policy.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Cited code moved since the evidence was written: tests/test_directory_policy.py:68 (now line 71)
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-83 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_hooks.py:195 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- tests/test_hooks.py:219 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_hooks.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-84 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar
- tests/test_hooks.py:1246 — skip marker with reason '"no GNU tar here (macOS ships bsdtar'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_hooks.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Cited code moved since the evidence was written: tests/test_hooks.py:1246 (now line 1279)
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-85 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "no GNU tar here (macOS ships bsdtar, which has no --remove-files
- tests/test_hooks.py:1306 — skip marker with reason '"no GNU tar here (macOS ships bsdtar, which has no --remove-files'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_hooks.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Cited code moved since the evidence was written: tests/test_hooks.py:1306 (now line 1339)
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-86 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "needs a POSIX bash to measure against"
- tests/test_hooks_0903.py:1083 — skip marker with reason '"needs a POSIX bash to measure against"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_hooks_0903.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-87 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: f"no {tool} here"
- tests/test_hooks_0903.py:1086 — skip marker with reason 'f"no {tool} here"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_hooks_0903.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.

### VERDICT-F-88 — WITHDRAWN — Minor/P2 — BRITTLE_TEST — age 43d

A test is skipped with no expiry: "symlinks unavailable on this platform"
- tests/test_mcp_tools.py:324 — skip marker with reason '"symlinks unavailable on this platform"'; no date or expiry in the reason
- found by a regular expression over the test files, not by a model
- withdrawn by the skip scan 2026-11-27: it read tests/test_mcp_tools.py again and files nothing at the cited lines, which are as they were — the same text no longer reads as a skip with no expiry, so the rule that filed this was wrong
- Root cause: A skip with no expiry is a deleted test that nobody decided to delete: it never runs again and no one is told. → not investigated in local mode

The skip scan that filed this read the same lines again and no longer files them. The finding was a false positive of the rule as it then stood, and it stays on the record as one.


## Accepted risks (1)

_The maintainer's decision, recorded with `verdict-accept`, never the tester's: each is a real defect whose fix was declined, with the reason and where the decision is written down. Out of the open counts and the release blockers; not out of sight._

- **VERDICT-F-21** (Major/P2, age 4d) — accepted 2026-09-05 by ArtJack, citing DECISIONS.md 2026-09-02 — Verdict: the chain ratchet moves to the outcome ledger (v0.66.0): Deleting outcomes.json as well as runs.jsonl still sheds the chain signal. Accepted rather than solved: the cost is the project's entire permanent track record, and the next report states how many findings it is tracking, so the loss is visible. Fabrication is made expensive and loud, not impossible — the same standard the chain was built to.


## Track record

87 findings tracked across this project's history · 69 settled, 18 still undecided.

| Confidence claimed | Held up | of those, measured | Withdrawn | Rate |
|---|---|---|---|---|
| proven | 54 | 0 | 9 | 86% |
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

## Reading map (140 production modules, 86% covered overall)

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

- no agent ran: 33 bounded question(s) went to chat-120b — no exploratory charter, no archaeology, no adversarial reading of the suite
- the commit history: no origin was traced, and no `git log -S` was run
- 1 of 10 prior open finding(s) were carried unread, and 0 re-filed because the code they cite changed and no model looked at the change
- 6 file(s) and 24 function(s) were read; nothing else in the repository was
- claims the counterfactual could not reach — a probe that would not run leaves its finding a hypothesis, and an unproven severity is held at Minor for a reading and at Major for a failing test the model classified
- nothing outside the checkout was read — no database, no MCP tools, no production numbers — so a standing blocker that quotes one was NOT re-read
- 5 question(s) the model did not answer
- 141 candidate function(s) were never asked about: the cap of 24 function(s) was reached
- changed in the range and read by no question here, because none of it is program source: 9 configuration or data file(s), 10 document(s), 2 other file(s)
- 4 reading(s) this engine could not prove were listed as leads in the report, not filed — a lead is a question for a run that can judge it, not a finding

## Next run focus

- needs a model run — diff_over_limit: the range is larger than the caps this engine runs under; part of it was never read
- needs a model run — unexercised_changed_lines: 185
- lead, unproven: src/verdict_mcp/census_aliases.py:90 `_inside` — _inside treats repository root as inside, violating strict containment
- lead, unproven: src/verdict_mcp/census_aliases.py:127 `_under` — _under incorrectly treats the repository root as a valid subpath
- lead, unproven: src/verdict_mcp/census_aliases.py:172 `_options` — `paths` option incorrectly converted to list of keys, dropping pattern mappings
- lead, unproven: src/verdict_mcp/local_skip_close.py:195 `close_by_scan` — eligible set mixes int and string IDs causing missed closures
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

## Notes

No Claude tokens were spent on this run. The verdict cannot improve on its own: a previous `fail` stays `fail`, and a previous `blocked` stays `blocked`, until something with judgment looks at it. The skip scan read again what it had filed, and settled what it measured: withdrawn VERDICT-F-80, VERDICT-F-81, VERDICT-F-82, VERDICT-F-83, VERDICT-F-84, VERDICT-F-85, VERDICT-F-86, VERDICT-F-87, VERDICT-F-88.

**Leads — read by a small model, not proven, not filed (4).** Each is a question for a run that can judge it; none is on the record.
- `src/verdict_mcp/census_aliases.py:90` `_inside` — _inside treats repository root as inside, violating strict containment (read as Minor; probe_unsafe: argument 1 is not a literal (m.Path('.')))
- `src/verdict_mcp/census_aliases.py:127` `_under` — _under incorrectly treats the repository root as a valid subpath (read as Major; the model did not answer with JSON)
- `src/verdict_mcp/census_aliases.py:172` `_options` — `paths` option incorrectly converted to list of keys, dropping pattern mappings (read as Major; the model did not answer with JSON)
- `src/verdict_mcp/local_skip_close.py:195` `close_by_scan` — eligible set mixes int and string IDs causing missed closures (read as Major; the model did not answer with JSON)

---

*Countable sections rendered from `state.json` by `verdict-finalize`; the prose is the agent's. They cannot disagree.*
