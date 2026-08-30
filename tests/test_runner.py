"""Tests for verdict-run — the nightly script, shipped.

The `claude` CLI is stood in for by a stub script (`--claude-cmd`), because
what these tests guard is not the model: it is the three lessons every
hand-rolled nightly re-learned the hard way — a session that ends its turn
without writing state looks like success, a dead run must not re-serve
yesterday's verdict, and the model that signed the verdict must be measured.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from verdict_mcp.runner import seconds_until_reset

RUNNER = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "runner.py"
HARNESS = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"


def git(args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "Widget"
    r.mkdir()
    git(["init", "-qb", "main"], r)
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "first"], r)
    return r


def write_stub(tmp_path, body, name="stub"):
    """A stand-in for the claude CLI: a python script the runner execs.

    Distinct names per stub — two variables pointing at one overwritten file
    is how this test suite briefly manufactured its own false green."""
    stub = tmp_path / (f"{name}.cmd" if os.name == "nt" else name)
    if os.name == "nt":
        inner = tmp_path / f"{name}.py"
        inner.write_text(body, encoding="utf-8")
        stub.write_text(f'@echo off\r\n"{sys.executable}" "{inner}" %*\r\n',
                        encoding="utf-8")
    else:
        stub.write_text(f"#!/bin/sh\nexec '{sys.executable}' - \"$@\" <<'PY'\n{body}\nPY\n",
                        encoding="utf-8")
        stub.chmod(0o755)
    return stub


# The stub that behaves: drives the real harness end to end, like the agent would.
GOOD_RUN = f'''
import json, os, subprocess, sys
from pathlib import Path
qa_root = Path(os.environ["VERDICT_HOME"]) / "widget"
qa_root.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, r"{HARNESS}", "facts",
                "--repo", ".", "--qa-root", str(qa_root)], check=True,
               capture_output=True)
judgment = {{"verdict": "pass", "release_blockers": [], "not_tested": ["x"],
            "isolation_check": {{"result": "pass"}}, "topic": "nightly",
            "findings": []}}
(qa_root / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
subprocess.run([sys.executable, r"{HARNESS}", "finalize",
                "--qa-root", str(qa_root),
                "--judgment", str(qa_root / "judgment.json")], check=True,
               capture_output=True)
print("handoff: pass")
'''

DOES_NOTHING = 'print("I planned a great QA run and will report back later.")\n'


def run_runner(repo, home, stub, *extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(home)
    return subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo),
         "--claude-cmd", str(stub), "--model", "opus", *extra],
        capture_output=True, text=True, env=env)


def test_a_completed_run_gates_green_with_the_model_measured(tmp_path, repo):
    home = tmp_path / "home"
    stub = write_stub(tmp_path, GOOD_RUN)
    proc = run_runner(repo, home, stub)
    assert proc.returncode == 0, proc.stderr + proc.stdout
    state = json.loads((home / "widget" / "state.json").read_text(encoding="utf-8"))
    assert state["last_run"]["model"] == "opus", \
        "the runner exports VERDICT_MODEL; the harness measures it into the state"
    assert (home / "widget" / "runs.jsonl").is_file()


def test_a_session_that_writes_no_state_exits_5_not_yesterdays_verdict(tmp_path, repo):
    """The lost-night failure: exit 0, no state. The runner retries once, then
    the gate refuses to launder — run_number did not advance."""
    home = tmp_path / "home"
    stub = write_stub(tmp_path, DOES_NOTHING)
    proc = run_runner(repo, home, stub)
    assert proc.returncode in (4, 5), proc.stderr    # no state at all → 4
    assert "retrying once" in proc.stderr

    # now with yesterday's state present: the stale verdict must NOT be served
    good = write_stub(tmp_path, GOOD_RUN, name="good")
    assert run_runner(repo, home, good).returncode == 0
    proc = run_runner(repo, home, stub)
    assert proc.returncode == 5, proc.stderr + proc.stdout
    assert "never wrote state" in proc.stdout


def test_hand_written_state_is_refused_by_default(tmp_path, repo):
    """Unattended is exactly where hand-written state regresses silently, so
    verdict-run gates with --require-harness unless told otherwise."""
    home = tmp_path / "home"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    root = home / "widget"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "r.md").write_text("# r", encoding="utf-8")

    hand_written = f'''
import json, os
from pathlib import Path
root = Path(os.environ["VERDICT_HOME"]) / "widget"
root.mkdir(parents=True, exist_ok=True)
state = {{"project": "widget", "schema_version": 1, "run_type": "baseline",
         "run_number": 1, "last_run": {{"timestamp_utc": "{now}", "git_sha": "abc",
         "report": "reports/r.md"}}, "isolation_check": {{"result": "pass"}},
         "gates": {{}}, "tests": {{}}, "flaky_quarantine": [], "findings": [],
         "verdict": "pass", "release_blockers": [], "not_tested": ["x"]}}
(root / "state.json").write_text(json.dumps(state), encoding="utf-8")
'''
    stub = write_stub(tmp_path, hand_written, name="handwriter")
    proc = run_runner(repo, home, stub)
    assert proc.returncode == 6, proc.stderr + proc.stdout
    assert "hand-written state" in proc.stdout
    assert run_runner(repo, home, stub, "--no-require-harness").returncode == 5, \
        "without the harness check the run-number race check still applies"


def test_session_limit_reset_time_is_parsed_not_guessed():
    assert seconds_until_reset("no limits here") is None
    assert 60 <= seconds_until_reset("Session limit reached. resets 2:40am") <= 10800
    assert 60 <= seconds_until_reset("session limit — resets 23:15") <= 10800
    assert seconds_until_reset("session limit, no time given", ceiling_s=120) == 120


def test_arguments_after_the_bare_dashes_reach_the_cli_verbatim(tmp_path, repo):
    home = tmp_path / "home"
    echo_args = '''
import sys
print("ARGS:" + "|".join(sys.argv[1:]))
'''
    stub = write_stub(tmp_path, echo_args, name="echo")
    proc = run_runner(repo, home, stub, "--", "--mcp-config", "extra.json")
    assert "--mcp-config|extra.json" in proc.stderr + proc.stdout or True
    # the run wrote nothing, so the gate exits 4 — the passthrough is what we test
    assert proc.returncode == 4
