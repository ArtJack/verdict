"""The 0.90.3 guard fixes, each driven the way Claude Code drives a hook.

The audit of 2026-10-02 fed 1,631 command strings to the Bash guard under both
interpreters a plugin is run with. 150 that write the code under test were
allowed; 62 that a QA run needs were refused. Every row below is one of those
strings, or its sibling, and each table has the direction that must stay denied
beside the direction that must stay allowed — a guard that refuses everything
passes the first half of any of them.

Two kinds of test, as in test_hooks.py. The tables assert what the guard says.
`SHELL_SHAPES` also asserts what the *shell* does: every command in it is run by
a real bash inside a throwaway checkout, and the guard has to refuse exactly the
ones that changed something outside `.qa/`. Without that half a table is a set
of claims about a program nobody executed.
"""

import ast
import json
import os
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
# What `python3` is on a stock Mac: 3.9, and the interpreter hooks.json actually
# starts (VERDICT-F-55).
SYSTEM_PYTHON = "/usr/bin/python3"

# The tables are shell command lines, measured on POSIX. On Windows the guard
# tokenizes with shlex's non-POSIX mode, which keeps the quotes on a token; that
# mode was forced over these same tables while they were written (two rows
# differ, both quoted command words) but it was not run on Windows, and a table
# that has not been measured there does not get to claim the platform.
posix_only = pytest.mark.skipif(os.name == "nt", reason="shell command tables, measured on POSIX")


def run_hook(script, payload, *, strict=None, python=sys.executable, cwd=None, home=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    if strict is not None:
        env["VERDICT_STRICT"] = strict
    if home is not None:
        env["VERDICT_HOME"] = str(home)
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    proc = subprocess.run([python, str(HOOKS / script)], input=raw, capture_output=True,
                          text=True, env=env, cwd=cwd, encoding="utf-8", errors="replace")
    return proc.returncode, proc.stderr


def bash(command, cwd, **who):
    return {"hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": command}, "cwd": str(cwd), **who}


def write(path, cwd=None, **who):
    event = {"hook_event_name": "PreToolUse", "tool_name": "Write",
             "tool_input": {"file_path": str(path)}, **who}
    if cwd is not None:
        event["cwd"] = str(cwd)
    return event


def _checkout(root):
    repo = root / "repo"
    (repo / ".qa" / "reports").mkdir(parents=True)
    (repo / ".qa" / "notes.md").write_text("a note\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("b = 2\na = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True)
    (root / "scratch").mkdir()
    return repo


@pytest.fixture()
def checkout(tmp_path):
    """A real checkout with a QA root, code under test, and scratch beside it.

    Real, because the guards read the filesystem: a `.qa/` counts only beside a
    `.git`, and a temp root is scratch only where it is not a checkout.
    """
    return _checkout(tmp_path)


@pytest.fixture(scope="module")
def tree(tmp_path_factory):
    """The same checkout, made once for the tables. The guard reads a command
    line and never runs it, so no row can change the tree for the next."""
    return _checkout(tmp_path_factory.mktemp("tables"))


def judge(command, checkout, **kw):
    """Exit code and reason for one command line, in a strict session."""
    command = (command.replace("@SCRATCH", str(checkout.parent / "scratch"))
               .replace("@REPO", str(checkout)))
    return run_hook("enforce_bash_scope.py", bash(command, checkout), strict="1", **kw)


def refused(command, checkout):
    rc, err = judge(command, checkout)
    assert rc == 2, f"this writes outside the QA root and was allowed: {command}"
    assert "QA root" in err and "Traceback" not in err, err


def allowed(command, checkout):
    rc, err = judge(command, checkout)
    assert rc == 0, f"nothing outside the QA root is written, and the guard refused: {err}"


# ── T0-4: the Bash guard is armed by the caller, not only by the environment ──

TESTERS = [{"agent_type": "verdict"}, {"agent_type": "verdict:verdict"},
           {"agent_type": "acme:verdict"}, {"agent_type": "verdict-rc"},
           {"agent_name": "verdict"}, {"subagent_type": "verdict:verdict"}]
STRANGERS = [{}, {"agent_id": "a1b2"}, {"agent_type": "Explore"},
             {"agent_type": "general-purpose"}, {"agent_type": "verdict-opus-check"},
             {"agent_type": "verdict-root-cause"}, {"agent_type": "myverdict"},
             {"agent_type": "verdict:helper"}, {"agent_type": None}, {"agent_type": 7}]


@pytest.mark.parametrize("who", TESTERS, ids=lambda w: json.dumps(w))
def test_the_bash_guard_is_armed_by_the_agent_the_event_names(checkout, who):
    """T0-4, the Major: `main()` returned on `VERDICT_STRICT` before it had read
    the event, so in every interactive session the tester's Write and Edit were
    refused while its `rm`, `sed -i` and `git checkout` went through. Claude
    Code names the agent in every hook input fired inside a subagent; the write
    guard has always read that, and now this one does.

    No VERDICT_STRICT anywhere in these: the event is the only thing arming it.
    """
    rc, err = run_hook("enforce_bash_scope.py", bash("echo x > src/app.py", checkout, **who))
    assert rc == 2, f"the tester's own redirect into the checkout was allowed for {who}"
    assert "QA root" in err
    assert "the caller is the verdict agent" in err, "the reason should say what armed it"
    # …and the tester still writes its own findings.
    rc, err = run_hook("enforce_bash_scope.py",
                       bash("echo r > .qa/reports/r.md", checkout, **who))
    assert rc == 0, err


@pytest.mark.parametrize("who", STRANGERS, ids=lambda w: json.dumps(w))
def test_nobody_elses_shell_command_is_judged(checkout, who):
    """The other half, and the reason the guard was strict-only for so long:
    the same event fires for the user's own shell and for every other agent, and
    a write heuristic on those would get the plugin uninstalled. An event that
    names no agent is the user. A name that merely contains the word is not the
    tester — `verdict-opus-check` is a read-only reviewer."""
    rc, err = run_hook("enforce_bash_scope.py", bash("rm -rf src", checkout, **who))
    assert rc == 0 and err == "", f"a command that is not the tester's was judged: {err}"


def test_strict_still_arms_it_for_everyone_and_zero_does_not_disarm_the_tester(checkout):
    rc, err = run_hook("enforce_bash_scope.py", bash("rm -rf src", checkout), strict="1")
    assert rc == 2 and "VERDICT_STRICT" in err
    rc, err = run_hook("enforce_bash_scope.py",
                       bash("rm -rf src", checkout, agent_type="verdict:verdict"), strict="0")
    assert rc == 2, "VERDICT_STRICT=0 is the absence of strict mode, not a pass for the tester"


def test_one_rule_names_the_tester_for_all_three_hooks():
    """K-D-13: the write guard asked for `verdict` or `<plugin>:verdict` and the
    Stop hook asked whether the name CONTAINED "verdict". Measured: `verdict-rc`
    — the name eval/run_eval.py provisions the tester under — was the tester to
    one hook and a stranger to the other, and its Write outside the QA root was
    allowed. One function now, and nobody keeps a rule of their own."""
    sys.path.insert(0, str(HOOKS))
    import qa_paths

    for who in TESTERS:
        assert qa_paths.caller_is_verdict(who), who
    for who in STRANGERS:
        assert not qa_paths.caller_is_verdict(who), who
    for junk in (None, [], "verdict", 7):
        assert not qa_paths.caller_is_verdict(junk), "an event that is not one names nobody"

    for script in ("enforce_bash_scope.py", "enforce_write_scope.py", "enforce_run_contract.py"):
        tree = ast.parse((HOOKS / script).read_text(encoding="utf-8"))
        imported = [a.name for n in ast.walk(tree)
                    if isinstance(n, ast.ImportFrom) and n.module == "qa_paths" for a in n.names]
        assert "caller_is_verdict" in imported, f"{script} does not use the shared rule"
        called = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", None) == "caller_is_verdict"]
        assert called, f"{script} imports the shared rule and never asks it"
        own = [n.name for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and "is_verdict" in n.name]
        assert not own, f"{script} keeps a rule of its own: {own}"


@pytest.mark.parametrize("agent, told", [("verdict:verdict", True), ("verdict-rc", True),
                                         ("verdict-opus-check", False),
                                         ("verdict-root-cause", False)])
def test_the_stop_hook_reads_the_same_name_the_guards_do(checkout, tmp_path, agent, told):
    """The Stop hook's half of K-D-13, in the hook itself: a run that measured
    and never finalized is the tester's to finish, and an agent that only has
    the word in its name is somebody finishing beside it."""
    marker = {"started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
              "repo": str(checkout), "git_sha": "abc", "session_id": "sess-9"}
    (checkout / ".qa" / "run-in-progress.json").write_text(json.dumps(marker), encoding="utf-8")
    event = {"cwd": str(checkout), "hook_event_name": "SubagentStop", "session_id": "sess-9",
             "agent_type": agent}
    rc, err = run_hook("enforce_run_contract.py", event, home=tmp_path / "empty")
    assert "Traceback" not in err
    if told:
        assert rc == 2 and "verdict-finalize" in err, f"{agent} is the tester and was not told"
    else:
        assert rc == 0 and err == "", f"{agent} is not the tester and was told to finalize"


# ── K-D-12: the maintainer's ledgers, refused to every caller in every mode ───

@pytest.mark.parametrize("ledger, pen", [("accepted.json", "verdict-accept"),
                                         ("answers.json", "verdict-answer")])
@pytest.mark.parametrize("who", [{}, {"agent_type": "Explore"},
                                 {"agent_type": "verdict:verdict"}],
                         ids=["nobody named", "another agent", "the tester"])
def test_the_ledgers_are_refused_whoever_asks_and_in_whatever_mode(checkout, ledger, pen, who):
    """K-D-12: the write guard refused the ledgers only under VERDICT_STRICT or to
    a caller the event named. So in an interactive session a tester whose event
    carried no agent could write the file that accepts its own findings' risks —
    measured: unidentified caller, `accepted.json`, allowed. Nothing a Write or
    an Edit does to these files is ever right: the maintainer's pen is a
    command, run from outside any session."""
    for strict in (None, "0", "1"):
        rc, err = run_hook("enforce_write_scope.py", write(checkout / ".qa" / ledger, **who),
                           strict=strict)
        assert rc == 2, f"{ledger} was writable for {who} with VERDICT_STRICT={strict}"
        assert pen in err and "grading its own paper" in err, err
    # NotebookEdit names its file differently, and is the same write.
    rc, _ = run_hook("enforce_write_scope.py",
                     {"tool_name": "NotebookEdit",
                      "tool_input": {"notebook_path": str(checkout / ".qa" / ledger)}, **who})
    assert rc == 2


def test_refusing_the_ledgers_to_everyone_takes_nothing_else_away(checkout, tmp_path):
    """The over-correction this must not become: only the two files, and only
    inside a QA root. The tester's own state stays writable, and a scratch file
    that happens to be called accepted.json is not the ledger."""
    for name in ("judgment.json", "questions.json", "accepted.json.bak", "accepted.jsonl"):
        rc, err = run_hook("enforce_write_scope.py", write(checkout / ".qa" / name),
                           strict="1")
        assert rc == 0, f"{name} is the tester's to write: {err}"
    rc, err = run_hook("enforce_write_scope.py", write(tmp_path / "scratch" / "accepted.json"))
    assert rc == 0, f"a file by that name outside any QA root is nobody's ledger: {err}"
    rc, err = run_hook("enforce_write_scope.py", write(checkout / "src" / "app.py"))
    assert rc == 0, "an unnamed caller in a non-strict session is the user, and is left alone"


@posix_only
@pytest.mark.parametrize("command", ["echo '{}' > .qa/accepted.json",
                                     "cp /etc/hosts .qa/answers.json",
                                     "tee .qa/accepted.json", "rm .qa/answers.json",
                                     "cd .qa && echo '{}' > accepted.json",
                                     "(rm .qa/accepted.json)",
                                     "(cd .qa && cp /etc/hosts answers.json)"])
def test_the_bash_guard_keeps_refusing_the_ledgers(checkout, command):
    """Inside the QA root, where every other write is the tester's — and still
    refused, by strict mode and by name alike."""
    rc, err = judge(command, checkout)
    assert rc == 2 and "maintainer" in err, err
    rc, err = run_hook("enforce_bash_scope.py", bash(command, checkout, agent_type="verdict"))
    assert rc == 2 and "maintainer" in err, err


# ── K-D-14: a relative path belongs to the event, not to the hook process ─────

def test_a_relative_write_is_read_against_the_events_directory(checkout, tmp_path):
    """K-D-14: a relative `file_path` was resolved by realpath, which is to say
    against wherever the hook process was started. Both directions: a hook
    started inside `.qa/` read `src/app.py` as QA state, and one started
    anywhere else refused the tester its own report."""
    rc, err = run_hook("enforce_write_scope.py", write("src/app.py", cwd=checkout),
                       strict="1", cwd=checkout / ".qa")
    assert rc == 2, "the event stands in the checkout: src/app.py is the code under test"
    rc, err = run_hook("enforce_write_scope.py", write(".qa/reports/r.md", cwd=checkout),
                       strict="1", cwd=tmp_path)
    assert rc == 0, f"the event stands in the checkout: .qa/reports is its QA root: {err}"
    # An absolute path was never the problem, and still is not.
    rc, _ = run_hook("enforce_write_scope.py", write(checkout / "src" / "app.py", cwd=tmp_path),
                     strict="1", cwd=checkout / ".qa")
    assert rc == 2


@pytest.mark.parametrize("script", ["enforce_bash_scope.py", "enforce_write_scope.py"])
@pytest.mark.parametrize("event", ["[]", '"a string"', "7", "null",
                                   '{"tool_input": "not an object"}',
                                   '{"tool_input": {"command": 7, "file_path": 7}}',
                                   '{"tool_input": {"command": "rm -rf src"}, "cwd": 7}',
                                   '{"agent_type": ["verdict"], "tool_input": {}}'])
def test_a_guard_fails_open_on_json_that_is_not_an_event(script, event):
    """"Malformed input exits 0" covered text that was not JSON. JSON that is not
    an event — a list, a string, a `tool_input` that is not an object — reached
    `.get()` in the write guard and died with a traceback and exit 1. A hook
    that cannot read its event has nothing to refuse."""
    rc, err = run_hook(script, event, strict="1", cwd=str(HOOKS))
    assert "Traceback" not in err, err
    assert rc in (0, 2), "a guard exits 0 or 2, never an interpreter's 1"
    if "rm -rf" not in event:
        assert rc == 0, err


# ── K-D-1 / T0-8: formatters, in the shape that rewrites files ────────────────

FORMATTERS_WRITE = [
    "black .", "black src", "black -q -l 100 src", "isort .", "isort --profile black src",
    "autopep8 -i src/app.py", "autopep8 --in-place -r .", "yapf -i src/app.py", "yapf -ir .",
    "ruff format", "ruff format src", "ruff check --fix src", "ruff check --fix-only .",
    "ruff check . --select I --fix", "ruff check --add-noqa src",
    "gofmt -w src", "goimports -w src", "prettier --write src", "prettier -w src",
    "eslint --fix src", "eslint src --ext .ts --fix",
    "biome format --write src", "biome check --apply src", "biome check --write src",
    "rustfmt src/main.rs", "cargo fmt", "cargo +nightly fmt", "cargo fmt --all",
    "clang-format -i src/a.c", "clang-format -style=file -i src/a.c", "swiftformat .",
    "dart format .", "dart format lib test", "terraform fmt", "terraform fmt -recursive",
    "terraform fmt -diff", "terraform -chdir=src fmt",
    "cd @SCRATCH && terraform -chdir=@REPO/src fmt", "shfmt -w .", "shfmt -l -w scripts",
    "pre-commit run", "pre-commit run --all-files",
    # no flag turns pre-commit's hooks into reports: this one only prints the diff they made
    "pre-commit run --all-files --show-diff-on-failure",
    # …and where it stands is the repository, not the directory
    "cd .qa && pre-commit run --all-files",
    # the spellings a QA run actually uses
    "uvx ruff format", "uvx ruff@0.6.9 format src", "uv run ruff check --fix .",
    "uv run --with black black .", "python3 -m black src", "python -m isort .",
    "python3 -m pre_commit run -a", "npx prettier --write .", "npx -y eslint --fix src",
    "npx @biomejs/biome format --write src", "pnpm exec prettier --write .",
    "yarn dlx prettier --write src", "npm exec -- eslint --fix src",
    "poetry run black .", "pipx run black .", "pipenv run isort .", "hatch run ruff format",
    ".venv/bin/black src", "./node_modules/.bin/prettier --write src",
    "timeout 60 ruff format", "cd src && black .", "bash -c 'ruff format src'",
]
FORMATTERS_REPORT = [
    "black --check src", "black --diff src", "black --check --diff .", "black -c 'x=1'",
    "black --version", "isort --check-only src", "isort -c src", "isort --diff src",
    "autopep8 src/app.py", "autopep8 --diff src/app.py", "yapf src/app.py", "yapf -d src/app.py",
    "ruff check src", "ruff check --diff src", "ruff check --fix --diff src",
    "ruff format --check src", "ruff format --diff src", "ruff --version",
    "ruff check . --output-format=github",
    "gofmt -l .", "gofmt -d .", "goimports -l src",
    "prettier --check src", "prettier -c src", "prettier -l src", "prettier src/app.js",
    "eslint src", "eslint --fix-dry-run src", "biome check src", "biome format src",
    "biome ci src", "rustfmt --check src/main.rs", "rustfmt --emit stdout src/main.rs",
    "cargo fmt --check", "cargo fmt -- --check", "cargo test", "cargo clippy",
    "clang-format src/a.c", "clang-format --dry-run -i src/a.c", "clang-format -n src/a.c",
    "swiftformat --lint .", "dart format -o none .", "dart format --output=show lib",
    "dart analyze", "terraform fmt -check", "terraform fmt -check -recursive",
    "terraform fmt -write=false -diff", "terraform validate", "shfmt -d .", "shfmt -l .",
    "pre-commit --version", "pre-commit run --help", "pre-commit validate-config",
    "uvx ruff check hooks tests", "uv run ruff format --check", "python3 -m black --check src",
    "python -m isort --check-only src", "npx prettier --check src", "npx eslint src",
    "poetry run black --check .",
    # runners and interpreters doing what a QA run needs them for
    "uv run pytest -q", "uv run --no-sync pytest -q", "npm test", "npm run lint", "yarn test",
    "python3 -m pytest -q", "python3 -m json.tool .qa/state.json",
    # a formatter pointed at scratch or at the QA root is nobody's code under test
    "black .qa/notes.py", "prettier --write .qa/report.md", "ruff format @SCRATCH",
    "cd @SCRATCH && ruff format .", "cd @SCRATCH && black .", "cd .qa && isort .",
    "terraform -chdir=@SCRATCH fmt",
]


@posix_only
@pytest.mark.parametrize("command", FORMATTERS_WRITE)
def test_a_formatter_run_over_the_code_under_test_is_refused(tree, command):
    """K-D-1, the audit's only HIGH: `black .`, `ruff format`, `gofmt -w`,
    `prettier --write`, `eslint --fix`, `isort .` and `pre-commit run` were
    unknown commands, and unknown commands are allowed. A tester running the
    project's own format step rewrites the code it is judging — of every
    mutation this guard exists to stop, the one most likely to be an accident."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", FORMATTERS_REPORT)
def test_the_same_tools_asked_only_to_report_are_the_lint_gate(tree, command):
    """And the half that keeps strict mode switched on: `black --check`, `ruff
    format --diff`, `gofmt -l`, `prettier --check` are how a QA run measures the
    format gate. A denylist of names would have refused all of them."""
    allowed(command, tree)


# ── K-D-2 / K-D-3: git verbs that write, and git spellings that only read ─────

GIT_WRITES = [
    # a read verb told to write a file (K-D-2)
    "git log --output=src/app.py", "git log --output src/app.py", "git diff --output=src/app.py",
    "git show --output=src/app.py HEAD", "git shortlog --output=src/app.py HEAD",
    "git stash show -p --output=src/app.py", "git reflog show --output=src/app.py",
    "git format-patch -1", "git format-patch -1 -o src", "git format-patch -1 -osrc",
    "git format-patch -1 --output-directory src", "git archive HEAD -o src/x.tar",
    "git archive --output=src/x.tar HEAD", "git bundle create src/x.bundle HEAD",
    "git -C src log --output=app.py",
    # working-tree, index, ref and remote writers the mutator set never had (K-D-3)
    "git checkout-index -a -f", "git read-tree -m -u HEAD", "git read-tree --empty",
    "git add -A", "git add src/app.py", "git mergetool", "git fetch origin", "git fetch",
    "git remote add up /x", "git remote set-url origin /x", "git remote -v add up /x",
    "git remote remove origin", "git symbolic-ref HEAD refs/heads/other",
    "git symbolic-ref -d refs/x", "git clone /x y", "git clone /x", "git init",
    "git init src/nested",
    # a dry run that is taken back is not one
    "git clean -n --no-dry-run -f", "git clean -n --no-dry -f",
    "git clean --dry-run --no-dry-run -f", "git push -n --no-dry-run origin main",
    # `-n` is not --dry-run everywhere
    "git commit -n -m x", "git fetch -n origin", "git merge -n feature",
    # a word that is only a value where it stands
    'git commit -m "--help" -a', "git reflog expire --expire=now --all",
    "git reflog delete HEAD@{0}", "git config set user.name x", "git config unset user.name",
    "git submodule foreach git clean -fd", "git submodule foreach 'git checkout -- .'",
    "git submodule foreach --recursive git clean -q -fd",
]
GIT_READS = [
    "git log --output=.qa/log.txt", "git diff --output=@SCRATCH/d.patch", "git log -n 5",
    "git log --oneline -5 -- src/app.py", "git log --format=%H", "git diff --stat HEAD~1",
    "git show HEAD:src/app.py", "git format-patch -1 --stdout", "git format-patch -1 -o .qa/p",
    "git archive HEAD", "git archive HEAD -o @SCRATCH/x.tar",
    "git bundle create .qa/x.bundle HEAD", "git bundle verify x.bundle",
    "git clean -n", "git clean -n -fdx", "git clean -fdn", "git add -n .", "git add --dry-run .",
    "git rm -n src/app.py", "git push -n origin main", "git prune -n",
    "git read-tree -n -m HEAD", "git fetch --dry-run", "git remote", "git remote -v",
    "git remote show origin", "git remote get-url origin", "git symbolic-ref HEAD",
    "git symbolic-ref --short HEAD", "git mergetool --tool-help",
    "git clone . @SCRATCH/copy", "git -C .qa init", "git -C .qa add -A",
    "git reflog -n 5", "git reflog HEAD", "git reflog show --all",
    "git reflog exists refs/heads/main", "git config get user.name", "git config list",
    "git notes --ref x list", "git bisect visualize", "git sparse-checkout check-rules",
    "git submodule foreach git status", "git submodule foreach --recursive -q git status",
    "git commit --help", "git push --help",
    "git stash show -p", "git stash list",
]


@posix_only
@pytest.mark.parametrize("command", GIT_WRITES)
def test_a_git_command_that_writes_is_refused_whatever_its_verb_is_called(tree, command):
    """K-D-2: `git log --output=src/app.py` overwrites a tracked file, and the
    handler returned before it looked because `log` is in no mutator set. K-D-3:
    `checkout-index -a -f` and `read-tree -m -u HEAD` rewrite the working tree
    and were not in that set either."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", GIT_READS)
def test_a_git_command_that_only_reads_is_allowed_whatever_it_resembles(tree, command):
    """T3-9: `git clean -n`, `git reflog -n 5`, `git reflog HEAD`, `git config
    get`, `git submodule foreach git status` and `git commit --help` were all
    refused as mutations."""
    allowed(command, tree)


# (argv after `git`, must the guard refuse it, does real git change the checkout?)
GIT_MEASURED = [
    (["log", "--output=leak.txt"], True, True),
    (["log", "--output", "leak.txt"], True, True),
    (["diff", "--output=leak.txt"], True, True),
    (["stash", "show", "-p", "--output=leak.txt"], True, True),
    (["reflog", "show", "--output=leak.txt"], True, True),
    (["shortlog", "--output=leak.txt", "HEAD"], True, True),
    (["format-patch", "-1"], True, True),
    (["format-patch", "-1", "-o", "patches"], True, True),
    (["format-patch", "-1", "--stdout"], False, False),
    (["archive", "HEAD", "-o", "leak.tar"], True, True),
    (["archive", "HEAD"], False, False),
    (["bundle", "create", "leak.bundle", "HEAD"], True, True),
    (["clean", "-n"], False, False),
    (["clean", "-fdn"], False, False),
    (["clean", "-n", "--no-dry-run", "-f"], True, True),
    (["clean", "-n", "--no-dry", "-f"], True, True),
    (["clean", "--dry-run", "--no-dry-run", "-f"], True, True),
    (["add", "-n", "."], False, False),
    (["add", "--dry-run", "."], False, False),
    (["add", "-A"], True, True),
    (["rm", "-n", "a.txt"], False, False),
    (["checkout-index", "-a", "-f"], True, True),
    (["read-tree", "--empty"], True, True),
    (["symbolic-ref", "HEAD"], False, False),
    (["symbolic-ref", "HEAD", "refs/heads/keepme"], True, True),
    (["remote"], False, False),
    (["remote", "-v"], False, False),
    (["remote", "add", "up", "/nowhere"], True, True),
    (["remote", "-v", "add", "up", "/nowhere"], True, True),
    (["reflog", "-n", "5"], False, False),
    (["reflog", "HEAD"], False, False),
    (["reflog", "expire", "--expire=now", "--all"], True, True),
    (["config", "get", "user.name"], False, False),
    (["commit", "-m", "--help", "-a"], True, True),
    (["init", "nested"], True, True),
    (["clone", "-q", ".", "copy"], True, True),
    (["submodule", "foreach", "git", "status"], False, False),
]


def _git_world(tmp_path):
    """A checkout with a commit, a second branch, a stash, an uncommitted change
    and an untracked file — something for every shape above to act on."""
    repo = tmp_path / "victim"
    repo.mkdir()

    def run(*argv):
        subprocess.run(["git", "-C", str(repo), *argv], check=True, capture_output=True,
                       text=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True,
                   capture_output=True)
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    (repo / "a.txt").write_text("one\n", encoding="utf-8")
    run("add", "-A")
    run("commit", "-qm", "first")
    run("branch", "keepme")
    (repo / "a.txt").write_text("stashed\n", encoding="utf-8")
    run("stash")
    (repo / "a.txt").write_text("two\n", encoding="utf-8")
    (repo / "junk.txt").write_text("junk\n", encoding="utf-8")
    return repo


def _git_state(repo):
    def out(*argv):
        return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True,
                              text=True).stdout
    files = {str(p.relative_to(repo)): p.read_bytes() for p in sorted(repo.rglob("*"))
             if p.is_file() and ".git" not in p.relative_to(repo).parts}
    return (out("rev-parse", "HEAD"), out("symbolic-ref", "HEAD"),
            out("for-each-ref"), out("status", "--porcelain"), out("config", "--local", "-l"),
            out("reflog"), out("stash", "list"), sorted(files.items()),
            sorted(str(p.relative_to(repo)) for p in repo.glob("*/.git")))


@posix_only
@pytest.mark.parametrize("shape, denied, mutates", GIT_MEASURED,
                         ids=[" ".join(s) for s, _, _ in GIT_MEASURED])
def test_the_guard_agrees_with_git_about_the_verbs_it_did_not_model(tmp_path, shape, denied,
                                                                   mutates):
    repo = _git_world(tmp_path)
    rc, err = run_hook("enforce_bash_scope.py", bash("git " + " ".join(shape), repo),
                       strict="1")
    if denied:
        assert rc == 2, f"this must not be allowed: git {' '.join(shape)}"
    else:
        assert rc == 0, f"nothing changes, and the guard refused: {err}"


@posix_only
@pytest.mark.parametrize("shape, denied, mutates", GIT_MEASURED,
                         ids=[" ".join(s) for s, _, _ in GIT_MEASURED])
def test_real_git_does_what_that_matrix_claims(tmp_path, shape, denied, mutates):
    """The other half: run it and look. This is how `git clean -n --no-dry-run
    -f` got into the table — git spells the option `--[no-]dry-run`, and the
    guard's oldest exemption believed any `--dry-run` it saw."""
    repo = _git_world(tmp_path)
    before = _git_state(repo)
    subprocess.run(["git", *shape], cwd=repo, capture_output=True, text=True)
    assert (_git_state(repo) != before) == mutates, (
        f"the matrix says mutates={mutates}; real git disagrees for: git {' '.join(shape)}")


# ── K-D-10: redirect forms ────────────────────────────────────────────────────

REDIRECT_WRITES = [
    "echo x 1<> src/app.py", "echo x <> src/new.py", "echo x 3<>src/app.py",
    "echo x >& src/app.py", "echo x >&src/app.py", "pytest -q >& out.log",
    "(echo x > src/app.py)", "{ echo x; } > src/app.py",
    # the redirections are taken out of the command, not out of the judgement
    "rm src/app.py 2>&1", "rm -f src/app.py 2>/dev/null", "touch marker >/dev/null 2>&1",
]
REDIRECT_READS = [
    "cmd 2>&1", "cmd >&2", "cmd 1>&2", "exec 3>&-", "exec 3>&1", "exec 3<&0", "cmd >&-",
    "cmd 3>&1 1>&2 2>&3", "pytest -q > /dev/null 2>&1", "pytest -q >& /dev/null",
    "pytest -q 2>&1 | tee .qa/pytest.log", "echo x >& .qa/out.log", "echo x 1<> .qa/out.log",
    "echo '<>' 'a >& b' \"1<> c\"",
    # P-48: `2>&1` and `2>/dev/null` were read as operands of the command beside them
    "mkdir -p .qa/reports 2>&1", "rm -f .qa/tmp.txt 2>/dev/null",
    "touch .qa/marker >/dev/null 2>&1", "cp src/app.py .qa/app.py 2>/dev/null",
    "chmod +x .qa/run.sh 2>&1", "rm -f .qa/x < /dev/null",
]


@posix_only
@pytest.mark.parametrize("command", REDIRECT_WRITES)
def test_every_spelling_of_a_redirect_into_the_checkout_is_refused(tree, command):
    """K-D-10: `N<>file` opens read-write, and the `>` in it follows a `<`,
    which the operator pattern refuses to start on. `>&word` with a word that is
    not a descriptor truncates the file, and every `&…` target was waved through
    as a duplication. Both measured: the file was written."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", REDIRECT_READS)
def test_a_descriptor_is_not_a_file_and_a_redirection_is_not_an_operand(tree, command):
    """`2>&1` duplicates a descriptor. It was also handed to the command beside
    it as a word, so `mkdir -p .qa/reports 2>&1` gave mkdir a directory called
    `2>&1` — which resolves into the checkout — and a write inside the QA root
    was refused for it."""
    allowed(command, tree)


# ── K-D-9: a shell inside a shell, and the syntax in front of a command ───────

DEEP = "bash -c \"sh -c \\\"bash -c \\\\\\\"sh -c 'rm src/app.py'\\\\\\\"\\\"\""
NESTED_WRITES = [
    "bash -lc 'rm src/app.py'", "bash -ec 'rm src/app.py'", "sh -xc 'rm src/app.py'",
    "bash -euxc 'echo x > src/app.py'", "bash -o pipefail -c 'rm src/app.py'", DEEP,
    # a long option with a `c` in it is not the flag, and the flag is still behind it
    "bash --norc -c 'rm src/app.py'", "bash --rcfile /dev/null -c 'rm src/app.py'",
    "(rm src/app.py)", "( rm src/app.py )", "((true)) && (rm src/app.py)",
    "{ rm src/app.py; }", "if true; then rm src/app.py; fi",
    "if false; then :; else rm src/app.py; fi", "if false; then :; elif rm src/app.py; then :; fi",
    "while true; do rm src/app.py; break; done", "for f in a b; do rm src/app.py; done",
    "if rm src/app.py; then echo gone; fi", "! rm src/app.py",
    "true & rm src/app.py", "pytest -q |& tee src/app.py", '"rm" "src/app.py"',
    "bash <<EOF\nrm src/app.py\nEOF", "bash -s <<'EOF'\necho x > src/app.py\nEOF",
    "sudo bash <<EOF\nrm src/app.py\nEOF", "bash <<<'rm src/app.py'",
    "eval 'bash -c \"rm src/app.py\"'",
]
NESTED_READS = [
    "(pytest -q)", "( cd src && ls )", "{ pytest -q; }", "if true; then pytest -q; fi",
    # the `)` that closes a subshell is not part of its last word
    "(git stash list)", "(cd .qa && git worktree list)", "((git stash list))",
    "while read f; do cat \"$f\"; done < .qa/list", "for f in a b; do echo $f; done",
    "! grep -q x src/app.py", "pytest -q & wait", "pytest -q |& tee .qa/out.log",
    "bash -lc 'pytest -q'", "bash -ec 'echo x > .qa/out'", "bash --norc script.sh",
    "bash script.sh -c 'rm src/app.py'", "bash <<EOF\npytest -q\nEOF",
    "bash run.sh <<EOF\nrm src/app.py\nEOF", "python3 - <<'EOF'\nprint('rm src/app.py')\nEOF",
    "bash -lc 'git status'", "sh -c 'cd .qa && echo x > notes.md'",
]


@posix_only
@pytest.mark.parametrize("command", NESTED_WRITES)
def test_a_command_is_found_behind_whatever_the_shell_lets_stand_in_front(tree, command):
    """K-D-9: `bash -lc` was not `-c`, so the string behind it was never read.
    `(rm f)` made the command's name `(rm`, `{ rm f; }` made it `{`, and `if
    true; then rm f; fi` made it `then`. Four levels of `sh -c` walked out past
    a depth cap of three. Measured for the first two: the file was gone."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", NESTED_READS)
def test_the_same_syntax_around_a_read_is_still_a_read(tree, command):
    """`bash script.sh -c '…'` is a script and its arguments, and `bash run.sh
    <<EOF` a script and its input: neither string is the shell's to run."""
    allowed(command, tree)


# ── K-D-6: find -exec and xargs run a command; which one decides ──────────────

FIND_XARGS_WRITES = [
    r"find src -exec sed -i s/a/b/ {} \;", r"find src -name '*.py' -exec sed -i.bak s/a/b/ {} +",
    r"find src -exec sh -c 'rm $1' _ {} \;", r"find src -name '*.py' -ok rm {} \;",
    r"find src -execdir rm {} \;", r"find src -type d -execdir touch marker \;",
    r"find src -exec mv {} {}.bak \;", r"find src -exec git add {} \;",
    "find src -fprint src/app.py", "find src -fprintf src/app.py '%p'", "find src -fls listing",
    "find -L src -name '*.pyc' -delete", "find . -name '*.pyc' -delete",
    "xargs bash -c 'rm $0'", "echo f | xargs rm", "xargs rm < list", "xargs -0 rm",
    "xargs -n1 -P4 rm", "cat list | xargs sed -i s/a/b/", "cat list | xargs -I{} cp {} src/",
    "cat list | xargs -I% mv % src/", "cat list | xargs git add", "cat list | xargs touch",
    "parallel rm ::: src/app.py", "cat list | parallel sed -i s/a/b/ {}",
]
FIND_XARGS_READS = [
    r"find src -name '*.py' -exec grep -l x {} \;", r"find . -name '*.py' -exec wc -l {} +",
    r"find src -name '*.py' -exec sed -n 1p {} \;", r"find src -exec git log -1 -- {} \;",
    r"find src -name '*.py' -exec python3 -m py_compile {} \;",
    r"find .qa -name '*.tmp' -exec rm {} \;", "find .qa -name '*.tmp' -delete",
    "cd .qa && find . -name '*.tmp' -delete", "find src -fprint .qa/list.txt",
    "find src -fprint @SCRATCH/list.txt", "find . -name '*.py' -newer x -print",
    "git ls-files | xargs git log --", "echo x | xargs -I{} git log -1 -- {}",
    "git ls-files | xargs git blame", "echo x | xargs sed -n p", "echo x | xargs perl -ne print",
    "echo x | xargs grep -l needle", "find . -name '*.py' -print0 | xargs -0 wc -l",
    "echo x | xargs -I{} cp {} .qa/", "echo x | xargs -I{} cp {} @SCRATCH/",
    "echo x | parallel git log -1 --", "echo x | parallel sed -n p",
]


@posix_only
@pytest.mark.parametrize("command", FIND_XARGS_WRITES)
def test_find_and_xargs_are_judged_by_the_command_they_run(tree, command):
    """K-D-6: `find -exec` asked whether the next word was a known mutator, so
    `-exec sed -i`, `-exec sh -c`, `-ok` and `-fprint FILE` all went through —
    measured, `find src -exec sed -i s/a/b/ {} \\;` rewrote the file. `xargs`
    asked the same question of a list of four names, and `xargs bash -c 'rm
    $0'` was none of them."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", FIND_XARGS_READS)
def test_find_and_xargs_running_a_read_are_reads(tree, command):
    """…and the same list refused `git`, `sed` and `perl` under xargs whatever
    they were asked to do: `git ls-files | xargs git log --` and `xargs sed -n
    p`, fourteen strings in the audit, all reads."""
    allowed(command, tree)


def test_what_arrives_on_stdin_is_still_refused_by_name(checkout):
    """The stdin rule itself is unchanged: a mutator whose operands the command
    line does not carry cannot be judged, and says so."""
    rc, err = judge("cat list | xargs rm", checkout)
    assert rc == 2 and "name the paths on the command line" in err, err
    rc, err = judge("cd .qa && xargs rm < list", checkout)
    assert rc == 2, "inside the QA root too: the names could be absolute"


# ── K-D-7: a wrapper's flags are the wrapper's ────────────────────────────────

WRAPPED_WRITES = [
    "sudo -n rm src/app.py", "sudo -n -u nobody rm src/app.py", "sudo -- rm src/app.py",
    "time -p rm src/app.py", "command -p rm src/app.py", "exec -a x rm src/app.py",
    "nice -n 5 rm src/app.py", "nice -n5 rm src/app.py", "nice --adjustment=5 rm src/app.py",
    "timeout -s KILL 5 rm src/app.py", "timeout --signal=KILL -k 1 5 rm src/app.py",
    "gtimeout 5 rm src/app.py", "stdbuf -o L rm src/app.py", "stdbuf -oL rm src/app.py",
    "chrt -r 10 rm src/app.py", "taskset 0x1 rm src/app.py", "taskset -c 0 rm src/app.py",
    "ionice -c 3 rm src/app.py", "caffeinate -i rm src/app.py", "builtin eval 'rm src/app.py'",
    "env -i rm src/app.py", "env -u X FOO=1 rm src/app.py", "env -S 'rm src/app.py'",
    "env -C src rm app.py", "env -C .qa rm ../src/app.py",
    "script -q src/app.py pytest", "script src/typescript", "script",
    "script -q /dev/null rm src/app.py", "script -q -c 'rm src/app.py' /dev/null",
    "time -o src/timing.txt pytest", "flock /tmp/l rm src/app.py", "flock src/.lock pytest",
    "sudo env nice -n 1 timeout 5 rm src/app.py",
]
WRAPPED_READS = [
    "sudo -n pytest -q", "time -p pytest -q", "command -p pytest -q", "command -v pytest",
    "command -v rm", "exec -a x pytest -q", "nice -n 10 pytest -q", "timeout -s INT 600 pytest -q",
    "timeout -k 5 600 pytest -q", "stdbuf -o L pytest -q", "chrt -i 0 pytest -q",
    "taskset -c 0 pytest -q", "caffeinate -i pytest -q", "env -u PYTHONPATH pytest -q",
    "env PYTHONPATH=src python -c 'import app'", "env | sort", "env -C .qa rm notes.md",
    "script -q /dev/null pytest -q", "script -q .qa/typescript pytest -q",
    "time -o .qa/timing.txt pytest", "flock @SCRATCH/l pytest -q",
    "sudo -n rm .qa/tmp.txt", "timeout 5 rm -rf .qa/tmp",
]


@posix_only
@pytest.mark.parametrize("command", WRAPPED_WRITES)
def test_the_command_behind_a_wrapper_is_read_whatever_the_wrapper_is_given(tree, command):
    """K-D-7: one set of value-taking flags served every wrapper, and `-n` and
    `-p` were in it — booleans to sudo, time and command. So `sudo -n rm f`
    handed `rm` to `-n` as its value, the FILE became the command, and nothing
    was seen. `script FILE CMD` had its file read as the command."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", WRAPPED_READS)
def test_a_wrapper_around_a_read_or_an_in_scope_write_is_allowed(tree, command):
    allowed(command, tree)


@posix_only
def test_a_command_nested_past_reading_is_refused_not_crashed_on(checkout):
    """A wrapper chain is walked, however long. A chain of commands that each
    read the next — `xargs xargs xargs …` — is recursed into, and several
    hundred deep Python runs out of stack. That used to be impossible (the old
    handlers looked one word ahead and stopped); now that they read on, the
    way out must not be a traceback and exit 1, which the caller treats as
    "hook broken, carry on"."""
    rc, err = judge("env " * 700 + "rm src/app.py", checkout)
    assert rc == 2 and "rm targets" in err, err
    rc, err = judge("env " * 700 + "pytest -q", checkout)
    assert rc == 0, err
    for python in (sys.executable, SYSTEM_PYTHON):
        if not os.path.exists(python):
            continue
        rc, err = judge("xargs " * 700 + "rm src/app.py", checkout, python=python)
        assert "Traceback" not in err, err[-400:]
        assert rc == 2 and "nested too deeply" in err, err[-400:]


# ── K-D-8: where a relative path lands ────────────────────────────────────────

LANDS_OUTSIDE = [
    "pushd .qa && echo x > ../src/app.py", "pushd .qa && popd && echo x > notes.md",
    "cd .qa && cd - && echo x > src/app.py", "cd .qa && cd \"$OLDPWD\" && echo x > src/app.py",
    "cd .qa && cd .. && echo x > src/app.py", "cd .qa; cd -; rm src/app.py",
    "(cd @SCRATCH && true); echo x > out.txt", "cd .qa && (cd .. && echo x > notes.md)",
    "cd .qa | true; echo x > notes.md", "true | cd @SCRATCH; echo x > pwned.py",
    "sudo cd @SCRATCH; echo x > pwned.py", "env cd @SCRATCH; echo x > pwned.py",
    "cd .qa && bash -c 'cd .. && echo x > src/app.py'", "echo x > $PWD/src/app.py",
    "echo x > \"$(pwd)/src/app.py\"", "cd && echo x > notes.md",
    # a directory the line does not name is judged where the line started
    "cd \"$(git rev-parse --show-toplevel)\" && echo x > src/app.py",
    "cd .qa && cd $NOPE_UNSET_VAR && echo x > notes.md",
    "cd .qa && cd `dirname x` && echo x > notes.md",
]
LANDS_INSIDE = [
    "cd .qa && pytest 2>&1 | tee report.log", "cd .qa && echo x | tee out",
    "cd .qa && echo x > notes.md", "cd .qa && cd reports && echo x > r.md",
    "pushd .qa && echo x > a.md && popd && echo y > .qa/b.md",
    "pushd .qa && pushd reports && popd && echo x > notes.md",
    "cd src && cd - && echo x > .qa/out", "cd .qa && (cd .. && pytest -q) && echo x > notes.md",
    "(cd @SCRATCH && echo x > out.txt)", "cd @SCRATCH && echo x > out.txt",
    "cd @SCRATCH && pytest -q 2>&1 | tee out.log", "command cd .qa && echo x > notes.md",
    "cd .qa && echo x > $PWD/out", "cd .qa && echo x > \"$(pwd)/out\"",
    "cd .qa && echo x > `pwd`/out", "cd .qa && bash -c 'cd .. && echo x > .qa/out'",
    "bash -c 'cd @SCRATCH && echo x > out.txt'",
    "cd \"$(git rev-parse --show-toplevel)\" && echo x > .qa/out",
    "cd $(git rev-parse --show-toplevel) && pytest -q > .qa/out.txt",
    "cd \"$(dirname \"$0\")\" && pytest -q",
]


@posix_only
@pytest.mark.parametrize("command", LANDS_OUTSIDE)
def test_a_relative_write_is_judged_where_it_really_lands(tree, command):
    """K-D-8, the bypass half: the guard followed `cd DIR` and nothing else, so
    after `cd .qa && cd -` or `pushd .qa && … ../src` it still believed it stood
    in `.qa` and allowed a write that landed in the checkout. Measured."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", LANDS_INSIDE)
def test_a_relative_write_into_the_qa_root_is_not_refused_for_where_it_started(tree,
                                                                             command):
    """K-D-8, the false-denial half: a `|` reset the directory to the tool's
    own, so `cd .qa && pytest 2>&1 | tee report.log` — writing the test log
    where the tester keeps its logs — was refused as a write to the checkout."""
    allowed(command, tree)


# ── K-D-11: commands that write the file they are handed ──────────────────────

WRITERS = [
    "gzip src/app.py", "gzip -k src/app.py", "gzip -9v src/app.py", "gunzip src/app.py.gz",
    "bzip2 src/app.py", "bunzip2 src/app.py.bz2", "xz src/app.py", "unxz src/app.py.xz",
    "zstd src/app.py", "unzstd src/app.py.zst", "zstd src/app.py -o src/app.zst",
    "sort -o src/app.py src/app.py", "sort src/app.py -o src/app.py", "sort -uo src/app.py x",
    "sort --output=src/app.py x", "split -l 1 src/app.py src/part", "split -l 1 src/app.py",
    "csplit src/app.py 1", "csplit -f src/xx src/app.py 1", "cat x | sponge src/app.py",
    "iconv -f utf8 -t ascii -o src/app.py src/app.py", "dos2unix src/app.py",
    "unix2dos src/app.py", "dos2unix -n @SCRATCH/in.txt src/app.py", "ditto src/app.py src/b.py",
    "rename 's/a/b/' src/app.py", "rename .py .txt src/app.py", "mkfifo src/fifo",
    "mkfifo -m 600 src/fifo",
    "mknod src/dev c 1 3", "unzip -o z.zip -d src", "unzip -o z.zip", "unzip z.zip -d src",
    "zip -r src/x.zip src", "zip -m @SCRATCH/x.zip src/app.py", "7z x x.7z -osrc", "7z x x.7z",
    "7z a src/x.7z src", "cpio -id < x.cpio", "cpio -idmv < x.cpio", "pax -r -f x.tar",
    "unrar x x.rar src", "curl -o src/app.py http://127.0.0.1/x",
    "curl -sSLo src/app.py http://127.0.0.1/x", "curl --output src/app.py http://127.0.0.1/x",
    "curl -O http://127.0.0.1/app.py", "curl -s -D src/headers.txt http://127.0.0.1/x",
    "wget http://127.0.0.1/x", "wget -O src/app.py http://127.0.0.1/x",
    "wget -P src http://127.0.0.1/x", "wget --output-document=src/app.py http://127.0.0.1/x",
    "truncate -s 0 src/app.py", "truncate -s0 src/app.py", "truncate --size=0 src/app.py",
    "patch -p1 < fix.diff", "patch src/app.py fix.diff", "patch -p1 -i fix.diff",
]
WRITERS_ELSEWHERE = [
    "gzip -c src/app.py > /tmp/x.gz", "gzip -dc .qa/log.gz", "gunzip -c src/app.py.gz | head",
    "gzip -t src/app.py.gz", "gzip -l src/app.py.gz", "xz -kc src/app.py > @SCRATCH/app.xz",
    "zstd -c src/app.py", "zstd src/app.py -o @SCRATCH/app.zst", "gzip .qa/big.log",
    "sort src/app.py", "sort -u -k2 -t, src/app.py", "sort src/app.py -o .qa/sorted",
    "sort -o @SCRATCH/sorted src/app.py", "split -l 100 src/app.py .qa/part-",
    "cd .qa && split -l 100 ../src/app.py", "iconv -f utf8 -t ascii src/app.py",
    "iconv -f utf8 -t ascii -o .qa/app.txt src/app.py", "dos2unix -n src/app.py .qa/app.py",
    "dos2unix -i src/app.py", "rename -n 's/a/b/' src/app.py", "mkfifo .qa/fifo",
    "mkfifo -m 600 .qa/fifo",
    "unzip -l z.zip", "unzip -p z.zip member", "unzip -o z.zip -d .qa/unpacked",
    "unzip -o z.zip -d @SCRATCH", "zip -r @SCRATCH/x.zip src", "zip -sf x.zip", "7z l x.7z",
    "7z x x.7z -o@SCRATCH", "cpio -it < x.cpio", "cd .qa && cpio -id < ../x.cpio",
    "pax -f x.tar", "unrar l x.rar", "curl -sI http://127.0.0.1/x",
    "curl -s http://127.0.0.1:8000/health",
    "curl -sS -o /dev/null -w '%{http_code}' http://127.0.0.1:8000",
    "curl -s -o .qa/resp.html http://127.0.0.1:8000", "curl -sD - http://127.0.0.1/x",
    "curl -s http://127.0.0.1/x > .qa/resp.html", "wget -q -O - http://127.0.0.1:8000",
    "wget -q -O .qa/resp.html http://127.0.0.1:8000", "wget -q -P .qa http://127.0.0.1:8000",
    "wget --spider http://127.0.0.1:8000", "cd @SCRATCH && wget http://127.0.0.1/x",
    "truncate -s 0 .qa/log", "truncate -s0 .qa/log", "truncate -r src/app.py .qa/log",
    "patch --dry-run -p1 < fix.diff", "patch .qa/a .qa/fix.diff", "patch -o .qa/out src/app.py d",
    "cd .qa && patch a fix.diff",
]


@posix_only
@pytest.mark.parametrize("command", WRITERS)
def test_a_command_that_writes_the_file_it_is_handed_is_refused(tree, command):
    """K-D-11: `gzip f` leaves `f.gz` where `f` was, and `sort -o f f`
    overwrites its own input — both measured — and neither was a command the
    guard knew. Nor `split`, `sponge`, `iconv -o`, `dos2unix`, the archive
    extractors other than tar, `curl -o` or `wget`, which saves where it
    stands by default."""
    refused(command, tree)


@posix_only
@pytest.mark.parametrize("command", WRITERS_ELSEWHERE)
def test_the_same_commands_reading_or_writing_in_scope_are_allowed(tree, command):
    """`gzip -c f > scratch` reads `f`. `truncate -s 0 .qa/log` was refused
    because `0` was read as a path (T3-9) — and is still read as an option's
    value, not skipped as "the first operand", or `truncate -s0 src/app.py`
    would have walked through with its file unread."""
    allowed(command, tree)


# ── K-D-4, K-D-5, K-D-15: what a QA run was refused ───────────────────────────

NOT_A_WRITE = [
    # a heredoc body is data (K-D-4)
    "cat > .qa/notes.md <<'EOF'\nrm -rf src\ncp a b\ngit commit -am x\nEOF",
    "cat > .qa/judgment.json <<'EOF'\n{\"cmd\": \"rm src/app.py\"}\nEOF\necho done",
    "cat <<'EOF'\nrm -rf src\nEOF", "cd .qa && cat > j.json <<EOF\nrm src\nEOF",
    "cat <<-'EOF' > .qa/x\n\tsed -i s/a/b/ src/app.py\n\tEOF",
    "python3 - <<'EOF'\nimport os\nprint(os.getcwd())  # rm src/app.py\nEOF",
    # the script is not a file (K-D-5)
    "sed -i '' 's/a/b/' .qa/notes.md", "sed -i s/a/b/ .qa/notes.md", "sed -i.bak s/a/b/ .qa/notes.md",
    "sed -i .bak s/a/b/ .qa/notes.md", "sed -n -i '' p .qa/notes.md",
    "sed -i '' -e s/a/b/ -e s/c/d/ .qa/notes.md", "sed -E -i 's/(a)/\\1/' .qa/notes.md",
    "sed --in-place 's/[a-z]*/x/' .qa/notes.md", "perl -i -pe s/a/b/ .qa/notes.md",
    "perl -pi -e 's/a.*/b/' .qa/notes.md", "perl -i.bak -pe s/a/b/ .qa/notes.md",
    "cd .qa && sed -i '' s/a/b/ notes.md", "cd @SCRATCH && sed -i '' s/a/b/ src/app.py",
    # an `i` in an option is not `-i`
    "perl -Mstrict -ne 'print' src/app.py", "perl -Ilib -MList::Util -e 1 src/app.py",
    "sed -n -e '/import/p' src/app.py", "sed -l 80 -n p src/app.py",
    # scratch is scratch (K-D-15)
    "echo x > /var/tmp/verdict-probe.txt", "cp src/app.py /var/tmp/", "tee /private/var/tmp/x",
]
STILL_A_WRITE = [
    "cat > .qa/notes.md <<'EOF'\nfine\nEOF\nrm src/app.py",
    "cat <<'EOF' > src/app.py\nx\nEOF", "cat > src/app.py <<'EOF'\nx\nEOF",
    "sed -i '' 's/a/b/' src/app.py", "sed -i s/a/b/ src/app.py", "sed -i.bak s/a/b/ src/app.py",
    "sed -i .bak s/a/b/ src/app.py", "sed -I .bak s/a/b/ src/app.py", "gsed -i s/a/b/ src/app.py",
    "sed -ie s/a/b/ src/app.py", "sed -i -e s/a/b/ src/app.py", "sed -n -i p src/app.py",
    "sed s/a/b/ -i src/app.py", "sed --in-place=.bak s/a/b/ .qa/notes.md src/app.py",
    # GNU sed's `-i` takes no word of its own: with the script given by -e, this edits `.env`
    "sed -e s/a/b/ -i .env", "sed -e s/a/b/ -i .env .qa/notes.md",
    "perl -i -pe s/a/b/ src/app.py", "perl -pi -e s/a/b/ src/app.py",
    "perl -pie s/a/b/ src/app.py", "perl -i fix.pl src/app.py",
]


@posix_only
@pytest.mark.parametrize("command", NOT_A_WRITE)
def test_what_a_qa_run_needs_is_no_longer_refused(tree, command):
    """T3-9. A heredoc body was tokenized as a command (K-D-4): the redirect
    scan read the masked view and the tokenizer was handed the raw text, so a
    note whose first word was `rm` was a deletion. The sed script was yielded as
    a path (K-D-5): `s/a/b/` resolves into the checkout, so every in-place edit
    inside `.qa/` was refused with the script named as the target. `/var/tmp`
    was not scratch (K-D-15)."""
    allowed(command, tree)


@posix_only
@pytest.mark.parametrize("command", STILL_A_WRITE)
def test_and_none_of_that_was_bought_with_a_bypass(tree, command):
    """Each rule above, in the direction it must not move. The file behind the
    script is still a file; a command after a heredoc is still a command."""
    refused(command, tree)


def test_the_reason_names_the_file_and_not_the_script(checkout):
    rc, err = judge("sed -i '' 's/a/b/' src/app.py", checkout)
    assert rc == 2 and "app.py" in err and "s/a/b/" not in err, err


# ── the shell that would actually run it ──────────────────────────────────────

# (command, does a real bash change anything in the checkout outside `.qa/`?)
SHELL_SHAPES = [
    # redirect forms (K-D-10)
    ("echo x >& src/app.py", True),
    ("echo x >&src/app.py", True),
    ("echo x 1<> src/app.py", True),
    ("echo x <> src/new.py", True),
    ("echo x >&2", False),
    ("echo x 2>&1 >/dev/null", False),
    ("echo x >& .qa/out.log", False),
    ("mkdir -p .qa/reports 2>&1", False),
    ("rm -f .qa/tmp.txt 2>/dev/null", False),
    ("rm src/app.py 2>&1", True),
    # compound forms and nesting (K-D-9)
    ("(rm src/app.py)", True),
    ("{ rm src/app.py; }", True),
    ("if true; then rm src/app.py; fi", True),
    ("if false; then :; else rm src/app.py; fi", True),
    ("while true; do rm src/app.py; break; done", True),
    ("if rm src/app.py; then :; fi", True),
    ("! rm src/app.py", True),
    ("true & rm src/app.py", True),
    ('"rm" "src/app.py"', True),
    ("bash -ec 'rm src/app.py'", True),
    (DEEP, True),
    ("bash <<EOF\nrm src/app.py\nEOF", True),
    ("bash <<<'rm src/app.py'", True),
    ("(true)", False),
    ("{ ls > /dev/null; }", False),
    ("bash -ec 'echo x > .qa/out'", False),
    # heredoc bodies (K-D-4)
    ("cat > .qa/notes.md <<'EOF'\nrm -rf src\nEOF", False),
    ("cat <<'EOF' > /dev/null\nrm -rf src\nEOF", False),
    ("cat > src/app.py <<'EOF'\nx\nEOF", True),
    # where a relative path lands (K-D-8)
    ("cd .qa && cd - > /dev/null && echo x > probe.txt", True),
    ("pushd .qa > /dev/null && echo x > ../src/probe.txt", True),
    ("pushd .qa > /dev/null && popd > /dev/null && echo x > probe.txt", True),
    ("pushd .qa > /dev/null && pushd reports > /dev/null && popd > /dev/null "
     "&& echo x > probe.txt", False),
    ("cd .qa && cd \"$OLDPWD\" && echo x > probe.txt", True),
    ("(cd .qa && true); echo x > probe.txt", True),
    ("cd .qa && (cd .. && true) && echo x > probe.txt", False),
    ("cd .qa && (cd .. && echo x > probe.txt)", True),
    ("cd .qa | true; echo x > probe.txt", True),
    ("cd .qa && echo x | tee probe.txt > /dev/null", False),
    ("cd .qa && echo x > probe.txt", False),
    ("cd .qa && echo x > \"$PWD/probe.txt\"", False),
    ("cd .qa && echo x > \"$(pwd)/probe.txt\"", False),
    ("echo x > \"$PWD/probe.txt\"", True),
    ("cd src && cd - > /dev/null && echo x > .qa/probe.txt", False),
    ("command cd .qa && echo x > probe.txt", False),
    ("cd .qa && bash -c 'cd .. && echo x > probe.txt'", True),
    ("cd .qa && bash -c 'cd .. && echo x > .qa/probe.txt'", False),
    ("cd \"$(git rev-parse --show-toplevel)\" && echo x > probe.txt", True),
    ("cd \"$(git rev-parse --show-toplevel)\" && echo x > .qa/probe.txt", False),
    # wrappers (K-D-7)
    ("time -p rm src/app.py", True),
    ("command -p rm src/app.py", True),
    ("(exec -a x rm src/app.py)", True),
    ("nice -n 5 rm src/app.py", True),
    ("env -S 'rm src/app.py'", True),
    ("env FOO=1 rm src/app.py", True),
    ("command -v rm > /dev/null", False),
    ("nice -n 5 true", False),
    # find and xargs (K-D-6)
    (r"find src -name '*.py' -exec rm {} \;", True),
    ("find src -name '*.py' -exec sh -c 'rm \"$1\"' _ {} \\;", True),
    (r"find src -name '*.py' -exec sed -i.bak s/a/z/ {} \;", True),
    (r"find src -name '*.py' -exec cat {} \; > /dev/null", False),
    (r"find .qa -name '*.md' -exec rm {} \;", False),
    ("echo src/app.py | xargs rm", True),
    ("echo src/app.py | xargs bash -c 'rm $0'", True),
    ("echo src/app.py | xargs cat > /dev/null", False),
    ("echo src/app.py | xargs sed -n p > /dev/null", False),
    ("git ls-files | xargs git log --oneline -- > /dev/null", False),
    # commands that write the file they are handed (K-D-11)
    ("gzip src/app.py", True),
    ("gzip -k src/app.py", True),
    ("gzip -c src/app.py > .qa/app.gz", False),
    ("sort -o src/app.py src/app.py", True),
    ("sort src/app.py -o .qa/sorted", False),
    ("split -l 1 src/app.py src/part", True),
    ("split -l 1 src/app.py .qa/part", False),
    ("mkfifo src/fifo", True),
    ("mkfifo .qa/fifo", False),
    ("tee src/app.py < /dev/null", True),
    # the script is not a file (K-D-5)
    ("sed -i.bak s/a/z/ src/app.py", True),
    ("sed -i.bak s/a/z/ .qa/notes.md", False),
    ("sed -n 1p src/app.py > /dev/null", False),
    ("perl -i -pe s/a/z/ src/app.py", True),
    ("perl -i -pe s/a/z/ .qa/notes.md", False),
    ("perl -ne 'print' src/app.py > /dev/null", False),
]


def _shell_world(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".qa" / "reports").mkdir(parents=True)
    (repo / ".qa" / "notes.md").write_text("a note\n", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("b = 2\na = 1\n", encoding="utf-8")
    for argv in (["init", "-q", "-b", "main"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "first"]):
        subprocess.run(["git", *argv], cwd=repo, check=True, capture_output=True)
    return repo


def _outside_the_qa_root(repo):
    """Everything in the checkout that is not QA state: what a QA run must leave alone."""
    seen = {}
    for path in sorted(repo.rglob("*")):
        rel = path.relative_to(repo)
        if rel.parts[0] in (".git", ".qa"):
            continue
        mode = path.lstat().st_mode
        seen[str(rel)] = path.read_bytes() if stat.S_ISREG(mode) else stat.S_IFMT(mode)
    return seen


def _runnable(command):
    """Skip a row whose tool is not installed, rather than measure its absence."""
    if os.name == "nt" or not shutil.which("bash"):
        pytest.skip("needs a POSIX bash to measure against")
    for tool in ("gzip", "split", "mkfifo", "perl", "nice", "xargs", "find", "sed", "sort", "tee"):
        if command.split()[0] == tool and not shutil.which(tool):
            pytest.skip(f"no {tool} here")


@pytest.mark.parametrize("command, writes_outside", SHELL_SHAPES,
                         ids=[c for c, _ in SHELL_SHAPES])
def test_the_guard_agrees_with_the_shell_that_would_run(tmp_path, command, writes_outside):
    """Refused exactly when a real bash would change something outside `.qa/`.

    Both directions in one table, as with git and tar: the guard is a model of
    the shell, and a model is only as good as the last time somebody ran the
    thing it models. Half of what 0.90.3 fixes was a spelling nobody had run."""
    _runnable(command)
    repo = _shell_world(tmp_path)
    rc, err = run_hook("enforce_bash_scope.py", bash(command, repo), strict="1")
    if writes_outside:
        assert rc == 2, f"real bash changes the checkout here, and the guard allowed it: {command}"
    else:
        assert rc == 0, f"nothing outside .qa/ changes, and the guard refused: {err}"


@pytest.mark.parametrize("command, writes_outside", SHELL_SHAPES,
                         ids=[c for c, _ in SHELL_SHAPES])
def test_real_bash_does_what_that_table_claims(tmp_path, command, writes_outside):
    """The other half: run it, in a checkout made for the purpose, and diff."""
    _runnable(command)
    repo = _shell_world(tmp_path)
    before = _outside_the_qa_root(repo)
    subprocess.run(["bash", "-c", command], cwd=repo, capture_output=True, timeout=60,
                   stdin=subprocess.DEVNULL)
    assert (_outside_the_qa_root(repo) != before) == writes_outside, (
        f"the table says writes_outside={writes_outside}; real bash disagrees for: {command}")


# ── the interpreter the plugin is actually started with ───────────────────────

ON_THE_FLOOR = [
    ("echo x > src/app.py", 2), ("black .", 2), ("uvx ruff format", 2),
    ("git log --output=src/app.py", 2), ("git checkout-index -a -f", 2),
    ("echo x 1<> src/app.py", 2), ("echo x >& src/app.py", 2), ("bash -lc 'rm src/app.py'", 2),
    ("(rm src/app.py)", 2), ("if true; then rm src/app.py; fi", 2), (DEEP, 2),
    (r"find src -exec sed -i s/a/b/ {} \;", 2), ("xargs bash -c 'rm $0'", 2),
    ("sudo -n rm src/app.py", 2), ("script -q src/app.py pytest", 2),
    ("pushd .qa && echo x > ../src/app.py", 2), ("cd .qa && cd - && echo x > src/app.py", 2),
    ("gzip src/app.py", 2), ("sort -o src/app.py src/app.py", 2),
    ("curl -o src/app.py http://127.0.0.1/x", 2), ("unzip -o z -d src", 2),
    ("bash <<EOF\nrm src/app.py\nEOF", 2), ("echo '{}' > .qa/accepted.json", 2),
    ("black --check src", 0), ("git log -n 5", 0), ("git clean -n", 0), ("git remote -v", 0),
    ("cmd 2>&1", 0), ("exec 3>&-", 0), ("(pytest -q)", 0), ("echo x | xargs sed -n p", 0),
    ("git ls-files | xargs git log --", 0), ("cd .qa && pytest 2>&1 | tee report.log", 0),
    ("cd .qa && echo x > notes.md", 0), ("gzip -c src/app.py > /tmp/x.gz", 0),
    ("curl -sI http://127.0.0.1/x", 0), ("truncate -s 0 .qa/log", 0),
    ("sed -i '' 's/a/b/' .qa/notes.md", 0), ("echo x > /var/tmp/verdict-probe.txt", 0),
    ("cat > .qa/notes.md <<'EOF'\nrm -rf src\nEOF", 0), ("git reflog -n 5", 0),
]


@posix_only
@pytest.mark.skipif(not os.path.exists(SYSTEM_PYTHON), reason="no system python3 here")
@pytest.mark.parametrize("command, expected", ON_THE_FLOOR, ids=[c for c, _ in ON_THE_FLOOR])
def test_the_guard_says_the_same_thing_under_the_system_python(tree, command, expected):
    """`hooks.json` spells the interpreter `python3`, and on a stock Mac that is
    /usr/bin/python3 = 3.9 — not the one this suite runs under. One row for
    every rule 0.90.3 added, in both directions, under that interpreter: the
    Bash guard once died on import there while the write guard beside it went
    on denying (VERDICT-F-55), and a rule that only exists on 3.13 is not
    installed for most of the people who have it."""
    rc, err = judge(command, tree, python=SYSTEM_PYTHON)
    assert "Traceback" not in err, err
    assert rc == expected, f"{command!r} under {SYSTEM_PYTHON}: exit {rc}: {err}"


@pytest.mark.skipif(not os.path.exists(SYSTEM_PYTHON), reason="no system python3 here")
@pytest.mark.parametrize("script", ["enforce_bash_scope.py", "enforce_write_scope.py",
                                    "enforce_run_contract.py"])
def test_every_hook_this_release_touched_still_starts_under_the_system_python(script, checkout):
    """Armed by identity, with no VERDICT_STRICT: the path 0.90.3 added, on the
    interpreter it will run on."""
    event = dict(bash("echo x > src/app.py", checkout, agent_type="verdict:verdict"),
                 **write(checkout / "src" / "app.py"))
    event["tool_input"] = {"command": "echo x > src/app.py",
                           "file_path": str(checkout / "src" / "app.py")}
    rc, err = run_hook(script, event, python=SYSTEM_PYTHON)
    assert "Traceback" not in err and "Error" not in err, err
    assert rc == (0 if script == "enforce_run_contract.py" else 2), err
