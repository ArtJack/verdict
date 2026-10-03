"""What a headless session may see, and the flags it is launched with.

The runner handed `claude` the operator's whole environment, and the session
hands its environment to every Bash call the tester makes — hence to the
project's own tests and whatever they spawn: cloud and `gh`/`op` tokens, a
`GIT_DIR` from a hook, the `PYTHONPATH` 0.90.1 stopped leaking (audit
2026-10-02, O-S-2). And "isolated" was `--setting-sources` alone: user-scope
MCP servers live in ~/.claude.json and loaded into a session that skips
permissions (O-S-3); the CLI's own dollar ceiling was never passed (O-S-9).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from test_runner import RUNNER, write_stub
from verdict_mcp.runner import child_env, passthrough_names

SHELL = {"PATH": "/bin", "HOME": "/h", "LANG": "C", "LC_ALL": "C", "TMPDIR": "/t",
         "AWS_SECRET_ACCESS_KEY": "x", "GH_TOKEN": "x", "OP_SERVICE_ACCOUNT_TOKEN": "x",
         "GIT_DIR": "/elsewhere/.git", "GIT_WORK_TREE": "/elsewhere", "PYTHONPATH": "/x",
         "CLAUDE_CODE_OAUTH_TOKEN": "t", "ANTHROPIC_BASE_URL": "u", "VERDICT_HOME": "/v",
         "HTTPS_PROXY": "p", "SSL_CERT_FILE": "/ca.pem", "XDG_CONFIG_HOME": "/c"}


def test_the_child_sees_an_allowlist_not_the_operators_shell():
    env = child_env(SHELL)
    assert set(env) == {"PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "CLAUDE_CODE_OAUTH_TOKEN",
                        "ANTHROPIC_BASE_URL", "VERDICT_HOME", "HTTPS_PROXY", "SSL_CERT_FILE",
                        "XDG_CONFIG_HOME"}


def test_a_named_variable_is_let_through():
    env = child_env(SHELL, ["GH_TOKEN", " ", ""])
    assert "GH_TOKEN" in env and "AWS_SECRET_ACCESS_KEY" not in env


def test_passthrough_names_come_from_the_flag_and_the_environment(monkeypatch):
    monkeypatch.setenv("VERDICT_ENV_PASSTHROUGH", "DATABASE_URL, REDIS_URL")
    args = SimpleNamespace(env_passthrough=["A,B", "C"])
    assert passthrough_names(args) == ["A", "B", "C", "DATABASE_URL", "REDIS_URL"]


# ── through the real runner, with a stub standing in for the CLI ─────────────

@pytest.fixture()
def repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# scratch\n", encoding="utf-8")
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "x@y"],
                 ["config", "user.name", "t"], ["add", "."], ["commit", "-q", "-m", "b"]):
        subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)
    return repo


def _stub(tmp_path, record: Path) -> Path:
    """The runner tests' stub (a .cmd on Windows), recording what it was started with.
    The record's path is a literal in the script: an environment variable would have
    to be let through the allowlist to reach it, which is the thing under test."""
    return write_stub(
        tmp_path,
        "import json, os, sys\n"
        f"open({str(record)!r}, 'w').write(json.dumps({{'argv': sys.argv[1:], "
        "'env': sorted(os.environ)}))\n"
        "print('looked around, wrote nothing')\n", name="claude-env-stub")


def test_the_session_is_launched_isolated_and_capped(tmp_path, repo):
    record = tmp_path / "record.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env.update(VERDICT_HOME=str(tmp_path / "home"), AWS_SECRET_ACCESS_KEY="leak",
               GH_TOKEN="leak", CLAUDE_PROBE="kept", KEEP_ME="named")
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo), "--claude-cmd", str(_stub(tmp_path, record)),
         "--model", "opus", "--max-budget-usd", "3.5", "--mcp-config", "sales-mcp.json",
         "--env-passthrough", "KEEP_ME"],
        capture_output=True, text=True, env=env)
    assert record.is_file(), proc.stderr
    seen = json.loads(record.read_text(encoding="utf-8"))
    argv = seen["argv"]
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--mcp-config") + 1] == "sales-mcp.json"
    assert argv[argv.index("--max-budget-usd") + 1] == "3.5"
    assert "AWS_SECRET_ACCESS_KEY" not in seen["env"] and "GH_TOKEN" not in seen["env"]
    assert "CLAUDE_PROBE" in seen["env"] and "KEEP_ME" in seen["env"]
    assert "VERDICT_STRICT" in seen["env"]


def test_a_budget_that_is_not_a_number_is_refused_before_anything_runs(tmp_path, repo):
    record = tmp_path / "record.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(tmp_path / "home")
    proc = subprocess.run(
        [sys.executable, str(RUNNER), "--repo", str(repo), "--claude-cmd", str(_stub(tmp_path, record)),
         "--model", "opus", "--max-budget-usd", "three"],
        capture_output=True, text=True, env=env)
    assert proc.returncode == 2 and "not a number" in proc.stderr and not record.exists()
