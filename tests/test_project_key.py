"""Tests for verdict_mcp.project_key against the docs/project-key.md decision table."""

import subprocess

import pytest

from verdict_mcp.project_key import derive_key, sanitize


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
        cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "Sales"
    r.mkdir()
    _git(["init", "-qb", "main"], r)
    (r / "f.txt").write_text("x")
    _git(["add", "."], r)
    _git(["commit", "-qm", "init"], r)
    return r


def test_normal_repo_uses_lowercased_basename(repo):
    assert derive_key(repo) == ("sales", "git")


def test_linked_worktree_uses_main_worktree_basename(repo):
    wt = repo / ".claude" / "worktrees" / "qa-nightly"
    _git(["worktree", "add", "-q", str(wt)], repo)
    assert derive_key(wt) == ("sales", "git")


def test_detached_head_is_unaffected(repo):
    _git(["checkout", "-q", "--detach"], repo)
    assert derive_key(repo) == ("sales", "git")


def test_bare_repo_strips_dot_git(repo, tmp_path):
    bare = tmp_path / "app.git"
    _git(["clone", "-q", "--bare", str(repo), str(bare)], tmp_path)
    assert derive_key(bare) == ("app", "git")


def test_subdirectory_of_repo_resolves_to_repo_key(repo):
    sub = repo / "src" / "deep"
    sub.mkdir(parents=True)
    assert derive_key(sub) == ("sales", "git")


def test_non_git_directory_falls_back_to_basename(tmp_path):
    d = tmp_path / "MyProject"
    d.mkdir()
    assert derive_key(d) == ("myproject", "directory")


def test_sanitize():
    assert sanitize("Sales") == "sales"
    assert sanitize("app.git") == "app"
    assert sanitize("Ugly Name!") == "ugly-name-"
    assert sanitize("") == "-"
