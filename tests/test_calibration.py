"""Tests for the track record — the tester's own error rate, computed.

The value of a QA agent's finding depends on how often its findings hold up,
and that number is worthless if the agent can influence it. So these tests are
mostly about what the system refuses to let the model do: revise a confidence
after seeing the outcome, mark its own findings correct, or let a false
positive quietly age off the page.
"""

import json
from datetime import date, datetime, timezone

import pytest

from verdict_mcp.harness import finding_hash, merge, render_report, write_state
from verdict_mcp.state import (
    CALIBRATION_MIN_SAMPLE, calibration, is_open, load_outcomes, merge_outcomes,
    norm_status, outcome_row)

NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def facts(n=1):
    return {"project": "demo", "run_type": "baseline" if n == 1 else "delta",
            "run_number": n, "last_run": {"timestamp_utc": NOW, "git_sha": "abc1234"},
            "gates": {}}


def finding(i=1, **over):
    f = {"id": f"D-F-{i}", "title": f"bug {i}", "evidence": [f"src/m{i}.py:10"],
         "severity": "Major", "priority": "P1", "failure_classification": "REAL_DEFECT",
         "confidence": "probable", "status": "open"}
    f.update(over)
    return f


def judgment(findings, **over):
    j = {"findings": findings, "verdict": "fail", "release_blockers": [],
         "not_tested": ["nothing"], "isolation_check": {"result": "pass"},
         "report": "reports/r.md"}
    j.update(over)
    return j


def run(qa_root, n, findings, previous):
    """One full run through merge → report → write_state, ledger and all."""
    state = merge(facts(n), judgment(findings), previous, today=date.today(),
                  ledger=load_outcomes(qa_root))
    (qa_root / "reports").mkdir(parents=True, exist_ok=True)
    (qa_root / "reports" / "r.md").write_text(render_report(state), encoding="utf-8")
    problems = write_state(qa_root, state)
    assert problems == [], problems
    return state


@pytest.fixture
def qa_root(tmp_path):
    root = tmp_path / "qa"
    root.mkdir()
    return root


# ── the outcome is computed, never claimed ────────────────────────────────

def test_regression_confirms_a_finding_because_it_came_back():
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()), status="resolved")]}
    state = merge(facts(2), judgment([finding()]), prev)
    f = state["findings"][0]
    assert f["delta"] == "REGRESSED" and f["outcome"] == "confirmed"


def test_a_resolution_without_re_injection_settles_nothing():
    """Absence is not evidence of a fix — §6's rule, now with teeth."""
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()))]}
    merely_gone = merge(facts(2), judgment([finding(status="resolved")]), prev)
    verified = merge(facts(2), judgment([finding(status="resolved", fix_verified=True)]), prev)
    assert merely_gone["findings"][0]["outcome"] == "unknown"
    assert verified["findings"][0]["outcome"] == "confirmed"


def test_a_withdrawal_is_the_one_thing_that_refutes():
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()))]}
    state = merge(facts(2), judgment([finding(status="withdrawn", delta="WITHDRAWN")]), prev)
    assert state["findings"][0]["outcome"] == "refuted"


def test_the_model_cannot_mark_its_own_finding_correct():
    """The one field a tester must never own. Whatever it writes is overwritten."""
    state = merge(facts(1), judgment([finding(outcome="confirmed",
                                              outcome_reason="trust me")]), None)
    f = state["findings"][0]
    assert f["outcome"] == "unknown" and "still open" in f["outcome_reason"]


def test_a_decided_outcome_sticks_when_the_finding_changes_state_again():
    """Without stickiness the record erodes: a finding confirmed by regression on
    one run would go back to undecided the moment it was still open on the next."""
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()), status="resolved")]}
    regressed = merge(facts(2), judgment([finding()]), prev)
    still_open = merge(facts(3), judgment([finding()]), regressed)
    assert still_open["findings"][0]["delta"] == "STILL_OPEN"
    assert still_open["findings"][0]["outcome"] == "confirmed"


def test_a_withdrawal_overrides_an_earlier_confirmation():
    """Stickiness has exactly one exception: the tester saying it got this wrong."""
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()), status="resolved")]}
    regressed = merge(facts(2), judgment([finding()]), prev)
    assert regressed["findings"][0]["outcome"] == "confirmed"
    withdrawn = merge(facts(3), judgment([finding(status="withdrawn", delta="WITHDRAWN")]),
                      regressed)
    assert withdrawn["findings"][0]["outcome"] == "refuted"


# ── the claim is frozen at filing ─────────────────────────────────────────

def test_confidence_cannot_be_revised_after_the_fact():
    """A prediction edited once the answer is known is not a prediction."""
    first = dict(finding(confidence="hypothesis"), hash=finding_hash(finding()))
    state = merge(facts(2), judgment([finding(confidence="proven")]), {"findings": [first]})
    assert state["findings"][0]["confidence"] == "hypothesis"


def test_confidence_survives_being_carried_forward_unmentioned():
    first = dict(finding(confidence="proven"), hash=finding_hash(finding()))
    state = merge(facts(2), judgment([]), {"findings": [first]})
    carried = state["findings"][0]
    assert carried["confidence"] == "proven" and carried["outcome"] == "unknown"
    assert "no one verified" in carried["outcome_reason"]


# ── the false-positive record does not age off the page ───────────────────

def test_a_withdrawn_finding_survives_a_run_that_does_not_mention_it():
    """A tester that lets its own false positives fall off the report is hiding
    the one number a reader needs to weigh everything else it says."""
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()))]}
    withdrawn = merge(facts(2), judgment([finding(status="withdrawn", delta="WITHDRAWN")]), prev)
    silent = merge(facts(3), judgment([]), withdrawn)
    assert [f["delta"] for f in silent["findings"]] == ["WITHDRAWN"]
    assert silent["findings"][0]["outcome"] == "refuted"


# ── the ledger, which is what makes any of this measurable ────────────────

def test_the_ledger_keeps_outcomes_after_findings_leave_state(qa_root):
    """state.json drops a finding resolved two runs ago. If the outcome went with
    it, the sample would reset every run and never reach a rate."""
    s1 = run(qa_root, 1, [finding(1), finding(2)], None)
    s2 = run(qa_root, 2, [finding(1, status="resolved", fix_verified=True), finding(2)], s1)
    s3 = run(qa_root, 3, [finding(2)], s2)

    assert [f["id"] for f in s3["findings"]] == ["D-F-2"], "resolved findings age out of state"
    ledger = load_outcomes(qa_root)
    assert {row["id"]: row["outcome"] for row in ledger.values()} == {
        "D-F-1": "confirmed", "D-F-2": "unknown"}
    assert s3["calibration"]["findings_tracked"] == 2
    assert s3["calibration"]["decided_outcomes"] == 1


def test_the_ledger_upserts_by_identity_so_nothing_is_counted_twice():
    """Folding the same run in twice — a retried finalize — must leave one row,
    not two. Identity is the hash, which is why findings have one."""
    rows = [{"hash": "h1", "id": "D-F-1", "confidence": "proven", "outcome": "confirmed"}]
    once = merge_outcomes({}, rows, "2026-09-01")
    twice = merge_outcomes(once, rows, "2026-09-01")
    assert once == twice and len(twice) == 1


def test_a_decided_row_is_not_downgraded_by_a_later_unknown():
    ledger = {"h1": {"hash": "h1", "outcome": "confirmed", "outcome_reason": "regressed",
                     "confidence": "proven"}}
    after = merge_outcomes(ledger, [{"hash": "h1", "outcome": "unknown",
                                     "outcome_reason": "still open", "confidence": "proven"}])
    assert after["h1"]["outcome"] == "confirmed"
    assert after["h1"]["outcome_reason"] == "regressed"


def test_a_missing_or_corrupt_ledger_reads_as_empty_and_never_raises(tmp_path):
    assert load_outcomes(tmp_path) == {}
    (tmp_path / "outcomes.json").write_text("{not json", encoding="utf-8")
    assert load_outcomes(tmp_path) == {}
    (tmp_path / "outcomes.json").write_text('{"findings": []}', encoding="utf-8")
    assert load_outcomes(tmp_path) == {}


def test_the_ledger_row_carries_the_tally_fields_and_not_the_essay():
    row = outcome_row({"hash": "h1", "id": "D-F-1", "severity": "Major",
                       "confidence": "probable", "outcome": "confirmed",
                       "title": "a long title", "evidence": ["x"] * 50,
                       "root_cause": {"proof": {"method": "differential"}}}, "2026-09-01")
    assert row["proof_method"] == "differential" and row["decided_on"] == "2026-09-01"
    assert "evidence" not in row and "title" not in row


def test_an_undecided_row_carries_no_decision_date():
    assert "decided_on" not in outcome_row({"hash": "h", "outcome": "unknown"}, "2026-09-01")


# ── the arithmetic, and its refusal to show a rate it has not earned ──────

def test_no_rate_is_published_below_the_minimum_sample():
    state = {"findings": [{"hash": f"h{i}", "confidence": "proven", "outcome": "confirmed"}
                          for i in range(5)]}
    bucket = calibration(state)["by_confidence"]["proven"]
    assert bucket["precision"] is None
    assert "too few for a rate" in bucket["reading"]


def test_a_rate_appears_once_the_sample_is_there():
    rows = [{"hash": f"c{i}", "confidence": "proven", "outcome": "confirmed"} for i in range(27)]
    rows += [{"hash": f"r{i}", "confidence": "proven", "outcome": "refuted"} for i in range(3)]
    bucket = calibration({"findings": rows})["by_confidence"]["proven"]
    assert bucket["decided"] == CALIBRATION_MIN_SAMPLE
    assert bucket["precision"] == 0.9 and bucket["reading"] == "27 of 30 held up"


def test_undecided_findings_are_excluded_from_the_denominator_not_guessed_at():
    rows = [{"hash": "a", "confidence": "proven", "outcome": "confirmed"},
            {"hash": "b", "confidence": "proven", "outcome": "unknown"},
            {"hash": "c", "confidence": "proven"}]
    cal = calibration({"findings": rows})
    assert cal["findings_tracked"] == 3
    assert cal["decided_outcomes"] == 1 and cal["undecided_outcomes"] == 2
    assert cal["by_confidence"]["proven"]["decided"] == 1


def test_findings_with_no_stated_confidence_land_in_their_own_bucket():
    """Runs that predate the rule are legal and must not be silently folded into
    a bucket they never claimed."""
    cal = calibration({"findings": [{"hash": "a", "outcome": "confirmed"}]})
    assert cal["by_confidence"]["unstated"]["confirmed"] == 1
    assert "proven" not in cal["by_confidence"]


def test_an_invented_confidence_value_is_not_given_its_own_row():
    cal = calibration({"findings": [{"hash": "a", "confidence": "very sure",
                                     "outcome": "confirmed"}]})
    assert set(cal["by_confidence"]) == {"unstated"}


def test_proof_method_is_tallied_separately_from_confidence():
    rows = [{"hash": "a", "confidence": "proven", "outcome": "confirmed",
             "root_cause": {"proof": {"method": "counterfactual"}}},
            {"hash": "b", "confidence": "proven", "outcome": "refuted",
             "root_cause": {"proof": {"method": "reading"}}}]
    by_method = calibration({"findings": rows})["by_proof_method"]
    assert by_method["counterfactual"]["confirmed"] == 1
    assert by_method["reading"]["refuted"] == 1


def test_the_current_run_outranks_its_own_ledger_row():
    """A withdrawal filed today beats the confirmation inferred yesterday."""
    ledger = {"h1": {"hash": "h1", "confidence": "proven", "outcome": "confirmed"}}
    cal = calibration({"findings": [{"hash": "h1", "confidence": "proven",
                                     "outcome": "refuted"}]}, ledger=ledger)
    assert cal["by_confidence"]["proven"] == {
        **cal["by_confidence"]["proven"], "confirmed": 0, "refuted": 1}


# ── the report says it plainly, or says nothing ───────────────────────────

def test_the_report_stays_silent_until_something_has_been_settled(qa_root):
    run(qa_root, 1, [finding(1), finding(2)], None)
    assert "Track record" not in (qa_root / "reports" / "r.md").read_text(encoding="utf-8")


def test_the_report_shows_counts_before_it_has_earned_a_rate(qa_root):
    s1 = run(qa_root, 1, [finding(1), finding(2)], None)
    run(qa_root, 2, [finding(1, status="resolved", fix_verified=True), finding(2)], s1)
    report = (qa_root / "reports" / "r.md").read_text(encoding="utf-8")
    assert "## Track record" in report
    assert "_not yet_" in report, "a rate must not appear below the minimum sample"
    assert "1 settled" in report


# ── the status field these tallies read ───────────────────────────────────

def test_status_comparison_is_case_insensitive():
    """A live baseline wrote "OPEN", and every consumer disagreed with it — the
    gate reported zero open findings for a project holding seven."""
    assert is_open({"status": "OPEN"}) and is_open({"status": " open "})
    assert not is_open({"status": "Resolved"})
    assert norm_status(None) == ""


def test_merge_normalizes_status_so_downstream_counts_are_right():
    state = merge(facts(1), judgment([finding(status="OPEN")]), None)
    assert state["findings"][0]["status"] == "open"


def test_a_withdrawn_finding_stops_counting_as_open():
    """It was retracted as never real; leaving it open kept it counting toward
    blockers it had already been withdrawn from."""
    prev = {"findings": [dict(finding(), hash=finding_hash(finding()))]}
    state = merge(facts(2), judgment([finding(delta="WITHDRAWN")]), prev)
    f = state["findings"][0]
    assert f["status"] == "withdrawn" and not is_open(f) and f["outcome"] == "refuted"


def test_an_unrecognised_status_reads_as_open_not_as_closed():
    """The safe direction: `"closed"`, `"done"`, or a missing status are not
    evidence a defect was fixed. Read the other way, one typo hid an open
    Critical from the gate, the blockers and the hotspot ranking."""
    assert is_open({"status": "closed"}) and is_open({"status": "done"})
    assert is_open({}) and is_open({"status": ""})
    assert not is_open({"status": "resolved"}) and not is_open({"status": "WITHDRAWN"})


def test_the_ledger_is_folded_once_not_twice(qa_root):
    """Folding it in `merge` from today's date and again in `write_state` from
    the run timestamp gave two different `decided_on` values across a
    UTC-midnight run — the calibration block inside the state could disagree
    with the ledger persisted beside it."""
    s1 = run(qa_root, 1, [finding(1)], None)
    run(qa_root, 2, [finding(1, status="resolved", fix_verified=True)], s1)
    row = next(iter(load_outcomes(qa_root).values()))
    assert row["decided_on"] == NOW[:10], "the run's own date, from one place"


def test_internal_keys_never_reach_the_written_state(qa_root):
    state = run(qa_root, 1, [finding(1)], None)
    written = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert not [k for k in written if k.startswith("_")], written.keys()
    assert "_ledger" not in state


def test_a_torn_write_cannot_leave_a_half_written_state(qa_root):
    """Every artifact goes through a temp file and os.replace, so a crash
    mid-write leaves the previous version intact rather than a truncated one."""
    s1 = run(qa_root, 1, [finding(1)], None)
    run(qa_root, 2, [finding(1), finding(2)], s1)
    for name in ("state.json", "state.json.prev", "outcomes.json"):
        json.loads((qa_root / name).read_text(encoding="utf-8"))   # parses = intact
    assert not list(qa_root.glob("*.tmp")), "no temp files survive a clean run"


def test_the_report_and_the_gate_order_findings_identically():
    """The harness carried its own copy of the REGRESSED-first sort, and the two
    had already drifted: `order_findings` strips whitespace before ranking a
    severity, the harness copy did not, so ` Critical ` sorted below `Major` in
    the report and above it everywhere else. One function now, not two."""
    from verdict_mcp.state import order_findings
    findings = [
        {"id": "A", "severity": " Critical ", "delta": "NEW", "age_days": 1,
         "evidence": ["a.py:1"], "title": "a", "status": "open"},
        {"id": "B", "severity": "Major", "delta": "NEW", "age_days": 1,
         "evidence": ["b.py:1"], "title": "b", "status": "open"},
    ]
    expected = [f["id"] for f in order_findings(findings)]
    assert expected == ["A", "B"]

    report = render_report({"project": "p", "run_number": 1, "run_type": "baseline",
                            "verdict": "fail", "findings": findings,
                            "last_run": {"timestamp_utc": NOW}})
    seen = [line.split()[1] for line in report.splitlines() if line.startswith("### ")]
    assert seen == expected, "the report must not have its own opinion about order"


def test_the_renderer_never_crashes_on_unexpected_prose():
    """`validate_judgment` rejects a non-object prose with an actionable message,
    but a renderer that raises on unexpected input loses a whole run to a typo."""
    state = {"project": "p", "run_number": 1, "run_type": "baseline", "verdict": "pass",
             "findings": [], "last_run": {"timestamp_utc": NOW}}
    for prose in ("a bare string", ["a", "list"], 42, None, {"findings": "not a map"}):
        assert "# QA report" in render_report(state, prose), repr(prose)


# ── the ledger reads the measurement, not the flag (F-32) ───────────────────

from verdict_mcp.harness import _stamp_outcome  # noqa: E402


def _resolved(**over):
    return {"id": "D-F-9", "delta": "RESOLVED", "status": "resolved", **over}


def test_a_measured_re_injection_confirms():
    out = _stamp_outcome(_resolved(fix_verified=True,
                                   verification={"test": "t.py::a", "at_previous": "fail",
                                                 "at_head": "pass"}))
    assert out["outcome"] == "confirmed" and "re-injection" in out["outcome_reason"]


def test_a_claim_the_harness_could_not_weigh_still_stands():
    """The claim is not thrown away. On a project the harness cannot measure it
    is the only evidence there is, and starving the ledger is how the track
    record died in the first place."""
    out = _stamp_outcome(_resolved(fix_verified=True))
    assert out["outcome"] == "confirmed" and "claimed by the tester" in out["outcome_reason"]


def test_an_inconclusive_measurement_is_silence_not_evidence():
    """VERDICT-F-35: 0.62.0 demoted a claim whenever a measurement had been
    *attempted*, and which test gets attempted is a prose lottery — so the same
    hand-verified claim landed `confirmed` when the write-up quoted no node id
    and `unknown` when it did. Two of these ran against a test that says
    nothing; neither may change the outcome."""
    for verification in ({"test": "t.py::new", "at_previous": "error", "at_head": "error"},
                         {"test": "t.py::a", "at_previous": "pass", "at_head": "pass"}):
        out = _stamp_outcome(_resolved(fix_verified=True, verification=verification))
        assert out["outcome"] == "confirmed", (verification, out)
        assert out["outcome_basis"] == "claimed", out
    bare = _stamp_outcome(_resolved(fix_verified=True))
    assert (bare["outcome"], bare["outcome_basis"]) == ("confirmed", "claimed")


def test_a_measurement_that_contradicts_the_claim_still_settles_nothing():
    """The one measurement that outranks the claim: the guarding test still
    fails on the code being judged."""
    out = _stamp_outcome(_resolved(fix_verified=True,
                                   verification={"test": "t.py::a", "at_previous": "fail",
                                                 "at_head": "fail"}))
    assert out["outcome"] == "unknown", out
    assert "still fails at HEAD" in out["outcome_reason"]


def test_the_basis_says_which_of_the_two_it_was():
    measured = _stamp_outcome(_resolved(fix_verified=True,
                                        verification={"test": "t.py::a", "at_previous": "fail",
                                                      "at_head": "pass"}))
    assert measured["outcome_basis"] == "measured"
    assert _stamp_outcome(_resolved(fix_verified=True))["outcome_basis"] == "claimed"


def test_a_resolution_with_neither_is_still_undecided():
    out = _stamp_outcome(_resolved())
    assert out["outcome"] == "unknown" and "absence is not proof" in out["outcome_reason"]


def test_a_settled_outcome_still_outranks_the_new_rule():
    """The ledger is permanent: a row decided under any earlier rule stays."""
    out = _stamp_outcome(_resolved(fix_verified=True),
                         {"outcome": "confirmed", "outcome_reason": "settled long ago"})
    assert out["outcome"] == "confirmed" and out["outcome_reason"] == "settled long ago"


def test_a_regression_is_recorded_on_the_finding_and_carried(tmp_path):
    """VERDICT-F-34: `delta` is one run's transition. When a finding came back
    is a fact about the finding, and anything downstream that did not look on
    that exact run needs it to still be there."""
    open_f = finding(1)
    s1 = merge(facts(1), judgment([open_f]), None)
    s2 = merge(facts(2), judgment([dict(open_f, status="resolved")]), s1)
    s3 = merge(facts(3), judgment([dict(open_f, status="open")]), s2)
    assert s3["findings"][0]["delta"] == "REGRESSED"
    assert s3["findings"][0]["regressed_at_run"] == 3
    s4 = merge(facts(4), judgment([dict(open_f, status="open")]), s3)
    assert s4["findings"][0]["delta"] == "STILL_OPEN"
    assert s4["findings"][0]["regressed_at_run"] == 3, "carried, not recomputed"


def test_a_finding_that_never_came_back_carries_no_marker():
    s1 = merge(facts(1), judgment([finding(1)]), None)
    s2 = merge(facts(2), judgment([finding(1)]), s1)
    assert "regressed_at_run" not in s2["findings"][0]


def test_the_tally_separates_what_was_measured_from_what_was_asserted():
    """VERDICT-F-36: the block counted both as one integer, so a rate built
    mostly on the tester's own word read exactly like a measured one."""
    from verdict_mcp.state import calibration
    rows = [{"hash": "m1", "outcome": "confirmed", "outcome_basis": "measured",
             "confidence": "proven"},
            {"hash": "c1", "outcome": "confirmed", "outcome_basis": "claimed",
             "confidence": "proven"},
            {"hash": "r1", "outcome": "refuted", "confidence": "proven"}]
    c = calibration({"findings": rows}, min_sample=3)["by_confidence"]["proven"]
    assert (c["confirmed"], c["confirmed_measured"], c["confirmed_claimed"]) == (2, 1, 1)
    assert "1 measured, 1 on the tester's word" in c["reading"]
    assert any("outcome_basis" in x
               for x in calibration({"findings": rows}, min_sample=3)["caveats"])


def test_rows_from_before_the_field_are_not_relabelled():
    """A row with no basis recorded predates the field; calling it the tester's
    word would be a claim of its own."""
    from verdict_mcp.state import calibration
    rows = [{"hash": f"o{i}", "outcome": "confirmed", "confidence": "proven"}
            for i in range(3)]
    c = calibration({"findings": rows}, min_sample=3)["by_confidence"]["proven"]
    assert c["reading"] == "3 of 3 held up", c["reading"]


def test_the_caveat_no_longer_contradicts_the_rule():
    """It read "a finding resolved without re-injection stays undecided" over
    rows that were confirmed on exactly that basis."""
    from verdict_mcp.state import calibration
    caveats = " ".join(calibration({"findings": []}, min_sample=3)["caveats"])
    assert "resolved without re-injection stays undecided" not in caveats
    assert "nobody checked at all stays undecided" in caveats


def test_a_measurement_the_harness_declined_to_weigh_does_not_deny_the_row():
    """VERDICT-F-40: `_apply_verification` stamps `not_weighed` on a test chosen
    by prose order from several candidates and refuses to reopen the finding
    with it. Reading the same record here as a contradiction denied the row
    anyway, under a reason saying the opposite of the note beside it."""
    weak = {"test": "t.py::unrelated", "at_previous": "pass", "at_head": "fail",
            "selected_by": "first_cited", "candidates": 3,
            "not_weighed": "chosen by prose order from 3 cited tests"}
    out = _stamp_outcome(_resolved(fix_verified=True, verification=weak))
    assert out["outcome"] == "confirmed" and out["outcome_basis"] == "claimed", out


def test_a_measurement_the_harness_did_weigh_still_denies_it():
    """The false-positive guard: one deliberately chosen test, still failing."""
    strong = {"test": "t.py::a", "at_previous": "fail", "at_head": "fail",
              "selected_by": "explicit", "candidates": 1}
    out = _stamp_outcome(_resolved(fix_verified=True, verification=strong))
    assert out["outcome"] == "unknown", out


def test_the_ledger_row_keeps_the_measurement_not_only_the_sentence():
    """VERDICT-F-41: a row outlives its finding, so a `confirmed` with no
    measurement recorded can never be audited — 19 of 21 were unjoinable."""
    from verdict_mcp.state import outcome_row
    f = {"id": "D-F-1", "hash": "h1", "severity": "Major", "confidence": "proven",
         "outcome": "confirmed", "outcome_basis": "measured",
         "outcome_reason": "fix-verified: the guarding test failed on re-injection",
         "verification": {"test": "tests/test_x.py::test_y", "at_previous": "fail",
                          "at_head": "pass", "selected_by": "explicit",
                          "previous_sha": "abc123", "summary": "1 failed → 1 passed"}}
    row = outcome_row(f, "2026-09-02")
    assert row["verification"] == {"test": "tests/test_x.py::test_y", "at_previous": "fail",
                                   "at_head": "pass", "selected_by": "explicit"}, row
    assert "summary" not in row["verification"], "a row is a hundred bytes, not a finding"


def test_a_row_with_nothing_measured_carries_no_empty_block():
    from verdict_mcp.state import outcome_row
    row = outcome_row({"id": "D-F-2", "hash": "h2", "outcome": "unknown"})
    assert "verification" not in row, row
