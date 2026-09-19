"""`verdict-local --delta`: the run that may never resolve a finding by silence.

The hazard a cheap engine really carries is not a wrong finding — a hypothesis
held at Minor costs a person five minutes to check. It is the silence of the
findings it never mentions: `merge()` reads an unmentioned finding as resolved
unless five or more AND over half the backlog goes quiet at once, so 0.88.0's
local mode, which wrote `still_open: []`, closed backlogs it had never looked at.

Every test here is about that: a prior open finding leaves a delta resolved by
measurement, carried by id, or re-filed with the drift that moved it, and never
any other way. The model is a stub with a script, because none of this is the
model's job.
"""

import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small  # noqa: E402
from verdict_mcp.harness import render_report  # noqa: E402

PY = f'"{sys.executable}"'
GATE = f"{PY} -m pytest -q -p no:cacheprovider --junitxml={{report}}"
IDS = f"{PY} -m pytest --collect-only -q -p no:cacheprovider"
ONE = f"{PY} -m pytest -q -p no:cacheprovider {{id}}"


MATCHES = {"verdict": "matches", "line": None, "mechanism": "the code does what it says"}


class ScriptedModel(small.Model):
    """A Model that answers from a script instead of from a gateway.

    A subclass rather than a stub, so the counters under test — calls, answered,
    unanswered, transport errors — are the real ones the run records. When the
    script runs out it falls back to `default`; `default=None` is the model that
    never produces usable JSON, which is a case with its own rule.
    """

    def __init__(self, replies=(), default=MATCHES, name="fake-8b"):
        super().__init__(name, "http://gateway.test:4000", "token")
        self.replies, self.default, self.prompts = list(replies), default, []

    def ask(self, prompt, max_tokens=1200):
        self.prompts.append(prompt)
        reply = self.replies.pop(0) if self.replies else self.default
        if reply is None:
            return "I am not sure."         # no JSON in it: counted unanswered
        self.calls += 1
        self.input_tokens += 100
        self.output_tokens += 20
        return reply if isinstance(reply, str) else json.dumps(reply)


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                           "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


CITED = "def rate(weight):\n    \"\"\"Cost per kilo.\"\"\"\n    return weight * 2\n"
TEST = "from cited import rate\n\n\ndef test_rate():\n    assert rate(2) == 4\n"


def project(tmp_path, profile_extra="", findings=None, judgment_extra=None):
    """A repo at run 1, finalized through the real harness, with anchors."""
    repo = tmp_path / "Proj"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    (repo / "cited.py").write_text(CITED, encoding="utf-8")
    (repo / "other.py").write_text("def other(x):\n    return x\n", encoding="utf-8")
    (repo / "test_cited.py").write_text(TEST, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    qa = tmp_path / "qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: {GATE}\ntest_ids_cmd: {IDS}\n{profile_extra}---\n\n"
        "# QA Profile — proj\n\nProject-Key: proj\n", encoding="utf-8")
    from verdict_mcp.harness import facts_main, finalize_main
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    judgment = {
        "topic": "baseline", "verdict": "pass with risks",
        "isolation_check": {"result": "pass"}, "release_blockers": [],
        "not_tested": ["concurrency"],
        "findings": findings if findings is not None else [{
            "id": "PROJ-F-1", "title": "rate doubles where the spec says triples",
            "severity": "Major", "priority": "P1", "status": "open",
            "failure_classification": "REAL_DEFECT", "confidence": "proven",
            "evidence": ["cited.py:3 — `return weight * 2`"]}],
    }
    judgment.update(judgment_extra or {})
    (qa / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")]) == 0
    return repo, qa


def state_of(qa):
    return json.loads((qa / "state.json").read_text(encoding="utf-8"))


def delta(repo, qa, model=None, **over):
    kwargs = dict(limit=4, gate=None, reruns=0, prove=False, delta=True)
    kwargs.update(over)
    return small.run(repo, qa, model or ScriptedModel(), **kwargs)


# ── the three places a prior finding may go ───────────────────────────────────

def test_a_drifted_finding_is_refiled_and_never_left_silent(tmp_path):
    """The exact case that cost the Sales key ten findings: the cited line moves,
    `still_open` over it is refused by the harness, and silence resolves it. The
    third option — re-file it under its own id with the drift as evidence — is
    the only honest one, and it is what this engine takes."""
    repo, qa = project(tmp_path)
    (repo / "cited.py").write_text(
        "def rate(weight):\n    \"\"\"Cost per kilo.\"\"\"\n    return weight * 2.0\n",
        encoding="utf-8")
    git(repo, "commit", "-qam", "touch the cited line")

    assert delta(repo, qa) == 0
    state = state_of(qa)
    found = [f for f in state["findings"] if f["id"] == "PROJ-F-1"]
    assert len(found) == 1, "one id is one finding"
    assert found[0]["status"] == "open", "a drifted finding is not resolved by silence"
    assert any("re-filed unread" in e for e in found[0]["evidence"]), \
        "the evidence has to say the code moved and that nothing read it"
    judgment = json.loads((qa / "judgment.json").read_text(encoding="utf-8"))
    assert judgment["still_open"] == [], "a drifted id may not be carried by the word"
    assert (qa / "findings" / "PROJ-F-1.json").is_file()


def test_silence_never_resolves_a_finding_in_a_local_delta(tmp_path):
    """Nothing moved, nothing was read, and the finding is still open — because
    the run said so by id, not because the merge's floor happened to hold."""
    repo, qa = project(tmp_path)
    (repo / "other.py").write_text("def other(x):\n    return x  # a comment\n",
                                   encoding="utf-8")
    git(repo, "commit", "-qam", "touch an uncited file")

    assert delta(repo, qa) == 0
    judgment = json.loads((qa / "judgment.json").read_text(encoding="utf-8"))
    assert judgment["still_open"] == ["PROJ-F-1"], "carried by id, explicitly"
    found = state_of(qa)["findings"][0]
    assert found["status"] == "open" and found["delta"] == "STILL_OPEN"
    assert "carried_forward" not in found, "it was reported, not left to the silence rule"


def test_the_partition_puts_every_prior_open_finding_in_exactly_one_place():
    """The unit behind the invariant. Three findings, three outcomes, no overlap."""
    previous = {"findings": [
        {"id": "P-F-1", "status": "open"},
        {"id": "P-F-2", "status": "open"},
        {"id": "P-F-3", "status": "open"},
        {"id": "P-F-4", "status": "resolved"},
        {"id": "P-F-5", "status": "accepted"},
    ]}
    facts = {
        "verification": {"P-F-1": {"at_previous": "fail", "at_head": "pass",
                                   "selected_by": "explicit", "test": "t::a"}},
        "evidence_drift": {"status": "measured", "findings": {
            "P-F-2": {"drift": "changed", "refs": [{"ref": "a.py:3", "status": "changed"}]},
            "P-F-3": {"drift": "unchanged", "refs": [{"ref": "b.py:1", "status": "unchanged"}]}}},
    }
    resolved, still_open, refile = small.partition_prior(previous, facts)
    assert resolved == ["P-F-1"]
    assert still_open == ["P-F-3"]
    assert [f["id"] for f, _d, _m in refile] == ["P-F-2"]
    assert small.carry_invariant(["P-F-1", "P-F-2", "P-F-3"], resolved, still_open,
                                 {"P-F-2"}) == []
    assert small.carry_invariant(["P-F-1", "P-F-9"], resolved, still_open, set()) == ["P-F-9"]


def test_a_resolution_needs_a_measured_fail_then_pass_on_a_chosen_test():
    """A test that merely passes at HEAD proves nothing — it may never have
    demonstrated the defect. `harness._chosen` draws the line for the agent; a
    cheaper engine gets no weaker rule."""
    passes_only = {"verification": {"F-1": {"at_previous": "pass", "at_head": "pass",
                                            "selected_by": "explicit"}}}
    assert small.measured_resolution(passes_only, "F-1") is None
    quoted = {"verification": {"F-1": {"at_previous": "fail", "at_head": "pass",
                                       "selected_by": "first_cited"}}}
    assert small.measured_resolution(quoted, "F-1") is None, \
        "a test quoted in prose is not a test somebody chose"
    real = {"verification": {"F-1": {"at_previous": "fail", "at_head": "pass",
                                     "selected_by": "added_this_run"}}}
    assert small.measured_resolution(real, "F-1") is not None
    assert small.measured_resolution({}, "F-1") is None


# ── the verdict ───────────────────────────────────────────────────────────────

def test_the_verdict_never_improves_on_its_own():
    """Six functions read by an 8B model may make a verdict worse or leave it
    alone. A `fail` that turns into `pass` because nobody looked is the single
    outcome this whole tier is not allowed to have.

    The cases that matter are the ones where this run DID find something: a
    standing `fail` beside a freshly filed Minor is exactly where an engine that
    scores only its own findings quietly promotes the verdict. (Pinned as P4,
    which survived the first campaign because these three lines were missing.)
    """
    assert small.local_verdict("fail", [], [], True) == "fail"
    assert small.local_verdict("fail", [], [{"severity": "Minor"}], True) == "fail"
    assert small.local_verdict("fail", [{"severity": "Minor"}], [], True) == "fail", \
        "a run that filed something of its own does not get to re-score the release"
    assert small.local_verdict("fail", [], [], True, cold_lines=4) == "fail"
    assert small.local_verdict("fail", [], [], True, ceiling="no code read") == "fail"
    assert small.local_verdict("fail", [], [{"severity": "Critical"}], True) == "fail"
    assert small.local_verdict("pass with risks", [], [], True) == "pass with risks"
    assert small.local_verdict("pass", [], [], True) == "pass"
    assert small.local_verdict("pass", [{"severity": "Minor"}], [], True) == "pass with risks"
    assert small.local_verdict("pass", [], [{"severity": "Blocker"}], True) == "fail", \
        "a carried Blocker still fails the release"
    assert small.local_verdict("pass", [], [{"severity": "Critical"}], True) == "pass with risks"


def test_a_standing_blocked_verdict_is_never_improved_by_a_local_run():
    """`blocked` is the harder half of the same rule, and the more expensive one
    to get wrong: the gate turns exit 3 into exit 0. `blocked` means a previous
    run could not test at all — an environment, a tool, a requirement nobody
    answered — and this engine cannot tell whether that reason has cleared."""
    assert small.local_verdict("blocked", [], [], True) == "blocked"
    assert small.local_verdict("blocked", [{"severity": "Minor"}], [], True) == "blocked", \
        "filing something of its own does not clear whatever blocked the last run"
    assert small.local_verdict("blocked", [], [], True, cold_lines=9) == "blocked"
    assert small.local_verdict("blocked", [], [], True, ceiling="no code read") == "blocked"
    assert small.local_verdict("blocked", [], [{"severity": "Critical"}], True) == "blocked"
    assert small.local_verdict("blocked", [], [{"severity": "Blocker"}], True) == "fail", \
        "worse is always allowed: an open Blocker fails whatever the standing verdict was"
    assert small.local_verdict("blocked", [], [], False) == "blocked"


def test_a_carried_blocked_verdict_says_why_it_was_carried(tmp_path):
    """A `blocked` that simply reappears reads like a run that re-judged it. The
    run says, in the list a reader checks, that it did not."""
    repo, qa = project(tmp_path, judgment_extra={"verdict": "blocked"})
    (repo / "other.py").write_text("def other(x):\n    return x  # c\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch an uncited file")

    assert delta(repo, qa) == 0
    state = state_of(qa)
    assert state["verdict"] == "blocked"
    assert small.CARRIED_BLOCKED in state["not_tested"]
    report = (qa / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "cannot tell whether what blocked it has cleared" in report


def test_no_gate_counts_is_blocked_not_pass():
    """Nothing measured says a test ran, so nothing says the code works."""
    assert small.local_verdict("pass", [], [], False) == "blocked"
    assert small.local_verdict(None, [], [], False) == "blocked"
    assert small.counts_measured({"gates": {"s": {"counts": {"passed": 3}}}}) is True
    assert small.counts_measured({"gates": {"s": {"counts_unparsed": "x"}}}) is False
    assert small.counts_measured({"gates": {}}) is False
    assert small.counts_measured({"no_gates": "none ran",
                                  "gates": {"s": {"counts": {"passed": 1}}}}) is False


def test_a_baseline_keeps_this_engines_own_arithmetic():
    """Nothing to carry and nothing to protect: the 0.88.0 rule stands, and the
    only thing added is the cap for code the run could not read."""
    assert small.local_verdict(None, [], [], True) == "pass"
    assert small.local_verdict(None, [{"severity": "Critical"}], [], True) == "fail"
    assert small.local_verdict(None, [], [], True, cold_lines=4) == "pass with risks"
    assert small.local_verdict(None, [], [], True, ceiling="no code read") == "pass with risks"


# ── the quarantine ────────────────────────────────────────────────────────────

def test_a_quarantine_is_released_by_measurement_not_by_its_expiry_date(tmp_path):
    """Five identical runs answer it exactly. An expiry is a date somebody wrote
    down, and releasing a test because that date passed is how a flaky test walks
    back into the set that blocks releases."""
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "test_steady.py").write_text("def test_steady():\n    assert True\n",
                                         encoding="utf-8")
    today = date(2026, 9, 17)
    due = [{"test_id": "test_steady.py::test_steady", "quarantined_until": "2026-09-01",
            "first_seen": "2026-08-01", "fail_count": 1, "run_count": 3, "reason": "flaky"}]
    kept, released, notes = small.requarantine(repo, due, ONE, today, runs=2)
    assert kept == [] and len(released) == 1
    assert "released from quarantine by measurement" in " ".join(notes)


def test_a_quarantine_that_still_fails_gets_a_new_expiry_with_measured_counts(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "test_bad.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    today = date(2026, 9, 17)
    due = [{"test_id": "test_bad.py::test_bad", "quarantined_until": "2026-09-01",
            "first_seen": "2026-08-01", "fail_count": 1, "run_count": 3, "reason": "flaky"}]
    kept, released, notes = small.requarantine(repo, due, ONE, today, runs=2)
    assert released == [] and len(kept) == 1
    assert kept[0]["quarantined_until"] == (today + timedelta(days=14)).isoformat()
    assert kept[0]["fail_count"] == 2 and kept[0]["run_count"] == 2
    assert "0 of 2 identical runs passed" in kept[0]["reason"]
    assert "quarantine extended by measurement" in " ".join(notes)


def test_a_quarantine_that_cannot_be_re_measured_is_kept_and_said_out_loud(tmp_path):
    """No `test_one_cmd`, no measurement — so no release, and a line a person can act on."""
    repo = tmp_path / "r"
    repo.mkdir()
    due = [{"test_id": "t::x", "quarantined_until": "2026-09-01"}]
    kept, released, notes = small.requarantine(repo, due, None, date(2026, 9, 17))
    assert kept == due and released == []
    assert "NOT re-measured" in notes[0] and "test_one_cmd" in notes[0]


def test_one_test_gets_one_quarantine_entry_and_one_finding(tmp_path):
    """A test already under an expiry that goes unstable again would otherwise be
    in the list twice — last run's counts and this run's — with nothing to say
    which expiry governs; and it would get a second finding id for one defect."""
    old = {"test_id": "t.py::x", "quarantined_until": "2099-01-01", "run_count": 3}
    fresh = {"test_id": "t.py::x", "quarantined_until": "2026-10-01", "run_count": 5}
    assert small.merge_quarantine([old], [fresh]) == [fresh], "this run's measurement wins"
    assert small.merge_quarantine([old], []) == [old]
    assert small.merge_quarantine([], []) == []

    previous = {"findings": [
        {"id": "P-F-4", "status": "open", "failure_classification": "FLAKY",
         "title": "t.py::x is not deterministic", "evidence": ["measured"]},
        {"id": "P-F-5", "status": "resolved", "failure_classification": "FLAKY",
         "title": "t.py::y is not deterministic"}]}
    assert small.flaky_findings_by_test(previous, ["t.py::x"]) == {"t.py::x": "P-F-4"}
    assert small.flaky_findings_by_test(previous, ["t.py::y"]) == {}, "resolved is not open"
    assert small.flaky_findings_by_test(None, ["t.py::x"]) == {}


def test_an_expiry_that_is_not_due_is_carried_verbatim(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    entry = {"test_id": "t::x", "quarantined_until": "2099-01-01"}
    kept, released, notes = small.requarantine(repo, [entry], ONE, date(2026, 9, 17))
    assert kept == [entry] and released == [] and notes == []


def test_the_previous_quarantine_and_verified_intact_survive_a_local_delta(tmp_path):
    """Both were wiped by 0.88.0: the quarantine because the judgment rebuilt it
    from this run's flakiness alone, verified_intact because it was written `[]`.
    A quarantine dropped by accident lets a flaky test block a release, and an
    intact list dropped by accident deletes the confirmation people pay for."""
    repo, qa = project(tmp_path, judgment_extra={
        "verified_intact": ["rate() never returns a negative cost"],
        "flaky_quarantine": [{"test_id": "test_cited.py::test_rate",
                              "quarantined_until": "2099-01-01",
                              "first_seen": "2026-09-01", "fail_count": 1, "run_count": 3,
                              "reason": "measured"}]})
    (repo / "other.py").write_text("def other(x):\n    return x  # c\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch an uncited file")

    assert delta(repo, qa) == 0
    state = state_of(qa)
    assert state["verified_intact"] == ["rate() never returns a negative cost"]
    assert [q["test_id"] for q in state["flaky_quarantine"]] == ["test_cited.py::test_rate"]


# ── the refusals ──────────────────────────────────────────────────────────────

def test_a_run_that_got_no_answers_writes_no_state(tmp_path):
    """Every question asked, none answered: a judgment assembled from that is a
    run that measured the suite and called it QA. It refuses, and leaves the run
    marker so tomorrow knows a night was lost."""
    repo, qa = project(tmp_path)
    (repo / "other.py").write_text("def other(x):\n    return x + 1\n", encoding="utf-8")
    git(repo, "commit", "-qam", "change other.py")
    before = state_of(qa)["run_number"]

    silent = ScriptedModel(default=None)       # never produces usable JSON
    assert delta(repo, qa, silent, limit=4) == 5
    assert silent.unanswered and not silent.answered
    assert state_of(qa)["run_number"] == before, "no state was written"
    assert (qa / "run-in-progress.json").is_file(), "the lost night leaves its marker"


def test_a_dead_gateway_is_named_before_the_suite_runs(tmp_path, monkeypatch, capsys):
    """Found at the first question, a dead gateway has already cost a whole suite
    run and left a marker claiming a run in progress. Found first, it costs one
    round trip."""
    repo, qa = project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gateway.test:4000")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    monkeypatch.setattr(small, "gateway_alive", lambda *a, **k: (False, "connection refused"))
    called = []
    monkeypatch.setattr(small, "run", lambda *a, **k: called.append(a) or 0)

    assert small.main(["--repo", str(repo), "--qa-root", str(qa)]) == 5
    assert called == [], "nothing was measured"
    err = capsys.readouterr().err
    assert "the gateway is not answering" in err and "connection refused" in err
    assert "not a QA pass" in err


# ── the record ────────────────────────────────────────────────────────────────

def test_the_engine_and_its_counters_land_in_last_run_and_in_the_report(tmp_path):
    """A report that names its harness and not its judge reads the same whether
    an Opus session or an 8B model on the desk wrote it."""
    repo, qa = project(tmp_path)
    (repo / "other.py").write_text("def other(x):\n    return x  # c\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch an uncited file")

    model = ScriptedModel()
    assert delta(repo, qa, model) == 0
    last = state_of(qa)["last_run"]
    assert last["engine"] == "verdict-local"
    assert last["local"]["host"] == "gateway.test"
    assert last["local"]["model"] == "fake-8b"
    assert last["local"]["calls"] == model.calls
    report = (qa / last["report"]).read_text(encoding="utf-8")
    assert "- Judge: verdict-local" in report
    assert "no Claude tokens spent" in report
    row = json.loads((qa / "usage.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["engine"] == "verdict-local"
    assert row["usage"]["requests"] == 0, "a measured zero, not an unknown"
    assert row["local"]["calls"] == model.calls


def test_a_sweep_still_says_none_where_the_judge_would_be():
    """The other half of the same rule: a run nobody judged must not look like a
    run somebody did."""
    state = {"run_type": "sweep", "project": "p", "run_number": 2, "verdict": "pass",
             "last_run": {"timestamp_utc": "2026-09-17T00:00:00Z", "report": "r.md"},
             "findings": [], "not_tested": ["x"]}
    assert "- Judge: none (model-free sweep)" in render_report(state)


def test_the_not_tested_list_is_counted_not_described(tmp_path):
    repo, qa = project(tmp_path)
    (repo / "other.py").write_text("def other(x):\n    return x  # c\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch an uncited file")

    assert delta(repo, qa) == 0
    lines = " ".join(state_of(qa)["not_tested"])
    assert "no agent ran" in lines and "no exploratory charter" in lines
    assert "1 of 1 prior open finding(s) were carried unread" in lines
    assert "nothing outside the checkout was read" in lines
    assert "no origin was traced" in lines


def test_the_focus_list_and_the_blockers_do_not_grow_forever():
    """A nightly that appends its own focus to the previous run's, every night,
    ends up with a list nobody reads — which is the same as not having one."""
    assert small._unique(["a", "b", "a", "b", "c"]) == ["a", "b", "c"]
    assert small._unique([]) == []


def test_a_state_on_disk_is_carried_even_when_the_delta_flag_was_forgotten(tmp_path):
    """The flag says what the operator expected; the state on disk says what the
    run must do. A caller that forgot it would otherwise get the 0.88.0 behaviour
    back — no prior finding mentioned, and the merge resolving the lot."""
    repo, qa = project(tmp_path)
    (repo / "other.py").write_text("def other(x):\n    return x  # c\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch an uncited file")

    assert delta(repo, qa, delta=False) == 0
    judgment = json.loads((qa / "judgment.json").read_text(encoding="utf-8"))
    assert judgment["still_open"] == ["PROJ-F-1"]
    assert state_of(qa)["findings"][0]["status"] == "open"


def test_a_first_run_in_an_empty_root_is_a_baseline_with_nothing_carried(tmp_path):
    repo = tmp_path / "Fresh"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    (repo / "m.py").write_text("def m(x):\n    return x\n", encoding="utf-8")
    (repo / "test_m.py").write_text("from m import m\n\n\ndef test_m():\n    assert m(1) == 1\n",
                                    encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "profile.md").write_text(f"---\ngates:\n  suite: {GATE}\n---\n\n# p\n\n"
                                   "Project-Key: fresh\n", encoding="utf-8")

    assert small.run(repo, qa, ScriptedModel(), limit=2, gate=None, reruns=0,
                     prove=False, delta=False) == 0
    state = state_of(qa)
    assert state["run_type"] == "baseline" and state["run_number"] == 1
    assert state["findings"] == [] and state["verdict"] == "pass"
    judgment = json.loads((qa / "judgment.json").read_text(encoding="utf-8"))
    assert judgment["still_open"] == [] and judgment["resolved"] == []


# ── the eval rig's wiring ─────────────────────────────────────────────────────

def test_the_eval_rig_can_drive_the_local_engine_with_no_network(tmp_path):
    """`run_eval --engine local` is scored by the same answer key as the agent.
    The point of running it there is not "does it find as much" — it will not —
    but the hard gate: it must never produce a false green. What is tested here
    is the wiring, through the seam the rig exposes for exactly that."""
    sys.path.insert(0, str(REPO / "eval"))
    import run_eval

    args = type("A", (), {"local_model": "qwen3", "local_limit": 6,
                          "local_env_file": None})()
    argv = run_eval.local_argv(Path("/checkout"), Path("/qa"), args, "delta")
    assert "--delta" in argv, "the seeded phase is a delta, and that is the question"
    assert "--qa-root" in argv and argv[argv.index("--limit") + 1] == "6"
    assert "--delta" not in run_eval.local_argv(Path("/c"), Path("/q"), args, "baseline")

    seen = {}

    def fake_engine(passed):
        seen["argv"] = list(passed)
        seen["home"] = os.environ.get("VERDICT_HOME")
        return 0

    log = tmp_path / "phase.log"
    run_eval.run_local_engine("/checkout", tmp_path / "home", "/qa", args, "delta", log,
                              engine=fake_engine)
    assert seen["home"] == str(tmp_path / "home"), "the rig's isolated QA home reaches it"
    assert "exit 0" in log.read_text(encoding="utf-8")
    assert os.environ.get("VERDICT_HOME") != str(tmp_path / "home"), "put back afterwards"

    with pytest.raises(RuntimeError, match="exited 5"):
        run_eval.run_local_engine("/checkout", tmp_path / "home", "/qa", args, "baseline",
                                  log, engine=lambda _argv: 5)


@pytest.mark.parametrize("drift,carried", [("unchanged", True), ("moved", True),
                                           ("unresolvable", True), ("changed", False),
                                           ("missing", False)])
def test_only_changed_and_missing_force_a_re_file(drift, carried):
    """`moved` means the harness found the line again, so the evidence still
    says what the finding says. `unresolvable` could not be measured at all, and
    the conservative reading of an unknown is to carry it, not to re-file it."""
    previous = {"findings": [{"id": "P-F-1", "status": "open"}]}
    facts = {"evidence_drift": {"status": "measured",
                                "findings": {"P-F-1": {"drift": drift, "refs": []}}}}
    resolved, still_open, refile = small.partition_prior(previous, facts)
    assert resolved == []
    assert (still_open == ["P-F-1"]) is carried
    assert (len(refile) == 1) is (not carried)


def test_the_engines_summary_goes_to_the_phase_log_not_into_the_result_json(tmp_path, capsys):
    """The first local proof printed verdict-local's summary ahead of the result JSON on the
    same stdout, and nothing that parses a result could read it."""
    sys.path.insert(0, str(REPO / "eval"))
    import run_eval

    args = type("A", (), {"local_model": "qwen3", "local_limit": 6, "local_env_file": None})()

    def chatty_engine(_argv):
        print("  model      qwen3 · 48 call(s) · Claude tokens: 0")
        return 0

    log = tmp_path / "phase.log"
    run_eval.run_local_engine("/checkout", tmp_path / "home", "/qa", args, "delta", log,
                              engine=chatty_engine)
    assert capsys.readouterr().out == "", "stdout is the result JSON's, and nothing else's"
    text = log.read_text(encoding="utf-8")
    assert "48 call(s)" in text and text.rstrip().endswith("exit 0")


# ── the window each question asks for ─────────────────────────────────────────

class _Reply:
    def __init__(self, doc):
        self._raw = json.dumps(doc).encode("utf-8")

    def read(self, *_a):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _gateway(monkeypatch, refuse_num_ctx=False):
    """A stand-in for `urlopen` that records each request body."""
    import io as _io
    import urllib.error
    bodies = []

    def urlopen(req, timeout=None):
        body = json.loads(req.data.decode("utf-8"))
        bodies.append(body)
        if refuse_num_ctx and "num_ctx" in body:
            raise urllib.error.HTTPError(req.full_url, 400, "Bad Request", {},
                                         _io.BytesIO(b'{"error": "Unrecognized argument: num_ctx"}'))
        return _Reply({"content": [{"type": "text", "text": '{"ok": true}'}],
                       "usage": {"input_tokens": 10, "output_tokens": 3}})

    monkeypatch.setattr(small.urllib.request, "urlopen", urlopen)
    return bodies


def test_each_question_asks_for_a_window_it_fits_in(monkeypatch):
    """At Ollama's default 4,096 tokens a long question loses its FRONT — the instructions
    and `/no_think` with them. Measured 2026-09-17: a ~6k-token prompt arrived as 2,050
    tokens and the model invented its answer; with `num_ctx: 8192` it arrived whole."""
    bodies = _gateway(monkeypatch)
    assert small.Model("qwen3", "http://gw", "t").ask_json("q") == {"ok": True}
    assert bodies[-1]["num_ctx"] == small.DEFAULT_NUM_CTX == 8192
    small.Model("qwen3", "http://gw", "t", num_ctx=0).ask_json("q")
    assert "num_ctx" not in bodies[-1], "0 leaves the server's own default alone"


def test_a_gateway_that_refuses_the_window_is_asked_again_without_it(monkeypatch, capsys):
    bodies = _gateway(monkeypatch, refuse_num_ctx=True)
    model = small.Model("qwen3", "http://gw", "t")
    assert model.ask_json("q") == {"ok": True}, "a refused parameter is not a failed question"
    assert "num_ctx" in bodies[0] and "num_ctx" not in bodies[1]
    assert model.num_ctx == 0 and model.errors == 0 and model.answered == 1
    assert "refused num_ctx" in capsys.readouterr().err
    model.ask_json("again")
    assert len(bodies) == 3 and "num_ctx" not in bodies[2], "asked once, remembered after"


def test_the_window_is_a_flag_and_an_environment_variable(monkeypatch):
    seen = {}
    monkeypatch.setattr(small, "Model", lambda *a, **k: seen.update(k) or (_ for _ in ()).throw(SystemExit(0)))
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gw")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")
    for argv, env, want in ((["--num-ctx", "16384"], None, 16384), ([], "12000", 12000), ([], None, 8192)):
        if env is None:
            monkeypatch.delenv("VERDICT_LOCAL_NUM_CTX", raising=False)
        else:
            monkeypatch.setenv("VERDICT_LOCAL_NUM_CTX", env)
        seen.clear()
        with pytest.raises(SystemExit):
            small.main(["--repo", str(REPO), *argv])
        assert seen.get("num_ctx") == want, (argv, env)


def test_a_red_suite_is_a_fail_whatever_the_findings_say():
    """Measured on the seeded delta, 2026-09-17: the tier carried all five prior findings
    honestly and still reported `pass with risks` over three failing tests, because the
    verdict was arithmetic over severities and an unproven reading is capped at Minor. A
    strong model may classify a failure and ship anyway; this one cannot be trusted to."""
    assert small.gate_failed({"gates": {"suite": {"result": "fail", "counts": {"failed": 3}}}})
    assert not small.gate_failed({"gates": {"suite": {"result": "pass", "counts": {"passed": 8}}}})
    assert not small.gate_failed({})

    assert small.local_verdict("pass with risks", [], [], True, gates_failed=True) == "fail"
    assert small.local_verdict("pass", [], [], True, gates_failed=True) == "fail"
    assert small.local_verdict(None, [], [], True, gates_failed=True) == "fail"
    assert small.local_verdict("pass", [], [], False, gates_failed=True) == "blocked", \
        "a suite that produced no counts at all is still `blocked`, not `fail`"
    assert small.local_verdict("pass with risks", [], [], True, gates_failed=False) \
        == "pass with risks", "a green suite is left where it was"


# ── a finding that already exists ─────────────────────────────────────────────

CLAIM = {"verdict": "mismatch", "line": 3,
         "mechanism": "rate multiplies by two where the docstring's spec says three"}
REAL = {"is_real": True, "severity": "Major", "title": "rate doubles instead of tripling",
        "impact": "every quote is a third too low"}


def test_a_resolved_finding_that_comes_back_is_regressed_not_new(tmp_path):
    """Measured on the seeded delta: the rounding defect the last run had resolved came
    back, the engine described it correctly and filed it as NEW — a regression reported
    as news. Its own id is what lets the harness call it REGRESSED, and rank it first."""
    repo, qa = project(tmp_path, findings=[{
        "id": "PROJ-F-1", "title": "rate doubles where the spec says triples",
        "severity": "Major", "priority": "P1", "status": "resolved",
        "failure_classification": "REAL_DEFECT", "confidence": "proven",
        "evidence": ["cited.py:3 — `return weight * 2`"]}])
    (repo / "other.py").write_text("def other(x):\n    return x + 0\n", encoding="utf-8")
    (repo / "cited.py").write_text(CITED + "\n# touched\n", encoding="utf-8")
    git(repo, "commit", "-qam", "the fix is reverted along with a touch")

    delta(repo, qa, ScriptedModel([CLAIM, REAL]))
    state = state_of(qa)
    back = [f for f in state["findings"] if f["id"] == "PROJ-F-1"]
    assert len(back) == 1 and back[0]["delta"] == "REGRESSED" and back[0]["status"] == "open"
    assert back[0]["title"] == "rate doubles where the spec says triples", "the id names that finding"
    assert any(e.startswith("REGRESSED — PROJ-F-1 was resolved") for e in back[0]["evidence"])
    assert not [f for f in state["findings"] if f.get("delta") == "NEW"], "and no NEW twin"


def test_a_claim_about_an_open_findings_function_is_not_filed_twice(tmp_path):
    """The same blindness filed a second finding for a defect already open — on a project
    with a backlog, a new duplicate every night the function changes."""
    repo, qa = project(tmp_path)
    (repo / "cited.py").write_text(CITED + "\n# touched\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch the function's file")

    delta(repo, qa, ScriptedModel([CLAIM, REAL]))
    state = state_of(qa)
    assert [f["id"] for f in state["findings"]] == ["PROJ-F-1"], "one defect, one finding"
    assert any("not filed again" in line and "PROJ-F-1" in line for line in state["not_tested"]), \
        "a claim that was not filed is still said"


def test_the_index_matches_by_line_first_by_name_second_and_never_by_a_common_name(tmp_path):
    repo = tmp_path / "r"
    repo.mkdir()
    (repo / "m.py").write_text("def round_cents(x):\n    return round(x, 2)\n\n"
                               "def main(x):\n    return x\n", encoding="utf-8")
    from verdict_mcp.anchors import line_sha
    anchored = {"id": "A-F-1", "status": "resolved", "title": "an old reading",
                "anchors": [{"path": "m.py", "line": 2,
                             "line_sha": line_sha(b"    return round(x, 2)")}]}
    named = {"id": "A-F-2", "status": "resolved", "title": "round_cents uses banker's rounding",
             "evidence": ["resolved in run 2"]}
    common = {"id": "A-F-3", "status": "open", "title": "main swallows errors"}
    elsewhere = {"id": "A-F-4", "status": "resolved", "title": "round_cents in another module",
                 "evidence": ["other.py:9 — round_cents"]}
    withdrawn = {"id": "A-F-5", "status": "withdrawn", "title": "round_cents is fine"}
    chunks = {c.name: c for c in small.chunks_of(repo, "m.py")}

    idx = small.PriorIndex({"findings": [withdrawn, elsewhere, named, anchored, common]})
    prior, status, how = idx.match(repo, chunks["round_cents"])
    assert prior["id"] == "A-F-1" and status == "resolved" and "line hash" in how, \
        "the measured link wins over the named one"

    idx = small.PriorIndex({"findings": [withdrawn, elsewhere, named, common]})
    prior, _, how = idx.match(repo, chunks["round_cents"])
    assert prior["id"] == "A-F-2" and "by name" in how, \
        "a finding citing another file does not claim this one; a withdrawn one never matches"
    assert idx.match(repo, chunks["main"]) == (None, None, None), "`main` names nothing"


# ── what the Sales shadow run taught (2026-09-18) ─────────────────────────────

def test_in_a_delta_an_unproven_reading_is_a_lead_not_a_finding(tmp_path):
    """27 unproven Minor readings in one Sales night, on top of 69 open findings. On a
    project with a record, what a small model read and could not prove is a question for
    a run that can judge it — in the report and the focus list, not in the state."""
    repo, qa = project(tmp_path)
    (repo / "other.py").write_text("def other(x):\n    \"\"\"Return x doubled.\"\"\"\n"
                                   "    return x\n", encoding="utf-8")
    git(repo, "commit", "-qam", "other() drifts from its docstring")
    claim = {"verdict": "mismatch", "line": 3,
             "mechanism": "other returns x where its docstring promises x doubled"}
    real = {"is_real": True, "severity": "Major", "title": "other forgets to double",
            "impact": "every caller gets half"}

    delta(repo, qa, ScriptedModel([claim, real]), prove=False)
    state = state_of(qa)
    assert [f["id"] for f in state["findings"]] == ["PROJ-F-1"], "nothing unproven was filed"
    assert any("listed as leads in the report" in x for x in state["not_tested"])
    assert any(x.startswith("lead, unproven: other.py:3 `other`") for x in state["next_run_focus"])
    report = (qa / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "**Leads — read by a small model, not proven, not filed (1).**" in report
    assert "other forgets to double" in report


def test_a_first_pass_over_a_fresh_project_still_files_what_it_reads(tmp_path):
    """The lead rule protects a record; a first pass has none to protect."""
    assert small.leads_text([]) == ""
    lines = small.leads_text([{"path": "a.py", "line": 3, "function": "f", "title": "t",
                               "severity": "Minor", "why": "w"}] * 30).splitlines()
    assert any("… and 5 more, not listed" in x for x in lines), "capped, and says so"


def test_a_night_on_a_project_with_a_record_has_a_budget(tmp_path, monkeypatch):
    """Measured on Sales: 4 h 10 min, 190 questions, 259 functions skipped at the cap. A
    night gets an hour, 24 functions and 12 proofs; a fresh project and a gate keep theirs."""
    seen = {}
    monkeypatch.setattr(small, "gateway_alive", lambda *a, **k: (True, "ok"))
    monkeypatch.setattr(small, "run", lambda *a, **k: seen.update(budget=k["budget"]) or 0)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://gw")
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "t")

    repo, qa = project(tmp_path)
    small.main(["--repo", str(repo), "--qa-root", str(qa), "--delta"])
    b = seen["budget"]
    assert (b.functions, b.probes, b.seconds) == (small.NIGHT_MAX_FUNCTIONS,
                                                  small.NIGHT_MAX_PROBES,
                                                  small.NIGHT_MODEL_BUDGET_S) == (24, 12, 3600)
    fresh = tmp_path / "fresh-qa"
    fresh.mkdir()
    small.main(["--repo", str(repo), "--qa-root", str(fresh)])
    b = seen["budget"]
    assert (b.functions, b.probes, b.seconds) == (small.MAX_FUNCTIONS, None, None)


def test_a_conflict_the_record_already_held_is_asked_not_refused(tmp_path):
    """Sales run 32 holds F-144 citing a line F-149 claims as a site of its class. A run that
    only carries both cannot settle it, and refusing it lost the whole night."""
    from verdict_mcp.validate import validate_judgment
    a = {"id": "S-F-1", "title": "a", "severity": "Major", "priority": "P1", "status": "open",
         "failure_classification": "REAL_DEFECT", "evidence": ["cfg.yaml:9 the live edit"]}
    b = {"id": "S-F-2", "title": "b", "severity": "Major", "priority": "P1", "status": "open",
         "failure_classification": "REAL_DEFECT", "evidence": ["x.py:1 the root"],
         "root_cause": {"mechanism": "m", "class": {"sites": ["cfg.yaml:9 the same edit"]}}}
    previous = {"findings": [a, b]}
    carried_only = {"verdict": "fail", "isolation_check": {"result": "pass"},
                    "release_blockers": [], "not_tested": ["x"], "findings": [],
                    "still_open": ["S-F-1", "S-F-2"], "resolved": []}
    assert not [p for p in validate_judgment(carried_only, previous, set()) if "site" in p]

    new = dict(a, id="S-F-3", confidence="hypothesis")
    filing = dict(carried_only, findings=[new])
    assert any("S-F-3 cites cfg.yaml:9" in p for p in validate_judgment(filing, previous, set())), \
        "a finding filed THIS run is still held to the rule"


def test_a_proof_imports_a_packaged_file_through_the_projects_own_root(tmp_path, monkeypatch):
    """Every Sales probe failed: `core/src/sales_core/cli.py` was imported from the repository
    root, so `sales_core`'s own imports reached a stale install elsewhere that lacked the day's
    new module. Reproduced here with a decoy package ahead on the path."""
    repo = tmp_path / "repo"
    pkg = repo / "core" / "src" / "shop"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "labels.py").write_text("WIDTH = 4\n", encoding="utf-8")
    (pkg / "cli.py").write_text("from shop.labels import WIDTH\n\ndef width():\n"
                                "    return WIDTH\n", encoding="utf-8")
    decoy = tmp_path / "decoy" / "shop"                 # an older install: no labels.py
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "decoy"))

    root, module = small.probe_root(repo, "core/src/shop/cli.py")
    assert (root, module) == (repo / "core" / "src", "shop.cli")
    value, err = small.run_probe(sys.executable, root, module, "m.width()")
    assert (value, err) == (4, None), err

    (repo / "pytest.ini").write_text("[pytest]\npythonpath = core/src\n", encoding="utf-8")
    assert small.import_roots(repo) == ["core/src"]
    assert small.probe_root(repo, "core/src/shop/cli.py") == (repo / "core" / "src", "shop.cli")


def test_a_declared_root_wins_and_a_plain_file_keeps_the_old_rule(tmp_path):
    repo = tmp_path / "repo"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "models.py").write_text("X = 1\n", encoding="utf-8")
    (repo / "pricer.py").write_text("X = 1\n", encoding="utf-8")
    assert small.probe_root(repo, "app/models.py") == (repo, "app.models"), "no package, no config"
    assert small.probe_root(repo, "pricer.py") == (repo, "pricer")
    (repo / "setup.cfg").write_text("[tool:pytest]\npythonpath = app\n", encoding="utf-8")
    assert small.probe_root(repo, "app/models.py") == (repo / "app", "models"), \
        "the project's own test runner says where imports start"


def test_the_night_with_an_inherited_conflict_finalizes_and_asks_once(tmp_path):
    """End to end, the Sales shape: the record already holds two findings claiming one site,
    the night carries both, and the run is recorded with the conflict parked as a question."""
    repo, qa = project(tmp_path, findings=[
        {"id": "PROJ-F-1", "title": "rate doubles where the spec says triples",
         "severity": "Major", "priority": "P1", "status": "open",
         "failure_classification": "REAL_DEFECT", "confidence": "proven",
         "evidence": ["cited.py:3 — `return weight * 2`"]},
        {"id": "PROJ-F-2", "title": "other passes its input through",
         "severity": "Minor", "priority": "P2", "status": "open",
         "failure_classification": "REAL_DEFECT", "confidence": "hypothesis",
         "evidence": ["other.py:2 — `return x`"],
         "root_cause": {"mechanism": "m", "class": {"sites": ["other.py:2 — the pass-through"]}}}])
    state = state_of(qa)
    for f in state["findings"]:            # an older run left the contradiction in the record
        if f["id"] == "PROJ-F-2":
            f["root_cause"]["class"]["sites"].append("cited.py:3 — claimed by PROJ-F-1 too")
    (qa / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (repo / "test_cited.py").write_text(TEST + "\n# touched\n", encoding="utf-8")
    git(repo, "commit", "-qam", "touch nothing a finding cites")

    assert delta(repo, qa) == 0, "the night is recorded, not refused"
    assert state_of(qa)["run_number"] == 2
    asked = json.loads((qa / "questions.json").read_text(encoding="utf-8"))
    texts = [q.get("question", "") for q in (asked.get("questions") or {}).values()]
    assert len(texts) == 1, "asked once"
    assert any("PROJ-F-1 cites cited.py:3" in t and "already held" in t for t in texts), texts


class _ByPrompt(ScriptedModel):
    """Answers by what is asked, not by order — for runs whose question order is the
    engine's business, not the test's."""

    def __init__(self, rules, default=MATCHES):
        super().__init__(default=default)
        self.rules = rules

    def ask(self, prompt, max_tokens=1200):
        for needle, reply in self.rules:
            if needle in prompt:
                self.prompts.append(prompt)
                self.calls += 1
                return json.dumps(reply)
        return super().ask(prompt, max_tokens)


def test_in_a_delta_a_models_opinion_that_a_green_test_is_brittle_is_a_lead(tmp_path):
    repo, qa = project(tmp_path)
    (repo / "test_cited.py").write_text(TEST + "\n\ndef test_rate_again():\n"
                                        "    assert rate(3) == 6\n", encoding="utf-8")
    git(repo, "commit", "-qam", "a second test")
    model = _ByPrompt([("currently passes", {"brittle": True, "line": 5,
                                             "why": "it pins the doubling the spec says is a bug"})])
    delta(repo, qa, model)
    state = state_of(qa)
    assert not [f for f in state["findings"] if f.get("failure_classification") == "BRITTLE_TEST"]
    report = (qa / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "may assert something incidental" in report, "said as a lead, in the report"


def test_a_counterfactual_proves_a_packaged_file_through_the_projects_root(tmp_path, monkeypatch):
    """The Sales failure, end to end through the proof itself: with the import rooted at the
    repository, `shop`'s own import reaches the decoy and the probe cannot run at all."""
    repo = tmp_path / "repo"
    pkg = repo / "core" / "src" / "shop"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "labels.py").write_text("WIDTH = 4\n", encoding="utf-8")
    (pkg / "cli.py").write_text("from shop.labels import WIDTH\n\n\ndef width():\n"
                                "    \"\"\"Twice the label width.\"\"\"\n    return WIDTH\n",
                                encoding="utf-8")
    decoy = tmp_path / "decoy" / "shop"
    decoy.mkdir(parents=True)
    (decoy / "__init__.py").write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "decoy"))

    chunk = next(c for c in small.chunks_of(repo, "core/src/shop/cli.py") if c.name == "width")
    model = ScriptedModel([{"expression": "m.width()", "fix_line": 6,
                            "fix_replacement": "    return WIDTH * 2"}])
    proof = small.counterfactual(model, repo, chunk,
                                 {"mechanism": "returns the width, not twice it", "line": 6},
                                 sys.executable)
    assert proof["status"] == "proven", proof
    assert (proof["before"], proof["after"]) == (4, 8)


def test_two_findings_with_one_identity_in_one_run_are_one_finding(tmp_path):
    """The harness knows a finding by its path and title and refuses a run that files one
    identity twice — on Sales that refusal cost the night. The second is folded into the
    first, its evidence added, and the run is recorded."""
    repo = tmp_path / "Two"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    (repo / "two.py").write_text("def f(x):\n    \"\"\"Double.\"\"\"\n    return x\n\n\n"
                                 "def g(x):\n    \"\"\"Double.\"\"\"\n    return x\n",
                                 encoding="utf-8")
    (repo / "test_two.py").write_text("from two import f\n\n\ndef test_f():\n"
                                      "    assert f(0) == 0\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "two")
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "profile.md").write_text(f"---\ngates:\n  suite: {GATE}\n---\n\nProject-Key: two\n",
                                   encoding="utf-8")
    same = {"is_real": True, "severity": "Minor", "title": "doubling is missing", "impact": "x"}
    model = _ByPrompt([("software tester reading one function", {
                           "verdict": "mismatch", "line": 3,
                           "mechanism": "returns x where the docstring promises double"}),
                       ("A defect has been claimed", same)])
    assert small.run(repo, qa, model, limit=4, gate=None, reruns=0, prove=False, delta=False) == 0
    mine = [f for f in state_of(qa)["findings"] if f["title"] == "doubling is missing"]
    assert len(mine) == 1, "one identity, one finding"
    assert sum("two.py:" in e for e in mine[0]["evidence"]) >= 2, "both sites are on it"


# ── what replaying the shadow night taught (2026-09-18) ───────────────────────

SKIPPED = ("import pytest\n\n\n@pytest.mark.skip(reason=\"the fixture file is not in the repo\")\n"
           "def test_later():\n    assert True\n")


def test_the_second_night_carries_what_the_first_filed_and_is_not_refused(tmp_path):
    """Replaying the first Sales shadow night's output: every skip marker it filed would come
    back on the second night, be filed again under a new id, and finalize refuses a state
    holding one identity twice — every night after the first would have been lost."""
    repo, qa = project(tmp_path)
    (repo / "test_skip.py").write_text(SKIPPED, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a skip with no expiry")
    assert delta(repo, qa) == 0
    first = [f["id"] for f in state_of(qa)["findings"] if "skipped with no expiry" in f["title"]]
    assert len(first) == 1

    (repo / "other.py").write_text("def other(x):\n    return x  # night two\n", encoding="utf-8")
    git(repo, "commit", "-qam", "night two")
    assert delta(repo, qa) == 0, "the second night is recorded, not refused"
    state = state_of(qa)
    assert state["run_number"] == 3
    again = [f for f in state["findings"] if "skipped with no expiry" in f["title"]]
    assert [f["id"] for f in again] == first, "one identity, one id, night after night"
    assert again[0]["status"] == "open" and again[0]["delta"] == "STILL_OPEN"
    assert any("already on the record" in x and f"{first[0]} (open)" in x
               for x in state["not_tested"]), "not filed again, and said"


def test_a_resolved_identity_that_comes_back_is_regressed_under_its_own_id(tmp_path):
    """A skip marker a person removed — its finding resolved — is put back. The regular
    expression finds it under the identity it was resolved under: its own id, REGRESSED."""
    scratch = tmp_path / "scan"             # the finding exactly as the scanner files it
    scratch.mkdir()
    (scratch / "test_skip.py").write_text(SKIPPED, encoding="utf-8")
    skip = small.group_skips(small.skips_without_expiry(scratch, ["test_skip.py"]))[0]
    gone = dict(small.skip_finding(skip, "PROJ-F-2"), status="resolved")
    repo, qa = project(tmp_path, findings=[
        {"id": "PROJ-F-1", "title": "rate doubles where the spec says triples",
         "severity": "Major", "priority": "P1", "status": "open",
         "failure_classification": "REAL_DEFECT", "confidence": "proven",
         "evidence": ["cited.py:3 — `return weight * 2`"]}, gone])
    (repo / "test_skip.py").write_text(SKIPPED, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the skip is back")

    assert delta(repo, qa) == 0
    state = state_of(qa)
    back = [f for f in state["findings"] if f["title"] == gone["title"]]
    assert [(f["id"], f["delta"], f["status"]) for f in back] == [("PROJ-F-2", "REGRESSED", "open")]
    assert any(e.startswith("REGRESSED — PROJ-F-2 was resolved") for e in back[0]["evidence"])


def test_a_failing_test_this_engine_filed_is_not_classified_again(tmp_path):
    """The model words a failure differently each night, so the identity rule alone would file
    a new duplicate every night the test stays red — and spend a question on it each time."""
    repo, qa = project(tmp_path)
    # A different size, not only different bytes: a same-size rewrite inside the second the
    # gate compiled the file reuses the cached bytecode, and the test stays green.
    (repo / "test_cited.py").write_text(TEST.replace("== 4", "== 6, 'the spec triples'"),
                                        encoding="utf-8")
    git(repo, "commit", "-qam", "a test goes red")

    def asked(title):
        return _ByPrompt([("classifying one failing test", {
            "classification": "REAL_DEFECT", "severity": "Major", "title": title,
            "mechanism": "rate doubles where the test expects triple"})])

    night_one = asked("rate(2) returns 4 where the test expects 6")
    delta(repo, qa, night_one)
    red = [f for f in state_of(qa)["findings"]
           if any(" fails at HEAD" in e for e in f.get("evidence") or [])]
    assert len(red) == 1 and red[0]["delta"] == "NEW"
    assert sum("classifying one failing test" in p for p in night_one.prompts) == 1

    (repo / "other.py").write_text("def other(x):\n    return x  # night two\n", encoding="utf-8")
    git(repo, "commit", "-qam", "night two, the test still red")
    night_two = asked("the rate test fails: doubling instead of tripling")
    assert delta(repo, qa, night_two) == 0
    state = state_of(qa)
    again = [f for f in state["findings"]
             if any(" fails at HEAD" in e for e in f.get("evidence") or [])]
    assert [f["id"] for f in again] == [red[0]["id"]], "the same failure, the same finding"
    assert not [p for p in night_two.prompts if "classifying one failing test" in p], \
        "and no question spent on it"
    assert any(f"{red[0]['id']} (open)" in x for x in state["not_tested"])


def test_a_range_with_nothing_in_it_reads_nothing(tmp_path):
    """The second Sales shadow night ran at the commit the first had measured. Its empty range
    fell through to the reading map — the least-covered files of the whole repository — and the
    run reported the range as larger than its caps. Nothing changed; nothing is read."""
    repo, qa = project(tmp_path)
    model = ScriptedModel()
    assert delta(repo, qa, model) == 0
    assert model.prompts == [], "no question about code no commit touched"
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert "diff_over_limit" not in (facts.get("needs_claude") or {})
    assert state_of(qa)["run_number"] == 2


def test_a_project_whose_ids_carry_no_prefix_files_and_finalizes(tmp_path):
    """The dress rehearsal on the Sales copy (2026-09-18): the next id was `F-163` — the record's
    own numbering — and finalize refused every finding file the night wrote, because the file
    rule still demanded `<PROJECT>-F-<n>.json`. The whole night was lost at its last step."""
    repo, qa = project(tmp_path, findings=[{
        "id": "F-1", "title": "rate doubles where the spec says triples",
        "severity": "Major", "priority": "P1", "status": "open",
        "failure_classification": "REAL_DEFECT", "confidence": "proven",
        "evidence": ["cited.py:3 — `return weight * 2`"]}])
    (repo / "test_skip.py").write_text(SKIPPED, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "a skip with no expiry")
    assert delta(repo, qa) == 0, "the night is recorded"
    ids = [f["id"] for f in state_of(qa)["findings"]]
    assert ids.count("F-2") == 1 and "F-1" in ids, ids
    from verdict_mcp.filed import finding_file
    assert finding_file(qa / "findings" / "F-2.json") == (qa, "F-2"), \
        "and the write-time check recognises the file as a finding"
