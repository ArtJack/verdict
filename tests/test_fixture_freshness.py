"""The gate that keeps the seeded-defect fixture and its committed diff in step.

Its job is to notice when the fixture pair drifts from `pricer-delta.diff`.
VERDICT-F-13 was about the edges it could not see: the reproduction copied
bytes, so a mode change or a symlink swap came back identical, an untracked
file planted in the fixture was invisible, and a tracked file missing from the
working tree crashed instead of reporting.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / "eval" / "fixture_freshness.py"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "-C", str(repo), *args], capture_output=True, text=True)


@pytest.fixture()
def fixture_repo(tmp_path):
    """A miniature of the real layout: eval/fixtures/{pricer,pricer_rev_b}."""
    repo = tmp_path / "repo"
    fixtures = repo / "eval" / "fixtures"
    (fixtures / "pricer").mkdir(parents=True)
    (fixtures / "pricer_rev_b").mkdir(parents=True)
    (fixtures / "pricer" / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    (fixtures / "pricer_rev_b" / "app.py").write_text("def f():\n    return 2\n",
                                                      encoding="utf-8")
    gate = repo / "eval" / "fixture_freshness.py"
    gate.write_text(GATE.read_text(encoding="utf-8"), encoding="utf-8")
    git(repo, "init", "-qb", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "fixture")
    # The anchor is whatever the gate itself regenerates right now.
    out = subprocess.run([sys.executable, str(gate)], cwd=repo, capture_output=True, text=True)
    assert "no longer describes" in out.stdout or out.returncode != 0, out.stdout
    return repo, fixtures


def run_gate(repo):
    return subprocess.run([sys.executable, str(repo / "eval" / "fixture_freshness.py")],
                          cwd=repo, capture_output=True, text=True)


def anchor(repo, fixtures):
    """Write the anchor the gate currently regenerates, so it starts green."""
    sys.path.insert(0, str(repo / "eval"))
    proc = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'eval'); import fixture_freshness as f;"
         " open('eval/fixtures/pricer-delta.diff','w').write(f.regenerate())"],
        cwd=repo, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "anchor")
    assert run_gate(repo).returncode == 0


def test_a_green_pair_stays_green(fixture_repo):
    repo, fixtures = fixture_repo
    anchor(repo, fixtures)
    assert run_gate(repo).returncode == 0


def test_a_mode_change_is_no_longer_invisible(fixture_repo):
    """`copyfile` drops the mode, so an executable bit flipped reproduced
    identically and the gate reported OK over a changed fixture."""
    repo, fixtures = fixture_repo
    anchor(repo, fixtures)
    target = fixtures / "pricer" / "app.py"
    os.chmod(target, 0o755)
    git(repo, "add", "-A")
    proc = run_gate(repo)
    assert proc.returncode != 0, proc.stdout


def test_an_untracked_file_planted_in_the_fixture_is_reported(fixture_repo):
    """A diff built from `ls-files` cannot describe it, so an eval run would
    read a fixture the anchor never covered."""
    repo, fixtures = fixture_repo
    anchor(repo, fixtures)
    (fixtures / "pricer" / "planted.py").write_text("SECRET = 1\n", encoding="utf-8")
    proc = run_gate(repo)
    assert proc.returncode != 0
    assert "untracked" in (proc.stdout + proc.stderr), proc.stdout + proc.stderr


def test_a_tracked_file_missing_from_the_tree_reports_rather_than_crashes(fixture_repo):
    repo, fixtures = fixture_repo
    anchor(repo, fixtures)
    (fixtures / "pricer" / "app.py").unlink()
    proc = run_gate(repo)
    assert proc.returncode != 0
    combined = proc.stdout + proc.stderr
    assert "Traceback" not in combined, combined
    assert "missing from the working tree" in combined, combined
