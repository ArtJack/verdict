"""verdict-backfill: a repro for an old finding, drafted by the local model, kept only if it reproduces (0.92.0)."""

import json
import subprocess
import sys

import pytest

from conftest import git, judgment
from verdict_mcp import backfill, gate, replay
from verdict_mcp.harness import facts_main, finalize_main

PY = sys.executable
PASS_THROUGH = lambda writable: ["env"]          # a stand-in sandbox that runs the command as is
NO_SANDBOX = lambda writable: None

GOOD = "import a\nassert a.x == 2, f\"DEFECT: x is {a.x}, the spec says 2\"\n"


class FakeModel:
    name = "fake-120b"

    def __init__(self, script, explains="x must be 2", then=None):
        self.scripts = [script] + ([then] if then else [])
        self.explains, self.calls, self.prompts = explains, 0, []

    def ask_json(self, prompt, max_tokens=1200):
        self.calls += 1
        self.prompts.append(prompt)
        return {"script": self.scripts[min(self.calls, len(self.scripts)) - 1], "explains": self.explains}


def _sha(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def _old(fid="W-F-1", anchored_at_run=1):
    return {"id": fid, "title": "x is one in a.py where the spec says two", "severity": "Major",
            "status": "open", "confidence": "proven", "anchored_at_run": anchored_at_run,
            "anchors": [{"path": "a.py", "line": 1}], "evidence": ["a.py:1 — `x = 1`"]}


@pytest.mark.parametrize("script, why", [
    ("import subprocess\nassert 1 == 2, 'DEFECT: x'\n", "imports subprocess"),
    ("import os\nos.system('true')\nassert os.sep == 'x', 'DEFECT: x'\n", "calls os.system"),
    ("import a\nassert a.x == 2, a.x\n", "no `assert` whose message carries"),
    ("assert False, 'DEFECT: always'\n", "no `assert` whose message carries"),
    ("import a\nif a.x:\n    raise AssertionError('DEFECT: x')\nassert a.x, 'DEFECT: y'\n", "raises the mark itself"),
    ("def (:\n", "does not parse"),
    ("import a\nassert a is not None, 'DEFECT: no module'\nassert a.x == 2, 'DEFECT: x'\n", "2 assertions carry"),
    (GOOD, None),
])
def test_a_draft_is_checked_before_it_runs(script, why):
    problem = backfill.check_script(script)
    assert (problem is None) if why is None else (problem and why in problem), problem


def test_the_model_reads_the_cited_code_at_head_numbered(repo):
    code = backfill.cited_code(repo, _old())
    assert "# a.py — import it as `a`; it defines: x" in code and "# (lines 1-1)" in code
    assert "    1  x = 1" in code
    assert backfill.citations({"anchors": [{"path": "a.py", "line": 1}],
                               "evidence": ["a.py:1 — x", "b.py:7 — y"]}) == [("a.py", 1), ("b.py", 7)]


def test_a_model_written_repro_never_runs_without_the_sandbox(repo, tmp_path):
    finding = {"id": "W-F-1", "repro": {"command": f'{PY} -c "import a; assert a.x == 2, \'DEFECT: x\'"',
                                        "cwd": "repo", "expect": dict(backfill.EXPECT),
                                        "origin": "backfill 2026-10-18 (fake)"}}
    scratch, _, _ = replay._fresh_checkout(repo)
    try:
        refused = replay.replay_one(finding, repo, scratch, tmp_path, 60, sandbox=NO_SANDBOX)
        ran = replay.replay_one(finding, repo, scratch, tmp_path, 60, sandbox=PASS_THROUGH)
    finally:
        replay._remove_checkout(repo, scratch)
    assert refused["result"] == "could not run" and "only inside a sandbox" in refused["checks"][0]
    assert ran["result"] == "reproduced", ran


def test_a_repro_that_reproduces_at_head_says_still_broken(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    model = FakeModel(GOOD)
    row = backfill.backfill_one(model, repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH)
    assert row["verdict"].startswith(backfill.STILL_BROKEN), row
    assert row["repro"]["origin"].startswith("backfill ") and row["repro"]["expect"] == backfill.EXPECT
    assert row["anchor"] is None, "a defect still there needs no second commit"
    assert (qa / "scratch" / "backfill" / "W-F-1.py").read_text(encoding="utf-8") == GOOD
    assert "x = 1" in model.prompts[0]


def test_a_repro_that_reproduces_only_at_the_anchored_commit_says_looks_fixed(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    anchored = _sha(repo)
    (qa / "runs.jsonl").write_text(json.dumps({"run_number": 1, "git_sha": anchored}) + "\n", encoding="utf-8")
    (repo / "a.py").write_text("x = 2\n", encoding="utf-8")
    git(["commit", "-qam", "fix"], repo)
    row = backfill.backfill_one(FakeModel(GOOD), repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH)
    assert row["verdict"].startswith(f"{backfill.LOOKS_FIXED} since {anchored[:12]}"), row
    assert row["head"]["result"] == "not reproduced" and row["anchor"]["result"] == "reproduced"


def test_a_draft_that_reproduces_nowhere_is_discarded(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    wrong = "import a\nassert a.x == 1, 'DEFECT: wrong expectation'\n"
    row = backfill.backfill_one(FakeModel(wrong), repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH)
    assert row["verdict"].startswith("no working repro"), row


def test_a_refused_draft_is_never_written_or_run(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    row = backfill.backfill_one(FakeModel("import socket\nassert 1 == 2, 'DEFECT: x'\n"), repo, qa,
                                _old(), PY, 60, sandbox=PASS_THROUGH)
    assert row["verdict"] == "no working repro: the draft imports socket"
    assert not (qa / "scratch").exists()


def test_finalize_attaches_a_still_broken_repro_to_its_old_finding(repo, qa_root, capsys):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    (qa_root / "findings").mkdir(exist_ok=True)
    old = {"id": "W-F-1", "title": "x is one in a.py where the spec says two", "severity": "Major",
           "priority": "P1", "status": "open", "failure_classification": "REAL_DEFECT",
           "confidence": "proven", "evidence": ["a.py:1 — `x = 1`"]}
    (qa_root / "findings" / "W-F-1.json").write_text(json.dumps(old), encoding="utf-8")
    (qa_root / "judgment.json").write_text(json.dumps(judgment(findings=[])), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")]) == 0
    capsys.readouterr()
    repro = {"command": f"{PY} /qa/scratch/backfill/W-F-1.py", "cwd": "repo",
             "expect": dict(backfill.EXPECT), "origin": "backfill 2026-10-18 (fake-120b)"}
    (qa_root / replay.BACKFILL_FILE).write_text(json.dumps(
        {"id": "W-F-1", "verdict": f"{replay.STILL_BROKEN}: reproduces at HEAD", "repro": repro}) + "\n",
        encoding="utf-8")
    git(["commit", "-q", "--allow-empty", "-m", "next"], repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    (qa_root / "judgment.json").write_text(json.dumps(judgment(findings=[], still_open=["W-F-1"])),
                                           encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")]) == 0, \
        capsys.readouterr().err
    assert "now carry a model-written repro from verdict-backfill (W-F-1)" in capsys.readouterr().err
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    (f,) = [x for x in state["findings"] if x["id"] == "W-F-1"]
    assert f["repro"] == repro


def test_adoption_skips_a_finding_that_has_a_repro_or_a_row_that_is_not_still_broken():
    mw = {"command": "x", "origin": "backfill 2026-10-18 (m)"}
    findings = [{"id": "A", "status": "open"}, {"id": "B", "status": "open", "repro": {"command": "y"}},
                {"id": "C", "status": "open"}, {"id": "D", "status": "resolved"},
                {"id": "E", "status": "open"}]
    rows = {"A": {"verdict": "still broken: …", "repro": mw}, "B": {"verdict": "still broken: …", "repro": mw},
            "C": {"verdict": "looks fixed since abc", "repro": mw}, "D": {"verdict": "still broken: …", "repro": mw},
            "E": {"verdict": "still broken: …", "repro": {"command": "z"}}}
    assert replay.adopt_backfill(findings, rows) == ["A"], "E's repro is not marked model-written"


def test_the_gate_names_old_findings_that_look_fixed(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / replay.BACKFILL_FILE).write_text("\n".join(json.dumps(r) for r in (
        {"id": "F-1", "verdict": "looks fixed since abc123: …"},
        {"id": "F-2", "verdict": "still broken: …"},
        {"id": "F-3", "verdict": "no working repro: …"})) + "\n", encoding="utf-8")
    out = {"findings_open": [{"id": "F-1"}, {"id": "F-2"}, {"id": "F-3"}, {"id": "F-4"}]}
    gate._backfill_overlay(out, qa)
    line = gate.backfill_line(out)
    assert line.startswith("backfill: 1 open finding(s) look fixed since the commit they were anchored on (F-1)")
    assert "1 still broken, repro attached at the next run (F-2)" in line and "F-3" not in line


def test_a_model_written_repro_sees_none_of_the_callers_secrets(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("SOME_API_TOKEN", "s3cret-value")
    probe = (f'{PY} -c "import os; v = os.environ.get(\'SOME_API_TOKEN\'); '
             f'assert v is not None, \'DEFECT: hidden \' + os.environ[\'HOME\']"')
    finding = {"id": "W-F-9", "repro": {"command": probe, "cwd": "repo", "expect": dict(backfill.EXPECT),
                                        "origin": "backfill 2026-10-18 (fake)"}}
    scratch, _, _ = replay._fresh_checkout(repo)
    try:
        row = replay.replay_one(finding, repo, scratch, tmp_path, 60, sandbox=PASS_THROUGH)
    finally:
        replay._remove_checkout(repo, scratch)
    assert row["result"] == "reproduced", row          # the variable was not there to read
    assert "s3cret-value" not in row["output_tail"] and str(scratch.parent) in row["output_tail"]


def test_the_prompt_names_each_cited_files_import_path_and_what_it_defines(repo):
    (repo / "pkg").mkdir()
    (repo / "pkg" / "fees.py").write_text("RATE = 2\n\nclass Fees:\n    def total(self, a):\n        return a * RATE\n",
                                          encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "fees"], repo)
    code = backfill.cited_code(repo, {"anchors": [{"path": "pkg/fees.py", "line": 5}]})
    assert "import it as `pkg.fees`; it defines: RATE; class Fees: total" in code
    assert backfill.module_of("core/src/sales_core/db.py", ["core/src"]) == "sales_core.db"


def test_a_draft_that_dies_on_an_import_gets_one_repair(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    broken = "from a import nothing_here\nassert nothing_here == 2, 'DEFECT: x'\n"
    model = FakeModel(broken, then=GOOD)
    row = backfill.backfill_one(model, repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH)
    assert row["verdict"].startswith(backfill.STILL_BROKEN) and row.get("repaired") is True, row
    assert model.calls == 2 and "ImportError" in model.prompts[1]
    assert (qa / "scratch" / "backfill" / "W-F-1.py").read_text(encoding="utf-8") == GOOD


def test_a_bare_cited_file_name_is_found_in_the_tree(repo):
    (repo / "core" / "src" / "shop").mkdir(parents=True)
    (repo / "core" / "src" / "shop" / "job_health.py").write_text("def stuck_jobs():\n    return []\n",
                                                                   encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "jobs"], repo)
    code = backfill.cited_code(repo, {"evidence": ["job_health.py:1 — no timeout"]}, roots=["core/src"])
    assert "# core/src/shop/job_health.py — import it as `shop.job_health`" in code


def test_a_draft_that_crashes_on_a_wrong_argument_gets_one_repair(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    crashes = "import a\nint(a.x, unknown_kwarg=1)\nassert a.x == 2, 'DEFECT: x'\n"
    model = FakeModel(crashes, then=GOOD)
    row = backfill.backfill_one(model, repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH)
    assert row.get("repaired") is True and row["verdict"].startswith(backfill.STILL_BROKEN), row
    assert "TypeError" in model.prompts[1]


def test_a_finding_gets_another_draft_told_why_the_last_one_failed(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    wrong = "import a\nassert a.x == 1, 'DEFECT: wrong expectation'\n"
    model = FakeModel(wrong, then=GOOD)
    row = backfill.backfill_one(model, repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH, attempts=3)
    assert row["verdict"].startswith(backfill.STILL_BROKEN) and row["attempts"] == 2, row
    assert "An earlier draft for this finding did not show the defect" in model.prompts[1]


def test_attempts_stop_at_the_limit(repo, tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    model = FakeModel("import a\nassert a.x == 1, 'DEFECT: wrong expectation'\n")
    row = backfill.backfill_one(model, repo, qa, _old(), PY, 60, sandbox=PASS_THROUGH, attempts=2)
    assert row["verdict"].startswith("no working repro") and row["attempts"] == 2 and model.calls == 2


def test_a_model_written_repro_that_stops_reproducing_never_closes_its_finding():
    from verdict_mcp.harness import _apply_replay
    rec = {"at_head": "not reproduced", "at_previous": "reproduced", "previous_sha": "abc1234def",
           "isolated": True}
    model = {"id": "F-1", "status": "open", "delta": "STILL_OPEN",
             "repro": {"command": "x", "origin": "backfill 2026-10-18 (m)"}}
    _apply_replay(model, None, {"F-1": rec}, "2026-10-18T00:00:00Z")
    assert model["status"] == "open" and "resolved_by" not in model and "fix_verified" not in model
    assert model["fix_suspected"].startswith("its model-written repro reproduces at abc1234 and not at HEAD")
    tester = {"id": "F-2", "status": "open", "delta": "STILL_OPEN", "repro": {"command": "x"}}
    _apply_replay(tester, None, {"F-2": dict(rec)}, "2026-10-18T00:00:00Z")
    assert tester["status"] == "resolved" and tester["resolved_by"] == "measurement (repro)"


def test_the_gate_names_a_suspected_fix_with_the_findings_that_look_fixed(tmp_path):
    out = {"findings_open": [{"id": "F-1", "fix_suspected": "its model-written repro …"}, {"id": "F-2"}]}
    gate._backfill_overlay(out, tmp_path)
    assert gate.backfill_line(out).startswith("backfill: 1 open finding(s) look fixed since the commit "
                                              "they were anchored on (F-1)")


def test_the_sandbox_is_sandbox_exec_on_macos_and_nothing_elsewhere(tmp_path, monkeypatch):
    monkeypatch.setattr(replay.sys, "platform", "darwin")
    monkeypatch.setattr(replay.shutil, "which", lambda name: "/usr/bin/sandbox-exec")
    prefix = replay.sandbox_prefix(tmp_path)
    assert prefix[:2] == ["sandbox-exec", "-p"] and "(deny network*)" in prefix[2]
    assert f'(allow file-write* (subpath "{tmp_path.resolve()}")' in prefix[2]
    monkeypatch.setattr(replay.sys, "platform", "linux")
    assert replay.sandbox_prefix(tmp_path) is None
    monkeypatch.setattr(replay.sys, "platform", "darwin")
    monkeypatch.setattr(replay.shutil, "which", lambda name: None)
    assert replay.sandbox_prefix(tmp_path) is None


def _record(repo, home):
    qa = home / "widget"
    qa.mkdir(parents=True)
    (qa / "profile.md").write_text(
        f"---\ntest_one_cmd: {PY} -m pytest {{id}} -q\n---\n\n# QA Profile — widget\n\nProject-Key: widget\n"
        f"Repo-Path: {repo}\n", encoding="utf-8")
    old = dict(_old(), priority="P1", failure_classification="REAL_DEFECT")
    (qa / "state.json").write_text(json.dumps({"project": "widget", "run_number": 1,
                                               "last_run": {"git_sha": _sha(repo)},
                                               "findings": [old]}), encoding="utf-8")
    return qa


def test_the_command_drafts_runs_and_writes_one_row_per_finding(repo, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    qa = _record(repo, home)
    monkeypatch.setenv("VERDICT_HOME", str(home))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gateway.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    monkeypatch.setattr(backfill, "sandbox_prefix", PASS_THROUGH)
    monkeypatch.setattr(backfill, "Model", lambda name, url, token: FakeModel(GOOD))
    original = backfill.backfill_one
    monkeypatch.setattr(backfill, "backfill_one",
                        lambda *a, **k: original(*a, **dict(k, sandbox=PASS_THROUGH)))
    assert backfill.main(["widget", "--model", "fake-120b"]) == 0
    out, err = capsys.readouterr()
    (row,) = [json.loads(line) for line in (qa / replay.BACKFILL_FILE).read_text(encoding="utf-8").splitlines()]
    assert row["id"] == "W-F-1" and row["verdict"].startswith(replay.STILL_BROKEN)
    assert "1 still broken" in out and "no Claude tokens" in out
    assert f"at {_sha(repo)[:12]} (the record's last tested commit)" in err


def test_the_command_refuses_without_a_gateway_or_a_sandbox(repo, tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    _record(repo, home)
    monkeypatch.setenv("VERDICT_HOME", str(home))
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert backfill.main(["widget"]) == 2 and "ANTHROPIC_BASE_URL" in capsys.readouterr().err
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gateway.invalid")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    monkeypatch.setattr(backfill, "sandbox_prefix", NO_SANDBOX)
    assert backfill.main(["widget"]) == 2 and "nothing was drafted" in capsys.readouterr().err
