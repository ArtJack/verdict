"""A link is a second name for a file somewhere else — the hooks' half.

The release's own Opus gate (2026-10-03) showed the harness writing through links planted
in a QA root: `ln -s ../src/app.py .qa/facts.json`, then `verdict-facts`. The harness
refuses such a root now (tests/test_qa_root_links.py). Here: the Bash guard refuses the
`ln` that would build one, refuses a hard link that gives a file in the checkout a name in
scratch — every other rule judges a write by its path, and that is the one write no
`realpath` can see — and refuses `verdict-issues --create`, which posts under the
maintainer's name. And the Stop hook does not write its "told once" note through a marker
that is a link.

No import of the package: this file runs on the hooks' own floor, the `python3` a stock
Mac starts them with.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
posix_only = pytest.mark.skipif(os.name == "nt", reason="shell command tables, measured on POSIX")
links = pytest.mark.skipif(os.name == "nt", reason="symlinks need a privilege on Windows")


@pytest.fixture()
def repo(tmp_path):
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / ".qa").mkdir()
    (root / "src" / "app.py").write_text("a = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    return root


def judge(command, cwd, **who):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_STRICT"] = "1"
    event = {"hook_event_name": "PreToolUse", "tool_name": "Bash",
             "tool_input": {"command": command}, "cwd": str(cwd), **who}
    proc = subprocess.run([sys.executable, str(HOOKS / "enforce_bash_scope.py")],
                          input=json.dumps(event), capture_output=True, text=True, env=env,
                          encoding="utf-8", errors="replace")
    return proc.returncode, proc.stderr


@posix_only
@pytest.mark.parametrize("command, code, reports_exists", [
    ("ln -s ../src/app.py .qa/facts.json", 2, False),
    ("ln -s .. .qa/reports", 2, False),                       # S1, on a fresh root
    ("ln -s ../src .qa/reports", 2, False),                   # S3
    ("ln src/app.py .qa/facts.json", 2, False),               # a hard link: no -s to look for
    ("ln -sf ../../README.md .qa/reports/x.md", 2, True),     # S2
    ("ln -s ../../README.md .qa/reports", 2, True),           # lands inside the directory
    ("ln -s /etc/hosts .qa/facts.json", 2, False),
    ("cd .qa && ln -s ../src/app.py facts.json", 2, False),
    ("ln -s state.json .qa/latest.json", 0, False),           # a link that stays inside the root
    ("ln -s /tmp/verdict-scratch-x/py /tmp/verdict-scratch-x/python", 0, False),   # scratch
    ("ln src/app.py /tmp/verdict-scratch-x/alias", 2, False),  # a scratch name for the code
    ("ln -f src/app.py /tmp/verdict-scratch-x/alias", 2, False),
    ("ln /tmp/verdict-scratch-x/a /tmp/verdict-scratch-x/b", 0, False),
    ("ln -s $PWD/src /tmp/verdict-scratch-x/src", 0, False),  # a symlink in scratch: resolved
    ("verdict-issues myapp --create", 2, False),
    ("verdict-issues myapp", 0, False),                       # the dry run reads
])
def test_the_guard_refuses_a_link_out_of_the_qa_root(command, code, reports_exists, repo):
    if reports_exists:
        (repo / ".qa" / "reports").mkdir()
    got, err = judge(command, repo)
    assert got == code, "{!r}: exit {}\n{}".format(command, got, err)


@links
@posix_only
def test_a_write_through_a_scratch_symlink_is_still_read_where_it_lands(repo, tmp_path):
    """Why a symlink in scratch is left alone: the next write through it is resolved."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    os.symlink(repo / "src", scratch / "src")
    got, _ = judge("echo junk > {}".format(scratch / "src" / "app.py"), repo)
    assert got == 2


@links
def test_the_stop_hook_does_not_write_its_note_through_a_link(repo, tmp_path):
    """The hook marks the marker "told once" — a write by name, in the root, by a
    process the tester's own stop triggers."""
    victim = repo / "src" / "marker-shaped.json"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = json.dumps({"started_utc": stamp, "session_id": "sess-1", "repo": str(repo)})
    victim.write_text(body, encoding="utf-8")
    os.symlink("../src/marker-shaped.json", repo / ".qa" / "run-in-progress.json")
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(tmp_path / "home")
    event = {"cwd": str(repo), "hook_event_name": "SubagentStop", "session_id": "sess-1",
             "agent_type": "verdict:verdict"}
    proc = subprocess.run([sys.executable, str(HOOKS / "enforce_run_contract.py")],
                          input=json.dumps(event), capture_output=True, text=True, env=env)
    assert "Traceback" not in proc.stderr
    assert victim.read_text(encoding="utf-8") == body, "the hook wrote through the link"
