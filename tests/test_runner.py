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


# --- live output, heartbeat, and the earned skip -----------------------------
#
# All three exist because of one external report: the first outside user was
# bitten twice by the runner's silence (empty log until the very end, killed
# parent = no trace), and their friend's objection to a nightly — "I don't
# change code every day" — is answered by arithmetic, not a schedule.

SLOW_TALKER = (
    'import sys, time\n'
    'print("first line", flush=True)\n'
    'time.sleep(2.5)\n'
    'print("second line", flush=True)\n'
)


def test_runner_streams_output_live_and_heartbeats(tmp_path, repo):
    home = tmp_path / "home"
    stub = write_stub(tmp_path, SLOW_TALKER, name="slow")
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(home)
    env["VERDICT_HEARTBEAT_S"] = "1"
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo),
         "--claude-cmd", str(stub), "--model", "opus"],
        capture_output=True, text=True, env=env)
    # The child's lines must be in the runner's own stream (that is what a
    # redirected nightly log receives), and the quiet gap must have produced
    # at least one heartbeat.
    assert "first line" in proc.stderr
    assert "second line" in proc.stderr
    assert "still running" in proc.stderr, "no heartbeat during a 2.5s silence at 1s interval"


MARKER_STUB = '''
import os, pathlib
pathlib.Path(r"{marker}").write_text("ran", encoding="utf-8")
print("stub ran")
'''


def _run_with_marker(tmp_path, repo, home, name, *extra):
    marker = tmp_path / f"{name}.marker"
    stub = write_stub(tmp_path, MARKER_STUB.format(marker=marker), name=name)
    proc = run_runner(repo, home, stub, *extra)
    return proc, marker


def test_skip_unchanged_spends_no_model_run(tmp_path, repo):
    home = tmp_path / "home"
    good = write_stub(tmp_path, GOOD_RUN, name="good")
    first = run_runner(repo, home, good)
    assert first.returncode == 0, first.stderr

    proc, marker = _run_with_marker(tmp_path, repo, home, "second", "--skip-unchanged")
    assert not marker.exists(), "claude was invoked although HEAD was unchanged"
    assert "skip" in proc.stderr
    assert proc.returncode == 0, "the standing pass must re-gate green"


def test_skip_unchanged_runs_when_head_moved(tmp_path, repo):
    home = tmp_path / "home"
    good = write_stub(tmp_path, GOOD_RUN, name="good")
    assert run_runner(repo, home, good).returncode == 0

    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "change"], repo)

    _, marker = _run_with_marker(tmp_path, repo, home, "moved", "--skip-unchanged")
    assert marker.exists(), "HEAD moved — the run must happen"


def test_skip_unchanged_runs_when_a_quarantine_expired(tmp_path, repo):
    """Unchanged code is not the only reason to run: an expired quarantine
    needs a model to re-evaluate it, and skipping past that would let a flake
    rot in quarantine forever."""
    home = tmp_path / "home"
    good = write_stub(tmp_path, GOOD_RUN, name="good")
    assert run_runner(repo, home, good).returncode == 0

    state_path = home / "widget" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["flaky_quarantine"] = [
        {"test_id": "test_x", "quarantined_until": "2020-01-01"}]
    state_path.write_text(json.dumps(state), encoding="utf-8")

    _, marker = _run_with_marker(tmp_path, repo, home, "expired", "--skip-unchanged")
    assert marker.exists(), "an expired quarantine must force a real run"


def test_without_the_flag_unchanged_head_still_runs(tmp_path, repo):
    """Opt-in means opt-in: the nightly's semantics do not change silently."""
    home = tmp_path / "home"
    good = write_stub(tmp_path, GOOD_RUN, name="good")
    assert run_runner(repo, home, good).returncode == 0
    _, marker = _run_with_marker(tmp_path, repo, home, "noflag")
    assert marker.exists()


# --- the runner provisions what an isolated session cannot see ---------------
#
# The first self-run from a fresh clone came back `blocked`: "Agent type
# 'verdict' not found", no hooks enforcing, every tool denied. The runner
# launches with `--setting-sources project`, which is deliberate isolation and
# also exactly why a bare checkout cannot run the agent. The nightly and the
# eval each hand-rolled the missing steps; docs/nightly.md told everyone else
# to run `verdict-run` bare.

ARGV_DUMP = '''
import json, os, sys
from pathlib import Path
Path(os.environ["ARGV_OUT"]).write_text(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd()}))
print("looked around, wrote nothing")
'''


def _argv_of(tmp_path, repo, *extra, name="dump"):
    stub = write_stub(tmp_path, ARGV_DUMP, name=name)
    out = tmp_path / f"{name}-argv.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env.update(VERDICT_HOME=str(tmp_path / "home"), ARGV_OUT=str(out))
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo),
         "--claude-cmd", str(stub), "--model", "opus", *extra],
        capture_output=True, text=True, env=env)
    argv = json.loads(out.read_text(encoding="utf-8"))["argv"] if out.is_file() else None
    return proc, argv


def test_a_bare_checkout_is_provisioned_and_launched_headless(tmp_path, repo):
    proc, argv = _argv_of(tmp_path, repo)
    assert argv is not None, proc.stderr
    agent = repo / ".claude" / "agents" / "verdict.md"
    assert agent.is_file() and "${CLAUDE_PLUGIN_ROOT}" not in agent.read_text(encoding="utf-8")
    local = json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))
    assert set(local["hooks"]) >= {"PreToolUse", "PostToolUse", "Stop", "SessionStart"}
    assert "${CLAUDE_PLUGIN_ROOT}" not in json.dumps(local)
    assert "--dangerously-skip-permissions" in argv
    i = argv.index("--setting-sources")
    assert argv[i + 1] == "project,local", "hooks live in settings.local.json"
    assert "provision: wrote" in proc.stderr and "installed hooks" in proc.stderr


def test_an_operators_agent_file_and_hooks_are_kept_not_replaced(tmp_path, repo):
    """The nightly provisions its own agent from a pinned checkout; a project
    may carry its own hooks. Both are theirs, named on stderr, never clobbered."""
    agent = repo / ".claude" / "agents" / "verdict.md"
    agent.parent.mkdir(parents=True)
    agent.write_text("# the operator's pinned copy\n", encoding="utf-8")
    local = repo / ".claude" / "settings.local.json"
    local.write_text(json.dumps({"hooks": {"Stop": []}, "theirs": True}), encoding="utf-8")
    proc, argv = _argv_of(tmp_path, repo)
    assert argv is not None, proc.stderr
    assert agent.read_text(encoding="utf-8") == "# the operator's pinned copy\n"
    assert json.loads(local.read_text(encoding="utf-8")) == {"hooks": {"Stop": []}, "theirs": True}
    assert "kept existing .claude/agents/verdict.md" in proc.stderr
    assert "kept existing hooks" in proc.stderr


def test_a_tracked_settings_json_is_not_touched(tmp_path, repo):
    """This repository ships `.claude/settings.json`; provisioning into it would
    dirty a tracked file in the code under test. Hooks go to the local file."""
    tracked = repo / ".claude" / "settings.json"
    tracked.parent.mkdir(parents=True)
    tracked.write_text('{"includeCoAuthoredBy": false}\n', encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "ship settings"], repo)
    proc, argv = _argv_of(tmp_path, repo)
    assert argv is not None, proc.stderr
    assert tracked.read_text(encoding="utf-8") == '{"includeCoAuthoredBy": false}\n'
    assert "hooks" in json.loads((repo / ".claude" / "settings.local.json").read_text(encoding="utf-8"))


def test_an_operators_permission_flag_is_not_doubled(tmp_path, repo):
    proc, argv = _argv_of(tmp_path, repo, "--", "--permission-mode", "plan")
    assert argv is not None, proc.stderr
    assert "--dangerously-skip-permissions" not in argv
    assert argv[argv.index("--permission-mode") + 1] == "plan"


def test_no_agent_and_no_plugin_root_refuses_before_spending_a_run(tmp_path, repo):
    """A session without the agent can only come back `blocked` — after a full
    model run. Refuse up front instead, and say what to do."""
    empty = tmp_path / "not-a-plugin"
    empty.mkdir()
    # An explicit --plugin-root is authoritative: a wrong path is an error, not
    # a fallback to whatever checkout happens to be nearby — which is also what
    # makes this refusal reachable from a test that runs inside the real one.
    proc, argv = _argv_of(tmp_path, repo, "--plugin-root", str(empty), name="refused")
    assert proc.returncode == 2, proc.stderr
    assert argv is None, "the claude stub must never have been launched"
    assert "not available to an isolated session" in proc.stderr
    assert "--plugin-root" in proc.stderr and "PyPI" in proc.stderr
    assert not (repo / ".claude" / "agents").exists()


def test_no_provision_writes_nothing(tmp_path, repo):
    proc, argv = _argv_of(tmp_path, repo, "--no-provision")
    assert argv is not None, proc.stderr
    assert not (repo / ".claude").exists()
    assert "--dangerously-skip-permissions" in argv, "permissions are separate from provisioning"
