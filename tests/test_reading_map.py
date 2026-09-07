"""The reading map (T-16) and the verification candidates (T-18): one coverage
run, two facts the tester used to derive by hand.

Boltons runs 2–4 produced 13 of 15 top findings from the six lowest-coverage
modules, re-deriving the ranking from the coverage JSON on every run; and
`verification_test` was declared on 0 of 30 findings because nobody searched
for the test that executes a cited line. Both come from the coverage.py run
the harness already makes — now on every run that names a coverage command,
a baseline included. Every test here runs a real suite under coverage.
"""

import json
import subprocess
import sys

from conftest import judgment
from verdict_mcp.harness import collect, finalize_main, merge, render_report
from verdict_mcp.validate import validate_judgment

CMD = f'"{sys.executable}" -m coverage run -m pytest -q -p no:cacheprovider'
WELL = "def a(x):\n    return x + 1\n\n\ndef b(x):\n    return x - 1\n"
POORLY = "def c(x):\n    if x:\n        return 1\n    return 2\n\n\ndef d(x):\n    return x * 2\n"
TESTS = ("from well import a, b\n\ndef test_a():\n    assert a(1) == 2\n\n\n"
         "def test_b():\n    assert b(1) == 0\n")


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def project(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "well.py").write_bytes(WELL.encode())
    (r / "poorly.py").write_bytes(POORLY.encode())
    (r / "test_well.py").write_bytes(TESTS.encode())
    git(r, "add", "-A")
    git(r, "commit", "-qm", "base")
    qa = tmp_path / "qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "reports" / "r.md").write_text("# r", encoding="utf-8")
    return r, qa


def finding(**over):
    f = {"id": "P-F-1", "title": "a is off by one", "severity": "Major", "priority": "P1",
         "status": "open", "failure_classification": "REAL_DEFECT", "confidence": "proven",
         "evidence": ["well.py:2 — `return x + 1`"]}
    f.update(over)
    return f


def test_a_baseline_measures_the_map_least_covered_first_and_test_files_apart(tmp_path):
    r, qa = project(tmp_path)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    assert facts["coverage"]["status"] == "unavailable", "a baseline has no range for diff coverage"
    rm = facts["reading_map"]
    assert rm["status"] == "measured" and rm["modules"] == 2
    assert [m["path"] for m in rm["lowest"]] == ["poorly.py", "well.py"], "ascending by coverage"
    poorly, well = rm["lowest"]
    assert poorly["percent"] == 0 and poorly["never_imported"] is True, \
        "coverage never saw poorly.py — nothing imports it — and that is the first thing to read"
    assert poorly["open_findings"] == 0 and poorly["last_cited_run"] is None
    assert well["percent"] == 100 and well["statements"] == 4
    assert rm["never_examined"] == ["poorly.py", "well.py"], "no finding cites anything yet"
    assert "test_well.py" not in json.dumps(rm["lowest"]), "a test file is not a module to read"
    assert rm["overall_percent"] is not None and rm["findings_by_module"] == {}
    assert "verification_candidates" not in facts


def test_the_map_names_the_findings_that_cite_each_module(tmp_path):
    r, qa = project(tmp_path)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    (qa / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (qa / "judgment.json").write_text(json.dumps(judgment(findings=[finding()])), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    rm = facts["reading_map"]
    well = next(m for m in rm["lowest"] if m["path"] == "well.py")
    assert well["open_findings"] == 1 and well["last_cited_run"] == 1
    assert rm["findings_by_module"] == {"well.py": {"open": 1, "ids": ["P-F-1"], "last_cited_run": 1}}
    assert rm["never_examined"] == ["poorly.py"], "the cited module leaves the never-examined list"


def test_candidates_are_the_tests_whose_contexts_executed_the_cited_lines(tmp_path):
    r, qa = project(tmp_path)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    (qa / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (qa / "judgment.json").write_text(json.dumps(judgment(findings=[
        finding(), finding(id="P-F-2", title="d doubles", evidence=["poorly.py:8 — `return x * 2`"]),
        finding(id="P-F-3", title="b is off by one", evidence=["well.py:6 — `return x - 1`"])])),
        encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    cands = facts["verification_candidates"]
    assert cands["P-F-1"]["tests"] == ["test_well.py::test_a"], "the test that executed line 2, not any test of the file"
    assert cands["P-F-3"]["tests"] == ["test_well.py::test_b"]
    assert cands["P-F-1"]["lines_covered"] == {"test_well.py::test_a": 1}
    assert cands["P-F-1"]["source"] == "coverage contexts"
    assert "P-F-2" not in cands, "no test executed poorly.py:8 — no candidate is invented"
    # finalize puts the list on the finding, and the report says where it came from
    (qa / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    state = merge(facts, judgment(findings=[finding(), finding(id="P-F-2", title="d doubles",
                                                            evidence=["poorly.py:8 — `return x * 2`"])]),
                  json.loads((qa / "state.json").read_text(encoding="utf-8")))
    by_id = {f["id"]: f for f in state["findings"]}
    assert by_id["P-F-1"]["candidate_tests"] == ["test_well.py::test_a"]
    assert "candidate_tests" not in by_id["P-F-2"]
    report = render_report(state)
    assert ("- Never measured — no `verification_test` declared — coverage says these tests "
            "execute its cited lines: `test_well.py::test_a`") in report
    assert "## Reading map (2 production modules" in report
    assert "| `poorly.py` | 0% | None | 1 | run 1 |" in report
    assert "Never cited by any finding" not in report, "both modules are cited now"
    assert state["reading_map"]["status"] == "measured"


def test_a_finding_that_declares_its_test_gets_no_candidates_line_and_a_judgment_may_not_write_them():
    bad = validate_judgment(judgment(findings=[finding(candidate_tests=["x"])]))
    assert len(bad) == 1 and "candidate_tests" in bad[0]
