"""`verdict-local` over a named range: a PR gate that spends no Claude tokens.

Two things separate a gate run from a nightly, and each was a hazard in 0.88.0.
It has no previous state, so the range has to be supplied or diff coverage — the
one measurement a PR gate exists to make — is unavailable exactly where it
matters. And it runs on a branch, where `derive_key` returns the MAIN worktree's
key: pointed at the project's own state root, a judgment about a branch nobody
merged would overwrite the record of the trunk.

The third hazard is the quiet one. A range with no Python in it used to read
nothing and report `pass`. Here it reads nothing, says so in one fixed sentence,
and cannot rise above `pass with risks`.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small  # noqa: E402

from test_local_delta import ScriptedModel, git, state_of  # noqa: E402

PY = f'"{sys.executable}"'
GATE = f"{PY} -m pytest -q -p no:cacheprovider --junitxml={{report}}"
COVERAGE = f"{PY} -m coverage run -m pytest -q -p no:cacheprovider"

MOD = "def kept(x):\n    return x + 1\n"
TEST = "from mod import kept\n\n\ndef test_kept():\n    assert kept(1) == 2\n"


def branch_repo(tmp_path, second=None, extra_files=None):
    """Two commits, so a range exists → (repo, `BASE..HEAD`)."""
    repo = tmp_path / "Branchy"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    (repo / "mod.py").write_text(MOD, encoding="utf-8")
    (repo / "test_mod.py").write_text(TEST, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    base = git(repo, "rev-parse", "HEAD")
    if second is None and not extra_files:
        second = "def kept(x):\n    return x + 1  # the change under review\n"
    if second is not None:
        (repo / "mod.py").write_text(second, encoding="utf-8")
    for name, text in (extra_files or {}).items():
        (repo / name).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "the change under review")
    return repo, f"{base}..HEAD"


def throwaway_root(tmp_path, coverage=False, name="pr.qa"):
    """The `.qa/` a branch run is given: the key's profile, and nothing else."""
    qa = tmp_path / name
    qa.mkdir()
    extra = f"coverage_suite_cmd: {COVERAGE}\n" if coverage else ""
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: {GATE}\n{extra}---\n\n# QA Profile — branchy\n\n"
        "Project-Key: branchy\n", encoding="utf-8")
    return qa


def gate_run(repo, qa, sha_range, model=None, **over):
    kwargs = dict(limit=4, gate=None, reruns=0, prove=False, sha_range=sha_range)
    kwargs.update(over)
    return small.run(repo, qa, model or ScriptedModel(), **kwargs)


# ── the range ─────────────────────────────────────────────────────────────────

def test_a_supplied_range_drives_diff_coverage(tmp_path):
    """No previous state, so the harness would derive no range at all and report
    diff coverage unavailable — on the one run whose entire question is the diff."""
    repo, sha_range = branch_repo(
        tmp_path, second="def kept(x):\n    return x + 1\n\n\ndef added(x):\n    return x * 2\n")
    qa = throwaway_root(tmp_path, coverage=True)

    assert gate_run(repo, qa, sha_range) == 0
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert facts["last_run"]["sha_range"] == sha_range
    cov = facts["coverage"]
    assert cov["status"] == "measured", cov
    assert cov["per_file"]["mod.py"]["unexercised_functions"] == ["added"]
    assert state_of(qa)["run_type"] == "baseline", "a first run here carries nothing"


def test_a_range_run_reads_the_diff_not_the_reading_map(tmp_path):
    """The ranking for a delta is the change, not the least-covered module in the
    repository: re-reading that spends the night re-deriving yesterday's findings."""
    facts = {"coverage": {"status": "measured",
                          "per_file": {"b.py": {"unexercised_ranges": [[1, 3]]}}},
             "reading_map": {"lowest": [{"path": "never_touched.py"}]}}
    repo = Path("/nowhere")
    assert small.delta_candidates(facts, repo, []) == [], \
        "no range at all: the reading map is the fallback, and it has no real files here"
    ranked = small.delta_candidates(facts, REPO, ["src/verdict_mcp/small.py"])
    assert ranked == ["src/verdict_mcp/small.py"]
    assert small.delta_candidates(facts, REPO, ["app.ts", "README.md"]) == [], \
        "a range with no Python reads nothing rather than falling back to the whole repo"


def test_a_typescript_only_diff_reads_nothing_and_says_so(tmp_path):
    """A green gate over a diff this engine cannot read is not a QA pass, and the
    report has to be the one that says that out loud."""
    repo, sha_range = branch_repo(tmp_path, extra_files={
        "app.ts": "export const rate = (w: number) => w * 2;\n"})
    qa = throwaway_root(tmp_path)

    model = ScriptedModel()
    assert gate_run(repo, qa, sha_range, model) == 0
    state = state_of(qa)
    assert state["verdict"] == "pass with risks", "the ceiling holds over unread code"
    assert any(small.NO_CODE_READ in line for line in state["not_tested"])
    assert model.calls == 0, "nothing was asked, because nothing was readable"
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert "non_python_diff" in facts["needs_claude"]


# ── the state root a branch may not touch ─────────────────────────────────────

def test_a_range_without_a_qa_root_is_refused(tmp_path, capsys):
    repo, sha_range = branch_repo(tmp_path)
    assert small.main(["--repo", str(repo), "--range", sha_range,
                       "--env-file", str(_env_file(tmp_path))]) == 2
    err = capsys.readouterr().err
    assert "--range/--base needs --qa-root" in err
    assert "MAIN worktree's project key" in err


def _env_file(tmp_path) -> Path:
    path = tmp_path / "gw.env"
    path.write_text("ANTHROPIC_BASE_URL=http://gateway.test:4000\n"
                    "ANTHROPIC_AUTH_TOKEN=t\n", encoding="utf-8")
    return path


def test_a_branch_run_never_writes_the_keys_state_root(tmp_path, monkeypatch):
    """P-31, end to end: the key's own root is left exactly as it was, and
    everything this run wrote is inside the throwaway directory it was given."""
    repo, sha_range = branch_repo(tmp_path)
    qa = throwaway_root(tmp_path)
    home = tmp_path / "verdict-home"
    key_root = home / "branchy"
    (key_root / "reports").mkdir(parents=True)
    (key_root / "state.json").write_text(json.dumps({"run_number": 7}), encoding="utf-8")
    monkeypatch.setenv("VERDICT_HOME", str(home))
    monkeypatch.setattr(small, "gateway_alive", lambda *a, **k: (True, "200"))
    monkeypatch.setattr(small, "Model", lambda *a, **k: ScriptedModel())
    before = sorted(p.name for p in key_root.iterdir())

    assert small.main(["--repo", str(repo), "--range", sha_range, "--qa-root", str(qa),
                       "--reruns", "0", "--no-prove",
                       "--env-file", str(_env_file(tmp_path))]) == 0
    assert json.loads((key_root / "state.json").read_text(encoding="utf-8")) == {"run_number": 7}
    assert sorted(p.name for p in key_root.iterdir()) == before
    assert (qa / "state.json").is_file(), "the throwaway root is what was written"


def test_the_reference_state_is_read_and_never_written(tmp_path):
    """The branch run wants to know which of the project's open findings this
    range touches, and that lives in the real state — so it is read, once, and
    the file is byte-identical afterwards."""
    repo, sha_range = branch_repo(tmp_path, second="def kept(x):\n    return x + 2\n")
    qa = throwaway_root(tmp_path)
    reference = tmp_path / "main-state.json"
    reference.write_text(json.dumps({"findings": [
        {"id": "BRANCHY-F-9", "status": "open", "evidence": ["mod.py:2 — the guard"]},
        {"id": "BRANCHY-F-8", "status": "open", "evidence": ["elsewhere.py:1"]},
        {"id": "BRANCHY-F-7", "status": "resolved", "evidence": ["mod.py:2"]}]}), encoding="utf-8")
    before = reference.read_bytes()

    assert gate_run(repo, qa, sha_range, reference_state=reference) == 0
    assert reference.read_bytes() == before, "the project's own record was not touched"
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert facts["needs_claude"]["touches_open_finding"] == ["BRANCHY-F-9"], \
        "an open finding citing a changed file, and only that one"


def test_touches_findings_reads_anchors_and_cited_evidence():
    reference = {"findings": [
        {"id": "F-1", "status": "open", "anchors": [{"path": "a.py", "line": 2}]},
        {"id": "F-2", "status": "open", "evidence": ["b.py:9 — the guard"]},
        {"id": "F-3", "status": "open", "evidence": ["c.py:1"]},
        {"id": "F-4", "status": "resolved", "anchors": [{"path": "a.py", "line": 3}]}]}
    assert small.touches_findings(reference, ["a.py", "b.py"]) == ["F-1", "F-2"]
    assert small.touches_findings(None, ["a.py"]) == []


# ── what a model would still be owed ──────────────────────────────────────────

def test_needs_claude_names_every_measured_reason():
    """Not advice and not a score: each entry is something the harness counted,
    so "this gate is green, and here is what it never asked" is checkable."""
    facts = {"coverage": {"status": "measured", "changed_lines": 10,
                          "changed_lines_executed": 4}}
    filed = [{"id": "F-1", "severity": "Major", "confidence": "hypothesis"},
             {"id": "F-2", "severity": "Major", "confidence": "proven"},
             {"id": "F-3", "severity": "Minor", "confidence": "hypothesis"}]
    owed = small.needs_claude(facts, filed, [{"id": "F-9"}], ["F-4"], 2, True, True)
    assert owed["unexercised_changed_lines"] == 6
    assert owed["touches_open_finding"] == ["F-4"]
    assert owed["unprovable_high_severity"] == ["F-1"], \
        "a proven one needs nothing, and a Minor is not worth a model run"
    assert owed["drift_unsettled"] == ["F-9"]
    assert owed["questions_parked"] == 2
    assert "non_python_diff" in owed and "diff_over_limit" in owed
    assert small.needs_claude({}, [], [], [], 0, False, False) == {}, \
        "nothing measured, nothing claimed"


def test_the_unexercised_count_is_zero_when_coverage_was_not_measured():
    assert small.unexercised_diff({}) == 0
    assert small.unexercised_diff({"coverage": {"status": "unavailable"}}) == 0
    assert small.unexercised_diff({"coverage": {"status": "measured", "changed_lines": 0}}) == 0
    assert small.unexercised_diff({"coverage": {"status": "measured", "changed_lines": 5,
                                                "changed_lines_executed": 5}}) == 0


# ── the caps ──────────────────────────────────────────────────────────────────

def test_the_model_budget_stops_and_reports_what_it_skipped():
    budget = small.Budget(functions=2)
    assert budget.take_function() and budget.take_function()
    assert not budget.take_function()
    assert budget.skipped == 1 and "cap of 2 function(s)" in budget.stopped
    spent = small.Budget(functions=99, seconds=0)
    assert not spent.take_function()
    assert "model budget ran out" in spent.stopped


def test_the_probe_cap_leaves_a_claim_a_hypothesis():
    budget = small.Budget(probes=1)
    assert budget.take_probe() and not budget.take_probe()
    assert small.Budget().take_probe() is True, "no cap unless one is asked for"


def test_a_capped_run_says_how_many_functions_it_never_asked_about(tmp_path):
    repo, sha_range = branch_repo(tmp_path, second=(
        "def kept(x):\n    return x + 1\n\n\ndef two(x):\n    return x\n\n\n"
        "def three(x):\n    return x\n"))
    qa = throwaway_root(tmp_path)

    assert gate_run(repo, qa, sha_range, budget=small.Budget(functions=1)) == 0
    lines = " ".join(state_of(qa)["not_tested"])
    assert "candidate function(s) were never asked about" in lines
    assert "cap of 1 function(s) was reached" in lines


def test_a_gate_run_takes_the_caps_without_being_told(tmp_path, monkeypatch):
    """The defaults are the product decision: six files, twenty-four functions,
    six probes, two minutes a call and fifteen minutes of model time."""
    repo, sha_range = branch_repo(tmp_path)
    qa = throwaway_root(tmp_path)
    monkeypatch.setattr(small, "gateway_alive", lambda *a, **k: (True, "200"))
    monkeypatch.setattr(small, "Model", lambda *a, **k: ScriptedModel())
    seen = {}

    def spy(repo_, qa_, model_, limit, gate, reruns, prove=True, **kw):
        seen.update(limit=limit, budget=kw.get("budget"), sha_range=kw.get("sha_range"))
        return 0

    monkeypatch.setattr(small, "run", spy)
    assert small.main(["--repo", str(repo), "--range", sha_range, "--qa-root", str(qa),
                       "--env-file", str(_env_file(tmp_path))]) == 0
    assert seen["limit"] == small.GATE_MAX_FILES
    assert seen["budget"].functions == small.GATE_MAX_FUNCTIONS
    assert seen["budget"].probes == small.GATE_MAX_PROBES
    assert seen["budget"].seconds == small.GATE_MODEL_BUDGET_S
    assert seen["sha_range"] == sha_range


def test_a_base_ref_is_resolved_through_the_merge_base(tmp_path):
    """`main..HEAD` after somebody else merges reads their commits as this
    branch's change; the merge base asks the question that was meant."""
    repo, _ = branch_repo(tmp_path)
    resolved = small.resolve_range(repo, None, "main")
    assert resolved and resolved.endswith("..HEAD")
    assert small.resolve_range(repo, "a..b", "main") == "a..b", "an explicit range wins"
    assert small.resolve_range(repo, None, None) is None
    assert small.resolve_range(repo, None, "no-such-ref") is None


def test_chunks_are_narrowed_to_the_lines_the_range_touched(tmp_path):
    source = ("def one(x):\n    return x\n\n\ndef two(x):\n    return x\n\n\n"
              "def three(x):\n    return x\n")
    (tmp_path / "m.py").write_text(source, encoding="utf-8")
    assert [c.name for c in small.chunks_in_range(tmp_path, "m.py", {5, 6})] == ["two"]
    assert [c.name for c in small.chunks_in_range(tmp_path, "m.py", None)] == \
        ["one", "two", "three"]
    assert [c.name for c in small.chunks_in_range(tmp_path, "m.py", {99})] == \
        ["one", "two", "three"], "lines outside every function fall back to the file"


def test_changed_files_names_what_the_range_touched(tmp_path):
    repo, sha_range = branch_repo(tmp_path, extra_files={"app.ts": "export const x = 1;\n"})
    assert small.changed_files(repo, sha_range) == ["app.ts"]
    assert small.changed_files(repo, None) == []
    assert small.changed_files(repo, "nope..nope") == []


def test_the_liveliness_probe_reads_a_real_answer(tmp_path):
    """The one HTTP test in the engine, against a server this test starts: a
    liveliness check that always returns True is not a check."""
    import http.server
    import threading

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):                                   # noqa: N802 — stdlib's name
            self.send_response(200 if self.path.endswith("liveliness") else 404)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        base = f"http://127.0.0.1:{server.server_address[1]}"
        alive, detail = small.gateway_alive(base, "token", timeout_s=5)
        assert alive and "200" in detail
    finally:
        server.shutdown()
        server.server_close()
    dead, why = small.gateway_alive("http://127.0.0.1:1", "token", timeout_s=2)
    assert dead is False and "unreachable" in why


def test_subprocess_calls_here_name_their_encoding():
    """The Windows lesson this repository learned twice: a subprocess without an
    explicit encoding decodes with the console's code page."""
    assert subprocess.run([sys.executable, "-c", "print('ok')"], capture_output=True,
                          text=True, encoding="utf-8").stdout.strip() == "ok"
