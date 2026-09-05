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
    INDEX_HEADER, collect, finding_hash, index_row, merge, run_date, write_state)

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


from conftest import git, judgment  # noqa: E402


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
    """The expected date comes off the run's own clock, not the machine's.

    This asserted against `date.today()` and went red the first evening UTC
    crossed midnight ahead of a UTC-7 host — green in CI, red locally for seven
    hours a day. VERDICT-F-54 moved `merge` to the run's UTC stamp precisely so
    the two could not disagree; a test that keeps one foot in the local clock
    re-opens the gap it closed. Same shape as VERDICT-F-24, which this file
    already has a test for.
    """
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{
        "hash": finding_hash(judgment()["findings"][0]), "status": "open",
        "first_seen": (run_date(facts) - timedelta(days=6)).isoformat()}]}
    state = merge(facts, judgment(), previous)
    assert state["findings"][0]["age_days"] == 6


def test_merge_carries_forward_a_finding_this_run_did_not_mention(repo, qa_root):
    facts = collect(repo, qa_root, [])
    previous = {"findings": [{
        "id": "W-F-9", "hash": "beefbeef", "status": "open", "severity": "Minor",
        "priority": "P3", "first_seen": run_date(facts).isoformat(), "title": "old thing",
        "evidence": ["z.py:1"]}]}
    state = merge(facts, judgment(), previous)
    carried = [f for f in state["findings"] if f["hash"] == "beefbeef"][0]
    assert carried["delta"] == "RESOLVED" and carried["status"] == "resolved"
    assert "not reported this run" in carried["carried_forward"]


def _backlog(n):
    """`n` prior open findings — the standing backlog a scoped run never reads."""
    return [{"id": f"W-B-{i}", "hash": f"b{i:07x}", "status": "open",
             "severity": "Critical", "priority": "P1", "title": f"old thing {i}",
             "first_seen": datetime.now(timezone.utc).date().isoformat(),
             "evidence": [f"z{i}.py:1"]}
            for i in range(n)]


def test_a_scoped_run_does_not_resolve_the_backlog_it_never_looked_at(repo, qa_root):
    """Production, sales run 10: a merge gate over three files resolved 62 open
    findings — 14 of them Critical — because the judgment only spoke to the
    diff. The gate reads open Criticals, so silence from a run that never
    looked had closed the backlog and would have gated on 3 instead of 17."""
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(), {"findings": _backlog(62)})
    carried = [f for f in state["findings"] if str(f["id"]).startswith("W-B-")]
    assert len(carried) == 62, "a held finding is still tracked, not dropped"
    assert {f["delta"] for f in carried} == {"STILL_OPEN"}
    assert {f["status"] for f in carried} == {"open"}
    assert "62 of 62" in carried[0]["carried_forward"]
    assert sum(1 for f in state["findings"] if f["status"] == "open") == 63


def test_full_sweep_licenses_silence_to_resolve_the_whole_backlog(repo, qa_root):
    """The guardrail is a default, not a wall. A run that really did sweep
    everything says so, and silence resolves exactly as it always did."""
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(full_sweep=True), {"findings": _backlog(62)})
    carried = [f for f in state["findings"] if str(f["id"]).startswith("W-B-")]
    assert {f["delta"] for f in carried} == {"RESOLVED"}
    assert {f["status"] for f in carried} == {"resolved"}


def test_silence_still_resolves_when_the_run_reported_most_of_the_backlog(repo, qa_root):
    """The ordinary case the guardrail must not swallow: a delta run that
    re-reported 8 of 10 and stopped mentioning 2 is describing two fixes."""
    facts = collect(repo, qa_root, [])
    prior = _backlog(10)
    reported = [{**f, "failure_classification": "REAL_DEFECT", "confidence": "proven"}
                for f in prior[:8]]
    state = merge(facts, judgment(findings=reported), {"findings": prior})
    seen = {}
    for f in state["findings"]:
        seen[f["delta"]] = seen.get(f["delta"], 0) + 1
    assert seen == {"STILL_OPEN": 8, "RESOLVED": 2}


def test_the_hold_has_a_floor_and_a_share_and_both_edges_are_exact(repo, qa_root):
    """Below five unmentioned, proportion is noise and silence resolves even
    when it is total; at exactly half of a real backlog it still resolves —
    the hold needs *more* than half. One past either edge, it fires."""
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(findings=[]), {"findings": _backlog(4)})
    assert {f["delta"] for f in state["findings"]} == {"RESOLVED"}

    def reported(prior, n):
        return [{**f, "failure_classification": "REAL_DEFECT",
                 "confidence": "proven"} for f in prior[:n]]

    prior = _backlog(10)  # 5 of 10 unmentioned: at the share edge, resolves
    state = merge(facts, judgment(findings=reported(prior, 5)), {"findings": prior})
    assert sum(f["delta"] == "RESOLVED" for f in state["findings"]) == 5

    prior = _backlog(10)  # 6 of 10 unmentioned: past the edge, held
    state = merge(facts, judgment(findings=reported(prior, 4)), {"findings": prior})
    assert sum(f["delta"] == "STILL_OPEN" for f in state["findings"]) == 10


def test_a_held_backlog_is_a_state_the_pipeline_will_write(repo, qa_root):
    """Production held its 62 findings through the full pipeline, not through
    merge() in isolation — a hold that `validate` then refuses to write is a
    guardrail that fails at the exact moment it fires."""
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(), {"findings": _backlog(62)})
    assert write_state(qa_root, state) == []


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


# ── runner dialects ───────────────────────────────────────────────────────

# Real summary lines. The count-drop gate and the id set-diff are two of the
# things Verdict does that a plain test run does not — and for every runner
# below they used to be silently unavailable, because the parser only spoke
# pytest and said nothing when it understood nothing.
SUMMARIES = [
    ("pytest", "3 failed, 4 passed, 1 skipped in 0.02s",
     {"passed": 4, "failed": 3, "skipped": 1}),
    ("cargo", "test result: ok. 5 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out",
     {"passed": 5, "failed": 0, "skipped": 1}),
    ("jest", "Tests:       1 failed, 4 passed, 5 total",
     {"collected": 5, "passed": 4, "failed": 1}),
    ("vitest", " Tests  2 failed | 5 passed (7)",
     {"collected": 7, "passed": 5, "failed": 2}),
    ("rspec", "5 examples, 1 failure, 2 pending",
     {"collected": 5, "failed": 1, "skipped": 2}),
    ("phpunit", "Tests: 5, Assertions: 10, Failures: 1.",
     {"collected": 5, "failed": 1}),
    ("phpunit", "OK (5 tests, 5 assertions)", {"passed": 5}),
    ("dotnet", "Passed!  - Failed:     0, Passed:     5, Skipped:     0, Total:     5",
     {"collected": 5, "passed": 5, "failed": 0, "skipped": 0}),
    ("surefire", "Tests run: 12, Failures: 1, Errors: 0, Skipped: 2",
     {"collected": 12, "failed": 1, "errors": 0, "skipped": 2}),
    ("gotestsum", "DONE 12 tests, 1 failure in 0.5s", {"collected": 12, "failed": 1}),
]


@pytest.mark.parametrize("dialect,line,expected", SUMMARIES,
                         ids=[f"{d}-{i}" for i, (d, _, _) in enumerate(SUMMARIES)])
def test_each_runner_dialect_is_parsed_and_named(dialect, line, expected):
    from verdict_mcp.harness import _counts
    counts, name = _counts(line)
    assert counts == expected
    assert name == dialect, "the dialect is reported so a reader can audit the reading"


def test_overlapping_vocabularies_do_not_steal_each_others_output():
    """`1 failure` is gotestsum and rspec; `Failures: 1` is surefire and phpunit;
    `5 passed` is pytest, cargo, jest and vitest. Read by the wrong dialect the
    numbers are not wrong so much as incomplete — cargo read as pytest silently
    drops `ignored`, which is the skip count the gate cares about."""
    from verdict_mcp.harness import _counts
    assert _counts("test result: ok. 5 passed; 0 failed; 1 ignored")[0]["skipped"] == 1
    assert _counts("Tests run: 12, Failures: 1, Errors: 0, Skipped: 2")[0]["collected"] == 12
    assert _counts("DONE 12 tests, 1 failure in 0.5s")[0]["collected"] == 12


def test_plain_go_test_is_counted_from_its_per_test_lines():
    """`go test` prints no totals at all; the -v lines are the only signal."""
    from verdict_mcp.harness import _counts
    counts, name = _counts(
        "--- PASS: TestA (0.00s)\n--- FAIL: TestB (0.01s)\n--- SKIP: TestC (0.00s)\nFAIL\n")
    assert counts == {"passed": 1, "failed": 1, "skipped": 1} and name == "go test -v"


def test_an_unreadable_summary_says_so_instead_of_reporting_nothing(repo, qa_root):
    """Empty counts have two very different causes — the suite reported nothing,
    or we failed to understand it — and they need different fixes."""
    facts = collect(repo, qa_root, [("suite", _emit(["Build succeeded. Nothing to report."]))])
    gate = facts["gates"]["suite"]
    assert "counts" not in gate
    assert "cannot fire" in gate["counts_unparsed"]
    assert "tests" not in facts


def test_a_runner_reported_total_beats_our_arithmetic(repo, qa_root):
    """Several runners report both parts and a total, and they disagree when a
    test errors during collection. The runner's own number wins."""
    facts = collect(repo, qa_root, [("suite", _emit(["Tests run: 12, Failures: 1, Errors: 0, Skipped: 2"]))])
    assert facts["tests"]["collected"] == 12


def test_finalize_rejects_a_bad_judgment_in_the_author_s_own_terms(repo, qa_root):
    """A judgment problem used to surface after the merge, phrased for a
    structure the agent never wrote. It is caught before the merge now, and
    nothing is written."""
    subprocess.run([sys.executable, str(HARNESS), "facts", "--repo", str(repo),
                    "--qa-root", str(qa_root)], check=True, capture_output=True)
    j = judgment()
    j["findings"][0].pop("confidence")
    path = qa_root / "j.json"
    path.write_text(json.dumps(j), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(HARNESS), "finalize", "--qa-root", str(qa_root),
         "--judgment", str(path)], capture_output=True, text=True)
    assert proc.returncode == 1
    assert "fix the judgment, not the check" in proc.stderr
    assert "will be filed as NEW" in proc.stderr
    assert not (qa_root / "state.json").exists(), "nothing is written on a bad judgment"


# ── runs.jsonl: the machine record of run history ─────────────────────────

def test_every_finalized_run_appends_one_machine_native_history_line(repo, qa_root):
    """The time series used to live only in INDEX.md, and production wrote
    prose into its cells — every consumer then had to un-parse a rendering."""
    from verdict_mcp.state import load_runs
    facts = collect(repo, qa_root, [])
    state = merge(facts, judgment(), None)
    assert write_state(qa_root, state) == []
    rows, skipped = load_runs(qa_root)
    assert skipped == 0 and len(rows) == 1
    row = rows[0]
    assert row["run_number"] == 1 and row["verdict"] == "pass with risks"
    assert row["findings"]["open_by_severity"] == {"Major": 1}
    assert row["findings"]["delta"] == {"NEW": 1}
    assert row["timestamp_utc"] == facts["last_run"]["timestamp_utc"]


def test_a_torn_trailing_line_is_skipped_and_counted_never_fatal(qa_root):
    from verdict_mcp.state import load_runs
    (qa_root / "runs.jsonl").write_text(
        '{"run_number": 1, "verdict": "pass"}\n{"run_number": 2, "verd',
        encoding="utf-8")
    rows, skipped = load_runs(qa_root)
    assert [r["run_number"] for r in rows] == [1] and skipped == 1


def test_a_rewritten_run_keeps_the_last_line_not_both(qa_root):
    from verdict_mcp.state import load_runs
    (qa_root / "runs.jsonl").write_text(
        '{"run_number": 1, "verdict": "fail"}\n'
        '{"run_number": 1, "verdict": "pass with risks"}\n', encoding="utf-8")
    rows, _ = load_runs(qa_root)
    assert len(rows) == 1 and rows[0]["verdict"] == "pass with risks"


def test_a_correction_appended_after_a_rollback_outranks_the_row_it_corrects(repo, qa_root):
    """`validate` refuses a second finalize at the same run number, so the way
    to retry a bad run is to restore state.json and re-run. That rolls back
    every file except runs.jsonl, which is append-only by design — the stale
    row stays, and only the revision says which of the two won."""
    from verdict_mcp.state import load_runs
    facts = collect(repo, qa_root, [])
    first = merge(facts, judgment(run_label="first finalize, miscounted"), None)
    assert write_state(qa_root, first) == []
    (qa_root / "state.json").unlink()  # the operator's rollback
    assert write_state(qa_root, merge(facts, judgment(run_label="corrected"), None)) == []
    lines = (qa_root / "runs.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2, "history is append-only; the stale row is never removed"
    assert json.loads(lines[0]).get("revision") is None, "generation zero stays absent"
    assert json.loads(lines[1])["revision"] == 1
    rows, _ = load_runs(qa_root)
    assert len(rows) == 1 and rows[0]["run_label"] == "corrected"


def test_a_higher_revision_wins_even_when_it_is_not_the_last_line(qa_root):
    """The point of the marker. A reader that trusts file order alone is one
    `sort` — or one hand-appended row — away from a superseded verdict."""
    from verdict_mcp.state import load_runs
    (qa_root / "runs.jsonl").write_text(
        '{"run_number": 1, "verdict": "pass with risks", "revision": 1}\n'
        '{"run_number": 1, "verdict": "fail"}\n', encoding="utf-8")
    rows, _ = load_runs(qa_root)
    assert len(rows) == 1 and rows[0]["verdict"] == "pass with risks"


def test_a_garbled_revision_never_outranks_a_real_one(qa_root):
    from verdict_mcp.state import load_runs
    (qa_root / "runs.jsonl").write_text(
        '{"run_number": 1, "verdict": "pass with risks", "revision": 2}\n'
        '{"run_number": 1, "verdict": "fail", "revision": "later"}\n', encoding="utf-8")
    rows, _ = load_runs(qa_root)
    assert rows[0]["verdict"] == "pass with risks"


def test_the_model_that_signed_the_verdict_is_measured_not_remembered(repo, qa_root, monkeypatch):
    """Which model signed a verdict used to live only in the operator's memory.
    The runner exports VERDICT_MODEL; the measurement lands in last_run and the
    history row — absent when nothing exported it, never guessed."""
    monkeypatch.setenv("VERDICT_MODEL", "opus")
    facts = collect(repo, qa_root, [])
    assert facts["last_run"]["model"] == "opus"
    state = merge(facts, judgment(), None)
    assert write_state(qa_root, state) == []
    from verdict_mcp.state import load_runs
    assert load_runs(qa_root)[0][0]["model"] == "opus"

    monkeypatch.delenv("VERDICT_MODEL")
    bare = collect(repo, qa_root, [])
    assert "model" not in bare["last_run"]


# --- a suite that ran nothing is a measured fact, not a judgment call -------

def test_executed_nothing_fires_when_every_test_was_skipped():
    from verdict_mcp.harness import _counts, executed_nothing
    counts, dialect = _counts("===== 12 skipped in 0.30s =====")
    assert dialect == "pytest" and counts == {"skipped": 12}
    assert "executed nothing" in executed_nothing(counts)


@pytest.mark.parametrize("summary", [
    "===== 8 passed, 2 skipped in 1.2s =====",
    "===== 3 failed, 5 passed in 2.0s =====",
    "===== 7 passed in 0.4s =====",
])
def test_executed_nothing_stays_quiet_on_a_suite_that_ran(summary):
    """A guard that fires on ordinary skips would be ignored within a week."""
    from verdict_mcp.harness import _counts, executed_nothing
    counts, _ = _counts(summary)
    assert executed_nothing(counts) is None


def test_executed_nothing_is_dialect_agnostic():
    from verdict_mcp.harness import _counts, executed_nothing
    counts, dialect = _counts("Tests: 4 skipped, 4 total")
    assert dialect == "jest"
    assert executed_nothing(counts)


def test_executed_nothing_says_nothing_when_counts_were_unparsed():
    """No counts is 'we could not read it', which is a different problem."""
    from verdict_mcp.harness import executed_nothing
    assert executed_nothing({}) is None


def test_facts_report_a_skip_all_suite(repo, qa_root):
    """End to end: the fact reaches judgment.json's author already measured."""
    from verdict_mcp.harness import collect
    skip_all = _emit(["===== 12 skipped in 0.30s ====="])
    facts = collect(repo, qa_root, [("suite", skip_all)])
    gate = facts["gates"]["suite"]
    assert "executed_nothing" in gate, gate
    assert "12 collected tests were skipped" in gate["executed_nothing"]


# --- a gate dramatically slower than its own history is a measured fact -----
#
# The motivating case is external: three tests started calling a live CLI, the
# suite went 3s -> 65s, a week of subscription quota burned silently -- and the
# number sat in facts.json the whole run, measured and uncompared.

def test_duration_regression_fires_on_the_reported_case():
    from verdict_mcp.harness import duration_regressed
    msg = duration_regressed(65.2, [3.0, 3.1, 3.2, 3.0, 3.1])
    assert msg and "21x" in msg and "65.2s" in msg


@pytest.mark.parametrize("current,priors", [
    (4.0, [3.0, 3.1, 3.2]),        # slower, but within the factor
    (0.5, [0.07, 0.07]),           # 7x, but the absolute floor holds
    (65.0, [3.0]),                 # one prior is not a baseline
    (65.0, []),                    # no history: no claim
    (3.0, [3.0, 3.1, 3.2]),        # steady state
])
def test_duration_regression_stays_quiet(current, priors):
    from verdict_mcp.harness import duration_regressed
    assert duration_regressed(current, priors) is None


def test_collect_reports_duration_regression_from_history(repo, qa_root, monkeypatch):
    """End to end: history in runs.jsonl, comparison in collect, fact in the
    gate result -- the judgment step receives it established."""
    import verdict_mcp.harness as h
    rows = [{"run_number": n, "gate_durations": {"suite": 0.001}} for n in (1, 2, 3)]
    (qa_root / "runs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    # The real gate takes ~1s of wall clock; against a 1ms median that is
    # thousands of x. Only the absolute floor needs lowering to test the wiring.
    monkeypatch.setattr(h, "_DURATION_ABS_FLOOR_S", 0.0)
    facts = h.collect(repo, qa_root, [("suite", _emit(["1 passed"]))])
    gate = facts["gates"]["suite"]
    assert "duration_regressed" in gate, gate
    assert "x)" in gate["duration_regressed"]


def test_history_rows_carry_gate_durations(repo, qa_root, tmp_path):
    """finalize writes the telemetry the next run's comparison reads."""
    from verdict_mcp.harness import collect
    facts = collect(repo, qa_root, [("suite", _emit(["1 passed"]))])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    jp = tmp_path / "j.json"
    jp.write_text(json.dumps(judgment()), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HARNESS), "finalize",
                           "--qa-root", str(qa_root), "--judgment", str(jp)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    row = json.loads((qa_root / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert "gate_durations" in row and "suite" in row["gate_durations"]


def test_gate_durations_do_not_disturb_the_chain(repo, qa_root, tmp_path):
    """The chain must not sign telemetry: an old state signed before
    gate_durations existed re-derives its row WITH the field today, and if the
    field were in the signed body every pre-upgrade state would read as
    tampered -- including this repository's own committed .qa."""
    from verdict_mcp.state import chain_link
    signed_without = {"run_number": 5, "verdict": "pass"}
    link = chain_link("", signed_without)
    rederived_with = {"run_number": 5, "verdict": "pass",
                      "gate_durations": {"suite": 31.3}}
    assert chain_link("", rederived_with) == link, \
        "gate_durations leaked into the chain body"
    tampered = {"run_number": 5, "verdict": "fail"}
    assert chain_link("", tampered) != link, "the verdict itself must stay signed"


# --- verified intact: confirmation is a deliverable --------------------------
#
# The first external user's words: the invariants of his money were checked and
# confirmed intact, the report said so in the middle where nobody reads, and
# that confirmation is what a tester is paid for. The field is optional by
# design -- forcing it would push models to invent entries.

def test_verified_intact_travels_from_judgment_to_state_and_report(repo, qa_root, tmp_path):
    from verdict_mcp.harness import collect
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    j = judgment(verified_intact=[
        "ledger invariant: debits equal credits across all 12 fixtures (pytest -k ledger, 12 passed)",
    ])
    jp = tmp_path / "j.json"
    jp.write_text(json.dumps(j), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HARNESS), "finalize",
                           "--qa-root", str(qa_root), "--judgment", str(jp)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert state["verified_intact"] == j["verified_intact"]
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "## Verified intact" in report
    # Prominence is the point: after the blockers, before Not tested.
    assert report.index("## Release blockers") < report.index("## Verified intact") \
        < report.index("## Not tested")


def test_verified_intact_is_optional_and_absent_means_no_section(repo, qa_root, tmp_path):
    from verdict_mcp.harness import collect
    facts = collect(repo, qa_root, [])
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    jp = tmp_path / "j.json"
    jp.write_text(json.dumps(judgment()), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(HARNESS), "finalize",
                           "--qa-root", str(qa_root), "--judgment", str(jp)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "## Verified intact" not in report, \
        "an empty forced section would push models to pad it"


# ── three findings run 4 filed against the harness that measured it ────────

def test_the_set_diff_count_is_not_capped_by_the_display_list(repo, qa_root):
    """VERDICT-F-20: the lists are capped at 50 for display, and the count used
    to be len() of the capped list — so a mass deletion read as −50 under a
    line claiming set-diff accounting. Live on run 4: +50 where the truth was
    +166. The counts now come from the untruncated sets."""
    ledger = [f"t.py::test_{i:03d}" for i in range(200)]
    (qa_root / "test-ids.txt").write_text("\n".join(ledger) + "\n", encoding="utf-8")
    facts = collect(repo, qa_root, [], test_ids_cmd=_emit(ledger[:20]))
    ids = facts["test_ids"]
    assert ids["removed_count"] == 180 and ids["added_count"] == 0
    assert len(ids["removed"]) == 50 and ids["truncated"] is True
    state = merge(facts, judgment(), None)
    assert "| +0/−180 |" in index_row(state), index_row(state)
    from verdict_mcp.harness import render_report
    line = [ln for ln in render_report(state).splitlines() if ln.startswith("Test-id ledger")][0]
    assert "+0 / −180" in line and "truncated to 50" in line, line


def test_index_row_dates_from_the_measured_stamp_not_the_local_clock(repo, qa_root):
    """VERDICT-F-24: `date.today()` on a UTC-7 host after 17:00 stamped the INDEX
    with yesterday, permanently, against a state stamped tomorrow in UTC."""
    state = merge(collect(repo, qa_root, []), judgment(), None)
    state["last_run"]["timestamp_utc"] = "2026-09-02T04:44:40Z"
    assert index_row(state).startswith("| 2026-09-02 |")
    state["last_run"]["timestamp_utc"] = ""
    assert index_row(state).startswith("| n/a |"), "measured or nothing — never composed"


def test_a_profiles_project_key_beats_the_directory_name(repo, qa_root):
    """VERDICT-F-23: run 4 executed from a clone named `verdict-clone` re-keyed
    the committed state and its INDEX to a second project name, because the
    harness derived identity from the directory and never read the profile."""
    for spelling in ("Project-Key: sales\n", "**Project-Key:** `sales`\n"):
        (qa_root / "profile.md").write_text(f"---\ngates: {{}}\n---\n{spelling}", encoding="utf-8")
        facts = collect(repo, qa_root, [])
        assert (facts["project"], facts["project_key_source"]) == ("sales", "profile"), spelling


def test_a_previous_states_key_beats_the_directory_name(repo, qa_root):
    (qa_root / "state.json").write_text(json.dumps({"project": "sales", "run_number": 3}),
                                        encoding="utf-8")
    facts = collect(repo, qa_root, [])
    assert (facts["project"], facts["project_key_source"]) == ("sales", "state")


def test_without_a_recorded_key_the_directory_name_stands(repo, qa_root):
    facts = collect(repo, qa_root, [])
    assert facts["project_key_source"] == "git" and facts["project"] == repo.name.lower()



def test_the_run_date_is_the_runs_own_utc_calendar_day():
    """VERDICT-F-54 moved every `first_seen`, `age_days` and report filename
    onto this one function, and run 12 listed it among the rules nothing
    watches (VERDICT-F-60).

    Three properties, each with an input that can tell it apart from a wrong
    one. The stamp is *translated* before parsing, because `fromisoformat`
    only learned to read a trailing `Z` in 3.11 and this project's floor is
    3.9 — on the 3.10 CI leg, dropping the translation makes every run fall
    back to today's date. The offset it is translated to is UTC, not some
    other hour. And an offset already in the stamp is converted rather than
    read off the wall clock.
    """
    from verdict_mcp.harness import run_date

    def at(stamp):
        return run_date({"last_run": {"timestamp_utc": stamp}})

    # Early morning UTC: a translation to any other offset moves the day.
    assert at("2026-09-06T00:30:00Z") == date(2026, 9, 6)
    # Late evening UTC, the other side of the same boundary.
    assert at("2026-09-05T23:30:00Z") == date(2026, 9, 5)
    # A non-UTC offset is converted, not taken at face value: 23:30 at -07:00
    # is already the next day in UTC.
    assert at("2026-09-05T23:30:00-07:00") == date(2026, 9, 6)
    # Unreadable stamps fall back rather than raising — the fallback is the
    # behaviour a missing translation would produce for EVERY stamp on 3.10.
    assert at("not a timestamp") == datetime.now(timezone.utc).date()
    assert at("") == datetime.now(timezone.utc).date()


@pytest.mark.parametrize("age_h, expected, forbidden", [
    (0.0, "seconds ago", "minute"),
    (0.05, "3 minutes ago", "hour"),
    (0.75, "45 minutes ago", "hour"),
    # The two boundaries, as literals rather than as arithmetic on the
    # constants under test: a probe derived from the constant moves with a
    # mutation of it and can only ever pass (the lesson of the 0.67.0
    # tolerance tests). Exactly 60 minutes is an hour, not "60 minutes ago",
    # and exactly 1.05 hours is where the phrase starts carrying a decimal.
    (1.0, "1 hour ago", "60 minutes"),
    (1.05, "1.1 hours ago", "1 hour ago"),
    (2.01, "2.0 hours ago", "minute"),
    (5.9, "5.9 hours ago", "minute"),
])
def test_the_retry_marker_says_the_age_it_recorded(age_h, expected, forbidden):
    """VERDICT-F-53: the retry window is six hours wide and every marker inside
    it was narrated as "minutes ago", so a live run published `age_hours: 2.01`
    beside a sentence calling it minutes old.

    Same shape as VERDICT-F-36 and VERDICT-F-45, which this project has now
    fixed three times: a rendered sentence contradicting the measured value
    printed next to it.
    """
    from verdict_mcp.harness import _ago
    assert _ago(age_h) == expected
    assert forbidden not in _ago(age_h)


def test_a_two_hour_old_retry_marker_is_not_described_as_minutes_old(repo, qa_root):
    """The end-to-end version: the phrase in `meaning` and the number in
    `age_hours` are written into the same object and must agree."""
    facts_args = [sys.executable, str(HARNESS), "facts", "--repo", str(repo),
                  "--qa-root", str(qa_root)]
    subprocess.run(facts_args, capture_output=True, text=True, check=True)
    marker = json.loads((qa_root / "run-in-progress.json").read_text(encoding="utf-8"))
    two_hours_ago = datetime.now(timezone.utc) - timedelta(hours=2, minutes=1)
    marker["started_utc"] = two_hours_ago.strftime("%Y-%m-%dT%H:%M:%SZ")
    (qa_root / "run-in-progress.json").write_text(json.dumps(marker), encoding="utf-8")

    out = json.loads(subprocess.run(facts_args, capture_output=True, text=True,
                                    check=True).stdout)
    attempt = out["previous_attempt_this_run"]
    assert 2.0 <= attempt["age_hours"] <= 2.2, attempt
    assert "hours ago" in attempt["meaning"], attempt["meaning"]
    assert "minutes ago" not in attempt["meaning"], attempt["meaning"]
    assert "this run's own retry" in attempt["meaning"], "still a retry, not a lost run"


def test_a_stale_bytecode_cache_can_hide_a_change_and_the_sweep_removes_it(tmp_path):
    """VERDICT-F-50: CPython validates a cached module on the source's mtime in
    WHOLE SECONDS plus its size, so a same-size rewrite that lands in the same
    second runs the previous version's bytecode with no sign anything is wrong.

    This is the mechanism behind a re-injection campaign that killed 4 of 5
    mutants with the cache in place and 5 of 5 once swept, while the check the
    contract prescribed — printing the loaded module's `__file__` — was right
    both times, because the path was never what was wrong.

    Note what the fix has to be. `PYTHONDONTWRITEBYTECODE` stops a cache being
    written; it does not stop an existing one being read. Only the sweep does.
    """
    from verdict_mcp.harness import _drop_bytecode
    mod = tmp_path / "probe.py"
    mod.write_text("VALUE = 'first'\n", encoding="utf-8")
    read = [sys.executable, "-c", "import probe; print(probe.VALUE)"]
    # Explicit, not inherited: a caller that already suppresses bytecode would
    # otherwise leave this test asserting on a cache that was never written,
    # and it would pass by never reaching the thing it is about.
    writes = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}

    first = subprocess.run(read, cwd=tmp_path, capture_output=True, text=True,
                           env=writes, check=True)
    assert first.stdout.strip() == "first"
    assert list(tmp_path.rglob("__pycache__")), "the cache this test is about"

    stamp = mod.stat().st_mtime
    mod.write_text("VALUE = 'secnd'\n", encoding="utf-8")   # same length, on purpose
    os.utime(mod, (stamp, stamp))                            # ...and the same second

    stale = subprocess.run(read, cwd=tmp_path, capture_output=True, text=True,
                           env=writes, check=True)
    assert stale.stdout.strip() == "first", "the defect: the cache outranks the source"

    _drop_bytecode(tmp_path)
    assert not list(tmp_path.rglob("__pycache__"))
    fresh = subprocess.run(read, cwd=tmp_path, capture_output=True, text=True,
                           env={**writes, "PYTHONDONTWRITEBYTECODE": "1"}, check=True)
    assert fresh.stdout.strip() == "secnd", "after the sweep the source decides"
    assert not list(tmp_path.rglob("__pycache__")), "and no new cache is left behind"


def test_fix_verification_runs_with_bytecode_writing_off(tmp_path, monkeypatch):
    """The other half of VERDICT-F-50: the harness must not create the cache it
    would then have to sweep. `_run_test` is where every verification
    subprocess is spawned, at HEAD and at the previous commit alike."""
    from verdict_mcp import harness
    seen = {}

    def fake_run(cmd, **kw):
        seen.update(kw.get("env") or {})
        return subprocess.CompletedProcess(cmd, 0, "1 passed", "")

    # Cleared first: inherited from the caller, this assertion holds whether or
    # not `_run_test` sets anything, which is a test that cannot fail.
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    harness._run_test("pytest {id}", "tests/t.py::x", tmp_path, tmp_path, 30)
    assert seen.get("PYTHONDONTWRITEBYTECODE") == "1"
