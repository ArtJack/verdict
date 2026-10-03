"""The maintainer's two pens are refused to the tester as commands, not only as files.

The ledger files — `accepted.json`, `answers.json` — are refused to every writer.
The commands that write them were an unknown command to the Bash guard, so a
tester could run `verdict-accept <project> <its own finding> --cite … --reason …`
and accept its own findings' risks, or answer its own questions. Found while the
file rule (K-D-12) was being closed for 0.90.3. Reading a ledger is not writing
it: `--list` and `--help` pass, and so does everything the harness itself runs.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
SYSTEM_PYTHON = "/usr/bin/python3"
posix_only = pytest.mark.skipif(os.name == "nt", reason="shell command tables, measured on POSIX")


def judge(command, cwd, *, strict="1", python=sys.executable, **who):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    if strict is not None:
        env["VERDICT_STRICT"] = strict
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": command}, "cwd": str(cwd), **who}
    proc = subprocess.run([python, str(HOOKS / "enforce_bash_scope.py")], input=json.dumps(event),
                          capture_output=True, text=True, env=env, encoding="utf-8",
                          errors="replace")
    return proc.returncode, proc.stderr


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    root = tmp_path_factory.mktemp("pens") / "repo"
    (root / ".qa").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


PENS = [
    "verdict-accept myapp MYAPP-F-21 --cite DECISIONS.md --reason 'accepted'",
    "verdict-accept myapp MYAPP-F-21 --revoke",
    "verdict-answer myapp MYAPP-Q-3 --answer 'half-up is the rule'",
    "verdict-answer myapp MYAPP-Q-3 --dismiss",
    "/opt/venv/bin/verdict-accept myapp MYAPP-F-21 --cite x --reason y",
    "python3 /plugin/src/verdict_mcp/accept.py myapp MYAPP-F-21 --cite x --reason y",
    "python3 /plugin/src/verdict_mcp/questions.py myapp MYAPP-Q-3 --answer yes",
    "python -m verdict_mcp.accept myapp MYAPP-F-21 --cite x --reason y",
    "env X=1 verdict-accept myapp MYAPP-F-21 --cite x --reason y",
    "bash -c 'verdict-accept myapp MYAPP-F-21 --cite x --reason y'",
    "git status && verdict-answer myapp MYAPP-Q-3 --answer yes",
]

READS = [
    "verdict-accept myapp --list",
    "verdict-answer myapp --list",
    "verdict-accept --help",
    "verdict-answer -h",
    "python3 /plugin/src/verdict_mcp/accept.py myapp --list",
    "verdict-gate myapp --require-harness --format text",
    "verdict-facts --repo . --qa-root .qa",
    "verdict-finalize --qa-root .qa --judgment .qa/judgment.json",
    "python3 /plugin/src/verdict_mcp/harness.py facts --repo . --qa-root .qa",
    "python3 /plugin/src/verdict_mcp/gate.py myapp --require-harness --min-run-number 4",
    "verdict-validate .qa/state.json",
]


@posix_only
@pytest.mark.parametrize("command", PENS)
def test_the_tester_cannot_run_the_maintainers_pen(command, repo):
    code, err = judge(command, repo)
    assert code == 2, f"allowed: {command}"
    assert "maintainer's pen" in err and "grading its own paper" in err


@posix_only
@pytest.mark.parametrize("command", READS)
def test_reading_a_ledger_and_running_the_harness_are_not_the_pen(command, repo):
    code, err = judge(command, repo)
    assert code == 0, f"refused: {command}\n{err}"


@posix_only
def test_the_pen_is_refused_to_the_agent_and_left_to_the_maintainers_own_shell(repo):
    command = PENS[0]
    assert judge(command, repo, strict=None, agent_type="verdict")[0] == 2
    assert judge(command, repo, strict=None, agent_type="verdict:verdict")[0] == 2
    # No agent named and no strict mode: the maintainer, in their own session.
    assert judge(command, repo, strict=None)[0] == 0
    assert judge(command, repo, strict=None, agent_type="Explore")[0] == 0


@posix_only
@pytest.mark.skipif(not os.path.exists(SYSTEM_PYTHON), reason="no stock python3")
def test_the_rule_holds_on_the_interpreter_hooks_json_starts(repo):
    assert judge(PENS[0], repo, python=SYSTEM_PYTHON)[0] == 2
    assert judge(READS[0], repo, python=SYSTEM_PYTHON)[0] == 0


# ── a command the armed guard cannot read is refused, not waved through ──────────────
#
# An uncaught exception is exit 1, which Claude Code reads as "the hook broke" and lets
# the command run. Found on this file's own rule: inside `bash -c`, the pen's sentinel
# was joined into a path with a NUL in it and `realpath` raised.

@posix_only
def test_a_nul_byte_in_the_command_is_refused_not_a_crash(repo):
    code, err = judge("echo x > src/app.py\x00", repo)
    assert code == 2 and "NUL byte" in err
    # and the unarmed guard still says nothing at all
    assert judge("echo x > src/app.py\x00", repo, strict=None)[0] == 0


@posix_only
def test_a_parser_failure_while_armed_is_a_refusal(repo, tmp_path):
    """The instrument, controlled: a guard whose target check raises must exit 2."""
    broken = tmp_path / "hooks"
    broken.mkdir()
    for name in ("enforce_bash_scope.py", "qa_paths.py"):
        text = (HOOKS / name).read_text(encoding="utf-8")
        if name == "enforce_bash_scope.py":
            anchor = '    """(allowed, resolved-or-reason) for one candidate write target."""\n'
            assert text.count(anchor) == 1
            text = text.replace(anchor, anchor + '    raise ValueError("boom")\n')
        (broken / name).write_text(text, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_STRICT"] = "1"
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": "echo x > src/app.py"}, "cwd": str(repo)}
    proc = subprocess.run([sys.executable, str(broken / "enforce_bash_scope.py")],
                          input=json.dumps(event), capture_output=True, text=True, env=env)
    assert proc.returncode == 2 and "could not be read (ValueError)" in proc.stderr
