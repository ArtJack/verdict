"""The quarantine, re-measured: quarantined tests rerun and released, flaky findings by
test, and failures already on record.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

try:
    from .harness import _run_test
    from .state import norm_status
    from .local_suite import QUARANTINE_DAYS
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from harness import _run_test
    from state import norm_status
    from local_suite import QUARANTINE_DAYS


# ── the quarantine, re-measured ───────────────────────────────────────────────


# Five identical runs is what releases a quarantine. Arithmetic, not judgment:
# the model is never asked whether a test has stopped being flaky.
REQUARANTINE_RUNS = 5


REQUARANTINE_TIMEOUT_S = 300


def requarantine(repo: Path, entries, test_one_cmd: str | None, today,
                 runs: int = REQUARANTINE_RUNS) -> tuple:
    """Re-run every DUE quarantine entry `runs` times → (kept, released, notes).

    An expiry is a date somebody wrote down, not a measurement, and releasing a
    test because the date passed is how a flaky test walks back into the set that
    blocks releases. Five identical runs answer the question exactly, and the
    model is never asked: repetition is arithmetic. An entry with no expiry due
    is carried verbatim, and a project with no `test_one_cmd` gets its entries
    kept, a parked question, and a line in `not_tested` — never a release.
    """
    kept, released, notes = [], [], []
    for entry in entries or []:
        if not isinstance(entry, dict) or not entry.get("test_id"):
            continue
        until = str(entry.get("quarantined_until") or "")
        if until and until > today.isoformat():
            kept.append(entry)
            continue
        if not test_one_cmd:
            kept.append(entry)
            notes.append(f"{entry['test_id']} is due for release from quarantine and was NOT "
                         "re-measured: the profile declares no `test_one_cmd`, so nothing here "
                         "can run one test. The quarantine is kept rather than expired")
            continue
        outcomes = [_run_test(test_one_cmd, str(entry["test_id"]), repo, repo,
                              REQUARANTINE_TIMEOUT_S)["result"] for _ in range(runs)]
        passed = sum(1 for r in outcomes if r == "pass")
        if passed == runs:
            released.append({**entry, "runs_measured": runs})
            notes.append(f"{entry['test_id']} passed {runs} of {runs} identical runs — released "
                         "from quarantine by measurement; it blocks releases again")
        else:
            kept.append({**entry,
                         "first_seen": entry.get("first_seen") or today.isoformat(),
                         "fail_count": runs - passed, "run_count": runs,
                         "quarantined_until": (today + timedelta(days=QUARANTINE_DAYS)).isoformat(),
                         "reason": f"re-measured {today.isoformat()}: {passed} of {runs} identical "
                                   "runs passed — still not deterministic, so the expiry moves"})
            notes.append(f"{entry['test_id']} passed only {passed} of {runs} identical runs — "
                         "quarantine extended by measurement")
    return kept, released, notes


def flaky_findings_by_test(previous: dict | None, test_ids) -> dict:
    """`{test id: finding id}` for the open FLAKY findings a previous run left.

    Matched on the test id appearing in the finding's own words, which is how
    this engine and the agent both write them. There is no structured link
    between a quarantine entry and its finding, and inventing one now would not
    read the findings people already have.
    """
    wanted = {str(t) for t in test_ids if t}
    out: dict = {}
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or norm_status(f.get("status")) != "open":
            continue
        if f.get("failure_classification") != "FLAKY":
            continue
        blob = " ".join([str(f.get("title") or "")] + [str(e) for e in (f.get("evidence") or [])])
        for test_id in wanted:
            if test_id in blob:
                out.setdefault(test_id, str(f.get("id")))
    return out


def failure_on_record(previous: dict | None, test_id: str) -> dict | None:
    """The open or accepted finding this engine filed for this failing test, or None.

    Matched on the exact sentence `failure_finding` writes — `<id> fails at HEAD` — and
    nothing looser: a finding that merely mentions a test may be about something else in
    it, and treating it as this failure would hide a new one. A resolved finding is not
    matched here; a failure that returns goes through the identity rule like any other."""
    sentence = f"{test_id} fails at HEAD"
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if norm_status(f.get("status")) not in ("open", "accepted"):
            continue
        if any(str(e).startswith(sentence) for e in f.get("evidence") or []):
            return f
    return None


def released_ids(previous: dict | None, released: list) -> list:
    """The FLAKY findings whose quarantine this run released — they are re-filed
    with the measurement, not left standing on a claim that is no longer true."""
    tests = [r.get("test_id") for r in released if isinstance(r, dict)]
    return sorted(set(flaky_findings_by_test(previous, tests).values()))


def merge_quarantine(carried: list, fresh: list) -> list:
    """The carried entries plus this run's, one per test id.

    A test already under an expiry that goes unstable again would otherwise be in
    the list twice — once with last run's counts and once with this run's — and a
    reader would have no way to tell which expiry governs. This run's measurement
    wins, because it is the newer one.
    """
    by_test = {}
    for entry in list(carried) + list(fresh):
        if isinstance(entry, dict) and entry.get("test_id"):
            by_test[str(entry["test_id"])] = entry
    return [by_test[k] for k in sorted(by_test)]
