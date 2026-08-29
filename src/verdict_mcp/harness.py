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
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from .project_key import derive_key
    from .validate import validate
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project_key import derive_key
    from validate import validate

RE_BASELINE_AFTER_DAYS = 7
RE_BASELINE_FILES = 100
RE_BASELINE_LINES = 10_000
# pytest, vitest, go test and friends all end with a countable line; these
# cover the runners the fixtures and live projects actually use.
_COUNT_PATTERNS = (
    (re.compile(r"(\d+) passed"), "passed"),
    (re.compile(r"(\d+) failed"), "failed"),
    (re.compile(r"(\d+) skipped"), "skipped"),
    (re.compile(r"(\d+) error"), "errors"),
    (re.compile(r"(\d+) xfailed"), "xfailed"),
)


def _run(cmd, cwd=None, shell=False):
    return subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True)


def _git(args, repo):
    proc = _run(["git", "-C", str(repo), *args])
    return proc.stdout.strip() if proc.returncode == 0 else None


def _summary_line(output: str) -> str:
    """The last line carrying countable results — the line a human reads."""
    for line in reversed([l.strip() for l in output.splitlines() if l.strip()]):
        if any(p.search(line) for p, _ in _COUNT_PATTERNS):
            return line[:300]
    tail = [l.strip() for l in output.splitlines() if l.strip()]
    return tail[-1][:300] if tail else ""


def _counts(output: str) -> dict:
    counts = {}
    for pattern, name in _COUNT_PATTERNS:
        m = pattern.search(output)
        if m:
            counts[name] = int(m.group(1))
    return counts


def collect(repo: Path, qa_root: Path, gates: list[tuple[str, str]],
            test_ids_cmd: str | None = None) -> dict:
    """Measure everything about this run that is not a judgment."""
    now = datetime.now(timezone.utc)
    previous = None
    state_path = qa_root / "state.json"
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

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
        gate_results[name] = {
            "command": command,
            "exit_code": proc.returncode,
            "result": "pass" if proc.returncode == 0 else "fail",
            "duration_s": duration,
            "summary": _summary_line(output),
            **({"counts": _counts(output)} if _counts(output) else {}),
        }

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
    }

    tests = {}
    for gate in gate_results.values():
        tests.update(gate.get("counts", {}))
        if "duration_s" not in tests and gate.get("counts"):
            tests["duration_s"] = gate["duration_s"]
    if tests:
        collected = sum(v for k, v in tests.items()
                        if k in ("passed", "failed", "skipped", "errors", "xfailed"))
        facts["tests"] = {"collected": collected, **tests}

    if test_ids_cmd:
        proc = _run(test_ids_cmd, cwd=repo, shell=True)
        ids = sorted({l.strip() for l in proc.stdout.splitlines() if "::" in l})
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
            before = ([l.strip() for l in ledger.read_text(encoding="utf-8").splitlines() if l.strip()]
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
    import hashlib
    if finding.get("hash"):
        return str(finding["hash"])
    evidence = " ".join(str(e) for e in (finding.get("evidence") or []))
    m = re.search(r"([A-Za-z0-9_./-]+\.[A-Za-z]{1,5})", evidence)
    path = m.group(1) if m else ""
    title = _WS.sub(" ", _LINE_NUMBERS.sub("", str(finding.get("title", "")))).strip().lower()
    return hashlib.sha256(f"{path}|{title}".encode()).hexdigest()[:8]


def merge(facts: dict, judgment: dict, previous: dict | None, today: date | None = None) -> dict:
    """Facts + judgment → a state file, with identity and deltas computed."""
    today = today or date.today()
    prev_by_hash = {}
    for f in ((previous or {}).get("findings") or []):
        if f.get("hash"):
            prev_by_hash[str(f["hash"])] = f

    findings = []
    seen = set()
    for f in judgment.get("findings", []) or []:
        entry = dict(f)
        h = finding_hash(entry)
        entry["hash"] = h
        seen.add(h)
        prior = prev_by_hash.get(h)
        first_seen = (prior or {}).get("first_seen") or today.isoformat()
        entry["first_seen"] = first_seen
        try:
            entry["age_days"] = (today - date.fromisoformat(str(first_seen))).days
        except ValueError:
            entry["age_days"] = 0
        status = entry.get("status", "open")
        if entry.get("delta") == "WITHDRAWN":
            pass  # the tester's own correction; never overwritten
        elif prior is None:
            entry["delta"] = "NEW"
        elif status == "resolved":
            entry["delta"] = "RESOLVED"
        elif prior.get("status") == "resolved":
            entry["delta"] = "REGRESSED"
        else:
            entry["delta"] = "STILL_OPEN"
        findings.append(entry)

    # A finding the previous run had and this run did not mention is resolved —
    # silence is not the same as an assertion, so it is carried, not dropped.
    for h, prior in prev_by_hash.items():
        if h in seen or prior.get("status") == "resolved":
            continue
        carried = dict(prior)
        carried.update(status="resolved", delta="RESOLVED",
                       carried_forward="not reported this run; no longer observed")
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
        if f.get("status") == "open":
            sev[f.get("severity")] = sev.get(f.get("severity"), 0) + 1
    bcmm = "/".join(str(sev.get(s, 0)) for s in ("Blocker", "Critical", "Major", "Minor"))
    report = str((state.get("last_run") or {}).get("report") or "")
    name = Path(report).name
    return (f"| {date.today().isoformat()} | {state['project']} | {state['run_type']} "
            f"| {state['verdict']} | {counts} | n/a | {bcmm} | [{name}]({report}) |")


INDEX_HEADER = ("| Date | Project | Run type | Verdict | Tests (pass/skip/fail) | Δ tests "
                "| Findings (B/C/M/m) | Report |\n|---|---|---|---|---|---|---|---|")


def write_state(qa_root: Path, state: dict) -> list[str]:
    """Validate, then write: state.json.prev, state.json, and the INDEX row.

    Validation happens here because the PostToolUse hook matches Write/Edit and
    would never see a file a shell command wrote. An invalid state is not
    written at all — prevention beats notification.
    """
    problems = validate(state, qa_root, _read_json(qa_root / "state.json"))
    if problems:
        return problems
    current = qa_root / "state.json"
    if current.is_file():
        shutil.copyfile(current, qa_root / "state.json.prev")
    current.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    reports = qa_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    index = reports / "INDEX.md"
    if index.is_file():
        body = index.read_text(encoding="utf-8").rstrip("\n")
    else:
        body = f"# QA run index — {state['project']}\n\n{INDEX_HEADER}"
    index.write_text(body + "\n" + index_row(state) + "\n", encoding="utf-8")
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
    import os
    home = Path(os.environ.get("VERDICT_HOME", str(Path.home() / ".claude" / "verdict")))
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
    facts = collect(repo, qa_root, gates, args.test_ids_cmd)
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
    state = merge(facts, judgment, previous)
    problems = write_state(qa_root, state)
    if problems:
        print(f"verdict-finalize: refusing to write an invalid state "
              f"({len(problems)} problem(s)):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    print(f"verdict-finalize: wrote {qa_root / 'state.json'} "
          f"(run {state['run_number']}, {state['run_type']}, verdict {state['verdict']!r}) "
          f"and appended the INDEX row")
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
