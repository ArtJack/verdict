"""Tests for the fact harness — the deterministic half of a run.

Every value these tests assert is one a model used to produce by hand, and got
wrong at least once in production.
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from verdict_mcp.harness import (
    INDEX_HEADER, collect, finding_hash, index_row, merge, write_state)

HARNESS = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"


def _emit(lines):
    """A shell command printing these lines, on any platform.

    One print() per line, with no backslash escapes anywhere: a POSIX shell
    unescapes `\\n` inside double quotes before Python ever sees it, while
    cmd.exe passes it through — so an escape-based version emitted two lines on
    macOS, one literal line on Windows, and passed locally while failing in CI.
    """
    body = "; ".join(f"print({line!r})" for line in lines)
    return f'"{sys.executable}" -c "{body}"'


def git(args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "Widget"
    r.mkdir()
    git(["init", "-qb", "main"], r)
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "first"], r)
    return r


@pytest.fixture()
def qa_root(tmp_path):
    root = tmp_path / "qa"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "r.md").write_text("# report", encoding="utf-8")
    return root


def judgment(**over):
    j = {
        "report": "reports/r.md",
        "isolation_check": {"result": "pass"},
        "verdict": "pass with risks",
        "release_blockers": [],
        "not_tested": ["concurrency"],
        "findings": [{
            "id": "W-F-1", "title": "off-by-one at line 42", "severity": "Major",
            "priority": "P1", "status": "open", "failure_classification": "REAL_DEFECT",
            "confidence": "proven", "evidence": ["a.py:42 the guard"]}],
    }
    j.update(over)
    return j


# ── measuring ─────────────────────────────────────────────────────────────

def test_collect_measures_time_key_and_git(repo, qa_root):
    facts = collect(repo, qa_root, [])
    assert facts["project"] == "widget" and facts["project_key_source"] == "git"
    assert facts["run_number"] == 1 and facts["run_type"] == "baseline"
    ts = datetime.strptime(facts["last_run"]["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ")
    assert abs((datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc)).total_seconds()) < 120
    assert facts["last_run"]["git_sha"] and facts["last_run"]["git_branch"] == "main"


def test_collect_runs_gates_and_parses_counts(repo, qa_root):
    py = sys.executable
    facts = collect(repo, qa_root, [
        ("suite", f'"{py}" -c "import sys; print(\'3 passed, 1 skipped, 2 failed in 0.4s\'); sys.exit(1)"'),
        ("lint", f'"{py}" -c "pass"'),
    ])
    suite = facts["gates"]["suite"]
    assert suite["exit_code"] == 1 and suite["result"] == "fail"
    assert suite["counts"] == {"passed": 3, "skipped": 1, "failed": 2}
    assert isinstance(suite["duration_s"], float)
    assert facts["gates"]["lint"]["result"] == "pass"
    assert facts["tests"]["collected"] == 6


def test_collect_derives_run_type_and_range_from_previous(repo, qa_root):
    first = collect(repo, qa_root, [])
    (qa_root / "state.json").write_text(json.dumps({
        "run_number": 1,
        "last_run": {"git_sha": first["last_run"]["git_sha"],
                     "timestamp_utc": first["last_run"]["timestamp_utc"]}}), encoding="utf-8")
    (repo / "b.py").write_text("y = 2\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "second"], repo)

    facts = collect(repo, qa_root, [])
    assert facts["run_number"] == 2 and facts["run_type"] == "delta"
    assert facts["last_run"]["sha_range"].startswith(first["last_run"]["git_sha"])
    assert "1 file changed" in facts["last_run"]["diff_stat"]


def test_collect_declares_re_baseline_when_the_stored_sha_is_gone(repo, qa_root):
    (qa_root / "state.json").write_text(json.dumps({
        "run_number": 3, "last_run": {"git_sha": "deadbee", "timestamp_utc": "2026-01-01T00:00:00Z"}}),
        encoding="utf-8")
    facts = collect(repo, qa_root, [])
    assert facts["run_type"] == "re-baseline"
    assert "not in this repository" in facts["run_type_reason"]


def test_collect_declares_re_baseline_when_the_previous_run_is_old(repo, qa_root):
    first = collect(repo, qa_root, [])
    old = (datetime.now(timezone.utc) - timedelta(days=9)).strftime("%Y-%m-%dT%H:%M:%SZ")
    (qa_root / "state.json").write_text(json.dumps({
        "run_number": 1,
        "last_run": {"git_sha": first["last_run"]["git_sha"], "timestamp_utc": old}}),
        encoding="utf-8")
    facts = collect(repo, qa_root, [])
    assert facts["run_type"] == "re-baseline" and "9 days ago" in facts["run_type_reason"]


def test_test_id_set_diff_not_summary_arithmetic(repo, qa_root):
    (qa_root / "test-ids.txt").write_text("t.py::a\nt.py::gone\n", encoding="utf-8")
    facts = collect(repo, qa_root, [], test_ids_cmd=_emit(["t.py::a", "t.py::new"]))
    assert facts["test_ids"]["status"] == "measured"
    assert facts["test_ids"]["added"] == ["t.py::new"]
    assert facts["test_ids"]["removed"] == ["t.py::gone"]


def test_parametrised_ids_with_spaces_survive_the_ledger_round_trip(repo, qa_root):
    # `test_rate[west 7kg]` is one id, not two words.
    ids = ["t.py::test_rate[west 7kg]", "t.py::test_rate[east 2kg]"]
    (qa_root / "test-ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    facts = collect(repo, qa_root, [], test_ids_cmd=_emit(ids))
    assert facts["test_ids"]["count"] == 2
    assert facts["test_ids"]["added"] == [] and facts["test_ids"]["removed"] == []


def test_zero_test_ids_is_reported_as_unavailable_not_as_an_empty_suite(repo, qa_root):
    # A project whose addopts carry -q turns `--collect-only -q` into -qq and
    # prints per-file counts; claiming count 0 would be the lie §6 forbids.
    ledger = qa_root / "test-ids.txt"
    ledger.write_text("t.py::a\n", encoding="utf-8")
    facts = collect(repo, qa_root, [], test_ids_cmd=_emit(["tests/test_x.py: 5"]))
    assert facts["test_ids"]["status"] == "unavailable"
    assert "-qq" in facts["test_ids"]["reason"]
    assert "count" not in facts["test_ids"]
    assert ledger.read_text(encoding="utf-8") == "t.py::a\n"  # ledger untouched


# ── merging ───────────────────────────────────────────────────────────────

def test_hash_is_stable_across_moving_line_numbers():
    a = {"title": "off-by-one at line 42", "evidence": ["a.py:42 guard"]}
    b = {"title": "off-by-one at line 87", "evidence": ["a.py:87 guard"]}
    assert finding_hash(a) == finding_hash(b)
    other = {"title": "unrelated problem", "evidence": ["b.py:1"]}
    assert finding_hash(other) != finding_hash(a)


def test_merge_assigns_deltas_the_model_used_to_guess(repo, qa_root):
    facts = collect(repo, qa_root, [])
    first = merge(facts, judgment(), None)
    assert first["findings"][0]["delta"] == "NEW"
    assert first["findings"][0]["age_days"] == 0

    facts2 = dict(facts, run_number=2, run_type="delta")
    second = merge(facts2, judgment(), first)
    assert second["findings"][0]["delta"] == "STILL_OPEN"

    fixed = judgment()
    fixed["findings"][0]["status"] = "resolved"
    third = merge(facts2, fixed, second)
    assert third["findings"][0]["delta"] == "RESOLVED"

    fourth = merge(facts2, judgment(), third)
    assert fourth["findings"][0]["delta"] == "REGRESSED"


def test_merge_ages_from_first_seen(repo, qa_root):
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{
        "hash": finding_hash(judgment()["findings"][0]), "status": "open",
        "first_seen": (date.today() - timedelta(days=6)).isoformat()}]}
    state = merge(facts, judgment(), previous)
    assert state["findings"][0]["age_days"] == 6


def test_merge_carries_forward_a_finding_this_run_did_not_mention(repo, qa_root):
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{
        "id": "W-F-9", "hash": "beefbeef", "status": "open", "severity": "Minor",
        "priority": "P3", "first_seen": date.today().isoformat(), "title": "old thing",
        "evidence": ["z.py:1"]}]}
    state = merge(facts, judgment(), previous)
    carried = [f for f in state["findings"] if f["hash"] == "beefbeef"][0]
    assert carried["delta"] == "RESOLVED" and carried["status"] == "resolved"
    assert "not reported this run" in carried["carried_forward"]


def test_merge_preserves_unknown_keys_from_the_previous_state(repo, qa_root):
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(), {"house_rules": {"kept": True}, "findings": []})
    assert state["house_rules"] == {"kept": True}


# ── writing ───────────────────────────────────────────────────────────────

def test_write_state_refuses_an_invalid_state_and_writes_a_valid_one(repo, qa_root):
    facts = collect(repo, qa_root, [])
    bad = merge(facts, judgment(report="inline to caller"), None)
    problems = write_state(qa_root, bad)
    assert problems and not (qa_root / "state.json").exists()

    good = merge(facts, judgment(), None)
    assert write_state(qa_root, good) == []
    written = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert written["run_number"] == 1
    index = (qa_root / "reports" / "INDEX.md").read_text(encoding="utf-8")
    assert INDEX_HEADER.splitlines()[0] in index and "| widget |" in index


def test_write_state_snapshots_the_previous_state_for_the_run_number_check(repo, qa_root):
    facts = collect(repo, qa_root, [])
    write_state(qa_root, merge(facts, judgment(), None))
    facts2 = dict(facts, run_number=2, run_type="delta")
    write_state(qa_root, merge(facts2, judgment(), None))
    assert json.loads((qa_root / "state.json.prev").read_text(encoding="utf-8"))["run_number"] == 1


def test_index_row_counts_open_findings_by_severity(repo, qa_root):
    facts = collect(repo, qa_root, [("s", "echo '2 passed, 1 failed'")])
    j = judgment()
    j["findings"].append({"id": "W-F-2", "title": "worse", "severity": "Critical",
                          "priority": "P0", "status": "open", "evidence": ["a.py:1"]})
    row = index_row(merge(facts, j, None))
    assert "| 0/1/1/0 |" in row and "[r.md](reports/r.md)" in row


# ── the CLIs ──────────────────────────────────────────────────────────────

def test_cli_requires_an_explicit_subcommand():
    proc = subprocess.run([sys.executable, str(HARNESS)], capture_output=True, text=True)
    assert proc.returncode == 2 and "facts|finalize" in proc.stderr


def test_cli_round_trip(repo, qa_root, tmp_path):
    facts_cli = subprocess.run(
        [sys.executable, str(HARNESS), "facts", "--repo", str(repo), "--qa-root", str(qa_root),
         "--gate", "suite=echo '5 passed in 0.1s'"],
        capture_output=True, text=True)
    assert facts_cli.returncode == 0, facts_cli.stderr
    assert (qa_root / "facts.json").is_file()

    jpath = tmp_path / "judgment.json"
    jpath.write_text(json.dumps(judgment()), encoding="utf-8")
    final = subprocess.run(
        [sys.executable, str(HARNESS), "finalize",
         "--qa-root", str(qa_root), "--judgment", str(jpath)],
        capture_output=True, text=True)
    assert final.returncode == 0, final.stderr
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert state["tests"]["passed"] == 5 and state["findings"][0]["delta"] == "NEW"


# ── the rendered report ───────────────────────────────────────────────────

def test_report_is_rendered_from_state_and_cannot_contradict_it(repo, qa_root):
    from verdict_mcp.harness import render_report
    facts = collect(repo, qa_root, [("suite", _emit(["7 passed, 1 failed"]))])
    j = judgment()
    j["findings"] = [
        {"id": "W-F-2", "title": "rounding drifts", "severity": "Critical", "priority": "P0",
         "status": "open", "failure_classification": "REAL_DEFECT", "evidence": ["m.py:9"]},
        {"id": "W-F-1", "title": "old news", "severity": "Minor", "priority": "P3",
         "status": "open", "evidence": ["a.py:1"]},
    ]
    state = merge(facts, j, {"findings": [
        {"hash": finding_hash({"title": "rounding drifts", "evidence": ["m.py:9"]}),
         "status": "resolved", "first_seen": "2026-08-01"}]})
    text = render_report(state, {"risks": "Money paths dominate.",
                                 "findings": {"W-F-2": "The mechanism is truncation."}})

    assert "**VERDICT: pass with risks**" in text
    # REGRESSED outranks the Critical/Minor ordering and appears first
    assert text.index("W-F-2") < text.index("W-F-1")
    assert "REGRESSED" in text.split("W-F-1")[0]
    assert "7 passed" in text and "suite" in text          # gates from state
    assert "Money paths dominate." in text                  # prose from the agent
    assert "The mechanism is truncation." in text
    assert "concurrency" in text                            # not_tested carried through


def test_finalize_writes_the_report_so_it_cannot_go_missing(repo, qa_root, tmp_path):
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    j = judgment()
    j.pop("report")                       # the agent names no report at all
    j["topic"] = "delta-run"
    jpath = tmp_path / "j.json"
    jpath.write_text(json.dumps(j), encoding="utf-8")

    proc = subprocess.run([sys.executable, str(HARNESS), "finalize",
                           "--qa-root", str(qa_root), "--judgment", str(jpath)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    report = qa_root / state["last_run"]["report"]
    assert report.is_file() and "delta-run" in report.name
    assert "VERDICT" in report.read_text(encoding="utf-8")


# ── reuse, and the visibility of an abandoned run ─────────────────────────

def test_facts_reuse_skips_the_gates_only_for_the_same_head(repo, qa_root):
    slow = _emit(["1 passed"])
    first = subprocess.run([sys.executable, str(HARNESS), "facts", "--repo", str(repo),
                            "--qa-root", str(qa_root), "--gate", f"suite={slow}"],
                           capture_output=True, text=True)
    assert first.returncode == 0, first.stderr

    again = subprocess.run([sys.executable, str(HARNESS), "facts", "--repo", str(repo),
                            "--qa-root", str(qa_root), "--gate", f"suite={slow}",
                            "--reuse-if-fresh"], capture_output=True, text=True)
    assert json.loads(again.stdout)["reused"]["why"].startswith("same HEAD")

    (repo / "c.py").write_text("z = 3\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "third"], repo)
    moved = subprocess.run([sys.executable, str(HARNESS), "facts", "--repo", str(repo),
                            "--qa-root", str(qa_root), "--gate", f"suite={slow}",
                            "--reuse-if-fresh"], capture_output=True, text=True)
    assert "reused" not in json.loads(moved.stdout)


def test_an_abandoned_run_is_reported_not_swept_up(repo, qa_root):
    (qa_root / "run-in-progress.json").write_text(
        json.dumps({"started_utc": "2026-08-29T01:00:00Z"}), encoding="utf-8")
    facts = collect(repo, qa_root, [])
    assert facts["previous_run_incomplete"]["started_utc"] == "2026-08-29T01:00:00Z"
    assert "lost" in facts["previous_run_incomplete"]["meaning"]


def test_finalize_clears_the_marker(repo, qa_root, tmp_path):
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (qa_root / "run-in-progress.json").write_text("{}", encoding="utf-8")
    jpath = tmp_path / "j.json"
    jpath.write_text(json.dumps(judgment()), encoding="utf-8")
    subprocess.run([sys.executable, str(HARNESS), "finalize", "--qa-root", str(qa_root),
                    "--judgment", str(jpath)], capture_output=True, text=True, check=True)
    assert not (qa_root / "run-in-progress.json").exists()


def test_a_healthy_run_does_not_report_itself_as_abandoned(repo, qa_root):
    """`facts` writes its marker before the gates run, so a run killed mid-suite
    leaves a trace. It read that marker back on the same pass, and every healthy
    run announced that the previous one had died — a warning that fires every
    time is one nobody reads."""
    first = json.loads(subprocess.run(
        [sys.executable, str(HARNESS), "facts", "--repo", str(repo),
         "--qa-root", str(qa_root)],
        capture_output=True, text=True, check=True).stdout)
    assert "previous_run_incomplete" not in first
    assert "previous_attempt_this_run" not in first
    marker = json.loads((qa_root / "run-in-progress.json").read_text(encoding="utf-8"))
    assert marker["git_sha"], "the marker records the commit it was staked at"


def test_a_reworded_re_report_is_the_same_finding_not_a_new_one(repo, qa_root):
    """The hash is a content fingerprint and drifts whenever the tester rewords
    its own finding. Matched only by hash, a reworded re-report was filed as NEW
    *and* carried forward as resolved: two entries, one id, and a state the
    validator refuses to write — so the run produced nothing at all."""
    facts = collect(repo, qa_root, [])
    first = merge(facts, judgment(), None)

    reworded = judgment()
    reworded["findings"][0]["title"] = "off-by-one in the floor guard, re-examined"
    reworded["findings"][0]["evidence"] = ["a.py:44 the same guard, quoted differently"]
    second = merge(dict(facts, run_number=2, run_type="delta"), reworded, first)

    assert len(second["findings"]) == 1, "one finding, not a NEW plus a carried duplicate"
    entry = second["findings"][0]
    assert entry["delta"] == "STILL_OPEN"
    assert entry["hash"] == first["findings"][0]["hash"], "identity survives the rewording"
    assert entry["first_seen"] == first["findings"][0]["first_seen"]


def test_a_state_whose_hashes_predate_the_harness_still_merges(repo, qa_root):
    """Every hash in four live projects — 115 of them — was hand-authored before
    the harness existed and matches nothing computable. Without the id fallback
    no project could ever take its first harness-driven run."""
    facts = collect(repo, qa_root, [])
    previous = merge(facts, judgment(), None)
    previous["findings"][0]["hash"] = "deadbeef"  # as a model once typed it

    state = merge(dict(facts, run_number=2, run_type="delta"), judgment(), previous)
    assert len(state["findings"]) == 1
    assert state["findings"][0]["delta"] == "STILL_OPEN"
    assert state["findings"][0]["hash"] == "deadbeef", "the stored identity is kept"


def test_a_retry_at_the_same_commit_is_not_a_lost_run(repo, qa_root):
    """A live run mistyped its id command, re-ran `facts`, and was told its own
    first attempt was a lost night. The alarm exists to make a real gap visible;
    one that fires on every retry is one nobody reads."""
    args = [sys.executable, str(HARNESS), "facts", "--repo", str(repo),
            "--qa-root", str(qa_root)]
    subprocess.run(args, capture_output=True, text=True, check=True)
    retry = json.loads(subprocess.run(args, capture_output=True, text=True,
                                      check=True).stdout)
    assert "previous_run_incomplete" not in retry
    assert "this run's own retry" in retry["previous_attempt_this_run"]["meaning"]

    # a marker from another commit is the real thing: that coverage never happened
    (qa_root / "run-in-progress.json").write_text(json.dumps({
        "started_utc": "2026-01-01T00:00:00Z", "repo": str(repo),
        "git_sha": "deadbeef"}), encoding="utf-8")
    lost = json.loads(subprocess.run(args, capture_output=True, text=True,
                                     check=True).stdout)
    assert "its work is lost" in lost["previous_run_incomplete"]["meaning"]
