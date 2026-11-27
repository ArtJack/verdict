"""What the skip scan filed, the skip scan settles (`local_skip_close.py`).

A finding the regular expression filed has no test that fails at the previous commit and
passes at HEAD, so `local_carry` could never close one. Verdict's own record carried nine of
them for three runs after the scan stopped filing them. These tests hold the rule that
replaced that: withdrawn when the scan reads the same lines and files nothing, resolved when
the lines changed or the file is gone, and left exactly where it was on anything the run did
not measure — a file it did not read, a red gate, a ledger it did not refresh, a
`pytest.skip()` call that can hide its own file from collection.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verdict_mcp import local_skip_close as close  # noqa: E402
from verdict_mcp import small  # noqa: E402
from verdict_mcp.local_skips import SCAN_EVIDENCE, skip_finding, skips_without_expiry  # noqa: E402
from verdict_mcp.local_suite import focus_finding  # noqa: E402
from verdict_mcp.validate import validate_finding  # noqa: E402
from test_local_delta import GATE, IDS, PY, SKIPPED, delta, git, state_of  # noqa: E402

# A guard written as a call: the scan before 2026-10-16 filed it; the scan now passes it.
GUARD = ("import shutil\nimport pytest\n\n\ndef test_tool():\n"
         "    if not shutil.which(\"no-such-tool-anywhere\"):\n"
         "        pytest.skip(\"no tool here\")\n"
         "    assert True\n")
# A seeded skip in a fixture the suite never collects (eval/fixtures/pricer, in this repo).
SEEDED = ("import pytest\n\n\n@pytest.mark.skip(reason=\"temporarily disabled 2026-05-02 - flaky?\")\n"
          "def test_seeded():\n    assert False\n")
# A module-level skip call: pytest collects nothing from this file, so it is absent from the
# ledger for a reason that is not the suite's shape.
MODULE_SKIP = ("import pytest\n\npytest.skip(\"disabled until staging is back\", "
               "allow_module_level=True)\n\n\ndef test_flow():\n    assert True\n")
CITED = "def rate(weight):\n    return weight * 2\n"
TEST = "from cited import rate\n\n\ndef test_rate():\n    assert rate(2) == 4\n"


def scan_filed(path, line, reason, ident):
    """A finding in exactly the shape the scan files it."""
    return skip_finding({"path": path, "line": line, "reason": reason}, ident)


def project(tmp_path, files, findings, ids_cmd=IDS):
    """A repo at run 1 with `files`, finalized through the real harness with `findings`, so
    every finding carries the anchors verdict-facts re-measures on the next run."""
    repo = tmp_path / "Proj"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    for rel, text in {"cited.py": CITED, "other.py": "def other(x):\n    return x\n",
                      "test_cited.py": TEST,
                      "conftest.py": "collect_ignore_glob = [\"fixtures/*\"]\n", **files}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    qa = tmp_path / "qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: {GATE}\ntest_ids_cmd: {ids_cmd}\n---\n\n"
        "# QA Profile — proj\n\nProject-Key: proj\n", encoding="utf-8")
    from verdict_mcp.harness import facts_main, finalize_main
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    judgment = {"topic": "baseline", "verdict": "pass with risks",
                "isolation_check": {"result": "pass"}, "release_blockers": [],
                "not_tested": ["concurrency"], "findings": findings}
    (qa / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    return repo, qa


def night(repo, message="night two"):
    (repo / "other.py").write_text(f"def other(x):\n    return x  # {message}\n", encoding="utf-8")
    git(repo, "commit", "-qam", message)


def by_id(qa):
    return {f["id"]: f for f in state_of(qa)["findings"]}


FILED = [scan_filed("test_guard.py", 7, '"no tool here"', "PROJ-F-1"),
         scan_filed("fixtures/test_seeded.py", 4,
                    'reason="temporarily disabled 2026-05-02 - flaky?"', "PROJ-F-2"),
         scan_filed("integration/test_all.py", 3,
                    '"disabled until staging is back", allow_module_level=True', "PROJ-F-3")]
FILES = {"test_guard.py": GUARD, "fixtures/test_seeded.py": SEEDED,
         "integration/test_all.py": MODULE_SKIP}


# ── a whole run ───────────────────────────────────────────────────────────────

def test_what_the_scan_no_longer_files_is_withdrawn_and_a_module_skip_stays_open(tmp_path):
    """The three shapes Verdict's own record carried, on one night. The guard the scan now
    reads past and the fixture the suite never collects are withdrawn — refuted, on the
    record. The module-level skip call is absent from the ledger for a reason that is not the
    suite's shape, so nothing is concluded from that absence, and it stays open."""
    repo, qa = project(tmp_path, FILES, FILED)
    night(repo)
    assert delta(repo, qa) == 0
    found = by_id(qa)
    for fid in ("PROJ-F-1", "PROJ-F-2"):
        assert (found[fid]["status"], found[fid]["delta"], found[fid]["outcome"]) == (
            "withdrawn", "WITHDRAWN", "refuted"), fid
        assert found[fid]["evidence"][-1].startswith("withdrawn by the skip scan")
    assert "the suite collects nothing" in found["PROJ-F-2"]["evidence"][-1]
    assert (found["PROJ-F-3"]["status"], found["PROJ-F-3"]["delta"]) == ("open", "STILL_OPEN")
    judgment = json.loads((qa / "judgment.json").read_text(encoding="utf-8"))
    assert judgment["still_open"] == ["PROJ-F-3"]
    assert "withdrawn PROJ-F-1, PROJ-F-2" in judgment["prose"]["notes"]


def test_a_withdrawal_stays_withdrawn_on_the_next_night(tmp_path):
    """A withdrawal is a record, not a state the next run re-litigates: night three neither
    reopens it nor loses it."""
    repo, qa = project(tmp_path, FILES, FILED)
    night(repo)
    assert delta(repo, qa) == 0
    night(repo, "night three")
    assert delta(repo, qa) == 0
    found = by_id(qa)
    assert found["PROJ-F-1"]["status"] == "withdrawn" and found["PROJ-F-1"]["outcome"] == "refuted"


def test_a_cited_line_that_changed_and_is_not_filed_again_is_resolved_not_withdrawn(tmp_path):
    """Somebody gave the skip an expiry. The code moved under the finding, so it is gone by
    measurement — resolved, outcome unknown — and not the rule's error."""
    filed = [scan_filed("test_skip.py", 4, 'reason="the fixture file is not in the repo"',
                        "PROJ-F-1")]
    repo, qa = project(tmp_path, {"test_skip.py": SKIPPED}, filed)
    (repo / "test_skip.py").write_text(SKIPPED.replace(
        'reason="the fixture', 'reason="until 2099-01-01: the fixture'), encoding="utf-8")
    git(repo, "commit", "-qam", "an expiry on the skip")
    assert delta(repo, qa) == 0
    found = by_id(qa)["PROJ-F-1"]
    assert (found["status"], found["delta"], found["outcome"]) == ("resolved", "RESOLVED", "unknown")
    assert found["evidence"][-1].startswith("resolved by the skip scan")


def test_a_skip_still_filed_stays_open(tmp_path):
    """The scan finds the same marker at the same line: nothing is settled."""
    filed = [scan_filed("test_skip.py", 4, 'reason="the fixture file is not in the repo"',
                        "PROJ-F-1")]
    repo, qa = project(tmp_path, {"test_skip.py": SKIPPED}, filed)
    night(repo)
    assert delta(repo, qa) == 0
    assert by_id(qa)["PROJ-F-1"]["status"] == "open"


def test_a_cited_file_that_is_gone_is_resolved(tmp_path):
    filed = [scan_filed("test_skip.py", 4, 'reason="the fixture file is not in the repo"',
                        "PROJ-F-1")]
    repo, qa = project(tmp_path, {"test_skip.py": SKIPPED}, filed)
    git(repo, "rm", "-q", "test_skip.py")
    git(repo, "commit", "-qm", "the skipped test is deleted")
    assert delta(repo, qa) == 0
    found = by_id(qa)["PROJ-F-1"]
    assert (found["status"], found["outcome"]) == ("resolved", "unknown")
    assert "no longer in the checkout" in found["evidence"][-1]


def test_outside_the_suite_needs_every_gate_green(tmp_path):
    """A red suite may be a collection that broke: an absence from the ledger then says
    nothing about the suite's shape."""
    repo, qa = project(tmp_path, FILES, FILED)
    (repo / "test_red.py").write_text("def test_red():\n    assert False\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a red test")
    delta(repo, qa)
    assert by_id(qa)["PROJ-F-2"]["status"] == "open"


def test_outside_the_suite_needs_a_ledger_this_run_measured(tmp_path):
    """The id command printed nothing this run, so the ledger is last run's: carried."""
    repo, qa = project(tmp_path, FILES, FILED)
    profile = (qa / "profile.md").read_text(encoding="utf-8")
    (qa / "profile.md").write_text(profile.replace(IDS, f"{PY} -c pass"), encoding="utf-8")
    night(repo)
    assert delta(repo, qa) == 0
    found = by_id(qa)
    assert found["PROJ-F-2"]["status"] == "open"
    assert found["PROJ-F-1"]["status"] == "withdrawn", "read again: no ledger needed for that"


# ── the rule, piece by piece ──────────────────────────────────────────────────

def test_both_finders_carry_the_line_the_scan_is_known_by():
    skip = skip_finding({"path": "t.py", "line": 3, "reason": '"x"'}, "P-F-1")
    focus = focus_finding({"path": "a.test.ts", "line": 2, "reason": "it.only('x')"}, "P-F-2")
    assert SCAN_EVIDENCE in skip["evidence"] and SCAN_EVIDENCE in focus["evidence"]
    assert close.cited_sites(skip) == [("t.py", 3)]
    assert close.cited_sites(focus) == [("a.test.ts", 2)]


def test_a_finding_the_scan_did_not_file_is_never_its_to_settle():
    model_read = {"id": "P-F-1", "status": "open", "evidence": ["t.py:3 — skip marker with reason"]}
    assert close.cited_sites(model_read) == []


def test_a_file_the_scan_could_not_open_is_not_a_file_it_read(tmp_path):
    (tmp_path / "test_a.py").write_text("def test_a():\n    pass\n", encoding="utf-8")
    read: set = set()
    skips_without_expiry(tmp_path, ["test_a.py", "test_missing.py"], read=read)
    assert read == {"test_a.py"}


def test_a_line_moved_by_an_edit_elsewhere_and_found_there_again_stays_open(tmp_path):
    """The anchor says the cited line now sits at line 6; the scan files a skip at 6."""
    (tmp_path / "test_s.py").write_text("import pytest\n\n\n\n\n@pytest.mark.skip(reason=\"later\")\n"
                                        "def test_s():\n    pass\n", encoding="utf-8")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "test-ids.txt").write_text("test_s.py::test_s\n", encoding="utf-8")
    scan = close.SkipScan(tmp_path, tmp_path / "qa")
    assert ("test_s.py", 6) in scan.hits()
    prior = {"findings": [scan_filed("test_s.py", 4, "", "P-F-1")]}
    facts = {"evidence_drift": {"findings": {"P-F-1": {"drift": "moved", "refs": [
        {"ref": "test_s.py:4", "status": "moved", "now_line": 6}]}}}}
    assert close.settled_by_scan(prior, scan, facts, tmp_path, tmp_path / "qa", set()) == []


def test_a_directory_the_suite_collects_from_is_never_outside_it(tmp_path):
    """`tests/test_b.py` is absent from the ledger while `tests/test_a.py` is in it: whatever
    kept test_b out — a module-level skip, an import that failed quietly — it is not that
    the suite does not look in `tests/`, so nothing is withdrawn."""
    for rel in ("tests/test_a.py", "tests/test_b.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(SEEDED, encoding="utf-8")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "test-ids.txt").write_text("tests/test_a.py::test_seeded\n",
                                                  encoding="utf-8")
    scan = close.SkipScan(tmp_path, tmp_path / "qa")
    prior = {"findings": [scan_filed("tests/test_b.py", 4, "x", "P-F-1")]}
    facts = {"test_ids": {"status": "measured"}, "gates": {"suite": {"result": "pass"}},
             "evidence_drift": {"findings": {"P-F-1": {"drift": "unchanged", "refs": [
                 {"ref": "tests/test_b.py:4", "status": "unchanged"}]}}}}
    assert close.settled_by_scan(prior, scan, facts, tmp_path, tmp_path / "qa", set()) == []
    (tmp_path / "qa" / "test-ids.txt").write_text("elsewhere/test_c.py::test_c\n",
                                                  encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "test_c.py").write_text(TEST, encoding="utf-8")
    scan = close.SkipScan(tmp_path, tmp_path / "qa")
    assert [s for _f, s, _n in close.settled_by_scan(
        prior, scan, facts, tmp_path, tmp_path / "qa", set())] == ["withdrawn"], \
        "the control: with nothing collected under tests/, the same finding is outside"


def test_outside_the_suite_is_a_pytest_question_only(tmp_path):
    """The ledger is pytest's collection. A JUnit file it does not list is not outside the
    suite, it is outside the ledger — even with `@Disabled` on the cited line, a decorator."""
    (tmp_path / "java" / "src").mkdir(parents=True)
    (tmp_path / "java" / "src" / "CartTest.java").write_text(
        "class CartTest {\n  @Disabled\n  void total() {}\n}\n", encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "test_c.py").write_text(TEST, encoding="utf-8")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "test-ids.txt").write_text("elsewhere/test_c.py::test_rate\n",
                                                  encoding="utf-8")
    scan = close.SkipScan(tmp_path, tmp_path / "qa")
    prior = {"findings": [scan_filed("java/src/CartTest.java", 2, "@Disabled", "P-F-1")]}
    facts = {"test_ids": {"status": "measured"}, "gates": {"suite": {"result": "pass"}},
             "evidence_drift": {"findings": {"P-F-1": {"drift": "unchanged", "refs": [
                 {"ref": "java/src/CartTest.java:2", "status": "unchanged"}]}}}}
    assert "java/src/CartTest.java" not in scan.read, "not tracked by git, so the scan did not read it"
    assert close.settled_by_scan(prior, scan, facts, tmp_path, tmp_path / "qa", set()) == []


def test_only_unchanged_or_moved_lines_are_as_they_were():
    refs = {"t.py:1": {"status": "unchanged"}, "t.py:2": {"status": "moved", "now_line": 9},
            "t.py:3": {"status": "changed"}, "t.py:4": {"status": "missing"}}
    assert [close._now(("t.py", n), refs) for n in (1, 2, 3, 4, 5)] == [
        ("t.py", 1), ("t.py", 9), None, None, None]


def test_a_closure_the_validator_refuses_leaves_the_id_where_it_was(tmp_path):
    """`file` is the run's `mint`, which writes nothing for an entry the validator refuses:
    the id must then still be carried, or the carry invariant stops the run."""
    (tmp_path / "test_g.py").write_text(GUARD, encoding="utf-8")
    (tmp_path / "qa").mkdir()
    (tmp_path / "qa" / "test-ids.txt").write_text("test_g.py::test_tool\n", encoding="utf-8")
    scan = close.SkipScan(tmp_path, tmp_path / "qa")
    prior = {"findings": [scan_filed("test_g.py", 7, '"no tool here"', "P-F-1")]}
    facts = {"evidence_drift": {"findings": {"P-F-1": {"drift": "unchanged", "refs": [
        {"ref": "test_g.py:7", "status": "unchanged"}]}}}}
    still_open, to_refile = ["P-F-1"], []
    refused = close.close_by_scan(prior, scan, facts, tmp_path, tmp_path / "qa", [], still_open,
                                  to_refile, lambda entry, into: None)
    assert refused == [] and still_open == ["P-F-1"]
    written = close.close_by_scan(prior, scan, facts, tmp_path, tmp_path / "qa", [], still_open,
                                  to_refile, lambda entry, into: into.append(entry))
    assert [f["id"] for f in written] == ["P-F-1"] and still_open == []


def test_a_closed_finding_passes_the_finding_validator():
    prior = scan_filed("t.py", 3, '"x"', "P-F-1")
    for status in ("withdrawn", "resolved"):
        entry = close.closed_finding(prior, status, f"{status} by the skip scan: measured")
        assert validate_finding(entry, "findings/P-F-1.json", {"P-F-1"}) == []
        assert entry["evidence"][:-1] == prior["evidence"], "what the scan wrote is kept"
    assert close.closed_finding(prior, "withdrawn", "n")["delta"] == "WITHDRAWN"
    assert "delta" not in close.closed_finding(prior, "resolved", "n")


def test_small_still_exports_the_scan_its_tests_call():
    assert small.skips_without_expiry is skips_without_expiry
