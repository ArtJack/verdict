#!/usr/bin/env python3
"""verdict-validate — the state contract, enforced at the write boundary.

Stdlib only, no model, no network: runnable as a bare script from a checkout.

Every rule below exists because a real run broke it. A prompt rule reduces how
often a model invents a value; it cannot stop a model from inventing a value it
is capable of inventing. Two of four production timestamps landed on exactly
:00 seconds months after `date -u` became a written rule. So the contract stops
being prose the agent is asked to honour and becomes a gate the state must pass:

  - the report field must name a file that exists (a run once wrote
    "inline to caller (no report file written per caller instruction)" there,
    three times, and every downstream consumer believed it);
  - run_number must advance (a crashed headless session left yesterday's state
    in place and the next reader could not tell);
  - timestamps must be ISO-8601 Z and close to now (fabricated ones corrupt
    every age, expiry, and re-baseline decision built on them);
  - a `pass` verdict cannot stand over an open Critical or Blocker;
  - findings need stable identity, valid enums, and cited evidence.

Exit codes: 0 valid · 1 violations found · 2 usage/unreadable.

As a PostToolUse hook it is called with the hook JSON on stdin and reports
violations on stderr with exit 2, which shows the agent what it must fix while
it can still fix it — in-session, rather than a lost run later.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERDICTS = {"pass", "pass with risks", "blocked", "fail"}
RUN_TYPES = {"baseline", "delta", "re-baseline"}
# WITHDRAWN is the tester's own false-positive record: a finding that was
# reported and turned out not to be real. It exists because a production run
# needed the concept and invented the word — and a tester that quietly deletes
# its wrong findings is hiding its own error rate.
DELTAS = {"NEW", "STILL_OPEN", "RESOLVED", "REGRESSED", "WITHDRAWN"}
SEVERITIES = {"Blocker", "Critical", "Major", "Minor", "Trivial"}
PRIORITIES = {"P0", "P1", "P2", "P3"}
CLASSIFICATIONS = {"REAL_DEFECT", "STALE_EXPECTATION", "BRITTLE_TEST", "ENVIRONMENT", "FLAKY"}
# Optional, because five archived corpus runs predate them and must keep
# scoring: a contract that retroactively invalidates its own history is not a
# contract, it is a rewrite.
CONFIDENCES = {"proven", "probable", "hypothesis"}
OUTCOMES = {"confirmed", "refuted", "unknown"}
STATUSES = {"open", "resolved", "withdrawn"}
REQUIRED_TOP = ("project", "schema_version", "run_type", "run_number", "last_run",
                "isolation_check", "verdict", "release_blockers", "not_tested")
_ISO_Z = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
# A run that finished more than a day ago, or in the future, did not just write
# this file. Generous either way: clock skew is real, a two-day-old "now" is not.
FUTURE_TOLERANCE = timedelta(minutes=10)
PAST_TOLERANCE = timedelta(days=1)


def _status(finding) -> str:
    """Status, case-normalized. Mirrors state.norm_status, duplicated because
    this module is the PostToolUse hook and must import nothing."""
    return str(finding.get("status") or "").strip().lower()


def _parse_z(value: str):
    if not isinstance(value, str) or not _ISO_Z.match(value):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def validate(state, root: Path, previous=None, now=None):
    """Return a list of violation strings. Empty means the state is admissible.

    `root` is the QA root the state lives in — the report path is resolved
    against it. `previous` is the prior state when one is available, which is
    what makes the run_number rule checkable.
    """
    now = now or datetime.now(timezone.utc)
    bad = []

    if not isinstance(state, dict):
        return ["state.json is not a JSON object"]

    for field in REQUIRED_TOP:
        if field not in state:
            bad.append(f"missing required field: {field}")

    if state.get("verdict") not in VERDICTS:
        bad.append(f"verdict {state.get('verdict')!r} is not one of {sorted(VERDICTS)}")
    if state.get("run_type") not in RUN_TYPES:
        bad.append(
            f"run_type {state.get('run_type')!r} is not one of {sorted(RUN_TYPES)} — "
            "machine consumers switch on this field; put the descriptive detail "
            "('merge gate re-gate', 'claim verification') in run_label")
    if "run_label" in state and not isinstance(state["run_label"], str):
        bad.append("run_label must be a string when present")

    run_number = state.get("run_number")
    if not isinstance(run_number, int) or run_number < 1:
        bad.append(f"run_number must be a positive integer, got {run_number!r}")
    elif previous is not None:
        prev_run = previous.get("run_number")
        if isinstance(prev_run, int) and run_number <= prev_run:
            bad.append(
                f"run_number did not advance: {run_number} after {prev_run} — a run that "
                "wrote no state must not leave the previous verdict standing as if fresh")

    last = state.get("last_run")
    if not isinstance(last, dict):
        bad.append("last_run must be an object")
    else:
        ts = last.get("timestamp_utc")
        parsed = _parse_z(str(ts))
        if parsed is None:
            bad.append(f"last_run.timestamp_utc {ts!r} is not ISO-8601 UTC (YYYY-MM-DDThh:mm:ssZ)")
        elif parsed - now > FUTURE_TOLERANCE:
            bad.append(f"last_run.timestamp_utc {ts} is in the future — measure it with `date -u`")
        elif now - parsed > PAST_TOLERANCE:
            bad.append(
                f"last_run.timestamp_utc {ts} is over a day old — this run did not happen "
                "then; measure the time with `date -u` rather than recalling it")

        report = last.get("report")
        if not isinstance(report, str) or not report.strip():
            bad.append("last_run.report must name the report file this run wrote")
        else:
            candidate = Path(report)
            resolved = candidate if candidate.is_absolute() else root / candidate
            if candidate.suffix != ".md":
                bad.append(
                    f"last_run.report {report!r} is not a path to a .md file — the report "
                    "artifact is part of the contract and no caller may waive it")
            elif not resolved.is_file():
                bad.append(f"last_run.report points at a file that does not exist: {resolved}")

    findings = state.get("findings")
    if findings is None:
        bad.append("missing required field: findings")
    elif not isinstance(findings, list):
        bad.append("findings must be a list")
    else:
        seen_ids = set()
        seen_hashes = {}
        for i, f in enumerate(findings):
            where = f"findings[{i}]"
            if not isinstance(f, dict):
                bad.append(f"{where} is not an object")
                continue
            fid = f.get("id")
            if not fid:
                bad.append(f"{where} has no id")
            elif fid in seen_ids:
                bad.append(f"{where} repeats id {fid!r} — ids are minted once and never reused")
            else:
                seen_ids.add(fid)
            h = f.get("hash")
            if not h:
                bad.append(f"{where} ({fid}) has no hash — findings are aged by hash, not by id")
            elif h in seen_hashes:
                # Found live: two ids in one state shared a hash, the second
                # filed as "F-003 confirmed in production". By the identity rule
                # they are one finding, so ageing, deltas and the outcome ledger
                # all collapse them — silently, and onto whichever came last.
                bad.append(
                    f"{where} ({fid}) shares hash {h} with {seen_hashes[h]} — by the identity "
                    "rule those are the same finding, and every run-over-run comparison will "
                    "treat them as one. Merge them, or cite the distinct evidence that makes "
                    "them different findings")
            else:
                seen_hashes[h] = fid
            if f.get("severity") not in SEVERITIES:
                bad.append(f"{where} ({fid}) severity {f.get('severity')!r} not in {sorted(SEVERITIES)}")
            if f.get("priority") not in PRIORITIES:
                bad.append(f"{where} ({fid}) priority {f.get('priority')!r} not in {sorted(PRIORITIES)}")
            if f.get("delta") is not None and f.get("delta") not in DELTAS:
                bad.append(f"{where} ({fid}) delta {f.get('delta')!r} not in {sorted(DELTAS)}")
            conf = f.get("confidence")
            if conf is not None and conf not in CONFIDENCES:
                bad.append(f"{where} ({fid}) confidence {conf!r} not in {sorted(CONFIDENCES)}")
            elif conf is None and f.get("delta") == "NEW":
                # Required only where it can still be honestly given: a finding
                # filed this run. Confidence is a *prediction*, and a prediction
                # supplied after the outcome is known is worth nothing — so it
                # is demanded at filing or not at all. Findings inherited from
                # runs that predate this rule stay legal and score as `unstated`.
                bad.append(
                    f"{where} ({fid}) is NEW without `confidence` — state the claim as you "
                    f"file it: {sorted(CONFIDENCES)}. It is scored against what the finding "
                    "actually does, so it cannot be added later")
            oc = f.get("outcome")
            if oc is not None and oc not in OUTCOMES:
                bad.append(f"{where} ({fid}) outcome {oc!r} not in {sorted(OUTCOMES)}")
            if f.get("delta") == "WITHDRAWN" and _status(f) == "open":
                bad.append(f"{where} ({fid}) is WITHDRAWN but still open — a finding "
                           "retracted as never real cannot also count as a live defect")
            fv = f.get("fix_verified")
            if fv is not None and not isinstance(fv, bool):
                bad.append(f"{where} ({fid}) fix_verified must be true or false, not {fv!r}")
            elif fv is True and not (f.get("evidence") or []):
                # `fix_verified` upgrades a resolution into evidence that the
                # finding was real, so it has to cost something: name the guard
                # that failed on re-injection, or do not make the claim.
                bad.append(f"{where} ({fid}) claims fix_verified with no evidence — cite the "
                           "test that failed when the defect was re-injected")
            fc = f.get("failure_classification")
            if fc is not None and fc not in CLASSIFICATIONS:
                bad.append(f"{where} ({fid}) failure_classification {fc!r} not in {sorted(CLASSIFICATIONS)}")
            if _status(f) == "open" and not (f.get("evidence") or []):
                bad.append(
                    f"{where} ({fid}) is open with no evidence — an uncited finding is a "
                    "HYPOTHESIS, not a finding")

        if state.get("verdict") == "pass":
            blocking = [f.get("id") for f in findings
                        if isinstance(f, dict) and _status(f) == "open"
                        and f.get("severity") in {"Critical", "Blocker"}]
            if blocking:
                bad.append(
                    "verdict is `pass` with open Critical/Blocker findings: "
                    + ", ".join(str(b) for b in blocking))

    if not isinstance(state.get("not_tested"), list):
        bad.append("not_tested must be a list — a `pass` without a stated not-tested list "
                   "is incomplete, and an empty list is a claim of total coverage")

    quarantine = state.get("flaky_quarantine")
    if quarantine is not None and not isinstance(quarantine, list):
        bad.append("flaky_quarantine must be a list")
    elif isinstance(quarantine, list):
        for i, q in enumerate(quarantine):
            if isinstance(q, dict) and not q.get("quarantined_until"):
                bad.append(f"flaky_quarantine[{i}] ({q.get('test_id')}) has no expiry — "
                           "quarantine without an expiry is a graveyard")
    return bad


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, f"no such file: {path}"
    except (OSError, json.JSONDecodeError) as exc:
        return None, f"unreadable: {exc}"


def _hook_mode() -> int:
    """PostToolUse: validate a state.json the agent just wrote."""
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # fail open: a broken hook must never brick a session
    target = ((data.get("tool_input") or {}).get("file_path") or "")
    if os.path.basename(target) != "state.json":
        return 0
    path = Path(target)
    state, err = _load(path)
    if err:
        sys.stderr.write(f"verdict-validate: {path} {err}\n")
        return 2
    prev_path = path.with_suffix(".json.prev")
    previous, _ = _load(prev_path) if prev_path.is_file() else (None, None)
    bad = validate(state, path.parent, previous)
    if not bad:
        return 0
    sys.stderr.write(
        "verdict-validate: the state you just wrote violates the contract "
        f"({len(bad)} problem(s)) — fix it now, in this run:\n  " + "\n  ".join(bad) + "\n")
    return 2


def main(argv=None) -> int:
    if not sys.stdin.isatty() and not argv and len(sys.argv) == 1:
        return _hook_mode()
    ap = argparse.ArgumentParser(
        prog="verdict-validate",
        description="Validate a Verdict state.json against the state contract.")
    ap.add_argument("state", type=Path, help="path to state.json")
    ap.add_argument("--previous", type=Path, default=None,
                    help="prior state.json, enabling the run_number-advanced check")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    state, err = _load(args.state)
    if err:
        print(f"verdict-validate: {args.state} {err}", file=sys.stderr)
        return 2
    previous = None
    if args.previous:
        previous, perr = _load(args.previous)
        if perr:
            print(f"verdict-validate: --previous {args.previous} {perr}", file=sys.stderr)
            return 2
    bad = validate(state, args.state.parent, previous)
    if bad:
        print(f"verdict-validate: {len(bad)} violation(s):\n  " + "\n  ".join(bad),
              file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"verdict-validate: OK — {args.state} satisfies the state contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
