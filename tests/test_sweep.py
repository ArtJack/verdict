"""The model-free night (T-5): `verdict-run --skip-unless-drift`.

HEAD moved, but by a commit that touched nothing any finding cites; the gates
are green, the test-id set is unchanged, no quarantine is due, no cited line
moved. Then the runner finalizes a sweep — the previous verdict carried by id,
signed by no model, run number advanced — and spends nothing. Any condition
failing runs the model, and says which.
"""

import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

from test_runner import write_stub
from verdict_mcp.harness import facts_main, finalize_main
from verdict_mcp.runner import sweep_blockers, sweep_judgment

RUNNER = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "runner.py"
PY = f'"{sys.executable}"'
STUB = "import os\nfrom pathlib import Path\nPath(os.environ['ARGV_OUT']).write_text('ran')\nprint('stub ran')\n"


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def project(tmp_path):
    """A repo with a cited module, an uncited module, a green test, a profile
    naming the gate and the id command, and run 1 finalized with anchors."""
    repo = tmp_path / "Proj"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    (repo / "cited.py").write_bytes(b"def a(x):\n    return x + 1\n")
    (repo / "other.py").write_bytes(b"def b(x):\n    return x\n")
    (repo / "test_a.py").write_bytes(b"from cited import a\n\ndef test_a():\n    assert a(1) == 2\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    home = tmp_path / "home"
    qa = home / "proj"
    (qa / "reports").mkdir(parents=True)
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: {PY} -m pytest -q -p no:cacheprovider\n"
        f"test_ids_cmd: {PY} -m pytest --collect-only -q -p no:cacheprovider\n---\n\n"
        "# QA Profile — proj\n\nProject-Key: proj\n", encoding="utf-8")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    judgment = {"topic": "baseline", "verdict": "pass with risks", "isolation_check": {"result": "pass"},
                "release_blockers": [], "not_tested": ["concurrency"],
                "findings": [{"id": "PROJ-F-1", "title": "a is off by one", "severity": "Major",
                              "priority": "P1", "status": "open", "failure_classification": "REAL_DEFECT",
                              "confidence": "proven", "evidence": ["cited.py:2 — `return x + 1`"]}]}
    (qa / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    return repo, home, qa


def run(tmp_path, repo, home, *extra):
    launcher = write_stub(tmp_path, STUB, name="claude-stub")   # a .cmd on Windows
    out = tmp_path / "argv.json"
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env.update(VERDICT_HOME=str(home), ARGV_OUT=str(out))
    proc = subprocess.run([sys.executable, str(RUNNER), "--repo", str(repo), "--claude-cmd",
                           str(launcher), "--model", "opus", "--no-provision", *extra],
                          capture_output=True, text=True, env=env, encoding="utf-8",
                          errors="replace")
    return proc, out.exists()


def state_of(qa):
    return json.loads((qa / "state.json").read_text(encoding="utf-8"))


def test_a_commit_that_touches_nothing_cited_is_swept_without_a_model(tmp_path):
    repo, home, qa = project(tmp_path)
    (repo / "other.py").write_bytes(b"def b(x):\n    return x  # untouched by any finding\n")
    git(repo, "commit", "-qam", "touch other.py")
    proc, model_ran = run(tmp_path, repo, home, "--skip-unless-drift")
    assert not model_ran, proc.stderr
    assert "verdict-run: swept — run 2" in proc.stderr and "no model call" in proc.stderr
    assert "1 commit(s), 1 file(s) changed, none cited by a finding" in proc.stderr
    s = state_of(qa)
    assert s["run_number"] == 2 and s["run_type"] == "sweep" and s["verdict"] == "pass with risks"
    assert s["last_run"]["model"] == "none"
    f = s["findings"][0]
    assert f["delta"] == "STILL_OPEN" and f["re_reported"] == "still_open" and f["age_days"] == 0
    assert s["not_tested"][0].startswith("everything a judgment covers")
    assert s["isolation_check"]["result"] == "n/a"
    report = (qa / s["last_run"]["report"]).read_text(encoding="utf-8")
    assert "run 2 (sweep)" in report and "Model-free sweep over" in report
    assert proc.returncode == 0, proc.stdout + proc.stderr
    rows = [json.loads(ln) for ln in (qa / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["run_type"] == "sweep" and rows[-1]["run_number"] == 2


def test_a_commit_that_touches_a_cited_file_runs_the_model_and_says_why(tmp_path):
    repo, home, qa = project(tmp_path)
    (repo / "cited.py").write_bytes(b"def a(x):\n    return x + 1  # a comment on the cited line\n")
    git(repo, "commit", "-qam", "touch cited.py")
    proc, model_ran = run(tmp_path, repo, home, "--skip-unless-drift")
    assert model_ran, proc.stderr
    assert "verdict-run: no sweep — " in proc.stderr
    assert "cited code moved or changed: PROJ-F-1" in proc.stderr
    assert "changed files a finding cites: cited.py" in proc.stderr
    assert state_of(qa)["run_number"] == 1, "the stub wrote no state; nothing was swept"


def test_the_unchanged_head_path_still_applies(tmp_path):
    repo, home, qa = project(tmp_path)
    proc, model_ran = run(tmp_path, repo, home, "--skip-unless-drift")
    assert not model_ran and "HEAD unchanged since run 1" in proc.stderr
    assert state_of(qa)["run_number"] == 1


# ── the tier below the sweep: --on-drift ──────────────────────────────────

def env_file(tmp_path, base="http://127.0.0.1:1"):
    path = tmp_path / "gw.env"
    path.write_text(f"ANTHROPIC_BASE_URL={base}\nANTHROPIC_AUTH_TOKEN=t\n", encoding="utf-8")
    return path


def test_on_drift_local_never_launches_claude(tmp_path):
    """The whole point of the tier. The sweep is blocked — a cited file moved —
    and a night told to be local goes to the gateway or nowhere. The stub CLI is
    the instrument: if it ever ran, it would leave its file behind."""
    repo, home, qa = project(tmp_path)
    (repo / "cited.py").write_bytes(b"def a(x):\n    return x + 1  # touched\n")
    git(repo, "commit", "-qam", "touch cited.py")
    proc, model_ran = run(tmp_path, repo, home, "--on-drift", "local",
                          "--local-env-file", str(env_file(tmp_path)))
    assert not model_ran, proc.stderr
    assert proc.returncode == 5, proc.stderr
    assert "the local gateway is down" in proc.stderr
    assert state_of(qa)["run_number"] == 1, "nothing was written"
    assert not (qa / "run-in-progress.json").exists(), \
        "a night that never started must not leave a marker claiming it did"


def test_on_drift_local_refuses_without_an_endpoint(tmp_path):
    """Refused before anything runs, because the alternative — quietly spending
    the expensive model instead — is the outcome this release exists to remove."""
    repo, home, _qa = project(tmp_path)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("VERDICT_") and not k.startswith("ANTHROPIC_")}
    env["VERDICT_HOME"] = str(home)
    env["ARGV_OUT"] = str(tmp_path / "argv.json")
    proc = subprocess.run([sys.executable, str(RUNNER), "--repo", str(repo),
                           "--claude-cmd", "definitely-not-on-path",
                           "--no-provision", "--on-drift", "local"],
                          capture_output=True, text=True, env=env, encoding="utf-8",
                          errors="replace")
    assert proc.returncode == 2, proc.stderr
    assert "--on-drift local needs ANTHROPIC_BASE_URL" in proc.stderr
    assert "must not fall through to a Claude run" in proc.stderr
    assert "not found on PATH" not in proc.stderr, \
        "a local night does not need the claude CLI, so a missing one is not its problem"


def test_on_drift_none_writes_nothing_and_says_the_run_did_not_happen(tmp_path):
    repo, home, qa = project(tmp_path)
    (repo / "cited.py").write_bytes(b"def a(x):\n    return x + 1  # touched\n")
    git(repo, "commit", "-qam", "touch cited.py")
    proc, model_ran = run(tmp_path, repo, home, "--on-drift", "none")
    assert not model_ran and proc.returncode == 5, proc.stderr
    assert "--on-drift none forbids a model run" in proc.stderr
    assert state_of(qa)["run_number"] == 1
    assert not (qa / "run-in-progress.json").exists()


def test_on_drift_local_still_sweeps_when_it_can_and_names_the_dead_gateway(tmp_path):
    """The sweep is allowed, so the night is still worth something — and the
    not_tested says the model was unreachable, rather than leaving a reader to
    assume the sweep was a choice."""
    repo, home, qa = project(tmp_path)
    (repo / "other.py").write_bytes(b"def b(x):\n    return x  # untouched by any finding\n")
    git(repo, "commit", "-qam", "touch other.py")
    proc, model_ran = run(tmp_path, repo, home, "--on-drift", "local",
                          "--local-env-file", str(env_file(tmp_path)))
    assert not model_ran and proc.returncode == 0, proc.stderr
    s = state_of(qa)
    assert s["run_type"] == "sweep" and s["run_number"] == 2
    assert any("the local model was unreachable" in line for line in s["not_tested"])


def test_on_drift_model_is_the_default_and_unchanged(tmp_path):
    repo, home, qa = project(tmp_path)
    (repo / "cited.py").write_bytes(b"def a(x):\n    return x + 1  # touched\n")
    git(repo, "commit", "-qam", "touch cited.py")
    proc, model_ran = run(tmp_path, repo, home, "--skip-unless-drift")
    assert model_ran, proc.stderr
    assert state_of(qa)["run_number"] == 1


def test_every_blocker_is_a_measurement():
    today = date(2026, 9, 8)
    facts = {"evidence_drift": {"status": "measured", "summary": {"drifted_findings": [],
                                                                    "drifted_accepted": [],
                                                                    "drifted_intact": []}},
             "gates": {"suite": {"result": "pass", "counts": {"passed": 3}}},
             "test_ids": {"status": "measured", "added_count": 0, "removed_count": 0},
             "coverage": {"status": "measured", "changed_lines": 4, "changed_lines_executed": 2}}
    previous = {"findings": [{"id": "P-F-1", "status": "open", "anchors": [{"path": "a.py", "line": 1}]}],
                "flaky_quarantine": [{"test_id": "t::x", "quarantined_until": "2026-09-20"}]}
    assert sweep_blockers(facts, previous, ["b.py"], today) == []
    assert "changed files a finding cites: a.py" in sweep_blockers(facts, previous, ["a.py", "b.py"], today)
    red = json.loads(json.dumps(facts)); red["gates"]["suite"]["result"] = "fail"
    assert "gate suite failed" in sweep_blockers(red, previous, ["b.py"], today)
    unparsed = json.loads(json.dumps(facts)); unparsed["gates"]["suite"] = {"result": "pass", "counts_unparsed": "x"}
    why = sweep_blockers(unparsed, previous, ["b.py"], today)
    assert "gate suite: counts unparsed" in why and "no gate produced test counts" in why
    ids = json.loads(json.dumps(facts)); ids["test_ids"]["removed_count"] = 2
    assert "the test-id set changed (+0/-2)" in sweep_blockers(ids, previous, ["b.py"], today)
    assert "quarantine due: t::x" in sweep_blockers(facts, previous, ["b.py"], date(2026, 9, 21))
    moved = json.loads(json.dumps(facts)); moved["evidence_drift"]["summary"]["drifted_findings"] = ["P-F-1"]
    assert "cited code moved or changed: P-F-1" in sweep_blockers(moved, previous, ["b.py"], today)
    unmeasured = json.loads(json.dumps(facts)); unmeasured["evidence_drift"] = {"status": "unavailable", "reason": "no anchors"}
    assert "evidence drift not measured (no anchors)" in sweep_blockers(unmeasured, previous, ["b.py"], today)
    cold = json.loads(json.dumps(facts)); cold["coverage"]["changed_lines_executed"] = 0
    assert "the diff has changed lines no test executed" in sweep_blockers(cold, previous, ["b.py"], today)
    assert "no commit range to compare" in sweep_blockers(facts, previous, None, today)
    incomplete = json.loads(json.dumps(facts)); incomplete["previous_run_incomplete"] = {"x": 1}
    assert "the previous run never finished" in sweep_blockers(incomplete, previous, ["b.py"], today)


def test_a_sweep_carries_verified_intact_and_says_nothing_outside_was_read():
    """P-32: the sweep used to write `verified_intact: []`, so the cheapest run in
    the system silently deleted the list the NEXT sweep is supposed to guard —
    and the confirmation the first external user said he was paying for. It also
    now states the one limit a model-free run shares with a local one: nothing
    outside the checkout was read, so a standing blocker quoting a production
    number was not re-checked."""
    previous = {"verdict": "pass", "findings": [],
                "verified_intact": ["net proceeds never go negative",
                                    "no order is charged twice"]}
    j = sweep_judgment({"last_run": {"sha_range": "a..b"}}, previous, ["x.py"], 1)
    assert j["verified_intact"] == ["net proceeds never go negative",
                                    "no order is charged twice"]
    assert any("nothing outside the checkout was read" in line for line in j["not_tested"])
    with_note = sweep_judgment({"last_run": {}}, previous, [], 1, ["the model was unreachable"])
    assert with_note["not_tested"][-1] == "the model was unreachable"


def test_the_synthetic_judgment_carries_every_open_finding_by_id_and_nothing_else():
    previous = {"verdict": "fail", "release_blockers": ["P-F-1 — data loss"],
                "next_run_focus": ["re-verify P-F-1"], "flaky_quarantine": [],
                "findings": [{"id": "P-F-1", "status": "open"}, {"id": "P-F-2", "status": "accepted"},
                             {"id": "P-F-3", "status": "resolved"}]}
    j = sweep_judgment({"last_run": {"sha_range": "a..b"}}, previous, ["x.py", "y.py"], 3)
    assert j["still_open"] == ["P-F-1"] and j["findings"] == [] and j["resolved"] == []
    assert j["verdict"] == "fail" and j["release_blockers"] == ["P-F-1 — data loss"]
    assert j["topic"] == "sweep" and j["isolation_check"]["result"] == "n/a"
    assert "3 commits (2 files changed, none cited by a finding)" in j["not_tested"][0]
    assert j["next_run_focus"] == ["re-verify P-F-1"] and j["questions"] == []


def test_the_harness_child_imports_the_code_the_runner_is(monkeypatch):
    """Measured on the Sales nightly: `python3 src/verdict_mcp/runner.py`, started by an
    interpreter that never installed the package, could not `-m verdict_mcp.harness`, and
    every sweep from 2026-09-17 ended `No module named 'verdict_mcp'` — exit 5, nothing
    measured. The child is handed the runner's own source root — on its own sys.path, never
    in the environment: 0.90.0 used PYTHONPATH, every grandchild inherited it, and from an
    installed verdict that was the whole site-packages of Verdict's environment. The Sales
    pytest imported Verdict's packages and collected 925 of ~3,450 tests (2026-09-18)."""
    from verdict_mcp import runner
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = cmd, kw
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    runner._harness("facts", "--help")
    exe, flag, _boot, src, *rest = seen["cmd"]
    assert (exe, flag, rest) == (sys.executable, "-c", ["facts", "--help"])
    assert (Path(src) / "verdict_mcp" / "harness.py").is_file(), src
    assert seen["kw"].get("env") is None, "the environment is inherited untouched"


def test_the_harness_bootstrap_runs_the_subcommand_it_is_given():
    """The bootstrap for real: it takes its path argument off argv before the harness
    parses it, and dispatches the subcommand that follows."""
    from verdict_mcp import runner
    proc = runner._harness("facts", "--help")
    assert proc.returncode == 0, proc.stderr[-400:]
    assert proc.stdout.startswith("usage: verdict-facts"), proc.stdout[:200]
