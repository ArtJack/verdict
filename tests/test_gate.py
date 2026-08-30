"""Tests for verdict-gate, run exactly the way the Action's gate mode runs it:
as a bare script with zero installs."""

import json
import os
import subprocess
import sys
from pathlib import Path


GATE = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "gate.py"

BASE_STATE = {
    "project": "pricer", "schema_version": 1, "run_type": "delta", "run_number": 4,
    "last_run": {"timestamp_utc": "2026-08-24T17:30:00Z", "git_sha": "b4e2943",
                 "sha_range": "2c67f47..b4e2943",
                 "report": "reports/2026-08-24-payment-retry.md"},
    "isolation_check": {"result": "pass"},
    "gates": {}, "tests": {"collected": 1, "passed": 1, "skipped": 0, "failed": 0},
    "flaky_quarantine": [],
    "findings": [
        {"id": "PRC-F-2", "hash": "b", "first_seen": "2026-08-19", "status": "open",
         "delta": "REGRESSED", "age_days": 5, "title": "banker's rounding is back",
         "severity": "Critical", "priority": "P0",
         "failure_classification": "REAL_DEFECT", "evidence": ["pricer.py:17 round(amount, 2)"]},
        {"id": "PRC-F-9", "hash": "c", "first_seen": "2026-08-24", "status": "open",
         "delta": "NEW", "age_days": 0, "title": "minor nit | with a pipe",
         "severity": "Minor", "priority": "P3",
         "failure_classification": None, "evidence": []},
    ],
    "verdict": "fail", "release_blockers": ["PRC-F-2"],
    "not_tested": ["concurrency"],
}


def make_home(tmp_path, **overrides):
    state = {**BASE_STATE, **overrides}
    root = tmp_path / "home" / "pricer"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return tmp_path / "home"


# BASE_STATE carries an open Critical, so a `pass` over it is a state that
# contradicts itself — the gate refuses it, and the tests that only want to
# exercise "verdict pass → exit 0" have to say so with findings that permit one.
NOTHING_BLOCKING = [f for f in BASE_STATE["findings"] if f["severity"] == "Minor"]
PASSABLE = {"verdict": "pass", "release_blockers": [], "findings": NOTHING_BLOCKING}


def gate(tmp_path, *args, home=None, cwd=None, state_kwargs=None):
    home = home or make_home(tmp_path, **(state_kwargs or {}))
    # Inherit the environment (Windows Python cannot start without SystemRoot);
    # strip only Verdict's own variables so the test home is authoritative.
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    env["VERDICT_HOME"] = str(home)
    proc = subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True, text=True, cwd=cwd, env=env,
    )
    return proc


def test_fail_exits_1(tmp_path):
    proc = gate(tmp_path, "pricer")
    assert proc.returncode == 1
    assert "VERDICT: fail" in proc.stdout


def test_pass_exits_0(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs=PASSABLE)
    assert proc.returncode == 0


def test_pass_with_risks_default_accepts(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs={"verdict": "pass with risks"})
    assert proc.returncode == 0
    assert "accepted" in proc.stdout


def test_pass_with_risks_fails_under_fail_on_risks(tmp_path):
    proc = gate(tmp_path, "pricer", "--fail-on", "risks",
                state_kwargs={"verdict": "pass with risks"})
    assert proc.returncode == 1


def test_blocked_exits_3(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs={"verdict": "blocked"})
    assert proc.returncode == 3


def test_no_state_exits_4(tmp_path):
    proc = gate(tmp_path, "nope")
    assert proc.returncode == 4
    assert "no Verdict state" in proc.stdout


def test_corrupt_state_exits_4(tmp_path):
    home = make_home(tmp_path)
    (home / "pricer" / "state.json").write_text("{broken", encoding="utf-8")
    proc = gate(tmp_path, "pricer", home=home)
    assert proc.returncode == 4


def test_min_run_number_exits_5(tmp_path):
    proc = gate(tmp_path, "pricer", "--min-run-number", "5")
    assert proc.returncode == 5
    assert "stale" in proc.stdout


def test_max_age_exits_5(tmp_path):
    proc = gate(tmp_path, "pricer", "--max-age-hours", "1")
    assert proc.returncode == 5


def test_stale_check_outranks_a_passing_verdict(tmp_path):
    proc = gate(tmp_path, "pricer", "--min-run-number", "5",
                state_kwargs={"verdict": "pass", "release_blockers": []})
    assert proc.returncode == 5


def test_github_output_format(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "github-output")
    assert "verdict=fail" in proc.stdout
    assert "exit-code=1" in proc.stdout
    assert 'blockers=["PRC-F-2"]' in proc.stdout


def test_github_comment_marker_and_ordering(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "github-comment")
    out = proc.stdout
    assert out.startswith("<!-- verdict-gate -->")
    assert out.index("REGRESSED") < out.index("NEW")
    assert "\\|" in out  # pipe in a title is escaped, not table-breaking


def test_json_format(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "json")
    data = json.loads(proc.stdout)
    assert data["exit_code"] == 1 and data["verdict"] == "fail"
    assert data["findings_open"][0]["id"] == "PRC-F-2"


def test_min_run_number_exact_boundary_passes(tmp_path):
    # run_number == required is satisfied; only < is stale (kills < -> <=)
    proc = gate(tmp_path, "pricer", "--min-run-number", "4", state_kwargs=PASSABLE)
    assert proc.returncode == 0


def test_max_age_within_window_passes_and_unparseable_is_stale(tmp_path):
    from datetime import datetime, timedelta, timezone
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    proc = gate(tmp_path, "pricer", "--max-age-hours", "2",
                state_kwargs={**PASSABLE,
                              "last_run": {**BASE_STATE["last_run"],
                                           "timestamp_utc": fresh}})
    assert proc.returncode == 0
    proc = gate(tmp_path, "pricer", "--max-age-hours", "2",
                state_kwargs={"verdict": "pass", "release_blockers": [],
                              "last_run": {**BASE_STATE["last_run"],
                                           "timestamp_utc": "not a time"}})
    assert proc.returncode == 5


def test_unknown_verdict_exits_4(tmp_path):
    proc = gate(tmp_path, "pricer", state_kwargs={"verdict": "maybe"})
    assert proc.returncode == 4
    assert "no usable verdict" in proc.stdout


def test_stale_outranks_blocked(tmp_path):
    # precedence: 'the expected run never happened' beats 'the last run was blocked'
    proc = gate(tmp_path, "pricer", "--min-run-number", "9",
                state_kwargs={"verdict": "blocked"})
    assert proc.returncode == 5


def test_json_contract_fields(tmp_path):
    data = json.loads(gate(tmp_path, "pricer", "--format", "json").stdout)
    assert data["project"] == "pricer"
    assert data["run_type"] == "delta"
    assert data["sha_range"] == "2c67f47..b4e2943"
    assert data["last_run_utc"] == "2026-08-24T17:30:00Z"
    assert data["not_tested"] == ["concurrency"]
    assert data["report"] == "reports/2026-08-24-payment-retry.md"
    missing = json.loads(gate(tmp_path, "nope", "--format", "json").stdout)
    assert missing["exit_code"] == 4 and missing["known_projects"] == ["pricer"]


def test_sarif_format(tmp_path):
    proc = gate(tmp_path, "pricer", "--format", "sarif")
    sarif = json.loads(proc.stdout)
    assert sarif["version"] == "2.1.0"
    run = sarif["runs"][0]
    assert run["tool"]["driver"]["name"] == "verdict-gate"
    results = {r["ruleId"]: r for r in run["results"]}
    reg = results["PRC-F-2"]
    assert reg["level"] == "error"  # Critical -> error
    assert results["PRC-F-9"]["level"] == "note"  # Minor -> note
    # location parsed from "cart.py:88"-style evidence
    loc = reg["locations"][0]["physicalLocation"]
    assert loc["artifactLocation"]["uri"] == "pricer.py"
    assert loc["region"]["startLine"] == 17
    assert proc.returncode == 1  # exit contract unchanged by format


def test_default_resolution_prefers_team_qa(tmp_path):
    repo = tmp_path / "myapp"
    (repo / ".qa" / "reports").mkdir(parents=True)
    (repo / ".qa" / "state.json").write_text(
        json.dumps({**BASE_STATE, "project": "myapp", **PASSABLE}), encoding="utf-8")
    home = tmp_path / "empty-home"
    home.mkdir()
    proc = gate(tmp_path, home=home, cwd=repo)
    assert proc.returncode == 0
    assert "team-mode" in json.loads(gate(tmp_path, "--format", "json",
                                          home=home, cwd=repo).stdout)["resolved_via"]


def test_open_findings_are_counted_whatever_the_case_of_the_status(tmp_path):
    """The bug this caught in production: a baseline wrote "OPEN", and the gate
    reported zero open findings for a project holding seven, one Critical."""
    findings = [dict(f, status=f["status"].upper()) for f in BASE_STATE["findings"]]
    out = json.loads(gate(tmp_path, "pricer", "--format", "json",
                          state_kwargs={"findings": findings}).stdout)
    assert [f["id"] for f in out["findings_open"]] == ["PRC-F-2", "PRC-F-9"]


def test_require_harness_separates_a_measured_run_from_a_composed_one(tmp_path):
    """Exit 6, distinct from 4 (never ran) and 5 (ran too long ago): the tester
    ran and wrote a state, but composed the numbers instead of measuring them."""
    home = make_home(tmp_path)
    root = home / "pricer"
    assert gate(tmp_path, "pricer", "--require-harness", home=home).returncode == 6

    # now furnish the traces a real pipeline leaves
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    stamp = state["last_run"]["timestamp_utc"]
    state["calibration"] = {"decided_outcomes": 0}
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (root / "facts.json").write_text(json.dumps({"measured_at": stamp}), encoding="utf-8")
    (root / "judgment.json").write_text("{}", encoding="utf-8")
    (root / "reports").mkdir(exist_ok=True)
    (root / state["last_run"]["report"]).write_text(
        "# report\n\n*Countable sections rendered from `state.json` by "
        "`verdict-finalize`; the prose is the agent's.*\n", encoding="utf-8")
    proc = gate(tmp_path, "pricer", "--require-harness", "--format", "json", home=home)
    assert proc.returncode == 1, "the fail verdict decides once the run is admissible"
    assert all(json.loads(proc.stdout)["harness"].values())


def test_stale_facts_from_an_earlier_run_do_not_count_as_measured(tmp_path):
    """facts.json survives in the QA root. A later hand-written run would inherit
    it, so the file must describe *this* run to count."""
    home = make_home(tmp_path)
    root = home / "pricer"
    (root / "facts.json").write_text(
        json.dumps({"measured_at": "2020-01-01T00:00:00Z"}), encoding="utf-8")
    proc = gate(tmp_path, "pricer", "--require-harness", "--format", "json", home=home)
    assert proc.returncode == 6, "no durable trace either, so the state is refused"
    assert json.loads(proc.stdout)["harness"]["facts_measured"] is False, \
        "and the stale facts.json is still not counted as this run's measurement"


def test_the_gate_refuses_a_state_that_contradicts_itself(tmp_path):
    """A recorded verdict standing over findings that forbid it is not a verdict.
    Serving it green is how a false pass reaches a merge — which is exactly what
    a `pass` over a Critical typed `"closed"` used to do."""
    critical = dict(BASE_STATE["findings"][0], severity="Critical", status="closed")
    proc = gate(tmp_path, "pricer", state_kwargs={
        "verdict": "pass", "release_blockers": [], "findings": [critical]})
    assert proc.returncode == 1
    assert "contradicts itself" in proc.stdout

    blocker = dict(BASE_STATE["findings"][0], severity="Blocker", status="open")
    proc = gate(tmp_path, "pricer", state_kwargs={
        "verdict": "pass with risks", "release_blockers": [], "findings": [blocker]})
    assert proc.returncode == 1 and "no verdict but `fail`" in proc.stdout


def test_an_open_critical_still_allows_pass_with_risks(tmp_path):
    """§10 caps it there rather than forbidding it — the gate must not invent a
    stricter rule than the contract states."""
    critical = dict(BASE_STATE["findings"][0], severity="Critical", status="open")
    proc = gate(tmp_path, "pricer", state_kwargs={
        "verdict": "pass with risks", "release_blockers": [], "findings": [critical]})
    assert proc.returncode == 0


def test_require_harness_survives_a_checkout_that_drops_the_scratch(tmp_path):
    """A team-mode `.qa/` gitignores facts.json and judgment.json — they are
    per-run scratch. Requiring all four traces would have failed the exact
    deployment this check exists for, on a state the harness genuinely produced.
    The durable pair decides: `calibration` is written only by `merge`, the
    footer only by the renderer."""
    home = make_home(tmp_path)
    root = home / "pricer"
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    state["calibration"] = {"decided_outcomes": 0}
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (root / "reports").mkdir(exist_ok=True)
    (root / state["last_run"]["report"]).write_text(
        "# report\n\n*Countable sections rendered from `state.json` by "
        "`verdict-finalize`; the prose is the agent's.*\n", encoding="utf-8")
    # no facts.json, no judgment.json — as a fresh checkout leaves it
    proc = gate(tmp_path, "pricer", "--require-harness", "--format", "json", home=home)
    assert proc.returncode == 1, "the fail verdict decides; the run is admissible"
    signals = json.loads(proc.stdout)["harness"]
    assert signals["state_computed"] and signals["report_rendered"]
    assert not signals["facts_measured"], "reported, but not required"


def test_require_harness_still_refuses_a_state_with_neither_durable_trace(tmp_path):
    proc = gate(tmp_path, "pricer", "--require-harness", home=make_home(tmp_path))
    assert proc.returncode == 6 and "hand-written state" in proc.stdout
