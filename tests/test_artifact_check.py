"""finalize reads its own artifacts back — the run-4 discipline, made mechanical.

Run 4 found two harness defects (a state re-keyed to the directory name, an
INDEX row dated from the local clock) by comparing the state, the INDEX row,
the runs.jsonl row and the report against each other. Each test here corrupts
exactly one artifact after a real finalize and expects the check to name it.
"""

import json
import subprocess
import sys
from pathlib import Path

from verdict_mcp.harness import check_artifacts, collect, merge, write_state

from conftest import judgment

HARNESS = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"


def finalized(repo, qa_root):
    state = merge(collect(repo, qa_root, []), judgment(), None)
    assert write_state(qa_root, state) == []
    return state


def test_a_clean_finalize_has_nothing_to_report(repo, qa_root):
    assert check_artifacts(qa_root, finalized(repo, qa_root)) == []


def test_an_index_row_dated_from_the_wrong_clock_is_named(repo, qa_root):
    """VERDICT-F-24's shape. The renderer is fixed; this is what catches the
    next renderer."""
    state = finalized(repo, qa_root)
    index = qa_root / "reports" / "INDEX.md"
    lines = index.read_text(encoding="utf-8").splitlines()
    lines[-1] = "| 1999-01-01" + lines[-1][len("| 2026-09-02"):]
    index.write_text("\n".join(lines) + "\n", encoding="utf-8")
    problems = check_artifacts(qa_root, state)
    assert any("dated 1999-01-01" in p and "measured" in p for p in problems), problems


def test_an_index_row_naming_another_project_is_named(repo, qa_root):
    """VERDICT-F-23's shape."""
    state = finalized(repo, qa_root)
    index = qa_root / "reports" / "INDEX.md"
    text = index.read_text(encoding="utf-8")
    index.write_text(text.replace(f"| {state['project']} |", "| verdict-clone |"), encoding="utf-8")
    problems = check_artifacts(qa_root, state)
    assert any("names project 'verdict-clone'" in p for p in problems), problems


def test_a_history_row_that_does_not_carry_the_signed_link_is_named(repo, qa_root):
    state = finalized(repo, qa_root)
    runs = qa_root / "runs.jsonl"
    rows = [json.loads(line) for line in runs.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows[-1]["chain"] = "0" * 64
    runs.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    problems = check_artifacts(qa_root, state)
    assert any("last link" in p for p in problems), problems


def test_a_missing_history_row_is_named(repo, qa_root):
    state = finalized(repo, qa_root)
    (qa_root / "runs.jsonl").write_text("", encoding="utf-8")
    problems = check_artifacts(qa_root, state)
    assert any("runs.jsonl ends at run None" in p for p in problems), problems


def test_a_report_that_went_missing_is_named(repo, qa_root):
    state = finalized(repo, qa_root)
    (qa_root / state["last_run"]["report"]).unlink()
    problems = check_artifacts(qa_root, state)
    assert any("is not on disk" in p for p in problems), problems


def test_the_cli_says_it_out_loud_and_still_records_the_run(repo, qa_root, tmp_path):
    """The check runs after every finalize. A disagreement is a warning on
    stderr — the stream the agent reads — never a refusal: the run is
    recorded and the state is valid; what is wrong is a renderer."""
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    jp = tmp_path / "j.json"
    jp.write_text(json.dumps(judgment()), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HARNESS), "finalize", "--qa-root", str(qa_root),
                           "--judgment", str(jp)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "WARNING" not in proc.stderr, "a clean finalize must not cry wolf"
