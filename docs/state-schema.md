# Verdict state file — schema v1

Location: `<qa-root>/state.json`. The QA root is `<repo>/.qa/` (team mode) or
`$VERDICT_HOME/<project-key>/` (solo mode; `VERDICT_HOME` defaults to `~/.claude/verdict`,
and the key derivation is specified in [project-key.md](project-key.md)). Rules: **preserve
unknown keys on update**; bump `schema_version` only on structural change, and say so in
the report; every timestamp is measured with `date -u +%Y-%m-%dT%H:%M:%SZ` at write time,
never composed from memory.

Concurrency is last-writer-wins **with collision detection**: the agent re-reads
`state.json` immediately before its final write and aborts the write when `run_number`
moved, recording the collision in its report. Deliberately no lock file — nightly + manual
overlap is rare, and a stale lock would block every future run; detection beats prevention
here.

## Example

```json
{
  "project": "pricer",
  "schema_version": 1,
  "run_type": "delta",
  "run_number": 4,
  "last_run": {
    "timestamp_utc": "2026-08-24T17:30:00Z",
    "git_sha": "b4e2943",
    "sha_range": "2c67f47..b4e2943",
    "git_branch": "main",
    "diff_stat": "16 files changed, 661 insertions(+), 39 deletions(-)",
    "report": "reports/2026-08-24-payment-retry.md"
  },
  "isolation_check": {
    "result": "pass",
    "method": "ls .env -> not present; no live service probed"
  },
  "gates": {
    "pytest": {
      "result": "pass",
      "command": "python -m pytest",
      "summary": "212 passed, 1 skipped in 8.31s",
      "exit_code": 0,
      "duration_s": 8.31
    }
  },
  "tests": { "collected": 213, "passed": 212, "skipped": 1, "failed": 0, "duration_s": 8.31 },
  "coverage": { "line_pct": 71, "command": "make coverage" },
  "flaky_quarantine": [
    {
      "test_id": "test_pricer.py::test_bulk_discount_applies",
      "first_seen": "2026-08-20",
      "fail_count": 2,
      "run_count": 6,
      "quarantined_until": "2026-09-03"
    }
  ],
  "findings": [
    {
      "id": "PRICER-F-003",
      "hash": "7a3f1c02",
      "first_seen": "2026-08-22",
      "status": "open",
      "delta": "STILL_OPEN",
      "age_days": 2,
      "title": "is_listable rejects a price exactly at the floor",
      "severity": "Major",
      "priority": "P1",
      "failure_classification": "REAL_DEFECT",
      "confidence": "proven",
      "outcome": "unknown",
      "outcome_reason": "still open; nothing has settled it",
      "evidence": ["pricer.py:14 (price > floor)", "README.md rule 1 (at or above)"]
    }
  ],
  "verdict": "pass with risks",
  "release_blockers": [],
  "not_tested": ["concurrency under parallel checkout — no harness present"],
  "next_run_focus": ["re-evaluate quarantined flake on expiry 2026-09-03"]
}
```

## Field reference

| Field | Required | Meaning |
|---|---|---|
| `project` | yes | Project key: repo directory name, lowercase, exactly |
| `schema_version` | yes | Integer; this document describes v1 |
| `run_type` | yes | `baseline` · `delta` · `re-baseline` — a strict enum, because consumers switch on it |
| `run_label` | no | Free text describing *this* run when the type alone is too coarse ("merge gate re-gate", "claim verification"). Introduced when a production run smuggled the description into `run_type` and broke every consumer that read it |
| `run_number` | yes | Monotonic counter |
| `last_run` | yes | `timestamp_utc`, `git_sha`, `sha_range`, `report` at minimum. `model` appears when the launcher exported `VERDICT_MODEL` (verdict-run does): the model that signed the verdict, measured rather than remembered |
| `isolation_check` | yes | Result of the profile's isolation check (§0) |
| `gates` | yes | One entry per gate actually run: command, summary line, exit code, and `duration_s` (optional but required to make the week-over-week duration gate measurable) |
| `tests` | yes | Collected/passed/skipped/failed counts (plus optional `duration_s`) — a silent drop in `collected` is a finding |
| `flaky_quarantine[]` | yes | `{test_id, first_seen, fail_count, run_count, quarantined_until}` — expiry is mandatory |
| `findings[]` | yes | `{id, hash, first_seen, status, delta, age_days, title, severity, priority, failure_classification, confidence, evidence[]}` — `failure_classification` holds the §3 value for any finding about a failing/erroring/skipped/nondeterministic test, `null` for pure design findings; machine consumers (the eval scorer, the gate) read the field, not the prose |
| `findings[].confidence` | on `NEW` | The tester's claim about the finding when filed: `proven` (demonstrated it happen) · `probable` (traced, not executed) · `hypothesis` (suspected). Required on findings filed this run, and **frozen** afterwards — the harness restores the filed value if a later run tries to revise it, because a confidence edited after the outcome is known measures nothing |
| `findings[].fix_verified` | no | Boolean, meaningful on a `RESOLVED` finding: `true` only when the defect was re-injected in a scratch copy and a guard failed. It is what separates "fixed" from "absent", and it is the only judgment field that feeds the track record — so it requires cited evidence |
| `findings[].outcome` | computed | `confirmed` · `refuted` · `unknown`, written by `verdict-finalize`, never by the agent. Confirmed = regressed, resolved-and-fix-verified, or accepted by the maintainer (`outcome_basis: accepted`). Refuted = withdrawn. Everything else is unknown, and stays out of every rate. Once decided it sticks, so a track record cannot erode as findings change state; only a withdrawal overrides an earlier decision |
| `findings[].outcome_reason` | computed | The sentence explaining the outcome, so a reader can audit the tally without re-deriving it |
| `findings[].accepted` | on `accepted` | `{by, on, citation, reason}` — the maintainer's decision to accept the risk, copied from `accepted.json` by `verdict-finalize`. `status: accepted` (delta `ACCEPTED`) is the one status a judgment may not write: it closes the finding for the open counts and the release blockers, lists it under **Accepted risks** in the report, and settles it `confirmed` on the maintainer's word. A revoked acceptance reopens the finding at the next run with `accepted_revoked` on it |
| `calibration` | computed | The track record block: `by_confidence` and `by_proof_method` counts over every finding the project ever filed, with `precision` present only once a bucket reaches `min_sample` (30) settled outcomes. Rendered into the report as **Track record** |
| `findings[].root_cause` | no | The §3.5 chain when one was established: `{mechanism, origin, class{pattern, sites[]}, trigger, latent_condition, fix_location, proof{method, evidence}, confidence}`. `proof.method` is `counterfactual` · `differential` · `archaeology` · `reading`; `fix_location` is `code` · `test` · `spec` · `environment` · `process`; `confidence` is `proven` · `hypothesis`. Carrying it forward means the next run inherits the diagnosis instead of re-deriving it |
| `verdict` | yes | `pass` · `pass with risks` · `blocked` · `fail` |
| `run_type: sweep` | — | The model-free run (0.86.0): `verdict-run --skip-unless-drift` found HEAD moved by commits that touched nothing any finding cites, every gate green with parsed counts, the test-id set unchanged, no quarantine due, no cited line moved — and finalized a synthetic judgment that carries every open finding by id and the previous verdict, `last_run.model: none`. Run number advances; the history row is signed like any other |
| `findings[].exercised_by_tests` | computed | The collected tests whose coverage contexts executed the finding's cited lines and stayed green, ranked by how many of those lines each covers, top five. Not a guard and not a candidate for `verification_test`: a defect filed under a green suite is executed by tests that do not fail on it — these are the assertions to review, and where a regression test belongs. Absent when no test executed the lines |
| `reading_map` | measured | Copied from facts: every production module the coverage run saw, least covered first (`lowest`, ≤25, each with `percent`, `statements`, `missed`, the `open_findings` that cite it and `last_cited_run`), git-tracked modules the suite never imported (`never_imported: true`, 0%), `never_examined` (the least-covered modules no finding has ever cited), `findings_by_module`, `overall_percent`. Present when the profile names `coverage_suite_cmd` |
| `gates[].report` | measured | When the gate command carries `{report}`: the JUnit XML or CTRF JSON the gate wrote, read for `counts`, `duration_s`, `failures` (id, kind, message), `slowest` and the ids' shape; `status: missing` when the gate wrote nothing. Counts from a report set `counts_dialect: report/<format>` |
| `findings[].filed_at` | computed | The modification time of the finding's file, `<qa-root>/findings/<ID>.json` — the measured moment it was written, which is when it was proven. Absent on a finding the judgment carried inline or by id |
| `findings[].re_reported` | computed | `still_open` or `resolved`: the judgment carried this finding by id, and finalize copied it from the previous state — evidence as last filed. Set for one run only; a carried copy drops it |
| `questions` | computed | The questions the tester parked for a person, rendered from `questions.json` with the maintainer's `answers.json` folded in: `{parked: [{id, question, finding?, context?, asked_on, asked_at_run, age_days}], answered_since_last_run: [{id, question, status, answer|reason, by, on}]}`. Present only while something is parked or an answer is unread |
| `findings[].anchors` | computed | Every `path:line` the finding's evidence and `root_cause.class.sites` cite, hashed at finalize: `{ref, path, line, blob, line_sha}`, or `{ref, status: unresolvable, reason}` when the reference names no file this repository has. Carried while the evidence text is unchanged (`anchored_at_run` says which run took them), so drift is measured from when the evidence was written. See [Anchors and drift](#anchors-and-drift--where-the-cited-code-went) |
| `findings[].last_verified_at` | computed | The timestamp of the harness's own last re-run of the finding's test (`at_head` pass or fail); an `error` or `unavailable` ran nothing and dates nothing. Carried forward; absent when never measured — and then the report says "no `verification_test` declared" |
| `findings[].introduced_at` · `introduced_sha` | computed | The date (and full sha) of the commit `root_cause.origin` names, resolved by git — dwell time is `first_seen` minus this. Absent when the origin names no commit this repository has; never derived from `first_seen` |
| `findings[].fixed_at` | computed | The date the harness measured fail→pass on a chosen test — the verified-fix date, not the fix commit's own; only on a `measured` resolution, never on a claim. Fix latency is this minus `first_seen` |
| `verified_intact_anchors` | computed | One anchor list per `verified_intact` item, aligned by index — the strings stay strings |
| `evidence_anchors` | computed | `{status: measured, refs, unresolvable}`, or `{status: unavailable, reason}` when facts.json named no `repo` and nothing could be anchored |
| `evidence_drift` | measured | Copied from facts: where the previous state's anchors are now — per open finding, per accepted finding, per verified-intact item — `unchanged` · `moved` (with `now_line`) · `changed` · `missing` · `unresolvable`, with `summary.drifted_findings` / `drifted_accepted` / `drifted_intact`. `status: unavailable` when the previous state carried no anchors |
| `release_blockers` | yes | Concrete blockers, or empty |
| `not_tested` | yes | What was consciously not covered — a silent skip is a reporting failure. Must be **non-empty on `pass` and `pass with risks`**: an empty list claims total coverage, which almost no run can say honestly |
| `next_run_focus` | no | Carries intent to the next run |
| `coverage` | no | Direction matters, not the absolute number |

## The profile's front matter — `<qa-root>/profile.md`

The profile has always recorded a project's real commands in prose; the front-matter block
makes them machine-readable, so `verdict-facts` runs the gates itself instead of the agent
retyping them into flags each run. That retyping was the last transcription step in the
pipeline, and transcription is where this architecture assumes error.

```
---
gates:
  suite: .venv/bin/python -m pytest -q
  lint: ruff check .
test_ids_cmd: .venv/bin/python -m pytest --collect-only -q
test_one_cmd: .venv/bin/python -m pytest {id} -q
coverage_suite_cmd: .venv/bin/python -m coverage run -m pytest -q
coverage_cmd: diff-cover coverage.xml
---

# QA Profile — myproject
...prose, unchanged...
```

A deliberately small subset of YAML rather than YAML: `key: value` at the left margin, and
one level of two-space-indented `name: value` under a bare `key:`. Values run to end of
line and are taken literally, because commands are full of colons, quotes and pipes. A
line the parser cannot read is an **error naming that line**, never a skip — silently
dropping a gate would reintroduce exactly the failure the block removes. Keys beyond
`gates`, `test_ids_cmd` and `coverage_cmd` are kept and reported as unread rather than
discarded.

Explicit `--gate` still wins, and the override is recorded in the facts; a run that ends up
with no gates at all records `no_gates` and says every count and duration gate is
unmeasurable, because "nothing to measure" and "nobody said what to measure" are different
states of the world.

## Run history — `<qa-root>/runs.jsonl`

One machine-native JSON line per finalized run: run number and type, verdict, timestamp,
SHAs, test counts, open findings by severity, delta counts, quarantine size, report path,
and the signing `model` when it was measured. Appended by `verdict-finalize`; consumed by
`get_history`/`get_trends`, which fall back to parsing INDEX.md only for history that
predates the file. The INDEX stays — for humans and git diffs — but it is a render;
this file is the record. Readers skip a torn trailing line (a crash mid-append).

Duplicate run numbers resolve by `revision`, not by file order. They are rarer than they
look — `validate` refuses a second finalize at a run number that did not advance, so a
retry means restoring `state.json` from `state.json.prev` and re-running. That rolls back
every file except this one, because append-only is the point: the superseded row stays on
disk forever. `revision` is the correction generation, absent on generation zero and one
higher on each correction; the highest generation for a run number wins, and equal
generations fall back to the last write, which is what every row written before the field
existed relies on. Nothing is ever rewritten to mark it stale — the correction is appended,
and it is the correction that carries the marker.

## A clean `pass` needs a suite somebody could read

`executed_nothing` is the defence against a suite that collects tests and runs none of
them, and it is arithmetic over parsed counts — so it only fires when the runner's summary
was legible. A project whose test entrypoint hides that summary
(`pytest -q >/dev/null; echo ALL TESTS PASSED; exit 0`) yields `counts_unparsed`, the
defence never computes, and the check ends up disabled by exactly the thing it guards
against. Measured on the liar fixture: through its own entrypoint a `pass` state gated to
exit 0 over a suite in which all three tests were skipped; behind a legible pytest gate
the same code reported `executed_nothing: all 3 collected tests were skipped`.

So `validate` refuses the unqualified `pass` when **no gate in the run produced test
counts**. The rule is run-level rather than per-gate, and that is what keeps it quiet: a
lint or freshness gate legitimately parses to no counts, and naming the test gate would
need semantics the harness does not have. One readable gate anywhere in the run satisfies
it. A run that ran **no gates at all** is refused the same way: `verdict-facts` records
`no_gates` when neither `--gate` nor a profile front-matter block supplied one, the state
carries it, and an unqualified `pass` over zero measurement is exactly the weakest run
earning the strongest verdict (VERDICT-F-17 — the first version of this rule left it
alone). `pass with risks` stays available — the rule refuses the unqualified verdict, not
the run. A state with `gates: {}` and no `no_gates` predates the fact travelling and is
left alone.

## Diff coverage — which changed lines any test executed

"Coverage on changed files must not decrease" (§6) was a gate the agent could only declare
unmeasurable: the profile named a `coverage_cmd`, nothing ran it, and `coverage` in the
state was whatever the judgment wrote. Sales reported the gate unmeasurable four runs in a
row. It is measured now, and at a finer grain than a percentage.

**What it measures.** `verdict-facts` runs the suite once more under coverage.py with
dynamic contexts (`coverage_suite_cmd` in the profile — e.g. `.venv/bin/python -m
coverage run -m pytest`, or a pytest-cov form with `--cov-context=test`; the harness
supplies the rcfile through `COVERAGE_RCFILE`), renders the database with `coverage json
--show-contexts`, and intersects it with the added/modified `.py` lines in the run's commit
range. **The rc file, the coverage database and the rendered JSON are written to a
temporary directory and removed when the measurement ends.** They used to be written into
the QA root, which in team mode is the committed directory: run 5 of this repository left
a 94,987,311-byte `coverage.json` there, ignored by nothing, one `git add .qa` from a
permanent blob in the repository (VERDICT-F-29). A QA root that ran 0.53–0.57 may still
hold one; the names are listed in `.qa/.gitignore` so it cannot be committed. A changed file coverage never saw was imported by nothing the suite ran, and every
changed line in it counts as unexercised — the honest reading.

**Child processes are measured too.** Coverage traces the process it starts, so a suite
that drives its code through subprocesses measured none of it: run 5 of this repository
read 217 changed lines of `issues.py` as "0 executed, not imported by anything the suite
executed" while eight tests exercised every one of them through a CLI subprocess
(VERDICT-F-28) — a false claim, and one the zero-coverage rule can turn into a refused
pass. The harness points `COVERAGE_PROCESS_START` at a config of its own whose static
`context` is `verdict:subprocess`, and coverage's startup hook arms every Python child
from there. Nothing is injected into the environment — no `PYTHONPATH`, no
`sitecustomize` — and the parent's own data is unchanged: its import-time lines keep the
empty context that keeps them from counting. A line only a child reached is counted as
executed, reported per file as `executed_in_subprocess`, and attributed to no test,
because there is no test context to attribute it to. Where the installed coverage ships no
startup hook, children go unmeasured and `subprocess_coverage` reads `none recorded` —
a gap, stated, not a claim.

`coverage.by_kind` splits the changed lines into `production` and `tests`, **and production
is the number to read**. The executed-under-a-test-context rule is right for production code
and structurally wrong for test code: a fixture body and a `def test_*` line never carry a
context, so every test file pays a permanent unexercised tax. Blended, the percent then moves
with the test/production composition of the diff rather than with coverage — across two runs
of this repository it fell 91% → 78% while production coverage *rose* 97% → 100%
(VERDICT-F-44). The blended figure is still reported, because it is what the schema has
always carried; it is not the one a gate should read.

Measuring children means the children record whatever they run, including files a test
generated in a temp directory that is gone before anything renders. `coverage json` aborts
on the first source it cannot read, so one such file cost this repository its entire
measurement — 63% at run 5, `unavailable` at run 6 (VERDICT-F-31). The render sets
`ignore_errors`, which is proportion rather than indulgence: a file whose source cannot be
read is a file no line can be attributed to anyway, and a changed file missing from the
render still counts as wholly unexercised.

```json
"coverage": {
  "status": "measured", "sha_range": "a1b2c3..d4e5f6",
  "changed_files": 3, "changed_lines": 213, "changed_lines_executed": 130, "percent": 61,
  "per_file": {
    "src/pricer.py": {"changed": 40, "measured": 38, "executed": 12,
                      "unexercised_ranges": [[81, 99], [104, 110]],
                      "tests": ["tests/test_pricer.py::test_floor"],
                      "unexercised_functions": ["apply_bulk"]}
  },
  "tests_touching_diff": ["tests/test_pricer.py::test_floor", "…"],
  "unexercised_functions": ["src/pricer.py:apply_bulk"]
}
```

`status: unavailable` with a `reason` when there is no `coverage_suite_cmd`, no commit
range (a baseline), or the database could not be rendered — said, never estimated. Measured
coverage outranks a `coverage` block the judgment wrote; the written block survives only
when the harness had nothing to measure with.

**The one rule.** A clean `pass` over a change **no** test executed is refused by
`validate`, the same shape as a pass over an unreadable suite. It fires only on the
measured zero; a diff with some execution is the agent's §6 delta call. Per-test
attribution (`tests`) is a lower bound — a tracer may record a line under one context and
skip it under the next — while "executed by any test" is exact, and that is what the rule
is built on.

## Fix verification — measured, not claimed

`fix_verified` is the one judgment field that feeds the track record, and it was almost
never set: re-injecting a defect by hand is the step every run skipped, so resolutions
stayed `unknown` and the calibration ledger starved — 95 of 110 Sales findings undecided.
The harness verifies now, the same way the contract asks the tester to: by running the
test that demonstrates the defect against the code before the fix and the code after it.

**What it measures.** For every finding open in the previous state, `verdict-facts` looks
for a cited test — an explicit `verification_test` on the finding, or a pytest node id
(`path/test_x.py::test_y[...]`) in its evidence. **Order is the choice**: the explicit
citation leads, then any id the collector saw for the first time this run — what a fix's
own regression test looks like — and prose order last. The record says which, in
`selected_by` (`explicit`, `added_this_run`, `first_cited`, `unselectable`) and
`candidates`. Taking whichever match came first meant the harness ran a non-guarding test
for every finding it verified on run 7 (VERDICT-F-26), and a `first_cited` pick among
several may not refuse a resolution: the measurement is recorded with a `not_weighed` note
instead, because overruling the tester is the strongest thing a measurement does here and
it may only rest on a test somebody chose. Since v0.77.0 such a pick is not run at all —
run 12 verified F-26 itself against an id quoted inside another finding's evidence, the
fourth mis-selection in a row, and a pass/pass record about a test nobody chose reads as
a measurement. The record says `unselectable`, lists the `candidate_tests`, carries no
`test`, and `verification_notes` asks for a declared `verification_test`. **A confirmation
needs a chosen test** (v0.79.0): `fix_verified` and a `confirmed` / `measured` outcome follow a
fail→pass only when `selected_by` is `explicit` or `added_this_run`. A single `first_cited`
test may still refuse a resolution — the conservative direction, a finding held open costs a
re-read — but its fail→pass is recorded under `not_weighed` and settles nothing, because a
confirmed row is a permanent grade and run 12 showed a prose-quoted id can be another
finding's test entirely (VERDICT-F-72). **A citation is checked against the
collected test-id ledger before anything runs**: evidence is prose, and the node-id regex
matches one anywhere in it, including inside a quoted source snippet. Run 5 of this
repository ran `t.py::new`, a test that exists in no file here, and published the
resulting error as a verification (VERDICT-F-26). An id the collector never reported is
not run at all, and `verification_notes` names the finding and the id. Where no ledger
exists — `test_ids_cmd` unset, or collection failed — there is nothing to check against
and every citation is tried, as before. It runs that test at HEAD, and again in a
scratch worktree of the previous run's commit, with the previous commit's source on
`PYTHONPATH` ahead of any installed copy. The result is classified from the runner's
parsed summary, never from the exit code alone: a setup *error* at the old commit exits 1
just like a failure would, and reading it as "fail" would mint a false verification.

```json
"verification": {
  "VERDICT-F-20": {
    "test": "tests/test_harness.py::test_the_set_diff_count_is_not_capped_by_the_display_list",
    "previous_sha": "01d797cf…", "at_previous": "fail", "at_head": "pass",
    "test_copied_from_head": true, "summary": "1 failed in 0.4s → 1 passed in 0.3s"
  }
}
```

**What `merge` does with it.** Three outcomes, all mechanical:

- `at_previous: fail` and `at_head: pass` on a finding that resolves this run — explicitly
  or by silence — stamps `fix_verified: true`, appends the measurement to the finding's
  evidence, and the outcome is `confirmed`. That is the loop closing: a decided outcome
  the tester never had to assert.
- `at_head: fail` — the cited test **still fails** — refuses the resolution. The finding
  stays `open`, `STILL_OPEN`, with `resolution_refused` naming the test. Neither a claim
  nor silence can close a finding whose demonstrating test fails on the code being judged.
- Anything else (`error`, `unavailable`, pass/pass, no cited test, no `test_one_cmd`) is
  *not verifiable*, said so in the record, and changes nothing. A test that passes at both
  commits did not demonstrate the defect, or the old source was not what ran — the
  harness cannot tell which, and does not pretend to.

**Isolation is not optional, and it is the harness's job here.** `verification.pythonpath`
records the scratch source the re-run actually imported. A copied tree carries the project's
virtualenv, and an editable install's `.pth` names the *original* checkout absolutely, so a
counterfactual run without that isolation imports the unmodified source and every injection
reads as a no-op — measured at 0 of 4 defects caught without it, 4 of 4 with it
(VERDICT-F-43). The machine-side verifier has always set it; the agent-facing contract now
says so too, with the check to run before trusting a green counterfactual.

**What it needs.** The profile names how to run one test: `test_one_cmd`, with `{id}`
where the node id goes. Without it nothing runs and `verification_notes` says so. **The
cited test's file always comes from HEAD** — the counterfactual is the new test against
the old source — and is marked `test_copied_from_head` when the old commit's copy differed
or was absent. Copying only when the file was *absent* read presence of the file as
presence of the test, so the commonest real shape, a regression test appended to a test
file that already existed, could never verify (VERDICT-F-25). Every `conftest.py` from the
repository root down to the test's own directory travels with it too, listed in
`support_copied_from_head`: a test is not only its file, and a regression test that lands
with the fixture it needs met an old commit that had never seen that fixture and errored
there, which is not a measurement (VERDICT-F-33). The previous commit missing from this clone (a squash-merged
branch head) leaves `at_previous: unavailable`; the HEAD half still runs, so a still-
failing test still refuses resolution. Bounded: at most 25 findings per run, 120 s per
test run, so verification cannot become the suite.

A ledger row carries `verification` too — the test, both results and how it was chosen,
four fields and no more. A row outlives its finding, so without the measurement a
`confirmed` cannot be audited at all once `state.json` drops the finding: 19 of this
repository's 21 confirmed rows were unjoinable when run 8 tried (VERDICT-F-41).

`findings[].regressed_at_run` records the run on which a finding came back, and is carried
forward on every run after. `delta` describes only the transition one run computed, so a
regression was visible for exactly one run and anything that did not look on that run —
`verdict-issues` filing a recurrence, for one — could never learn it happened
(VERDICT-F-34).

`findings[].verification` is written by `verdict-finalize` only. A judgment carrying it is
rejected — the field is a measurement, and measurements are not claimed. The report's
`Fix verification:` line counts the measurements themselves (`at_previous`/`at_head` plus
the computed `delta`), never `fix_verified` — that is the one judgment field in the block,
and counting it there published run 5's error/error record as "1 verified" (VERDICT-F-30).
A finding claiming `fix_verified` that its own measurement does not show is named on the
line below it.

## One coverage run, three facts — the reading map and the tests that exercise a defect

The suite runs under coverage.py whenever the profile names `coverage_suite_cmd` — a
baseline and an empty-diff delta used to measure nothing, and those are exactly the runs
that need to know where the least-tested code is. From one run: the diff measurement above
(`coverage`, unchanged), **`reading_map`**, and **`exercised_by`**.

The reading map is every production module the tracer saw, least covered first, with the
open findings that cite it (from the anchors) and the last run that did; plus every
git-tracked `.py` file the suite never imported, at 0% and `never_imported: true` — a module
nothing imports is the least-tested code there is and invisible to a tracer; plus
`never_examined`, the least-covered modules no finding has ever cited. Boltons runs 2–4
produced 13 of the project's 15 highest-severity findings from its six lowest-coverage
modules, re-deriving this ranking from the coverage JSON by hand on every run. The report
renders it as **Reading map**. Test files are not modules to read and are left out; so are
git-tracked scripts outside the roots the suite imports from (`docs/conf.py`, a bench script
under `misc/`), listed apart as `outside_package`.

`exercised_by` comes from the coverage contexts: for every open finding with anchors, the
tests whose contexts executed its cited lines, ranked by how many of the lines each covers,
top five. finalize puts them on the finding as `exercised_by_tests`, and the report prints
"Exercised and green: …" under the finding. They are **not** candidates for
`verification_test`, and the first acceptance run said so: a defect filed under a green suite
is, by construction, executed by tests that do not fail on it — the two tests that pin
`rotate_file`'s off-by-one execute every line of the defect. What the list is: the assertions
to review (§3: green tests are under review too), and the place a regression test belongs. A
guard that fails on the defect is what `verification_test` names; the harness finds it on its
own once a fix lands with its test (`added_this_run`).

## Structured test results before dialects — `{report}`

`verdict-facts` reads a dozen runner dialects off the summary line, and a dialect is a
guess: vitest's and jest's counted the file line on a stranger's repository. A gate command
may carry `{report}`; the harness renders it to a scratch path before the gate runs
(`pytest -q --junitxml={report}`, `vitest --reporter=junit --outputFile={report}`,
`gotestsum --junitfile {report}`, or any CTRF reporter) and parses what the gate wrote:
JUnit XML or CTRF JSON. The gate result carries `report` — exact counts, `duration_s`, the
`failures` with their messages, the `slowest` tests — and its counts outrank the dialect
(`counts_dialect: report/junit`). When no `test_ids_cmd` is set, the id ledger comes from the
report, in the report's own shape (`classname::name` for JUnit, `filePath::name` for CTRF)
and `test_ids.ids_from` says so — a pytest node id needs `test_ids_cmd`, and so does fix
verification. A gate given a path that writes nothing reads `report.status: missing` and
falls back to the dialect. The scratch directory is removed when the measurement ends;
nothing is written into the checkout.

## The model-free night — `verdict-run --skip-unless-drift`

`--skip-unchanged` answered half of "I don't change code every day": HEAD equal to the last
run's sha re-gates the standing verdict. The other half is HEAD moved by a commit that
touched nothing any finding cites. The runner asks the harness: it runs `verdict-facts`
itself and sweeps only when **every** condition holds — `evidence_drift` measured and empty;
no changed file in the range is cited by an open or accepted finding or a verified-intact
anchor; every gate passed with parsed counts and nothing `executed_nothing`; the test-id set
measured and unchanged; no quarantine due; no incomplete previous run; no changed line that
zero tests executed. Then it finalizes a synthetic judgment — the previous verdict, blockers,
focus and quarantine, every open finding carried by `still_open`, an isolation check that
says no agent ran, a `not_tested` that says what a sweep does not do — with `--sweep`, which
sets `run_type: sweep` and `last_run.model: none`. The run number advances, the report and
the INDEX row are written, the history row is signed. Any condition failing prints why and
runs the model; the suite then runs once more inside the agent's own `verdict-facts`.

## Findings as files — `<qa-root>/findings/<ID>.json`

The judgment was one JSON written from memory at the end of the run: boltons paused
3:32 to write 39,500 characters, a third of them eight findings re-typed from the
previous state to say "still there"; ofetch 5:12. Since 0.84.0 a finding is a file,
`findings/<ID>.json`, the shape of one entry of `findings[]` (the package ships it as
`templates/finding.example.json`; `verdict-facts` names it as `finding_template` and the
directory as `findings_dir`), written the moment the finding is proven, while the evidence
is in front of its author. The PostToolUse validator checks it as it is written — the
same per-finding rules the judgment loop always applied, plus the filename must equal the
`id` — and a rejection costs one file. A finding file may carry `narrative`, the
per-finding prose the report renders under it (what `prose.findings[id]` used to be).

`verdict-finalize` assembles the files, oldest first, and stamps each finding's
`filed_at` from the file's modification time. `judgment.json` keeps the run-level fields
and may still carry `findings[]` inline — but files **and** inline findings in one run is
refused, never merged. `verdict-facts` moves the previous run's `findings/` to
`findings.prev/` before the run starts (`findings_archived` says so); a retry of the same
run — a marker at this commit, minutes old — keeps the files, because they are this
attempt's own. Nothing is deleted.

**The two cheap verbs.** `still_open: [ids]` — looked at, still there, nothing new to say:
finalize copies the finding from the previous state (title, severity, evidence, root
cause, declared test; never the computed fields, never a fix claim) and it reads
`STILL_OPEN` with `re_reported: still_open`; its anchors carry, because the evidence text
is unchanged. `resolved: [ids]` — looked at, gone, not fix-verified: an explicit
resolution, outside the silence guardrail, `outcome: unknown` unless the harness measured
the fix. Both take only ids that are open in the previous state; an accepted risk is the
maintainer's and is refused; an id in a list and in a file is refused. And the word
"still there" is not available where the harness knows better: a `still_open` id whose
cited code `changed` or went `missing` since the evidence was written (`evidence_drift`)
is refused — "write `findings/<ID>.json` with fresh evidence, or resolve it". `moved` is
allowed; the report says where the line went.

**One class, one finding.** Filing findings one at a time makes it easy to file an
instance of a class as a second finding — the thing §3.5's class link exists to prevent.
`validate_judgment` refuses a finding whose evidence cites a `path:line` that another
finding (filed this run, or carried by id) lists under `root_cause.class.sites`, and two
findings that list the same site; the message names both exits: fold it into the class,
or take the site out of the class it does not belong to. Exact, never heuristic.

**A declared test is a collected id.** A run wrote "none — no test in
tests/x.py::y covers this" into `verification_test` and the harness read it as a
citation it could not find. When `test-ids.txt` exists, a `verification_test` that is not
in it is refused: declare a collected id, or omit the field and say in evidence that no
test guards this — which is a finding about the suite.

## Questions with a second pen — `questions.json` and `answers.json`

A run ends with things only a person can decide, and they used to live in the closing
handoff and the prose, so the next run asked them again. Two files, one pen each.

`questions.json` is **finalize's**: every question a judgment asked
(`questions: [{question, context?, finding?, options?}]`), with an id minted once
(`<PROJECT>-Q-<n>`, the project's finding prefix), the run that asked it, its date, and
its status — `parked`, `answered`, `dismissed`. A question already on the ledger (same
text, case and whitespace aside) is not minted twice. `answers.json` is **the
maintainer's**, written by `verdict-answer <project> <Q-id> --answer "…"` or
`--dismiss --reason "…"`; the scope guards refuse it to the tester, as they refuse
`accepted.json`, and a judgment cannot write an answer. finalize folds each answer into
the question it answers and marks it `acknowledged_at_run` the first time a run reads it.

```json
{"schema_version": 1, "questions": {
  "PRICER-Q-1": {"question": "Is half-up the rounding rule for cents?", "finding": "PRICER-F-3",
                 "asked_on": "2026-09-07", "asked_at_run": 3, "status": "answered",
                 "answer": "Half-up; the README is right.", "by": "ArtJack", "on": "2026-09-08",
                 "acknowledged_at_run": 4}}}
```

`verdict-facts` writes `questions` — what is parked, with its age, and what was answered
since the last run — so a decision is read, never re-asked. The report renders **Needs
human decision** and **Answered since the last run**; the session-start banner says how
many are waiting and how to answer; `verdict-gate`'s text and PR-comment renderers list
them; the MCP server has `get_questions`. Nothing is sent: a question is not an issue,
and no message leaves the machine for one.

## Anchors and drift — where the cited code went

A finding cites `path:line`, and until 0.83.0 nothing read that citation again:
the next run re-read the code, or did not, and "the code under an accepted risk
changed" was a sentence the contract asked the agent to write from memory.
`verdict-finalize` now turns every such reference — in a finding's `evidence`
and `root_cause.class.sites`, and in each `verified_intact` item — into an
anchor: the file's git blob id (computed as git computes it, so an uncommitted
file anchors the same way) and a hash of that one line.

```json
"anchors": [
  {"ref": "src/pricer/money.py:14", "path": "src/pricer/money.py", "line": 14,
   "blob": "9e1c4f0a77b2", "line_sha": "3d2a5c9b1e0f4a67"},
  {"ref": "publish/index.ts:112", "status": "unresolvable",
   "reason": "no such file in the repository"}
]
```

The next `verdict-facts` re-measures every anchor the previous state carries and
writes `evidence_drift`: `unchanged` (same blob, or the same line at the same
place in a file that changed elsewhere), `moved` (the same line elsewhere —
`now_line` says where), `changed` (the line is gone), `missing` (the file is
gone), `unresolvable` (the reference never named a file). A finding's drift is
the worst of its resolvable references. Open findings, accepted findings and
verified-intact items are measured in three buckets, because they are three
different sentences: what to re-read, what a maintainer's decision was made
about, and what the tester stood on.

```json
"evidence_drift": {
  "status": "measured",
  "findings": {"PRICER-F-3": {"drift": "moved",
               "refs": [{"ref": "src/pricer/money.py:14", "status": "moved", "now_line": 19}]}},
  "accepted": {"PRICER-F-1": {"drift": "changed", "refs": [{"ref": "src/pricer/zones.py:22", "status": "changed"}]}},
  "verified_intact": [{"text": "Zone lookup is pure …", "drift": "unchanged", "refs": [{"ref": "src/pricer/zones.py:18", "status": "unchanged"}]}],
  "summary": {"drifted_findings": ["PRICER-F-3"], "drifted_accepted": ["PRICER-F-1"], "drifted_intact": []}
}
```

Anchors are **carried, not refreshed**, while a re-reported finding's evidence
text is the text they were taken from; new evidence re-anchors. So an anchor
dates from when the tester last wrote about that code, and "moved since" means
since it last looked — which is the question, rather than "since last night".
Nothing decides anything on an anchor by itself: `unresolvable` costs nothing,
and the rule that reads drift (0.84.0: a `still_open` id whose cited code
changed or vanished is refused, "the code you cite no longer says that") stays
quiet on it. A previous state written before anchors existed reads
`evidence_drift.status: unavailable`, never `unchanged`; a facts.json that
names no `repo` leaves `evidence_anchors.status: unavailable` in the state,
said, not silent.

`facts.json` gains two small things beside `evidence_drift`: `repo`, the path
finalize runs git in, and `next_finding_id` — one past the highest id ever
minted for the project, the outcome ledger included, so a finding resolved runs
ago cannot have its number reused and two findings can no longer share an id by
accident.

## Silence, resolution, and `full_sweep`

A finding the previous run had and this run does not mention is normally resolved: the
tester looked and it was gone, and that is how a backlog drains without ceremony. A
*scoped* run breaks that inference. A merge gate over three files, or a charter aimed at
one subsystem, says nothing about the rest of the backlog, and reading its silence as
"fixed" closes findings nobody looked at.

So silence resolves only at a scale a fix explains better than a narrow run does. When more
than half the incoming open backlog goes unmentioned (and at least five findings do — below
that, proportion is noise), those findings are held `STILL_OPEN` with the reason on each
`carried_forward`, rather than resolved. Holding open is the recoverable error: a stale open
finding costs a re-read, a wrongly-closed Critical costs the gate.

A run that really did sweep everything sets `"full_sweep": true` on the judgment and gets
silence-as-resolution back unconditionally. It must be a real boolean — a truthy string
would grant the licence by accident, so `validate_judgment` rejects one. Resolving a finding
explicitly, by re-reporting it with `status: "resolved"`, always works and is never subject
to the guardrail.

Each row also carries **`chain`** — `sha256(previous chain + this row, canonical JSON)` —
and `state.json` records the same value in `last_run.chain`. This is what makes
`--require-harness` resist imitation rather than only forgery. The two older durable
signals are a key holding a dict and a fixed footer string, both of which a model can
satisfy by copying what is already in the committed `.qa/` artifacts; a link cannot be
copied, because it is a function of the row beneath it. The row is derived from the
state, so re-deriving it also catches a `state.json` edited after signing — laundering a
verdict in place leaves the history intact but no longer reproduces the link.

Two deliberate limits. A history with no links at all reads as *unchained*, not broken,
so a project from before this existed keeps passing its own gate — the gate says so in
its output rather than staying quiet, and one `verdict-finalize` run signs the history
from then on. And once any row is signed, a later row that drops its link is a break,
not a downgrade: without that ratchet a fabricator would simply omit what it cannot
compute. None of this makes fabrication impossible — a model that reimplements the
chain correctly can still hand-write a state, at which point it has done most of the
work the harness would have done. What changes is that the cheap version fails loudly.

## The issue ledger — `<qa-root>/issues.json`

Written by `verdict-issues`, never by the agent or by `finalize`. One entry per finding
that has been filed as a GitHub issue — `{number, url, created_at, run_number, hash}` keyed
by finding id — so a re-run files nothing twice, and the state itself is never touched: it
is finalize's and it is chain-signed. **A finding that comes back is filed again.** The id
is minted once and never reused, so its presence in the ledger answers "has this finding
ever been filed" while a tracker needs "has this *occurrence* been filed": a REGRESSED
finding, the class the contract ranks first, was reported as already filed while its issue
sat closed (VERDICT-F-27). A recurrence is filed once per regression — the guard is the
run number, so running the tool twice over one state still files nothing twice — and the
new entry carries `previous`, the trail back to the issue it replaces. `verdict-issues` is a dry run unless `--create`; what
would leave the machine is printed first, title by title, and creation goes through the
operator's own `gh` login. It does not close or comment on issues when findings resolve —
a closed issue is a human's claim, `fix_verified` is the harness's measurement, and the
tracker must not be able to overrule the ledger.

## The chain's ratchet — `outcomes.json` → `chain`

The run-history chain proves a run was not composed by hand, and its ratchet lived entirely
inside the file it guards: once a row carried a link, a later row that dropped one was a
break. But a history with *no* links at all reads `unchained`, which is accepted — every
project is unsigned until its next harness run, and failing them all would be a migration
by ambush. So the whole signal came off with one `rm`: delete `runs.jsonl`, drop
`last_run.chain`, and the project is back to the state the chain was built to leave behind
(VERDICT-F-21).

The ledger carries the ratchet now, because it is a different file with a different job:

```json
"chain": { "since_run": 7, "last_link": "954f480f0303…" }
```

Written by `verdict-finalize` beside the outcomes it keeps. `verify_chain(rows, anchor)`
then reads three cases rather than two:

- no anchor, no links → `unchained`, accepted, said out loud. A project that genuinely
  predates the chain has no anchor, because nothing ever wrote one.
- an anchor, and a history with no links → `broken`. Something removed what the ledger
  records.
- an anchor whose `last_link` is absent from an otherwise valid history → `broken`. This is
  the forger's best move: not an unsigned history but a *correctly signed* one begun from a
  start of their own choosing, which verifies perfectly against itself. An internal ratchet
  cannot see it; a second file can.

This does not make fabrication impossible, and it is not meant to. Shedding the signal now
means destroying the permanent track record as well — every decided outcome this project
ever recorded — and the next report says how many findings it is tracking.

## The accepted-risk ledger — `<qa-root>/accepted.json`

The maintainer's, not the tester's. Written only by `verdict-accept`; the scope guards
refuse the file to the verdict agent even inside the QA root, and `validate_judgment`
refuses `status: accepted` in a judgment — a finding cannot accept its own risk.

```json
{
  "schema_version": 1,
  "accepted": {
    "VERDICT-F-21": {
      "hash": "…", "severity": "Major", "title": "…",
      "by": "ArtJack", "on": "2026-09-04",
      "citation": "DECISIONS.md 2026-09-02 — the chain ratchet moves to the outcome ledger",
      "reason": "deleting outcomes.json too defeats the anchor; the cost is the whole track record",
      "revoked": {"by": "…", "on": "…", "reason": "…"}
    }
  }
}
```

Keyed by finding id; `revoked` is present once an acceptance has been reversed, and the
entry stays so the record shows both decisions. Readers between runs (`verdict-gate`, the
session banner, the MCP server, `verdict-issues`) apply it to a *copy* of the findings —
the signed history row must still re-derive from `state.json` as written. `verdict-finalize`
applies it to the next state, where the finding reads `accepted` / `ACCEPTED` and the
acceptance is inside the signed row. A missing or corrupt ledger reads as empty: it can
reopen nothing the state does not already say is open.

## The outcome ledger — `<qa-root>/outcomes.json`

`state.json` holds open findings and the current run's resolutions; a finding resolved two
runs ago is no longer in it. That is deliberate — state stays small — but it means decided
outcomes would leave the sample as soon as they stopped being news, and no track record
could ever accumulate. `outcomes.json` is where they persist: one compact row per finding
ever filed, keyed by `hash`, upserted by `verdict-finalize` (so a re-run rewrites rows
instead of double-counting them).

```json
{
  "schema_version": 1,
  "project": "pricer",
  "findings": {
    "7a3f1c02": {
      "hash": "7a3f1c02", "id": "PRICER-F-003", "severity": "Major",
      "confidence": "probable", "proof_method": "differential",
      "outcome": "confirmed", "outcome_reason": "regressed: it was fixed and came back, so it was real",
      "first_seen": "2026-08-22", "decided_on": "2026-09-04"
    }
  }
}
```

**Measurement outranks the claim; silence does not.** `fix_verified` reaches a finding
from two places: the harness sets it when its own re-injection measured fail→pass, and a
judgment may claim it for a re-injection done by hand. The outcome rule could not tell
them apart, so the track record recorded `confirmed` over a measurement that never
happened — live in this repository's ledger for `VERDICT-F-20`, whose cited test exists in
no file and was measured error/error (VERDICT-F-32).

The first correction demoted a claim whenever a measurement had been *attempted*, and
which test gets attempted is a prose lottery: the same hand-verified claim landed
`confirmed` when the write-up quoted no node id and `unknown` when it did — four findings
verified identically, two outcomes, decided by prose (VERDICT-F-35). So an inconclusive
measurement (pass at both commits, an error, nothing runnable) is silence and changes
nothing. Only a measurement that *contradicts* the claim does.

`findings[].outcome_basis` records which of the two a `confirmed` rests on: `measured` is
the harness's own re-injection, `claimed` is the tester's, weighed only by the absence of
a contradiction. The calibration block counts them separately and its reading names the
split, because a rate built mostly on the tester's word read exactly like a measured one
(VERDICT-F-36). A row written before the field existed carries neither, and is left
uncounted in the split rather than relabelled. Rows already decided are untouched, because
a decided outcome sticks.

A decided outcome is never overwritten by a later `unknown` — losing sight of a finding is
not evidence that nothing was ever settled. Evidence, prose, and root-cause chains stay in
the reports; the ledger keeps only what a tally needs. A missing or corrupt ledger reads as
empty and never fails a run.

The finding `hash` is a short hash of `file path + rule + normalized message` (lowercase,
line numbers stripped) so identity stays stable across runs while line numbers move. The
human-facing `id` (`<PROJECT>-F-<n>`) is minted once, at first sight, and never renumbered
or reused — `hash` is how a finding is recognized; `id` is how humans talk about it.

**Matching is hash first, then id.** A hash is a fingerprint of the words, and it moves
whenever the tester rewords its own title or cites a different line; matched on hash alone,
a reworded re-report is filed as `NEW` *and* carried forward as resolved — two entries, one
id, and a state the validator refuses to write, so the run produces nothing. When the hash
misses, `verdict-finalize` falls back to the id and adopts the stored hash, because §6
mints ids once and forbids reuse: a re-reported id is a deliberate identity claim. This is
also what lets a project migrate onto the harness at all — every hash written before the
harness existed was authored by hand and matches nothing computable.
