#!/usr/bin/env python3
"""verdict-facts / verdict-finalize — the deterministic half of a QA run.

Stdlib only, runnable as bare scripts from a checkout.

Roughly two thirds of a state file is arithmetic and transcription: the
timestamp, the SHAs, the diff range, gate exit codes and durations, test
counts, finding hashes, ages, and deltas. None of it is judgment, all of it is
a place to be confidently wrong, and a prompt rule cannot stop a model from
inventing a value it is capable of inventing — two of four production
timestamps sat on exactly `:00` seconds months after `date -u` became a rule.

So the work moves:

    verdict-facts     measures. Runs the gates the caller names, times them,
                      parses their counts, reads git, derives the project key,
                      computes run_number and run_type. Writes facts.json.
                      Touches nothing else; read-only on the repository.

    <the agent>       judges. Writes judgment.json: verdict, findings (title,
                      severity, priority, classification, evidence, status),
                      not_tested, next_run_focus, isolation_check, quarantine.
                      Nothing it writes there is a number it had to compute.

    verdict-finalize  merges. Hashes each finding, matches it against the
                      previous state to assign first_seen, age_days, and the
                      NEW / STILL_OPEN / RESOLVED / REGRESSED delta, writes
                      state.json.prev, validates, and only then writes
                      state.json and the INDEX row.

`finalize` validates before it writes, because the PostToolUse validator hook
matches Write/Edit and would never see a file written by a shell command.
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from .census import code_census
    from .profile import ProfileError, gates_from
    from .profile import load as load_profile
    from .project_key import derive_key
    from .state import (OUTCOMES_FILE, calibration, is_open, load_outcomes,
                        merge_outcomes, norm_status, order_findings)
    from .state import home as state_home
    from .validate import validate, validate_judgment
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from census import code_census
    from profile import ProfileError, gates_from
    from profile import load as load_profile
    from project_key import derive_key
    from state import (OUTCOMES_FILE, calibration, is_open, load_outcomes,
                       merge_outcomes, norm_status, order_findings)
    from state import home as state_home
    from validate import validate, validate_judgment

RE_BASELINE_AFTER_DAYS = 7
# A run marker at the same commit, this recent, is a retry rather than a night
# that was lost. Generous: a mistyped gate command and a re-run can straddle a
# long investigation.
RETRY_WINDOW_HOURS = 6
RE_BASELINE_FILES = 100
RE_BASELINE_LINES = 10_000
# Runner dialects. Each carries a *signature* — a phrase only that runner
# prints — and is tried in order of how distinctive that signature is.
#
# The earlier design was a flat union of patterns that only spoke pytest, so
# for Go, Ruby, PHP, .NET and JVM projects the counts came back empty, and
# *silently*: the "a silent drop in test count is a finding" gate and the
# test-id set-diff simply never fired. A feature that is unavailable is a
# problem; one that is unavailable without saying so is a defect.
#
# Signatures rather than ordering alone, because these vocabularies overlap:
# `1 failure` appears in both gotestsum and rspec, `Failures: 1` in both
# surefire and phpunit, and `5 passed` in pytest, cargo, jest and vitest. Read
# by the wrong dialect the numbers are not wrong so much as incomplete — cargo
# read as pytest silently drops `ignored`, which is the skip count the gate
# cares about.
_DIALECTS = (
    # signature                          name            fields
    (r"Tests run:\s*\d+", "surefire", {                 # JUnit / Maven surefire
        "collected": r"Tests run:\s*(\d+)", "failed": r"Failures:\s*(\d+)",
        "errors": r"Errors:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)"}),
    (r"\bDONE\s+\d+\s+tests?\b", "gotestsum", {        # DONE 12 tests, 1 failure in 0.5s
        "collected": r"DONE\s+(\d+)\s+tests?", "failed": r"(\d+)\s+failures?",
        "skipped": r"(\d+)\s+skipped"}),
    (r"Total:\s*\d+", "dotnet", {                       # Failed: 0, Passed: 5, Total: 5
        "collected": r"Total:\s*(\d+)", "passed": r"Passed:\s*(\d+)",
        "failed": r"Failed:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)"}),
    (r"Assertions:\s*\d+", "phpunit", {                 # Tests: 5, Assertions: 10, Failures: 1.
        "collected": r"Tests:\s*(\d+)", "failed": r"Failures:\s*(\d+)",
        "errors": r"Errors:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)"}),
    (r"OK \(\d+ tests?", "phpunit", {                    # OK (5 tests, 5 assertions)
        "passed": r"OK \((\d+) tests?", "failed": r"^(?!)"}),
    (r"\d+ examples?\b", "rspec", {                     # 5 examples, 1 failure, 2 pending
        "collected": r"(\d+) examples?", "failed": r"(\d+) failures?",
        "skipped": r"(\d+) pending"}),
    (r"test result:", "cargo", {                        # test result: ok. 5 passed; 1 ignored
        "passed": r"(\d+) passed", "failed": r"(\d+) failed",
        "skipped": r"(\d+) ignored"}),
    (r"passed \(\d+\)", "vitest", {                       # Tests  2 failed | 5 passed (7)
        "collected": r"passed \((\d+)\)", "passed": r"(\d+) passed",
        "failed": r"(\d+) failed", "skipped": r"(\d+) skipped"}),
    (r"\d+ (?:total|todo)\b", "jest", {                   # Tests: 1 failed, 4 passed, 5 total
        "collected": r"(\d+) total", "passed": r"(\d+) passed",
        "failed": r"(\d+) failed", "skipped": r"(\d+) (?:skipped|todo)"}),
    (r"\d+ (?:passed|failed|skipped|xfailed|error)", "pytest", {
        "passed": r"(\d+) passed", "failed": r"(\d+) failed",
        "skipped": r"(\d+) skipped", "errors": r"(\d+) errors?\b",
        "xfailed": r"(\d+) xfailed"}),
)
_DIALECTS = tuple((re.compile(sig), name,
                   {f: re.compile(pat) for f, pat in fields.items()})
                  for sig, name, fields in _DIALECTS)
# `go test` proper prints no totals at all — only per-test lines under -v. It
# gets counted by tallying those, which is the only signal it offers.
_GO_VERBOSE = (re.compile(r"^--- PASS: ", re.M), re.compile(r"^--- FAIL: ", re.M),
               re.compile(r"^--- SKIP: ", re.M))
_COUNT_PATTERNS = tuple(
    (sig, name) for sig, name, _ in _DIALECTS) + tuple(
    (p, "go") for p in _GO_VERBOSE)


def _run(cmd, cwd=None, shell=False):
    return subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True)


def _git(args, repo):
    proc = _run(["git", "-C", str(repo), *args])
    return proc.stdout.strip() if proc.returncode == 0 else None


def _summary_line(output: str) -> str:
    """The last line carrying countable results — the line a human reads."""
    for line in reversed([x.strip() for x in output.splitlines() if x.strip()]):
        if any(p.search(line) for p, _ in _COUNT_PATTERNS):
            return line[:300]
    tail = [x.strip() for x in output.splitlines() if x.strip()]
    return tail[-1][:300] if tail else ""


def _counts(output: str) -> tuple[dict, str | None]:
    """Parse a runner's summary into counts, and say which dialect was read.

    Naming the dialect is not decoration: a reader who sees empty counts needs
    to know whether the suite reported nothing or whether we failed to
    understand it, and those are different problems with different fixes.
    """
    for signature, name, fields in _DIALECTS:
        if not signature.search(output):
            continue
        counts = {}
        for field, pattern in fields.items():
            m = pattern.search(output)
            if m:
                counts[field] = int(m.group(1))
        if counts:
            return counts, name
    passed, failed, skipped = (len(p.findall(output)) for p in _GO_VERBOSE)
    if passed or failed or skipped:
        return {"passed": passed, "failed": failed, "skipped": skipped}, "go test -v"
    return {}, None


_UNSET = object()


def _parse_marker_time(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def collect(repo: Path, qa_root: Path, gates: list[tuple[str, str]],
            test_ids_cmd: str | None = None, abandoned=_UNSET) -> dict:
    """Measure everything about this run that is not a judgment."""
    now = datetime.now(timezone.utc)
    previous = None
    state_path = qa_root / "state.json"
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

    # A marker left by the previous invocation means that run started and never
    # finished — the failure mode that once cost a whole night silently. It is
    # reported as a fact, not swept up: the next reader deserves to know the
    # gap exists.
    # Read from disk only when the caller has not already read it. `facts_main`
    # writes this run's marker before the gates start — so that a run killed
    # mid-suite still leaves one — which means by the time we get here the file
    # describes *this* run. Reading it here unconditionally made every healthy
    # run announce that the previous one had been abandoned, and a warning that
    # fires every time is one nobody reads.
    marker_path = qa_root / "run-in-progress.json"
    if abandoned is _UNSET:
        abandoned = None
        if marker_path.is_file():
            try:
                abandoned = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                abandoned = {"note": "unreadable marker"}

    key, key_source = derive_key(repo)
    sha = _git(["rev-parse", "HEAD"], repo)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    prev_sha = ((previous or {}).get("last_run") or {}).get("git_sha")
    sha_range = diff_stat = None
    files_changed = lines_changed = None
    if prev_sha and sha and _git(["cat-file", "-t", prev_sha], repo) == "commit":
        sha_range = f"{prev_sha}..{sha}"
        diff_stat = _git(["diff", "--shortstat", sha_range], repo)
        if diff_stat:
            nums = [int(n) for n in re.findall(r"(\d+)", diff_stat)]
            files_changed = nums[0] if nums else None
            lines_changed = sum(nums[1:]) if len(nums) > 1 else None

    run_number = int((previous or {}).get("run_number") or 0) + 1
    run_type, why = "baseline", "no previous state"
    if previous:
        run_type, why = "delta", "previous state present"
        prev_ts = ((previous or {}).get("last_run") or {}).get("timestamp_utc")
        try:
            age = now - datetime.strptime(str(prev_ts), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc)
        except (ValueError, TypeError):
            age = None
        if prev_sha and sha_range is None:
            run_type, why = "re-baseline", f"stored sha {prev_sha} is not in this repository"
        elif age is not None and age > timedelta(days=RE_BASELINE_AFTER_DAYS):
            run_type, why = "re-baseline", f"previous run was {age.days} days ago"
        elif (files_changed or 0) > RE_BASELINE_FILES or (lines_changed or 0) > RE_BASELINE_LINES:
            run_type, why = "re-baseline", f"diff spans {files_changed} files / {lines_changed} lines"

    gate_results = {}
    for name, command in gates:
        started = time.monotonic()
        proc = _run(command, cwd=repo, shell=True)
        duration = round(time.monotonic() - started, 2)
        output = proc.stdout + proc.stderr
        counts, dialect = _counts(output)
        gate_results[name] = {
            "command": command,
            "exit_code": proc.returncode,
            "result": "pass" if proc.returncode == 0 else "fail",
            "duration_s": duration,
            "summary": _summary_line(output),
            **({"counts": counts, "counts_dialect": dialect} if counts else
               {"counts_unparsed": "no recognised runner summary — the count-drop gate "
                                   "and the id set-diff cannot fire for this gate"}),
        }

    # Characteristic signatures of model-written code that are mechanically
    # countable — hallucinated imports, placeholders, swallowed exceptions,
    # AI-attribution of the range. Leads for §4.5 judgment, never findings.
    try:
        facts_census = code_census(repo, sha_range)
    except Exception as exc:  # a census must never cost a run
        facts_census = {"scope": f"census failed: {exc}"}

    facts = {
        "measured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": key,
        "project_key_source": key_source,
        "qa_root": str(qa_root),
        "schema_version": 1,
        "run_number": run_number,
        "run_type": run_type,
        "run_type_reason": why,
        "last_run": {
            "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_sha": sha, "git_branch": branch, "sha_range": sha_range,
            "diff_stat": diff_stat,
        },
        "gates": gate_results,
        "code_census": facts_census,
    }
    if abandoned:
        # A marker at this same commit, minutes old, is this run's own earlier
        # attempt — a mistyped gate command, a retry — not a night that was
        # lost. Reported as such and kept out of the alarm, because the alarm
        # exists to make a real gap visible and a reader who sees it fire on
        # every retry stops reading it. A marker at a *different* commit, or an
        # old one, is the real thing: coverage of that commit never happened.
        started = _parse_marker_time(abandoned.get("started_utc"))
        age_h = (now - started).total_seconds() / 3600 if started else None
        retry = (abandoned.get("git_sha") == sha and sha is not None
                 and age_h is not None and age_h <= RETRY_WINDOW_HOURS)
        if retry:
            facts["previous_attempt_this_run"] = {
                **abandoned,
                "age_hours": round(age_h, 2),
                "meaning": "an earlier attempt at this same commit, minutes ago — this "
                           "run's own retry, not a lost run. Nothing is missing",
            }
        else:
            facts["previous_run_incomplete"] = {
                **abandoned,
                **({"age_hours": round(age_h, 2)} if age_h is not None else {}),
                "meaning": "a previous run started and never wrote state; its work is "
                           "lost, not merely unreported",
            }

    tests = {}
    for gate in gate_results.values():
        tests.update(gate.get("counts", {}))
        if "duration_s" not in tests and gate.get("counts"):
            tests["duration_s"] = gate["duration_s"]
    if tests:
        # A runner that reports its own total is more trustworthy than our
        # arithmetic over its parts — several report both, and they disagree
        # when a test errors during collection.
        collected = tests.get("collected") or sum(
            v for k, v in tests.items()
            if k in ("passed", "failed", "skipped", "errors", "xfailed"))
        facts["tests"] = {**tests, "collected": collected}

    if test_ids_cmd:
        proc = _run(test_ids_cmd, cwd=repo, shell=True)
        ids = sorted({x.strip() for x in proc.stdout.splitlines() if "::" in x})
        if not ids:
            # Zero ids is almost never an empty suite; it is a command that
            # printed something else. The commonest cause is verbosity: a
            # project whose addopts already carry -q turns `--collect-only -q`
            # into -qq, which prints per-file counts instead of ids — the same
            # trap this tool's own liar fixture seeds. Reporting count 0 here
            # would be the lie §6 forbids ("0 collected is not 1 failing"), so
            # the ledger is left untouched and the gap is named.
            facts["test_ids"] = {
                "status": "unavailable",
                "reason": ("the id command produced no `::` lines "
                           f"(exit {proc.returncode}) — if the project's addopts already "
                           "set -q, drop the -q from --collect-only, which otherwise "
                           "becomes -qq and prints counts instead of ids"),
                "command": test_ids_cmd,
            }
        else:
            ledger = qa_root / "test-ids.txt"
            # splitlines, not split: parametrised ids contain spaces
            # (`test_rate[west 7kg]`), and whitespace-splitting the ledger
            # turns one id into several — every one of which then reads as
            # added or removed on the next run.
            before = ([x.strip() for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
                      if ledger.is_file() else [])
            facts["test_ids"] = {
                "status": "measured",
                "count": len(ids),
                "added": sorted(set(ids) - set(before))[:50],
                "removed": sorted(set(before) - set(ids))[:50],
                "source": "id set-diff, not summary arithmetic",
            }
            facts["_test_ids"] = ids
    return facts


# ── finalize ──────────────────────────────────────────────────────────────

_LINE_NUMBERS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def finding_hash(finding: dict) -> str:
    """Stable identity: cited path + normalized title, line numbers stripped.

    Deliberately not the id: ids are minted once for humans, hashes recognise
    the same finding across runs while line numbers move underneath it.
    """
    if finding.get("hash"):
        return str(finding["hash"])
    evidence = " ".join(str(e) for e in (finding.get("evidence") or []))
    m = re.search(r"([A-Za-z0-9_./-]+\.[A-Za-z]{1,5})", evidence)
    path = m.group(1) if m else ""
    title = _WS.sub(" ", _LINE_NUMBERS.sub("", str(finding.get("title", "")))).strip().lower()
    return hashlib.sha256(f"{path}|{title}".encode()).hexdigest()[:8]


DECIDED = ("confirmed", "refuted")


def _stamp_outcome(finding: dict, prior: dict | None = None) -> dict:
    """Derive the outcome from what the finding did — never from asking.

    Three things settle a finding. It regressed (it was fixed and came back, so
    it was real). It was resolved and the fix was verified by re-injection (§6:
    absence is not evidence, a failing guard is). Or the tester withdrew it,
    which is the one event that says it was never real.

    A settled outcome then *sticks*. Without that, a finding confirmed by
    regression on run 12 and still open on run 13 would quietly return to
    undecided, and the track record would erode every time a finding changed
    state. Withdrawal is the sole exception: an explicit correction outranks an
    earlier inference, because it is the tester saying it got this wrong.
    """
    delta, status = finding.get("delta"), norm_status(finding.get("status"))
    if delta == "WITHDRAWN" or status == "withdrawn":
        return {"outcome": "refuted",
                "outcome_reason": "withdrawn by the tester as never real"}
    prior_outcome = (prior or {}).get("outcome")
    if prior_outcome in DECIDED:
        return {"outcome": prior_outcome,
                "outcome_reason": (prior or {}).get("outcome_reason")
                or "settled by an earlier run"}
    if delta == "REGRESSED":
        return {"outcome": "confirmed",
                "outcome_reason": "regressed: it was fixed and came back, so it was real"}
    if delta == "RESOLVED" and finding.get("fix_verified") is True:
        return {"outcome": "confirmed",
                "outcome_reason": "fix-verified: the guarding test failed on re-injection"}
    if delta == "RESOLVED" and finding.get("carried_forward"):
        # Weaker still than an unverified resolution: nobody claimed anything.
        return {"outcome": "unknown",
                "outcome_reason": "not re-reported; no one verified anything"}
    if delta == "RESOLVED":
        return {"outcome": "unknown",
                "outcome_reason": "resolved but not fix-verified — absence is not proof"}
    return {"outcome": "unknown", "outcome_reason": "still open; nothing has settled it"}


def merge(facts: dict, judgment: dict, previous: dict | None, today: date | None = None,
          ledger: dict | None = None) -> dict:
    """Facts + judgment → a state file, with identity and deltas computed.

    `ledger` is the permanent outcome ledger (`outcomes.json`); passing it in
    keeps this function pure while letting the calibration block count every
    finding this project ever filed, not just the ones still in state.
    """
    today = today or date.today()
    prev_by_hash, prev_by_id = {}, {}
    for f in ((previous or {}).get("findings") or []):
        if f.get("hash"):
            prev_by_hash[str(f["hash"])] = f
        if f.get("id"):
            prev_by_id[str(f["id"])] = f

    findings = []
    seen = set()
    for f in judgment.get("findings", []) or []:
        entry = dict(f)
        h = finding_hash(entry)
        prior = prev_by_hash.get(h)
        if prior is None:
            # Fall back to the id. The hash is a *content fingerprint* — cited
            # path plus normalized title — and it drifts the moment the tester
            # rewords its own finding, which it does constantly as evidence
            # accumulates. The id does not drift: §6 mints it once and forbids
            # reuse, so a re-reported id is a deliberate identity claim.
            #
            # Without this, a reworded re-report is filed as NEW *and* carried
            # forward as resolved — two entries, one id, and a state the
            # validator rightly refuses to write. Every hash in four live
            # projects was hand-authored before the harness existed and matches
            # nothing computable, so without the fallback no project could ever
            # take its first harness-driven run.
            prior = prev_by_id.get(str(entry.get("id") or ""))
            if prior is not None and prior.get("hash"):
                h = str(prior["hash"])  # identity is continuous; the fingerprint moved
        entry["hash"] = h
        seen.add(h)
        first_seen = (prior or {}).get("first_seen") or today.isoformat()
        entry["first_seen"] = first_seen
        try:
            entry["age_days"] = (today - date.fromisoformat(str(first_seen))).days
        except ValueError:
            entry["age_days"] = 0
        status = norm_status(entry.get("status", "open")) or "open"
        entry["status"] = status
        if entry.get("delta") == "WITHDRAWN":
            # The tester's own correction; the delta is never overwritten, and
            # the status follows from it — a finding that was never real cannot
            # also be open, and left to drift it would keep counting toward
            # blockers it has already been retracted from.
            entry["status"] = status = "withdrawn"
        elif prior is None:
            entry["delta"] = "NEW"
        elif status == "resolved":
            entry["delta"] = "RESOLVED"
        elif prior.get("status") == "resolved":
            entry["delta"] = "REGRESSED"
        else:
            entry["delta"] = "STILL_OPEN"

        # The claim is frozen at filing. Calibration scores a prediction, and a
        # confidence revised after the outcome is known is hindsight wearing a
        # prediction's clothes.
        if prior and prior.get("confidence"):
            entry["confidence"] = prior["confidence"]
        entry.update(_stamp_outcome(entry, prior))
        findings.append(entry)

    # A finding the previous run had and this run did not mention is resolved —
    # silence is not the same as an assertion, so it is carried, not dropped.
    for h, prior in prev_by_hash.items():
        if h in seen:
            continue
        if norm_status(prior.get("status")) == "withdrawn":
            # A withdrawal is the tester's own error record. Resolutions age out
            # of state into the reports and the ledger; this one stays visible,
            # because a tester that files a false positive and lets it fall off
            # the page next run is hiding the number that weighs all the others.
            findings.append(dict(prior))
            continue
        if norm_status(prior.get("status")) == "resolved":
            continue
        carried = dict(prior)
        carried.update(status="resolved", delta="RESOLVED",
                       carried_forward="not reported this run; no longer observed")
        # Silence is not verification. A finding nobody re-reported proves
        # nothing about whether it was real, so it stays undecided — unless an
        # earlier run already settled it, which silence cannot undo either.
        carried.update(_stamp_outcome(carried, prior))
        findings.append(carried)

    state = {
        "project": facts["project"],
        "schema_version": facts.get("schema_version", 1),
        "run_type": facts["run_type"],
        "run_number": facts["run_number"],
        "last_run": {**facts["last_run"], "report": judgment.get("report", "")},
        "isolation_check": judgment.get("isolation_check", {}),
        "gates": facts.get("gates", {}),
        "findings": findings,
        "verdict": judgment.get("verdict"),
        "release_blockers": judgment.get("release_blockers", []),
        "not_tested": judgment.get("not_tested", []),
    }
    for optional in ("run_label", "next_run_focus", "flaky_quarantine", "coverage"):
        if judgment.get(optional) is not None:
            state[optional] = judgment[optional]
    if facts.get("tests"):
        state["tests"] = facts["tests"]
    # Computed here rather than left to a consumer: the next run reads
    # state.json anyway, so its own track record arrives without asking for it.
    # Folded once, and carried: computing it here from `today` and again in
    # write_state from the run timestamp gave two different `decided_on` dates
    # across a UTC-midnight run, so the calibration block inside the state
    # could disagree with the ledger persisted beside it.
    decided_on = str((state.get("last_run") or {}).get("timestamp_utc") or "")[:10] \
        or today.isoformat()
    state["_ledger"] = merge_outcomes(ledger or {}, findings, decided_on)
    state["calibration"] = calibration(state, ledger=state["_ledger"])
    if facts.get("test_ids"):
        state["test_ids"] = facts["test_ids"]
    # Unknown keys from the previous state survive (schema rule).
    for key, value in (previous or {}).items():
        state.setdefault(key, value)
    state.pop("_qa_root", None)
    return state


def index_row(state: dict) -> str:
    t = state.get("tests") or {}
    counts = f"{t.get('passed', 'n/a')} / {t.get('skipped', 'n/a')} / {t.get('failed', 'n/a')}"
    sev = {}
    for f in state.get("findings", []):
        if is_open(f):
            sev[f.get("severity")] = sev.get(f.get("severity"), 0) + 1
    bcmm = "/".join(str(sev.get(s, 0)) for s in ("Blocker", "Critical", "Major", "Minor"))
    report = str((state.get("last_run") or {}).get("report") or "")
    name = Path(report).name
    return (f"| {date.today().isoformat()} | {state['project']} | {state['run_type']} "
            f"| {state['verdict']} | {counts} | n/a | {bcmm} | [{name}]({report}) |")


INDEX_HEADER = ("| Date | Project | Run type | Verdict | Tests (pass/skip/fail) | Δ tests "
                "| Findings (B/C/M/m) | Report |\n|---|---|---|---|---|---|---|---|")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and `os.replace`, which is atomic on POSIX and
    Windows alike. Nothing here is large enough for the extra copy to matter,
    and a torn state.json costs a run at best."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_state(qa_root: Path, state: dict) -> list[str]:
    """Validate, then write: state.json.prev, state.json, and the INDEX row.

    Validation happens here because the PostToolUse hook matches Write/Edit and
    would never see a file a shell command wrote. An invalid state is not
    written at all — prevention beats notification.
    """
    # The ledger `merge` folded travels on the state under a private key —
    # taken off before anything serialises it, because reusing that result is
    # what keeps the persisted ledger and the state's own calibration block
    # describing the same run, and a leading underscore is not a licence to
    # write internals into the artifact.
    ledger = state.pop("_ledger", None)
    problems = validate(state, qa_root, _read_json(qa_root / "state.json"))
    if problems:
        return problems
    if ledger is None:
        decided_on = str((state.get("last_run") or {}).get("timestamp_utc") or "")[:10] or None
        ledger = merge_outcomes(load_outcomes(qa_root), state.get("findings", []), decided_on)

    # Atomic replace, not a bare write. A crash between truncate and flush
    # leaves the file the whole system pivots on half-written, and §6 already
    # carries a rule for recovering from a corrupt state — cheaper to make it
    # near-impossible than to handle it well.
    _atomic_write(qa_root / "state.json.prev",
                  (qa_root / "state.json").read_text(encoding="utf-8")) \
        if (qa_root / "state.json").is_file() else None
    _atomic_write(qa_root / "state.json", json.dumps(state, indent=2) + "\n")
    _atomic_write(qa_root / OUTCOMES_FILE,
                  json.dumps({"schema_version": 1, "project": state.get("project"),
                              "findings": ledger}, indent=2, sort_keys=True) + "\n")

    reports = qa_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    index = reports / "INDEX.md"
    if index.is_file():
        body = index.read_text(encoding="utf-8").rstrip("\n")
    else:
        body = f"# QA run index — {state['project']}\n\n{INDEX_HEADER}"
    _atomic_write(index, body + "\n" + index_row(state) + "\n")
    return []


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_root(repo: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    team = repo / ".qa"
    if team.is_dir():
        return team
    home = state_home()  # one spelling of the default, in state.py
    return home / derive_key(repo)[0]


def facts_main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="verdict-facts",
        description="Measure the deterministic half of a QA run. Read-only on the repo.")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--qa-root", default=None)
    ap.add_argument("--gate", action="append", default=[], metavar="NAME=COMMAND",
                    help="a gate to run and measure; repeatable")
    ap.add_argument("--test-ids-cmd", default=None,
                    help="command printing one test id per line, for set-diff accounting")
    ap.add_argument("--out", type=Path, default=None, help="also write facts.json here")
    ap.add_argument("--reuse-if-fresh", action="store_true",
                    help="reuse an existing facts.json when it describes this same HEAD "
                         "and is recent — a retry should not re-run the suite")
    ap.add_argument("--reuse-max-age-min", type=float, default=90.0)
    ap.add_argument("--no-profile", action="store_true",
                    help="ignore the profile's front-matter block (explicit --gate only)")
    args = ap.parse_args(argv)

    gates = []
    for spec in args.gate:
        if "=" not in spec:
            ap.error(f"--gate expects NAME=COMMAND, got {spec!r}")
        name, command = spec.split("=", 1)
        gates.append((name.strip(), command.strip()))

    repo = args.repo.expanduser().resolve()
    qa_root = _resolve_root(repo, args.qa_root)
    qa_root.mkdir(parents=True, exist_ok=True)

    # The profile already records the project's real commands; retyping them
    # into flags on every run is a transcription step, and a transcription step
    # is a place for the model to be confidently wrong. Explicit --gate still
    # wins — a caller narrowing a run should not have to edit the profile.
    profile_notes, profile_source, declared_authorship = [], None, None
    if not args.no_profile:
        try:
            config, profile_notes = load_profile(qa_root)
        except ProfileError as exc:
            print(f"verdict-facts: {exc}", file=sys.stderr)
            return 2
        from_profile = gates_from(config)
        named = {name for name, _ in gates}
        adopted = [(n, c) for n, c in from_profile if n not in named]
        gates.extend(adopted)
        if adopted:
            profile_source = [n for n, _ in adopted]
        if config.get("authorship"):
            declared_authorship = config["authorship"]
        if args.test_ids_cmd is None and config.get("test_ids_cmd"):
            args.test_ids_cmd = config["test_ids_cmd"]
            profile_notes.append("test_ids_cmd taken from the profile")
        overridden = [n for n, _ in from_profile if n in named]
        if overridden:
            profile_notes.append(
                "gates overridden on the command line: " + ", ".join(sorted(overridden)))

    # Reuse, not resume. A model's judgment cannot be continued from the
    # middle, but the gates it was about to judge can be spared a second run —
    # and only while they still describe this commit and are minutes old.
    existing = _read_json(qa_root / "facts.json") if args.reuse_if_fresh else None
    if existing:
        head = _git(["rev-parse", "HEAD"], repo)
        try:
            age = (datetime.now(timezone.utc) - datetime.strptime(
                existing.get("measured_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)).total_seconds() / 60
        except (ValueError, TypeError):
            age = 1e9
        same_head = (existing.get("last_run") or {}).get("git_sha") == head
        if same_head and age <= args.reuse_max_age_min:
            existing["reused"] = {"measured_at": existing.get("measured_at"),
                                  "age_minutes": round(age, 1),
                                  "why": "same HEAD, within the freshness window; "
                                         "gates were not re-run"}
            print(json.dumps(existing, indent=2))
            return 0

    # Order matters: read whatever the last run left behind, *then* stake this
    # run's claim. The marker is written before the gates so a run killed
    # mid-suite still leaves a trace.
    abandoned = _read_json(qa_root / "run-in-progress.json")
    (qa_root / "run-in-progress.json").write_text(json.dumps({
        "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": str(repo),
        # The commit is what separates "my own retry" from "last night died".
        "git_sha": _git(["rev-parse", "HEAD"], repo)}, indent=2) + "\n",
        encoding="utf-8")
    facts = collect(repo, qa_root, gates, args.test_ids_cmd, abandoned=abandoned)
    if declared_authorship:
        facts.setdefault("code_census", {}).setdefault("provenance", {})[
            "declared"] = declared_authorship
    if profile_source:
        facts["gates_from_profile"] = profile_source
    if profile_notes:
        facts["profile_notes"] = profile_notes
    if not gates:
        # Said out loud rather than left to inference: a run with no gates
        # measured nothing, and "nothing to measure" and "nobody told me what
        # to measure" are different states of the world.
        facts["no_gates"] = ("no gates ran — neither --gate nor a profile front-matter "
                             "block supplied one, so every count and duration gate is "
                             "unmeasurable this run")
    ids = facts.pop("_test_ids", None)
    if ids is not None:
        (qa_root / "test-ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    text = json.dumps(facts, indent=2)
    (args.out or (qa_root / "facts.json")).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def finalize_main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="verdict-finalize",
        description="Merge measured facts with the agent's judgment into state.json.")
    ap.add_argument("--qa-root", required=True)
    ap.add_argument("--facts", type=Path, default=None, help="default: <qa-root>/facts.json")
    ap.add_argument("--judgment", type=Path, required=True)
    args = ap.parse_args(argv)

    qa_root = Path(args.qa_root).expanduser().resolve()
    facts = _read_json(args.facts or (qa_root / "facts.json"))
    judgment = _read_json(args.judgment)
    if facts is None:
        print("verdict-finalize: facts.json missing or unreadable — run verdict-facts first",
              file=sys.stderr)
        return 2
    if judgment is None:
        print(f"verdict-finalize: {args.judgment} missing or unreadable", file=sys.stderr)
        return 2

    previous = _read_json(qa_root / "state.json")

    # Checked here, where the author of judgment.json still stands. Validating
    # only the merged state stops a bad state reaching disk but explains it in
    # the vocabulary of a structure the agent did not write — a reworded
    # evidence line used to surface as `repeats id`, which says nothing about
    # what to change.
    author_problems = validate_judgment(judgment, previous)
    if author_problems:
        print(f"verdict-finalize: {args.judgment} has {len(author_problems)} problem(s) "
              "— fix the judgment, not the check:\n  " + "\n  ".join(author_problems),
              file=sys.stderr)
        return 1

    state = merge(facts, judgment, previous, ledger=load_outcomes(qa_root))

    # Render the report before validating: the validator requires the file to
    # exist, and writing it here is what makes "the report went missing"
    # impossible rather than merely forbidden.
    report_rel = (state.get("last_run") or {}).get("report") or ""
    if not report_rel or not report_rel.endswith(".md"):
        stamp = facts.get("measured_at", "")[:10]
        topic = judgment.get("topic") or state.get("run_type", "run")
        report_rel = f"reports/{stamp}-{topic}.md".replace(" ", "-")
        state["last_run"]["report"] = report_rel
    report_path = qa_root / report_rel
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(state, judgment.get("prose")), encoding="utf-8")

    problems = write_state(qa_root, state)
    if problems:
        print(f"verdict-finalize: refusing to write an invalid state "
              f"({len(problems)} problem(s)):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    marker = qa_root / "run-in-progress.json"
    marker.unlink(missing_ok=True)
    print(f"verdict-finalize: wrote {qa_root / 'state.json'} and {report_path} "
          f"(run {state['run_number']}, {state['run_type']}, verdict {state['verdict']!r}), "
          f"appended the INDEX row, cleared the run marker")
    return 0


def main(argv=None) -> int:
    """Bare-script entry: an explicit subcommand, because dispatching on the
    script's own filename breaks the moment anyone renames or symlinks it."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("facts", "finalize"):
        sub = argv.pop(0)
        return facts_main(argv) if sub == "facts" else finalize_main(argv)
    print("usage: harness.py {facts|finalize} [options]   "
          "(installed as verdict-facts / verdict-finalize)", file=sys.stderr)
    return 2




# ── the report, rendered ──────────────────────────────────────────────────

def _render_calibration(cal: dict) -> list[str]:
    """The tester's own track record, or nothing at all.

    Nothing at all until something has actually been settled: a section reading
    "0 of 0" trains the reader to skip it, and by the time there is a number
    worth seeing they no longer look. Rates stay hidden until the bucket has
    enough decided outcomes to earn one — `reading` carries the counts either
    way, so the section is honest at every sample size.
    """
    if not cal or not cal.get("decided_outcomes"):
        return []
    lines = ["", "## Track record", "",
             f"{cal.get('findings_tracked', 0)} findings tracked across this project's "
             f"history · {cal['decided_outcomes']} settled, "
             f"{cal.get('undecided_outcomes', 0)} still undecided.", ""]
    for label, store in (("Confidence claimed", cal.get("by_confidence") or {}),
                         ("Proof method", cal.get("by_proof_method") or {})):
        rows = [(k, v) for k, v in store.items() if v.get("decided")]
        if not rows:
            continue
        lines += [f"| {label} | Held up | Withdrawn | Rate |", "|---|---|---|---|"]
        for key, v in sorted(rows, key=lambda kv: -kv[1]["decided"]):
            rate = f"{v['precision']:.0%}" if v.get("precision") is not None else "_not yet_"
            lines.append(f"| {key} | {v['confirmed']} | {v['refuted']} | {rate} |")
        lines.append("")
    lines += [f"*A rate appears once a row has {cal.get('min_sample')} settled outcomes. "
              "Settled means fix-verified or regressed (it held up) against withdrawn "
              "(it did not); a finding merely resolved is not evidence either way.*", ""]
    return lines


def render_report(state: dict, prose: dict | None = None) -> str:
    """Render the report from the state, injecting the agent's prose.

    Everything countable comes from the state, so the report and the state
    cannot disagree — they did, once, when the state pointed at a stale file.
    Everything that requires a sentence comes from `prose`, because a rendered
    table is not an explanation and nobody should pretend otherwise.
    """
    prose = prose or {}
    last = state.get("last_run") or {}
    out = [f"# QA report — {state.get('project')} · run {state.get('run_number')} "
           f"({state.get('run_type')})", ""]
    if state.get("run_label"):
        out += [f"*{state['run_label']}*", ""]
    out += [f"**VERDICT: {state.get('verdict')}**", ""]

    out += ["## Scope", "",
            f"- Range: `{last.get('sha_range') or last.get('git_sha') or 'n/a'}`"
            + (f" · {last['diff_stat']}" if last.get("diff_stat") else ""),
            f"- Branch: `{last.get('git_branch') or 'n/a'}` · measured {last.get('timestamp_utc')}"]
    iso = state.get("isolation_check") or {}
    if iso:
        detail = iso.get("method") or iso.get("note") or ""
        out.append(f"- Isolation check: **{iso.get('result', iso.get('status', 'n/a'))}**"
                   + (f" — {detail}" if detail else ""))
    if prose.get("scope"):
        out += ["", prose["scope"]]

    gates = state.get("gates") or {}
    if gates:
        out += ["", "## Gates", "", "| Gate | Result | Exit | Duration | Summary |",
                "|---|---|---|---|---|"]
        for name, g in gates.items():
            out.append(f"| `{name}` | {g.get('result', '?')} | {g.get('exit_code', '?')} "
                       f"| {g.get('duration_s', '?')}s | {str(g.get('summary', ''))[:120]} |")
    tests = state.get("tests") or {}
    if tests:
        counted = ", ".join(f"{k} {v}" for k, v in tests.items() if k != "duration_s")
        out += ["", f"Tests: {counted}"]
    ids = state.get("test_ids") or {}
    if ids.get("status") == "measured":
        out.append(f"Test-id ledger: {ids['count']} ids · +{len(ids.get('added', []))} "
                   f"/ −{len(ids.get('removed', []))} (set-diff, not summary arithmetic)")
    elif ids.get("status") == "unavailable":
        out.append(f"Test-id ledger: **unavailable** — {ids.get('reason', '')}")

    if prose.get("risks"):
        out += ["", "## Risks", "", prose["risks"]]

    # The gate, the MCP surface and this report must agree on what "REGRESSED
    # first" means. They did not: this module carried its own copy of the sort,
    # and a severity with a stray space already sorted differently in the two.
    findings = order_findings(state.get("findings") or [])
    open_f = [f for f in findings if is_open(f)]
    out += ["", f"## Findings — REGRESSED first ({len(open_f)} open of {len(findings)} tracked)", ""]
    if not findings:
        out.append("_None recorded this run._")
    for f in findings:
        cls = f.get("failure_classification")
        out.append(f"### {f.get('id')} — {f.get('delta', '?')} — "
                   f"{f.get('severity')}/{f.get('priority')}"
                   + (f" — {cls}" if cls else "")
                   + (f" — age {f['age_days']}d" if f.get("age_days") else ""))
        out.append("")
        out.append(str(f.get("title", "")))
        for e in (f.get("evidence") or []):
            out.append(f"- {e}")
        rc = f.get("root_cause") or {}
        if rc:
            chain = " → ".join(str(rc[k]) for k in ("mechanism", "origin") if rc.get(k))
            if chain:
                out.append(f"- Root cause: {chain}")
            if rc.get("class"):
                out.append(f"- Class: {json.dumps(rc['class'])[:200]}")
        if f.get("carried_forward"):
            out.append(f"- _{f['carried_forward']}_")
        if prose.get("findings", {}).get(str(f.get("id"))):
            out += ["", prose["findings"][str(f.get("id"))]]
        out.append("")

    out += _render_calibration(state.get("calibration") or {})

    blockers = state.get("release_blockers") or []
    out += ["## Release blockers", "",
            "\n".join(f"- {b}" for b in blockers) if blockers else "_None._", ""]
    out += ["## Not tested", ""]
    nt = state.get("not_tested") or []
    out.append("\n".join(f"- {n}" for n in nt) if nt else
               "_Nothing listed — which is itself a reporting failure if the surface was not covered._")
    if prose.get("fix_order"):
        out += ["", "## Fix order", "", prose["fix_order"]]
    if state.get("next_run_focus"):
        out += ["", "## Next run focus", "",
                "\n".join(f"- {n}" for n in state["next_run_focus"])]
    quarantine = state.get("flaky_quarantine") or []
    if quarantine:
        out += ["", "## Quarantine", ""]
        for q in quarantine:
            out.append(f"- `{q.get('test_id')}` until {q.get('quarantined_until')} "
                       f"({q.get('fail_count', '?')}/{q.get('run_count', '?')} runs)")
    if prose.get("notes"):
        out += ["", "## Notes", "", prose["notes"]]
    out += ["", "---", "",
            "*Countable sections rendered from `state.json` by `verdict-finalize`; the "
            "prose is the agent's. They cannot disagree.*"]
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
