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
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from . import questions
    from .anchors import evidence_drift
    from .census import code_census
    from .hygiene import hygiene_census, is_hygiene
    from .filed import FINDINGS_DIR, archive_findings, load_filed
    from .readfirst import read_first
    from .focus import risk_focus
    from .replay import adopt_backfill, load_backfill, measure_findings, without_repro
    from .escalate import not_tested_line as escalation_not_tested
    from .reports import read_report
    from .profile import (ProfileError, gates_from, hygiene_filing_from, contract_rule_from,
                          repro_rule_from, risk_class_from, risk_paths_from,
                          assertion_gaps_from)
    from .profile import load as load_profile
    from .project_key import derive_key
    from .state import is_open, load_accepted, load_outcomes, norm_status, project_key_for_root
    from .state import load_runs
    from .state import misplaced_root, root_refusal
    from .validate import (inherited_conflicts, known_tests, report_outside_reports,
                           validate_judgment)
    from . import clock
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import questions
    from anchors import evidence_drift
    from census import code_census
    from hygiene import hygiene_census, is_hygiene
    from filed import FINDINGS_DIR, archive_findings, load_filed
    from readfirst import read_first
    from focus import risk_focus
    from replay import adopt_backfill, load_backfill, measure_findings, without_repro
    from escalate import not_tested_line as escalation_not_tested
    from reports import read_report
    from profile import (ProfileError, gates_from, hygiene_filing_from, contract_rule_from,
                         repro_rule_from, risk_paths_from, assertion_gaps_from,
                         risk_class_from)
    from profile import load as load_profile
    from project_key import derive_key
    from state import is_open, load_accepted, load_outcomes, norm_status, project_key_for_root
    from state import load_runs
    from state import misplaced_root, root_refusal
    from validate import (inherited_conflicts, known_tests, report_outside_reports,
                          validate_judgment)
try:  # split out of this file by the structure pass; still importable here
    from .harness_common import _git, _read_json, _resolve_root, _run, _session_identity
except ImportError:  # executed as a bare script
    from harness_common import _git, _read_json, _resolve_root, _run, _session_identity
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
try:  # split out of this file by the structure pass; still importable here
    from .report_names import _lift_narratives, _re_report, _report_name, _safe_topic as _safe_topic
except ImportError:  # executed as a bare script
    from report_names import _lift_narratives, _re_report, _report_name, _safe_topic as _safe_topic
try:  # split out of this file by the structure pass; still importable here
    from .finalize_policy import change_lines, gate_policy
except ImportError:  # executed as a bare script
    from finalize_policy import change_lines, gate_policy
try:  # split out of this file by the structure pass; still importable here
    from .finalize_bill import _gateway_host, _measure_bill, _record_bill
except ImportError:  # executed as a bare script
    from finalize_bill import _gateway_host, _measure_bill, _record_bill
try:  # split out of this file by the structure pass; still importable here
    from .report_sections import _render_calibration as _render_calibration
except ImportError:  # executed as a bare script
    from report_sections import _render_calibration as _render_calibration
try:  # split out of this file by the structure pass; still importable here
    from .report_render import render_report
except ImportError:  # executed as a bare script
    from report_render import render_report

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


if __name__ == "__main__":
    sys.exit(main())
