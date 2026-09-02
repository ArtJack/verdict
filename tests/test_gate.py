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
    # Decode as UTF-8 explicitly. `text=True` alone decodes with the locale
    # encoding — cp1252 on Windows — while gate.py deliberately reconfigures
    # its stdout to UTF-8, so every non-ASCII character it writes came back as
    # mojibake and only on the Windows legs. Latent until an assertion finally
    # read one: the `Δ` column header of the PR comment's findings table.
    proc = subprocess.run(
        [sys.executable, str(GATE), *args],
        capture_output=True, text=True, encoding="utf-8", cwd=cwd, env=env,
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


# --- --max-commits-behind: a verdict ages in commits, not only in hours -------
#
# The banner only misleads a reader; this gate merges code. A `pass` measured
# against a commit the branch has moved past is a false green at the most
# expensive moment there is. Opt-in, like the other two staleness flags.

def _drift_repo(tmp_path):
    """A repo with three commits, and a QA home whose profile points at it."""
    r = tmp_path / "proj"
    r.mkdir()

    def g(*a):
        return subprocess.run(["git", "-C", str(r), *a],
                              capture_output=True, text=True, check=True).stdout.strip()

    g("init", "-q", "-b", "main")
    g("config", "user.email", "t@e.com")
    g("config", "user.name", "t")
    shas = []
    for i in range(3):
        (r / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        g("add", "-A")
        g("commit", "-qm", f"c{i}")
        shas.append(g("rev-parse", "HEAD"))
    return r, shas, g


def _drift_home(tmp_path, repo, sha, **overrides):
    home = make_home(tmp_path, **{**PASSABLE, **overrides})
    root = home / "pricer"
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    state["last_run"] = {**state.get("last_run", {}), "git_sha": sha}
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (root / "profile.md").write_text(f"**Repo-Path:** `{repo}`\n", encoding="utf-8")
    return home


def test_drift_within_limit_passes(tmp_path):
    r, shas, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, shas[1])          # one commit behind
    proc = gate(tmp_path, "pricer", "--max-commits-behind", "1", home=home)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_drift_beyond_limit_is_stale(tmp_path):
    r, shas, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, shas[0])          # two commits behind
    proc = gate(tmp_path, "pricer", "--max-commits-behind", "1", home=home)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "measured 2 commits ago" in proc.stdout


def test_diverged_state_never_gates_a_merge(tmp_path):
    r, shas, g = _drift_repo(tmp_path)
    g("checkout", "-q", "-b", "side", shas[0])
    (r / "elsewhere.txt").write_text("content main never had", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "side")
    home = _drift_home(tmp_path, r, shas[-1])         # main's tip, not on side
    proc = gate(tmp_path, "pricer", "--max-commits-behind", "99", home=home)
    assert proc.returncode == 5, proc.stdout + proc.stderr
    assert "not in this branch's history" in proc.stdout


def test_squash_merged_state_still_gates(tmp_path):
    """The whole point of the F-10 fix, at the gate rather than the banner."""
    r, shas, g = _drift_repo(tmp_path)
    g("checkout", "-q", "-b", "feat")
    (r / "work.txt").write_text("w", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "work")
    feat = g("rev-parse", "HEAD")
    g("checkout", "-q", "main")
    subprocess.run(["git", "-C", str(r), "merge", "-q", "--squash", "feat"],
                   capture_output=True, text=True)
    g("commit", "-qm", "squashed (#1)")
    home = _drift_home(tmp_path, r, feat)
    proc = gate(tmp_path, "pricer", "--max-commits-behind", "0", home=home)
    assert proc.returncode == 0, "a squash merge must not read as drift\n" + proc.stdout


def test_unmeasurable_drift_does_not_fail_the_gate(tmp_path):
    """A gate that fails on a shallow clone is a gate people route around."""
    home = _drift_home(tmp_path, tmp_path / "no-such-repo", "deadbeef" * 5)
    proc = gate(tmp_path, "pricer", "--max-commits-behind", "0", home=home)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_flag_absent_means_no_drift_check(tmp_path):
    """Backward compatibility: existing pipelines must not start failing."""
    r, shas, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, shas[0])          # two behind, unchecked
    proc = gate(tmp_path, "pricer", home=home)
    assert proc.returncode == 0, proc.stdout + proc.stderr


# --- staleness is reported even when it is not gated -------------------------
#
# Found on this repository's own PR comment. `code_drift` was computed only
# inside the `--max-commits-behind` branch, so a gate run without the flag —
# which is how the Action invokes it — could not say the verdict described a
# different commit. The comment advertised three long-fixed Majors as `NEW ·
# 0d` while the SessionStart banner, computing the same drift unconditionally,
# said plainly that the code had moved. Reporting welded to enforcing goes
# silent the moment enforcing is off.

def test_drift_is_reported_without_the_gating_flag(tmp_path):
    r, shas, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, shas[0])          # two commits behind
    proc = gate(tmp_path, "pricer", home=home)
    assert proc.returncode == 0, "reporting drift must not start failing the gate"
    assert "measured 2 commits ago" in proc.stdout


def test_a_diverged_verdict_says_so_in_the_pr_comment(tmp_path):
    """The surface an outside reader sees, and the one that ran without the
    flag. The warning sits above the findings table, because every row under it
    has to be read differently once you know it was measured elsewhere."""
    r, shas, g = _drift_repo(tmp_path)
    g("checkout", "-q", "-b", "side", shas[0])
    (r / "elsewhere.txt").write_text("content main never had", encoding="utf-8")
    g("add", "-A")
    g("commit", "-qm", "side")
    home = _drift_home(tmp_path, r, shas[-1])
    proc = gate(tmp_path, "pricer", "--format", "github-comment", home=home)
    assert proc.returncode == 0
    assert "[!WARNING]" in proc.stdout
    assert "not in this branch's history" in proc.stdout
    body = proc.stdout
    assert body.index("[!WARNING]") < body.index("| Δ |"), \
        "a note under the table arrives after the reader has believed it"


def test_a_current_verdict_carries_no_stale_note(tmp_path):
    """The false positive that would train readers to skim the line."""
    r, shas, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, shas[-1])
    for fmt in ([], ["--format", "github-comment"]):
        proc = gate(tmp_path, "pricer", *fmt, home=home)
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "Stale" not in proc.stdout and "measured " not in proc.stdout, fmt


def test_unmeasurable_drift_is_recorded_but_never_announced(tmp_path):
    """`unknown` covers a shallow clone, a missing repo and an unrecognised sha.
    It is *recorded*, so a JSON consumer can tell "we looked and could not tell"
    from "we never looked" — and never *rendered*, because a staleness note
    nobody can act on costs the real one its credibility.

    Written this way after a mutation survived the first version: the renderers
    already stay quiet on `unknown`, so a test that only read them could not
    fail. Asserting on the recorded value is what makes the rule testable."""
    home = _drift_home(tmp_path, tmp_path / "nonexistent-repo", "0" * 40)
    proc = gate(tmp_path, "pricer", home=home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "Stale" not in proc.stdout and "describes different code" not in proc.stdout

    proc = gate(tmp_path, "pricer", "--format", "json", home=home)
    assert json.loads(proc.stdout)["code_drift"]["status"] == "unknown"


def test_drift_note_says_only_what_is_actionable():
    """The decision itself, unit-tested, because reading it through a renderer
    could not fail: the text format has no `Stale:` prefix to assert on, so a
    note wrongly produced for `unknown` slipped past a CLI-only test twice.
    Test the helper directly when the contract lives in the helper."""
    sys.path.insert(0, str(GATE.parent))
    from gate import _drift_note

    assert _drift_note({"code_drift": {"status": "current"}}) is None
    assert _drift_note({"code_drift": {"status": "unknown"}}) is None
    assert _drift_note({}) is None, "a run that never measured says nothing"

    diverged = _drift_note({"code_drift": {"status": "diverged"}})
    assert "not in this branch's history" in diverged

    assert "1 commit ago" in _drift_note({"code_drift": {"status": "behind", "commits": 1}})
    assert "4 commits ago" in _drift_note({"code_drift": {"status": "behind", "commits": 4}})
    assert _drift_note({"code_drift": {"status": "behind", "commits": 0}}) is None, \
        "behind by nothing is current, not stale"
    assert "does not contain" in _drift_note({"code_drift": {"status": "absent"}})


def test_the_gating_flag_still_gates(tmp_path):
    """Reporting was separated from enforcing; enforcing must be unchanged."""
    r, shas, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, shas[0])
    assert gate(tmp_path, "pricer", "--max-commits-behind", "1", home=home).returncode == 5
    assert gate(tmp_path, "pricer", "--max-commits-behind", "9", home=home).returncode == 0


def test_an_absent_commit_is_reported_and_gated_like_divergence(tmp_path):
    """VERDICT-F-18: a complete clone that lacks the recorded commit used to
    read as `unknown` and go unmentioned. It is reported in text and in the
    comment, and under --max-commits-behind it is stale, like divergence."""
    r, _, _ = _drift_repo(tmp_path)
    home = _drift_home(tmp_path, r, "0" * 40)
    proc = gate(tmp_path, "pricer", home=home)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "does not contain" in proc.stdout
    proc = gate(tmp_path, "pricer", "--format", "github-comment", home=home)
    assert "[!WARNING]" in proc.stdout and "does not contain" in proc.stdout
    proc = gate(tmp_path, "pricer", "--max-commits-behind", "99", home=home)
    assert proc.returncode == 5, proc.stdout
    assert "does not contain the commit at all" in proc.stdout
