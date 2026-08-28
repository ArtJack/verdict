"""Subprocess-driven tests for the two PreToolUse scope guards.

Each hook is exercised exactly the way Claude Code runs it: a python3 process
with the hook-event JSON on stdin and the policy carried by environment
variables. Exit 0 = allow, 2 = deny.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
HOME_SOLO = os.path.expanduser("~/.claude/verdict")


def run_hook(script, payload, *, strict=None, env_extra=None):
    env = {k: v for k, v in os.environ.items()
           if k not in ("VERDICT_STRICT", "VERDICT_HOME")}
    if strict is not None:
        env["VERDICT_STRICT"] = strict
    if env_extra:
        env.update(env_extra)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=raw, capture_output=True, text=True, env=env,
    )
    return proc.returncode, proc.stderr


def write_event(path, agent=None):
    data = {"tool_name": "Write", "tool_input": {"file_path": path}}
    if agent:
        data["agent_name"] = agent
    return data


def bash_event(command, cwd):
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


@pytest.fixture()
def repo():
    # A fictional path OUTSIDE any temp dir: the guards do pure string
    # analysis, and pytest's real tmp_path sits under the macOS temp tree,
    # which the Bash guard rightly allow-lists as scratch.
    return "/fictional/checkout/repo"


# --- enforce_write_scope.py -------------------------------------------------

def test_write_allows_team_qa_in_strict():
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event("/repo/.qa/reports/x.md"), strict="1")
    assert rc == 0


def test_write_allows_default_solo_root_in_strict():
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event(f"{HOME_SOLO}/pricer/state.json"), strict="1")
    assert rc == 0


def test_write_honors_verdict_home(tmp_path):
    vh = tmp_path / "qa-home"
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event(str(vh / "pricer" / "state.json")),
                     strict="1", env_extra={"VERDICT_HOME": str(vh)})
    assert rc == 0
    # when VERDICT_HOME points elsewhere, the default root is no longer in scope
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event(f"{HOME_SOLO}/pricer/state.json"),
                     strict="1", env_extra={"VERDICT_HOME": str(vh)})
    assert rc == 2


def test_write_blocks_outside_in_strict():
    rc, err = run_hook("enforce_write_scope.py",
                       write_event("/repo/src/app.py"), strict="1")
    assert rc == 2
    assert "QA root" in err


def test_write_blocks_identified_verdict_caller_without_strict():
    for agent in ("verdict", "acme:verdict"):
        rc, _ = run_hook("enforce_write_scope.py",
                         write_event("/repo/src/app.py", agent=agent))
        assert rc == 2


def test_write_allows_outside_when_not_strict_and_caller_unknown():
    rc, _ = run_hook("enforce_write_scope.py", write_event("/repo/src/app.py"))
    assert rc == 0


def test_write_blocks_qa_traversal_escape():
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event("/repo/.qa/../../etc/passwd"), strict="1")
    assert rc == 2


def test_write_fails_open_on_malformed_input():
    rc, _ = run_hook("enforce_write_scope.py", "this is not json", strict="1")
    assert rc == 0


# --- enforce_bash_scope.py: pass-through and allowed commands ---------------

def test_bash_noop_when_not_strict(repo):
    rc, _ = run_hook("enforce_bash_scope.py", bash_event("rm -rf src", repo))
    assert rc == 0


@pytest.mark.parametrize("command", [
    "python -m pytest -q",
    "uv run pytest",
    "git diff && git status && git log --oneline",
    "echo hi > /dev/null",
    "pytest -q 2>&1",
    "git apply --check fix.patch",
    "cat <<EOF\nhello\nEOF",
])
def test_bash_allows_reads_and_safe_commands(repo, command):
    rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 0, err


def test_bash_allows_tmpdir_redirect(repo, tmp_path):
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event("echo x > $TMPDIR/scratch.txt", repo),
                       strict="1", env_extra={"TMPDIR": str(tmp_path)})
    assert rc == 0, err


def test_bash_allows_writes_into_verdict_home(repo, tmp_path):
    vh = tmp_path / "qa-home"
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"tee {vh}/pricer/reports/r.md", repo),
                       strict="1", env_extra={"VERDICT_HOME": str(vh)})
    assert rc == 0, err


def test_bash_allows_default_solo_root(repo):
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"echo s > {HOME_SOLO}/p/notes.md", repo), strict="1")
    assert rc == 0, err


def test_bash_allows_relative_redirect_inside_qa(repo):
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event("echo r > .qa/reports/r.md", repo), strict="1")
    assert rc == 0, err


def test_bash_allows_git_mutation_inside_qa_root(repo):
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"git -C {repo}/.qa commit -am snapshot", repo),
                       strict="1")
    assert rc == 0, err


# --- enforce_bash_scope.py: denials -----------------------------------------

@pytest.mark.parametrize("command", [
    "echo hi > src/app.py",
    "cat notes >> README.md",
    "tee src/x.py",
    "sed -i '' 's/a/b/' app.py",
    "rm -rf src",
    "mv a.py b.py",
    "cp fix.py src/app.py",
    "touch marker.txt",
    "git checkout -- .",
    "git commit -am wip",
    "VAR=1 env cp a.py b.py",
    "pytest -q && echo done > out.log",
    "dd if=/dev/zero of=src/blob bs=1",
])
def test_bash_blocks_mutations_outside_qa(repo, command):
    rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 2, f"expected deny for: {command}"
    assert "QA root" in err


def test_bash_blocks_unresolved_variable_target(repo):
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event("echo x > $TOTALLY_UNSET_VAR_XYZ/x.txt", repo),
                       strict="1")
    assert rc == 2
    assert "unresolved" in err


def test_bash_denies_when_unparseable_but_pattern_visible(repo):
    rc, _ = run_hook("enforce_bash_scope.py",
                     bash_event("echo 'oops > src/x.py", repo), strict="1")
    assert rc == 2


def test_bash_allows_when_unparseable_and_no_pattern(repo):
    rc, _ = run_hook("enforce_bash_scope.py",
                     bash_event("echo 'oops", repo), strict="1")
    assert rc == 0


def test_bash_fails_open_on_malformed_input():
    rc, _ = run_hook("enforce_bash_scope.py", "not json at all", strict="1")
    assert rc == 0
