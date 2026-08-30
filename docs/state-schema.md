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
| `not_tested` | yes | What was consciously not covered — a silent skip is a reporting failure |
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
this file is the record. Readers skip a torn trailing line (a crash mid-append) and keep
the last line per run_number.

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
