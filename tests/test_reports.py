"""Structured test results before summary dialects (T-14).

A gate command may carry `{report}`; the harness renders it to a scratch
path, runs the gate, and reads what it wrote — JUnit XML or CTRF JSON — for
exact counts, per-test durations, the failures with their messages and the
ids. The dialects stay as the fallback that says it is a fallback.
"""

import json
import sys

from verdict_mcp.harness import collect
from verdict_mcp.reports import read_report

JUNIT = ('<testsuites><testsuite name="pytest" tests="3">'
         '<testcase classname="tests.test_money" name="test_a" time="0.01"/>'
         '<testcase classname="tests.test_money" name="test_b" time="0.5">'
         '<failure message="assert 100 == 101">trace</failure></testcase>'
         '<testcase classname="tests.test_money" name="test_c" time="0"><skipped/></testcase>'
         '</testsuite></testsuites>')
CTRF = json.dumps({"results": {"tool": {"name": "vitest"}, "summary": {"tests": 2}, "tests": [
    {"name": "adds", "status": "passed", "duration": 12, "filePath": "test/a.test.ts"},
    {"name": "fails", "status": "failed", "duration": 3, "filePath": "test/a.test.ts",
     "message": "expected 1 to be 2"}]}})


def writer(text: str) -> str:
    """A gate that writes `text` to the path it is given, then prints a summary
    line the dialects would misread, and exits 0."""
    script = f"import sys; open(sys.argv[1], 'w').write({text!r}); print('1 passed in 0.1s')"
    return f'"{sys.executable}" -c "{script.replace(chr(34), chr(92) + chr(34))}" {{report}}'


def test_a_junit_report_outranks_the_summary_line_and_feeds_the_ledger(repo, qa_root):
    facts = collect(repo, qa_root, [("suite", writer(JUNIT))])
    g = facts["gates"]["suite"]
    assert g["counts_dialect"] == "report/junit"
    assert g["counts"] == {"passed": 1, "failed": 1, "skipped": 1, "errors": 0, "collected": 3}
    assert g["report"]["failures"] == [{"id": "tests.test_money::test_b", "kind": "failure",
                                        "message": "assert 100 == 101"}]
    assert g["report"]["slowest"][0] == {"id": "tests.test_money::test_b", "duration_s": 0.5}
    assert g["command"].endswith("{report}"), "the recorded command keeps the placeholder"
    assert facts["tests"]["collected"] == 3 and facts["tests"]["failed"] == 1
    ids = facts["test_ids"]
    assert ids["status"] == "measured" and ids["count"] == 3 and "report" in ids["ids_from"]
    assert "not pytest node ids" in ids["ids_from"]
    assert facts["_test_ids"][0] == "tests.test_money::test_a", "the ledger facts_main writes"


def test_a_ctrf_report_is_read_the_same_way(repo, qa_root):
    g = collect(repo, qa_root, [("vitest", writer(CTRF))])["gates"]["vitest"]
    assert g["counts_dialect"] == "report/ctrf" and g["report"]["tool"] == "vitest"
    assert g["counts"]["collected"] == 2 and g["counts"]["failed"] == 1
    assert g["report"]["failures"][0]["message"] == "expected 1 to be 2"


def test_an_unwritten_report_falls_back_to_the_dialect_and_says_so(repo, qa_root):
    cmd = f'"{sys.executable}" -c "print(\'1 passed in 0.1s\')" {{report}}'
    g = collect(repo, qa_root, [("suite", cmd)])["gates"]["suite"]
    assert g["report"]["status"] == "missing" and "report flag" in g["report"]["reason"]
    assert g["counts"]["passed"] == 1 and g["counts_dialect"] != "report/junit"


def test_an_explicit_id_command_outranks_the_reports_ids(repo, qa_root):
    facts = collect(repo, qa_root, [("suite", writer(JUNIT))],
                    test_ids_cmd=f'"{sys.executable}" -c "print(\'tests/test_money.py::test_a\')"')
    assert facts["test_ids"]["count"] == 1 and "ids_from" not in facts["test_ids"]


def test_the_reader_names_what_it_cannot_read(tmp_path):
    bad = tmp_path / "r.xml"
    bad.write_text("<testsuites", encoding="utf-8")
    assert read_report(bad)[0]["status"] == "unreadable"
    (tmp_path / "r.json").write_text('{"nope": 1}', encoding="utf-8")
    assert "results.tests" in read_report(tmp_path / "r.json")[0]["reason"]
    assert read_report(tmp_path / "absent")[0]["status"] == "missing"
    junit_with_file = tmp_path / "f.xml"
    junit_with_file.write_text('<testsuite><testcase file="tests/test_a.py" classname="x" name="t" time="1"/></testsuite>',
                               encoding="utf-8")
    summary, ids = read_report(junit_with_file)
    assert ids == ["tests/test_a.py::t"] and summary["id_shape"] == "file::name"
