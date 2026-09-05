"""Tests for the session-start memory hook.

It exists because of a measured failure: Verdict filed eleven evidenced
findings on a live site, one a release blocker, and the very next session in
that repository did a full SEO pass and touched none of them. The findings were
in `state.json` the whole time; nothing put them on screen.

So the tests come in two halves. That it *says the useful thing* — the blocker
first, the counts, no repetition. And that it stays quiet everywhere else,
because this runs at the start of every session in every repo the plugin sees.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "report_open_findings.py"


def fire(cwd, home=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    if home:
        env["VERDICT_HOME"] = str(home)
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps({"cwd": str(cwd)}),
                          # The hook writes UTF-8 by contract; decoding with the
                          # locale codepage would turn its dashes into mojibake
                          # on Windows only, and an assertion on them would lie.
                          capture_output=True, text=True, encoding="utf-8", env=env)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "Widget"
    r.mkdir()
    subprocess.run(["git", "init", "-qb", "main"], cwd=r, check=True, capture_output=True)
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "first"], cwd=r, check=True, capture_output=True)
    return r


def plant(tmp_path, **over):
    root = tmp_path / "home" / "widget"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {
        "project": "widget", "schema_version": 1, "run_type": "delta", "run_number": 4,
        "last_run": {"timestamp_utc": stamp, "report": "reports/r.md"},
        "isolation_check": {}, "gates": {}, "verdict": "fail",
        "release_blockers": ["W-F-1 — the signer drops the nonce"],
        "not_tested": ["x"], "next_run_focus": ["re-check the signer"],
        "findings": [
            {"id": "W-F-1", "hash": "a", "status": "open", "delta": "STILL_OPEN",
             "severity": "Critical", "age_days": 5, "title": "the signer drops the nonce",
             "evidence": ["s.py:1"]},
            {"id": "W-F-2", "hash": "b", "status": "open", "delta": "STILL_OPEN",
             "severity": "Major", "age_days": 2, "title": "retry loop never terminates",
             "evidence": ["r.py:1"]},
            {"id": "W-F-3", "hash": "c", "status": "resolved", "delta": "RESOLVED",
             "severity": "Major", "age_days": 9, "title": "already fixed",
             "evidence": ["x.py:1"]},
        ],
    }
    state.update(over)
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return root.parent


# ── it says the useful thing ──────────────────────────────────────────────

def test_the_blocker_comes_first_and_the_counts_follow(tmp_path, repo):
    out = fire(repo, home=plant(tmp_path)).stdout
    assert "verdict **fail**" in out
    lines = out.splitlines()
    assert "release blocker" in lines[1], "the blocker leads; everything else is context"
    assert "the signer drops the nonce" in lines[2]
    assert "2 open findings" in out and "1 Critical" in out and "1 Major" in out
    assert "oldest 5d" in out
    assert "re-check the signer" in out


def test_a_finding_already_named_as_a_blocker_is_not_repeated(tmp_path, repo):
    """A session opener that says the same thing twice is one nobody finishes."""
    out = fire(repo, home=plant(tmp_path)).stdout
    assert out.count("W-F-1") == 1
    assert "W-F-2" in out, "the other open findings are still listed"


def test_resolved_findings_are_not_reported_as_outstanding(tmp_path, repo):
    out = fire(repo, home=plant(tmp_path)).stdout
    assert "W-F-3" not in out and "already fixed" not in out


def test_a_clean_project_says_so_in_one_line(tmp_path, repo):
    home = plant(tmp_path, verdict="pass", release_blockers=[], findings=[],
                 next_run_focus=[])
    out = fire(repo, home=home).stdout
    assert "Nothing open" in out and len(out.splitlines()) == 2


def test_stale_memory_is_flagged_rather_than_served_as_current(tmp_path, repo):
    home = plant(tmp_path, last_run={"timestamp_utc": "2026-01-01T00:00:00Z",
                                     "report": "reports/r.md"})
    out = fire(repo, home=home).stdout
    assert "days old" in out and "/verdict:run" in out


def test_findings_are_offered_as_findings_not_as_orders(tmp_path, repo):
    """The hook informs a session; it does not commandeer it."""
    out = fire(repo, home=plant(tmp_path)).stdout
    assert "findings, not instructions" in out


# ── and stays quiet everywhere else ───────────────────────────────────────

def test_a_repo_with_no_qa_state_prints_nothing(tmp_path, repo):
    proc = fire(repo, home=tmp_path / "empty")
    assert proc.returncode == 0 and proc.stdout == ""


def test_a_state_with_no_verdict_prints_nothing(tmp_path, repo):
    home = plant(tmp_path)
    (home / "widget" / "state.json").write_text(json.dumps({"project": "widget"}),
                                                encoding="utf-8")
    assert fire(repo, home=home).stdout == ""


def test_every_broken_input_fails_open(tmp_path):
    for payload in ("not json", "", "[]", "null", '{"cwd": null}',
                    '{"cwd": "/nonexistent/nowhere"}'):
        proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                              capture_output=True, text=True)
        assert proc.returncode == 0, payload
        assert proc.stdout == "", payload


def test_a_team_mode_root_in_the_tree_is_found(tmp_path, repo):
    root = repo / ".qa"
    (root / "reports").mkdir(parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "run_number": 1, "run_type": "baseline",
        "last_run": {"timestamp_utc": stamp}, "verdict": "blocked",
        "release_blockers": [], "findings": []}), encoding="utf-8")
    assert "verdict **blocked**" in fire(repo, home=tmp_path / "empty").stdout
