"""Every git call reads the repository it was asked about, whatever the environment names.

`git -C <repo>` gives way to the environment: GIT_DIR names a repository,
GIT_INDEX_FILE an index, GIT_OBJECT_DIRECTORY an object store, and git obeys each
of them wherever `-C` points. Measured on 0.90.2 with GIT_DIR set to repository A
and every reader asked about B: `derive_key(B)` answered A's key, so a run on B
would have read and written A's state, and the census, the harness and the runner
all read A's HEAD. `gitenv.git_env()` is the environment every git call now gets.
These tests hold each reader to it, and the sweep at the end keeps the next git
call from being written without it.
"""

import ast
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from verdict_mcp import accept, census, harness, project_key, questions, runner, small, state
from verdict_mcp.gitenv import git_env

SRC = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"

# The contract, written out rather than imported: a test that read the list from
# the module could not notice the module dropping one.
REPO_VARS = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE",
             "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_NAMESPACE")


def _git(args, cwd):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture()
def two(tmp_path, monkeypatch):
    """Repositories A and B with no commit in common, each with its own maintainer.
    B has two commits, so a range in B has an answer A cannot give. The variables
    are cleared first, so a suite run from inside a hook builds A and B instead of
    committing into the hook's repository."""
    for var in REPO_VARS:
        monkeypatch.delenv(var, raising=False)
    made = {}
    for name in ("Alpha", "Bravo"):
        r = tmp_path / name
        r.mkdir()
        _git(["init", "-qb", "main"], r)
        _git(["config", "user.name", f"{name} Maintainer"], r)
        (r / f"{name.lower()}.py").write_text("x = 1\n", encoding="utf-8")
        _git(["add", "-A"], r)
        _git(["commit", "-qm", f"{name} one"], r)
        made[name] = r
    a, b = made["Alpha"], made["Bravo"]
    b_first = _git(["rev-parse", "HEAD"], b)
    (b / "bravo2.py").write_text("y = 2\n", encoding="utf-8")
    _git(["add", "-A"], b)
    _git(["commit", "-qm", "Bravo two"], b)
    return SimpleNamespace(a=a, b=b, a_head=_git(["rev-parse", "HEAD"], a),
                           b_first=b_first, b_head=_git(["rev-parse", "HEAD"], b))


def test_git_env_is_the_environment_without_the_seven(monkeypatch):
    for var in REPO_VARS:
        monkeypatch.setenv(var, "/elsewhere")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/kept/gitconfig")      # set after import: seen
    env = git_env()
    assert env == {k: v for k, v in os.environ.items() if k not in REPO_VARS}
    assert env["GIT_CONFIG_GLOBAL"] == "/kept/gitconfig"
    env["PATH"] = "changed"
    assert os.environ.get("PATH") != "changed", "a copy, not the caller's environment"


def test_under_another_repositorys_git_dir_every_reader_answers_for_the_one_asked(
        two, monkeypatch):
    """The review's reproduction, carried to every git reader in the package:
    GIT_DIR names A, and each reader is asked about B."""
    monkeypatch.setenv("GIT_DIR", str(two.a / ".git"))
    rng = f"{two.b_first}..{two.b_head}"
    drift = state.code_drift(two.b, two.b_head)
    got = {
        "census._git": (census._git(["rev-parse", "HEAD"], two.b) or "").strip(),
        "harness._git": harness._git(["rev-parse", "HEAD"], two.b),
        "runner._head_sha": runner._head_sha(two.b),
        "project_key.derive_key": project_key.derive_key(two.b),
        "runner._changed_files": runner._changed_files(two.b, rng),
        "small.changed_files": small.changed_files(two.b, rng),
        "state.code_drift": (drift["status"], drift["head"]),
    }
    assert got == {
        "census._git": two.b_head,
        "harness._git": two.b_head,
        "runner._head_sha": two.b_head,
        "project_key.derive_key": ("bravo", "git"),   # was A's key, and with it A's state
        "runner._changed_files": ["bravo2.py"],
        "small.changed_files": ["bravo2.py"],
        "state.code_drift": ("current", two.b_head),  # was "absent", with A's HEAD
    }


def test_the_scratch_checkout_is_a_worktree_of_the_repository_asked(two, monkeypatch):
    """The one git call here that writes. Under A's GIT_DIR, `worktree add` looked
    for B's commit in A and failed, so no fix in B could be verified."""
    monkeypatch.setenv("GIT_DIR", str(two.a / ".git"))
    tmp = harness._scratch_checkout(two.b, two.b_head)
    assert tmp is not None, "B's own HEAD could not be checked out"
    try:
        assert sorted(p.name for p in tmp.glob("*.py")) == ["bravo.py", "bravo2.py"]
    finally:
        harness._remove_scratch(two.b, tmp)
    assert not tmp.exists()
    monkeypatch.delenv("GIT_DIR")
    for repo in (two.a, two.b):                        # registered nowhere once removed
        assert _git(["worktree", "list", "--porcelain"], repo).count("worktree ") == 1


@pytest.mark.parametrize("who", [accept._who, questions._who], ids=["accept", "questions"])
def test_a_signature_is_the_name_the_working_repository_configures(two, monkeypatch, who):
    """`git config user.name` has no `-C`: it reads the repository the process
    stands in. Under A's GIT_DIR, an entry signed in B carried A's maintainer."""
    monkeypatch.chdir(two.b)
    monkeypatch.setenv("GIT_DIR", str(two.a / ".git"))
    assert who() == "Bravo Maintainer"


def test_each_variable_that_misdirects_a_reader_on_its_own_is_dropped(two, monkeypatch):
    """GIT_DIR is not the only one. Each of these, set alone, sent a reader to A
    (measured on 0.90.2), and every pre-commit hook carries GIT_INDEX_FILE.
    GIT_COMMON_DIR and GIT_NAMESPACE misdirected none of these reads; they are
    dropped on the contract above."""
    a_git = two.a / ".git"

    def py_files():                                    # the harness's own call
        return harness._git(["ls-files", "--", "*.py", "**/*.py"], two.b)

    def toplevel():
        return Path(harness._git(["rev-parse", "--show-toplevel"], two.b) or "").resolve()

    cases = {
        # was "alpha.py": A's index read as B's
        "GIT_INDEX_FILE": (a_git / "index", py_files, "bravo.py\nbravo2.py"),
        # was A's directory
        "GIT_WORK_TREE": (two.a, toplevel, two.b.resolve()),
        # was "unknown": B's own commit unreadable in A's object store
        "GIT_OBJECT_DIRECTORY": (a_git / "objects",
                                 lambda: state.code_drift(two.b, two.b_head)["status"], "current"),
        # was "diverged": A's commit read as present in B
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": (
            a_git / "objects", lambda: state.code_drift(two.b, two.a_head)["status"], "absent"),
    }
    got, want = {}, {}
    for var, (value, read, expected) in cases.items():
        monkeypatch.setenv(var, str(value))
        got[var], want[var] = read(), expected
        monkeypatch.delenv(var)
    assert got == want


def _git_calls(tree):
    """(line, has_env) for every call whose first argument is a list literal that
    starts with "git": `subprocess.run`, `Popen`, or the harness's own `_run`."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.List)
                and node.args[0].elts and isinstance(node.args[0].elts[0], ast.Constant)
                and node.args[0].elts[0].value == "git"):
            out.append((node.lineno, any(k.arg == "env" for k in node.keywords)))
    return out


def test_every_git_call_in_the_package_names_its_environment():
    """A git call written without `env=` runs in whatever repository the caller's
    environment names. AST, not grep, as the clock's sweep does it."""
    missing = {}
    for path in sorted(SRC.glob("*.py")):
        bare = [line for line, has_env in _git_calls(ast.parse(path.read_text(encoding="utf-8")))
                if not has_env]
        if bare:
            missing[path.name] = bare
    assert not missing, f"git calls without env= (give them env=git_env()): {missing}"


def test_the_sweep_sees_the_calls_it_is_meant_to_see():
    """The control for the sweep: a blind instrument would pass every file. Each
    module that runs git must be seen, and a bare call must be caught."""
    seen = {path.stem for path in SRC.glob("*.py")
            if _git_calls(ast.parse(path.read_text(encoding="utf-8")))}
    assert {"accept", "census", "harness", "project_key", "questions", "runner",
            "small", "state"} <= seen, seen
    assert _git_calls(ast.parse('subprocess.run(["git", "status"])')) == [(1, False)]
