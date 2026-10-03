"""The PostToolUse validator speaks only about a QA root's files.

It validated every file named `state.json` anywhere: a user's own app settings
got "15 problems" and exit 2 in a session that had never run Verdict (audit
2026-10-02, T3-1). A QA root is the solo home or a `.qa/` beside a `.git`; a
`findings/<ID>.json` outside one is somebody else's file as well.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

VALIDATE = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "validate.py"
JUNK = json.dumps({"theme": "dark", "count": 3})


def _hook(path, home):
    env = {k: v for k, v in os.environ.items() if k != "VERDICT_HOME"}
    env["VERDICT_HOME"] = str(home)
    event = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write",
                        "tool_input": {"file_path": str(path)}})
    return subprocess.run([sys.executable, str(VALIDATE)], input=event,
                          capture_output=True, text=True, env=env)


def test_a_foreign_state_json_is_none_of_the_hooks_business(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    (app / "state.json").write_text(JUNK, encoding="utf-8")
    proc = _hook(app / "state.json", tmp_path / "home")
    assert proc.returncode == 0 and proc.stderr == "", proc.stderr


def test_a_foreign_findings_file_is_ignored_too(tmp_path):
    (tmp_path / "app" / "findings").mkdir(parents=True)
    target = tmp_path / "app" / "findings" / "X-F-1.json"
    target.write_text(JUNK, encoding="utf-8")
    assert _hook(target, tmp_path / "home").returncode == 0


def test_a_team_roots_state_is_still_checked(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".qa").mkdir()
    (tmp_path / ".qa" / "state.json").write_text(JUNK, encoding="utf-8")
    proc = _hook(tmp_path / ".qa" / "state.json", tmp_path / "home")
    assert proc.returncode == 2 and "violates the contract" in proc.stderr


def test_a_solo_roots_state_is_still_checked(tmp_path):
    home = tmp_path / "home"
    (home / "myapp").mkdir(parents=True)
    (home / "myapp" / "state.json").write_text(JUNK, encoding="utf-8")
    proc = _hook(home / "myapp" / "state.json", home)
    assert proc.returncode == 2 and "violates the contract" in proc.stderr


def test_a_dot_qa_without_a_repository_beside_it_is_not_a_root(tmp_path):
    (tmp_path / "src" / ".qa").mkdir(parents=True)
    target = tmp_path / "src" / ".qa" / "state.json"
    target.write_text(JUNK, encoding="utf-8")
    assert _hook(target, tmp_path / "home").returncode == 0
