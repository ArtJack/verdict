"""Subprocess-driven tests for the two PreToolUse scope guards.

Each hook is exercised exactly the way Claude Code runs it: a python3 process
with the hook-event JSON on stdin and the policy carried by environment
variables. Exit 0 = allow, 2 = deny.
"""

import ast
import json
import os
import shutil
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
        # Explicit, because the default is the locale codepage on Windows and
        # every guard's reason contains an em-dash. Without it the reader
        # thread dies on 0x97, stderr comes back empty, and an assertion on
        # the reason passes or fails for reasons that have nothing to do with
        # the guard. `errors` so a decode problem is visible as text rather
        # than as a lost message.
        encoding="utf-8", errors="replace",
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


def test_nested_shell_parses_a_quote_wrapped_command():
    """The Windows tokenizer keeps quotes; the recursion must survive them.

    `_tokens` runs shlex with posix=False on Windows so that path backslashes
    are not eaten as escapes — and that mode leaves the quotes on the token.
    The nested command therefore arrived as the single token '"rm f.txt"' and
    matched nothing, so shell recursion worked on POSIX and was dead on the
    platform where it shipped. Driving the helper directly exercises that path
    from any OS.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "ebs", HOOKS / "enforce_bash_scope.py")
    ebs = importlib.util.module_from_spec(spec)
    sys.modules["ebs"] = ebs
    sys.path.insert(0, str(HOOKS))
    spec.loader.exec_module(ebs)
    for quoted in ('"rm f.txt"', "'rm f.txt'"):
        found = list(ebs._check_shell(["-c", quoted], "/repo", 0))
        assert found, f"quote-wrapped nested command not parsed: {quoted}"
        assert found[0][0] == "rm"


# --- a copy has a source and a destination (F-37) ---------------------------

def test_bash_allows_copying_the_checkout_out_to_scratch(repo, tmp_path):
    """VERDICT-F-37: every non-flag argument of cp/mv/rsync counted as a write
    target, so copying the checkout into a scratch directory — the re-injection
    the agent contract asks for — was refused in the same words as overwriting
    source. A copy reads all but its last operand."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"cp -a {repo} {scratch}/tree2", repo), strict="1")
    assert rc == 0, err


def test_bash_still_blocks_copying_into_the_checkout(repo, tmp_path):
    """The guard's whole job, and the direction that must stay refused."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"cp -a {scratch}/x.py {repo}/src/app.py", repo), strict="1")
    assert rc == 2 and "QA root" in err


def test_bash_reads_an_explicit_target_directory(repo, tmp_path):
    """With `-t DIR` the destination is the flag's argument and every operand
    is a source — the one shape where "the last one" is wrong."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    ok, _ = run_hook("enforce_bash_scope.py",
                     bash_event(f"cp -t {scratch} {repo}/src/a.py {repo}/src/b.py", repo),
                     strict="1")
    assert ok == 0
    bad, err = run_hook("enforce_bash_scope.py",
                        bash_event(f"cp -t {repo}/src {scratch}/a.py", repo), strict="1")
    assert bad == 2 and "QA root" in err
    eq, err2 = run_hook("enforce_bash_scope.py",
                        bash_event(f"cp --target-directory={repo}/src {scratch}/a.py", repo),
                        strict="1")
    assert eq == 2, err2


def test_bash_blocks_moving_anything_out_of_the_checkout(repo, tmp_path):
    """VERDICT-F-39, a regression 0.65.0 shipped: `mv` was read as a copy, and
    a copy only writes its destination. But `mv` also *removes* its source — so
    the guard began permitting `mv <checkout>/hooks/enforce_bash_scope.py /tmp/`,
    the agent moving the guard itself out of the way, one commit after that
    exact command was denied."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f"mv {repo}/src/app.py {scratch}/app.py",
                    f"mv {repo}/.qa/../src/app.py {scratch}/",
                    f"rsync --remove-source-files {repo}/src/app.py {scratch}/"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 2, f"expected deny for: {command}"
        assert "QA root" in err


def test_bash_still_allows_a_move_that_touches_neither_end_of_the_checkout(repo, tmp_path):
    """The false-positive guard: treating a move's source as a target must not
    make every move a refusal."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"mv {scratch}/a.py {scratch}/b.py", repo), strict="1")
    assert rc == 0, err


def test_bash_still_allows_copying_out_which_is_the_whole_point_of_the_last_fix(repo, tmp_path):
    """`cp` reads its source. Repairing `mv` must not undo VERDICT-F-37."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f"cp -a {repo} {scratch}/tree2",
                    f"rsync {repo}/src/app.py {scratch}/"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 0, f"{command}: {err}"


def test_bash_blocks_archiving_the_checkout_away(repo, tmp_path):
    """VERDICT-F-42: the tar handler returned early on anything that was not an
    extraction, so `tar --remove-files -cf <scratch>/loot.tar <checkout>/hooks`
    — archive-then-delete, the `mv` shape from F-39 in another costume — was
    permitted."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f"tar --remove-files -cf {scratch}/loot.tar {repo}/src",
                    f"tar --remove-files -czf {scratch}/loot.tgz {repo}"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 2, f"expected deny for: {command}"
        assert "QA root" in err


def test_bash_still_allows_archiving_the_checkout_without_deleting_it(repo, tmp_path):
    """Reading is not writing. Refusing every `tar -cf` would refuse the backup
    the re-injection step legitimately makes."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f"tar -cf {scratch}/backup.tar {repo}/src",
                    f"tar --remove-files -cf {scratch}/x.tar {scratch}/stuff"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 0, f"{command}: {err}"


def test_bash_still_blocks_extracting_into_the_checkout(repo, tmp_path):
    """The case the handler already covered, which the fix must not disturb."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"tar -xf {scratch}/x.tar -C {repo}/src", repo), strict="1")
    assert rc == 2 and "QA root" in err


def test_bash_blocks_archive_then_delete_whatever_the_option_order(repo, tmp_path):
    """VERDICT-F-42, second pass. The first fix closed the one command the
    finding quoted and left the family open: every option token containing the
    letter `f` was treated as taking an argument, so `--remove-files` swallowed
    the operand behind it and the deletion had no visible target.

    The last case is the reason the old test passed for half the wrong reason —
    with `--remove-files` leading, it ate `-cf` rather than the archive name.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f"tar -cf {scratch}/loot.tar --remove-files {repo}/src",
                    f"tar -c -f {scratch}/loot.tar --remove-files {repo}/src",
                    f"tar cf {scratch}/loot.tar --remove-files {repo}/src",
                    f"tar -cf {scratch}/loot.tar --rem {repo}/src",
                    f"tar --remove-files -cf {scratch}/loot.tar {repo}/src"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 2, f"expected deny for: {command}"
        # Two platform details, both in the message rather than the guard: it
        # normalizes the target before reporting (so `repo/src` becomes
        # `repo\src` on Windows) and prints it with `!r`, which doubles every
        # backslash. Rendering the expectation the same way keeps this an
        # assertion about *which path* was named, on either platform.
        named = repr(str(Path(repo, "src")))[1:-1]
        assert named in err, f"the deletion target should be named: {err}"


def test_bash_allows_excluding_a_directory_from_an_archive(repo, tmp_path):
    """VERDICT-F-49: substring option parsing in the other direction. Any flag
    containing the letter `x` read as an extraction, so `--exclude=.venv` — the
    natural way to snapshot a checkout without dragging the virtualenv along,
    which is the contract's own scratch-copy step — was denied as an overwrite
    of the current directory. `-X` is exclude-from and is not extraction either.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    Path(repo, "ex.txt").write_text("junk\n", encoding="utf-8")
    for command in (f"tar --exclude=.venv -cf {scratch}/backup.tar {repo}/src",
                    f"tar -cf {scratch}/backup.tar --exclude junk {repo}/src",
                    f"tar -cf {scratch}/backup.tar -X {repo}/ex.txt {repo}/src"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 0, f"{command}: {err}"


def test_bash_still_blocks_extraction_named_the_long_way(repo, tmp_path):
    """The precision of the `x` fix must not cost the denial it exists for:
    `--extract` and its unambiguous abbreviation still overwrite in place."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f"tar --extract --file {scratch}/x.tar -C {repo}/src",
                    f"tar --ext -f {scratch}/x.tar -C {repo}/src",
                    f"tar xf {scratch}/x.tar -C {repo}/src"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 2, f"expected deny for: {command}"


def test_bash_reads_metacharacters_inside_quotes_as_text(repo):
    """VERDICT-F-22: redirects were found by scanning the raw command line, so
    a `>` that the shell would never execute denied four read-only commands in
    one QA run — a `{rc:>3}` format spec and a quoted `"<tmp>"` inside a
    heredoc body, and a `->` in a docstring.
    """
    heredoc = "python3 - <<'EOF'\n%s\nEOF"
    for command in (heredoc % "print(f'{rc:>3}')",
                    heredoc % 'print("<tmp> -> here")',
                    heredoc % "def f(x) -> int:\n    return x",
                    "echo 'a; rm -rf %s/src'" % repo,
                    'echo "pipe | and > arrow"'):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 0, f"{command!r}: {err}"


def test_bash_resolves_a_relative_redirect_against_the_cd_beside_it(repo, tmp_path):
    """VERDICT-F-22, fourth shape: a genuine redirect whose relative target was
    resolved against the tool's cwd rather than the `cd` in the same command
    line, so writing a scratch file was refused as writing to the checkout.

    The second case is the one that must stay denied — a `cd` back into the
    checkout puts the same relative name inside it.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"cd {scratch} && cat > trace.py <<'EOF'\nx = 1\nEOF", repo),
                       strict="1")
    assert rc == 0, err
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"cd {scratch} && cd {repo} && echo hi > pwned.py", repo),
                       strict="1")
    assert rc == 2, "a cd back into the checkout must not launder the redirect"
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"cd {scratch} | true; echo hi > pwned.py", repo),
                       strict="1")
    assert rc == 2, "a pipeline stage is a subshell; its cd does not carry"


def test_bash_still_sees_a_redirect_inside_a_nested_shell(repo):
    """Masking quoted text would have hidden `bash -c "... > file"` from the
    outer scan, where the raw-text scan used to catch it by accident. The
    nested parse has to look for redirects itself now."""
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f'bash -c "echo hi > {repo}/src/pwned.py"', repo),
                       strict="1")
    assert rc == 2 and "QA root" in err


def test_bash_looks_inside_eval(repo, tmp_path):
    """`eval` is a shell by another name, and masking made it the one place a
    redirect could hide: everything inside `eval "... > file"` is quoted text
    in the masked view, and the raw scan that used to catch it by accident is
    gone. Both a redirect and a mutating command inside it must still be seen.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    for command in (f'eval "echo hi > {repo}/src/pwned.py"',
                    f'eval "rm -rf {repo}/src"'):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 2, f"expected deny for: {command}"
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f'eval "pytest -q > {scratch}/out.txt"', repo), strict="1")
    assert rc == 0, err


@pytest.mark.parametrize("command, expect", [
    ('eval "echo hi > {repo}/src/pwned.py"', "output redirection"),
    ('eval "rm -rf {repo}/src"', "rm"),
    ('bash -c "echo hi > {repo}/src/pwned.py"', "output redirection"),
    ('bash -c "rm -rf {repo}/src"', "rm"),
])
def test_nested_commands_parse_under_windows_tokenization(repo, command, expect):
    """Run the non-POSIX tokenizer on every platform, not only on Windows.

    `_tokens` uses `shlex.split(posix=False)` there so path backslashes survive,
    and that mode keeps the quotes around a token — which once made the
    `bash -c` recursion work on POSIX and do nothing on Windows. Masking gave
    `eval` the same exposure, since a nested command left in quotes is entirely
    text in the masked view. Asserting it here means neither platform is the
    only place the bug can be seen.
    """
    import shlex
    sys.path.insert(0, str(HOOKS))
    import enforce_bash_scope as guard

    toks = shlex.split(command.format(repo=repo), posix=False)
    hits = list(guard._check_segment(toks, str(repo)))
    assert hits, f"nothing seen inside: {command}"
    assert hits[0][0] == expect
    assert str(repo) in hits[0][1]


def test_a_windows_path_survives_masking_and_target_reading(monkeypatch):
    """Backslash is an escape on POSIX and a path separator on Windows.

    `_tokens` already chose — shlex with posix=False on Windows, so paths keep
    their separators — and the masker and the redirect-target reader have to
    make the same choice. They did not, and the only place it could fire was
    the Windows CI leg: `C:\\Users\\...\\repo\\src` arrived as
    `C:Usersreposrc`, which then read as a *relative* path and resolved inside
    the checkout, so three correct commands were denied and one deletion target
    was reported under a name nothing matches.

    Forcing the flag here means the next such bug fails on every platform.
    """
    sys.path.insert(0, str(HOOKS))
    import enforce_bash_scope as guard

    win = r"C:\Users\runner\AppData\Local\Temp\repo\src\out.txt"
    monkeypatch.setattr(guard, "_POSIX", False)
    view, balanced = guard._mask_quoted(f"echo hi > {win}")
    assert balanced and len(view) == len(f"echo hi > {win}")
    assert list(guard._redirect_targets(f"echo hi > {win}", view)) == [win]

    # And the POSIX behaviour it must not cost: there, a backslash escapes.
    monkeypatch.setattr(guard, "_POSIX", True)
    assert list(guard._redirect_targets(r"echo hi > a\ b.txt",
                                        guard._mask_quoted(r"echo hi > a\ b.txt")[0])) \
        == ["a b.txt"]


@pytest.mark.parametrize("script", ["enforce_bash_scope.py", "enforce_write_scope.py",
                                    "enforce_run_contract.py"])
def test_every_guard_writes_its_reason_as_utf8(script):
    """A guard that blocks without a readable reason blocks for nothing.

    Each one explains itself in prose containing an em-dash. On Windows stderr
    defaults to the console codepage, so the byte written is cp1252's 0x97
    while the caller decodes UTF-8 — the explanation is replaced by a
    UnicodeDecodeError raised in a subprocess reader thread, which is easy to
    read as an empty message rather than a lost one.

    Checked as bytes, so this holds wherever it runs.
    """
    proc = subprocess.run([sys.executable, str(HOOKS / script)],
                          input=b"not json at all", capture_output=True)
    assert proc.returncode == 0, "malformed input must still fail open"
    proc.stderr.decode("utf-8")  # raises if the stream is not UTF-8

    # As a statement inside main(), not as text: a substring survives in a
    # comment or a docstring exactly as the future import did (VERDICT-F-64),
    # and run 12 measured this line as unwatched for that reason (VERDICT-F-60).
    tree = ast.parse((HOOKS / script).read_text(encoding="utf-8"))
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert mains, f"{script} has no main()"
    calls = [n for n in ast.walk(mains[0]) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", None)) == "utf8_stderr"]
    assert calls, f"{script} never calls utf8_stderr() from main() — its reason is lost on Windows"


def test_bash_blocks_archive_then_delete_reached_through_a_change_of_directory(repo, tmp_path):
    """VERDICT-F-56: tar reads its operands relative to `-C`, and the handler
    yielded them bare. From a scratch cwd, `-C <checkout> hooks` resolved to
    `<scratch>/hooks` — a path that does not exist and is allowed — while tar
    deleted the checkout's copy. Proven with real GNU tar during the audit.

    Both directions, from a cwd that is neither: the checkout must be denied
    and a scratch directory must survive, or the fix is just a wider refusal.
    """
    scratch = tmp_path / "scratch"
    (scratch / "stuff").mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    named = repr(str(Path(repo, "hooks")))[1:-1]
    for command in (f"tar -cf {scratch}/x.tar --remove-files -C {repo} hooks",
                    f"tar -cf {scratch}/x.tar --remove-files --directory={repo} hooks"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, elsewhere), strict="1")
        assert rc == 2, f"expected deny for: {command}"
        assert named in err, f"the checkout's path should be named: {err}"

    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"tar -cf {scratch}/x.tar --remove-files -C {scratch} stuff",
                                  elsewhere), strict="1")
    assert rc == 0, f"archiving scratch out of scratch must still be allowed: {err}"


def test_bash_blocks_a_deletion_list_it_cannot_read(repo, tmp_path):
    """VERDICT-F-59: `-T <file>` puts the operands in a file, so nothing on the
    command line names them and the handler yielded nothing at all. The module
    already had a word for a target it cannot see — `xargs` uses it — and this
    site did not.

    A `-T` without `--remove-files` only reads, and must stay allowed."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    Path(repo, "list.txt").write_text("hooks\n", encoding="utf-8")
    for command in (f"tar --remove-files -cf {scratch}/x.tar -T {repo}/list.txt",
                    f"tar --remove-files -cf {scratch}/x.tar --files-from {repo}/list.txt"):
        rc, err = run_hook("enforce_bash_scope.py", bash_event(command, repo), strict="1")
        assert rc == 2, f"expected deny for: {command}"
        assert "name the paths on the command line" in err, err

    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"tar -cf {scratch}/x.tar -T {repo}/list.txt", repo),
                       strict="1")
    assert rc == 0, f"reading a file list without --remove-files is not a write: {err}"


# ── tar, checked against the tar that would actually run ────────────────────

def _gnu_tar():
    """GNU tar, or None. macOS ships bsdtar, which rejects `--remove-files`
    outright — so on a stock Mac these rules are unreachable and the honest
    answer is to skip, not to pretend the platform was covered."""
    for name in ("tar", "gtar"):
        exe = shutil.which(name)
        if not exe:
            continue
        out = subprocess.run([exe, "--version"], capture_output=True, text=True)
        if "GNU tar" in out.stdout:
            return exe
    return None


TAR_SHAPES = [
    # (argv template, does real tar delete something in the checkout?)
    (["-cf", "{scratch}/x.tar", "--remove-files", "{repo}/hooks"], True),
    (["-cf{scratch}/x.tar", "--remove-files", "{repo}/hooks"], True),
    (["-cf{scratch}/x.tar", "--remove-files", "-C", "{repo}", "hooks"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files", "-C", "{repo}", "hooks"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files", "-C{repo}", "hooks"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files",
      "-C", "{repo}", "hooks", "-C", "{scratch}", "junk"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files",
      "-C", "{scratch}", "junk", "-C", "{repo}", "hooks"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files", "--directory={repo}", "hooks"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files", "-C", "{root}", "-C", "repo", "hooks"], True),
    (["-cf", "{scratch}/x.tar", "--remove-files", "--", "{repo}/hooks"], True),
    # `--` makes `-C` a filename, so the operand behind it is deleted rather
    # than consumed as a directory. Measured: tar exits 2 (no file named `-C`)
    # and removes the other one anyway.
    (["-cf", "{scratch}/x.tar", "--remove-files", "--", "-C", "{repo}/hooks"], True),
    # The operation and the archive split across separate tokens, with
    # `--remove-files` between them — a letter wrongly treated as taking an
    # argument swallows the flag and the deletion disappears.
    (["-c", "--remove-files", "-f", "{scratch}/x.tar", "{repo}/hooks"], True),
    # An `--exclude` value is a pattern, not an operand: measured, only the
    # scratch directory is removed.
    (["-cf", "{scratch}/x.tar", "--remove-files",
      "--exclude", "{repo}/src", "{scratch}/junk"], False),
    # …and the ones that must survive, or the guard is just a wider refusal
    (["-cf", "{scratch}/x.tar", "--remove-files", "-C", "{scratch}", "junk"], False),
    (["-cf{scratch}/x.tar", "--remove-files", "-C{scratch}", "junk"], False),
    (["-cf", "{scratch}/x.tar", "--remove-files",
      "-C", "{root}/repo", "-C", "../scratch", "junk"], False),
    (["-cf", "{scratch}/x.tar", "{repo}/src"], False),
    (["-czf", "{scratch}/x.tgz", "{repo}/src"], False),
]


def _tar_world(tmp_path):
    """A checkout, a scratch directory, and a cwd that is neither."""
    root = tmp_path / "world"
    repo, scratch, cwd = root / "repo", root / "scratch", root / "cwd"
    for d in (repo / "hooks", repo / "src", scratch / "junk", cwd):
        d.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    for f in (repo / "hooks" / "a.py", repo / "src" / "b.py", scratch / "junk" / "c.py"):
        f.write_text("x\n", encoding="utf-8")
    return root, repo, scratch, cwd


@pytest.mark.parametrize("shape, deletes_in_checkout", TAR_SHAPES,
                         ids=[" ".join(s) for s, _ in TAR_SHAPES])
def test_the_guard_agrees_with_the_tar_that_would_run(tmp_path, shape, deletes_in_checkout):
    """The acceptance criterion is the axis, not the example.

    VERDICT-F-42, F-49, F-56, F-59 and F-62 were all one handler and all found
    the same way: someone tried a spelling nobody had tried. Every one of these
    shapes was checked against GNU tar 1.35 by running it and looking at what
    was gone — `-C` is positional and compounds, and an attached `-cf<archive>`
    made `f` swallow `--remove-files` so the deletion had no visible target.

    Both directions on purpose: a guard that denies everything passes the first
    ten rows and fails the last five.
    """
    root, repo, scratch, cwd = _tar_world(tmp_path)
    argv = [a.format(repo=repo, scratch=scratch, root=root) for a in shape]
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event("tar " + " ".join(argv), cwd), strict="1")
    if deletes_in_checkout:
        assert rc == 2, f"real tar deletes inside the checkout here; guard allowed it: {argv}"
    else:
        assert rc == 0, f"nothing in the checkout is touched, and the guard refused: {err}"


@pytest.mark.parametrize("shape, deletes_in_checkout", TAR_SHAPES,
                         ids=[" ".join(s) for s, _ in TAR_SHAPES])
def test_real_tar_still_behaves_the_way_this_matrix_claims(tmp_path, shape, deletes_in_checkout):
    """The other half, and the reason the matrix can be trusted: run the actual
    tar and look. Without this the table above is a set of assertions about a
    program nobody executed, which is how the guard came to model `-C` as
    last-one-wins when tar has always applied it positionally."""
    exe = _gnu_tar()
    if exe is None:
        pytest.skip("no GNU tar here (macOS ships bsdtar, which has no --remove-files)")
    root, repo, scratch, cwd = _tar_world(tmp_path)
    argv = [a.format(repo=repo, scratch=scratch, root=root) for a in shape]
    subprocess.run([exe, *argv], cwd=cwd, capture_output=True)
    gone_in_checkout = not (repo / "hooks").exists() or not (repo / "src").exists()
    assert gone_in_checkout == deletes_in_checkout, (
        f"the matrix says deletes_in_checkout={deletes_in_checkout}; real tar disagrees "
        f"for: {' '.join(argv)}")


def test_extraction_into_scratch_is_allowed_from_inside_the_checkout(repo, tmp_path):
    """`-C` decides where an extraction lands, and the cwd does not.

    Reported against the shell's cwd instead, a QA session unpacking a fixture
    into its own scratch directory is refused for standing in the wrong place —
    and the run's working directory is nearly always the checkout, so the false
    positive is the common case rather than the rare one.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "x.tar").write_bytes(b"")
    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"tar -xf {scratch}/x.tar -C {scratch}", repo), strict="1")
    assert rc == 0, f"extraction into scratch must not depend on where you stand: {err}"


@pytest.mark.parametrize("spelling", ["gtar", "bsdtar", "/opt/homebrew/bin/gtar", "/usr/bin/tar"])
def test_the_tar_rules_reach_every_spelling_of_tar(tmp_path, spelling):
    """VERDICT-F-67: on macOS `/usr/bin/tar` is bsdtar, which cannot
    `--remove-files` at all, and the GNU tar that can is installed as `gtar` —
    a name the dispatcher matched by exact basename and so never read. Four
    findings' worth of rules were unreachable on the one binary able to do the
    thing. Both directions, as in the matrix above: the deleting shape denied
    under every name, the plain archive allowed under every name.
    """
    root, repo, scratch, cwd = _tar_world(tmp_path)
    deleting = f"{spelling} -cf {scratch}/x.tar --remove-files {repo}/hooks"
    rc, err = run_hook("enforce_bash_scope.py", bash_event(deleting, cwd), strict="1")
    assert rc == 2, f"`{spelling}` deletes inside the checkout and the guard allowed it"
    benign = f"{spelling} -cf {scratch}/x.tar {repo}/src"
    rc, err = run_hook("enforce_bash_scope.py", bash_event(benign, cwd), strict="1")
    assert rc == 0, f"a plain archive of the checkout is a read, whatever tar is called: {err}"

    rc, err = run_hook("enforce_bash_scope.py",
                       bash_event(f"tar -xf {scratch}/x.tar -C {repo}/src", repo), strict="1")
    assert rc == 2, "and extraction into the checkout is still refused"
