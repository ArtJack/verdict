"""Fix verification: the harness re-injects the defect so the tester need not.

`fix_verified` is the one judgment field that feeds the track record, and it
was almost never set — 95 of 110 Sales findings undecided, no precision rate
publishable. Each test here builds a real two-commit repository and lets the
real runner say whether the cited test fails before the fix and passes after.
"""

import json
import subprocess
import sys
from datetime import date, datetime, timezone

import verdict_mcp.harness as h
from verdict_mcp.harness import (cited_tests, collect, merge, render_report,
                                 resolve_test_id)
from verdict_mcp.validate import validate_judgment

from conftest import judgment

CMD = f'"{sys.executable}" -m pytest {{id}} -q -p no:cacheprovider'


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


BUGGY = "def pending(q, i):\n    return q - i\n"
FIXED = "def pending(q, i):\n    return q + i\n"
TEST = "from pkg import pending\n\ndef test_pending():\n    assert pending(3, 2) == 5\n"


def bugged_repo(tmp_path, *, with_test=True):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "pkg.py").write_text(BUGGY, encoding="utf-8")
    if with_test:
        (r / "test_pkg.py").write_text(TEST, encoding="utf-8")
    return r, commit(r, "bug")


def previous_state(qa_root, sha, evidence=("pkg.py:2 return q - i",
                                           "test_pkg.py::test_pending fails: assert 1 == 5")):
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "state.json").write_text(json.dumps({
        "project": "proj", "run_number": 1, "run_type": "baseline",
        "last_run": {"git_sha": sha,
                     "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "findings": [{"id": "P-F-1", "hash": "h1", "status": "open", "severity": "Major",
                      "priority": "P1", "title": "pending subtracts", "confidence": "proven",
                      "first_seen": date.today().isoformat(), "evidence": list(evidence)}],
    }), encoding="utf-8")
    return json.loads((qa_root / "state.json").read_text(encoding="utf-8"))


def resolved():
    j = judgment()
    j["findings"] = [{"id": "P-F-1", "title": "pending subtracts", "severity": "Major",
                      "priority": "P1", "status": "resolved", "evidence": ["pkg.py:2 now q + i"]}]
    return j


# ── the loop closes ─────────────────────────────────────────────────────────

def test_a_fix_is_verified_when_the_cited_test_fails_before_and_passes_after(tmp_path):
    repo, sha_a = bugged_repo(tmp_path)
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    commit(repo, "fix")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    rec = facts["verification"]["P-F-1"]
    assert (rec["at_previous"], rec["at_head"]) == ("fail", "pass"), rec
    assert rec["previous_sha"] == sha_a

    state = merge(facts, resolved(), prev)
    f = state["findings"][0]
    assert f["delta"] == "RESOLVED" and f["fix_verified"] is True
    assert f["outcome"] == "confirmed" and "fix-verified" in f["outcome_reason"]
    assert any("verification (measured)" in e for e in f["evidence"])
    assert "Fix verification: 1 verified" in render_report(state)


def test_silence_is_verified_too(tmp_path):
    """A finding nobody re-reported used to stay `unknown` forever. The cited
    test does not care whether anyone mentioned it."""
    repo, sha_a = bugged_repo(tmp_path)
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    commit(repo, "fix")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    j = judgment()
    j["findings"] = []
    carried = [f for f in merge(facts, j, prev)["findings"] if f["id"] == "P-F-1"][0]
    assert carried["delta"] == "RESOLVED" and carried["fix_verified"] is True
    assert carried["outcome"] == "confirmed"


# ── measurement outranks the claim ──────────────────────────────────────────

def test_a_resolution_is_refused_while_the_cited_test_still_fails(tmp_path):
    repo, sha_a = bugged_repo(tmp_path)
    (repo / "README").write_text("unrelated\n", encoding="utf-8")
    commit(repo, "unrelated")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    assert facts["verification"]["P-F-1"]["at_head"] == "fail"

    f = merge(facts, resolved(), prev)["findings"][0]
    assert f["status"] == "open" and f["delta"] == "STILL_OPEN"
    assert "test_pkg.py::test_pending still fails at HEAD" in f["resolution_refused"]
    assert f["outcome"] == "unknown" and "fix_verified" not in f

    j = judgment()
    j["findings"] = []
    carried = [x for x in merge(facts, j, prev)["findings"] if x["id"] == "P-F-1"][0]
    assert carried["status"] == "open" and "held open by measurement" in carried["carried_forward"]


def test_a_test_the_fix_added_is_carried_back_to_the_old_commit(tmp_path):
    """The commonest shape: fix and regression test land together. The old
    code has no test to run — so the new test is copied back and meets it."""
    repo, sha_a = bugged_repo(tmp_path, with_test=False)
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    (repo / "test_pkg.py").write_text(TEST, encoding="utf-8")
    commit(repo, "fix + test")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    rec = facts["verification"]["P-F-1"]
    assert rec["test_copied_from_head"] is True
    assert (rec["at_previous"], rec["at_head"]) == ("fail", "pass")
    assert merge(facts, resolved(), prev)["findings"][0]["fix_verified"] is True


# ── what is honestly not a verification ─────────────────────────────────────

def test_pass_at_both_commits_verifies_nothing(tmp_path):
    """The test did not demonstrate the defect — or the old source was not what
    ran. The harness cannot tell which, and does not pretend to."""
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "pkg.py").write_text(FIXED, encoding="utf-8")
    (r / "test_pkg.py").write_text(TEST, encoding="utf-8")
    sha_a = commit(r, "already fine")
    (r / "README").write_text("x\n", encoding="utf-8")
    commit(r, "later")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(r, qa, [], test_one_cmd=CMD)
    assert facts["verification"]["P-F-1"]["at_previous"] == "pass"
    f = merge(facts, resolved(), prev)["findings"][0]
    assert f["delta"] == "RESOLVED" and "fix_verified" not in f
    assert f["outcome"] == "unknown" and "absence is not proof" in f["outcome_reason"]


def test_a_setup_error_at_the_old_commit_never_reads_as_fail(tmp_path):
    """A collection error exits like a failure. Read as `fail`, it would mint a
    verification the code never earned — the one false positive this feature
    must not have."""
    # The fix adds the test *and* a helper it imports. Copied back to the old
    # commit the test cannot even be collected: that is an error, not a
    # failing assertion, and pytest exits 1 either way.
    repo, sha_a = bugged_repo(tmp_path, with_test=False)
    (repo / "test_pkg.py").write_text("import helper\n" + TEST, encoding="utf-8")
    (repo / "helper.py").write_text("", encoding="utf-8")
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    commit(repo, "fix + test + helper")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    rec = facts["verification"]["P-F-1"]
    assert rec["at_head"] == "pass" and rec["at_previous"] == "error", rec
    assert "fix_verified" not in merge(facts, resolved(), prev)["findings"][0]


def test_an_error_beside_a_failure_is_still_an_error(tmp_path):
    """The rule the pure-collection-error case cannot pin: a summary reading
    "1 failed, 1 error" must classify as `error`. The fix adds a fixture to
    conftest.py; the copied-back test file finds pkg (fails honestly) but not
    the fixture (errors). Read `failed` first and the old commit looks like a
    clean failure — and the fix looks verified."""
    repo, sha_a = bugged_repo(tmp_path, with_test=False)
    (repo / "conftest.py").write_text(
        "import pytest\n\n@pytest.fixture\ndef helper():\n    return 1\n", encoding="utf-8")
    (repo / "test_pkg.py").write_text(
        TEST + "\ndef test_with_fixture(helper):\n    assert helper == 1\n", encoding="utf-8")
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    commit(repo, "fix + fixture + tests")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD.replace("{id}", "test_pkg.py"))
    rec = facts["verification"]["P-F-1"]
    assert rec["at_head"] == "pass"
    assert rec["at_previous"] == "error", rec
    assert "fix_verified" not in merge(facts, resolved(), prev)["findings"][0]


def test_without_test_one_cmd_nothing_runs_and_the_note_says_how(tmp_path):
    repo, sha_a = bugged_repo(tmp_path)
    qa = tmp_path / "qa"
    previous_state(qa, sha_a)
    facts = collect(repo, qa, [])
    assert "verification" not in facts
    assert any("test_one_cmd" in n for n in facts["verification_notes"])


def test_a_missing_previous_commit_still_measures_head(tmp_path):
    """The squash-merged base of this repository's own run 3: gone from every
    clone. The counterfactual half is unavailable; the still-failing half
    still refuses a resolution."""
    repo, _ = bugged_repo(tmp_path)
    qa = tmp_path / "qa"
    prev = previous_state(qa, "deadbeef" * 5)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    rec = facts["verification"]["P-F-1"]
    assert rec["at_previous"] == "unavailable" and rec["at_head"] == "fail"
    assert any("not in this repository" in n for n in facts["verification_notes"])
    assert merge(facts, resolved(), prev)["findings"][0]["delta"] == "STILL_OPEN"


def test_verification_is_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(h, "VERIFY_MAX_FINDINGS", 2)
    repo, sha_a = bugged_repo(tmp_path)
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    prev["findings"] = [dict(prev["findings"][0], id=f"P-F-{i}", hash=f"h{i}") for i in range(1, 5)]
    (qa / "state.json").write_text(json.dumps(prev), encoding="utf-8")
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    assert len(facts["verification"]) == 2
    assert any("capped at 2 of 4" in n for n in facts["verification_notes"])


def test_the_old_source_is_put_ahead_of_any_installed_copy(tmp_path):
    repo, sha_a = bugged_repo(tmp_path)
    (repo / "src").mkdir()
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    commit(repo, "fix")
    qa = tmp_path / "qa"
    previous_state(qa, sha_a)
    rec = collect(repo, qa, [], test_one_cmd=CMD)["verification"]["P-F-1"]
    assert rec["pythonpath"] and all("verdict-verify-" in p for p in rec["pythonpath"])


def test_the_judgment_may_not_claim_a_verification():
    f = dict(judgment()["findings"][0], verification={"at_previous": "fail", "at_head": "pass"})
    bad = validate_judgment(judgment(findings=[f]))
    assert any("verification" in b and "verdict-finalize computes" in b for b in bad)


def test_cited_tests_reads_ids_not_line_references():
    f = {"verification_test": "tests/test_a.py::test_explicit",
         "evidence": ["tests/test_b.py::test_rate[west 7kg] fails.",
                      "src/x.py:12 the guard", "tests/test_b.py::test_rate[west 7kg]",
                      "see tests/test_c.py::TestK::test_m: assert 1 == 2"]}
    assert cited_tests(f) == ["tests/test_a.py::test_explicit",
                              "tests/test_b.py::test_rate[west 7kg]",
                              "tests/test_c.py::TestK::test_m"]


# ── a citation is only a citation if the collector reported it (F-26) ────────

OTHER = "def test_other():\n    assert True\n"


def _emit(lines):
    """A shell command printing these lines, on any platform — no backslash
    escapes, which a POSIX shell would eat before Python saw them."""
    body = "; ".join(f"print({line!r})" for line in lines)
    return f'"{sys.executable}" -c "{body}"'


def fixed_repo(tmp_path, **kw):
    repo, sha_a = bugged_repo(tmp_path, **kw)
    (repo / "pkg.py").write_text(FIXED, encoding="utf-8")
    commit(repo, "fix")
    return repo, sha_a


def test_a_node_id_scraped_from_prose_is_never_run(tmp_path):
    """VERDICT-F-26, live on run 5 of this repository: the regex matches a node
    id anywhere in evidence, including inside a quoted snippet, and the record
    for F-20 read `t.py::new` — a test that exists in no file here. It errored
    at both commits, and an error is not a measurement."""
    repo, sha_a = fixed_repo(tmp_path)
    qa = tmp_path / "qa"
    previous_state(qa, sha_a, evidence=("the old code called t.py::new",))
    facts = collect(repo, qa, [], test_ids_cmd=_emit(["test_pkg.py::test_pending"]),
                    test_one_cmd=CMD)
    assert "P-F-1" not in (facts.get("verification") or {})
    assert any("not in the collected id ledger" in n and "t.py::new" in n
               for n in facts["verification_notes"]), facts["verification_notes"]


def test_the_collected_citation_wins_over_the_scraped_one(tmp_path):
    """Selection was evidence ORDER — `tests[0]`, whatever it happened to be."""
    repo, sha_a = fixed_repo(tmp_path)
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a, evidence=("prose naming t.py::new first",
                                               "test_pkg.py::test_pending fails: assert 1 == 5"))
    facts = collect(repo, qa, [], test_ids_cmd=_emit(["test_pkg.py::test_pending"]),
                    test_one_cmd=CMD)
    rec = facts["verification"]["P-F-1"]
    assert rec["test"] == "test_pkg.py::test_pending"
    assert (rec["at_previous"], rec["at_head"]) == ("fail", "pass"), rec
    assert merge(facts, resolved(), prev)["findings"][0]["fix_verified"] is True


def test_without_a_ledger_a_citation_is_still_tried(tmp_path):
    """The filter is only as good as the ledger. A project with no
    `test_ids_cmd` has nothing to check against, and refusing to run there
    would turn a working verification off to fix a scraping bug."""
    repo, sha_a = fixed_repo(tmp_path)
    qa = tmp_path / "qa"
    previous_state(qa, sha_a, evidence=("the old code called t.py::new",))
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    assert facts["verification"]["P-F-1"]["test"] == "t.py::new"


def test_resolve_test_id_matches_the_collected_form_not_the_prose():
    known = {"tests/test_x.py::test_y", "tests/test_x.py::test_p[a]",
             "tests/test_x.py::test_p[b]", "tests/sub/test_z.py::test_q"}
    assert resolve_test_id("tests/test_x.py::test_y", known) == "tests/test_x.py::test_y"
    assert resolve_test_id("test_x.py::test_y", known) == "tests/test_x.py::test_y"
    assert resolve_test_id("tests\\test_x.py::test_y", known) == "tests/test_x.py::test_y"
    assert resolve_test_id("test_z.py::test_q", known) == "tests/sub/test_z.py::test_q"
    # a base id is what pytest expands over the parametrizations
    assert resolve_test_id("tests/test_x.py::test_p", known) == "tests/test_x.py::test_p"
    assert resolve_test_id("t.py::new", known) is None
    assert resolve_test_id("t.py::new", None) == "t.py::new"


# ── the new test meets the old source, appended or not (F-25) ────────────────

def test_a_regression_test_appended_to_an_existing_file_verifies(tmp_path):
    """VERDICT-F-25: the copy-back was file-level, so the commonest real shape
    — a regression test appended to a test file that already existed — left the
    old file in place. It does not contain the test, so at_previous read
    `error` and no fix could ever verify."""
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "pkg.py").write_text(BUGGY, encoding="utf-8")
    (r / "test_pkg.py").write_text(OTHER, encoding="utf-8")
    sha_a = commit(r, "bug, and a test file that already exists")
    (r / "pkg.py").write_text(FIXED, encoding="utf-8")
    (r / "test_pkg.py").write_text(OTHER + "\n" + TEST, encoding="utf-8")
    commit(r, "fix + appended regression test")
    qa = tmp_path / "qa"
    prev = previous_state(qa, sha_a)
    facts = collect(r, qa, [], test_ids_cmd=_emit(["test_pkg.py::test_pending"]),
                    test_one_cmd=CMD)
    rec = facts["verification"]["P-F-1"]
    assert rec["test_copied_from_head"] is True
    assert (rec["at_previous"], rec["at_head"]) == ("fail", "pass"), rec
    assert merge(facts, resolved(), prev)["findings"][0]["fix_verified"] is True


def test_a_test_file_the_fix_did_not_touch_is_not_reported_as_copied(tmp_path):
    """`test_copied_from_head` must keep meaning "the old commit did not have
    this test as written". Setting it unconditionally would make it noise."""
    repo, sha_a = fixed_repo(tmp_path)  # test_pkg.py is identical at both commits
    qa = tmp_path / "qa"
    previous_state(qa, sha_a)
    facts = collect(repo, qa, [], test_one_cmd=CMD)
    assert "test_copied_from_head" not in facts["verification"]["P-F-1"]


# ── the report counts the measurement, not the claim (F-30) ──────────────────

def _resolved_state(verification, **extra):
    return {"project": "p", "run_number": 2, "run_type": "delta", "verdict": "pass",
            "last_run": {"timestamp_utc": "2026-09-02T00:00:00Z"},
            "findings": [{"id": "P-F-1", "title": "t", "severity": "Major", "priority": "P1",
                          "status": "resolved", "delta": "RESOLVED",
                          "verification": verification, **extra}]}


def test_the_report_counts_the_measurement_not_the_claim():
    """VERDICT-F-30, live in run 5's own report: the block is selected by
    measurement and was counted by `fix_verified`, the one judgment field in
    it. A record measured error/error published as "1 verified", and the
    arithmetic then emptied the bucket that would have shown it."""
    claimed = _resolved_state({"test": "t.py::new", "at_previous": "error", "at_head": "error"},
                              fix_verified=True)
    text = render_report(claimed)
    assert "Fix verification: 0 verified" in text
    assert "1 measured but not verifiable" in text
    assert "claims fix_verified the measurement does not show: P-F-1" in text


def test_a_measured_fix_still_reads_as_verified():
    measured = _resolved_state({"test": "t.py::a", "at_previous": "fail", "at_head": "pass"},
                               fix_verified=True)
    text = render_report(measured)
    assert "Fix verification: 1 verified" in text
    assert "0 measured but not verifiable" in text
    assert "claims fix_verified" not in text
