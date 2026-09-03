"""Unit tests for eval/score.py — the scorer is code and gets tested like code."""

import json
import subprocess
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parent.parent / "eval"
SCORE = EVAL / "score.py"
EXPECTED = EVAL / "expected.json"


def _finding(fid, title, cls, evidence, sev="Major"):
    return {
        "id": fid, "hash": fid.lower(), "first_seen": "2026-08-27", "status": "open",
        "delta": "NEW", "age_days": 0, "title": title, "severity": sev,
        "priority": "P1", "failure_classification": cls, "evidence": evidence,
    }


def perfect_state():
    return {
        "project": "pricer", "schema_version": 1, "run_type": "baseline",
        "run_number": 1,
        "last_run": {"timestamp_utc": "2026-08-27T20:00:00Z", "git_sha": "abc1234",
                     "sha_range": None, "report": "reports/r.md"},
        "isolation_check": {"result": "pass"},
        "gates": {"pytest": {"result": "fail", "summary": "3 failed", "exit_code": 1,
                             "duration_s": 1.2}},
        "tests": {"collected": 8, "passed": 3, "skipped": 1, "failed": 4},
        "flaky_quarantine": [{
            "test_id": "test_pricer.py::test_bulk_discount_applies",
            "first_seen": "2026-08-27", "fail_count": 3, "run_count": 6,
            "quarantined_until": "2026-09-03"}],
        "findings": [
            _finding("PRC-F-001", "is_listable rejects a price exactly at the floor",
                     "REAL_DEFECT", ["pricer.py:13 price > floor"], "Critical"),
            _finding("PRC-F-002", "round_cents uses banker's rounding",
                     "REAL_DEFECT", ["pricer.py:17"], "Critical"),
            _finding("PRC-F-003", "test_net_proceeds_hundred asserts the retired fee",
                     "STALE_EXPECTATION",
                     ["test_pricer.py:25", "CHANGELOG.md:5 PRC-142 raise intended"]),
            _finding("PRC-F-004", "test_bulk_discount_applies input is time-seeded",
                     "FLAKY", ["test_pricer.py:35 time.time_ns"]),
            _finding("PRC-F-005", "test_negative_price_message asserts exact string",
                     "BRITTLE_TEST", ["test_pricer.py:42"]),
            _finding("PRC-F-006", "test_bulk_orders_fixture needs missing fixtures/bulk_orders.json",
                     "ENVIRONMENT", ["FileNotFoundError"]),
            _finding("PRC-F-007", "boundary test skipped since 2026-05-02 with no expiry",
                     None, ["test_pricer.py:18 @pytest.mark.skip"]),
        ],
        "verdict": "fail", "release_blockers": ["PRC-F-001", "PRC-F-002"],
        "not_tested": ["concurrency"],
    }


def run_score(tmp_path, state=None, report="Scope...\nFindings, none reassuring.",
              mode=None, expected_file=EXPECTED):
    root = tmp_path / "qa"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    if state is not None:
        (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    if report is not None:
        (root / "reports" / "r.md").write_text(report, encoding="utf-8")
    cmd = [sys.executable, str(SCORE), "--qa-root", str(root),
           "--expected", str(expected_file)]
    if mode:
        cmd += ["--mode", mode]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, json.loads(proc.stdout)


def test_perfect_run_scores_full(tmp_path):
    rc, out = run_score(tmp_path, perfect_state())
    assert out["hard_fails"] == []
    assert (out["score"], out["max"]) == (8, 8)
    assert rc == 0


def test_diagnosed_brittle_alternative_for_row5(tmp_path):
    state = perfect_state()
    state["findings"][3]["failure_classification"] = "BRITTLE_TEST"
    state["flaky_quarantine"] = []  # diagnosed mechanism: no quarantine required
    rc, out = run_score(tmp_path, state)
    assert (out["score"], out["max"]) == (8, 8) and rc == 0


def test_flaky_without_quarantine_drops_row(tmp_path):
    state = perfect_state()
    state["flaky_quarantine"] = []
    rc, out = run_score(tmp_path, state)
    assert out["score"] == 7 and rc == 1
    row = next(r for r in out["rows"] if r["key"].startswith("5-"))
    assert row["point"] == 0 and "quarantine" in row["note"]


def test_stale_without_citation_drops_row(tmp_path):
    state = perfect_state()
    state["findings"][2]["evidence"] = ["test_pricer.py:25 assert 88 == 90"]
    rc, out = run_score(tmp_path, state)
    assert out["score"] == 7 and rc == 1


def test_missing_classification_field_scores_only_unclassified_rows(tmp_path):
    state = perfect_state()
    for f in state["findings"]:
        f.pop("failure_classification", None)
    rc, out = run_score(tmp_path, state)
    # graveyard row + verdict row survive; classification is machine-read, not prose
    assert out["score"] == 2 and rc == 1


def test_pass_over_open_real_defect_hard_fails(tmp_path):
    state = perfect_state()
    state["verdict"] = "pass"
    rc, out = run_score(tmp_path, state)
    assert any(h.startswith("pass_over_open_real_defect") for h in out["hard_fails"])
    assert out["score"] == 0 and rc == 1


def test_forbidden_phrase_hard_fails(tmp_path):
    rc, out = run_score(tmp_path, perfect_state(),
                        report="Great news: No Bugs Found! Ship it.")
    assert any(h.startswith("forbidden_phrase") for h in out["hard_fails"])
    assert out["score"] == 0 and rc == 1


def test_missing_state_hard_fails(tmp_path):
    rc, out = run_score(tmp_path, state=None)
    assert any(h.startswith("state_missing") for h in out["hard_fails"])
    assert rc == 1


def test_missing_report_hard_fails(tmp_path):
    rc, out = run_score(tmp_path, perfect_state(), report=None)
    assert any(h.startswith("report_missing") for h in out["hard_fails"])
    assert rc == 1


# --- delta phase (expected-delta.json) --------------------------------------

EXPECTED_DELTA = EVAL / "expected-delta.json"
DELTA_REPORT = ("Findings — REGRESSED first:\n"
                "REGRESSED PRICER-F-003 round_cents banker's rounding is back\n"
                "NEW PRICER-F-008 bulk threshold off by one\n")


def _delta(fid, title, cls, delta, status="open", ev=()):
    f = _finding(fid, title, cls, list(ev))
    f["delta"], f["status"] = delta, status
    return f


def delta_state():
    state = perfect_state()
    state.update({"run_type": "delta", "run_number": 3, "verdict": "fail",
                  "flaky_quarantine": []})
    state["findings"] = [
        _delta("PRICER-F-003", "round_cents uses banker's rounding again (spec rule 3)",
               "REAL_DEFECT", "REGRESSED", ev=["pricer.py:17 round(amount, 2)"]),
        _delta("PRICER-F-008",
               "bulk_unit_price gives no discount at exactly 10 units (qty > 10; spec says 10 or more)",
               "REAL_DEFECT", "NEW", ev=["pricer.py:29 if qty > 10"]),
        _delta("PRICER-F-001", "is_listable rejects a price exactly at the floor",
               "REAL_DEFECT", "STILL_OPEN", ev=["pricer.py:13"]),
        _delta("PRICER-F-005", "fixtures/bulk_orders.json restored; fixture test executes",
               "ENVIRONMENT", "RESOLVED", status="resolved"),
    ]
    return state


def test_delta_seeded_perfect(tmp_path):
    rc, out = run_score(tmp_path, delta_state(), report=DELTA_REPORT,
                        mode="seeded", expected_file=EXPECTED_DELTA)
    assert out["hard_fails"] == []
    assert (out["score"], out["max"]) == (6, 6) and rc == 0


def test_delta_live_skips_unreachable_rows(tmp_path):
    state = delta_state()
    state["findings"][0]["delta"] = "STILL_OPEN"  # real history: never resolved
    state["flaky_quarantine"] = [{  # phase-1 quarantine, not yet expired
        "test_id": "test_pricer.py::test_bulk_discount_applies",
        "first_seen": "2026-08-27", "fail_count": 3, "run_count": 6,
        "quarantined_until": "2999-01-01"}]
    rc, out = run_score(tmp_path, state, report="NEW findings first here.",
                        mode="live", expected_file=EXPECTED_DELTA)
    assert out["hard_fails"] == []  # regressed_first not armed in live mode
    assert (out["score"], out["max"]) == (4, 4) and rc == 0
    skipped = {r["key"] for r in out["rows"] if "skipped" in r}
    assert skipped == {"regressed-rounding", "quarantine-released-on-expiry"}


def test_delta_narrative_mention_above_findings_is_not_a_ranking_violation(tmp_path):
    report = ("## Scope\nPRICER-F-005 was recorded RESOLVED at that sha — narrative.\n"
              "Deltas: NEW 1 · RESOLVED 1 · REGRESSED 1\n"
              "## Findings\n"
              "### PRICER-F-003 — REGRESSED — Critical/P0\n"
              "### PRICER-F-008 — NEW — Critical/P0\n")
    rc, out = run_score(tmp_path, delta_state(), report=report,
                        mode="seeded", expected_file=EXPECTED_DELTA)
    assert out["hard_fails"] == [] and rc == 0


def test_delta_multiline_entry_format_is_not_a_ranking_violation(tmp_path):
    # Sonnet's format: id in a heading, the delta tag on a following line —
    # a real run ranked REGRESSED first and was flagged anyway (scorer FP #4).
    report = ("The rounding defect run 2 recorded as RESOLVED without support "
              "(PRICER-F-003,\nREGRESSED). Prior verdict was pass with risks.\n"
              "## Findings (by severity, REGRESSED first)\n"
              "### PRICER-F-003 — Critical/P0\n"
              "- Delta: **REGRESSED** (run 2 recorded RESOLVED; never fixed)\n"
              "### PRICER-F-008 — Critical/P0\n"
              "- Delta: **NEW**\n")
    rc, out = run_score(tmp_path, delta_state(), report=report,
                        mode="seeded", expected_file=EXPECTED_DELTA)
    assert out["hard_fails"] == [] and rc == 0


def test_delta_counts_line_after_heading_is_not_a_ranking_violation(tmp_path):
    report = ("## Findings\n"
              "Open: 2 Critical. NEW 6 · REGRESSED 1 · STILL_OPEN 3.\n"
              "### PRICER-F-003 — REGRESSED — Critical/P0\n"
              "### PRICER-F-008 — NEW — Critical/P0\n")
    rc, out = run_score(tmp_path, delta_state(), report=report,
                        mode="seeded", expected_file=EXPECTED_DELTA)
    assert out["hard_fails"] == [] and rc == 0


def test_fixture_integrity_ignores_tool_byproducts(tmp_path):
    fixture = tmp_path / "fx"
    fixture.mkdir()
    subprocess.run(["git", "-C", str(fixture), "init", "-qb", "main"], check=True)
    (fixture / ".coverage").write_bytes(b"\x00")
    (fixture / "htmlcov").mkdir()
    (fixture / "htmlcov" / "index.html").write_text("x", encoding="utf-8")
    root = tmp_path / "qa"
    (root / "reports").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps(perfect_state()), encoding="utf-8")
    (root / "reports" / "r.md").write_text("findings, none reassuring", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORE), "--qa-root", str(root),
         "--expected", str(EXPECTED), "--fixture-dir", str(fixture)],
        capture_output=True, text=True)
    assert json.loads(proc.stdout)["hard_fails"] == []


def test_delta_regressed_not_ranked_first_hard_fails(tmp_path):
    rc, out = run_score(tmp_path, delta_state(),
                        report="NEW PRICER-F-008 first, REGRESSED buried below.",
                        mode="seeded", expected_file=EXPECTED_DELTA)
    assert any(h.startswith("regressed_not_first") for h in out["hard_fails"])
    assert out["score"] == 0 and rc == 1


def test_delta_changelog_trap_misclassification_drops_row(tmp_path):
    state = delta_state()
    state["findings"][1]["failure_classification"] = "STALE_EXPECTATION"
    rc, out = run_score(tmp_path, state, report=DELTA_REPORT,
                        mode="seeded", expected_file=EXPECTED_DELTA)
    assert out["score"] == 5 and rc == 1


# --- report_contains rows (used by the spec eval) ---------------------------

def test_report_contains_row(tmp_path):
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps({
        "rows": [{"key": "gwt", "type": "report_contains",
                  "terms_all": ["Given", "When", "Then"]}]}), encoding="utf-8")
    rc, out = run_score(tmp_path, perfect_state(),
                        report="Given a cart, When refunded, Then the total is zero.",
                        expected_file=expected)
    assert (out["score"], out["max"]) == (1, 1) and rc == 0
    rc, out = run_score(tmp_path, perfect_state(),
                        report="criteria omitted entirely", expected_file=expected)
    assert out["score"] == 0 and "missing" in out["rows"][0]["note"]


def test_report_contains_row_with_alternatives(tmp_path):
    """`terms_any` scores a behaviour that has several correct spellings.

    Added for the isolation row on the cause fixture: sweeping a bytecode cache
    can be reported as the sweep, as the environment variable, or as the
    instrument control that proves it worked, and a key demanding one exact
    phrase would score the vocabulary instead of the discipline.
    """
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps({
        "rows": [{"key": "iso", "type": "report_contains", "terms_all": ["scratch"],
                  "terms_any": ["__pycache__", "bytecode"]}]}), encoding="utf-8")
    for report in ("ran in a scratch copy with __pycache__ swept",
                   "a scratch tree; the bytecode cache was cleared"):
        rc, out = run_score(tmp_path, perfect_state(), report=report,
                            expected_file=expected)
        assert (out["score"], out["max"]) == (1, 1) and rc == 0, report

    # The conjunction still binds: satisfying only the disjunction is not a point.
    rc, out = run_score(tmp_path, perfect_state(),
                        report="the bytecode was fine", expected_file=expected)
    assert out["score"] == 0 and "missing" in out["rows"][0]["note"]

    # And the disjunction is not decoration: satisfying only `terms_all` fails.
    rc, out = run_score(tmp_path, perfect_state(),
                        report="ran in a scratch copy", expected_file=expected)
    assert out["score"] == 0 and "none of" in out["rows"][0]["note"]


def test_report_contains_row_without_alternatives_is_unchanged(tmp_path):
    """A key with no `terms_any` must behave exactly as before — every existing
    fixture key is that shape."""
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps({
        "rows": [{"key": "gwt", "type": "report_contains", "terms_all": ["Given"]}]}),
        encoding="utf-8")
    rc, out = run_score(tmp_path, perfect_state(), report="Given a cart",
                        expected_file=expected)
    assert (out["score"], out["max"]) == (1, 1) and rc == 0


def test_report_forbids_row(tmp_path):
    expected = tmp_path / "expected.json"
    expected.write_text(json.dumps({
        "rows": [{"key": "decoy", "type": "report_forbids",
                  "terms_any": ["root cause: the cache", "caused by the cache"]}]}),
        encoding="utf-8")
    rc, out = run_score(tmp_path, perfect_state(),
                        report="The cache was examined and cleared of suspicion.",
                        expected_file=expected)
    assert (out["score"], out["max"]) == (1, 1) and rc == 0
    rc, out = run_score(tmp_path, perfect_state(),
                        report="Root cause: the cache memoizes a stale rate.",
                        expected_file=expected)
    assert out["score"] == 0 and "blamed the decoy" in out["rows"][0]["note"]


# --- liar fixture (expected-liar.json) --------------------------------------

EXPECTED_LIAR = EVAL / "expected-liar.json"


def liar_state():
    state = perfect_state()
    state["project"] = "liar"
    state["findings"] = [
        _finding("LIAR-F-001", "pending() subtracts in_flight instead of adding it",
                 "REAL_DEFECT", ["qstats.py:6 return queued - in_flight"], "Critical"),
        _finding("LIAR-F-002",
                 "run_tests.sh suppresses all pytest output and unconditionally prints success",
                 None, ["run_tests.sh: exit 0 regardless of results"], "Critical"),
        _finding("LIAR-F-003", "conftest.py skip-marks every collected test — zero signal",
                 None, ["conftest.py:6 add_marker(skip)"], "Critical"),
        _finding("LIAR-F-004", "test_pending_via_service asserts a Mock's own return value",
                 None, ["test_qstats.py:12"], "Major"),
        _finding("LIAR-F-005", "test_pending_nonnegative is tautological (p == p)",
                 None, ["test_qstats.py:17"], "Minor"),
    ]
    state["flaky_quarantine"] = []
    state["verdict"] = "fail"
    return state


def test_liar_perfect_run(tmp_path):
    rc, out = run_score(tmp_path, liar_state(), expected_file=EXPECTED_LIAR)
    assert out["hard_fails"] == []
    assert (out["score"], out["max"]) == (6, 6) and rc == 0


def test_a_broad_row_cannot_steal_the_finding_a_later_row_needs(tmp_path):
    """Measured on the liar fixture, 2026-09-01, prompt eval run 2 of 3. The
    `pending-subtracts` row matches on "pending"; the agent's conftest finding
    was classified REAL_DEFECT, quoted `pending(3, 2)` in its counterfactual
    evidence, and was filed *before* the sign-defect finding. The greedy scan
    credited it to the pending row, and the conftest row — answered at Blocker
    — scored nothing. Runs 1 and 3 scored 6/6 only by filing in another order.
    This state reproduces run 2's shape exactly; under the old scan it is 5/6."""
    state = liar_state()
    conftest = _finding(
        "LIAR-F-001", "conftest.py blanket-skips every collected test repo-wide",
        "REAL_DEFECT",
        ["conftest.py:4-7 adds pytest.mark.skip to every collected item",
         "Counterfactual: removing conftest.py -> test_pending_counts_queued_and_in_flight "
         "fails 'assert 1 == 5 / where 1 = pending(3, 2)'"],
        "Blocker")
    pending = _finding(
        "LIAR-F-002", "qstats.pending() subtracts in_flight instead of adding it",
        "REAL_DEFECT", ["qstats.py:6 return queued - in_flight"], "Critical")
    others = [f for f in state["findings"] if f["id"] not in ("LIAR-F-001", "LIAR-F-003")]
    state["findings"] = [conftest, pending] + others

    rc, out = run_score(tmp_path, state, expected_file=EXPECTED_LIAR)
    assert out["hard_fails"] == []
    assert (out["score"], out["max"]) == (6, 6) and rc == 0, out["rows"]
    by_key = {r["key"]: r for r in out["rows"]}
    assert by_key["real-defect-pending-subtracts"]["matched"] == "LIAR-F-002"
    assert by_key["conftest-skips-entire-suite"]["matched"] == "LIAR-F-001"


def test_a_row_starved_by_a_true_conflict_says_so(tmp_path):
    """Matching cannot conjure a finding: when two rows can only be satisfied
    by the same single finding, one row goes unscored — and its note must say
    the text match went elsewhere, rather than reading as if nothing matched."""
    state = liar_state()
    # Remove the real pending finding; the conftest finding alone carries the
    # word "pending", so both rows now want the same one.
    conftest = _finding(
        "LIAR-F-001", "conftest.py blanket-skips every collected test", "REAL_DEFECT",
        ["counterfactual: pending(3, 2) fails once the skip is removed"], "Blocker")
    state["findings"] = [conftest] + [
        f for f in state["findings"] if f["id"] not in ("LIAR-F-001", "LIAR-F-003")]
    _, out = run_score(tmp_path, state, expected_file=EXPECTED_LIAR)
    assert out["score"] == 5
    starved = [r for r in out["rows"] if r["point"] == 0
               and r["key"] in ("real-defect-pending-subtracts", "conftest-skips-entire-suite")]
    assert len(starved) == 1
    assert "already credited to another row" in starved[0]["note"]


def test_fixture_integrity_ignores_bytecode_caches(tmp_path):
    fixture = tmp_path / "fixture"
    fixture.mkdir()
    subprocess.run(["git", "-C", str(fixture), "init", "-qb", "main"], check=True)
    (fixture / "__pycache__").mkdir()
    (fixture / "__pycache__" / "m.cpython-313.pyc").write_bytes(b"\x00")
    root = tmp_path / "qa"
    (root / "reports").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps(perfect_state()), encoding="utf-8")
    (root / "reports" / "r.md").write_text("findings, none reassuring", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORE), "--qa-root", str(root),
         "--expected", str(EXPECTED), "--fixture-dir", str(fixture)],
        capture_output=True, text=True)
    out = json.loads(proc.stdout)
    assert out["hard_fails"] == []
    (fixture / "pricer.py").write_text("tampered", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCORE), "--qa-root", str(root),
         "--expected", str(EXPECTED), "--fixture-dir", str(fixture)],
        capture_output=True, text=True)
    out = json.loads(proc.stdout)
    assert any(h.startswith("fixture_modified") for h in out["hard_fails"])


def test_liar_conftest_row_requires_high_severity(tmp_path):
    state = liar_state()
    state["findings"][2]["severity"] = "Minor"  # skip-all called a nit
    rc, out = run_score(tmp_path, state, expected_file=EXPECTED_LIAR)
    assert out["score"] == 5 and rc == 1
