"""The `directory` branch: this plugin as the Claude directory reads it.

The directory scans every file on the branch its listing tracks. Tracking `main`,
it failed every version after 0.90.2 on the secret scan's own test data ("Secret
in a shipped file: tests/test_hygiene.py"). `.github/directory_branch.py` writes
each release to `directory` without the tests, the eval harness, the QA record
and CI. Two promises hold it: nothing the plugin runs or reads is left behind,
and the branch only moves forward, one commit per release, never forced.
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / ".github" / "directory_branch.py"

_spec = importlib.util.spec_from_file_location("directory_branch", SCRIPT)
db = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(db)

# `${CLAUDE_PLUGIN_ROOT}/<path>` wherever the plugin names a file of its own: the
# hooks Claude Code runs, and what the agent, the commands and the skills read.
REFERENCE = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}/([A-Za-z0-9_.\-/]+)")


def tracked():
    try:
        out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z"], capture_output=True,
                             check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout: the branch is built from tracked files")
    return [p for p in out.decode("utf-8").split("\0") if p]


def test_the_branch_leaves_out_what_only_develops_verdict():
    paths = tracked()
    shipped = [p for p in paths if db.shipped(p)]
    assert "tests/test_hygiene.py" in paths and "tests/test_hygiene.py" not in shipped
    assert [p for p in shipped if p.startswith(("tests/", "eval/", ".qa/", ".github/"))] == []
    for needed in (".claude-plugin/plugin.json", "README.md", "LICENSE", "hooks/hooks.json",
                   "agents/verdict.md", "src/verdict_mcp/validate.py"):
        assert needed in shipped, needed
    # The directory holds a plugin of more than 512 files for a reviewer.
    assert len(shipped) <= 512


def test_everything_the_plugin_runs_or_reads_is_on_the_branch():
    shipped = {p for p in tracked() if db.shipped(p)}
    folders = {"/".join(p.split("/")[:i]) for p in shipped for i in range(1, p.count("/") + 1)}
    sources = [REPO / "hooks" / "hooks.json", *sorted((REPO / "agents").glob("*.md")),
               *sorted((REPO / "commands").glob("*.md")), *sorted((REPO / "skills").glob("*/SKILL.md"))]
    named = {(src.relative_to(REPO).as_posix(), m.group(1).rstrip("./"))
             for src in sources for m in REFERENCE.finditer(src.read_text(encoding="utf-8"))}
    assert len(named) >= 10, "the reference pattern stopped matching, so this test would pass on anything"
    missing = sorted(f"{src} names {path}" for src, path in named
                     if path not in shipped and path not in folders)
    assert missing == [], "the directory would get a plugin that names files it lacks:\n  " + "\n  ".join(missing)


# ── building the branch, in a scratch repository with a bare remote ─────────

def git(repo, *args):
    # UTF-8 explicitly: git writes UTF-8, and Windows would decode it in the ANSI
    # code page, which turned the commit message's "·" into "Â·" on CI.
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=True,
                          encoding="utf-8").stdout.strip()


FILES = {".claude-plugin/plugin.json": '{"name": "p", "version": "1.0.0"}\n',
         "hooks/hooks.json": "{}\n", "src/p/a.py": "A = 1\n", "README.md": "readme\n",
         "tests/test_a.py": "def test_a():\n    pass\n", "eval/fixture.txt": "seeded\n",
         ".qa/state.json": "{}\n", ".github/workflows/ci.yml": "on: push\n"}
PLUGIN = sorted(p for p in FILES if db.shipped(p))


def release(repo, version, **changes):
    for rel, text in {".claude-plugin/plugin.json": f'{{"name": "p", "version": "{version}"}}\n',
                      **changes}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", version)
    git(repo, "tag", f"v{version}")


@pytest.fixture
def plugin_repo(tmp_path, monkeypatch):
    for who in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{who}_NAME", "t")
        monkeypatch.setenv(f"GIT_{who}_EMAIL", "t@t")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
    repo = tmp_path / "plugin"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    release(repo, "1.0.0", **FILES)
    git(repo, "remote", "add", "origin", str(remote))
    return repo, remote


def test_a_release_is_one_commit_without_the_tests_and_a_rerun_writes_nothing(plugin_repo):
    repo, remote = plugin_repo
    first = db.build(repo, "v1.0.0", remote="origin")
    assert git(remote, "rev-parse", "refs/heads/directory") == first
    assert git(remote, "ls-tree", "-r", "--name-only", first).splitlines() == PLUGIN
    assert git(remote, "log", "-1", "--format=%s", first).startswith("directory: p 1.0.0 from v1.0.0 · ")
    assert db.build(repo, "v1.0.0", remote="origin") is None
    assert git(remote, "rev-parse", "refs/heads/directory") == first
    assert git(repo, "status", "--porcelain") == "", "the working tree or the index was touched"
    assert git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"


def test_the_next_release_extends_the_branch(plugin_repo):
    repo, remote = plugin_repo
    first = db.build(repo, "v1.0.0", remote="origin")
    release(repo, "1.0.1", **{"src/p/a.py": "A = 2\n"})
    second = db.build(repo, "v1.0.1", remote="origin")
    assert git(remote, "rev-parse", f"{second}^") == first
    assert git(remote, "show", f"{second}:src/p/a.py") == "A = 2"
    assert git(remote, "rev-parse", "refs/heads/directory") == second


def test_a_branch_that_moved_underneath_refuses_instead_of_losing_a_commit(plugin_repo, monkeypatch):
    repo, remote = plugin_repo
    first = db.build(repo, "v1.0.0", remote="origin")
    release(repo, "1.0.1", **{"src/p/a.py": "A = 2\n"})
    second = db.build(repo, "v1.0.1", remote="origin")
    # Read the remote's tip just before another writer moved it: the build goes on
    # the older commit, and the push is the only thing that can notice.
    monkeypatch.setattr(db, "_remote_tip", lambda *_: first)
    release(repo, "1.0.2", **{"src/p/a.py": "A = 3\n"})
    with pytest.raises(RuntimeError):
        db.build(repo, "v1.0.2", remote="origin")
    assert git(remote, "rev-parse", "refs/heads/directory") == second


def test_without_a_remote_only_the_local_branch_moves(plugin_repo):
    repo, remote = plugin_repo
    made = db.build(repo, "v1.0.0")
    assert git(repo, "rev-parse", "refs/heads/directory") == made
    assert git(remote, "for-each-ref", "refs/heads/directory") == ""
    assert db.build(repo, "v1.0.0") is None


def test_the_release_workflow_can_run_it(plugin_repo):
    repo, remote = plugin_repo
    sha = git(repo, "rev-parse", "HEAD")
    run = subprocess.run([sys.executable, str(SCRIPT), sha, "--label", "v1.0.0", "--push",
                          "--repo", str(repo)], capture_output=True, encoding="utf-8")
    assert run.returncode == 0, run.stderr
    tip = git(remote, "rev-parse", "refs/heads/directory")
    assert run.stdout.strip() == f"directory: {tip}"
    assert " from v1.0.0 · " in git(remote, "log", "-1", "--format=%s", tip)
    again = subprocess.run([sys.executable, str(SCRIPT), sha, "--push", "--repo", str(repo)],
                           capture_output=True, encoding="utf-8")
    assert again.returncode == 0 and "nothing written" in again.stdout
