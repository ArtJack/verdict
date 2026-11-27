"""The finding hook tells a tester, as it writes a repro, whether the harness will replay it.

`verdict-facts` and `verdict-finalize` replay a repro unattended only as one interpreter call,
and said so only in the replay record, after the run. An asked run on 2026-11-17 wrote two of
its three repros around `d=$(mktemp -d) && …`, learnt at finalize that neither ran, and had no
call left to rewrite them. The note is advice, not a violation: a project that is not Python
may have no other shape to offer, and a person running `verdict-replay` still runs any command.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
VALIDATE = SRC / "verdict_mcp" / "validate.py"
SYSTEM_PYTHON = "/usr/bin/python3"
sys.path.insert(0, str(SRC))
from verdict_mcp.repro_shape import shape_note  # noqa: E402

PY = sys.executable
GLUE = f'd=$(mktemp -d) && {PY} -c "import sys; print(sys.argv[1])" "$d"'
SHAPED = f'{PY} -c "import sys; print(sys.argv[1])" {{tmp}}'


def _root(tmp_path):
    home, repo = tmp_path / "home", tmp_path / "repo"
    qa = home / "book"
    (qa / "findings").mkdir(parents=True)
    repo.mkdir()
    (qa / "facts.json").write_text(json.dumps({"repo": str(repo)}), encoding="utf-8")
    return home, qa, repo


def _finding(fid, repro, **over):
    f = {"id": fid, "title": "the QR check never compares the address", "severity": "Minor",
         "priority": "P3", "status": "open", "confidence": "proven",
         "evidence": ["tools/check.py:12 — the decoded address is never compared"],
         "repro": repro}
    f.update(over)
    return f


def _hook(qa, home, finding, python=PY):
    path = qa / "findings" / f"{finding['id']}.json"
    path.write_text(json.dumps(finding), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "VERDICT_HOME"}
    env["VERDICT_HOME"] = str(home)
    event = json.dumps({"hook_event_name": "PostToolUse", "tool_name": "Write",
                        "tool_input": {"file_path": str(path)}})
    return subprocess.run([python, str(VALIDATE)], input=event, capture_output=True, text=True,
                          env=env, encoding="utf-8", errors="replace")


def _context(proc):
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


def test_a_repro_in_shell_glue_is_flagged_as_it_is_written(tmp_path):
    home, qa, _ = _root(tmp_path)
    proc = _hook(qa, home, _finding("BOOK-F-5", {"command": GLUE, "cwd": "repo",
                                                 "expect": {"exit": 0}}))
    assert proc.returncode == 0, proc.stderr
    note = _context(proc)
    assert "BOOK-F-5's repro will not be replayed unattended" in note
    assert "shell operator" in note and "{tmp}" in note and "verdict-replay" in note, note


def test_a_repro_the_harness_will_run_gets_no_note(tmp_path):
    home, qa, _ = _root(tmp_path)
    proc = _hook(qa, home, _finding("BOOK-F-6", {"command": SHAPED, "cwd": "repo",
                                                 "expect": {"exit": 0}}))
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == "", (proc.stdout,
                                                                             proc.stderr)


def test_a_violation_carries_the_note_too(tmp_path):
    home, qa, _ = _root(tmp_path)
    proc = _hook(qa, home, _finding("BOOK-F-7", {"command": GLUE}, evidence=[]))
    assert proc.returncode == 2 and "violates the contract" in proc.stderr
    assert "Also: BOOK-F-7's repro will not be replayed unattended" in proc.stderr, proc.stderr


def test_a_closed_finding_is_not_advised(tmp_path):
    home, qa, _ = _root(tmp_path)
    proc = _hook(qa, home, _finding("BOOK-F-8", {"command": GLUE}, status="resolved"))
    assert proc.returncode == 0 and proc.stdout == "", proc.stdout


@pytest.mark.skipif(not os.path.exists(SYSTEM_PYTHON), reason="no system python3 here")
def test_the_note_reaches_the_tester_under_the_system_python(tmp_path):
    """The hook runs on whatever `python3` is, 3.9 on a stock Mac, with none of the harness
    loaded: the module it now imports has to start there too."""
    home, qa, _ = _root(tmp_path)
    proc = _hook(qa, home, _finding("BOOK-F-9", {"command": GLUE}), python=SYSTEM_PYTHON)
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.returncode == 0 and "will not be replayed unattended" in _context(proc)


def test_a_program_that_is_not_python_is_named(tmp_path):
    _, qa, repo = _root(tmp_path)
    note = shape_note(_finding("WEB-F-1", {"command": "node --test tests/a.test.js"}), qa, repo)
    assert "`node` is not python or pytest" in note, note


def test_with_no_checkout_known_a_scripts_place_is_not_judged(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    finding = _finding("X-F-1", {"command": f"{PY} {tmp_path / 'outside' / 'probe.py'}"})
    assert shape_note(finding, qa, None) == ""
    assert "outside the QA root" in shape_note(finding, qa, tmp_path / "repo")
    glue = _finding("X-F-4", {"command": GLUE})
    assert "shell operator" in shape_note(glue, qa, None), "a shell needs no checkout to be seen"


def test_no_repro_no_note(tmp_path):
    assert shape_note({"id": "X-F-2"}, tmp_path) == ""
    assert shape_note({"id": "X-F-3", "repro": {"command": "  "}}, tmp_path) == ""
