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
    outcome this whole tier is not allowed to have."""
    assert small.local_verdict("fail", [], [], True) == "fail"
    assert small.local_verdict("fail", [], [{"severity": "Minor"}], True) == "fail"
    assert small.local_verdict("pass with risks", [], [], True) == "pass with risks"
    assert small.local_verdict("pass", [], [], True) == "pass"
    assert small.local_verdict("pass", [{"severity": "Minor"}], [], True) == "pass with risks"
    assert small.local_verdict("pass", [], [{"severity": "Blocker"}], True) == "fail", \
        "a carried Blocker still fails the release"
    assert small.local_verdict("pass", [], [{"severity": "Critical"}], True) == "pass with risks"
    assert small.local_verdict("blocked", [], [], True) == "blocked"


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
