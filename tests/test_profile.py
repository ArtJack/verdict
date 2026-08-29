"""Tests for the profile's machine-readable half.

The point of this file is deleting a transcription step: the profile has always
recorded a project's real commands, and the agent has always had to retype them
into `--gate` flags. What these tests guard is mostly the failure direction —
a block that cannot be read must say so, never quietly contribute nothing,
because a run that measured nothing and a run with nothing to measure look
identical from the outside and are not the same thing at all.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from verdict_mcp.profile import ProfileError, gates_from, load, parse

HARNESS = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"

BLOCK = '''---
gates:
  suite: .venv/bin/python -m pytest -q
  lint: ruff check .
test_ids_cmd: .venv/bin/python -m pytest --collect-only -q
coverage_cmd: diff-cover coverage.xml
---

# QA Profile — demo

Prose exactly as before.
'''


def test_a_profile_block_yields_gates_in_order():
    config = parse(BLOCK)
    assert gates_from(config) == [("suite", ".venv/bin/python -m pytest -q"),
                                  ("lint", "ruff check .")]
    assert config["coverage_cmd"] == "diff-cover coverage.xml"


def test_commands_are_taken_literally_to_end_of_line():
    """Commands are full of colons, quotes and pipes; a cleverer parser mangles
    them, and a mangled command is a gate that silently measures the wrong
    thing."""
    config = parse('---\ngates:\n  suite: sh -c "a: b | c" && echo done: yes\n---\n')
    assert config["gates"]["suite"] == 'sh -c "a: b | c" && echo done: yes'


def test_surrounding_quotes_come_off_but_inner_ones_stay():
    config = parse("""---\ngates:\n  suite: "python -c 'print(1)'"\n---\n""")
    assert config["gates"]["suite"] == "python -c 'print(1)'"


def test_a_file_with_no_block_is_not_an_error():
    assert parse("# QA Profile\n\nJust prose.\n") == {}


def test_comments_and_blank_lines_are_skipped():
    config = parse("---\n# which suite to run\n\ngates:\n  suite: pytest\n---\n")
    assert config == {"gates": {"suite": "pytest"}}


def test_an_unreadable_line_names_itself_instead_of_being_skipped():
    with pytest.raises(ProfileError, match="line 3.*cannot read"):
        parse("---\ngates:\n- suite: pytest\n---\n")


def test_an_orphaned_nested_line_says_what_is_missing():
    with pytest.raises(ProfileError, match="indented under nothing"):
        parse("---\n  suite: pytest\n---\n")


def test_gates_given_as_a_bare_value_is_rejected(tmp_path):
    """A gate has a name so the state can say which one failed."""
    (tmp_path / "profile.md").write_text("---\ngates: pytest\n---\n", encoding="utf-8")
    with pytest.raises(ProfileError, match="block of `name: command` lines"):
        load(tmp_path)


def test_keys_verdict_facts_does_not_read_are_reported_not_dropped(tmp_path):
    (tmp_path / "profile.md").write_text(
        "---\ngates:\n  suite: pytest\nsecurity_pass: enabled\n---\n", encoding="utf-8")
    config, notes = load(tmp_path)
    assert config["security_pass"] == "enabled"
    assert any("not read by verdict-facts" in n and "security_pass" in n for n in notes)


def test_a_missing_profile_is_reported_and_is_not_fatal(tmp_path):
    config, notes = load(tmp_path)
    assert config == {} and any("no profile at" in n for n in notes)


# ── through the CLI, which is where it earns its keep ─────────────────────

def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-qb", "main"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "first"], cwd=repo, check=True, capture_output=True)
    return repo


def _facts(repo, qa_root, *extra):
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "facts", "--repo", str(repo),
         "--qa-root", str(qa_root), *extra], capture_output=True, text=True)
    return proc, (json.loads(proc.stdout) if proc.returncode == 0 else None)


def test_facts_runs_a_whole_gate_set_with_no_flags_at_all(tmp_path):
    """The point of the exercise: the profile already knows the commands."""
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    (qa_root / "profile.md").write_text(
        f"---\ngates:\n  suite: {sys.executable} -c \"print('4 passed in 0.1s')\"\n---\n",
        encoding="utf-8")
    proc, facts = _facts(repo, qa_root)
    assert proc.returncode == 0, proc.stderr
    assert facts["gates_from_profile"] == ["suite"]
    assert facts["tests"]["passed"] == 4


def test_an_explicit_gate_overrides_the_profile_and_says_so(tmp_path):
    """Narrowing a run must not require editing the project's profile."""
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    (qa_root / "profile.md").write_text(
        "---\ngates:\n  suite: exit 1\n---\n", encoding="utf-8")
    proc, facts = _facts(repo, qa_root, "--gate", f'suite={sys.executable} -c "pass"')
    assert facts["gates"]["suite"]["exit_code"] == 0
    assert any("overridden on the command line" in n for n in facts["profile_notes"])


def test_a_broken_profile_stops_the_run_instead_of_measuring_nothing(tmp_path):
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    (qa_root / "profile.md").write_text("---\ngates:\n- suite: pytest\n---\n",
                                        encoding="utf-8")
    proc, _ = _facts(repo, qa_root)
    assert proc.returncode == 2 and "cannot read" in proc.stderr


def test_a_run_with_no_gates_at_all_says_so_in_the_facts(tmp_path):
    """"Nothing to measure" and "nobody told me what to measure" are different
    states of the world, and only one of them is the reader's problem."""
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    _, facts = _facts(repo, qa_root)
    assert "unmeasurable this run" in facts["no_gates"]


def test_no_profile_flag_restores_the_old_behaviour(tmp_path):
    repo, qa_root = _repo(tmp_path), tmp_path / "qa"
    qa_root.mkdir()
    (qa_root / "profile.md").write_text(
        "---\ngates:\n  suite: exit 7\n---\n", encoding="utf-8")
    _, facts = _facts(repo, qa_root, "--no-profile")
    assert facts["gates"] == {} and "no_gates" in facts
