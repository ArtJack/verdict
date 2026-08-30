"""Tests for the run-contract stop hook.

Its job is enforcement that does not depend on the model remembering anything.
Its risk is that it runs at the end of every turn in every session where the
plugin is enabled — so most of what follows tests **silence**: a hook that
speaks when it should not is worse than the hole it fills, and one that bricks a
session is worse still.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "enforce_run_contract.py"


def fire(event, home=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    if home:
        env["VERDICT_HOME"] = str(home)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                          capture_output=True, text=True, env=env)


def qa_root(tmp_path, *, harnessed: bool, fresh: bool = True, name="widget"):
    """A QA root holding a state written either by the harness or by hand."""
    root = tmp_path / "home" / name
    (root / "reports").mkdir(parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {
        "project": name, "schema_version": 1, "run_type": "baseline", "run_number": 1,
        "last_run": {"timestamp_utc": stamp, "git_sha": "abc", "report": "reports/r.md"},
        "isolation_check": {"result": "pass"}, "gates": {}, "tests": {},
        "flaky_quarantine": [], "findings": [], "verdict": "pass",
        "release_blockers": [], "not_tested": ["nothing"],
    }
    footer = ("*Countable sections rendered from `state.json` by `verdict-finalize`; "
              "the prose is the agent's.*")
    if harnessed:
        state["calibration"] = {"decided_outcomes": 0}
        (root / "facts.json").write_text(json.dumps({"measured_at": stamp}), encoding="utf-8")
        (root / "judgment.json").write_text("{}", encoding="utf-8")
        (root / "reports" / "r.md").write_text(f"# report\n\n{footer}\n", encoding="utf-8")
    else:
        (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    if not fresh:
        # Old by its *own* record — the file may have been touched a second ago
        # by a checkout, which is precisely the case that fooled version one.
        stale = dict(state, last_run=dict(state["last_run"],
                                          timestamp_utc="2026-08-01T12:00:00Z"))
        (root / "state.json").write_text(json.dumps(stale), encoding="utf-8")
    return root


@pytest.fixture()
def repo(tmp_path):
    """A git repo whose §0 key is `widget`, matching the QA root above."""
    r = tmp_path / "Widget"
    r.mkdir()
    for args in (["init", "-qb", "main"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "first"], cwd=r, check=True, capture_output=True)
    return r


# ── the one case it exists for ────────────────────────────────────────────

def test_hand_written_state_written_this_turn_blocks_the_stop(tmp_path, repo):
    """The demonstrated failure: a run composed its state instead of measuring
    it, and every downstream guard stayed silent because nothing invoked them."""
    home = qa_root(tmp_path, harnessed=False).parent
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 2
    assert "without going through the harness" in proc.stderr
    assert "verdict-facts" in proc.stderr and "§6" in proc.stderr


# ── everything else must be silent ────────────────────────────────────────

def test_a_harness_written_state_says_nothing(tmp_path, repo):
    home = qa_root(tmp_path, harnessed=True).parent
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_an_old_state_in_an_ordinary_coding_session_says_nothing(tmp_path, repo):
    """The common case by far: a project has a QA baseline from last night and
    the session is doing something else entirely."""
    home = qa_root(tmp_path, harnessed=False, fresh=False).parent
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_a_project_with_no_qa_root_says_nothing(tmp_path, repo):
    proc = fire({"cwd": str(repo)}, home=tmp_path / "empty")
    assert proc.returncode == 0 and proc.stderr == ""


def test_it_never_blocks_twice(tmp_path, repo):
    """Blocking a stop sends the agent back to work; blocking the *next* stop
    for the same reason is a loop, which is worse than a miss."""
    home = qa_root(tmp_path, harnessed=False).parent
    proc = fire({"cwd": str(repo), "stop_hook_active": True}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_a_freshly_checked_out_repo_says_nothing(tmp_path, repo):
    """This repo's own CI caught the first version of this hook firing on
    Verdict's committed team-mode `.qa/`: `git checkout` stamps every file with
    the current time, so mtime is not evidence that a run happened. Recency now
    comes from the timestamp the run itself recorded, which copying cannot
    forge."""
    root = repo / ".qa"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "schema_version": 1, "run_type": "baseline", "run_number": 1,
        "last_run": {"timestamp_utc": "2026-08-01T12:00:00Z", "report": "reports/r.md"},
        "isolation_check": {}, "gates": {}, "findings": [], "verdict": "pass",
        "release_blockers": [], "not_tested": ["x"]}), encoding="utf-8")
    os.utime(root / "state.json", None)          # as a fresh checkout leaves it
    proc = fire({"cwd": str(repo)}, home=tmp_path / "empty")
    assert proc.returncode == 0 and proc.stderr == ""


def test_a_state_with_no_usable_run_time_says_nothing(tmp_path, repo):
    home = tmp_path / "home"
    root = home / "widget"
    (root / "reports").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({"project": "widget", "last_run": {}}),
                                     encoding="utf-8")
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_every_broken_input_fails_open(tmp_path):
    """A hook that bricks sessions is worse than the problem it polices."""
    for payload in ("not json", "", "[]", "null", '{"cwd": null}',
                    '{"cwd": "/nonexistent/nowhere"}'):
        proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                              capture_output=True, text=True)
        assert proc.returncode == 0, payload
        assert proc.stderr == "", payload


def test_a_team_mode_qa_root_inside_the_repo_is_found(tmp_path, repo):
    """Team mode keeps the QA root in the tree; the hook must see it there too."""
    root = repo / ".qa"
    (root / "reports").mkdir(parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "schema_version": 1, "run_type": "baseline", "run_number": 1,
        "last_run": {"timestamp_utc": stamp, "report": "reports/r.md"},
        "isolation_check": {}, "gates": {}, "findings": [], "verdict": "pass",
        "release_blockers": [], "not_tested": ["x"]}), encoding="utf-8")
    proc = fire({"cwd": str(repo)}, home=tmp_path / "empty")
    assert proc.returncode == 2 and "without going through the harness" in proc.stderr
