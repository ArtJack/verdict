# Verdict state file — schema v1

Location: `<qa-root>/state.json`. The QA root is `<repo>/.qa/` (team mode) or
`$VERDICT_HOME/<project-key>/` (solo mode; `VERDICT_HOME` defaults to `~/.claude/verdict`,
and the key derivation is specified in [project-key.md](project-key.md)). Rules: **preserve
unknown keys on update**; bump `schema_version` only on structural change, and say so in
the report; every timestamp is measured with `date -u +%Y-%m-%dT%H:%M:%SZ` at write time,
never composed from memory.

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
    "git_sha_previous": "2c67f47",
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
      "blocking": true,
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
| `run_type` | yes | `baseline` · `delta` · `re-baseline` |
| `run_number` | yes | Monotonic counter |
| `last_run` | yes | `timestamp_utc`, `git_sha`, `sha_range`, `report` at minimum |
| `isolation_check` | yes | Result of the profile's isolation check (§0) |
| `gates` | yes | One entry per gate actually run: command, summary line, exit code, and `duration_s` (optional but required to make the week-over-week duration gate measurable) |
| `tests` | yes | Collected/passed/skipped/failed counts (plus optional `duration_s`) — a silent drop in `collected` is a finding |
| `flaky_quarantine[]` | yes | `{test_id, first_seen, fail_count, run_count, quarantined_until}` — expiry is mandatory |
| `findings[]` | yes | `{id, hash, first_seen, status, delta, age_days, title, severity, priority, failure_classification, evidence[]}` — `failure_classification` holds the §3 value for any finding about a failing/erroring/skipped/nondeterministic test, `null` for pure design findings; machine consumers (the eval scorer, the gate) read the field, not the prose |
| `verdict` | yes | `pass` · `pass with risks` · `blocked` · `fail` |
| `release_blockers` | yes | Concrete blockers, or empty |
| `not_tested` | yes | What was consciously not covered — a silent skip is a reporting failure |
| `next_run_focus` | no | Carries intent to the next run |
| `coverage` | no | Direction matters, not the absolute number |

The finding `hash` is a short hash of `file path + rule + normalized message` (lowercase,
line numbers stripped) so identity stays stable across runs while line numbers move. The
human-facing `id` (`<PROJECT>-F-<n>`) is minted once, at first sight, and never renumbered
or reused — `hash` is how a finding is recognized; `id` is how humans talk about it.
