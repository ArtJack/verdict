"""Questions with a second pen (T-4): parked by the tester, answered by the
maintainer, read by the next run — and pushed to every surface that reaches a
person (H.1), never mailed.

F-26 rode seven runs as a question; boltons parked four in its profile where no
reader would find them. `questions.json` is finalize's; `answers.json` is
`verdict-answer`'s; the guards refuse the second to the tester like they refuse
`accepted.json`.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import judgment
from verdict_mcp import questions as q
from verdict_mcp import server
from verdict_mcp.gate import _fmt_comment, _fmt_text, evaluate
from verdict_mcp.harness import facts_main, finalize_main

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
QUESTION = "Is half-up the rounding rule for cents, or is truncation the documented behaviour?"
ANSWER = "Half-up is the rule; README rule 3 is right and the two truncation tests are wrong."


def finding(fid="W-F-1"):
    return {"id": fid, "title": f"{fid} truncates", "severity": "Major", "priority": "P1",
            "status": "open", "failure_classification": "REAL_DEFECT", "confidence": "proven",
            "evidence": ["a.py:1 — int() truncates"]}


def run_facts(repo, qa_root):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    return json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))


def run_finalize(qa_root, j):
    (qa_root / "judgment.json").write_text(json.dumps(j), encoding="utf-8")
    rc = finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")])
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8")) \
        if (qa_root / "state.json").is_file() else None
    return rc, state


def ask(repo, qa_root, capsys, **over):
    run_facts(repo, qa_root)
    j = judgment(findings=[finding()], questions=[{"question": QUESTION, "finding": "W-F-1",
                                                  "context": "README rule 3 vs money.py:14"}])
    j.update(over)
    rc, state = run_finalize(qa_root, j)
    assert rc == 0, capsys.readouterr().err
    return state


def answer(qa_root, *extra, qid="W-Q-1", text=ANSWER):
    return q.main([str(qa_root), qid, "--answer", text, "--by", "Art", "--today", "2026-09-08",
                   *extra])


# ── finalize's pen ─────────────────────────────────────────────────────────

def test_finalize_mints_the_id_writes_the_ledger_and_renders_the_section(repo, qa_root, capsys):
    state = ask(repo, qa_root, capsys)
    ledger = q.load_questions(qa_root)["questions"]
    assert list(ledger) == ["W-Q-1"]
    entry = ledger["W-Q-1"]
    assert entry["question"] == QUESTION and entry["status"] == "parked"
    assert entry["asked_at_run"] == 1 and entry["finding"] == "W-F-1" and entry["asked_on"]
    parked = state["questions"]["parked"]
    assert parked[0]["id"] == "W-Q-1" and parked[0]["age_days"] == 0
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "## Needs human decision (1 parked)" in report
    assert f"**W-Q-1** (asked run 1, 0d ago · about W-F-1) — {QUESTION}" in report
    assert "verdict-answer widget <Q-id> --answer" in report


def test_the_same_question_asked_again_is_not_minted_twice(repo, qa_root, capsys):
    ask(repo, qa_root, capsys)
    ask(repo, qa_root, capsys, questions=[{"question": "  is HALF-UP the rounding rule for "
                                                       "cents, or is truncation the documented "
                                                       "behaviour "}])
    assert list(q.load_questions(qa_root)["questions"]) == ["W-Q-1"]


def test_a_judgment_question_needs_a_sentence_and_a_known_finding(repo, qa_root, capsys):
    run_facts(repo, qa_root)
    rc, _ = run_finalize(qa_root, judgment(findings=[finding()],
                                           questions=[{"question": "rounding?"},
                                                      {"question": QUESTION, "finding": "W-F-7"}]))
    err = capsys.readouterr().err
    assert rc == 1
    assert "questions[0] needs a `question` a person can answer" in err
    assert "questions[1] refers to finding 'W-F-7'" in err


# ── the maintainer's pen ───────────────────────────────────────────────────

def test_verdict_answer_writes_its_own_ledger_and_refuses_what_it_should(repo, qa_root, capsys):
    ask(repo, qa_root, capsys)
    assert answer(qa_root, qid="W-Q-9") == 2
    assert "no question 'W-Q-9'" in capsys.readouterr().err
    assert answer(qa_root, text="yes") == 2
    assert "needs a real answer" in capsys.readouterr().err
    assert not (qa_root / q.ANSWERS_FILE).exists(), "a refusal writes nothing"
    assert answer(qa_root) == 0
    out = capsys.readouterr().out
    assert "answered W-Q-1" in out and "the next run reads the decision" in out
    recorded = q.load_answers(qa_root)["W-Q-1"]
    assert recorded == {"answer": ANSWER, "by": "Art", "on": "2026-09-08"}
    assert answer(qa_root) == 2
    assert "already answered" in capsys.readouterr().err
    # the tester's ledger was not touched by the maintainer's pen
    assert q.load_questions(qa_root)["questions"]["W-Q-1"]["status"] == "parked"
    assert q.main([str(qa_root), "--list"]) == 0
    listed = capsys.readouterr().out
    assert "W-Q-1" in listed and "answered" in listed and ANSWER[:30] in listed


def test_dismiss_needs_a_reason_and_records_it(repo, qa_root, capsys):
    ask(repo, qa_root, capsys)
    assert q.main([str(qa_root), "W-Q-1", "--dismiss", "--reason", "short", "--today", "2026-09-08"]) == 2
    assert q.main([str(qa_root), "W-Q-1", "--dismiss", "--reason",
                   "Not a decision we will make this quarter; leave the code as it is.",
                   "--by", "Art", "--today", "2026-09-08"]) == 0
    assert q.load_answers(qa_root)["W-Q-1"]["dismissed"] is True


# ── the next run reads the decision ────────────────────────────────────────

def test_the_next_run_reads_the_answer_and_nobody_asks_again(repo, qa_root, capsys):
    ask(repo, qa_root, capsys)
    assert answer(qa_root) == 0
    facts = run_facts(repo, qa_root)
    assert facts["questions"]["parked"] == []
    fresh = facts["questions"]["answered_since_last_run"]
    assert fresh[0]["id"] == "W-Q-1" and fresh[0]["answer"] == ANSWER and fresh[0]["by"] == "Art"
    # the agent asks it again anyway: not re-minted, and the report shows the answer once
    state = ask(repo, qa_root, capsys)
    assert list(q.load_questions(qa_root)["questions"]) == ["W-Q-1"]
    entry = q.load_questions(qa_root)["questions"]["W-Q-1"]
    assert entry["status"] == "answered" and entry["acknowledged_at_run"] == 2
    assert state["questions"]["parked"] == []
    assert state["questions"]["answered_since_last_run"][0]["answer"] == ANSWER
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "### Answered since the last run" in report and ANSWER in report
    # acknowledged: the run after reads nothing new, and the state carries no section
    facts = run_facts(repo, qa_root)
    assert facts["questions"]["answered_since_last_run"] == []
    rc, state = run_finalize(qa_root, judgment(findings=[], still_open=["W-F-1"]))
    assert rc == 0, capsys.readouterr().err
    assert "questions" not in state


def test_a_project_that_never_asked_has_no_questions_fact(repo, qa_root):
    facts = run_facts(repo, qa_root)
    assert "questions" not in facts
    assert q.facts_view(qa_root, __import__("datetime").date(2026, 9, 8)) is None


# ── the surfaces ───────────────────────────────────────────────────────────

def _hook(script, payload, cwd=None):
    env = {k: v for k, v in os.environ.items() if k not in ("VERDICT_STRICT", "VERDICT_HOME")}
    env["VERDICT_STRICT"] = "1"
    return subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(payload),
                          capture_output=True, text=True, env=env, encoding="utf-8", cwd=cwd)


def test_the_guards_refuse_the_answers_ledger_to_the_tester(repo):
    qa = repo / ".qa"
    qa.mkdir()
    target = qa / q.ANSWERS_FILE
    proc = _hook("enforce_write_scope.py", {"tool_name": "Write",
                                            "tool_input": {"file_path": str(target)}})
    assert proc.returncode == 2 and "verdict-answer" in proc.stderr and "grading its own paper" in proc.stderr
    proc = _hook("enforce_bash_scope.py", {"tool_name": "Bash", "cwd": str(repo),
                                           "tool_input": {"command": f"echo '{{}}' > {target}"}})
    assert proc.returncode == 2 and "verdict-answer" in proc.stderr
    # the tester's own ledger stays writable: it is finalize's file, inside scope
    proc = _hook("enforce_write_scope.py", {"tool_name": "Write",
                                            "tool_input": {"file_path": str(qa / q.QUESTIONS_FILE)}})
    assert proc.returncode == 0


def test_the_banner_the_gate_and_the_server_say_what_is_waiting(repo, capsys):
    qa = repo / ".qa"
    (qa / "reports").mkdir(parents=True)
    ask(repo, qa, capsys)
    proc = _hook("report_open_findings.py", {"hook_event_name": "SessionStart", "cwd": str(repo)},
                 cwd=repo)
    assert proc.returncode == 0
    assert "1 question waiting for you — W-Q-1: " + QUESTION[:60] in proc.stdout
    assert "verdict-answer widget W-Q-1 --answer" in proc.stdout
    r = evaluate(str(qa), "fail", None, None)
    assert r["questions_parked"][0]["id"] == "W-Q-1"
    assert "needs human decision: 1 parked — W-Q-1: " in _fmt_text(r, 5)
    assert "**Needs human decision (1 parked):**" in _fmt_comment(r, 5)
    got = server.get_questions(str(qa))
    assert got["count"] == 1 and got["parked"][0]["question"] == QUESTION
    assert got["answer_with"].startswith("verdict-answer widget ")
    # answered: the banner and the gate stop asking, the server shows the answer
    assert answer(qa) == 0
    proc = _hook("report_open_findings.py", {"hook_event_name": "SessionStart", "cwd": str(repo)},
                 cwd=repo)
    assert "waiting for you" not in proc.stdout
    assert "questions_parked" not in evaluate(str(qa), "fail", None, None)
    assert server.get_questions(str(qa))["answered_since_last_run"][0]["answer"] == ANSWER
