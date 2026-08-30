"""A stored verdict ages by commits, not only by hours.

This file exists because of a measured failure on this repository. Its own
`.qa/state.json`, four hours old, named three open Major findings — all three
fixed and merged in the six commits since. Nothing was corrupt; only a run
resolves findings. But every consumer read the state as current, because the
only staleness signal in the product was a seven-day clock and the state was
not old. It was behind. These tests hold the distinction.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"))
from state import code_drift  # noqa: E402

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "report_open_findings.py"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    """A scratch repo with three commits on main and a diverged branch."""
    r = tmp_path / "repo"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.com")
    git(r, "config", "user.name", "t")
    shas = []
    for i in range(3):
        (r / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        git(r, "add", "-A")
        git(r, "commit", "-qm", f"c{i}")
        shas.append(git(r, "rev-parse", "HEAD"))
    return r, shas


def test_head_is_current(repo):
    r, shas = repo
    d = code_drift(r, shas[-1])
    assert d["status"] == "current" and d["commits"] == 0


def test_counts_commits_behind(repo):
    r, shas = repo
    assert code_drift(r, shas[0])["commits"] == 2
    assert code_drift(r, shas[0])["status"] == "behind"
    assert code_drift(r, shas[1])["commits"] == 1


def test_diverged_branch_is_not_reported_as_behind(repo):
    """The dangerous case: a verdict measured on code this branch never had."""
    r, shas = repo
    git(r, "checkout", "-q", "-b", "side", shas[0])
    (r / "side.txt").write_text("x", encoding="utf-8")
    git(r, "add", "-A")
    git(r, "commit", "-qm", "side")
    d = code_drift(r, shas[-1])          # main's tip, unreachable from side
    assert d["status"] == "diverged"
    assert d["commits"] is None, "a diverged verdict has no meaningful distance"


def test_unknown_never_raises_and_never_cries_wolf(repo, tmp_path):
    """A false 'you are behind' trains people to ignore the line."""
    r, _ = repo
    for bad in (None, "", "deadbeef" * 5, 12345, "not-a-sha"):
        assert code_drift(r, bad)["status"] == "unknown"
    assert code_drift(tmp_path / "no-such-dir", "HEAD")["status"] == "unknown"
    assert code_drift(tmp_path, "HEAD")["status"] == "unknown"   # exists, not a repo


def run_banner(cwd, qa_home):
    env = {k: v for k, v in os.environ.items() if k != "VERDICT_HOME"}
    env["VERDICT_HOME"] = str(qa_home)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps({"cwd": str(cwd)}),
                          capture_output=True, text=True, env=env).stdout


def seed_state(qa_home, key, sha, stamp=None):
    root = qa_home / key
    root.mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({
        "schema_version": "1.3", "project": key, "run_number": 2, "run_type": "delta",
        "verdict": "pass with risks",
        "last_run": {"timestamp_utc": stamp or datetime.now(timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"), "git_sha": sha},
        "findings": [{"id": "X-F-1", "severity": "Major", "status": "open",
                      "title": "a finding that may already be fixed", "age_days": 1}],
    }), encoding="utf-8")
    return root


def test_banner_warns_when_the_code_moved_on(repo, tmp_path):
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[0])
    out = run_banner(r, tmp_path / "qa")
    assert "Measured 2 commits ago" in out, out
    assert out.index("Measured 2 commits ago") < out.index("open finding"), \
        "the qualification must precede what it qualifies"


def test_banner_is_quiet_when_current(repo, tmp_path):
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[-1])
    out = run_banner(r, tmp_path / "qa")
    assert "Measured" not in out and "different code" not in out, out
    assert "open finding" in out, "the rest of the banner still renders"


def test_banner_singular_commit(repo, tmp_path):
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[1])
    assert "Measured 1 commit ago" in run_banner(r, tmp_path / "qa")


def test_banner_warns_on_divergence(repo, tmp_path):
    r, shas = repo
    git(r, "checkout", "-q", "-b", "side", shas[0])
    seed_state(tmp_path / "qa", r.name, shas[-1])
    assert "not in this branch's history" in run_banner(r, tmp_path / "qa")


def test_future_timestamp_is_named_not_rendered_as_negative_days(repo, tmp_path):
    """A state that misreports when it was written is a state to distrust."""
    ahead = (datetime.now(timezone.utc) + timedelta(days=400)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r, shas = repo
    seed_state(tmp_path / "qa", r.name, shas[-1], stamp=ahead)
    out = run_banner(r, tmp_path / "qa")
    assert "in the future" in out, out
    assert "-" not in out.splitlines()[0], f"negative day count leaked: {out.splitlines()[0]}"
