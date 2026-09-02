"""Tests for verdict-validate — the state contract as a machine gate.

Each violation case mirrors something a real run actually did.
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from verdict_mcp.validate import validate

VALIDATE = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "validate.py"


def now_z(delta=timedelta()):
    return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "r.md").write_text("# report", encoding="utf-8")
    return tmp_path


def good_state(**overrides):
    state = {
        "project": "pricer", "schema_version": 1, "run_type": "delta", "run_number": 4,
        "last_run": {"timestamp_utc": now_z(), "git_sha": "abc1234",
                     "sha_range": "aaa..abc", "report": "reports/r.md"},
        "isolation_check": {"result": "pass"},
        "gates": {}, "tests": {"collected": 8},
        "flaky_quarantine": [{"test_id": "t::x", "quarantined_until": "2026-09-09"}],
        "findings": [{
            "id": "PRC-F-1", "hash": "a1b2", "first_seen": "2026-08-20", "status": "open",
            "delta": "STILL_OPEN", "age_days": 4, "title": "floor boundary",
            "severity": "Major", "priority": "P1",
            "failure_classification": "REAL_DEFECT", "evidence": ["pricer.py:13"]}],
        "verdict": "pass with risks", "release_blockers": [], "not_tested": ["concurrency"],
    }
    state.update(overrides)
    return state


def test_good_state_passes(root):
    assert validate(good_state(), root) == []


def test_report_must_name_an_existing_file(root):
    # The exact dodge a production run used three times.
    state = good_state()
    state["last_run"]["report"] = "inline to caller (no report file written per caller instruction)"
    bad = validate(state, root)
    assert any("not a path to a .md file" in b for b in bad)

    state["last_run"]["report"] = "reports/never-written.md"
    assert any("does not exist" in b for b in validate(state, root))


def test_run_number_must_advance(root):
    previous = good_state(run_number=4)
    assert any("did not advance" in b for b in validate(good_state(run_number=4), root, previous))
    assert any("did not advance" in b for b in validate(good_state(run_number=3), root, previous))
    assert validate(good_state(run_number=5), root, previous) == []


def test_timestamp_must_be_measured_not_recalled(root):
    state = good_state()
    state["last_run"]["timestamp_utc"] = "2026-08-25T00:00:00Z"  # the real fabricated one
    assert any("over a day old" in b for b in validate(state, root))

    state["last_run"]["timestamp_utc"] = now_z(timedelta(hours=3))
    assert any("in the future" in b for b in validate(state, root))

    state["last_run"]["timestamp_utc"] = "2026-08-25 00:00"
    assert any("not ISO-8601" in b for b in validate(state, root))

    # clock skew inside tolerance is fine
    state["last_run"]["timestamp_utc"] = now_z(timedelta(minutes=-90))
    assert validate(state, root) == []


def test_pass_cannot_stand_over_an_open_critical(root):
    state = good_state(verdict="pass")
    state["findings"][0]["severity"] = "Critical"
    assert any("`pass` with open Critical" in b for b in validate(state, root))
    # the same finding resolved is no longer blocking
    state["findings"][0]["status"] = "resolved"
    assert validate(state, root) == []


def test_findings_need_identity_enums_and_evidence(root):
    state = good_state()
    state["findings"][0]["hash"] = ""
    state["findings"][0]["severity"] = "Nasty"
    state["findings"][0]["delta"] = "MAYBE"
    state["findings"][0]["evidence"] = []
    bad = "\n".join(validate(state, root))
    assert "has no hash" in bad and "severity 'Nasty'" in bad
    assert "delta 'MAYBE'" in bad and "open with no evidence" in bad


def test_duplicate_finding_ids_rejected(root):
    state = good_state()
    state["findings"].append(dict(state["findings"][0]))
    assert any("repeats id" in b for b in validate(state, root))


def test_quarantine_without_expiry_rejected(root):
    state = good_state(flaky_quarantine=[{"test_id": "t::y"}])
    assert any("has no expiry" in b for b in validate(state, root))


def test_missing_required_fields_and_bad_enums(root):
    state = good_state()
    del state["not_tested"]
    state["verdict"] = "looks fine"
    state["run_type"] = "audit"
    bad = "\n".join(validate(state, root))
    assert "missing required field: not_tested" in bad
    assert "verdict 'looks fine'" in bad and "run_type 'audit'" in bad


# --- CLI and hook surfaces --------------------------------------------------

def run_cli(*args, stdin=None):
    return subprocess.run([sys.executable, str(VALIDATE), *args],
                          input=stdin, capture_output=True, text=True)


def test_cli_exit_codes(root):
    (root / "state.json").write_text(json.dumps(good_state()), encoding="utf-8")
    assert run_cli(str(root / "state.json")).returncode == 0

    (root / "bad.json").write_text(json.dumps(good_state(verdict="nope")), encoding="utf-8")
    proc = run_cli(str(root / "bad.json"))
    assert proc.returncode == 1
    # Not merely "violation" somewhere in stderr: a crash inside this very
    # print prints the offending source line, which contains the word, and the
    # assertion could not tell a working message from a traceback.
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stderr.startswith("verdict-validate: 1 violation(s):"), proc.stderr
    assert "verdict 'nope'" in proc.stderr

    assert run_cli(str(root / "missing.json")).returncode == 2


def test_cli_quiet_says_nothing_when_the_state_is_good(root):
    (root / "state.json").write_text(json.dumps(good_state()), encoding="utf-8")
    loud = run_cli(str(root / "state.json"))
    quiet = run_cli(str(root / "state.json"), "--quiet")
    assert loud.returncode == quiet.returncode == 0
    assert "satisfies the state contract" in loud.stdout
    assert quiet.stdout.strip() == "", quiet.stdout


def test_cli_reads_the_previous_state_and_reports_its_own_errors(root, tmp_path):
    """`--previous` enables the run-number-advanced check. An unreadable one is
    a usage error about *that* file, not a silent fallback to no comparison."""
    (root / "state.json").write_text(json.dumps(good_state(run_number=4)), encoding="utf-8")
    prev = tmp_path / "prev.json"
    prev.write_text(json.dumps(good_state(run_number=9)), encoding="utf-8")
    stale = run_cli(str(root / "state.json"), "--previous", str(prev))
    assert stale.returncode == 1, stale.stderr
    assert "run_number" in stale.stderr

    missing = run_cli(str(root / "state.json"), "--previous", str(tmp_path / "nope.json"))
    assert missing.returncode == 2, missing.stderr
    assert "--previous" in missing.stderr

    prev.write_text(json.dumps(good_state(run_number=3)), encoding="utf-8")
    ok = run_cli(str(root / "state.json"), "--previous", str(prev))
    assert ok.returncode == 0, ok.stderr


def test_hook_blocks_a_bad_write_and_ignores_other_files(root):
    state_path = root / "state.json"
    state_path.write_text(json.dumps(good_state(verdict="pass", findings=[{
        "id": "X-1", "hash": "h", "status": "open", "severity": "Critical",
        "priority": "P0", "evidence": ["a.py:1"]}])), encoding="utf-8")
    hook_in = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(state_path)}})
    proc = run_cli(stdin=hook_in)
    assert proc.returncode == 2
    assert "open Critical" in proc.stderr

    # a write to anything else is none of its business
    other = json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(root / "notes.md")}})
    assert run_cli(stdin=other).returncode == 0

    # malformed hook input fails open — a broken hook must not brick a session
    assert run_cli(stdin="not json").returncode == 0


def test_hook_uses_previous_state_when_present(root):
    state_path = root / "state.json"
    state_path.write_text(json.dumps(good_state(run_number=4)), encoding="utf-8")
    (root / "state.json.prev").write_text(json.dumps(good_state(run_number=4)), encoding="utf-8")
    proc = run_cli(stdin=json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": str(state_path)}}))
    assert proc.returncode == 2 and "did not advance" in proc.stderr


# ── the calibration contract (v0.20.0) ────────────────────────────────────

def test_a_newly_filed_finding_must_state_its_confidence(root):
    """Demanded at filing or not at all: a confidence supplied after the outcome
    is known measures hindsight, not judgment."""
    new = dict(good_state()["findings"][0], delta="NEW", first_seen="2026-08-24")
    new.pop("confidence", None)
    bad = validate(good_state(findings=[new]), root)
    assert any("NEW without `confidence`" in b for b in bad)
    assert validate(good_state(findings=[dict(new, confidence="probable")]), root) == []


def test_findings_inherited_from_older_runs_stay_legal_without_one(root):
    """Runs that predate the rule must keep validating — a contract that
    retroactively invalidates its own history is a rewrite, not a contract."""
    old = dict(good_state()["findings"][0], delta="STILL_OPEN")
    old.pop("confidence", None)
    assert validate(good_state(findings=[old]), root) == []


def test_invented_confidence_and_outcome_values_are_rejected(root):
    f = good_state()["findings"][0]
    assert any("confidence 'very sure'" in b
               for b in validate(good_state(findings=[dict(f, confidence="very sure")]), root))
    assert any("outcome 'probably real'" in b
               for b in validate(good_state(findings=[dict(f, outcome="probably real")]), root))


def test_fix_verified_must_be_a_boolean_and_must_cite_the_guard(root):
    f = dict(good_state()["findings"][0], status="resolved", delta="RESOLVED")
    assert any("must be true or false" in b
               for b in validate(good_state(findings=[dict(f, fix_verified="yes")]), root))
    no_evidence = dict(f, fix_verified=True, evidence=[])
    assert any("no evidence" in b for b in validate(good_state(findings=[no_evidence]), root))
    assert validate(good_state(findings=[dict(f, fix_verified=True)]), root) == []


def test_an_uppercase_status_is_still_an_open_finding(root):
    """The live bug: "OPEN" made an open Critical invisible to every check that
    switched on this field, including the pass-over-Critical rule."""
    critical = dict(good_state()["findings"][0], status="OPEN", severity="Critical")
    bad = validate(good_state(verdict="pass", findings=[critical]), root)
    assert any("open Critical" in b for b in bad)


def test_two_findings_may_not_share_one_hash(root):
    """Found in a live state: one defect filed twice under two ids, the second
    as "F-003 confirmed in production". Identity is the hash, so ageing, deltas
    and the outcome ledger collapsed them onto whichever was written last."""
    f = good_state()["findings"][0]
    twice = [f, dict(f, id="PRC-F-2", title="the same thing, said again")]
    bad = validate(good_state(findings=twice), root)
    assert any("shares hash a1b2 with PRC-F-1" in b for b in bad)
    assert validate(good_state(findings=[f, dict(f, id="PRC-F-2", hash="c3d4")]), root) == []


# ── the status enum, which was declared and never enforced ────────────────

def test_a_status_outside_the_enum_is_rejected(root):
    """`STATUSES` sat in two modules, checked in neither. A one-word typo made a
    finding invisible to the blocker check, the gate and the hotspot ranking."""
    f = dict(good_state()["findings"][0], status="closed")
    bad = validate(good_state(findings=[f]), root)
    assert any("status 'closed' not in" in b for b in bad)


def test_a_finding_with_no_status_at_all_is_rejected(root):
    f = {k: v for k, v in good_state()["findings"][0].items() if k != "status"}
    assert any("has no status" in b for b in validate(good_state(findings=[f]), root))


def test_an_unrecognised_status_still_counts_as_open_for_the_pass_rule(root):
    """The exact false green: a `pass` carrying an open Critical typed
    `"closed"` validated cleanly and gated green. Reading `open` as anything not
    explicitly closed is the safe direction — an unknown status is not evidence
    a defect was fixed."""
    critical = dict(good_state()["findings"][0], status="closed", severity="Critical")
    bad = validate(good_state(verdict="pass", findings=[critical]), root)
    assert any("open Critical" in b for b in bad)


def test_resolved_and_withdrawn_findings_do_not_block_a_pass(root):
    for status in ("resolved", "withdrawn"):
        f = dict(good_state()["findings"][0], status=status, severity="Critical",
                 delta="RESOLVED" if status == "resolved" else "WITHDRAWN")
        assert validate(good_state(verdict="pass", findings=[f]), root) == [], status


# ── the judgment's own boundary ───────────────────────────────────────────

from verdict_mcp.validate import validate_judgment  # noqa: E402


def judgment(**over):
    j = {"verdict": "fail", "not_tested": ["concurrency"],
         "isolation_check": {"result": "pass"},
         "findings": [{"id": "P-F-1", "severity": "Major", "priority": "P1",
                       "status": "open", "confidence": "proven",
                       "failure_classification": "REAL_DEFECT",
                       "evidence": ["a.py:1"]}]}
    j.update(over)
    return j


def test_a_clean_judgment_passes():
    assert validate_judgment(judgment()) == []


def test_full_sweep_must_be_a_real_boolean():
    """`full_sweep` licenses silence to resolve findings wholesale, so a truthy
    string granting it by accident is exactly the failure mode to refuse."""
    assert any("full_sweep" in b for b in validate_judgment(judgment(full_sweep="yes")))
    assert validate_judgment(judgment(full_sweep=True)) == []
    assert validate_judgment(judgment(full_sweep=False)) == []


def test_a_finding_that_will_be_new_is_told_so_before_the_merge():
    """The whole point of checking here: `validate()` can only say a NEW finding
    lacks confidence *after* the merge decided it was NEW, in the vocabulary of
    a structure the agent never wrote."""
    f = {k: v for k, v in judgment()["findings"][0].items() if k != "confidence"}
    bad = validate_judgment(judgment(findings=[f]))
    assert any("will be filed as NEW — state its confidence now" in b for b in bad)

    # ...and a finding the previous state already knows needs none
    previous = {"findings": [{"id": "P-F-1", "hash": "abc", "status": "open"}]}
    assert validate_judgment(judgment(findings=[f]), previous) == []


def test_two_findings_under_one_id_are_named_as_such():
    """This is the message that used to arrive as `repeats id` from a structure
    the author did not write."""
    f = judgment()["findings"][0]
    bad = validate_judgment(judgment(findings=[f, dict(f, severity="Minor")]))
    assert any("both filed as 'P-F-1'" in b and "mint a second id" in b for b in bad)


def test_computed_fields_in_a_judgment_are_called_out():
    f = dict(judgment()["findings"][0], hash="deadbeef", age_days=3, outcome="confirmed")
    bad = validate_judgment(judgment(findings=[f]))
    assert any("verdict-finalize computes and will overwrite" in b for b in bad)
    assert any("hash" in b and "age_days" in b and "outcome" in b for b in bad)


def test_the_judgment_check_holds_the_same_lines_as_the_state_check():
    """Same rules, said earlier and in the author's own terms."""
    f = judgment()["findings"][0]
    assert any("uncited finding is a HYPOTHESIS" in b
               for b in validate_judgment(judgment(findings=[dict(f, evidence=[])])))
    assert any("open Critical/Blocker" in b for b in validate_judgment(
        judgment(verdict="pass", findings=[dict(f, severity="Critical")])))
    assert any("not one of" in b for b in validate_judgment(judgment(verdict="green")))
    assert any("not_tested must be a list" in b
               for b in validate_judgment(judgment(not_tested="nothing")))


def test_a_malformed_judgment_does_not_raise():
    assert validate_judgment("not an object") == ["judgment.json is not a JSON object"]
    assert any("findings must be a list" in b for b in validate_judgment(judgment(findings={})))


# ── at rest: a file, not a run ────────────────────────────────────────────

def test_at_rest_drops_the_freshness_rule_and_nothing_else(root):
    """A committed state is stale by tomorrow morning, by construction. Asking
    whether the team's checked-in baseline is *well-formed* is a different
    question from whether a run just happened, and this repo shipped a v0.12-era
    `.qa/` for weeks partly because nothing could ask the first one."""
    old = good_state()
    old["last_run"]["timestamp_utc"] = "2026-01-01T12:00:00Z"
    assert any("over a day old" in b for b in validate(old, root))
    assert validate(old, root, at_rest=True) == []


def test_a_future_timestamp_is_broken_at_rest_too(root):
    """Old is a property of a file. In the future is a property of a lie."""
    ahead = good_state()
    ahead["last_run"]["timestamp_utc"] = now_z(timedelta(days=2))
    assert any("in the future" in b for b in validate(ahead, root, at_rest=True))


def test_at_rest_still_enforces_every_other_rule(root):
    old = good_state(verdict="pass", findings=[
        dict(good_state()["findings"][0], severity="Critical", status="open")])
    old["last_run"]["timestamp_utc"] = "2026-01-01T12:00:00Z"
    bad = validate(old, root, at_rest=True)
    assert any("open Critical" in b for b in bad)
    assert not any("over a day old" in b for b in bad)


def test_the_cli_exposes_at_rest(root):
    state_path = root / "state.json"
    old = good_state()
    old["last_run"]["timestamp_utc"] = "2026-01-01T12:00:00Z"
    state_path.write_text(json.dumps(old), encoding="utf-8")
    assert run_cli(str(state_path)).returncode == 1
    assert run_cli(str(state_path), "--at-rest").returncode == 0


def test_prose_must_be_an_object_of_named_sections(root):
    """A bare string here crashed the renderer with a raw `AttributeError`,
    which told its author nothing about what to change — in the very check
    built to explain judgment errors in the author's own terms."""
    bad = validate_judgment(judgment(prose="I did a QA pass and it looks fine"))
    assert any("prose must be an object" in b and "AttributeError" in b for b in bad)
    assert validate_judgment(judgment(prose={"scope": "the diff", "risks": "rounding"})) == []
    assert validate_judgment(judgment()) == [], "prose is optional"


def test_prose_findings_must_map_ids_to_narratives(root):
    bad = validate_judgment(judgment(prose={"findings": ["not", "a", "map"]}))
    assert any("prose.findings must map a finding id" in b for b in bad)


def test_judgment_verified_intact_must_be_a_list_when_present():
    """Optional field, strict shape: confirmation entries carry evidence like
    findings do, and a bare string would flatten that into prose."""
    bad = validate_judgment(judgment(verified_intact="the ledger held"))
    assert any("verified_intact" in b for b in bad)
    ok = validate_judgment(judgment(
        verified_intact=["ledger invariant held: debits == credits (12 tests)"]))
    assert not any("verified_intact" in b for b in ok)
    assert not any("verified_intact" in b for b in validate_judgment(judgment())), \
        "optional means optional — absence is not an error"


# --- A clean `pass` needs measured evidence that a test executed -------------
#
# Found by running Verdict's own liar fixture through the real harness with a
# local 8B model standing in for the judgment step. The model never produced a
# false green — but a judgment that simply believed `ALL TESTS PASSED` did, and
# it reached exit 0 through `--require-harness`.

def _gate(counts=None, unparsed=True):
    g = {"command": "./run_tests.sh", "exit_code": 0, "result": "pass", "duration_s": 0.4,
         "summary": "ALL TESTS PASSED"}
    if counts:
        g["counts"], g["counts_dialect"] = counts, "pytest"
    elif unparsed:
        g["counts_unparsed"] = "no recognised runner summary"
    return g


def test_pass_cannot_stand_when_no_gate_produced_test_counts(root):
    """The liar fixture through its own entrypoint: `pytest -q >/dev/null; echo
    ALL TESTS PASSED; exit 0`. Counts are unparseable, so `executed_nothing`
    never computes, and a `pass` used to be written over a suite in which every
    collected test was skipped."""
    bad = validate(good_state(verdict="pass", gates={"tests": _gate()}), root)
    assert any("no gate in this run produced test counts" in b for b in bad)
    assert any("pass with risks" in b for b in bad), "the honest alternative is named"


def test_one_readable_gate_is_enough_and_a_lint_gate_is_not_punished(root):
    """The false positive the rule is shaped to avoid, and the exact shape of
    this repository's own state: a parsed `suite` gate beside an unparseable
    `fixture_freshness` one. Lint and freshness gates legitimately have no
    runner summary, so judging per gate would fire on every real project."""
    state = good_state(verdict="pass", gates={
        "suite": _gate(counts={"passed": 512}),
        "fixture_freshness": _gate()})
    assert validate(state, root) == []


def test_a_run_that_ran_no_gates_cannot_pass_unqualified(root):
    """VERDICT-F-17, filed by Verdict on itself: the first version of this rule
    left `gates: {}` alone, so a run that measured *nothing* got an unqualified
    `pass` while a run that measured something unreadable was refused. The
    harness now carries `no_gates` from facts, and that is what is refused —
    as the agent contract already demanded ("report that and fix the profile")."""
    state = good_state(verdict="pass", gates={},
                       no_gates="no gates ran — neither --gate nor a profile block")
    bad = validate(state, root)
    assert any("ran no gates at all" in b for b in bad)
    assert any("Fix the profile" in b for b in bad)
    # the honest verdict stays available
    assert validate(good_state(verdict="pass with risks", gates={},
                               no_gates="no gates ran"), root) == []


def test_empty_gates_without_the_fact_is_left_alone(root):
    """`gates: {}` with no `no_gates` is a state from before the fact travelled,
    or one built by hand. It is not overclaiming a suite it never mentioned,
    and refusing it would be a migration by ambush."""
    assert validate(good_state(verdict="pass", gates={}), root) == []


def test_pass_with_risks_remains_available_over_an_unreadable_suite(root):
    """The rule refuses the unqualified verdict, not the run. A tester who
    cannot read the suite can still ship a judgment — by saying so."""
    state = good_state(verdict="pass with risks", gates={"tests": _gate()})
    assert validate(state, root) == []


def test_counts_of_zero_do_not_pass_as_measurement(root):
    """`counts: {}` is what an unparsed run already means; a gate that reports
    counts must report some."""
    bad = validate(good_state(verdict="pass", gates={"tests": _gate(counts={})}), root)
    assert any("no gate in this run produced test counts" in b for b in bad)


# --- not_tested: the rule both messages promised but neither enforced --------

def test_empty_not_tested_is_refused_on_a_shipping_verdict(root):
    """Both validators said "an empty list is a claim of total coverage" while
    checking only `isinstance(value, list)`. `[]` is a list, so a `pass` with
    `not_tested: []` travelled through judgment, merge, state and gate."""
    for verdict in ("pass", "pass with risks"):
        bad = validate(good_state(verdict=verdict, not_tested=[]), root)
        assert any("claims total coverage" in b for b in bad), verdict
    bad = validate_judgment(judgment(verdict="pass", not_tested=[]))
    assert any("claims total coverage" in b for b in bad)


def test_a_failing_run_may_leave_not_tested_empty(root):
    """The run is stopping; it is not making a coverage claim worth policing."""
    for verdict in ("fail", "blocked"):
        assert validate(good_state(verdict=verdict, not_tested=[]), root) == [], verdict
    assert validate_judgment(judgment(verdict="fail", not_tested=[])) == []


def test_not_tested_must_still_be_a_list(root):
    bad = validate(good_state(not_tested="everything else"), root)
    assert any("not_tested must be a list" in b for b in bad)


# --- evidence is cited so somebody can go and look --------------------------

def test_evidence_entries_must_be_strings(root):
    """A local model returned `[{"file": "qstats.py", "line": 4}]`, which
    satisfied the presence check whose entire purpose is that a reader can
    follow the citation."""
    state = good_state()
    state["findings"][0]["evidence"] = [{"file": "pricer.py", "line": 13}]
    bad = validate(state, root)
    assert any("evidence[0] is dict, not a string" in b for b in bad)

    f = dict(judgment()["findings"][0], evidence=[{"file": "a.py", "line": 1}])
    assert any("evidence[0] is dict" in b for b in validate_judgment(judgment(findings=[f])))


def test_evidence_must_be_a_list_not_a_bare_string(root):
    state = good_state()
    state["findings"][0]["evidence"] = "pricer.py:13 the guard"
    assert any("evidence must be a list" in b for b in validate(state, root))


def test_well_formed_evidence_stays_clean(root):
    assert validate(good_state(), root) == []


# ── the judgment validator, pinned (mutation campaign, 2026-09-02) ──────────
#
# A mutation campaign over validate.py found 53 non-string mutants surviving
# the whole 639-test suite, and the shape of the gap was consistent: the rules
# in `validate` were pinned and their twins in `validate_judgment` were not.
# That is the wrong way round. `validate` guards the finished state, which the
# harness computes; `validate_judgment` guards what the *model* writes, and is
# the first place a fabricated claim is refused.

def test_judgment_fix_verified_must_be_a_boolean():
    """The twin of the state-side rule, and the one the model reaches first."""
    f = judgment()["findings"][0]
    for value in ("yes", 1, "true"):
        bad = validate_judgment(judgment(findings=[dict(f, fix_verified=value)]))
        assert any("fix_verified must be true or false" in b for b in bad), value
    assert validate_judgment(judgment(findings=[dict(f, fix_verified=True)])) == []
    assert validate_judgment(judgment(findings=[dict(f, fix_verified=False)])) == []


def test_judgment_fix_verified_must_cite_the_test_that_failed():
    f = dict(judgment()["findings"][0], status="resolved", fix_verified=True, evidence=[])
    bad = validate_judgment(judgment(findings=[f]))
    assert any("claims fix_verified with no evidence" in b for b in bad), bad
    kept = dict(f, evidence=["tests/test_x.py::test_y failed at the previous commit"])
    assert not [b for b in validate_judgment(judgment(findings=[kept]))
                if "fix_verified" in b]


def test_judgment_failure_classification_is_checked_but_optional():
    """`is not None and not in` — invert either half and a bad value passes or
    a legitimately absent one is refused."""
    f = judgment()["findings"][0]
    bad = validate_judgment(judgment(findings=[dict(f, failure_classification="MADE_UP")]))
    assert any("failure_classification" in b for b in bad), bad
    assert validate_judgment(judgment(findings=[dict(f, failure_classification=None)])) == []


def test_judgment_refuses_two_findings_with_one_id():
    """Identity is minted once. Two entries under one id is the shape that
    makes a delta unreadable."""
    f = judgment()["findings"][0]
    bad = validate_judgment(judgment(findings=[dict(f), dict(f, title="a different bug")]))
    assert any("P-F-1" in b and "findings[0]" in b for b in bad), bad


def test_judgment_names_the_finding_that_broke_a_rule():
    """The index in the message is how an operator finds it. Without it the
    error names nothing and the reader has to guess which finding."""
    f = judgment()["findings"][0]
    bad = validate_judgment(judgment(findings=[dict(f), dict(f, id="P-F-2", severity="Huge")]))
    assert any("findings[1]" in b for b in bad), bad


def test_judgment_checks_every_finding_not_just_the_first():
    """A loop that stops at the first bad entry hides everything after it."""
    f = judgment()["findings"][0]
    bad = validate_judgment(judgment(findings=[dict(f, id="P-F-1", severity="Huge"),
                                               dict(f, id="P-F-2", priority="P9")]))
    assert any("P-F-1" in b for b in bad) and any("P-F-2" in b for b in bad), bad


def test_judgment_caps_a_pass_that_leaves_a_blocker_open():
    f = judgment()["findings"][0]
    crit = dict(f, id="P-F-9", severity="Critical", status="open")
    bad = validate_judgment(judgment(verdict="pass", findings=[crit]))
    assert any("open Critical/Blocker" in b and "P-F-9" in b for b in bad), bad


def test_judgment_allows_a_pass_with_nothing_open():
    """The other half: `and` read as `or` refuses every clean pass, and a rule
    that fires on everything is one nobody reads."""
    f = dict(judgment()["findings"][0], status="resolved", delta=None)
    f.pop("delta")
    assert validate_judgment(judgment(verdict="pass", findings=[f])) == []
    assert validate_judgment(judgment(verdict="pass", findings=[])) == []


def test_judgment_allows_a_resolved_critical_under_a_pass():
    """Only *open* blockers cap the verdict — one that was fixed this run does
    not, or no project could ever return to `pass`."""
    f = dict(judgment()["findings"][0], id="P-F-9", severity="Critical", status="resolved")
    assert validate_judgment(judgment(verdict="pass", findings=[f])) == []


# ── the boundaries nobody was standing on ──────────────────────────────────

def test_the_clock_tolerances_are_where_they_say_they_are(root):
    """A tolerance no test stands on is a number anybody can widen. Both of
    these survived a mutation campaign at ±1 unit, which is exactly how a
    staleness rule quietly stops being one."""
    # Literal probes, never derived from the constants under test: reading the
    # value to build the input moves the probe with the mutation and the check
    # can no longer fail. The first cut of this test did exactly that.
    # Tolerances are 10 minutes ahead and 1 day behind. Each pair straddles its
    # boundary closely enough to catch a one-unit move in *either* direction,
    # with enough margin left that a slow machine cannot flip the result.
    inside_future = now_z(timedelta(minutes=9, seconds=30))
    outside_future = now_z(timedelta(minutes=10, seconds=30))
    inside_past = now_z(-timedelta(hours=23))
    outside_past = now_z(-timedelta(hours=25))

    def stamp(ts):
        s = good_state()
        s["last_run"] = {**s["last_run"], "timestamp_utc": ts}
        return [b for b in validate(s, root) if "timestamp" in b or "future" in b or "old" in b]

    assert stamp(inside_future) == [], "inside the future tolerance must pass"
    assert stamp(outside_future), "beyond the future tolerance must be refused"
    assert stamp(inside_past) == [], "inside the past tolerance must pass"
    assert stamp(outside_past), "beyond the past tolerance must be refused"


def test_a_timestamp_that_is_not_a_string_is_refused(root):
    """`not isinstance(...) or not match(...)` — read as `and`, a non-string
    reaches the regex and the rule dies on a TypeError instead of firing."""
    for value in (20260902, None, ["2026-09-02T00:00:00Z"], {"t": 1}):
        s = good_state()
        s["last_run"] = {**s["last_run"], "timestamp_utc": value}
        bad = validate(s, root)
        assert any("is not ISO-8601 UTC" in b for b in bad), f"{value!r}: {bad}"


def test_verified_intact_must_be_a_list(root):
    assert any("verified_intact" in b
               for b in validate(good_state(verified_intact="all good"), root))
    assert validate(good_state(verified_intact=["the suite is green"]), root) == []


def test_the_zero_coverage_refusal_fires_only_on_a_clean_pass(root):
    """Three guards, each of which survived mutation: the verdict must be
    `pass`, the coverage must be harness-measured, and the diff must be
    measured-zero rather than merely small."""
    zero = {"status": "measured", "changed_lines": 40, "changed_lines_executed": 0}
    fires = validate(good_state(verdict="pass", coverage=zero), root)
    assert any("none of the 40 changed lines was executed" in b for b in fires), fires

    # not a clean pass → the agent's call, not the validator's
    assert not [b for b in validate(good_state(verdict="pass with risks", coverage=zero), root)
                if "changed lines was executed" in b]
    # not harness-measured → a written block may not trigger a refusal
    written = {"status": "declared", "changed_lines": 40, "changed_lines_executed": 0}
    assert not [b for b in validate(good_state(verdict="pass", coverage=written), root)
                if "changed lines was executed" in b]
    # some execution → not the shape this rule is about
    some = {"status": "measured", "changed_lines": 40, "changed_lines_executed": 1}
    assert not [b for b in validate(good_state(verdict="pass", coverage=some), root)
                if "changed lines was executed" in b]


# ── the guards the campaign found on the state side ────────────────────────

def test_a_single_unexercised_changed_line_is_still_refused(root):
    """`changed > 0`, not `> 1`. A one-line change nothing executed is the
    same claim as a forty-line one."""
    one = {"status": "measured", "changed_lines": 1, "changed_lines_executed": 0}
    assert any("none of the 1 changed lines was executed" in b
               for b in validate(good_state(verdict="pass", coverage=one), root))


def test_a_run_number_must_be_a_positive_integer(root):
    """`not isinstance(...) or < 1` — read as `and`, a string run number
    reaches every downstream comparison."""
    for value in ("4", 0, -1, None, 4.5):
        assert any("run_number" in b for b in validate(good_state(run_number=value), root)), value
    assert validate(good_state(run_number=1), root) == []


def test_the_report_field_must_be_a_non_empty_string(root):
    """Same shape: `not isinstance(...) or not strip()`."""
    for value in (None, 42, "", "   ", []):
        s = good_state()
        s["last_run"] = {**s["last_run"], "report": value}
        assert any("report" in b for b in validate(s, root)), value


def test_the_state_validator_names_and_checks_every_finding_too(root):
    """The twins of the judgment-side rules closed in 0.67.0 — the campaign
    found the same three alive again on this side."""
    f = good_state()["findings"][0]
    bad = validate(good_state(findings=[dict(f, id="PRC-F-1", severity="Huge"),
                                        dict(f, id="PRC-F-2", hash="b2",
                                             failure_classification="MADE_UP")]), root)
    assert any("findings[0]" in b and "PRC-F-1" in b for b in bad), bad
    assert any("findings[1]" in b and "failure_classification" in b for b in bad), bad


def test_the_unmeasured_suite_refusal_names_which_gate_was_unreadable(root):
    """Run-level and only over an unqualified `pass`. `isinstance(g, dict) and
    g.get(...)` — read as `or`, every gate is listed as unreadable including the
    lint gate that legitimately parses to no counts."""
    s = good_state(verdict="pass", tests={},
                   gates={"suite": {"exit_code": 0, "counts_unparsed": True},
                          "lint": {"exit_code": 0}})
    bad = " ".join(b for b in validate(s, root) if "no gate in this run produced" in b)
    assert bad, "the rule must fire over a pass with no counts"
    assert "suite" in bad and "lint" not in bad, bad


def test_the_same_refusal_says_so_when_no_gate_reported_anything(root):
    """The `or` fallback: with nothing to list, the message must still say what
    happened rather than trailing off into empty parentheses."""
    s = good_state(verdict="pass", tests={}, gates={"lint": {"exit_code": 0}})
    bad = " ".join(b for b in validate(s, root) if "no gate in this run produced" in b)
    assert "no gate reported a runner summary" in bad, bad


# ── the five guards a mutation campaign found unwatched (F-48) ──────────────
#
# Run 9 ran the campaign method this repository documents, controlled the
# instrument first as the profile requires, and found five non-equivalent
# mutants still alive after 0.67.0 and 0.69.0. Nothing shipped was wrong; five
# guards could have been broken without a test noticing, in the one module
# written to refuse what the model writes. It proposed these checks.

def test_judgment_status_must_be_one_the_contract_knows():
    """Severity, priority, classification, fix_verified, duplicate ids, the
    index label, every-finding and the pass-cap were all covered. `status`,
    which decides whether a finding is even open, was not."""
    f = judgment()["findings"][0]
    for value in ("fixed", "OPEN-ISH", "done", 1):
        bad = validate_judgment(judgment(findings=[dict(f, status=value)]))
        assert any("status" in b for b in bad), (value, bad)
    for value in ("open", "resolved", "withdrawn"):
        assert not [b for b in validate_judgment(judgment(findings=[dict(f, status=value)]))
                    if "status" in b], value


def test_judgment_keeps_checking_after_a_malformed_entry():
    """The loop `continue`s past a non-dict. Read as `break`, everything after
    the first bad entry goes unchecked — and the every-finding test cannot
    reach it, because well-formed dicts never take that branch."""
    f = judgment()["findings"][0]
    bad = validate_judgment(judgment(findings=["not a finding at all",
                                               dict(f, id="P-F-2", severity="Huge")]))
    assert any("P-F-2" in b or "findings[1]" in b for b in bad), bad


def test_the_state_validator_keeps_checking_after_a_malformed_entry(root):
    f = good_state()["findings"][0]
    bad = validate(good_state(findings=[42, dict(f, id="PRC-F-2", hash="b2",
                                                 severity="Huge")]), root)
    assert any("PRC-F-2" in b or "findings[1]" in b for b in bad), bad


def _hook_event(path):
    return json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(path)}})


def test_hook_mode_refuses_a_state_it_cannot_read(root):
    """PostToolUse, the surface that catches a bad state while the run is still
    going. Exit 2 is what makes the agent fix it now."""
    (root / "state.json").write_text("{ not json", encoding="utf-8")
    proc = run_cli(stdin=_hook_event(root / "state.json"))
    assert proc.returncode == 2, proc.stderr
    assert "state.json" in proc.stderr


def test_hook_mode_is_silent_over_a_clean_state(root):
    """And the other half: a hook that complains about good work is one the
    agent learns to ignore."""
    (root / "state.json").write_text(json.dumps(good_state()), encoding="utf-8")
    proc = run_cli(stdin=_hook_event(root / "state.json"))
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr.strip() == "", proc.stderr


def test_hook_mode_ignores_writes_to_anything_else(root):
    (root / "notes.md").write_text("# notes", encoding="utf-8")
    proc = run_cli(stdin=_hook_event(root / "notes.md"))
    assert proc.returncode == 0 and proc.stderr.strip() == ""
