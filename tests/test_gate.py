"""Tests for verdict-gate, run exactly the way the Action's gate mode runs it:
as a bare script with zero installs."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "gate.py"

BASE_STATE = {
    "project": "pricer", "schema_version": 1, "run_type": "delta", "run_number": 4,
    "last_run": {"timestamp_utc": "2026-08-24T17:30:00Z", "git_sha": "b4e2943",
                 "sha_range": "2c67f47..b4e2943",
                 "report": "reports/2026-08-24-payment-retry.md"},
    "isolation_check": {"result": "pass"},
    "gates": {}, "tests": {"collected": 1, "passed": 1, "skipped": 0, "failed": 0},
    "flaky_quarantine": [],
    "findings": [
        {"id": "PRC-F-2", "hash": "b", "first_seen": "2026-08-19", "status": "open",
         "delta": "REGRESSED", "age_days": 5, "title": "banker's rounding is back",
         "severity": "Critical", "priority": "P0",
         "failure_classification": "REAL_DEFECT", "evidence": []},
        {"id": "PRC-F-9", "hash": "c", "first_seen": "2026-08-24", "status": "open",
         "delta": "NEW", "age_days": 0, "title": "minor nit | with a pipe",
         "severity": "Minor", "priority": "P3",
         "failure_classification": None, "evidence": []},
    ],
    "verdict": "fail", "release_blockers": ["PRC-F-2"],
    "not_tested": ["concurrency"],
}


def make_home(tmp_path, **overrides):
    state = {**BASE_STATE, **overrides}
    root = tmp_path / "home" / "pricer"
    (root / "reports").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps(state))
    return tmp_path / "home"


def gate(tmp_path, *args, home=None, cwd=None, state_kwargs=None):
    home = home or make_home(tmp_path, **(state_kwargs or {}))
    proc = subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True, text=True, cwd=cwd,
        env={"PATH": "/usr/bin:/bin", "VERDICT_HOME": str(home)},
    )
    return proc


def test_fail_exits_1(tmp_path):
    proc = gate(tmp_path, "pricer")
    assert proc.returncode == 1
    assert "VERDICT: fail" in proc.stdout


def test_pass_exits_0(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs={"verdict": "pass", "release_blockers": []})
    assert proc.returncode == 0


def test_pass_with_risks_default_accepts(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs={"verdict": "pass with risks"})
    assert proc.returncode == 0
    assert "accepted" in proc.stdout


def test_pass_with_risks_fails_under_fail_on_risks(tmp_path):
    proc = gate(tmp_path, "pricer", "--fail-on", "risks",
                state_kwargs={"verdict": "pass with risks"})
    assert proc.returncode == 1


def test_blocked_exits_3(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs={"verdict": "blocked"})
    assert proc.returncode == 3


def test_no_state_exits_4(tmp_path):
    proc = gate(tmp_path, "nope")
    assert proc.returncode == 4
    assert "no Verdict state" in proc.stdout


def test_corrupt_state_exits_4(tmp_path):
    home = make_home(tmp_path)
    (home / "pricer" / "state.json").write_text("{broken")
    proc = gate(tmp_path, "pricer", home=home)
    assert proc.returncode == 4


def test_min_run_number_exits_5(tmp_path):
    proc = gate(tmp_path, "pricer", "--min-run-number", "5")
    assert proc.returncode == 5
    assert "stale" in proc.stdout


def test_max_age_exits_5(tmp_path):
    proc = gate(tmp_path, "pricer", "--max-age-hours", "1")
    assert proc.returncode == 5


def test_stale_check_outranks_a_passing_verdict(tmp_path):
    proc = gate(tmp_path, "pricer", "--min-run-number", "5",
                state_kwargs={"verdict": "pass", "release_blockers": []})
    assert proc.returncode == 5


def test_github_output_format(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "github-output")
    assert "verdict=fail" in proc.stdout
    assert "exit-code=1" in proc.stdout
    assert 'blockers=["PRC-F-2"]' in proc.stdout


def test_github_comment_marker_and_ordering(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "github-comment")
    out = proc.stdout
    assert out.startswith("<!-- verdict-gate -->")
    assert out.index("REGRESSED") < out.index("NEW")
    assert "\\|" in out  # pipe in a title is escaped, not table-breaking


def test_json_format(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "json")
    data = json.loads(proc.stdout)
    assert data["exit_code"] == 1 and data["verdict"] == "fail"
    assert data["findings_open"][0]["id"] == "PRC-F-2"


def test_default_resolution_prefers_team_qa(tmp_path):
    repo = tmp_path / "myapp"
    (repo / ".qa" / "reports").mkdir(parents=True)
    (repo / ".qa" / "state.json").write_text(
        json.dumps({**BASE_STATE, "project": "myapp", "verdict": "pass",
                    "release_blockers": []}))
    home = tmp_path / "empty-home"
    home.mkdir()
    proc = gate(tmp_path, home=home, cwd=repo)
    assert proc.returncode == 0
    assert "team-mode" in json.loads(gate(tmp_path, "--format", "json",
                                          home=home, cwd=repo).stdout)["resolved_via"]
