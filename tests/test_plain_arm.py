"""The recall benchmark's plain arm: what it tells the session, and how it reads what comes back (0.92.1)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval" / "recall"))
import plain_arm  # noqa: E402

BRIEF = ("This is a run: start with verdict-facts.\n\nBaseline QA run of shop at HEAD abc.\n\n"
         "Scope, as the profile's \"Risk focus: money\" section lays out: fees and\nrefunds.\n\n"
         "Proof standard: a finding at Major or worse needs execution behind it.\n\n"
         "Do not open Verdict's own docs or harness source.\n")
PROFILE = ("---\ngates:\n  suite: /x/.venv/bin/python -m pytest -q\n---\n\n# QA Profile\n\n## What it is\n\nA shop.\n\n"
           "## Risk focus: money\n\n- **Fees.** `shop/fees.py`.\n\n## Real commands\n\nmake test\n")


def test_the_prompt_carries_the_scope_the_risk_notes_and_the_proof_standard_and_nothing_of_verdict(tmp_path):
    text = plain_arm.build_prompt("shop", "abcdef1234567890", BRIEF, PROFILE, tmp_path / "scratch",
                                  tmp_path / "findings.json", calls=35, cap=2.5)
    assert "Scope, as the notes below lay out: fees and refunds." in text
    assert "## Risk focus: money" in text and "`shop/fees.py`" in text and "Real commands" not in text
    assert "Proof standard: a finding at Major or worse needs execution behind it." in text
    assert "`/x/.venv/bin/python -m pytest -q`" in text and "Use `/x/.venv/bin/python` for Python" in text
    assert "about 35 tool calls; the session stops at $2.5" in text and str(tmp_path / "findings.json") in text
    assert "verdict" not in text.lower(), "the plain arm is told nothing of Verdict"


def test_findings_are_read_from_the_file_else_from_the_last_message(tmp_path):
    path = tmp_path / "findings.json"
    assert plain_arm.read_findings(path, 'Done.\n{"findings": [{"id": "P-1"}]}\nThanks') == [{"id": "P-1"}]
    path.write_text(json.dumps({"findings": [{"id": "P-2"}]}), encoding="utf-8")
    assert plain_arm.read_findings(path, '{"findings": [{"id": "P-1"}]}') == [{"id": "P-2"}]
    assert plain_arm.read_findings(tmp_path / "none.json", "no findings at all") == []


def test_findings_take_the_record_shapes_and_a_repro_without_a_command_is_dropped():
    got = plain_arm.normalize([{"title": "t", "severity": "major", "confidence": "sure", "repro": {"cwd": "repo"},
                                "anchors": [{"path": "a.py", "line": 3}, {"line": 4}], "evidence": [1]},
                               "not a finding"])
    assert got == [{"title": "t", "id": "P-1", "severity": "Minor", "confidence": "hypothesis", "status": "open",
                    "anchors": [{"path": "a.py", "line": 3}], "evidence": ["1"]}]


def test_usage_is_one_row_per_model_in_the_records_token_names():
    result = {"total_cost_usd": 1.5, "modelUsage": {"claude-opus-5-5": {
        "inputTokens": 10, "outputTokens": 20, "cacheReadInputTokens": 30, "cacheCreationInputTokens": 40, "costUSD": 1.4}}}
    assert plain_arm.usage_rows(result) == [{"usage": {"model": "claude-opus-5-5", "input_tokens": 10,
                                                       "output_tokens": 20, "cache_read_input_tokens": 30,
                                                       "cache_creation_input_tokens": 40}, "cli_cost_usd": 1.4}]
    assert plain_arm.result_of('noise\n{"type": "result", "total_cost_usd": 1.5}\n')["total_cost_usd"] == 1.5


def test_a_plain_root_that_names_verdict_or_sits_under_home_is_refused(tmp_path, capsys):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{"key": "shop", "sha": "abc"}]}), encoding="utf-8")
    brief, profile = tmp_path / "b.md", tmp_path / "p.md"
    brief.write_text(BRIEF, encoding="utf-8")
    profile.write_text(PROFILE, encoding="utf-8")
    for out in (tmp_path / "verdict-plain", Path.home() / "plain-arm-test-never-created"):
        assert plain_arm.main([str(cases), "shop", "--brief", str(brief), "--profile", str(profile),
                               "--out", str(out)]) == 2
        assert "names Verdict or sits under the home directory" in capsys.readouterr().err


def test_a_session_that_read_verdicts_records_is_flagged(tmp_path, monkeypatch):
    base = tmp_path / "projects"
    base.mkdir()
    (base / "s1.jsonl").write_text(
        json.dumps({"type": "tool_use", "input": {"file_path": "/Users/x/.claude/verdict/shop/state.json"}}) + "\n"
        + json.dumps({"type": "tool_use", "input": {"file_path": "src/fees.py"}}) + "\n", encoding="utf-8")
    monkeypatch.setattr(plain_arm, "_project_dir", lambda cwd, config_dir=None: base)
    assert plain_arm.contamination(tmp_path, "s1") == [".claude/verdict"]
    assert plain_arm.contamination(tmp_path, None) is None


def test_the_tree_is_a_standalone_clone_that_cannot_inherit_the_checkouts_local_settings(tmp_path):
    from conftest import git
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(["init", "-qb", "main"], repo)
    git(["add", "-A"], repo)
    git(["commit", "-qm", "one"], repo)
    (repo / ".claude").mkdir()                    # untracked, as verdict-run provisions it
    (repo / ".claude" / "settings.local.json").write_text('{"hooks": {}}', encoding="utf-8")
    sha = __import__("subprocess").run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                                       text=True).stdout.strip()
    tree = tmp_path / "out" / "tree"
    assert plain_arm.isolated_tree(repo, tree, sha) is None
    assert (tree / "a.py").is_file() and not (tree / ".claude").exists()
    assert (tree / ".git").is_dir(), "its own git directory, not a worktree's pointer file"


def test_the_test_command_is_read_as_the_harness_reads_it_and_any_interpreter_path_is_found(tmp_path, capsys):
    assert plain_arm.suite_command(PROFILE) == "/x/.venv/bin/python -m pytest -q"
    assert plain_arm.suite_command("---\ngates:\n  tests: tox -e py\n---\n") == "tox -e py"
    assert plain_arm.suite_command("no front matter at all") == ""
    assert plain_arm.interpreter("/x/.venv/bin/python3.12 -m pytest") == "/x/.venv/bin/python3.12"
    assert plain_arm.interpreter(r"C:\v\Scripts\Python.exe -m pytest") == r"C:\v\Scripts\Python.exe"
    assert plain_arm.interpreter("tox -e py") == "python3"
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [{"key": "shop", "sha": "abc"}]}), encoding="utf-8")
    (tmp_path / "b.md").write_text(BRIEF, encoding="utf-8")
    (tmp_path / "p.md").write_text(PROFILE, encoding="utf-8")
    a_file = tmp_path / "out-is-a-file"
    a_file.write_text("x", encoding="utf-8")
    assert plain_arm.main([str(cases), "shop", "--brief", str(tmp_path / "b.md"), "--profile",
                           str(tmp_path / "p.md"), "--out", str(a_file)]) == 2
    assert "is not an empty directory" in capsys.readouterr().err
