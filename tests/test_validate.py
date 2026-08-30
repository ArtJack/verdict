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
    assert proc.returncode == 1 and "violation" in proc.stderr

    assert run_cli(str(root / "missing.json")).returncode == 2


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
