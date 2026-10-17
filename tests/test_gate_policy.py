"""The verdict rule a judgment cannot talk its way past (`harness.gate_policy`).

On 2026-10-12 the provider's safety filter stopped two responses of a security gate and the
CLI carried the tester on to another model without saying so; only the eval's watcher
noticed. A tester that answered on more than one model signs nothing.
"""

import json
import os
import sys
from pathlib import Path

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


# ── a proven defect the change made blocks a money or security gate (Phase 2b) ──

import subprocess  # noqa: E402

from test_filed import write_finding  # noqa: E402
from verdict_mcp.harness import change_lines  # noqa: E402


def anchored(fid, line, **over):
    f = finding(fid, **over)
    f["anchors"] = [{"ref": f"a.py:{line}", "path": "a.py", "line": line}]
    return f


IN_CHANGE = lambda path, line: (path, int(line)) == ("a.py", 2)  # noqa: E731


@pytest.mark.parametrize("risk", ["money", "security"])
def test_a_proven_defect_on_a_line_the_change_made_blocks(risk):
    state = state_with(anchored("W-F-1", 2, severity="Minor"))
    notes = gate_policy(state, {"models": {"claude-opus-5-5": 9}}, risk, IN_CHANGE)
    assert state["verdict"] == "fail" and state["verdict_rule"]["raised_by"] == ["W-F-1"]
    assert state["release_blockers"][0].startswith("W-F-1: ")
    assert state["findings"][0]["severity"] == "Minor", "the rule moves the verdict, not the severity"
    assert notes and "proven in the change" in notes[0]


@pytest.mark.parametrize("finding_", [
    anchored("W-F-1", 1),                                   # a line the change did not make
    anchored("W-F-1", 2, severity="Trivial"),               # below the floor
    anchored("W-F-1", 2, confidence="probable"),
    anchored("W-F-1", 2, failure_classification="TEST_GAP"),
    anchored("W-F-1", 2, status="resolved"),
    anchored("W-F-1", 2, source="hygiene"),
    finding("W-F-1"),                                       # no anchors at all
])
def test_only_a_proven_minor_or_worse_real_defect_the_change_made_blocks(finding_):
    state = state_with(finding_)
    assert gate_policy(state, None, "money", IN_CHANGE) == []
    assert state["verdict"] == "pass with risks" and "verdict_rule" not in state


def test_without_a_gate_range_the_judgment_stands_and_says_why():
    state = state_with(anchored("W-F-1", 2))
    notes = gate_policy(state, None, "money", None)
    assert state["verdict"] == "pass with risks"
    assert notes and "no gate range" in notes[0]


def test_without_a_risk_class_nothing_is_raised():
    state = state_with(anchored("W-F-1", 2))
    assert gate_policy(state, None, None, IN_CHANGE) == []
    assert state["verdict"] == "pass with risks"


def test_the_one_model_rule_comes_first():
    state = state_with(anchored("W-F-1", 2))
    gate_policy(state, {"models": {"a": 1, "b": 1}}, "money", IN_CHANGE)
    assert state["verdict"] == "blocked"


def test_change_lines_reads_blame_against_the_range(repo):
    three_lines(repo)                      # "first" wrote line 1; "three lines" wrote 2 and 3
    in_change = change_lines(repo, "HEAD~1..HEAD")
    assert [in_change("a.py", n) for n in (1, 2, 3)] == [False, True, True]
    assert in_change("missing.py", 1) is False and in_change("a.py", "x") is False
    assert change_lines(repo, None) is None and change_lines(None, "HEAD~1..HEAD") is None
    assert change_lines(repo, "HEAD..HEAD") is None, "a range with no commit tells nothing apart"


def test_verdict_facts_records_the_range_given_or_inherited(repo, qa_root):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~1..HEAD"]) == 0
    facts = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    assert facts["last_run"]["sha_range"] == "HEAD~1..HEAD"
    # inherited: the variable `verdict-run --range` exports, read by a process of its own
    harness_py = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"
    (qa_root / "facts.json").unlink()
    proc = subprocess.run([sys.executable, str(harness_py), "facts", "--repo", str(repo),
                           "--qa-root", str(qa_root)], capture_output=True, text=True,
                          env=dict(os.environ, VERDICT_RANGE="HEAD~1..HEAD"))
    assert proc.returncode == 0, proc.stderr
    facts = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    assert facts["last_run"]["sha_range"] == "HEAD~1..HEAD"


def test_a_gate_in_a_root_of_its_own_says_it_was_a_gate_not_a_baseline(repo, qa_root, capsys):
    """Every branch gate runs in a throwaway root, so every one was recorded and reported as
    "run 1 (baseline)" — as if the whole repository had been read (trace 2026-10-15). The type
    stays the enum consumers switch on; the label says what the run was."""
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~1..HEAD"]) == 0
    facts = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    assert facts["run_type"] == "baseline" and "a gate over HEAD~1..HEAD" in facts["run_type_reason"]
    assert facts["run_label"].startswith("Gate over HEAD~1..HEAD")
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    assert state["run_label"] == facts["run_label"]
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "*Gate over HEAD~1..HEAD, in a root of its own" in report


def test_a_baseline_without_a_range_and_a_judgments_own_label_are_left_alone(repo, qa_root, capsys):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    assert "run_label" not in json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0 and "run_label" not in state, capsys.readouterr().err
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~1..HEAD"]) == 0
    assert "run_label" not in json.loads((qa_root / "facts.json").read_text(encoding="utf-8")), \
        "a range over a root with a previous state is a delta, not a gate on its own"
    (qa_root / "facts.json").unlink()
    (qa_root / "state.json").unlink()
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~1..HEAD"]) == 0
    rc, state = run_finalize(qa_root, judgment(findings=[], run_label="merge gate, asked"))
    assert rc == 0 and state["run_label"] == "merge gate, asked", "the judgment's own label wins"


def _profile(qa_root, front):
    (qa_root / "profile.md").write_text(f"---\n{front}\n---\n\n# QA Profile — widget\n",
                                        encoding="utf-8")


@pytest.mark.parametrize("line,verdict", [(2, "fail"), (1, "pass with risks")])
def test_finalize_blocks_only_a_proven_defect_on_a_changed_line(repo, qa_root, capsys,
                                                                 line, verdict):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    _profile(qa_root, "risk_class: money")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~1..HEAD"]) == 0
    write_finding(qa_root, finding("W-F-1", severity="Minor",
                                   evidence=[f"a.py:{line} — the guard"]))
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    err = capsys.readouterr().err
    assert rc == 0, err
    assert state["verdict"] == verdict
    if verdict == "fail":
        report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
        assert "a proven defect the change made blocks" in report and "**VERDICT: fail**" in report


def test_finalize_without_a_range_keeps_the_judgment_and_says_so(repo, qa_root, capsys):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    _profile(qa_root, "risk_class: money")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    write_finding(qa_root, finding("W-F-1", severity="Minor", evidence=["a.py:2 — the guard"]))
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    err = capsys.readouterr().err
    assert rc == 0, err
    assert state["verdict"] == "pass with risks" and "no gate range" in err


# ── rule 3: a fix that fails the project's own green tests is a contract dispute ──

def _critical_with_fix_breaking(n):
    f = finding("W-F-1", severity="Critical", evidence=["a.py:2 — the guard, as 22 tests assert it"])
    f["fix_breaks_tests"] = n
    return f


def test_a_fix_that_fails_green_tests_is_a_contract_dispute_not_a_blocker(repo, qa_root, capsys):
    """django-oscar, 2026-10-17: a baseline said `fail` on a Critical that 22 green tests
    assert the other way and the tracker had tuned on purpose. The tests are evidence of
    intent; a documented-versus-tested disagreement is the maintainer's to settle."""
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    write_finding(qa_root, _critical_with_fix_breaking(22))
    rc, state = run_finalize(qa_root, judgment(findings=[], verdict="fail",
                                               release_blockers=["W-F-1 (Critical): the guard"]))
    err = capsys.readouterr().err
    assert rc == 0, err
    f = next(x for x in state["findings"] if x["id"] == "W-F-1")
    assert f["contract_dispute"] is True and f["severity"] == "Major" and f["severity_was"] == "Critical"
    assert state["release_blockers"] == [] and state["verdict"] == "pass with risks"
    assert state["verdict_rule"] == {"rule": "contract dispute", "was": "fail", "capped": ["W-F-1"]}
    assert "verdict lowered from 'fail' to 'pass with risks'" in err
    ledger = json.loads((qa_root / "questions.json").read_text(encoding="utf-8"))
    q = next(r for r in ledger["questions"].values() if r.get("finding") == "W-F-1")
    assert "22 test(s) that pass at HEAD" in q["question"] and "Which is the contract" in q["question"]
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "contract dispute" in report


def test_a_fix_that_breaks_nothing_and_a_switched_off_rule_leave_the_verdict_alone(repo, qa_root, capsys):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    write_finding(qa_root, _critical_with_fix_breaking(0))
    rc, state = run_finalize(qa_root, judgment(findings=[], verdict="fail",
                                               release_blockers=["W-F-1 (Critical): the guard"]))
    assert rc == 0, capsys.readouterr().err
    f = next(x for x in state["findings"] if x["id"] == "W-F-1")
    assert "contract_dispute" not in f and f["severity"] == "Critical" and state["verdict"] == "fail"
    (qa_root / "state.json").unlink()
    (qa_root / "findings" / "W-F-1.json").unlink()
    _profile(qa_root, "contract_rule: off")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    write_finding(qa_root, _critical_with_fix_breaking(22))
    rc, state = run_finalize(qa_root, judgment(findings=[], verdict="fail",
                                               release_blockers=["W-F-1 (Critical): the guard"]))
    assert rc == 0, capsys.readouterr().err
    f = next(x for x in state["findings"] if x["id"] == "W-F-1")
    assert "contract_dispute" not in f and state["verdict"] == "fail", "the profile switched it off"


def test_a_disputed_finding_that_is_not_alone_caps_but_does_not_lower(repo, qa_root, capsys):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    write_finding(qa_root, _critical_with_fix_breaking(3))
    other = finding("W-F-2", severity="Critical", evidence=["a.py:3 — a second, undisputed defect"])
    write_finding(qa_root, other)
    rc, state = run_finalize(qa_root, judgment(findings=[], verdict="fail",
                                               release_blockers=["W-F-1 (Critical)", "W-F-2 (Critical)"]))
    err = capsys.readouterr().err
    assert rc == 0, err
    assert state["verdict"] == "fail" and state["release_blockers"] == ["W-F-2 (Critical)"]
    assert "capped at Major" in err and "the verdict stands at 'fail'" in err


def test_inside_a_money_gates_own_change_the_money_rule_keeps_precedence(repo, qa_root, capsys):
    """A defect the change made, whose fix fails the change's own tests, is judged as the
    change: the money rule blocks it, the contract rule does not excuse it."""
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    _profile(qa_root, "risk_class: money")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~1..HEAD"]) == 0
    f = finding("W-F-1", severity="Minor", evidence=["a.py:2 — the guard"])
    f["fix_breaks_tests"] = 4
    write_finding(qa_root, f)
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    assert state["verdict"] == "fail", "in the change: the money rule, not the dispute"
    f = next(x for x in state["findings"] if x["id"] == "W-F-1")
    assert "contract_dispute" not in f


def test_fix_breaks_tests_must_be_a_count(repo, qa_root, capsys):
    from verdict_mcp.harness import facts_main
    three_lines(repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    f = finding("W-F-1", severity="Major", evidence=["a.py:2 — the guard"])
    f["fix_breaks_tests"] = "22"
    write_finding(qa_root, f)
    rc, _ = run_finalize(qa_root, judgment(findings=[]))
    assert rc != 0 and "fix_breaks_tests must be a count" in capsys.readouterr().err


# ── the profile field ──────────────────────────────────────────────────────────

from verdict_mcp.profile import risk_class_from  # noqa: E402


@pytest.mark.parametrize("value,expected", [
    ("money", "money"), (" Security ", "security"), ("", None), (None, None)])
def test_risk_class_is_read_in_any_case_and_absent_is_none(value, expected):
    notes = []
    assert risk_class_from({} if value is None else {"risk_class": value}, notes) == expected
    assert notes == []


def test_a_misspelt_risk_class_applies_none_and_says_so():
    notes = []
    assert risk_class_from({"risk_class": "monye"}, notes) is None
    assert notes and "not understood" in notes[0]


def _two_model_session(tmp_path, monkeypatch, session="sess-local-1"):
    """A Claude session that has answered on two models, as a desktop session can."""
    config = tmp_path / "claude-config"
    project = config / "projects" / "-desk"
    project.mkdir(parents=True)
    rows = [json.dumps({"type": "assistant", "requestId": f"r{i}",
                        "timestamp": "2026-10-14T20:00:0%dZ" % i,
                        "message": {"model": model, "usage": {"input_tokens": 10,
                                                              "output_tokens": 5}}})
            for i, model in enumerate(["claude-model-a", "claude-model-b"])]
    (project / f"{session}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", session)


def test_a_local_run_does_not_bill_the_session_that_launched_it(tmp_path, monkeypatch):
    """Found 2026-10-14: run from inside a desktop session that had answered on two models,
    the one-model rule read *that* session's transcript and blocked the finalize tests. A
    `verdict-local` run launched from such a session is judged by a model behind a gateway,
    not by the session, and must not inherit its bill — or its block."""
    _two_model_session(tmp_path, monkeypatch)
    qa = tmp_path / "qa"
    qa.mkdir()
    local = {"measured_at": "2026-10-14T20:00:00Z", "last_run": {"engine": "verdict-local"}}
    assert harness._measure_bill(qa, local) is None
    assert gate_policy({"verdict": "pass with risks", "findings": []},
                       harness._measure_bill(qa, local)) == []
    # Control: the same transcript is still a tester's bill when a Claude session judged.
    tester = harness._measure_bill(qa, {"measured_at": "2026-10-14T20:00:00Z"})
    assert tester is not None and len(tester.get("models") or {}) == 2
    # And the engine's export alone is enough to tell a local run.
    monkeypatch.setenv("VERDICT_MODEL", "local:chat-120b")
    assert harness._measure_bill(qa, {"measured_at": "2026-10-14T20:00:00Z"}) is None
