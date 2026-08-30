"""Fixtures shared by the harness tests and the run-chain tests.

They lived in test_harness.py and were imported by name, which made every test
signature a redefinition of an imported symbol — noisy to lint and fragile to
read. A conftest is where pytest looks anyway.
"""

import subprocess

import pytest


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


@pytest.fixture()
def qa_root(tmp_path):
    root = tmp_path / "qa"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "r.md").write_text("# report", encoding="utf-8")
    return root


def judgment(**over):
    j = {
        "report": "reports/r.md",
        "isolation_check": {"result": "pass"},
        "verdict": "pass with risks",
        "release_blockers": [],
        "not_tested": ["concurrency"],
        "findings": [{
            "id": "W-F-1", "title": "off-by-one at line 42", "severity": "Major",
            "priority": "P1", "status": "open", "failure_classification": "REAL_DEFECT",
            "confidence": "proven", "evidence": ["a.py:42 the guard"]}],
    }
    j.update(over)
    return j
