"""Subprocess-driven tests for the two PreToolUse scope guards.

Each hook is exercised exactly the way Claude Code runs it: a python3 process
with the hook-event JSON on stdin and the policy carried by environment
variables. Exit 0 = allow, 2 = deny.
"""

import json
import os
import subprocess
import sys
import tempfile
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
def repo(tmp_path):
    """A real checkout, because the guards are no longer pure string analysis.

    They used to be, and a fictional path was enough. Two rules now read the
    filesystem: a team `.qa/` counts only beside a real `.git` (otherwise any
    nested directory named `.qa` inside the code under test was writable), and
    a temp root is scratch only where it is not a checkout (otherwise the eval
    harness's own mkdtemp repo put the code under test out of jurisdiction).
    Both need a repository that exists.
    """
    r = tmp_path / "repo"
    (r / ".qa" / "reports").mkdir(parents=True)
    (r / "src").mkdir()
    subprocess.run(["git", "init", "-q", str(r)], check=True, capture_output=True)
    return str(r)


# --- enforce_write_scope.py -------------------------------------------------

def test_write_allows_team_qa_in_strict(repo):
    rc, err = run_hook("enforce_write_scope.py",
                       write_event(f"{repo}/.qa/reports/x.md"), strict="1")
    assert rc == 0, err


def test_write_blocks_a_qa_directory_nested_in_the_code(repo):
    """`<repo>/src/.qa/` is code under test wearing the scope's name."""
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event(f"{repo}/src/.qa/x"), strict="1")
    assert rc == 2


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


def test_write_blocks_symlink_escape_from_inside_qa(tmp_path):
    # VERDICT-F-1 (found by Verdict reviewing its own repo): a symlink planted
    # inside .qa/ must not launder a write to wherever it points.
    outside = tmp_path / "outside"
    outside.mkdir()
    qa = tmp_path / "repo" / ".qa"
    qa.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")],
                   check=True, capture_output=True)
    link = qa / "link"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    rc, err = run_hook("enforce_write_scope.py",
                       write_event(str(link / "escaped.md")), strict="1")
    assert rc == 2, "write through a .qa-resident symlink escaped the QA root"
    # a real file inside the same .qa stays allowed
    rc, _ = run_hook("enforce_write_scope.py",
                     write_event(str(qa / "reports" / "ok.md")), strict="1")
    assert rc == 0


def test_bash_blocks_symlink_escape_from_inside_qa(tmp_path):
    # The escape target must live outside the guard's scratch allow-list: on
    # Linux, pytest's tmp_path is under /tmp, which the Bash guard rightly
    # allows — so the symlink points at a fictional non-scratch path (symlink
    # creation does not require the target to exist, and realpath resolves it
    # regardless).
    qa = tmp_path / "repo" / ".qa"
    qa.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(tmp_path / "repo")],
                   check=True, capture_output=True)
    link = qa / "link"
    try:
        link.symlink_to("/fictional-escape-target")
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    rc, _ = run_hook("enforce_bash_scope.py",
                     bash_event(f"echo x > {link}/escaped.txt", tmp_path / "repo"),
                     strict="1")
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


@pytest.mark.skipif(os.name == "nt", reason="`/tmp` is drive-relative on Windows")
@pytest.mark.parametrize("command", [
    "echo x > /tmp/scratch-probe.txt",
    "echo x >> /private/tmp/scratch-probe.txt",
    "tee /tmp/notes.txt",
])
def test_bash_allows_plain_tmp_roots(repo, command):
    """The POSIX temp roots, spelled the way a shell command actually spells them.

    Skipped on Windows on purpose rather than quietly passing: there, `/tmp` is
    a drive-relative path that resolves against whichever drive the process
    happens to be on, so the literal asserts nothing about the platform's real
    temp root. `test_bash_allows_the_platform_temp_root` covers that everywhere.
    """
    rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 0, err


@pytest.mark.parametrize("template", ["echo x > {}/probe.txt", "tee {}/notes.txt"])
def test_bash_allows_the_platform_temp_root(repo, template):
    """Scratch under the real temp root stays writable on every platform."""
    command = template.format(tempfile.gettempdir().replace("\\", "/"))
    rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 0, err


def test_bash_allows_git_dry_run_and_check(repo):
    for command in ("git clean --dry-run", "git apply --check fix.patch"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 0, (command, err)


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
    "echo x &> combined.log",
    "echo y >| clobbered.txt",
    "cmd 2> errors.txt",
    "tee src/x.py",
    "sed -i '' 's/a/b/' app.py",
    "perl -i -pe s/a/b/ app.py",
    "rm -rf src",
    "rmdir empty",
    "unlink f.py",
    "mv a.py b.py",
    "cp fix.py src/app.py",
    "install -m 755 tool.sh bin/tool",
    "touch marker.txt",
    "mkdir newdir",
    "ln -s a b",
    "chmod 777 script.sh",
    "chown me f.py",
    "truncate -s 0 log.py",
    "shred secrets.py",
    "rsync a/ b/",
    "patch -p1 < fix.diff",
    "git checkout -- .",
    "git switch main",
    "git restore .",
    "git commit -am wip",
    "git push origin main",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git stash",
    "git merge feature",
    "git rebase main",
    "git am patch.mbox",
    "git apply fix.patch",
    "git revert HEAD",
    "git cherry-pick abc123",
    "git tag v1",
    "git branch -D old",
    "git worktree add ../x",
    "git config user.name x",
    "VAR=1 env cp a.py b.py",
    "sudo rm -rf src",
    "nohup rm x.py",
    "command cp a b",
    "time mv a b",
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


# --- bypasses found by external audit, 2026-08-31 ---------------------------
#
# Every one of these exited 0 against the shipped guard. They are cheap to
# close and each was a real path to editing the code under test during a
# strict run, which is the one thing the guard exists to prevent.

@pytest.mark.parametrize("command", [
    # A git global flag that takes a value swallowed the verb: the guard read
    # "core.editor=true" as the subcommand, found it in no mutator set, and
    # let the commit through.
    "git -c core.editor=true commit -am x",
    "git --work-tree . commit -am x",
    "git --git-dir .git commit -am x",
    "git --namespace n commit -am x",
    # In-place editing is rarely spelled `-i`: perl clusters it behind -p and
    # sed also accepts the long form.
    "perl -pi -e s/x/y/ f.txt",
    "perl -i.bak -pe s/x/y/ f.txt",
    "sed --in-place s/x/y/ f.txt",
    "sed --in-place=.bak s/x/y/ f.txt",
    # find was in no mutator set at all.
    'find . -name "*.py" -delete',
    'find . -name "*.py" -exec rm {} ;',
])
def test_bash_blocks_audited_bypasses(repo, command):
    rc, _ = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 2, f"bypass still open: {command}"


@pytest.mark.parametrize("command", [
    "git status", "git diff --stat", "git log --oneline -5",
    "git commit --dry-run -am x",
    "pytest -q", "sed -n 1p f.txt", "perl -e 'print 1'",
    'find . -name "*.py"', 'find . -name "*.py" -exec grep -l x {} ;',
])
def test_bash_still_allows_read_only_work(repo, command):
    """The guard earns its place only if a real QA run never trips it."""
    rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 0, f"false positive on {command}: {err}"


def test_bash_has_jurisdiction_over_a_checkout_in_a_temp_dir(tmp_path):
    """The hole that made the eval's own guard coverage vacuous.

    The harness builds its scratch repo with mkdtemp, and the whole temp root
    was allow-listed as scratch — so during every eval run the guard had no
    jurisdiction over the code under test, and "zero false-positive blocks"
    described a check that could not fire.
    """
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    subprocess.run(["git", "init", "-q", str(checkout)], check=True, capture_output=True)
    rc, _ = run_hook("enforce_bash_scope.py",
                     bash_event("rm pricer.py", checkout), strict="1")
    assert rc == 2, "a checkout under a temp root is code under test, not scratch"


def test_bash_still_allows_genuine_scratch_in_a_temp_dir(tmp_path):
    """...while ordinary temp scratch stays writable, or strict mode is a
    thing people turn off."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event("touch cache.db", scratch), strict="1")
    assert rc == 0, err


def test_bash_allows_qa_state_inside_a_temp_checkout(tmp_path):
    """QA scope outranks the checkout rule: the tester must always be able to
    write its own findings, wherever the repository happens to live."""
    checkout = tmp_path / "checkout"
    (checkout / ".qa").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(checkout)], check=True, capture_output=True)
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event("tee .qa/state.json", checkout), strict="1")
    assert rc == 0, err


# --- second sweep: the same defect classes, one layer out --------------------
#
# The 0.44.0 fixes closed six specific commands. Re-probing the same classes —
# wrappers that hide the head, indirection, and an incomplete verb set — found
# every one of these still open.

@pytest.mark.parametrize("command", [
    # Wrappers whose own flags take values, or that were simply not listed.
    "timeout 5 rm f.txt",
    "nice -n 10 rm f.txt",
    "stdbuf -o0 rm f.txt",
    "sudo -u nobody rm f.txt",
    # A shell inside a shell. Not opaque the way an interpreter's -c is: this
    # module parses shell, so declining to look would have been a choice.
    'bash -c "rm f.txt"',
    'sh -c "git commit -am x"',
    # Targets that arrive on stdin cannot be checked, which is the same
    # situation as an unresolved $variable and gets the same answer.
    "echo f.txt | xargs rm",
    "cat list | xargs sed -i s/a/b/",
    # git verbs the set never had. `pull` is `fetch` + `merge`: it rewrites the
    # working tree, and it was the widest of these.
    "git pull",
    "git submodule update --init",
    "git bisect start",
    "git update-ref refs/heads/main HEAD",
    "git gc --prune=now",
    "git sparse-checkout set src",
    "git notes add -m x",
    "git stash",
    # Editors that mutate without ever spelling -i.
    'awk -i inplace "{print}" f.txt',
    "tar -xf archive.tar",
])
def test_bash_blocks_second_sweep_bypasses(repo, command):
    rc, _ = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 2, f"still open: {command}"


@pytest.mark.parametrize("command", [
    # The wrappers must not swallow innocent work.
    "timeout 300 pytest -q",
    "nice -n 5 pytest",
    'bash -c "pytest -q"',
    'sh -c "git diff --stat"',
    "cat list | xargs grep -l needle",
    # git's read-only forms, including the ones whose marker is a flag and the
    # ones that only report when bare. `git branch` lists; it does not create.
    "git branch", "git tag", "git submodule", "git submodule status",
    "git bisect log", "git stash list", "git reflog", "git notes",
    "git worktree list", "git config --list", "git config --get user.name",
    # tar creating an archive reads; only extraction overwrites.
    "tar -cf archive.tar src",
    'awk "{print}" f.txt',
])
def test_bash_second_sweep_has_no_false_positives(repo, command):
    rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
    assert rc == 0, f"false positive on {command}: {err}"


def test_nested_shell_recursion_is_bounded(repo):
    """A shell inside a shell inside a shell still terminates."""
    rc, _ = run_hook("enforce_bash_scope.py",
                     bash_event('bash -c "sh -c \\"bash -c \\\\\\"echo hi\\\\\\"\\""', repo),
                     strict="1")
    assert rc == 0
