"""The tester is launched as the session (`claude --agent verdict`), not asked for in words.

On 2026-10-06 four asked money gates ran from a packet that never asked for the agent: a
generic session at effort `medium`, without Verdict's prompt, and two of the four ended
their turn with no state. A session started as the agent runs on the agent's prompt, tools
and effort; the scope guards know it by name; and its Stop names it, so the never-finalized
rule sees it (0.90.8).
"""

import json
import os
import subprocess
import sys

import pytest

from test_runner import RUNNER, write_stub
from verdict_mcp.runner import (AGENT_PROMPT, DEFAULT_PROMPT, agent_effort, flag_refused,
                                agent_flags)


@pytest.fixture()
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# scratch\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "x@y"],
                 ["config", "user.name", "t"], ["add", "."], ["commit", "-q", "-m", "b"]):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)
    return repo


def _stub(tmp_path, record, refuses=False):
    """A `claude` that appends every launch's argv to `record`; the old one refuses
    `--agent` the way the CLI's option parser does, before any model is called."""
    refusal = ("if '--agent' in sys.argv:\n"
               "    sys.stderr.write(\"error: unknown option '--agent'\" + chr(10))\n"
               "    sys.exit(1)\n") if refuses else ""
    return write_stub(
        tmp_path,
        "import json, sys\n"
        f"open({str(record)!r}, 'a').write(json.dumps(sys.argv[1:]) + chr(10))\n"
        + refusal + "print('looked around, wrote nothing')\n",
        name="claude-old" if refuses else "claude-new")


def _run(tmp_path, repo, stub, *extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(tmp_path / "home")
    return subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo), "--claude-cmd", str(stub),
         "--model", "opus", *extra],
        capture_output=True, text=True, env=env)


def _launches(record):
    return [json.loads(line) for line in record.read_text(encoding="utf-8").splitlines()]


def _value(argv, flag):
    return argv[argv.index(flag) + 1]


def test_the_tester_is_the_session(tmp_path, repo):
    record = tmp_path / "launches.jsonl"
    proc = _run(tmp_path, repo, _stub(tmp_path, record))
    assert record.is_file(), proc.stderr
    first = _launches(record)[0]
    assert _value(first, "--agent") == "verdict", "the provisioned agent file is the main thread"
    assert _value(first, "--effort") == "xhigh", "the effort the agent file pins"
    assert _value(first, "-p") == AGENT_PROMPT
    assert "verdict-finalize" in AGENT_PROMPT and "verdict agent" not in AGENT_PROMPT, \
        "a session that is the tester is not told to go and find one"


def test_without_the_agent_file_the_session_is_told_in_words(tmp_path, repo):
    record = tmp_path / "launches.jsonl"
    proc = _run(tmp_path, repo, _stub(tmp_path, record), "--no-provision")
    assert record.is_file(), proc.stderr
    first = _launches(record)[0]
    assert "--agent" not in first and "--effort" not in first, \
        "an agent the CLI cannot load is a failed launch, not a tester"
    assert _value(first, "-p") == DEFAULT_PROMPT


def test_an_older_cli_that_refuses_the_flag_runs_the_tester_the_old_way(tmp_path, repo):
    record = tmp_path / "launches.jsonl"
    proc = _run(tmp_path, repo, _stub(tmp_path, record, refuses=True))
    launches = _launches(record)
    assert "--agent" in launches[0]
    assert all("--agent" not in argv and "--effort" not in argv for argv in launches[1:])
    assert _value(launches[1], "-p") == DEFAULT_PROMPT
    assert len(launches) == 3, \
        "the refusal spent nothing and is no attempt: both attempts are still there"
    assert "does not know --agent" in proc.stderr


def test_an_operators_own_flags_are_kept(tmp_path, repo):
    record = tmp_path / "launches.jsonl"
    _run(tmp_path, repo, _stub(tmp_path, record), "--", "--agent=mine", "--effort", "max")
    first = _launches(record)[0]
    assert "--agent" not in first and first.count("--agent=mine") == 1
    assert first.count("--effort") == 1 and _value(first, "--effort") == "max"


def test_the_effort_is_the_one_the_agent_file_pins(tmp_path):
    agents = tmp_path / ".claude" / "agents"
    agents.mkdir(parents=True)
    agent = agents / "verdict.md"
    agent.write_text("---\nname: verdict\neffort: high\n---\nbody text, effort: max\n",
                     encoding="utf-8")
    assert agent_effort(tmp_path) == "high"
    assert agent_flags(tmp_path, []) == ["--agent", "verdict", "--effort", "high"]
    agent.write_text("---\nname: verdict\n---\neffort: max\n", encoding="utf-8")
    assert agent_effort(tmp_path) == "xhigh", "a word in the body is not the frontmatter"
    assert agent_effort(tmp_path / "nowhere") == "xhigh"
    assert agent_flags(tmp_path / "nowhere", []) == []


def test_only_the_cli_refusing_the_flag_is_a_refusal():
    assert flag_refused("error: unknown option '--agent'\n")
    assert flag_refused("noise\nerror: unknown option '--effort'")
    assert not flag_refused("error: unknown option '--frobnicate'")
    assert not flag_refused("the tester wrote: unknown option --agent, says the old CLI")
    assert not flag_refused(None)
