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

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from . import questions
    from .anchors import DRIFTED, evidence_drift
    from .census import code_census
    from .hygiene import hygiene_census, is_hygiene
    from .filed import FINDINGS_DIR, archive_findings, load_filed
    from .readfirst import read_first
    from .focus import risk_focus
    from .replay import adopt_backfill, load_backfill, measure_findings, without_repro
    from .escalate import not_tested_line as escalation_not_tested
    from .reports import read_report
    from .profile import RISK_CLASSES, ProfileError, gates_from, hygiene_filing_from, contract_rule_from, repro_rule_from, risk_class_from, risk_paths_from, assertion_gaps_from
    from .profile import load as load_profile
    from .project_key import derive_key
    from .state import (is_open, load_accepted, load_outcomes, norm_status, order_findings,
                        project_key_for_root)
    from .state import load_runs
    from .state import misplaced_root, root_refusal
    from .usage import ENTRYPOINT_ENV, SESSION_ENV, run_usage
    from .usage import FIELDS as USAGE_FIELDS
    from .validate import (inherited_conflicts, known_tests, report_outside_reports,
                           validate_judgment)
    from . import clock
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import questions
    from anchors import DRIFTED, evidence_drift
    from census import code_census
    from hygiene import hygiene_census, is_hygiene
    from filed import FINDINGS_DIR, archive_findings, load_filed
    from readfirst import read_first
    from focus import risk_focus
    from replay import adopt_backfill, load_backfill, measure_findings, without_repro
    from escalate import not_tested_line as escalation_not_tested
    from reports import read_report
    from profile import RISK_CLASSES, ProfileError, gates_from, hygiene_filing_from, contract_rule_from, repro_rule_from, risk_paths_from, assertion_gaps_from, risk_class_from
    from profile import load as load_profile
    from project_key import derive_key
    from state import (is_open, load_accepted, load_outcomes, norm_status, order_findings,
                       project_key_for_root)
    from state import load_runs
    from state import misplaced_root, root_refusal
    from usage import ENTRYPOINT_ENV, SESSION_ENV, run_usage
    from usage import FIELDS as USAGE_FIELDS
    from validate import (inherited_conflicts, known_tests, report_outside_reports,
                          validate_judgment)
try:  # split out of this file by the structure pass; still importable here
    from .harness_common import (HYGIENE_LEDGER_FILE, _chosen, _git, _read_json, _resolve_root,
                                 _run, _session_identity)
except ImportError:  # executed as a bare script
    from harness_common import (HYGIENE_LEDGER_FILE, _chosen, _git, _read_json, _resolve_root,
                                _run, _session_identity)
try:  # split out of this file by the structure pass; still importable here
    from .facts_suite import (_counts, _summary_line, cannot_start, duration_regressed,
                              executed_nothing)
except ImportError:  # executed as a bare script
    from facts_suite import (_counts, _summary_line, cannot_start, duration_regressed,
                             executed_nothing)
try:  # split out of this file by the structure pass; still importable here
    from .facts_verify import (verify_findings, _drop_bytecode as _drop_bytecode,
                               _run_test as _run_test, _scratch_checkout as _scratch_checkout,
                               cited_tests as cited_tests, resolve_test_id as resolve_test_id,
                               select_test as select_test)
except ImportError:  # executed as a bare script
    from facts_verify import (verify_findings, _drop_bytecode as _drop_bytecode,
                              _run_test as _run_test, _scratch_checkout as _scratch_checkout,
                              cited_tests as cited_tests, resolve_test_id as resolve_test_id,
                              select_test as select_test)
try:  # split out of this file by the structure pass; still importable here
    from .facts_reading import (_test_id_from_context as _test_id_from_context, is_test_file,
                                reading_map_from as reading_map_from)
except ImportError:  # executed as a bare script
    from facts_reading import (_test_id_from_context as _test_id_from_context, is_test_file,
                               reading_map_from as reading_map_from)
try:  # split out of this file by the structure pass; still importable here
    from .facts_coverage import (PREMEASURED_ENV, PREMEASURED_MAX_AGE_MIN, _changed_lines,
                                 _coverage_with_gaps, _put, _restake_marker,
                                 GAPS_MIN_S as GAPS_MIN_S, _diff_from_files as _diff_from_files,
                                 _render_cmd as _render_cmd, _run_coverage as _run_coverage)
except ImportError:  # executed as a bare script
    from facts_coverage import (PREMEASURED_ENV, PREMEASURED_MAX_AGE_MIN, _changed_lines,
                                _coverage_with_gaps, _put, _restake_marker,
                                GAPS_MIN_S as GAPS_MIN_S, _diff_from_files as _diff_from_files,
                                _render_cmd as _render_cmd, _run_coverage as _run_coverage)
try:  # split out of this file by the structure pass; still importable here
    from .hygiene_facts import (hygiene_evidence as hygiene_evidence, split_hygiene,
                                tier2_items as tier2_items)
except ImportError:  # executed as a bare script
    from hygiene_facts import (hygiene_evidence as hygiene_evidence, split_hygiene,
                               tier2_items as tier2_items)
try:  # split out of this file by the structure pass; still importable here
    from .finalize_ids import finding_hash as finding_hash, next_finding_id
except ImportError:  # executed as a bare script
    from finalize_ids import finding_hash as finding_hash, next_finding_id
try:  # split out of this file by the structure pass; still importable here
    from .finalize_carry import (_apply_replay as _apply_replay, _replay_fresh_findings,
                                 _stamp_outcome as _stamp_outcome,
                                 read_first_accounting as read_first_accounting, run_date,
                                 survivor_accounting)
except ImportError:  # executed as a bare script
    from finalize_carry import (_apply_replay as _apply_replay, _replay_fresh_findings,
                                _stamp_outcome as _stamp_outcome,
                                read_first_accounting as read_first_accounting, run_date,
                                survivor_accounting)
try:  # split out of this file by the structure pass; still importable here
    from .finalize_write import (check_artifacts, write_state, INDEX_HEADER as INDEX_HEADER,
                                 index_row as index_row)
except ImportError:  # executed as a bare script
    from finalize_write import (check_artifacts, write_state, INDEX_HEADER as INDEX_HEADER,
                                index_row as index_row)
try:  # split out of this file by the structure pass; still importable here
    from .finalize_merge import merge
except ImportError:  # executed as a bare script
    from finalize_merge import merge

RE_BASELINE_AFTER_DAYS = 7
# A run marker at the same commit, this recent, is a retry rather than a night
# that was lost. Generous: a mistyped gate command and a re-run can straddle a
# long investigation.
RETRY_WINDOW_HOURS = 6
RE_BASELINE_FILES = 100
RE_BASELINE_LINES = 10_000


def _harness_identity() -> dict:
    """Which code measured this — the file that ran, and the version it says
    it is.

    The runner and the harness can come from different places: `verdict-run`
    from a wheel or a git ref, `verdict-facts` from whatever the agent finds
    first — the plugin cache, an installed copy, a checkout. On the third
    stranger run (changesets) the runner came from main and the facts from the
    published 0.80.1 in the plugin cache, and the only way to tell was to
    recognise a parser bug that main had already fixed. The path is the fact;
    the version is the file's own claim about itself.
    """
    try:
        from verdict_mcp import __version__ as declared
    except Exception:                                    # pragma: no cover
        declared = "0+unknown"
    return {"version": declared, "path": str(Path(__file__).resolve())}


def _sha256_of(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _prompt_identity(repo: Path) -> dict:
    """Which prompt judged — as a hash, because a version number is a claim.

    Two files can be the prompt: the one shipped beside this harness
    (`<plugin>/agents/verdict.md`) and the one Claude Code actually loaded in a
    team-mode checkout (`<repo>/.claude/agents/verdict.md`, provisioned from
    some plugin version, not necessarily this one). Both are hashed when
    present; the eval ledger reads the first, a drift between the two is a
    finding. Prompt versions were "byte-identical since 0.74.0" by assertion
    until now; a hash makes the assertion checkable.
    """
    root = Path(__file__).resolve().parents[2]
    out = {}
    shipped = _sha256_of(root / "agents" / "verdict.md")
    if shipped:
        out["prompt_sha256"] = shipped
    provisioned = _sha256_of(Path(repo) / ".claude" / "agents" / "verdict.md")
    if provisioned:
        out["provisioned_prompt_sha256"] = provisioned
    return out


def finding_template() -> Path:
    """One finding — the shape of `<qa-root>/findings/<ID>.json`."""
    return Path(__file__).resolve().parent / "templates" / "finding.example.json"


def judgment_template() -> Path:
    """The complete example judgment, shipped inside the package so a wheel
    and a plugin checkout name the same file. Every run used to learn the
    judgment's shape by reading `docs/state-schema.md` and `harness.py` during
    the run (2–3 minutes, ~15k characters) and three runs out of four still met
    the validator on a shape; a template is copied, not studied."""
    return Path(__file__).resolve().parent / "templates" / "judgment.example.json"


_UNSET = object()


def _ago(age_h: float) -> str:
    """A short age phrase that cannot contradict the hours beside it.

    The retry window is six hours wide, and a fixed "minutes ago" inside it put
    a false sentence next to a true number in the same object (VERDICT-F-53).
    """
    minutes = int(round(age_h * 60))
    if minutes < 1:
        return "seconds ago"
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    return f"{age_h:.1f} hours ago" if age_h >= 1.05 else "1 hour ago"


def _parse_marker_time(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def collect(repo: Path, qa_root: Path, gates: list[tuple[str, str]],
            test_ids_cmd: str | None = None, abandoned=_UNSET,
            test_one_cmd: str | None = None, coverage_suite_cmd: str | None = None,
            sha_range: str | None = None, hygiene_filing: str = "on",
            assertion_gaps: dict | None = None) -> dict:
    """Measure everything about this run that is not a judgment.

    `hygiene_filing` is the profile's `hygiene:` setting, which each caller reads
    with `hygiene_filing_from`: "off" counts every tier and files nothing. It is
    taken here, not patched onto the facts afterwards, so that no engine that
    measures can leave it out.

    `sha_range` overrides the range this function would otherwise derive from
    the previous state's sha. A run that judges a *branch* — a PR gate — has no
    previous state at all, so the derived range is None and diff coverage
    reports "no commit range this run": the one measurement a PR gate exists to
    make would be unavailable exactly where it matters. The caller that already
    knows the range (`BASE..HEAD`, or a merge-base) says so, and everything
    downstream — changed lines, per-file unexercised ranges, the census — is
    measured over the change under review rather than over nothing.
    """
    now = clock.now()
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
    # The recorded key is authoritative (§0). A profile that names its
    # Project-Key — or a previous state that already carries one — wins over
    # whatever this directory happens to be called. Nothing in the harness read
    # the header until run 4 of this repository, executed from a clone named
    # `verdict-clone`, re-keyed the committed team-mode state and its INDEX to
    # a second project name (VERDICT-F-23). In team mode `.qa/` is committed
    # and travels with the repository, so any clone, CI checkout or agent
    # worktree with a different directory name would have done the same.
    recorded = project_key_for_root(qa_root)
    if recorded and recorded != key:
        key, key_source = recorded, "profile"
    else:
        prior = _read_json(Path(qa_root) / "state.json") if qa_root else None
        if isinstance(prior, dict) and prior.get("project") and prior["project"] != key:
            key, key_source = str(prior["project"]), "state"
    sha = _git(["rev-parse", "HEAD"], repo)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    prev_sha = ((previous or {}).get("last_run") or {}).get("git_sha")
    range_override, sha_range = sha_range, None
    diff_stat = None
    files_changed = lines_changed = None
    if range_override and _git(["rev-parse", "--verify", "--quiet",
                                str(range_override).split("..")[0]], repo):
        sha_range = str(range_override)
    elif prev_sha and sha and _git(["cat-file", "-t", prev_sha], repo) == "commit":
        sha_range = f"{prev_sha}..{sha}"
    if sha_range:
        diff_stat = _git(["diff", "--shortstat", sha_range], repo)
        if diff_stat:
            nums = [int(n) for n in re.findall(r"(\d+)", diff_stat)]
            files_changed = nums[0] if nums else None
            lines_changed = sum(nums[1:]) if len(nums) > 1 else None

    run_number = int((previous or {}).get("run_number") or 0) + 1
    run_type, why = "baseline", "no previous state"
    gate_label = None
    if not previous and range_override and sha_range == str(range_override):
        # A gate in a root of its own — the throwaway root a branch gate runs in. Its scope is
        # the change, not the repository: `run_type` stays the enum consumers switch on, and
        # the label says what the run was (trace 2026-10-15: every branch gate read "run 1,
        # baseline", as if the whole repository had been read).
        why = f"no previous state; a gate over {sha_range}"
        gate_label = (f"Gate over {sha_range}, in a root of its own: the change is the scope, "
                      "not a baseline of the repository")
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
    report_ids: list = []
    # A gate that writes a report file (`{report}` in its command) is read
    # from the file: exact counts, per-test durations, failures with their
    # messages, the ids. The summary-line dialects are the fallback — a
    # dialect is a guess, and vitest's and jest's counted the file line.
    reports_dir = (Path(tempfile.mkdtemp(prefix="verdict-reports-"))
                   if any("{report}" in c for _, c in gates) else None)
    for name, command in gates:
        report_path = None
        rendered = command
        if reports_dir is not None and "{report}" in command:
            report_path = reports_dir / f"{name}.report"
            rendered = command.replace("{report}", str(report_path))
        started = time.monotonic()
        proc = _run(rendered, cwd=repo, shell=True)
        duration = round(time.monotonic() - started, 2)
        output = proc.stdout + proc.stderr
        counts, dialect = _counts(output)
        report = None
        if report_path is not None:
            report, ids = read_report(report_path)
            if report.get("status") == "measured":
                counts, dialect = dict(report["counts"]), f"report/{report['format']}"
                if ids and not report_ids:
                    report_ids = ids
        not_run = cannot_start(proc.returncode, output)
        gate_results[name] = {
            "command": command,
            "exit_code": proc.returncode,
            "result": ("pass" if proc.returncode == 0
                       else "unavailable" if not_run else "fail"),
            **({"unavailable": (f"the command could not start (exit {proc.returncode}) — "
                                "the environment is missing something it needs, so nothing "
                                "this gate checks was measured; it is not a test failure")}
               if not_run else {}),
            "duration_s": duration,
            "summary": _summary_line(output),
            **({"counts": counts, "counts_dialect": dialect} if counts else
               {"counts_unparsed": "no recognised runner summary — the count-drop gate "
                                   "and the id set-diff cannot fire for this gate"}),
            **({"executed_nothing": nothing_ran} if (nothing_ran := executed_nothing(counts))
               else {}),
            **({"report": report} if report is not None else {}),
        }
    if reports_dir is not None:
        shutil.rmtree(reports_dir, ignore_errors=True)

    # Compare each gate's duration against its own history. Prior durations
    # come from runs.jsonl rows written by finalize (gate_durations, additive
    # since 0.46.0) — the first runs after an upgrade have no history and stay
    # silent, which is honest: no baseline, no claim.
    prior_rows, _ = load_runs(qa_root)
    for name, g in gate_results.items():
        priors = [r["gate_durations"][name] for r in prior_rows
                  if isinstance(r.get("gate_durations"), dict)
                  and name in r["gate_durations"]][-5:]
        slow = duration_regressed(g.get("duration_s"), priors)
        if slow:
            g["duration_regressed"] = slow

    # Characteristic signatures of model-written code that are mechanically
    # countable — hallucinated imports, placeholders, swallowed exceptions,
    # AI-attribution of the range. Leads for §4.5 judgment, never findings.
    try:
        facts_census = code_census(repo, sha_range)
    except Exception as exc:  # a census must never cost a run
        facts_census = {"scope": f"census failed: {exc}"}

    # Junk, near-certain exposures and reading leads, on every run (T-28). Tier 1
    # becomes findings in finalize, tier 2 the ledger, leads what the tester reads first.
    try:
        facts_hygiene = hygiene_census(repo, filing=hygiene_filing)
    except Exception as exc:  # a scan must never cost a run
        facts_hygiene = {"status": "unavailable", "reason": f"hygiene scan failed: {exc}"}

    facts = {
        "measured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": key,
        "project_key_source": key_source,
        "qa_root": str(qa_root),
        # finalize anchors cited lines and resolves origin commits with git,
        # and it runs from the QA root — it has to be told where the code is.
        "repo": str(repo),
        "schema_version": 1,
        "run_number": run_number,
        "run_type": run_type,
        "run_type_reason": why,
        **({"run_label": gate_label} if gate_label else {}),
        # Start the judgment from this file; do not learn its shape by reading.
        "judgment_template": str(judgment_template()),
        # One finding, one file: this is its shape, written to `findings_dir`.
        "finding_template": str(finding_template()),
        "findings_dir": str(Path(qa_root) / FINDINGS_DIR),
        "last_run": {
            "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_sha": sha, "git_branch": branch, "sha_range": sha_range,
            "diff_stat": diff_stat,
            "harness": {**_harness_identity(), **_prompt_identity(repo)},
            # A verdict is only as good as its judge, and which model signed it
            # used to live only in the operator's memory. The runner that
            # launched the session knows; it exports VERDICT_MODEL and the
            # measurement lands here — absent when nothing exported it, never
            # guessed.
            **({"model": os.environ["VERDICT_MODEL"]}
               if os.environ.get("VERDICT_MODEL") else {}),
        },
        "gates": gate_results,
        "code_census": facts_census,
        "hygiene": facts_hygiene,
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
                # The window is six hours wide; saying "minutes ago" inside it
                # put a false sentence beside the true number in the same
                # object — `age_hours: 2.01` under "minutes ago" (VERDICT-F-53).
                "meaning": f"an earlier attempt at this same commit, {_ago(age_h)} — "
                           "this run's own retry, not a lost run. Nothing is missing",
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

    ids_from_report = None
    if not test_ids_cmd and report_ids:
        # No id command, but a gate wrote a report that names every test: the
        # ledger comes from there, in the report's own shape — said so, because
        # `classname::name` is not a pytest node id and `test_one_cmd` cannot
        # run it; a project that verifies fixes still declares `test_ids_cmd`.
        ids_from_report = sorted(set(report_ids))
    if test_ids_cmd or ids_from_report:
        if ids_from_report:
            ids = ids_from_report
        else:
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
                "reason": (f"the id command could not start (exit {proc.returncode}): "
                           f"{_summary_line(proc.stdout + proc.stderr)}"
                           if cannot_start(proc.returncode, proc.stdout + proc.stderr) else
                           "the id command produced no `::` lines "
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
            added = sorted(set(ids) - set(before))
            removed = sorted(set(before) - set(ids))
            facts["test_ids"] = {
                "status": "measured",
                **({"ids_from": "report — ids shaped as the report names them, not pytest "
                                "node ids; set test_ids_cmd for the collected form"}
                   if ids_from_report else {}),
                "count": len(ids),
                # The counts come from the untruncated sets; only the lists are
                # capped, for display. The renderer used to take len() of the
                # capped list, so a mass deletion read as "−50" under a line
                # claiming set-diff accounting — the display cap had silently
                # become the ceiling of the number the gate reported. Live on
                # run 4 of this repository: "+50" where the truth was +166
                # (VERDICT-F-20).
                "added_count": len(added),
                "removed_count": len(removed),
                "added": added[:50],
                "removed": removed[:50],
                "truncated": len(added) > 50 or len(removed) > 50,
                "source": "id set-diff, not summary arithmetic",
            }
            facts["_test_ids"] = ids
            # The ids the collector saw for the first time this run: what a
            # fix's own regression test looks like, and the one signal that
            # tells a guarding test from a mentioned one.
            facts["_added_test_ids"] = added

    # The id the next NEW finding takes — one more than the highest ever minted,
    # in the state or the outcome ledger — so the agent never scans for a gap
    # and two findings can no longer share an id by accident.
    facts["next_finding_id"] = next_finding_id(key, previous, load_outcomes(qa_root))

    # Where the code the previous run cited has gone since: re-hash every
    # anchor finalize recorded, so the tester reads what moved instead of
    # everything, and "the code under an accepted risk changed" is measured.
    if previous:
        prev_findings = [f for f in (previous.get("findings") or []) if isinstance(f, dict)]
        # A hygiene finding is the scan's, re-measured below: where its line moved is
        # nothing the tester must read, and nothing that should buy a model run.
        drift = evidence_drift(
            repo,
            [f for f in prev_findings if is_open(f) and not is_hygiene(f)],
            [f for f in prev_findings if norm_status(f.get("status")) == "accepted"],
            list(zip(previous.get("verified_intact") or [],
                     previous.get("verified_intact_anchors") or [])))
        facts["evidence_drift"] = drift or {
            "status": "unavailable",
            "reason": "the previous state carries no evidence anchors — it was written by a "
                      "verdict-finalize older than 0.83.0; this run anchors, the next measures"}

    verification, vnotes = verify_findings(repo, previous, test_one_cmd, prev_sha,
                                          known_ids=facts.get("_test_ids"),
                                          added_ids=facts.get("_added_test_ids"))
    if verification:
        facts["verification"] = verification
    if vnotes:
        facts["verification_notes"] = vnotes
    prev_findings = [f for f in ((previous or {}).get("findings") or []) if isinstance(f, dict)]
    # The same measurement for the command a finding carries (0.91.0): its `repro` run on a
    # fresh worktree at HEAD and at the previous commit. A reproduction that stops between
    # the two is a fix the harness watched; one that persists holds the finding open against
    # any resolution. Silence changes nothing; measurement does.
    replays, rnotes = measure_findings(repo, [f for f in prev_findings if is_open(f)], prev_sha,
                                       qa_root, str(facts.get("measured_at") or ""))
    _put(facts, replay=replays, replay_notes=rnotes)
    coverage, reading_map, exercised, gaps = _coverage_with_gaps(
        repo, sha_range, coverage_suite_cmd, prev_findings, assertion_gaps)
    _put(facts, assertion_gaps=gaps)
    facts["coverage"] = coverage
    if reading_map:
        facts["reading_map"] = reading_map
    if exercised:
        facts["exercised_by"] = exercised
    # What a person decided since the last run, and what is still waiting for
    # one — read here so a decision is read, never asked again.
    asked = questions.facts_view(qa_root, now.date())
    if asked:
        facts["questions"] = asked
    return facts


# ── finalize ──────────────────────────────────────────────────────────────


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
    ap.add_argument("--test-one-cmd", default=None,
                    help="command running one test, `{id}` standing for the node id — "
                         "re-runs each open finding's cited test at the previous commit "
                         "and at HEAD to verify fixes (default: the profile's test_one_cmd)")
    ap.add_argument("--coverage-suite-cmd", default=None,
                    help="command running the suite under coverage.py (e.g. `.venv/bin/python "
                         "-m coverage run -m pytest`) — measures which changed lines any test "
                         "executed (default: the profile's coverage_suite_cmd)")
    ap.add_argument("--out", type=Path, default=None, help="also write facts.json here")
    ap.add_argument("--range", dest="sha_range", default=os.environ.get("VERDICT_RANGE") or None,
                    metavar="BASE..HEAD",
                    help="the change under review — a PR gate's range (default: $VERDICT_RANGE, "
                         "which `verdict-run --range` exports; else the range since the previous "
                         "run). Recorded as last_run.sha_range")
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
    # Before the root is created, and before the marker, the ledger or the facts
    # are written: a root among the code, or a link in it, is a write somewhere
    # else (state.misplaced_root, state.planted_links).
    refusal = root_refusal(qa_root, "verdict-facts", repo)
    if refusal:
        print(refusal, file=sys.stderr)
        return 2
    qa_root.mkdir(parents=True, exist_ok=True)
    if args.out is not None:
        # `--out` is the caller's path, and the caller may be the tester:
        # `verdict-facts --out README.md` is a write into the code under test by a
        # command the Bash guard has no reason to refuse. Anywhere outside the
        # repository is the caller's business; inside it, only the QA root.
        # Read where the path lands, not how it is spelled: a link is followed.
        out_real, root_real = args.out.expanduser().resolve(), qa_root.resolve()
        in_repo = out_real == repo or repo in out_real.parents
        in_root = out_real == root_real or root_real in out_real.parents
        if in_repo and not in_root:
            print(f"verdict-facts: refusing --out {args.out} — it lands inside the repository "
                  "under test and outside the QA root; the harness does not write the checkout",
                  file=sys.stderr)
            return 2

    # The profile already records the project's real commands; retyping them
    # into flags on every run is a transcription step, and a transcription step
    # is a place for the model to be confidently wrong. Explicit --gate still
    # wins — a caller narrowing a run should not have to edit the profile.
    profile_notes, profile_source, declared_authorship, filing = [], None, None, "on"
    config: dict = {}
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
        filing = hygiene_filing_from(config, profile_notes)
        if args.test_ids_cmd is None and config.get("test_ids_cmd"):
            args.test_ids_cmd = config["test_ids_cmd"]
            profile_notes.append("test_ids_cmd taken from the profile")
        if args.test_one_cmd is None and config.get("test_one_cmd"):
            args.test_one_cmd = config["test_one_cmd"]
            profile_notes.append("test_one_cmd taken from the profile")
        if args.coverage_suite_cmd is None and config.get("coverage_suite_cmd"):
            args.coverage_suite_cmd = config["coverage_suite_cmd"]
            profile_notes.append("coverage_suite_cmd taken from the profile")
        overridden = [n for n, _ in from_profile if n in named]
        if overridden:
            profile_notes.append(
                "gates overridden on the command line: " + ", ".join(sorted(overridden)))

    # Reuse, not resume. A model's judgment cannot be continued from the
    # middle, but the gates it was about to judge can be spared a second run —
    # and only while they still describe this commit and are minutes old.
    # verdict-run measures before the tester starts (0.91.1) and names the commit it measured:
    # the tester's own first call then adopts those facts instead of measuring for a second time
    # inside a Bash call that ends at 10 minutes — where the assertion-gap census lost half its
    # budget on 2026-10-17 and a known defect's survivor went unmeasured.
    premeasured = os.environ.get(PREMEASURED_ENV, "")
    existing = _read_json(qa_root / "facts.json") if (args.reuse_if_fresh or premeasured) else None
    if existing:
        head = _git(["rev-parse", "HEAD"], repo)
        try:
            age = (clock.now() - datetime.strptime(
                existing.get("measured_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)).total_seconds() / 60
        except (ValueError, TypeError):
            age = 1e9
        same_head = (existing.get("last_run") or {}).get("git_sha") == head
        same_range = (existing.get("last_run") or {}).get("sha_range") == (args.sha_range or None) \
            or not args.sha_range
        adopt = premeasured and premeasured == head and age <= PREMEASURED_MAX_AGE_MIN and same_range
        if same_head and (adopt or (args.reuse_if_fresh and age <= args.reuse_max_age_min)):
            existing["reused"] = {"measured_at": existing.get("measured_at"),
                                  "age_minutes": round(age, 1),
                                  "why": ("measured by verdict-run before the tester started"
                                          if adopt else "same HEAD, within the freshness window")
                                         + "; gates were not re-run"}
            if adopt:
                _restake_marker(qa_root)
            print(json.dumps(existing, indent=2))
            print(f"verdict-facts: reusing facts measured {round(age, 1)} min ago at this HEAD. "
                  f"Judgment template → {judgment_template()}; one finding = one file, "
                  f"{qa_root / FINDINGS_DIR}/<ID>.json; next id {existing.get('next_finding_id')}",
                  file=sys.stderr)
            return 0

    # Order matters: read whatever the last run left behind, *then* stake this
    # run's claim. The marker is written before the gates so a run killed
    # mid-suite still leaves a trace.
    abandoned = _read_json(qa_root / "run-in-progress.json")
    head = _git(["rev-parse", "HEAD"], repo)
    (qa_root / "run-in-progress.json").write_text(json.dumps({
        "started_utc": clock.stamp(),
        "repo": str(repo),
        # The commit is what separates "my own retry" from "last night died".
        "git_sha": head,
        # Which session staked this claim, when the CLI says. It is what lets the
        # stop hook tell "the run this agent started and never finalized" from a
        # marker somebody else's night left behind, and what lets finalize find this
        # run's own transcript. Absent outside Claude Code; nothing depends on it.
        **_session_identity()}, indent=2) + "\n",
        encoding="utf-8")
    # Last run's finding files move aside before this run writes its own —
    # unless the marker says this is the same run trying again, in which case
    # the files are this attempt's and stay. Moved, never deleted.
    started = _parse_marker_time((abandoned or {}).get("started_utc")) if abandoned else None
    retry = bool(abandoned) and abandoned.get("git_sha") == head and started is not None \
        and (clock.now() - started).total_seconds() / 3600 <= RETRY_WINDOW_HOURS
    archived = archive_findings(qa_root, keep=retry)
    gaps_on, gaps_budget = assertion_gaps_from(config, profile_notes)
    facts = collect(repo, qa_root, gates, args.test_ids_cmd, abandoned=abandoned,
                    test_one_cmd=args.test_one_cmd, coverage_suite_cmd=args.coverage_suite_cmd,
                    sha_range=args.sha_range, hygiene_filing=filing,
                    assertion_gaps=({"test_one_cmd": args.test_one_cmd, "budget_s": gaps_budget,
                                     "globs": risk_paths_from(config, [])} if gaps_on else None))
    if archived:
        facts["findings_archived"] = archived
    # The scope the profile names (0.92.0): the files under the paths its risk-focus section
    # mentions, or defining the functions it names. The local tier reads these after the census
    # survivors, where it used to read the largest files on a project with no coverage map.
    try:
        profile_text = (qa_root / "profile.md").read_text(encoding="utf-8")
    except OSError:
        profile_text = ""
    if focus := risk_focus(repo, profile_text, is_test_file):
        facts["risk_focus"] = focus
    # Where to read first (0.91.0): the changed code no test executes, risk paths first — the
    # risk-focus files count as risk paths when the profile sets no `risk_paths` (0.92.0).
    head_range = (facts.get("last_run") or {}).get("sha_range")
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    ranked = read_first(repo, cov, facts.get("reading_map"),
                        changed=(_changed_lines(repo, head_range)
                                 if head_range and cov.get("status") != "measured" else None),
                        globs=risk_paths_from(config, profile_notes), is_test=is_test_file,
                        gaps=facts.get("assertion_gaps"), focus=(focus or {}).get("files") or ())
    if ranked:
        facts["read_first"] = ranked
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
    facts.pop("_added_test_ids", None)  # internal, like _test_ids: never written
    ids = facts.pop("_test_ids", None)
    if ids is not None:
        (qa_root / "test-ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    split_hygiene(facts, qa_root)
    text = json.dumps(facts, indent=2)
    # The QA root's copy is the one the gate, the scorer and the stop hook read as "facts
    # were measured for this run"; `--out` is a second copy, as its help has always said.
    # It was written *instead*: a run that asked for a copy lost the signal and read as
    # hand-written state (exit 6). Measured 2026-09-17 — a Sonnet run that scored 9 of 9 on
    # substance was zeroed for using a documented flag.
    (qa_root / "facts.json").write_text(text + "\n", encoding="utf-8")
    if args.out and args.out.expanduser().resolve() != (qa_root / "facts.json").resolve():
        args.out.expanduser().parent.mkdir(parents=True, exist_ok=True)
        args.out.expanduser().write_text(text + "\n", encoding="utf-8")
    print(text)
    print(f"verdict-facts: judgment template → {judgment_template()} — copy it, replace every "
          f"value, keep every key. One finding = one file, {qa_root / FINDINGS_DIR}/<ID>.json, "
          f"the shape of {finding_template()}; next id {facts.get('next_finding_id')}",
          file=sys.stderr)
    return 0


_REPORT_RUN = re.compile(r"·\s*run\s+(\d+)\b")


def _report_belongs_to(path: Path, run_number) -> bool:
    """True when the report on disk is this run's own — its header names the
    run number — so a retry reuses the file an earlier attempt at the same run
    left. A refusal takes its report back now (finalize_main); a finalize killed
    after rendering still leaves one, as every refusal used to."""
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:200]
    except OSError:
        return False
    m = _REPORT_RUN.search(head)
    return bool(m) and m.group(1) == str(run_number)


_TOPIC_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe_topic(topic, fallback: str) -> str:
    """A report topic is a filename fragment, never a path.

    `judgment.topic` went into `reports/<date>-<topic>.md` as written, so a
    topic of `../../x` named a file outside `reports/` and the `mkdir` below
    built the way there (audit 2026-10-02, H-D-1). One character class, runs
    of anything else collapsed to one dash, nothing left that a path could
    use."""
    text = _TOPIC_SAFE.sub("-", str(topic or ""))
    text = re.sub(r"-{2,}", "-", text).strip("-.")
    return text or fallback


def _report_name(qa_root: Path, stamp: str, topic: str, run_number) -> str:
    """`reports/<date>-<topic>.md`, unless an earlier run already wrote that
    file. A second delta on the same day used to overwrite the first one's
    report — the artifact of record, gone without a word — found by the
    acceptance run for 0.83.0 on its own history (boltons run 3 over run 2).
    Another run's file is left alone and this one gets `-run<n>` appended; a
    file this run itself wrote is reused."""
    base = f"reports/{stamp}-{_safe_topic(topic, 'run')}"
    for rel in (f"{base}.md", f"{base}-run{run_number}.md"):
        path = qa_root / rel
        if not path.exists() or _report_belongs_to(path, run_number):
            return rel
    n = 2
    while (qa_root / f"{base}-run{run_number}-{n}.md").exists():
        n += 1
    return f"{base}-run{run_number}-{n}.md"


# What a re-report by id carries from the previous state: the finding as its
# author last wrote it. Never the computed fields, never a fix claim — a
# resolution by id is "gone, not verified" unless the harness measures it.
_RE_REPORT_FIELDS = ("id", "title", "severity", "priority", "failure_classification",
                     "confidence", "evidence", "verification_test", "root_cause")


def _lift_narratives(judgment: dict) -> None:
    """A finding file's `narrative` becomes `prose.findings[id]` — the place
    the renderer has always read per-finding prose from."""
    for f in judgment.get("findings") or []:
        if not isinstance(f, dict) or "narrative" not in f:
            continue
        text = f.pop("narrative")
        if isinstance(text, str) and text.strip():
            prose = judgment.get("prose")
            if not isinstance(prose, dict):
                prose = judgment["prose"] = {}
            if not isinstance(prose.get("findings"), dict):
                prose["findings"] = {}
            prose["findings"].setdefault(str(f.get("id")), text)


def _re_report(judgment: dict, previous: dict | None, facts: dict) -> list[str]:
    """Expand `still_open` and `resolved` into findings copied from the
    previous state → problems.

    The verb is cheap on purpose — run 14 re-typed eighteen findings to say
    "still there" — and the harness keeps it honest: an id whose cited code
    changed or vanished since the evidence was written (`evidence_drift`, T-1)
    is refused, because the evidence no longer says what the finding says.

    A hygiene finding named by either verb expands to nothing: the scan re-measures
    it every run (reconcile), and the tester's word neither keeps it open nor
    closes it. The local tier and the sweep name every open id in `still_open`,
    and the copy — which carries no `source` — would stand beside the harness's
    own finding under the same id."""
    prev_by_id = {str(f.get("id")): f for f in ((previous or {}).get("findings") or [])
                  if isinstance(f, dict) and f.get("id")}
    drift = ((facts.get("evidence_drift") or {}).get("findings") or {}) \
        if isinstance(facts.get("evidence_drift"), dict) else {}
    bad = []
    for verb, status in (("still_open", "open"), ("resolved", "resolved")):
        for fid in judgment.get(verb) or []:
            prior = prev_by_id.get(str(fid))
            if prior is None:
                continue            # validate_judgment has already refused it
            if is_hygiene(prior):
                continue            # the harness's own: re-measured, never carried by word
            d = drift.get(str(fid)) if verb == "still_open" else None
            if isinstance(d, dict) and d.get("drift") in ("changed", "missing"):
                refs = ", ".join(f"{r.get('ref')} ({r.get('status')})" for r in d.get("refs") or []
                                 if r.get("status") in ("changed", "missing"))
                bad.append(f"still_open names {fid}, but the code it cites {d['drift']} since "
                           f"the evidence was written ({refs}) — write "
                           f"{FINDINGS_DIR}/{fid}.json with fresh evidence, or resolve it")
                continue
            entry = {k: prior[k] for k in _RE_REPORT_FIELDS if k in prior}
            entry["status"] = status
            entry["re_reported"] = verb
            judgment["findings"].append(entry)
    return bad


USAGE_FILE = "usage.jsonl"


def _judged_locally(facts: dict) -> bool:
    """Whether `verdict-local` judged this run — a model behind a gateway, not a Claude
    session. The engine signs `last_run.engine` before it finalizes and exports
    `VERDICT_MODEL=local:<alias>`; either is enough."""
    engine = str(((facts or {}).get("last_run") or {}).get("engine") or "")
    return engine == "verdict-local" or str(os.environ.get("VERDICT_MODEL") or "").startswith("local:")


def _measure_bill(qa_root: Path, facts: dict) -> dict | None:
    """What this run has spent, read from the session's own transcript → a record, or
    None when it cannot be known. Read before the state is composed, because the one
    thing in it that belongs in the state is *which model answered*: a run spawned as
    a subagent inherits its session's model, no operator exported `VERDICT_MODEL`, and
    for three weeks the author's own history recorded no model on most rows while the
    most expensive one on the account did the work."""
    # A local run's judge is not a Claude session. The session that launched it — an
    # orchestrator's desktop session, an eval — is somebody else's bill, and its models are
    # not the tester's: found 2026-10-14, when the suite was run from a desktop session that
    # had answered on two models, the one-model rule read that session's transcript and
    # blocked the finalize tests. A local gate launched from such a session would have been
    # blocked the same way. The engine's own calls and tokens are in `last_run.local`.
    if _judged_locally(facts):
        return None
    marker = _read_json(qa_root / "run-in-progress.json") or {}
    session = marker.get("session_id") or os.environ.get(SESSION_ENV)
    if not session:
        return None
    return run_usage(session, since=marker.get("started_utc"),
                     fingerprint=facts.get("measured_at"))


_MINOR_OR_WORSE = ("Blocker", "Critical", "Major", "Minor")


def change_lines(repo, sha_range):
    """`(path, line) -> bool`: whether `git blame` at HEAD attributes the line to a commit
    in `sha_range` — the change under review, told from the tree. None when the range is
    unknown or names no commit, because then nothing can be told apart."""
    if not repo or not sha_range:
        return None
    listed = _git(["rev-list", str(sha_range)], repo)
    commits = set((listed or "").split())
    if not commits:
        return None
    owners: dict = {}

    def in_change(path, line) -> bool:
        key = str(path)
        if key not in owners:
            out = _git(["blame", "-w", "-M", "-C", "--line-porcelain", "HEAD", "--", key], repo)
            lines = {}
            for row in (out or "").splitlines():
                parts = row.split(" ")
                if len(parts) >= 3 and len(parts[0]) == 40 and parts[2].isdigit():
                    lines[int(parts[2])] = parts[0]
            owners[key] = lines
        try:
            return owners[key].get(int(line)) in commits
        except (TypeError, ValueError):
            return False
    return in_change


def gate_policy(state: dict, bill: dict | None, risk_class: str | None = None,
                in_change=None, judgment: dict | None = None,
                contract_rule: bool = True) -> list[str]:
    """The verdict rules a judgment cannot talk its way past → what each did, for the run.

    1. **One model.** A tester whose own transcript answers on more than one model did not
       run on the model it was launched on, and its verdict is nobody's: `blocked`, with the
       models named. On 2026-10-12 the provider's safety filter stopped two responses of a
       security gate, the CLI carried on with another model and said nothing, and only the
       eval's watcher noticed.
    2. **A proven defect the change made blocks a money or security gate.** Under
       `risk_class: money` or `security`, an open, tester-filed finding that is `proven`, a
       `REAL_DEFECT`, Minor or worse, *and* cites a line `git blame` attributes to the gate's
       range (`in_change`) makes the verdict `fail` and joins the release blockers. Measured
       on the 2026-10 money key: the tester located the right defect, proved it and returned
       `pass with risks` five times in nineteen, and three times in six on fresh positives.
       Unscoped, the rule also blocked three of eight clean changes for defects that were
       already there; scoped to the change it is what Phase 2b measures. No range, no rule:
       a defect the change made cannot be told from one it found.
        3. **A fix that fails the project's own green tests is a contract dispute, not a
       blocker.** A finding whose counterfactual broke tests that pass at HEAD
       (`fix_breaks_tests` > 0) is marked `contract_dispute`, capped at Major, taken out of
       the release blockers, and a question is parked for the maintainer: the tests are
       evidence of intent, and a documented-versus-tested disagreement is theirs to settle.
       If the judgment's `fail` rested on it alone, the verdict becomes `pass with risks`.
       Inside a money or security gate's own range the money rule keeps precedence: a defect
       the change made is judged as the change, not as the project's contract. On
       2026-10-17 django-oscar's baseline said `fail` on a Critical that 22 green tests
       assert the other way and the tracker had tuned on purpose; `profile.md` turns the rule
       off with `contract_rule: off`.
    """
    models = {str(m): int(n) for m, n in ((bill or {}).get("models") or {}).items() if m}
    if len(models) > 1:
        reason = ("the tester answered on more than one model ("
                  + ", ".join(f"{m} ×{n}" for m, n in sorted(models.items())) + ")")
        state["verdict_rule"] = {"rule": "one model", "was": state.get("verdict"),
                                 "reason": reason}
        state["verdict"] = "blocked"
        return [f"verdict blocked: {reason} — no verdict is signed by a model nobody chose"]
    notes: list[str] = []
    if contract_rule:
        notes.extend(_contract_dispute(state, in_change, judgment))
    if risk_class not in RISK_CLASSES or state.get("verdict") not in ("pass", "pass with risks"):
        return notes
    if in_change is None:
        return notes + [f"risk_class {risk_class}: no gate range, so a defect the change made "
                        "cannot be told from one it found — the judgment's verdict stands"]
    proven = []
    for f in state.get("findings") or []:
        if not (is_open(f) and not is_hygiene(f)
                and str(f.get("confidence") or "") == "proven"
                and str(f.get("failure_classification") or "") == "REAL_DEFECT"
                and str(f.get("severity") or "") in _MINOR_OR_WORSE):
            continue
        if any(isinstance(a, dict) and a.get("path") and a.get("line")
               and in_change(a["path"], a["line"]) for a in f.get("anchors") or []):
            proven.append(f)
    if not proven:
        return notes
    was = state.get("verdict")
    blockers = list(state.get("release_blockers") or [])
    named = " ".join(str(b) for b in blockers)
    for f in proven:
        fid = str(f.get("id"))
        if fid not in named:
            blockers.append(f"{fid}: {f.get('title') or ''} ({f.get('severity')}, proven, in "
                            f"the change; risk_class {risk_class}: a proven defect blocks)")
    state["release_blockers"] = blockers
    state["verdict"] = "fail"
    state["verdict_rule"] = {"rule": f"risk_class {risk_class}: a proven defect the change made "
                                     "blocks",
                             "was": was, "raised_by": [str(f.get("id")) for f in proven]}
    return notes + [f"verdict raised from '{was}' to 'fail': risk_class {risk_class}, and "
                    f"{', '.join(str(f.get('id')) for f in proven)} proven in the change"]


_SEVERITY_CAP = "Major"


def _contract_dispute(state: dict, in_change, judgment: dict | None) -> list[str]:
    """Rule 3 of `gate_policy`: the findings whose fix fails the project's own green tests."""
    capped = []
    for f in state.get("findings") or []:
        n = f.get("fix_breaks_tests")
        if not (is_open(f) and not is_hygiene(f) and isinstance(n, int)
                and not isinstance(n, bool) and n > 0):
            continue
        if in_change is not None and any(
                isinstance(a, dict) and a.get("path") and a.get("line")
                and in_change(a["path"], a["line"]) for a in f.get("anchors") or []):
            continue            # the change's own defect: the money rule judges it
        f["contract_dispute"] = True
        if str(f.get("severity") or "") in ("Blocker", "Critical"):
            f["severity_was"] = f["severity"]
            f["severity"] = _SEVERITY_CAP
        capped.append(f)
    if not capped:
        return []
    ids = [str(f.get("id")) for f in capped]
    blockers = [b for b in (state.get("release_blockers") or [])
                if not any(fid in str(b) for fid in ids)]
    state["release_blockers"] = blockers
    if judgment is not None:
        for f in capped:
            judgment.setdefault("questions", []).append({
                "question": (f"{f['fix_breaks_tests']} test(s) that pass at HEAD assert the "
                             f"behaviour {f.get('id')} calls a defect, and the fix would fail "
                             f"them. Which is the contract — the tests, or what {f.get('id')} "
                             "expects?"),
                "finding": str(f.get("id")),
                "context": (f"{f.get('id')} is filed as a contract dispute: capped at "
                            f"{_SEVERITY_CAP}, not a release blocker on its own. "
                            "Verdict does not settle a documented-versus-tested disagreement."),
                "options": ["The tests are the contract: close the finding as intended behaviour",
                            "The documented behaviour is the contract: fix the code and the tests",
                            "Neither yet: decide the contract first"]})
    was = state.get("verdict")
    still = [f for f in state.get("findings") or []
             if is_open(f) and not is_hygiene(f)
             and str(f.get("severity") or "") in ("Blocker", "Critical")]
    if was == "fail" and not blockers and not still:
        state["verdict"] = "pass with risks"
        state["verdict_rule"] = {"rule": "contract dispute", "was": was, "capped": ids}
        return [f"verdict lowered from 'fail' to 'pass with risks': {', '.join(ids)} filed as a "
                "contract dispute (the fix fails tests that pass at HEAD), and nothing else blocks"]
    return [f"contract dispute: {', '.join(ids)} capped at {_SEVERITY_CAP} and taken out of the "
            f"blockers; the verdict stands at {was!r}"]


def _gateway_host(value) -> str | None:
    """The hostname in a gateway's base URL → or None. Never the URL itself.

    The local tier wrote `urlparse(base_url).hostname or base_url`, so a URL that parses
    to no hostname — one written without a scheme — went in whole, with whatever userinfo,
    path or query it carried. A bare hostname is read as one: that is what a facts.json
    written by 0.90.10 or earlier holds in `last_run.local.host`."""
    text = value.strip() if isinstance(value, str) else ""
    if not text:
        return None
    try:
        return urllib.parse.urlsplit(text if "//" in text else "//" + text).hostname or None
    except ValueError:
        return None


def _record_bill(qa_root: Path, state: dict, bill: dict | None,
                 gateway_host: str | None = None) -> None:
    """One line per run in `usage.jsonl`, beside the state and outside the signed row.

    Outside, because a bill is telemetry: signing it would make every state written
    before this file existed re-derive to a different row, the reason `gate_durations`
    is kept out of the chain body. A run with no readable transcript still gets its
    line — `usage: null` and why — so an absent bill is not mistaken for a free run.
    `gateway_host` is the host a local run called, which the state no longer carries
    (`finalize_main`): the bill is the paying machine's own telemetry, not the record a
    team commits, so it may name it.
    Never raises, and never changes the exit code: the state is already on disk."""
    try:
        last = state.get("last_run") or {}
        row = {"run_number": state.get("run_number"), "run_type": state.get("run_type"),
               "timestamp_utc": last.get("timestamp_utc"), "model": last.get("model")}
        if os.environ.get(ENTRYPOINT_ENV):
            row["entrypoint"] = os.environ[ENTRYPOINT_ENV]
        if os.environ.get("CLAUDE_EFFORT"):
            row["effort"] = os.environ["CLAUDE_EFFORT"]
        if isinstance(last.get("escalation"), dict):
            esc = last["escalation"]
            row["escalation"] = {k: esc.get(k) for k in ("leads", "local_model", "local_calls",
                                                          "functions_read", "budget_usd")}
        if state.get("run_type") == "sweep":
            row["usage"] = {"requests": 0, **{k: 0 for k in USAGE_FIELDS}}
            row["note"] = "model-free sweep: no model was called"
        elif last.get("engine"):
            # A second engine answered, so the Claude bill is a measured zero
            # rather than an unknown — and the engine's own counters go in the
            # same row, because "this night cost nothing" is only credible
            # beside the number of calls it took to cost nothing.
            row["engine"] = last["engine"]
            row["usage"] = {"requests": 0, **{k: 0 for k in USAGE_FIELDS}}
            row["local"] = {**(last.get("local") or {}),
                            **({"host": gateway_host} if gateway_host else {})}
            row["note"] = (f"judged by {last['engine']}: no Claude request was made; the "
                           "`local` object carries that engine's own calls and tokens")
        elif bill:
            row["usage"] = bill
            row["note"] = ("measured up to verdict-finalize; the closing handoff that "
                           "follows is not in it")
        else:
            row["usage"] = None
            row["note"] = ("no transcript could be read for this run — outside Claude Code, "
                           "another machine, or a cleaned home. Unknown, not zero")
        with (qa_root / USAGE_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    except Exception as exc:        # noqa: BLE001 — see the docstring
        print(f"verdict-finalize: the run's bill was not recorded ({exc}); the state is "
              "written and valid", file=sys.stderr)


def finalize_main(argv=None, *, gateway: str | None = None) -> int:
    """`gateway` is the base URL a local run called, handed in by `verdict-local` so
    that it reaches the bill and nothing else; the command line has no such flag."""
    ap = argparse.ArgumentParser(
        prog="verdict-finalize",
        description="Merge measured facts with the agent's judgment into state.json.")
    ap.add_argument("--qa-root", required=True)
    ap.add_argument("--facts", type=Path, default=None, help="default: <qa-root>/facts.json")
    ap.add_argument("--judgment", type=Path, required=True)
    ap.add_argument("--sweep", action="store_true",
                    help="a model-free sweep (verdict-run --skip-unless-drift): run_type becomes "
                         "'sweep' and no model signs the run — the judgment carries every open "
                         "finding by id and the previous verdict, because nothing it rested on moved")
    args = ap.parse_args(argv)

    qa_root = Path(args.qa_root).expanduser().resolve()
    refusal = root_refusal(qa_root, "verdict-finalize")
    if refusal:
        print(refusal, file=sys.stderr)
        return 1
    facts = _read_json(args.facts or (qa_root / "facts.json"))
    judgment = _read_json(args.judgment)
    if args.sweep and isinstance(facts, dict):
        facts["run_type"] = "sweep"
        facts["run_type_reason"] = ("model-free sweep: HEAD moved, nothing any finding cites "
                                    "changed, the gates are green — no agent ran")
        facts.setdefault("last_run", {})["model"] = "none"
    if facts is None:
        print("verdict-finalize: facts.json missing or unreadable — run verdict-facts first",
              file=sys.stderr)
        return 2
    if judgment is None:
        print(f"verdict-finalize: {args.judgment} missing or unreadable", file=sys.stderr)
        return 2
    # The same question once more, now that the facts say which repository this is:
    # inside it, only its own `.qa/`, wherever the solo home is said to be.
    among = misplaced_root(qa_root, facts.get("repo")) if isinstance(facts, dict) else None
    if among:
        print(f"verdict-finalize: refusing the QA root — {among}", file=sys.stderr)
        return 1

    previous = _read_json(qa_root / "state.json")

    # The bill, and with it the model that actually answered — measured while the run
    # marker still says when this run began. An operator's own label wins: `opus` from
    # `verdict-run --model` is what they chose to call it, and it is already in the facts.
    bill = None if args.sweep else _measure_bill(qa_root, facts)
    if bill and bill.get("model") and not (facts.get("last_run") or {}).get("model"):
        facts.setdefault("last_run", {})["model"] = bill["model"]

    # Findings as files: one `findings/<ID>.json` per finding, written when it
    # was proven; assembled here, oldest first. The judgment may still carry
    # `findings[]` itself — but not both, and never silently merged.
    filed, file_problems = load_filed(qa_root)
    if file_problems:
        print(f"verdict-finalize: {len(file_problems)} finding file(s) cannot be read — fix "
              "the file, not the check:\n  " + "\n  ".join(file_problems), file=sys.stderr)
        return 1
    inline = judgment.get("findings") or []
    if filed and inline:
        print(f"verdict-finalize: findings are in {FINDINGS_DIR}/ ({len(filed)} files) or in "
              f"{args.judgment} ({len(inline)} entries), never both — remove one set",
              file=sys.stderr)
        return 1
    sources = {}
    if filed:
        judgment["findings"] = []
        for f in filed:
            g = dict(f)
            sources[str(g.get("id"))] = {"file": g.pop("_file"), "filed_at": g.pop("_filed_at")}
            judgment["findings"].append(g)
    _lift_narratives(judgment)

    # Checked here, where the author of judgment.json still stands. Validating
    # only the merged state stops a bad state reaching disk but explains it in
    # the vocabulary of a structure the agent did not write — a reworded
    # evidence line used to surface as `repeats id`, which says nothing about
    # what to change.
    author_problems = validate_judgment(judgment, previous, known_tests(qa_root))
    if author_problems:
        print(f"verdict-finalize: {args.judgment} has {len(author_problems)} problem(s) "
              "— fix the judgment, not the check:\n  " + "\n  ".join(author_problems),
              file=sys.stderr)
        return 1
    # Asked, not refused: a class conflict the record already held between two findings this
    # run only carried. Folded by text in the questions ledger, so it is asked once, not nightly.
    for conflict in inherited_conflicts(judgment, (previous or {}).get("findings") or []):
        fid = conflict.split(" ", 1)[0]
        judgment.setdefault("questions", []).append({
            "question": ("Two findings claim one site, and the record already held it before this "
                         f"run: {conflict}"),
            "finding": fid})
    verb_problems = _re_report(judgment, previous, facts)
    if verb_problems:
        print(f"verdict-finalize: {len(verb_problems)} problem(s) with the ids you carried — "
              "fix the judgment, not the check:\n  " + "\n  ".join(verb_problems),
              file=sys.stderr)
        return 1
    for f in judgment["findings"]:
        src = sources.get(str(f.get("id")))
        if src:
            f["filed_at"] = src["filed_at"]

    # The gateway a local run called is not the record's business. merge() copies
    # `last_run` into the state whole, the report's Judge line read it from there, and in
    # team mode both are committed with the code — so every local run there committed the
    # gateway's network address (found 2026-10-15). Its host goes to the bill alone:
    # handed in by `verdict-local`, or taken out of a facts.json written by 0.90.10 or
    # earlier, which kept it in `last_run.local`.
    local = (facts.get("last_run") or {}).get("local")
    if isinstance(local, dict) and "host" in local:
        stray = local.pop("host")
        gateway = gateway or stray
    gateway_host = _gateway_host(gateway)

    state = merge(facts, judgment, previous, ledger=load_outcomes(qa_root),
                  accepted=load_accepted(qa_root), qa_root=qa_root)
    state.pop("verdict_rule", None)              # this run's rule or none, never the last one's
    # An escalation run says, in the harness's voice, what its tester was handed and that it read
    # nothing else (0.92.0): a short run must not read like a full one in the record.
    escalation = (state.get("last_run") or {}).get("escalation")
    if isinstance(escalation, dict):
        line = escalation_not_tested(escalation)
        if line not in state.setdefault("not_tested", []):
            state["not_tested"].append(line)
    try:
        profile_config, profile_notes = load_profile(qa_root)
    except ProfileError as exc:
        profile_config, profile_notes = {}, [f"profile not read for risk_class: {exc}"]
    risk_class = risk_class_from(profile_config, profile_notes)
    in_change = None
    if risk_class:
        repo_dir = facts.get("repo")
        in_change = change_lines(Path(repo_dir) if repo_dir else None,
                                 (facts.get("last_run") or {}).get("sha_range"))
    for note in profile_notes + gate_policy(state, bill, risk_class, in_change, judgment=judgment,
                                            contract_rule=contract_rule_from(profile_config,
                                                                             profile_notes)):
        if note.startswith(("verdict ", "risk_class", "profile not read", "contract dispute")):
            print(f"verdict-finalize: {note}", file=sys.stderr)
    # A finding filed this run with a `repro` is run on a fresh worktree at HEAD before
    # anything is written (0.91.0): `proven` with a reproduction that fails on a tree the
    # tester never touched is not proven, and the run is refused with the check that failed.
    # Findings the previous record already carried were measured by verdict-facts.
    repro_problems = _replay_fresh_findings(state, facts, qa_root)
    if repro_problems:
        print(f"verdict-finalize: {len(repro_problems)} finding(s) claim `proven` on a repro that "
              "did not reproduce on a fresh worktree at HEAD - fix the repro, or file the "
              "finding as `probable`:\n  " + "\n  ".join(repro_problems), file=sys.stderr)
        return 2
    # An old finding with no repro gets the one verdict-backfill drafted, when that draft reproduced
    # at HEAD on a fresh checkout (0.92.0). Marked as model-written, so every later replay runs it
    # in the sandbox; after the check above, so this run is never refused over a draft it did not file.
    if adopted := adopt_backfill(state.get("findings"), load_backfill(qa_root)):
        print(f"verdict-finalize: {len(adopted)} open finding(s) now carry a model-written repro from "
              f"verdict-backfill ({', '.join(adopted)}); later runs replay it in the sandbox",
              file=sys.stderr)
    # The census's survivors are measured facts about the suite (0.91.1): a line its tests run
    # and do not check, and the place a defect hides behind a green suite. A run
    # that turned the census on accounts for each survivor function — a finding cites it, or
    # not_tested names it — and under repro_rule: on it is refused until it does.
    # Both refusals below bind the agent's run only. The local engine proves by counterfactual,
    # never writes a repro, and runs unattended: a rule it cannot satisfy would cost a night's
    # state, not improve a judgment. A model-free sweep is no one's run at all: it carries the
    # record forward because nothing it rested on moved.
    strict = repro_rule_from(profile_config, profile_notes) and facts.get("run_type") != "sweep" and \
        str((facts.get("last_run") or {}).get("engine") or "") != "verdict-local"
    gap_acc = survivor_accounting(facts, state)
    if gap_acc and gap_acc["unaccounted"]:
        shown = ", ".join(gap_acc["unaccounted"][:5]) + (" ..." if len(gap_acc["unaccounted"]) > 5 else "")
        if strict:
            print(f"verdict-finalize: {len(gap_acc['unaccounted'])} assertion-gap survivor function(s) "
                  f"are neither cited by a finding nor named in not_tested: {shown} - read them, or "
                  "name each in not_tested as path::function with why", file=sys.stderr)
            return 2
        print(f"verdict-finalize: {len(gap_acc['unaccounted'])} assertion-gap survivor function(s) "
              f"unaccounted: {shown}", file=sys.stderr)
    rfa = state.get("read_first") if isinstance(state.get("read_first"), dict) else {}
    if rfa.get("unaccounted"):
        print(f"verdict-finalize: {len(rfa['unaccounted'])} of {len(rfa.get('items') or [])} read_first "
              f"functions are neither cited by a finding nor named in not_tested: "
              f"{', '.join(rfa['unaccounted'][:5])}{' ...' if len(rfa['unaccounted']) > 5 else ''}",
              file=sys.stderr)
    # A proven finding with no command behind it is proven to its author only: a stranger,
    # and `verdict-replay`, have prose. Said once here - and refused under `repro_rule: on`
    # for a finding filed in this run. A record older than the repro block carries proven
    # findings without one (19 of them in one project's record when the rule was first turned
    # on); refusing every later run for those would stop the record, not improve it.
    # ASCII on purpose: this stream reaches a cp1252 console on Windows (CI, 2026-10-17).
    if prose := without_repro(state["findings"]):
        filed_now = {str(f.get("id")) for f in state["findings"] if f.get("delta") == "NEW"}
        fresh = [i for i in prose if i in filed_now]
        if strict and fresh:
            print(f"verdict-finalize: repro_rule is on and {len(fresh)} proven Major+ finding(s) "
                  f"carry no `repro` block: {', '.join(fresh)} - add the command that shows the "
                  "defect (command, cwd, expect), or file the finding as `probable`",
                  file=sys.stderr)
            return 2
        print(f"verdict-finalize: no structured repro on {len(prose)} proven Major+ finding(s): "
              f"{', '.join(prose)}; verdict-replay cannot check them. A `repro` block "
              "(command, cwd, expect) makes a finding a command a stranger can run",
              file=sys.stderr)
    # Folded in memory; the ledger is saved only once the state is accepted (questions.fold).
    asked, qnotes, qledger = questions.fold(
        qa_root, questions.id_prefix(state["findings"], state["project"]),
        judgment.get("questions"), state["run_number"], run_date(facts))
    if asked["parked"] or asked["answered_since_last_run"]:
        state["questions"] = asked
    else:
        state.pop("questions", None)     # not carried from the previous state as an unknown key
    for note in qnotes:
        print(f"verdict-finalize: {note}", file=sys.stderr)

    # Render the report before validating: the validator requires the file to
    # exist, and writing it here is what makes "the report went missing"
    # impossible rather than merely forbidden. A refusal takes it back (below).
    report_rel = (state.get("last_run") or {}).get("report") or ""
    if not report_rel or not report_rel.endswith(".md"):
        stamp = facts.get("measured_at", "")[:10]
        topic = judgment.get("topic") or state.get("run_type", "run")
        report_rel = _report_name(qa_root, stamp, topic, state.get("run_number"))
        state["last_run"]["report"] = report_rel
    # Contained before it is written. The field was honoured as given, so an
    # absolute path or a `..` named any `*.md` in the code under test — the
    # README of a team-mode checkout, proven — and `mkdir(parents=True)` built
    # the way there (audit 2026-10-02, H-D-1). The report lives directly under
    # the QA root's reports/, which is where every real record has ever put it;
    # anything else is refused with nothing written.
    outside = report_outside_reports(report_rel)
    if outside:
        print(f"verdict-finalize: refusing the report path {report_rel!r} — {outside}",
              file=sys.stderr)
        return 1
    report_path = qa_root / report_rel
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # The link check at the top read the root as it stood; this reads the one name
    # about to be opened, at the moment it is opened.
    if report_path.is_symlink() or report_path.parent.resolve() != qa_root / "reports":
        print(f"verdict-finalize: refusing the report path {report_rel!r} — it does not "
              "resolve to a plain file directly under the QA root's reports/",
              file=sys.stderr)
        return 1
    displaced = report_path.read_bytes() if report_path.is_file() else None
    report_path.write_text(render_report(state, judgment.get("prose")), encoding="utf-8")

    problems = write_state(qa_root, state)
    if problems:
        # Not left as an orphan: removed if this call created it, its bytes put back if
        # it replaced a file (a judgment may name an earlier run's report). Left behind, it
        # is a "run N" no state, INDEX row or runs.jsonl line records, naming question ids
        # the ledger never minted; a retry renders it again, and a next attempt dated
        # another day writes a second "run N" beside it.
        if displaced is None:
            report_path.unlink(missing_ok=True)
        else:
            report_path.write_bytes(displaced)
        print(f"verdict-finalize: refusing to write an invalid state "
              f"({len(problems)} problem(s)):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    questions.save(qa_root, qledger)
    marker = qa_root / "run-in-progress.json"
    marker.unlink(missing_ok=True)
    _record_bill(qa_root, state, bill, gateway_host)
    disagreements = check_artifacts(qa_root, state)
    if disagreements:
        # Loud, on the stream the agent reads, and not a refusal: the run is
        # recorded and the state is valid. What is wrong is a renderer, and a
        # renderer defect is a finding about this harness — file it.
        print("verdict-finalize: WARNING — the artifacts this run wrote disagree with each "
              f"other ({len(disagreements)}); where they disagree the harness composed a "
              "value instead of measuring it. File it as a finding against verdict:\n  "
              + "\n  ".join(disagreements), file=sys.stderr)
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
        # The split, in the artifact a human reads. 0.64.0 recorded
        # `outcome_basis` and split the counts in the state, and this renderer —
        # the only place most readers ever see the number — kept printing one
        # column under a footnote saying a resolution nobody measured settles
        # nothing, which since that release is false (VERDICT-F-36).
        split = any(v.get("confirmed_claimed") or v.get("confirmed_accepted") for _, v in rows)
        acc_col = any(v.get("confirmed_accepted") for _, v in rows)
        header = ("| Held up | of those, measured |"
                  + (" accepted by the maintainer |" if acc_col else "")
                  + " Withdrawn | Rate |" if split else "| Held up | Withdrawn | Rate |")
        lines += [f"| {label} {header}", "|---|" + "---|" * ((4 + acc_col) if split else 3)]
        for key, v in sorted(rows, key=lambda kv: -kv[1]["decided"]):
            rate = f"{v['precision']:.0%}" if v.get("precision") is not None else "_not yet_"
            measured = f" {v.get('confirmed_measured', 0)} |" if split else ""
            if acc_col:
                measured += f" {v.get('confirmed_accepted', 0)} |"
            lines.append(f"| {key} | {v['confirmed']} |{measured} {v['refuted']} | {rate} |")
        lines.append("")
    buckets = [v for store in (cal.get("by_confidence") or {},
                               cal.get("by_proof_method") or {})
               for v in store.values()]
    any_claimed = any(v.get("confirmed_claimed") for v in buckets)
    # Rows written before `outcome_basis` existed carry neither, and the state
    # deliberately refuses to relabel them. The table showed `19 | 0` under a
    # caveat calling the two kinds exhaustive, so a reader subtracted and read
    # 19 as the tester's word — the state careful, the renderer not, which is
    # the split-brain shape VERDICT-F-36 was about, one release later
    # (VERDICT-F-45).
    # `buckets` is two stores concatenated, and each one partitions the same
    # settled outcomes — so the count has to be summed WITHIN a store and
    # compared ACROSS them, never taken over the concatenation. Taking a
    # maximum over the individual buckets reported the largest single row where
    # the sentence beneath says "those confirmations", meaning the whole
    # column: `Up to 17` where 21 of 28 were unrecorded, leaving a reader to
    # subtract 17 from 28 and credit 11 to the tester's word when the real
    # figure was 7 (VERDICT-F-51). The maximum across stores is a guard against
    # one of them carrying fewer rows than the other.
    def _unrecorded(store):
        return sum(max(0, v.get("confirmed", 0) - v.get("confirmed_measured", 0)
                       - v.get("confirmed_claimed", 0) - v.get("confirmed_accepted", 0))
                   for v in store.values())
    unrecorded = max((_unrecorded(store) for store in
                      (cal.get("by_confidence") or {}, cal.get("by_proof_method") or {})
                      if store), default=0)
    lines += [f"*A rate appears once a row has {cal.get('min_sample')} settled outcomes. "
              "Settled means fix-verified or regressed (it held up) against withdrawn "
              "(it did not); a resolution nobody checked at all settles nothing.*"]
    if any_claimed:
        lines += ["", "*`held up` covers two things and they are not equal: a re-injection "
                  "the harness measured, and one the tester asserted where no measurement "
                  "contradicts it. The `measured` column is the first kind. Read them "
                  "apart.*"]
    if any(v.get("confirmed_accepted") for v in buckets):
        lines += ["", "*`accepted by the maintainer` is a third kind: the defect was confirmed "
                  "by the person who owns the code and the fix was declined (`verdict-accept`). "
                  "It held up on their word, not under a check.*"]
    if unrecorded:
        lines += ["", f"*{unrecorded} of those confirmations were settled before "
                  "`outcome_basis` was recorded and are neither kind. They are counted in "
                  "`held up` and in no other column, because calling them the tester's word "
                  "would be a claim of its own.*"]
    lines.append("")
    return lines


def _render_reading_map(state: dict) -> list[str]:
    """Where the least-tested code is, and which of it no finding has touched."""
    rm = state.get("reading_map") if isinstance(state.get("reading_map"), dict) else {}
    if rm.get("status") != "measured" or not rm.get("lowest"):
        return []
    out = [f"## Reading map ({rm.get('modules')} production modules, "
           f"{rm.get('overall_percent')}% covered overall)", "",
           "| Module | Covered | Statements | Open findings | Last cited |",
           "|---|---|---|---|---|"]
    for m in rm["lowest"][:10]:
        cited = f"run {m['last_cited_run']}" if m.get("last_cited_run") is not None else "never"
        out.append(f"| `{m['path']}` | {m.get('percent')}% | {m.get('statements')} "
                   f"| {m.get('open_findings', 0)} | {cited} |")
    never = rm.get("never_examined") or []
    if never:
        out += ["", "Never cited by any finding, least covered first: "
                + ", ".join(f"`{p}`" for p in never[:10])]
    out.append("")
    return out


def _render_read_first(state: dict) -> list[str]:
    """The ranked functions, and which of them the run accounted for."""
    rf = state.get("read_first") if isinstance(state.get("read_first"), dict) else {}
    if not rf.get("items"):
        return []
    status = {k: "finding" for k in rf.get("cited") or []}
    status.update({k: "not_tested" for k in rf.get("declared_untested") or []})
    out = [f"## Read first — {rf.get('basis')}", "",
           "| Function | Risk | Accounted for |", "|---|---|---|"]
    for it in rf["items"]:
        key = f"{it.get('path')}::{it.get('function')}" if it.get("function") else str(it.get("path"))
        out.append(f"| `{key}` | {it.get('risk') or '—'} | {status.get(key, '**no** — neither cited nor declared untested')} |")
    if rf.get("unaccounted"):
        out += ["", f"{len(rf['unaccounted'])} of {len(rf['items'])} ranked functions were neither cited by a "
                "finding nor named in Not tested."]
    out.append("")
    return out


def _render_questions(state: dict) -> list[str]:
    """The questions parked for a person, and the answers no run had read yet."""
    asked = state.get("questions") if isinstance(state.get("questions"), dict) else {}
    parked, fresh = asked.get("parked") or [], asked.get("answered_since_last_run") or []
    if not parked and not fresh:
        return []
    out = [f"## Needs human decision ({len(parked)} parked)", ""]
    for q in parked:
        meta = f"asked run {q.get('asked_at_run')}"
        if q.get("age_days") is not None:
            meta += f", {q['age_days']}d ago"
        if q.get("finding"):
            meta += f" · about {q['finding']}"
        out.append(f"- **{q.get('id')}** ({meta}) — {q.get('question')}")
        if q.get("context"):
            out.append(f"  _{q['context']}_")
    if not parked:
        out.append("_None parked._")
    if fresh:
        out += ["", "### Answered since the last run", ""]
        for q in fresh:
            decided = (f"dismissed: {q.get('reason')}" if q.get("status") == "dismissed"
                       else str(q.get("answer")))
            out.append(f"- **{q.get('id')}** — {q.get('question')}\n"
                       f"  → {decided} ({q.get('by')}, {q.get('on')})")
    out += ["", f"_Answer with `verdict-answer {state.get('project')} <Q-id> --answer "
            "\"…\"`; the next run reads the decision instead of asking again._", ""]
    return out


def _measured_lines(f: dict, drift: dict, carried_unread: bool = False) -> list[str]:
    """Measured, not remembered: when the harness last ran this finding's
    test, whether the code it cites is still where the evidence says, and
    whether the tester re-reported it by id."""
    out = []
    if f.get("last_verified_at"):
        v = f.get("verification") if isinstance(f.get("verification"), dict) else {}
        at_head = v.get("at_head") if v.get("at_head") in ("pass", "fail") else None
        out.append(f"- Last measured {str(f['last_verified_at'])[:10]}"
                   + (f" — {'passes' if at_head == 'pass' else 'fails'} at HEAD"
                      if at_head else ""))
    elif is_open(f) and not f.get("verification_test"):
        out.append("- Never measured — no `verification_test` declared")
    ex = f.get("exercised_by_tests") or []
    if ex and is_open(f):
        out.append("- Exercised and green: " + ", ".join(f"`{t}`" for t in ex[:5])
                   + " — these run the cited lines and do not fail on the defect; the "
                     "assertion to review, and where a regression test belongs")
    moved_refs = _drifted_refs(drift, f)
    if moved_refs:
        out.append(f"- Cited code {moved_refs[0]} since the evidence was written: "
                   + ", ".join(moved_refs[1]))
    if f.get("re_reported") == "still_open" and carried_unread:
        # A local or sweep night carries an unmoved finding by id without reading it. Its
        # report said "looked at, still there" 73 times a night while its own not_tested
        # said "carried unread" (Sales, every night since 2026-09-27).
        out.append("- _Carried by id, not re-read this run: the cited code did not move; "
                   "the evidence is as last filed_")
    elif f.get("re_reported"):
        out.append(f"- _Re-reported by id (`{f['re_reported']}`): looked at, "
                   f"{'still there' if f['re_reported'] == 'still_open' else 'gone'}; "
                   "the evidence is as last filed_")
    return out


def _days_between(start, end) -> int | None:
    """Whole days from one recorded date to another, or None when either is
    missing or unreadable — a clock the report prints only when both ends
    were measured."""
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
    except (TypeError, ValueError):
        return None
    return (b - a).days


def _drifted_refs(drift: dict, finding: dict):
    """(worst drift, [rendered refs]) for a finding whose cited code moved, or None."""
    fid = str(finding.get("id") or "")
    d = (drift.get("findings") or {}).get(fid) or (drift.get("accepted") or {}).get(fid)
    if not isinstance(d, dict) or d.get("drift") not in DRIFTED:
        return None
    refs = [r for r in (d.get("refs") or []) if r.get("status") in DRIFTED]
    shown = [str(r.get("ref")) + (f" (now line {r['now_line']})" if r.get("now_line")
                                  else f" ({r.get('status')})") for r in refs[:6]]
    return d["drift"], shown


def _judge_line(state: dict, last: dict) -> list:
    """Who answered, and what it cost — beside the Harness line, never inferred.

    A report that names its harness and not its judge reads the same whether an
    Opus session spent four dollars on it or an 8B model on the desk answered
    forty bounded questions for nothing. Those are different reports, and the
    difference is exactly what a reader weighing the verdict needs first. A
    sweep says so too: "none" is a judge, and a run nobody judged must not look
    like a run somebody did.

    The model names the judge; the gateway it answered through is not on the line,
    even for a state written before the host left `last_run.local`. A team commits
    this report, and a network address is the payer's, not the reader's.
    """
    engine = last.get("engine")
    if not engine:
        return (["- Judge: none (model-free sweep) — no model was called, so nothing here "
                 "was judged this run"] if state.get("run_type") == "sweep" else [])
    local = last.get("local") if isinstance(last.get("local"), dict) else {}
    parts = [f"- Judge: {engine} · model `{last.get('model') or '?'}`"]
    parts.append(f"{local.get('calls', 0)} call(s), {local.get('tokens', 0)} token(s)")
    if local.get("errors"):
        parts.append(f"{local['errors']} transport error(s)")
    parts.append(f"{local.get('unanswered', 0)} question(s) unanswered")
    parts.append("no Claude tokens spent")
    return [" · ".join(parts)]


def _hygiene_lines(state: dict) -> list[str]:
    """What the scan's ledger could not do this run, and what a judgment said that it
    ignored — said under the scope, where a reader looks before trusting the counts."""
    block = state.get("hygiene") if isinstance(state.get("hygiene"), dict) else {}
    out = []
    if (block.get("summary") or {}).get("prior_unread"):
        out.append(f"- Hygiene ledger: last run's hygiene rows could not be read ({HYGIENE_LEDGER_FILE} "
                   "missing, unreadable, or written by another run) — nothing was carried forward: "
                   "every row this run is NEW, and none was resolved")
    ids = block.get("ignored_judgment_ids") or []
    if ids:
        out.append(f"- Hygiene findings the judgment named, and ignored: {', '.join(map(str, ids))} — "
                   "the scan's own: each resolves when the scan stops seeing it, never on a "
                   "judgment's word")
    return out


def render_report(state: dict, prose: dict | None = None) -> str:
    """Render the report from the state, injecting the agent's prose.

    Everything countable comes from the state, so the report and the state
    cannot disagree — they did, once, when the state pointed at a stale file.
    Everything that requires a sentence comes from `prose`, because a rendered
    table is not an explanation and nobody should pretend otherwise.
    """
    # Belt and braces: `validate_judgment` rejects a non-object `prose` with a
    # message its author can act on, but a renderer that raises AttributeError
    # on unexpected input is a renderer that loses a whole run to a typo.
    prose = prose if isinstance(prose, dict) else {}
    last = state.get("last_run") or {}
    out = [f"# QA report — {state.get('project')} · run {state.get('run_number')} "
           f"({state.get('run_type')})", ""]
    if state.get("run_label"):
        out += [f"*{state['run_label']}*", ""]
    out += [f"**VERDICT: {state.get('verdict')}**", ""]
    rule = state.get("verdict_rule") if isinstance(state.get("verdict_rule"), dict) else None
    if rule:
        detail = rule.get("reason") or ", ".join(rule.get("raised_by") or [])
        out += [f"> Set by the harness ({rule.get('rule')}): the judgment said "
                f"`{rule.get('was')}`; {detail}.", ""]

    out += ["## Scope", "",
            f"- Range: `{last.get('sha_range') or last.get('git_sha') or 'n/a'}`"
            + (f" · {last['diff_stat']}" if last.get("diff_stat") else ""),
            f"- Branch: `{last.get('git_branch') or 'n/a'}` · measured {last.get('timestamp_utc')}"]
    harness = last.get("harness") or {}
    if harness.get("path"):
        prompt = harness.get("prompt_sha256")
        out.append(f"- Harness: verdict-qa-mcp {harness.get('version') or '?'}"
                   + (f" · prompt {prompt[:12]}" if prompt else "")
                   + f" · `{harness['path']}`")
    out += _judge_line(state, last)
    drift = state.get("evidence_drift") if isinstance(state.get("evidence_drift"), dict) else {}
    if drift.get("status") == "measured":
        summary = drift.get("summary") or {}
        moved = summary.get("drifted_findings") or []
        moved_acc = summary.get("drifted_accepted") or []
        out.append(f"- Evidence drift: {len(moved)} of {len(drift.get('findings') or {})} "
                   "anchored open findings cite code that moved or changed since the "
                   "evidence was written"
                   + (f" ({', '.join(moved)})" if moved else "")
                   + (f"; under accepted risks: {', '.join(moved_acc)}" if moved_acc else ""))
    elif drift.get("status") == "unavailable":
        out.append(f"- Evidence drift: not measured — {drift.get('reason')}")
    iso = state.get("isolation_check") or {}
    if iso:
        detail = iso.get("method") or iso.get("note") or ""
        out.append(f"- Isolation check: **{iso.get('result', iso.get('status', 'n/a'))}**"
                   + (f" — {detail}" if detail else ""))
    out += _hygiene_lines(state)
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
        # Counts, not list lengths: the lists are capped at 50 for display and a
        # state from before the counts travelled falls back to the old reading.
        added_n = ids.get("added_count", len(ids.get("added", [])))
        removed_n = ids.get("removed_count", len(ids.get("removed", [])))
        out.append(f"Test-id ledger: {ids['count']} ids · +{added_n} / −{removed_n} "
                   "(set-diff, not summary arithmetic)"
                   + (" — id lists truncated to 50 each" if ids.get("truncated") else ""))
    elif ids.get("status") == "unavailable":
        out.append(f"Test-id ledger: **unavailable** — {ids.get('reason', '')}")
    measured = [f for f in state.get("findings", []) if isinstance(f.get("verification"), dict)]
    if measured or state.get("verification_notes"):
        # Counted from the measurement, never from `fix_verified` — that is the
        # one judgment field here, and counting it inside a block selected by
        # measurement published run 5's error/error record as "1 verified"
        # (VERDICT-F-30). Both halves below are the harness's own: `at_*` come
        # from the re-run, `delta` from merge.
        def _shows_fix(f):
            v = f["verification"]
            return v.get("at_previous") == "fail" and v.get("at_head") == "pass" and _chosen(v)
        verified = sum(1 for f in measured if _shows_fix(f) and f.get("delta") == "RESOLVED")
        refused = sum(1 for f in measured if f.get("resolution_refused"))
        not_run = sum(1 for f in measured
                      if f["verification"].get("selected_by") == "unselectable")
        prose_only = sum(1 for f in measured if f["verification"].get("not_weighed"))
        out.append(f"Fix verification: {verified} verified · {refused} refused (cited test "
                   f"still fails at HEAD) · {len(measured) - verified - refused - not_run} "
                   "measured but not verifiable"
                   + (f" · {not_run} not run (tests cited in prose only, none declared "
                      "as `verification_test`)" if not_run else "")
                   + (f" · {prose_only} measured on a prose citation only — recorded, not "
                      "confirmed; declare `verification_test`" if prose_only else ""))
        unconfirmed = [str(f.get("id")) for f in measured
                       if f.get("fix_verified") is True and not _shows_fix(f)]
        if unconfirmed:
            out.append("  - claims fix_verified the measurement does not show: "
                       + ", ".join(unconfirmed))
        for note in state.get("verification_notes") or []:
            out.append(f"  - {note}")
    cov = state.get("coverage") or {}
    if cov.get("status") == "measured":
        if cov.get("changed_lines"):
            out.append(f"Diff coverage: {cov['changed_lines_executed']}/{cov['changed_lines']} "
                       f"changed lines executed ({cov.get('percent')}%) across "
                       f"{cov['changed_files']} file(s); "
                       f"{len(cov.get('tests_touching_diff') or [])} test(s) touch the diff")
            kinds = cov.get("by_kind") or {}
            prod, tests_ = kinds.get("production") or {}, kinds.get("tests") or {}
            if prod.get("changed_lines") or tests_.get("changed_lines"):
                out.append(
                    f"  - production {prod.get('changed_lines_executed', 0)}/"
                    f"{prod.get('changed_lines', 0)}"
                    + (f" ({prod['percent']}%)" if prod.get("percent") is not None else "")
                    + f" · test code {tests_.get('changed_lines_executed', 0)}/"
                    f"{tests_.get('changed_lines', 0)}"
                    + (f" ({tests_['percent']}%)" if tests_.get("percent") is not None else "")
                    + " — read production first; a test file's fixtures and `def` lines "
                      "never carry a test context, so the blended number moves with the "
                      "shape of the diff")
            if cov.get("changed_lines_executed_in_subprocess"):
                out.append(f"  - {cov['changed_lines_executed_in_subprocess']} of them only in a "
                           "subprocess the suite spawned — measured, but no test to name")
            for path, pf in (cov.get("per_file") or {}).items():
                if pf.get("unexercised_ranges"):
                    rng = ", ".join(f"{a}-{b}" if a != b else str(a)
                                    for a, b in pf["unexercised_ranges"])
                    fns = ", ".join(pf.get("unexercised_functions") or [])
                    out.append(f"  - {path}: unexercised lines {rng}"
                               + (f" — functions never entered: {fns}" if fns else "")
                               + (f" ({pf['note']})" if pf.get("note") else ""))
        else:
            out.append("Diff coverage: no .py lines changed in the range")
    elif cov.get("status") == "unavailable":
        out.append(f"Diff coverage: **unmeasurable** — {cov.get('reason', '')}")

    if prose.get("risks"):
        out += ["", "## Risks", "", prose["risks"]]

    # The gate, the MCP surface and this report must agree on what "REGRESSED
    # first" means. They did not: this module carried its own copy of the sort,
    # and a severity with a stray space already sorted differently in the two.
    findings = order_findings(state.get("findings") or [])
    open_f = [f for f in findings if is_open(f)]
    accepted_f = [f for f in findings if norm_status(f.get("status")) == "accepted"]
    out += ["", f"## Findings — REGRESSED first ({len(open_f)} open of {len(findings)} tracked"
            + (f" · {len(accepted_f)} accepted" if accepted_f else "") + ")", ""]
    if not findings:
        out.append("_None recorded this run._")
    # Who carried the findings: a local engine or a sweep carries an unmoved one by id
    # without reading it; only a judging tester "looked at" it.
    carried_unread = ((state.get("last_run") or {}).get("engine") == "verdict-local"
                      or state.get("run_type") == "sweep")
    for f in findings:
        cls = f.get("failure_classification")
        dwell = _days_between(f.get("introduced_at"), f.get("first_seen"))
        latency = _days_between(f.get("first_seen"), f.get("fixed_at"))
        out.append(f"### {f.get('id')} — {f.get('delta', '?')} — "
                   f"{f.get('severity')}/{f.get('priority')}"
                   + (f" — {cls}" if cls else "")
                   + (f" — age {f['age_days']}d" if f.get("age_days") else "")
                   + (f" · lived {dwell}d before detection" if dwell is not None else "")
                   + (f" · fix verified {latency}d after detection" if latency is not None else ""))
        out.append("")
        out.append(str(f.get("title", "")))
        for e in (f.get("evidence") or []):
            out.append(f"- {e}")
        out += _measured_lines(f, drift, carried_unread)
        rc = f.get("root_cause") or {}
        if rc:
            chain = " → ".join(str(rc[k]) for k in ("mechanism", "origin") if rc.get(k))
            if chain:
                out.append(f"- Root cause: {chain}")
            if rc.get("class"):
                out.append(f"- Class: {json.dumps(rc['class'])[:200]}")
        if f.get("carried_forward"):
            out.append(f"- _{f['carried_forward']}_")
        acc = f.get("accepted") if norm_status(f.get("status")) == "accepted" else None
        if acc:
            out.append(f"- _Accepted risk — {acc.get('on')} by {acc.get('by')}, citing "
                       f"{acc.get('citation')}: {acc.get('reason')}_")
        if isinstance(f.get("accepted_revoked"), dict):
            r = f["accepted_revoked"]
            out.append(f"- _Acceptance revoked {r.get('on')} by {r.get('by')}: {r.get('reason')}_")
        narrative = prose.get("findings")
        if isinstance(narrative, dict) and narrative.get(str(f.get("id"))):
            out += ["", narrative[str(f.get("id"))]]
        out.append("")

    if accepted_f:
        # Apart from the open list and after it, never instead of it: a risk
        # somebody accepted is out of the counts, not out of sight.
        out += ["", f"## Accepted risks ({len(accepted_f)})", "",
                "_The maintainer's decision, recorded with `verdict-accept`, never the "
                "tester's: each is a real defect whose fix was declined, with the reason and "
                "where the decision is written down. Out of the open counts and the release "
                "blockers; not out of sight._", ""]
        for f in accepted_f:
            a = f.get("accepted") or {}
            moved_refs = _drifted_refs(drift, f)
            out.append(f"- **{f.get('id')}** ({f.get('severity')}/{f.get('priority')}, age "
                       f"{f.get('age_days', 0)}d) — accepted {a.get('on')} by {a.get('by')}, "
                       f"citing {a.get('citation')}: {a.get('reason')}"
                       + (f" — **the code under it {moved_refs[0]}** since the evidence was "
                          f"written: {', '.join(moved_refs[1])}" if moved_refs else ""))
        out.append("")

    out += _render_calibration(state.get("calibration") or {})

    blockers = state.get("release_blockers") or []
    out += ["## Release blockers", "",
            "\n".join(f"- {b}" for b in blockers) if blockers else "_None._", ""]
    vi = state.get("verified_intact") or []
    if vi:
        # Placed directly after the blockers, not buried mid-report: the
        # confirmation that named invariants held is a headline, not a footnote.
        out += ["## Verified intact", "",
                "\n".join(f"- {v}" for v in vi), ""]
    out += _render_questions(state)
    out += _render_read_first(state)
    out += _render_reading_map(state)
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
