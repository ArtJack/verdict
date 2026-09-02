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
| `findings[].outcome` | computed | `confirmed` · `refuted` · `unknown`, written by `verdict-finalize`, never by the agent. Confirmed = regressed, or resolved-and-fix-verified. Refuted = withdrawn. Everything else is unknown, and stays out of every rate. Once decided it sticks, so a track record cannot erode as findings change state; only a withdrawal overrides an earlier decision |
| `findings[].outcome_reason` | computed | The sentence explaining the outcome, so a reader can audit the tally without re-deriving it |
| `calibration` | computed | The track record block: `by_confidence` and `by_proof_method` counts over every finding the project ever filed, with `precision` present only once a bucket reaches `min_sample` (30) settled outcomes. Rendered into the report as **Track record** |
| `findings[].root_cause` | no | The §3.5 chain when one was established: `{mechanism, origin, class{pattern, sites[]}, trigger, latent_condition, fix_location, proof{method, evidence}, confidence}`. `proof.method` is `counterfactual` · `differential` · `archaeology` · `reading`; `fix_location` is `code` · `test` · `spec` · `environment` · `process`; `confidence` is `proven` · `hypothesis`. Carrying it forward means the next run inherits the diagnosis instead of re-deriving it |
| `verdict` | yes | `pass` · `pass with risks` · `blocked` · `fail` |
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
range. A changed file coverage never saw was imported by nothing the suite ran, and every
changed line in it counts as unexercised — the honest reading.

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
(`path/test_x.py::test_y[...]`) in its evidence. **A citation is checked against the
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

**What it needs.** The profile names how to run one test: `test_one_cmd`, with `{id}`
where the node id goes. Without it nothing runs and `verification_notes` says so. **The
cited test's file always comes from HEAD** — the counterfactual is the new test against
the old source — and is marked `test_copied_from_head` when the old commit's copy differed
or was absent. Copying only when the file was *absent* read presence of the file as
presence of the test, so the commonest real shape, a regression test appended to a test
file that already existed, could never verify (VERDICT-F-25). The previous commit missing from this clone (a squash-merged
branch head) leaves `at_previous: unavailable`; the HEAD half still runs, so a still-
failing test still refuses resolution. Bounded: at most 25 findings per run, 120 s per
test run, so verification cannot become the suite.

`findings[].verification` is written by `verdict-finalize` only. A judgment carrying it is
rejected — the field is a measurement, and measurements are not claimed. The report's
`Fix verification:` line counts the measurements themselves (`at_previous`/`at_head` plus
the computed `delta`), never `fix_verified` — that is the one judgment field in the block,
and counting it there published run 5's error/error record as "1 verified" (VERDICT-F-30).
A finding claiming `fix_verified` that its own measurement does not show is named on the
line below it.

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
is finalize's and it is chain-signed. `verdict-issues` is a dry run unless `--create`; what
would leave the machine is printed first, title by title, and creation goes through the
operator's own `gh` login. It does not close or comment on issues when findings resolve —
a closed issue is a human's claim, `fix_verified` is the harness's measurement, and the
tracker must not be able to overrule the ledger.

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
