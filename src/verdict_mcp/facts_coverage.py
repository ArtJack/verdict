"""Measuring which changed lines the suite executes: the coverage run, the diff it is
read against, the gaps census, and the marker that lets a run reuse a fresh measurement.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    from .gaps import BUDGET_S as GAPS_BUDGET_S, census as gap_census_of
    from . import sandbox
    from .harness_common import _git, _read_json, _session_identity
    from .facts_suite import _summary_line
    from .facts_reading import (SUBPROCESS_CONTEXT, _test_id_from_context, _tracked_python,
                                exercised_by_from, is_test_file, reading_map_from)
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import sandbox
    from gaps import BUDGET_S as GAPS_BUDGET_S, census as gap_census_of
    from harness_common import _git, _read_json, _session_identity
    from facts_suite import _summary_line
    from facts_reading import (SUBPROCESS_CONTEXT, _test_id_from_context, _tracked_python,
                               exercised_by_from, is_test_file, reading_map_from)


# ── diff coverage ──────────────────────────────────────────────────────────
#
# "Coverage on changed files must not decrease" was a gate the agent could
# only declare unmeasurable: the profile named a `coverage_cmd`, nothing ran
# it, and `coverage` in the state was whatever the judgment wrote. Sales
# reported the gate unmeasurable four runs in a row. Measured now, and at a
# finer grain than a percentage — which changed lines no test executed, which
# changed functions were never entered, which tests touch the diff at all.
# coverage.py's dynamic contexts carry the test→line map; pytest-cov's
# `--cov-context=test` writes the same database in node-id form. Both are
# read. Per-test attribution is a lower bound (a tracer may record a line
# under one context and skip it under the next); "executed by any test" is
# exact, and that is what the gate is built on.


COVERAGE_TIMEOUT_S = 1800


RENDER_TIMEOUT_S = 300


TEST_OMIT = ("tests/*", "*/tests/*", "test/*", "*/test/*", "test_*.py", "*/test_*.py",
             "*_test.py", "conftest.py", "*/conftest.py")


_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _changed_lines(repo: Path, sha_range: str) -> dict:
    """Added/modified line numbers per .py file, in new-side numbering."""
    diff = _git(["diff", "-U0", "--no-color", "--diff-filter=AM", sha_range, "--", "*.py"], repo)
    changed: dict = {}
    current = None
    for line in (diff or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            changed.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            m = _HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                changed[current].update(range(start, start + count))
    return {path: lines for path, lines in changed.items() if lines}


def _render_cmd(cmd: str, out: Path) -> str:
    """The `coverage json` invocation that matches how the suite was run — same
    interpreter prefix, so the database is read by the coverage that wrote it."""
    q = ('"' + str(out) + '"') if os.name == "nt" else shlex.quote(str(out))
    tail = f"-m coverage json --show-contexts -q -o {q}"
    if "-m coverage run" in cmd:
        return cmd[:cmd.index("-m coverage run")] + tail
    if "-m pytest" in cmd:
        return cmd[:cmd.index("-m pytest")] + tail
    return f"coverage json --show-contexts -q -o {q}"


def _ranges(lines: list) -> list:
    out: list = []
    for n in lines:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def measure_diff_coverage(repo: Path, sha_range: str | None, cmd: str | None) -> dict:
    """Run the suite under coverage.py and intersect the result with the diff.

    → {"status": "measured", ...} with changed/executed line counts, per-file
    unexercised ranges and never-entered functions, and the tests that touch
    the diff; or {"status": "unavailable", "reason"} — said, never estimated.
    """
    return measure_coverage(repo, sha_range, cmd, [])[0]


def measure_coverage(repo: Path, sha_range: str | None, cmd: str | None,
                     findings, on_files=None) -> tuple[dict, dict | None, dict | None]:
    """One coverage run, three facts: the diff measurement (`coverage`, the
    shape it has always had), the reading map (every production module's
    coverage, ascending, with the findings that cite it — T-16), and the
    verification candidates (for every open finding with anchors, the tests
    whose contexts executed its cited lines — T-18). The suite runs under
    coverage whenever the profile names a command: a baseline and an
    empty-diff delta used to measure nothing, and those are exactly the runs
    that need to know where the least-tested code is."""
    if not cmd:
        return ({"status": "unavailable",
                 "reason": "no coverage_suite_cmd in the profile — set one that runs the suite "
                           "under coverage.py (e.g. `.venv/bin/python -m coverage run -m pytest`) "
                           "to measure which changed lines any test executed; the diff-coverage "
                           "gate reads coverage.py's database only, so on another runner it "
                           "stays unmeasurable and says so"}, None, None)
    changed = _changed_lines(repo, sha_range) if sha_range else {}
    # Scratch, not record. These three used to be written into the QA root,
    # which in team mode IS the committed directory: run 5 of this repository
    # left a 94,987,311-byte coverage.json there, ignored by nothing, one
    # `git add .qa` away from a permanent 95 MB blob in the repository
    # (VERDICT-F-29). Nothing here survives the measurement it feeds.
    scratch = Path(tempfile.mkdtemp(prefix="verdict-coverage-"))
    try:
        files, meta = _run_coverage(repo, scratch, cmd)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if files is None:
        return ({"status": "unavailable", "command": cmd, **meta}, None, None)
    meta["command"] = cmd
    if on_files is not None:
        on_files(files, changed if sha_range else None)
    reading_map = reading_map_from(files, findings, _tracked_python(repo))
    reading_map.update(duration_s=meta.get("duration_s"), suite_exit_code=meta.get("suite_exit_code"))
    exercised = exercised_by_from(files, findings, repo)
    if not sha_range:
        diff = {"status": "unavailable",
                "reason": "no commit range this run (baseline or re-baseline) — diff coverage "
                          "measures the change since the previous run"}
    elif not changed:
        diff = {"status": "measured", "sha_range": sha_range, "changed_files": 0,
                "changed_lines": 0, "changed_lines_executed": 0,
                "note": "no .py lines added or modified in the range"}
    else:
        diff = _diff_from_files(files, changed, meta, sha_range, repo)
    return diff, reading_map, exercised


FACTS_WINDOW_S = 540


GAPS_MIN_S = 60


def inside_agent_call() -> bool:
    """True when this process runs inside a Claude Code session — a tester's Bash call."""
    return bool(os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_ENTRYPOINT"))


PREMEASURED_ENV = "VERDICT_FACTS_PREMEASURED"


PREMEASURED_MAX_AGE_MIN = 180


def _restake_marker(qa_root: Path) -> None:
    """The run marker verdict-run's measurement staked, claimed for this session — the stop
    hook and finalize's bill read the session from it."""
    marker = _read_json(qa_root / "run-in-progress.json") or {}
    marker.update(_session_identity())
    (qa_root / "run-in-progress.json").write_text(json.dumps(marker, indent=2) + "\n", encoding="utf-8")


def _put(facts: dict, **values) -> None:
    """Set each value that says something; an empty one is left out of facts.json."""
    facts.update({k: v for k, v in values.items() if v})


def _coverage_with_gaps(repo: Path, sha_range, cmd, findings, assertion_gaps: dict | None):
    """The coverage run, and on its data the assertion-gap census when the profile asks for it
    (0.91.0): mutants in risk-path functions tests execute, against only the tests that execute
    each line. Opt-in: it costs suite time, never model time."""
    box: dict = {}
    started = time.monotonic()

    def census(files, changed):
        budget = assertion_gaps.get("budget_s") or GAPS_BUDGET_S
        if inside_agent_call():
            # verdict-facts is the tester's first Bash call, and a Bash call ends at 10 minutes:
            # the census takes what is left of a 9-minute window after the coverage run.
            budget = min(budget, max(GAPS_MIN_S, FACTS_WINDOW_S - int(time.monotonic() - started)))
        box["gaps"] = gap_census_of(repo, files, assertion_gaps["test_one_cmd"],
                                    globs=assertion_gaps.get("globs"), changed=changed,
                                    is_test=is_test_file,
                                    test_id=lambda c: _test_id_from_context(c, repo),
                                    budget_s=budget)

    wanted = bool(assertion_gaps and assertion_gaps.get("test_one_cmd"))
    coverage, reading_map, exercised = measure_coverage(repo, sha_range, cmd, findings,
                                                        on_files=census if wanted else None)
    gaps = box.get("gaps")
    if assertion_gaps and not gaps:
        why = ("needs coverage_suite_cmd: the census runs, per line, the tests whose coverage "
               "contexts executed it") if not cmd else (
              "needs test_one_cmd with {id}" if not wanted else "the coverage run produced no data")
        gaps = {"status": "unavailable", "reason": f"assertion_gaps {why}"}
    return coverage, reading_map, exercised, gaps


def _run_coverage(repo: Path, scratch: Path, cmd: str) -> tuple[dict | None, dict]:
    """The suite under coverage.py with dynamic contexts, rendered to JSON →
    (files, meta), or (None, {"reason": …}) when nothing could be measured."""
    rc, db, out = scratch / "coverage.rc", scratch / "coverage.db", scratch / "coverage.json"
    # `ignore_errors` is not indulgence, it is proportion: measuring the suite's
    # children means the children record whatever they run, including files a
    # test generated in a temp directory that is gone before anything renders.
    # `coverage json` aborts on the first source it cannot read, so one such
    # file cost this repository its entire diff-coverage measurement — 63%
    # measured at run 5, `unavailable` at run 6 (VERDICT-F-31). A file whose
    # source cannot be read is a file no line can be attributed to anyway.
    rc.write_text("[run]\ndynamic_context = test_function\nrelative_files = True\n"
                  f"data_file = {db}\n[report]\nignore_errors = True\n"
                  "[json]\nshow_contexts = True\n", encoding="utf-8")
    # A suite that drives its code through child processes measures none of it:
    # coverage traces the process it starts. Run 5 of this repository read 217
    # changed lines of issues.py as "0 executed, not imported by anything the
    # suite executed" while eight tests exercised every one of them through a
    # CLI subprocess (VERDICT-F-28). coverage ships a startup hook that arms any
    # Python child when COVERAGE_PROCESS_START names a config; this gives those
    # children a config of their own whose static `context` is what tells their
    # lines apart from the parent's import-time execution. Nothing is injected
    # into the environment — no PYTHONPATH, no sitecustomize — and the parent's
    # own data is untouched: its lines keep the empty context, as measured.
    # Where coverage ships no such hook the children go unmeasured and the state
    # says `subprocess_coverage: none recorded`, which is a gap, not a claim.
    child_rc = scratch / "child.rc"
    child_rc.write_text(f"[run]\ncontext = {SUBPROCESS_CONTEXT}\nparallel = True\n"
                        "relative_files = True\n", encoding="utf-8")
    extra = {"COVERAGE_RCFILE": str(rc), "COVERAGE_FILE": str(db),
             "COVERAGE_PROCESS_START": str(child_rc)}
    started = time.monotonic()

    def boxed(command, timeout):
        # The suite and its render are target code: they run in the box (`sandbox.py`).
        return sandbox.run(command, cwd=str(repo), shell=True, writable=[repo, scratch],
                           extra_env=extra, timeout=timeout)

    try:
        proc = boxed(cmd, COVERAGE_TIMEOUT_S)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return None, {"reason": f"coverage run did not complete: {type(exc).__name__}"}
    duration = round(time.monotonic() - started, 2)
    render = _render_cmd(cmd, out)
    scope = "all files"
    try:
        rproc = boxed(render, RENDER_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        # A large suite's contexts make the full render slow: freqtrade's exceeded 300 s
        # (2026-10-17) and every coverage fact went with it. The production files alone
        # carry what the reading map, read_first and the assertion-gap census read.
        rc.write_text(rc.read_text(encoding="utf-8").replace(
            "[report]\n", "[report]\nomit = " + ", ".join(TEST_OMIT) + "\n", 1), encoding="utf-8")
        scope = f"production files only (the full render exceeded {RENDER_TIMEOUT_S} s)"
        try:
            rproc = boxed(render, COVERAGE_TIMEOUT_S // 2)
        except (subprocess.TimeoutExpired, OSError) as exc:
            rproc, rendered_err = None, type(exc).__name__
        else:
            rendered_err = _summary_line(rproc.stdout + rproc.stderr)
    except OSError as exc:
        rproc = None
        rendered_err = type(exc).__name__
    else:
        rendered_err = _summary_line(rproc.stdout + rproc.stderr)
    meta = {"render_command": render, "suite_exit_code": proc.returncode, "duration_s": duration,
            **({"render_scope": scope} if scope != "all files" else {})}
    if rproc is None or rproc.returncode != 0 or not out.is_file():
        return None, {**meta, "reason": "the suite ran but the coverage database could not be "
                                        "rendered: " + rendered_err}
    try:
        files = (json.loads(out.read_text(encoding="utf-8")) or {}).get("files") or {}
    except (OSError, json.JSONDecodeError) as exc:
        return None, {**meta, "reason": f"coverage.json unreadable: {exc}"}
    return files, meta


def _diff_from_files(files: dict, changed: dict, meta: dict, sha_range: str,
                     repo: Path) -> dict:
    """The changed lines of the range against what the suite executed."""
    cmd, proc_rc, duration = meta.get("command"), meta.get("suite_exit_code"), meta.get("duration_s")
    per_file: dict = {}
    total_measured = total_executed = total_in_child = 0
    split = {"production": [0, 0], "tests": [0, 0]}   # [measured, executed]
    touching: set = set()
    never_entered: list = []
    production_only = bool(meta.get("render_scope"))
    for path, lines in changed.items():
        f = files.get(path) or files.get(path.replace("/", "\\"))
        if not f and production_only and is_test_file(path):
            per_file[path] = {"changed": len(lines), "measured": 0, "executed": 0,
                              "note": "a test file, left out of a production-only render"}
            continue
        if not f:
            # coverage reports the files it saw. A changed .py file it never
            # saw was imported by nothing the suite ran — every changed line
            # in it is unexercised, and that is the honest count.
            per_file[path] = {"changed": len(lines), "measured": len(lines), "executed": 0,
                              "unexercised_ranges": _ranges(sorted(lines)), "tests": [],
                              "note": "no test executed it, and no subprocess the suite "
                                      "spawned recorded a line of it"}
            total_measured += len(lines)
            split["tests" if is_test_file(path) else "production"][0] += len(lines)
            continue
        ctx = f.get("contexts") or {}
        ran = lines & set(f.get("executed_lines") or [])
        # Executed *by a test*. A `def` line runs at import under the empty
        # context and proves nothing about the function it defines; counting it
        # let a brand-new, never-called function read as partly exercised and
        # kept the zero-exercised refusal from ever firing.
        executed = {ln for ln in ran if any(c for c in ctx.get(str(ln), []))}
        # A child process the suite spawned carries its own static context, so
        # its lines are non-empty above and count. Which of them ONLY a child
        # reached is worth saying: they have no test to name.
        in_test = {ln for ln in ran
                   if any(c for c in ctx.get(str(ln), []) if c != SUBPROCESS_CONTEXT)}
        only_child = {ln for ln in ran
                      if SUBPROCESS_CONTEXT in (ctx.get(str(ln)) or [])} - in_test
        missing = (lines & set(f.get("missing_lines") or [])) | (ran - executed)
        tests = {t for ln in executed for c in ctx.get(str(ln), [])
                 if c != SUBPROCESS_CONTEXT
                 for t in [_test_id_from_context(c, repo)] if t}
        fns = [name for name, fb in (f.get("functions") or {}).items()
               if name and not fb.get("executed_lines")
               and (set(fb.get("missing_lines") or []) & lines)]
        per_file[path] = {"changed": len(lines), "measured": len(executed) + len(missing),
                          "executed": len(executed),
                          **({"executed_in_subprocess": len(only_child)} if only_child else {}),
                          "unexercised_ranges": _ranges(sorted(missing)),
                          "tests": sorted(tests)[:10],
                          "unexercised_functions": fns[:10]}
        total_measured += len(executed) + len(missing)
        total_executed += len(executed)
        total_in_child += len(only_child)
        bucket = split["tests" if is_test_file(path) else "production"]
        bucket[0] += len(executed) + len(missing)
        bucket[1] += len(executed)
        touching |= tests
        never_entered += [f"{path}:{name}" for name in fns]
    return {"status": "measured", "tool": "coverage.py dynamic contexts", "command": cmd,
            "sha_range": sha_range, "suite_exit_code": proc_rc, "duration_s": duration,
            "changed_files": len(changed), "changed_lines": total_measured,
            "changed_lines_executed": total_executed,
            "changed_lines_executed_in_subprocess": total_in_child,
            "subprocess_coverage": "measured" if total_in_child else "none recorded",
            # Read production first. The blended number above is kept because
            # it is what the schema has always carried, but it is the one that
            # moves with composition rather than coverage.
            "by_kind": {kind: {"changed_lines": m, "changed_lines_executed": e,
                               "percent": (round(100 * e / m) if m else None)}
                        for kind, (m, e) in split.items()},
            "percent": (round(100 * total_executed / total_measured) if total_measured else None),
            "per_file": per_file, "tests_touching_diff": sorted(touching)[:50],
            "unexercised_functions": never_entered[:20]}
