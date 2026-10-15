"""The verdict rule a judgment cannot talk its way past (`harness.gate_policy`).

On 2026-10-12 the provider's safety filter stopped two responses of a security gate and the
CLI carried the tester on to another model without saying so; only the eval's watcher
noticed. A tester that answered on more than one model signs nothing.
"""

import pytest

from conftest import judgment
from test_filed import finding, run_facts, run_finalize, three_lines
import verdict_mcp.harness as harness
from verdict_mcp.harness import gate_policy


def state_with(*findings, verdict="pass with risks"):
    return {"verdict": verdict, "release_blockers": [], "findings": [dict(f) for f in findings]}


@pytest.mark.parametrize("verdict", ["pass", "pass with risks", "fail"])
def test_a_tester_that_answered_on_two_models_is_blocked(verdict):
    state = state_with(finding("W-F-1"), verdict=verdict)
    notes = gate_policy(state, {"models": {"claude-opus-5-5": 11, "claude-opus-4-8": 1}})
    assert state["verdict"] == "blocked"
    assert "claude-opus-4-8 ×1" in state["verdict_rule"]["reason"]
    assert state["verdict_rule"]["was"] == verdict
    assert notes and notes[0].startswith("verdict blocked")


@pytest.mark.parametrize("bill", [None, {}, {"models": {}}, {"models": {"claude-opus-5-5": 27}}])
def test_one_model_or_no_bill_leaves_the_verdict_alone(bill):
    state = state_with(finding("W-F-1"), verdict="pass")
    assert gate_policy(state, bill) == []
    assert state["verdict"] == "pass" and "verdict_rule" not in state


def test_finalize_blocks_a_run_whose_tester_switched_models(repo, qa_root, capsys, monkeypatch):
    three_lines(repo)
    run_facts(repo, qa_root)
    monkeypatch.setattr(harness, "_measure_bill", lambda root, facts: {
        "models": {"claude-opus-5-5": 11, "claude-opus-4-8": 1}, "model": "claude-opus-5-5",
        "requests": 12})
    rc, state = run_finalize(qa_root, judgment(findings=[], verdict="pass"))
    err = capsys.readouterr().err
    assert rc == 0, err
    assert state["verdict"] == "blocked" and "more than one model" in err
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "**VERDICT: blocked**" in report and "claude-opus-4-8 ×1" in report
    assert "Set by the harness (one model)" in report


def test_finalize_on_one_model_signs_the_judgment_as_written(repo, qa_root, capsys, monkeypatch):
    three_lines(repo)
    run_facts(repo, qa_root)
    monkeypatch.setattr(harness, "_measure_bill", lambda root, facts: {
        "models": {"claude-opus-5-5": 12}, "model": "claude-opus-5-5", "requests": 12})
    rc, state = run_finalize(qa_root, judgment(findings=[], verdict="pass with risks"))
    assert rc == 0, capsys.readouterr().err
    assert state["verdict"] == "pass with risks" and "verdict_rule" not in state
