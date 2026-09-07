"""Findings as files (H-2), the two cheap verbs, and one class per finding.

The judgment was one JSON written from memory at the end of the run — boltons
paused 3:32 to write 39,500 characters, a third of them eight findings re-typed
to say "still there". A finding is now a file written when it is proven and
validated when it is written; `still_open` and `resolved` carry a finding by
id; finalize assembles, and refuses a carry whose cited code changed (T-1) or a
second finding filed inside another finding's class.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from conftest import git, judgment
from verdict_mcp.filed import archive_findings, load_filed
from verdict_mcp.harness import facts_main, finalize_main
from verdict_mcp.validate import class_conflicts, validate_judgment

SRC = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"
THREE = b"x = 1\ny = 2\nz = 3\n"


NAMES = ("nil", "alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india")


def finding(fid="W-F-1", **over):
    # titles differ in letters, not digits: the identity hash strips line numbers
    n = int(fid.rsplit("-", 1)[1])
    f = {"id": fid, "title": f"defect {NAMES[n % len(NAMES)]} in a.py", "severity": "Major", "priority": "P1",
         "status": "open", "failure_classification": "REAL_DEFECT", "confidence": "proven",
         "evidence": ["a.py:2 — `y = 2` is the guard"]}
    f.update(over)
    return f


def three_lines(repo):
    (repo / "a.py").write_bytes(THREE)
    git(["commit", "-qam", "three lines"], repo)


def write_finding(qa_root, f, age_s=0):
    d = qa_root / "findings"
    d.mkdir(exist_ok=True)
    path = d / f"{f['id']}.json"
    path.write_text(json.dumps(f), encoding="utf-8")
    if age_s:
        stamp = time.time() - age_s
        os.utime(path, (stamp, stamp))
    return path


def run_facts(repo, qa_root):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    return json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))


def run_finalize(qa_root, j):
    (qa_root / "judgment.json").write_text(json.dumps(j), encoding="utf-8")
    rc = finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")])
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8")) \
        if (qa_root / "state.json").is_file() else None
    return rc, state


def hook(path):
    proc = subprocess.run([sys.executable, str(SRC / "validate.py")],
                          input=json.dumps({"tool_name": "Write",
                                            "tool_input": {"file_path": str(path)}}),
                          capture_output=True, text=True, encoding="utf-8")
    return proc.returncode, proc.stderr


# ── files ──────────────────────────────────────────────────────────────────

def test_finding_files_are_assembled_oldest_first_stamped_and_rendered(repo, qa_root, capsys):
    three_lines(repo)
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-2", narrative="Proven by counterfactual, not by reading."),
                  age_s=120)
    write_finding(qa_root, finding("W-F-1"))
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    assert [f["id"] for f in state["findings"]] == ["W-F-2", "W-F-1"], "oldest file first"
    for f in state["findings"]:
        assert f["filed_at"].endswith("Z") and f["delta"] == "NEW" and "narrative" not in f
    assert state["findings"][0]["filed_at"] < state["findings"][1]["filed_at"]
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "Proven by counterfactual, not by reading." in report
    assert not (qa_root / "run-in-progress.json").exists()


def test_files_and_inline_findings_together_are_refused(repo, qa_root, capsys):
    three_lines(repo)
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-1"))
    rc, state = run_finalize(qa_root, judgment(findings=[finding("W-F-2")]))
    assert rc == 1 and state is None
    assert "never both" in capsys.readouterr().err


def test_a_finding_file_is_validated_the_moment_it_is_written(repo, qa_root):
    three_lines(repo)
    run_facts(repo, qa_root)
    good = write_finding(qa_root, finding("W-F-1"))
    assert hook(good) == (0, "")
    bad = qa_root / "findings" / "W-F-2.json"          # the filename says W-F-2, the id says W-F-3
    bad.write_text(json.dumps({**finding("W-F-3"), "severity": "Huge", "hash": "x",
                               "evidence": []}), encoding="utf-8")
    rc, err = hook(bad)
    assert rc == 2
    assert "the finding you just wrote violates the contract" in err
    assert "filename says 'W-F-2'" in err and "severity 'Huge'" in err
    assert "sets hash" in err and "open with no evidence" in err
    # the same content anywhere else is not a finding file: the hook stays out of it
    elsewhere = qa_root / "W-F-2.json"
    elsewhere.write_text(bad.read_text(encoding="utf-8"), encoding="utf-8")
    assert hook(elsewhere) == (0, "")


def test_a_verification_test_must_be_a_collected_id(repo, qa_root):
    """P-24: a run wrote "none — no test in tests/x.py::y covers this" into the
    field and the harness read it as a citation it could not find."""
    three_lines(repo)
    run_facts(repo, qa_root)
    (qa_root / "test-ids.txt").write_text("tests/test_a.py::test_y\n", encoding="utf-8")
    prose = write_finding(qa_root, finding("W-F-1", verification_test="none — no test covers this"))
    rc, err = hook(prose)
    assert rc == 2 and "is not a collected test id" in err and "no test guards this" in err
    real = write_finding(qa_root, finding("W-F-1", verification_test="tests/test_a.py::test_y"))
    assert hook(real) == (0, "")
    # without a ledger there is nothing to check against, and nothing is refused
    (qa_root / "test-ids.txt").unlink()
    assert hook(prose) == (0, "")


def test_load_filed_names_what_it_cannot_read(qa_root):
    d = qa_root / "findings"
    d.mkdir()
    (d / "W-F-1.json").write_text("{not json", encoding="utf-8")
    (d / "W-F-2.json").write_text(json.dumps({"id": "W-F-9"}), encoding="utf-8")
    (d / "notes.json").write_text("{}", encoding="utf-8")
    found, problems = load_filed(qa_root)
    assert found == []
    assert any("unreadable" in p for p in problems)
    assert any("carries id 'W-F-9', but the filename says 'W-F-2'" in p for p in problems)
    assert any("notes.json" in p and "must be" in p for p in problems)


def test_a_judgment_may_not_write_the_filed_fields():
    bad = validate_judgment(judgment(findings=[finding(filed_at="x", re_reported="still_open")]))
    assert len(bad) == 1 and "filed_at, re_reported" in bad[0]


# ── the verbs ──────────────────────────────────────────────────────────────

def test_the_verbs_carry_a_finding_by_id_with_its_evidence_as_filed(repo, qa_root, capsys):
    three_lines(repo)
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-1"))
    write_finding(qa_root, finding("W-F-2", evidence=["a.py:3 — z"]))
    rc, first = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    anchors_then = {f["id"]: f["anchors"] for f in first["findings"]}

    run_facts(repo, qa_root)
    rc, state = run_finalize(qa_root, judgment(findings=[], still_open=["W-F-1"],
                                               resolved=["W-F-2"]))
    assert rc == 0, capsys.readouterr().err
    by_id = {f["id"]: f for f in state["findings"]}
    f1, f2 = by_id["W-F-1"], by_id["W-F-2"]
    assert f1["delta"] == "STILL_OPEN" and f1["re_reported"] == "still_open"
    assert f1["evidence"] == finding("W-F-1")["evidence"], "carried verbatim"
    assert f1["anchors"] == anchors_then["W-F-1"] and f1["anchored_at_run"] == 1
    assert f1["age_days"] == 0 and "filed_at" not in f1
    assert f2["delta"] == "RESOLVED" and f2["re_reported"] == "resolved"
    assert f2["outcome"] == "unknown" and "absence is not proof" in f2["outcome_reason"]
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "Re-reported by id (`still_open`): looked at, still there" in report
    assert "Re-reported by id (`resolved`): looked at, gone" in report


def test_the_verbs_refuse_what_they_cannot_carry():
    previous = {"findings": [{"id": "W-F-1", "status": "open"},
                             {"id": "W-F-2", "status": "accepted"},
                             {"id": "W-F-3", "status": "resolved"}]}
    j = judgment(findings=[finding("W-F-1")], still_open=["W-F-1", "W-F-2", "W-F-3", "W-F-9"],
                 resolved=["W-F-1"])
    bad = "\n".join(validate_judgment(j, previous))
    assert "W-F-1 is in still_open and filed as a finding" in bad
    assert "'W-F-2', an accepted risk" in bad
    assert "'W-F-3', which the previous state already has as resolved" in bad
    assert "'W-F-9', which is not in the previous state" in bad
    assert "W-F-1 is in both still_open and resolved" in bad
    assert "must be a list of finding ids" in "\n".join(
        validate_judgment(judgment(findings=[], still_open="W-F-1"), previous))


def test_still_open_is_refused_where_the_cited_code_changed_and_allowed_where_it_moved(
        repo, qa_root, capsys):
    three_lines(repo)
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-1"))
    rc, _ = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err

    # the cited line moved: the carry is allowed, and the report says where it went
    (repo / "a.py").write_bytes(b"w = 0\n" + THREE)
    git(["commit", "-qam", "insert"], repo)
    run_facts(repo, qa_root)
    rc, state = run_finalize(qa_root, judgment(findings=[], still_open=["W-F-1"]))
    assert rc == 0, capsys.readouterr().err
    assert state["evidence_drift"]["findings"]["W-F-1"]["drift"] == "moved"

    # the cited line itself rewritten: the word "still there" is not available
    (repo / "a.py").write_bytes(b"w = 0\nx = 1\ny = 22\nz = 3\n")
    git(["commit", "-qam", "change"], repo)
    run_facts(repo, qa_root)
    rc, _ = run_finalize(qa_root, judgment(findings=[], still_open=["W-F-1"]))
    err = capsys.readouterr().err
    assert rc == 1
    assert "the code it cites changed since the evidence was written" in err
    assert "write findings/W-F-1.json with fresh evidence, or resolve it" in err
    # fresh evidence in a file: accepted, re-anchored at this run
    write_finding(qa_root, finding("W-F-1", evidence=["a.py:3 — `y = 22` is the guard now"]))
    rc, state = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    f = state["findings"][0]
    assert f["delta"] == "STILL_OPEN" and f["anchored_at_run"] == 3 and "re_reported" not in f


# ── one class, one finding ─────────────────────────────────────────────────

def test_a_finding_filed_inside_another_findings_class_is_refused():
    a = finding("W-F-1", evidence=["src/x.py:14 — int() truncates"],
                root_cause={"mechanism": "m", "origin": "o",
                            "class": {"pattern": "int() on money",
                                      "sites": ["src/x.py:14 (this finding)", "src/r.py:41 — the twin"]}})
    b = finding("W-F-2", evidence=["src/r.py:41 — round() here"])
    bad = class_conflicts([a, b])
    assert bad == ["W-F-2 cites src/r.py:41, which W-F-1 names as a site of its class — fold "
                   "W-F-2 into W-F-1's sites, or remove the site from W-F-1's class; say which"]
    assert class_conflicts([a]) == [], "a finding citing its own sites is one finding"
    c = finding("W-F-3", root_cause={"class": {"sites": ["src/r.py:41 again"]}})
    assert "W-F-3 and W-F-1 both name src/r.py:41 as a site of their class" in class_conflicts([a, c])[0]


def test_the_class_rule_reaches_a_finding_carried_by_id(repo, qa_root, capsys):
    three_lines(repo)
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-1", root_cause={
        "mechanism": "m", "origin": "o",
        "class": {"pattern": "p", "sites": ["a.py:2 (this finding)", "a.py:3 — the twin"]}}))
    rc, _ = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-2", evidence=["a.py:3 — z is the twin"]))
    rc, _ = run_finalize(qa_root, judgment(findings=[], still_open=["W-F-1"]))
    assert rc == 1
    assert "W-F-2 cites a.py:3, which W-F-1 names as a site of its class" in capsys.readouterr().err


# ── facts: the directory between runs ──────────────────────────────────────

def test_facts_move_last_runs_files_aside_and_a_retry_keeps_them(repo, qa_root, capsys):
    three_lines(repo)
    facts = run_facts(repo, qa_root)
    assert facts["findings_dir"] == str(qa_root / "findings")
    assert Path(facts["finding_template"]).is_file()
    assert "findings_archived" not in facts
    write_finding(qa_root, finding("W-F-1"))
    rc, _ = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    # a fresh run: last run's file moves aside, never deleted
    facts = run_facts(repo, qa_root)
    assert facts["findings_archived"] == {"moved": 1, "to": "findings.prev",
                                          "why": "last run's finding files, moved aside so "
                                                 "this run starts empty"}
    assert not (qa_root / "findings").exists()
    assert (qa_root / "findings.prev" / "W-F-1.json").is_file()
    # this run writes a file, then the same run tries again: the file stays
    write_finding(qa_root, finding("W-F-2"))
    facts = run_facts(repo, qa_root)         # the marker at this commit is minutes old
    assert facts["findings_archived"]["kept"] == 1
    assert (qa_root / "findings" / "W-F-2.json").is_file()
    assert facts["previous_attempt_this_run"]


def test_archive_is_silent_on_an_empty_or_absent_directory(qa_root):
    assert archive_findings(qa_root, keep=False) is None
    (qa_root / "findings").mkdir()
    assert archive_findings(qa_root, keep=False) is None


def test_a_finding_carried_by_silence_drops_last_runs_verb(repo, qa_root, capsys):
    """`re_reported` describes one run's verb. A copy finalize carries on a later
    run — resolved by silence here — must not still say "re-reported by id"."""
    three_lines(repo)
    run_facts(repo, qa_root)
    write_finding(qa_root, finding("W-F-1"))
    rc, _ = run_finalize(qa_root, judgment(findings=[]))
    assert rc == 0, capsys.readouterr().err
    run_facts(repo, qa_root)
    rc, state = run_finalize(qa_root, judgment(findings=[], still_open=["W-F-1"]))
    assert rc == 0, capsys.readouterr().err
    assert state["findings"][0]["re_reported"] == "still_open"
    run_facts(repo, qa_root)
    rc, state = run_finalize(qa_root, judgment(findings=[]))       # unmentioned: silence resolves
    assert rc == 0, capsys.readouterr().err
    f = state["findings"][0]
    assert f["delta"] == "RESOLVED" and f.get("carried_forward")
    assert "re_reported" not in f
