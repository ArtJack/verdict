"""Evidence anchors and drift (T-1), `last_verified_at` (T-2), the two clocks (T-3).

A finding cites `path:line`. The harness hashes what it cites at finalize and
re-measures it at the next facts, so the tester is told where the code moved
instead of re-reading everything, and "the code under an accepted risk
changed" is a fact. Every test here builds a real repository and lets the real
`collect` / `merge` say what drifted. Each mutant pinned for 0.83.0 (L1–L7 in
eval/pinned_mutants.json) dies here.
"""

import json
import subprocess

from conftest import git, judgment
from verdict_mcp import anchors
from verdict_mcp.harness import collect, merge, next_finding_id, render_report, write_state
from verdict_mcp.state import outcome_row
from verdict_mcp.validate import validate_judgment

THREE = "x = 1\ny = 2\nz = 3\n"


def finding(**over):
    f = {"id": "W-F-1", "title": "the guard is off by one", "severity": "Major",
         "priority": "P1", "status": "open", "failure_classification": "REAL_DEFECT",
         "confidence": "proven", "evidence": ["a.py:2 — `y = 2` is the guard"]}
    f.update(over)
    return f


def rev_parse(repo, what):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", what],
                          capture_output=True, text=True, check=True).stdout.strip()


def finalize(repo, qa_root, j, facts=None):
    """facts → merge → write_state, and the state read back from disk."""
    facts = facts or collect(repo, qa_root, [])
    path = qa_root / "state.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    problems = write_state(qa_root, merge(facts, j, previous))
    assert problems == [], problems
    return json.loads(path.read_text(encoding="utf-8"))


def three_lines(repo):
    # bytes, not text: on Windows `write_text` turns the newline into CRLF and the blob moves
    (repo / "a.py").write_bytes(THREE.encode("utf-8"))
    git(["commit", "-qam", "three lines"], repo)


def rec(at_head, at_previous="fail"):
    return {"W-F-1": {"test": "t.py::t", "selected_by": "explicit", "candidates": 1,
                      "previous_sha": "abc1234", "at_previous": at_previous,
                      "at_head": at_head}}


# ── anchors at finalize ────────────────────────────────────────────────────

def test_finalize_anchors_every_cited_line(repo, qa_root):
    three_lines(repo)
    state = finalize(repo, qa_root, judgment(findings=[finding(
        evidence=["a.py:2 — `y = 2` is the guard", "t.py::test_y fails: assert 2 == 3"])]))
    f = state["findings"][0]
    assert f["anchors"] == [{"ref": "a.py:2", "path": "a.py", "line": 2,
                             "blob": anchors.blob_sha(THREE.encode())[:12],
                             "line_sha": anchors.line_sha(b"y = 2")}]
    assert f["anchored_at_run"] == 1
    # computed without git, equal to git's own object id
    assert rev_parse(repo, "HEAD:a.py")[:12] == f["anchors"][0]["blob"]
    assert state["evidence_anchors"] == {"status": "measured", "refs": 1, "unresolvable": 0}


def test_a_reference_that_names_nothing_is_recorded_as_such_and_costs_nothing(repo, qa_root):
    three_lines(repo)
    state = finalize(repo, qa_root, judgment(findings=[finding(
        evidence=["nope.py:3 does not exist", "a.py:99 is past the end", "../outside/x.py:1"])]))
    statuses = [a["status"] for a in state["findings"][0]["anchors"]]
    assert statuses == ["unresolvable"] * 3
    assert "beyond the end" in state["findings"][0]["anchors"][1]["reason"]
    assert state["evidence_anchors"]["unresolvable"] == 3


def test_the_class_sites_and_the_verified_intact_items_are_anchored_too(repo, qa_root):
    three_lines(repo)
    j = judgment(findings=[finding(root_cause={
        "mechanism": "m", "origin": "unknown",
        "class": {"pattern": "p", "sites": ["a.py:2 (this finding)", "a.py:3 — the twin"]}})],
        verified_intact=["a.py:1 still initialises x", "no reference here"])
    state = finalize(repo, qa_root, j)
    assert [a["ref"] for a in state["findings"][0]["anchors"]] == ["a.py:2", "a.py:3"]
    assert [[a["ref"] for a in group] for group in state["verified_intact_anchors"]] == \
        [["a.py:1"], []]


def test_anchors_are_carried_while_the_evidence_is_the_text_they_were_taken_from(repo, qa_root):
    three_lines(repo)
    state = finalize(repo, qa_root, judgment(findings=[finding()]))
    first = state["findings"][0]["anchors"]
    (repo / "a.py").write_bytes(("w = 0\n" + THREE).encode("utf-8"))   # the line moves
    git(["commit", "-qam", "insert"], repo)
    # same evidence: the anchor still dates from run 1, so the drift shows
    state = finalize(repo, qa_root, judgment(findings=[finding()]))
    assert state["findings"][0]["anchors"] == first
    assert state["findings"][0]["anchored_at_run"] == 1
    # new evidence: re-anchored now
    state = finalize(repo, qa_root, judgment(findings=[finding(evidence=["a.py:3 — moved"])]))
    assert state["findings"][0]["anchors"][0]["line"] == 3
    assert state["findings"][0]["anchored_at_run"] == 3


# ── drift at the next facts ────────────────────────────────────────────────

def test_the_next_facts_say_where_the_cited_code_went(repo, qa_root):
    three_lines(repo)
    finalize(repo, qa_root, judgment(findings=[finding()], verified_intact=["a.py:3 holds"]))

    facts = collect(repo, qa_root, [])
    drift = facts["evidence_drift"]
    assert drift["status"] == "measured"
    assert drift["findings"]["W-F-1"] == {"drift": "unchanged",
                                          "refs": [{"ref": "a.py:2", "status": "unchanged"}]}
    assert drift["summary"] == {"drifted_findings": [], "drifted_accepted": [],
                                "drifted_intact": []}

    # a line inserted above: moved, and the harness says to where (L3)
    (repo / "a.py").write_bytes(("w = 0\n" + THREE).encode("utf-8"))
    drift = collect(repo, qa_root, [])["evidence_drift"]
    assert drift["findings"]["W-F-1"] == {
        "drift": "moved", "refs": [{"ref": "a.py:2", "status": "moved", "now_line": 3}]}
    assert drift["verified_intact"][0]["drift"] == "moved"
    assert drift["verified_intact"][0]["refs"][0]["now_line"] == 4
    assert drift["summary"]["drifted_findings"] == ["W-F-1"]
    assert drift["summary"]["drifted_intact"] == [0]

    # the file changed elsewhere, the cited line where it was: unchanged
    (repo / "a.py").write_bytes("x = 1\ny = 2\nz = 33\n".encode("utf-8"))
    drift = collect(repo, qa_root, [])["evidence_drift"]
    assert drift["findings"]["W-F-1"]["refs"] == [
        {"ref": "a.py:2", "status": "unchanged", "file_changed": True}]

    # the cited line itself rewritten: changed
    (repo / "a.py").write_bytes("x = 1\ny = 22\nz = 3\n".encode("utf-8"))
    assert collect(repo, qa_root, [])["evidence_drift"]["findings"]["W-F-1"]["drift"] == "changed"

    # the file gone: missing
    (repo / "a.py").unlink()
    assert collect(repo, qa_root, [])["evidence_drift"]["findings"]["W-F-1"]["drift"] == "missing"


def test_the_code_under_an_accepted_risk_is_measured_in_its_own_bucket(repo, qa_root):
    three_lines(repo)
    finalize(repo, qa_root, judgment(findings=[finding()]))
    path = qa_root / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["findings"][0]["status"] = "accepted"
    path.write_text(json.dumps(state), encoding="utf-8")
    (repo / "a.py").write_bytes("x = 1\ny = 22\nz = 3\n".encode("utf-8"))
    drift = collect(repo, qa_root, [])["evidence_drift"]
    assert drift["findings"] == {}
    assert drift["accepted"]["W-F-1"]["drift"] == "changed"
    assert drift["summary"]["drifted_accepted"] == ["W-F-1"]


def test_a_previous_state_without_anchors_reads_unavailable_not_unchanged(repo, qa_root):
    three_lines(repo)
    finalize(repo, qa_root, judgment(findings=[finding()]))
    path = qa_root / "state.json"
    state = json.loads(path.read_text(encoding="utf-8"))
    state["findings"][0].pop("anchors")
    state.pop("verified_intact_anchors", None)
    path.write_text(json.dumps(state), encoding="utf-8")
    drift = collect(repo, qa_root, [])["evidence_drift"]
    assert drift["status"] == "unavailable" and "anchors" in drift["reason"]


def test_a_baseline_measures_no_drift_and_finalize_says_when_it_could_not_anchor(repo, qa_root):
    three_lines(repo)
    facts = collect(repo, qa_root, [])
    assert "evidence_drift" not in facts
    assert facts["repo"] == str(repo)
    # an older facts.json names no repo: nothing is anchored, and the state says so (L7)
    facts.pop("repo")
    state = merge(facts, judgment(findings=[finding()], verified_intact=["a.py:1 holds"]), None)
    assert state["evidence_anchors"]["status"] == "unavailable"
    assert "repo" in state["evidence_anchors"]["reason"]
    assert "anchors" not in state["findings"][0]
    assert state["verified_intact_anchors"] == []


def test_drift_travels_into_the_state_and_the_report(repo, qa_root):
    three_lines(repo)
    finalize(repo, qa_root, judgment(findings=[finding()]))
    (repo / "a.py").write_bytes(("w = 0\n" + THREE).encode("utf-8"))
    git(["commit", "-qam", "insert"], repo)
    state = finalize(repo, qa_root, judgment(findings=[finding()]))
    assert state["evidence_drift"]["summary"]["drifted_findings"] == ["W-F-1"]
    report = render_report(state)
    assert ("- Evidence drift: 1 of 1 anchored open findings cite code that moved or "
            "changed since the evidence was written (W-F-1)") in report
    assert "- Cited code moved since the evidence was written: a.py:2 (now line 3)" in report


# ── last_verified_at ───────────────────────────────────────────────────────

def test_last_verified_at_is_stamped_only_by_a_measurement(repo, qa_root):
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{"id": "W-F-1", "hash": "h", "status": "open",
                              "first_seen": "2026-09-01",
                              "last_verified_at": "2026-09-02T00:00:00Z"}]}
    # the test ran at HEAD, whatever it said: dated now
    state = merge({**facts, "verification": rec("fail")}, judgment(findings=[finding()]), previous)
    assert state["findings"][0]["last_verified_at"] == facts["measured_at"]
    state = merge({**facts, "verification": rec("pass", at_previous="pass")},
                  judgment(findings=[finding()]), previous)
    assert state["findings"][0]["last_verified_at"] == facts["measured_at"]
    # an error did not run the test (L4): the older date stands
    state = merge({**facts, "verification": rec("error")}, judgment(findings=[finding()]), previous)
    assert state["findings"][0]["last_verified_at"] == "2026-09-02T00:00:00Z"
    # nothing measured: carried, on a re-report and on a silent carry alike
    state = merge(facts, judgment(findings=[finding()]), previous)
    assert state["findings"][0]["last_verified_at"] == "2026-09-02T00:00:00Z"
    state = merge(facts, judgment(findings=[]), previous)
    assert state["findings"][0]["last_verified_at"] == "2026-09-02T00:00:00Z"
    # never measured: absent, and the report says what to declare
    state = merge(facts, judgment(findings=[finding()]), None)
    assert "last_verified_at" not in state["findings"][0]
    assert "- Never measured — no `verification_test` declared" in render_report(state)


def test_the_report_dates_the_measurement_and_its_result(repo, qa_root):
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{"id": "W-F-1", "hash": "h", "status": "open",
                              "first_seen": "2026-09-01"}]}
    state = merge({**facts, "verification": rec("fail")}, judgment(findings=[finding()]), previous)
    assert f"- Last measured {facts['measured_at'][:10]} — fails at HEAD" in render_report(state)


# ── the two clocks ─────────────────────────────────────────────────────────

def test_introduced_at_is_the_date_of_the_commit_the_origin_names(repo, qa_root):
    sha = rev_parse(repo, "HEAD")
    when = subprocess.run(["git", "-C", str(repo), "show", "-s", "--format=%cI", sha],
                          capture_output=True, text=True, check=True).stdout.strip()[:10]
    facts = collect(repo, qa_root, [])
    chain = {"mechanism": "m", "class": {"pattern": "p", "sites": ["a.py:1"]}}
    state = merge(facts, judgment(findings=[finding(root_cause={
        **chain, "origin": f"{sha[:9]} (perf: avoid Decimal) replaced the quantize"})]), None)
    assert state["findings"][0]["introduced_at"] == when
    assert state["findings"][0]["introduced_sha"] == sha
    # no commit named: no date — never first_seen in disguise (L5)
    state = merge(facts, judgment(findings=[finding(root_cause={
        **chain, "origin": "the July rewrite, no single commit"})]), None)
    assert "introduced_at" not in state["findings"][0]
    # a hex-looking word git does not know: no date
    state = merge(facts, judgment(findings=[finding(root_cause={
        **chain, "origin": "deadbeef1 by blame"})]), None)
    assert "introduced_at" not in state["findings"][0]


def test_fixed_at_is_the_date_of_the_measured_fix_never_of_a_claim(repo, qa_root):
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{"id": "W-F-1", "hash": "h", "status": "open",
                              "first_seen": "2026-09-01"}]}
    measured = merge({**facts, "verification": rec("pass")},
                     judgment(findings=[finding(status="resolved")]), previous)
    f = measured["findings"][0]
    assert f["fix_verified"] is True and f["outcome_basis"] == "measured"
    assert f["fixed_at"] == facts["measured_at"][:10]
    # the tester's word alone (L6): confirmed on a claim, but undated
    claimed = merge(facts, judgment(findings=[finding(status="resolved", fix_verified=True)]),
                    previous)
    assert claimed["findings"][0]["outcome_basis"] == "claimed"
    assert "fixed_at" not in claimed["findings"][0]


def test_the_report_prints_both_clocks_and_the_ledger_keeps_them(repo, qa_root):
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(findings=[finding()]), None)
    f = state["findings"][0]
    f.update(introduced_at="2026-01-01", first_seen="2026-09-01", fixed_at="2026-09-04")
    header = [ln for ln in render_report(state).splitlines() if ln.startswith("### W-F-1")][0]
    assert "· lived 243d before detection · fix verified 3d after detection" in header
    row = outcome_row(f)
    assert row["introduced_at"] == "2026-01-01" and row["fixed_at"] == "2026-09-04"
    assert "introduced_at" not in outcome_row(finding())


# ── the next id, and the judgment's side of the contract ───────────────────

def test_facts_name_the_next_finding_id(repo, qa_root):
    assert next_finding_id("widget", None, None) == "WIDGET-F-1"
    prev = {"findings": [{"id": "W-F-1"}, {"id": "W-F-7"}]}
    ledger = {"findings": {"h": {"id": "W-F-9"}}}   # resolved runs ago, gone from state
    assert next_finding_id("widget", prev, ledger) == "W-F-10"
    assert next_finding_id("pricer", {"findings": [{"id": "PRICER-F-003"}]}, None) == "PRICER-F-004"
    assert collect(repo, qa_root, [])["next_finding_id"] == "WIDGET-F-1"
    finalize(repo, qa_root, judgment(findings=[finding()]))
    assert collect(repo, qa_root, [])["next_finding_id"] == "W-F-2"


def test_a_judgment_that_writes_the_measured_fields_is_told():
    bad = validate_judgment(judgment(findings=[finding(anchors=[], last_verified_at="x",
                                                       introduced_at="y", fixed_at="z")]))
    assert len(bad) == 1 and "anchors, last_verified_at, introduced_at, fixed_at" in bad[0]


def test_references_are_read_the_way_evidence_is_written():
    assert anchors.refs_in([
        "src/pricer/money.py:14 — `return int(amount * 100)`",
        "tests/test_money.py::test_to_cents_rounds_half_up — fails at HEAD",   # a node id, not a ref
        "see https://example.com:8080/x.py:3 for context",                     # a URL, not a ref
        "src\\pricer\\report.py:41 rounds with round()",                        # Windows spelling
        "money.py:14 again", "12:30 is a time"]) == [
        ("src/pricer/money.py", 14), ("src/pricer/report.py", 41), ("money.py", 14)]
    assert len(anchors.refs_in([f"f{i}.py:1" for i in range(50)])) == anchors.MAX_REFS
