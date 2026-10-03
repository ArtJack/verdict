"""The probe sandbox — audit 2026-10-02, O-S-1 (Critical), O-D-5 and O-D-11.

Measured on 2026-10-02 with a fake gateway (`probe_small2.py`): the counterfactual ran the
model's expression in the REAL checkout first, with the operator's whole environment —
`env_has_token=True` beside the repository's own path — and the scratch copy it ran second
carried every `.env` file in the tree. The expression itself had passed three checks: one
line, names the function, the fix line is inside the chunk. Nothing else.

Every test here fails against the code the audit read. Each one pins a different wall:
the expression is a syntax tree the harness has read before anything runs; both runs happen
in a scratch copy; the child's environment is an allowlist; secrets never reach the copy;
every probe is on the record; a profile or a flag can switch the whole thing off; and the
interpreter is the one the gate runs, or none.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small  # noqa: E402
from verdict_mcp.validate import validate_finding  # noqa: E402

from test_local_delta import _ByPrompt, git  # noqa: E402
from test_local_gate import GATE, ScriptedModel, _env_file, branch_repo, state_of  # noqa: E402
from test_small import FakeModel  # noqa: E402

# The audit's own proof expression, verbatim in shape: a side effect smuggled through
# `open(...).write(...)` and `__import__`, returning truthy so the probe "succeeds".
AUDIT_EXPRESSION = ("m.f(open('/tmp/x', 'a').write(__import__('os').getcwd() + ' env_has_token='"
                    " + str('ANTHROPIC_AUTH_TOKEN' in __import__('os').environ) + '\\n') or 1)")


def _refuse_subprocess(monkeypatch):
    """Any child process started is the failure under test."""
    def boom(*a, **k):
        raise AssertionError(f"a subprocess was started: {a[0] if a else k}")
    monkeypatch.setattr(small.subprocess, "run", boom)


def _recorder_repo(tmp_path, marker: Path):
    """A git checkout whose one function writes where it ran and what it could see.

    The marker sits OUTSIDE the repository, and its path is a literal in the module —
    the only channel left once the environment is an allowlist and the expression a
    literal call."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text(
        "import os\n\n\n"
        f"MARKER = {str(marker)!r}\n\n\n"
        "def f(x):\n"
        '    """Return x plus two."""\n'
        "    with open(MARKER, 'a', encoding='utf-8') as fh:\n"
        "        fh.write(os.getcwd() + ' ' + os.path.realpath(__file__) + ' token='\n"
        "                 + str('ANTHROPIC_AUTH_TOKEN' in os.environ) + '\\n')\n"
        "    return x + 1\n", encoding="utf-8")
    git(repo, "init", "-qb", "main")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo


# ── O-S-1 (4): the expression is read as a syntax tree before anything runs ───

def test_the_audits_proof_expression_is_refused_before_any_subprocess(tmp_path, monkeypatch):
    """The exact shape the audit ran on 2026-10-02. It passed every check the code had —
    one line, names `f`, the fix line inside the chunk — and executed in the checkout."""
    _refuse_subprocess(monkeypatch)
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text('def f(x):\n    """x plus two."""\n    return x + 1\n',
                               encoding="utf-8")
    chunk = small.chunks_of(repo, "m.py")[0]
    model = FakeModel([{"expression": AUDIT_EXPRESSION, "fix_line": 3,
                        "fix_replacement": "    return x + 2"}])
    proof = small.counterfactual(model, repo, chunk, {"mechanism": "off by one", "line": 3},
                                 sys.executable)
    assert proof["status"] == "unavailable"
    assert proof["reason"].startswith("probe_unsafe:"), proof
    assert proof["expression"].startswith("m.f(open(") and proof["scratch"] is None, \
        "a refused probe is on the record too, with the text it refused"


@pytest.mark.parametrize("expression", [
    "m.round_cents(1.005)",
    "m.round_cents()",
    "m.round_cents(-1, 2.5, 'two', None, True, b'x')",
    "m.round_cents([1, (2, 3)], {'k': {4, 5}}, places=-2, label='x')",
])
def test_a_literal_call_on_the_function_under_probe_is_accepted(expression):
    text, why = small.safe_probe(expression, "round_cents")
    assert why is None and text == expression, (text, why)


@pytest.mark.parametrize("expression", [
    "m.round_cents(__import__('os').system('x'))",   # a call inside an argument
    "os.getcwd()",                                   # not on m
    "m.f(g())",                                      # a nested call
    "m.f(x)",                                        # a name
    "m.__dict__",                                    # not a call, and a dunder
    "m.__class__()",                                 # a dunder call
    "(lambda: 1)()",                                 # a lambda
    "m.f(*a)",                                       # starred
    "m.f(**k)",                                      # unpacked keywords
    "m.f(1).g",                                      # an attribute chain after the call
    "m.f(1)[0]",                                     # a subscript
    "m.f(1) + 1",                                    # not a single call
    "m.f(f'{1}')",                                   # an f-string
    "m.f([i for i in ()])",                          # a comprehension
    "m.g(1)",                                        # a different function of m
    "m.f(1); m.g(2)",                                # two statements
    "import os",                                     # not an expression at all
    "",
])
def test_anything_else_is_refused_as_probe_unsafe_and_never_run(expression, tmp_path, monkeypatch):
    _refuse_subprocess(monkeypatch)
    text, why = small.safe_probe(expression, "f")
    assert text is None and why.startswith("probe_unsafe:"), (expression, text, why)
    # and through the whole counterfactual, where it used to reach a subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    chunk = small.Chunk("m.py", "f", 1, 2, "def f(x):\n    return x + 1")
    proof = small.counterfactual(FakeModel([{"expression": expression, "fix_line": 2,
                                             "fix_replacement": "    return x + 2"}]),
                                 repo, chunk, {"mechanism": "off by one", "line": 2},
                                 sys.executable)
    assert proof["status"] == "unavailable", proof
    reason = proof["reason"]
    assert reason.startswith("probe_unsafe:") or "not one expression" in reason \
        or "does not call f" in reason, proof


def test_run_probe_itself_refuses_an_unsafe_expression(tmp_path, monkeypatch):
    """The second wall: `run_probe` is the only path to a child process, so it checks the
    expression too — a caller that forgot `safe_probe` cannot run arbitrary code."""
    _refuse_subprocess(monkeypatch)
    root = tmp_path / "t"
    root.mkdir()
    (root / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    value, err = small.run_probe(sys.executable, root, "m", "__import__('os').getcwd()")
    assert value is None and err.startswith("probe_unsafe:")


# ── O-S-1 (1): both runs in the scratch, the checkout untouched ───────────────

def test_both_probes_run_in_the_scratch_copy_and_the_checkout_is_untouched(tmp_path, monkeypatch):
    """Measured 2026-10-02: the "before" probe ran with `cwd=<repo>` and the real tree on
    `PYTHONPATH`, so a function with a side effect — or one that talks to a marketplace —
    ran against the checkout and whatever its config imports. Now the tree is copied once,
    the original is probed in the copy, the copy is patched, and the patched copy is probed."""
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "fake")   # as runner.run_local leaves it
    marker = tmp_path / "probe-runs.log"
    repo = _recorder_repo(tmp_path, marker)
    chunk = small.chunks_of(repo, "m.py")[0]
    model = FakeModel([{"expression": "m.f(1)", "fix_line": 12,
                        "fix_replacement": "    return x + 2"}])
    proof = small.counterfactual(model, repo, chunk, {"mechanism": "adds one, not two",
                                                      "line": 12}, sys.executable)
    assert proof["status"] == "proven", proof
    assert (proof["before"], proof["after"]) == (2, 3)

    runs = marker.read_text(encoding="utf-8").splitlines()
    assert len(runs) == 2, runs
    real = os.path.realpath(str(repo))
    scratch = os.path.realpath(proof["scratch"])
    for line in runs:
        cwd, file, token = line.split(" ")
        assert not os.path.realpath(cwd).startswith(real), f"ran in the checkout: {line}"
        assert os.path.realpath(cwd).startswith(scratch), f"ran outside the scratch: {line}"
        assert file.startswith(scratch), f"imported the checkout's module: {line}"
        assert token == "token=False", f"the gateway token reached the probe: {line}"
    assert git(repo, "status", "--porcelain") == "", "the checkout must come back untouched"
    assert proof["expression"] == "m.f(1)" and "verdict-cf-" in proof["scratch"]


# ── O-S-1 (2): the child's environment is an allowlist ────────────────────────

def test_the_probe_environment_is_an_allowlist(tmp_path, monkeypatch):
    """Measured 2026-10-02: `env=dict(os.environ, …)` handed the probe the gateway token
    the nightly exports, and whatever else launchd's environment holds."""
    for name in ("ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY", "VERDICT_MODEL",
                 "CLAUDE_CODE_OAUTH_TOKEN", "GH_TOKEN", "AWS_SECRET_ACCESS_KEY",
                 "SOME_KEY", "A_SECRET", "OP_SERVICE_ACCOUNT_TOKEN", "DATABASE_URL"):
        monkeypatch.setenv(name, "fake")
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    monkeypatch.setenv("PYTHONPATH", str(decoy))
    root = tmp_path / "t"
    root.mkdir()
    (root / "m.py").write_text(
        "import os\n\n\ndef f():\n"
        "    return {'keys': sorted(os.environ), 'pythonpath': os.environ.get('PYTHONPATH')}\n",
        encoding="utf-8")
    value, err = small.run_probe(sys.executable, root, "m", "m.f()")
    assert err is None, err
    keys = set(value["keys"])
    leaked = {k for k in keys if k.startswith(("ANTHROPIC_", "VERDICT_", "CLAUDE_", "AWS_", "OP_"))
              or k.endswith(("_TOKEN", "_KEY", "_SECRET", "_URL"))}
    assert leaked == set(), f"reached the probe: {sorted(leaked)}"
    home = "USERPROFILE" if os.name == "nt" else "HOME"      # Windows has no HOME to keep
    assert {"PATH", home, "PYTHONDONTWRITEBYTECODE", "PYTHONPATH"} <= keys, sorted(keys)
    assert str(decoy) not in (value["pythonpath"] or ""), \
        "the parent's PYTHONPATH is not the scratch's import path"
    assert os.path.realpath(value["pythonpath"].split(os.pathsep)[0]) == os.path.realpath(str(root))


# ── O-S-1 (3): secrets never reach the copy ───────────────────────────────────

def test_secret_files_are_left_out_of_the_scratch_copy(tmp_path):
    """`COPY_SKIP` listed `.git` and the virtualenvs and nothing else, so the scratch copy
    carried every `.env` in the tree — and the module under probe imports its config."""
    repo, into = tmp_path / "repo", tmp_path / "into"
    (repo / "config").mkdir(parents=True)
    planted = [".env", ".env.local", ".env.production", "server.pem", "private.key",
               "id_rsa", "id_rsa.pub", ".netrc", ".npmrc", ".pypirc", "credentials.json",
               "credentials-prod.json", "cert.p12", "cert.pfx", "secrets.yaml",
               "config/.env", "config/secrets.toml", "config/service.key"]
    for rel in planted:
        (repo / rel).write_text("SECRET=1\n", encoding="utf-8")
    (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "config" / "settings.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "environment.py").write_text("z = 3\n", encoding="utf-8")   # not a secret
    assert small.scratch_copy(repo, into) is True
    copied = sorted(p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file())
    assert copied == ["config/settings.py", "environment.py", "m.py"], copied


# ── O-S-1 (5): every probe is on the record ───────────────────────────────────

def _probe_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    return repo, small.Chunk("m.py", "f", 1, 2, "def f(x):\n    return x + 1")


def test_every_outcome_carries_the_expression_the_scratch_and_the_status(tmp_path):
    repo, chunk = _probe_repo(tmp_path)
    claim = {"mechanism": "off by one", "line": 2}
    proven = small.counterfactual(FakeModel([{"expression": "m.f(1)", "fix_line": 2,
                                              "fix_replacement": "    return x + 2"}]),
                                  repo, chunk, claim, sys.executable)
    disproven = small.counterfactual(FakeModel([{"expression": "m.f(1)", "fix_line": 1,
                                                 "fix_replacement": "def f(x):"}]),
                                     repo, chunk, claim, sys.executable)
    broken = small.counterfactual(FakeModel([{"expression": "m.f(1)", "fix_line": 2,
                                              "fix_replacement": "    return x +"}]),
                                  repo, chunk, claim, sys.executable)
    unsafe = small.counterfactual(FakeModel([{"expression": "m.f(g())", "fix_line": 2,
                                              "fix_replacement": "    return x + 2"}]),
                                  repo, chunk, claim, sys.executable)
    silent = small.counterfactual(FakeModel([None]), repo, chunk, claim, sys.executable)
    for proof in (proven, disproven, broken, unsafe, silent):
        assert {"status", "reason", "expression", "scratch"} <= set(proof), proof
    assert proven["status"] == "proven" and "verdict-cf-" in proven["scratch"]
    assert disproven["status"] == "disproven" and disproven["scratch"]
    assert broken["status"] == "unavailable" and "probe failed on the scratch" in broken["reason"]
    assert broken["expression"] == "m.f(1)" and broken["scratch"]
    assert unsafe["reason"].startswith("probe_unsafe:") and unsafe["scratch"] is None
    assert silent["expression"] == "" and silent["scratch"] is None


def test_the_finding_evidence_names_the_scratch_and_a_failed_probe(tmp_path):
    repo, chunk = _probe_repo(tmp_path)
    claim = {"mechanism": "off by one", "line": 2, "path": "m.py", "severity": "Major",
             "title": "adds one", "impact": "i", "function": "f"}
    proven = small.counterfactual(FakeModel([{"expression": "m.f(1)", "fix_line": 2,
                                              "fix_replacement": "    return x + 2"}]),
                                  repo, chunk, claim, sys.executable)
    entry = small.finding_of(claim, "P-F-1", chunk.source, proven)
    assert "COUNTERFACTUAL" in entry["evidence"][0]
    assert proven["scratch"] in entry["evidence"][0], "the record says where it ran"
    assert validate_finding(entry, "findings/P-F-1.json", set()) == []

    failed = small.counterfactual(FakeModel([{"expression": "m.f(1)", "fix_line": 2,
                                              "fix_replacement": "    return x +"}]),
                                  repo, chunk, claim, sys.executable)
    entry = small.finding_of(claim, "P-F-2", chunk.source, failed)
    assert entry["confidence"] == "hypothesis"
    assert entry["evidence"][0].startswith("m.py:2"), "the first line is still the citation"
    probe_line = entry["evidence"][-1]
    assert probe_line.startswith("PROBE") and "`m.f(1)`" in probe_line
    assert failed["scratch"] in probe_line and "unavailable" in probe_line, probe_line
    assert validate_finding(entry, "findings/P-F-2.json", set()) == []


def test_a_secret_in_the_expression_is_scrubbed_from_the_record(tmp_path, monkeypatch):
    """A string literal is the one thing the allowlist lets through, and a model that
    copied a key out of a docstring would put it on the record. The expression is
    scrubbed with the hygiene scan's own scrub before it is written anywhere."""
    _refuse_subprocess(monkeypatch)
    repo, chunk = _probe_repo(tmp_path)
    key = "sk-ant-api03-" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8S9t0U1v2W3x4Y5z6A7b8C9d0E1f2G3h4I5j6K7l8M9n0-AbCdEfGh"
    proof = small.counterfactual(FakeModel([{"expression": f"m.g({key!r})", "fix_line": 2,
                                             "fix_replacement": "    return x + 2"}]),
                                 repo, chunk, {"mechanism": "x", "line": 2}, sys.executable)
    assert key not in json.dumps(proof), proof
    assert key not in proof["reason"]


def test_the_run_writes_the_probe_ledger_into_facts(tmp_path):
    """`facts.json` says what ran: one row per probe, with the expression and where."""
    repo, sha_range = branch_repo(tmp_path)          # the gate stays green; the claim is scripted
    qa = _gate_root(tmp_path)
    assert small.run(repo, qa, _claiming_model(), limit=4, gate=None, reruns=0, prove=True,
                     sha_range=sha_range) == 0
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    ledger = facts["probes"]
    assert len(ledger) == 1, ledger
    row = ledger[0]
    assert row["path"] == "mod.py" and row["function"] == "kept"
    assert row["expression"] == "m.kept(1)" and row["status"] == "proven"
    assert "verdict-cf-" in row["scratch"]
    assert "probes" not in facts["last_run"]["local"], \
        "the ledger is not in the block usage.jsonl copies per run"
    assert [f["confidence"] for f in state_of(qa)["findings"]] == ["proven"]


# ── O-S-1 (4b): a profile or a flag switches probes off ───────────────────────

def _gate_root(tmp_path, extra=""):
    qa = tmp_path / "pr.qa"
    qa.mkdir()
    (qa / "profile.md").write_text(f"---\ngates:\n  suite: {GATE}\n{extra}---\n\n"
                                   "Project-Key: b\n", encoding="utf-8")
    return qa


def _claiming_model():
    """Claims `kept` is wrong and offers a probe that flips it: `x + 1` → `x + 2`."""
    return _ByPrompt([
        ("Does the code do exactly", {"verdict": "mismatch", "line": 2,
                                      "mechanism": "adds one where two was meant"}),
        ("A defect has been claimed", {"is_real": True, "severity": "Major", "title": "adds one",
                                       "impact": "every caller is one too low"}),
        ("Give me two things", {"expression": "m.kept(1)", "fix_line": 2,
                                "fix_replacement": "    return x + 2"}),
    ])


@pytest.mark.parametrize("how", ["profile", "flag"])
def test_probes_off_means_no_counterfactual_is_ever_called(tmp_path, monkeypatch, how):
    """`probes: off` in the profile — what a money project sets — or `--max-probes 0`:
    nothing is executed, and `not_tested` says which switch did it."""
    def never(*a, **k):
        raise AssertionError("counterfactual was called with probes off")
    monkeypatch.setattr(small, "counterfactual", never)
    repo, sha_range = branch_repo(tmp_path)
    qa = _gate_root(tmp_path, "probes: off\n" if how == "profile" else "")
    budget = small.Budget(probes=0) if how == "flag" else None
    assert small.run(repo, qa, _claiming_model(), limit=4, gate=None, reruns=0, prove=True,
                     sha_range=sha_range, budget=budget) == 0
    state = state_of(qa)
    lines = state["not_tested"]
    assert any(f"probes disabled by {how}" in x for x in lines), lines
    assert [f["confidence"] for f in state["findings"]] == ["hypothesis"]
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert facts["probes"] == []


def test_probes_off_is_read_the_way_hygiene_off_is():
    assert small.probes_off({"probes": "off"}) and small.probes_off({"probes": "False"})
    assert small.probes_off({"probes": "no"})
    assert not small.probes_off({}) and not small.probes_off({"probes": "on"})
    assert not small.probes_off({"probes": "nope"}), "a typo must not switch a control off"


# ── O-D-5: the default local model answers ────────────────────────────────────

def test_the_default_local_model_is_chat_not_qwen3(tmp_path, monkeypatch, capsys):
    """DECISIONS.md 2026-09-25: on the `qwen3` alias every call thinks through its budget
    and answers nothing (1 of 9 answered), and the run exits 5 after the whole suite."""
    monkeypatch.delenv("VERDICT_LOCAL_MODEL", raising=False)
    repo, _ = branch_repo(tmp_path)
    seen = {}
    monkeypatch.setattr(small, "gateway_alive", lambda *a, **k: (True, "200"))
    monkeypatch.setattr(small, "Model",
                        lambda name, *a, **k: seen.update(name=name) or ScriptedModel())
    monkeypatch.setattr(small, "run", lambda *a, **k: 0)
    assert small.main(["--repo", str(repo), "--qa-root", str(tmp_path / "qa"),
                       "--env-file", str(_env_file(tmp_path))]) == 0
    assert seen["name"] == "chat"
    with pytest.raises(SystemExit):
        small.main(["--help"])
    assert "qwen3" not in capsys.readouterr().out, "the help must not name the alias that answers nothing"


# ── O-D-11: the interpreter is the one the gate runs, or none ─────────────────

def test_a_venv_tool_resolves_to_the_python_beside_it():
    assert small.interpreter_of(".venv/bin/pytest -q") == ".venv/bin/python"
    assert small.interpreter_of("/x/.venv/bin/python -m pytest") == "/x/.venv/bin/python"
    assert small.interpreter_of("PYTHONDONTWRITEBYTECODE=1 /x/.venv/bin/python3.12 -m pytest") \
        == "/x/.venv/bin/python3.12"
    assert small.interpreter_of('"/a b/.venv/bin/python" -m pytest') == "/a b/.venv/bin/python", \
        "a quoted path is one token"
    assert small.interpreter_of("cd core && .venv/bin/coverage run -m pytest") == ".venv/bin/python"


def test_a_quoted_windows_path_is_one_word():
    """Found by the first Windows CI run of 0.90.3: whitespace splitting cut a quoted
    interpreter path in two and the gate's own python was never found."""
    words = small._gate_tokens(r'"C:\Program Files\Python312\python.exe" -m pytest -q', windows=True)
    assert words == [r"C:\Program Files\Python312\python.exe", "-m", "pytest", "-q"]
    assert small._gate_tokens("'/a b/bin/python' -m pytest", windows=True)[0] == "/a b/bin/python"
    assert small._gate_tokens('"/a b/.venv/bin/python" -m pytest', windows=False)[0] \
        == "/a b/.venv/bin/python"
    assert small._gate_tokens('unterminated "quote', windows=True) == ["unterminated", '"quote']


def test_uv_run_asks_uv_once_for_its_interpreter(tmp_path, monkeypatch):
    calls = []

    def fake_run(argv, **kw):
        calls.append((argv, kw))
        return subprocess.CompletedProcess(argv, 0, stdout="/proj/.venv/bin/python\n", stderr="")

    monkeypatch.setattr(small.subprocess, "run", fake_run)
    small._RUNNER_PYTHON.clear()
    assert small.interpreter_of("uv run pytest -q", tmp_path) == "/proj/.venv/bin/python"
    assert small.interpreter_of("uv run pytest -q", tmp_path) == "/proj/.venv/bin/python"
    assert len(calls) == 1, "asked once, cached"
    argv, kw = calls[0]
    assert argv[:3] == ["uv", "run", "python"] and "sys.executable" in argv[-1]
    assert kw["cwd"] == str(tmp_path) and kw["timeout"] == 30

    def failing(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="no project found")

    monkeypatch.setattr(small.subprocess, "run", failing)
    small._RUNNER_PYTHON.clear()
    assert small.interpreter_of("uv run pytest", tmp_path) is None


def test_a_bare_tool_is_found_on_path_and_a_non_python_gate_is_none(monkeypatch):
    monkeypatch.setattr(small.shutil, "which",
                        lambda name: {"pytest": "/w/bin/pytest", "python": "/w/bin/python"}.get(name))
    assert small.interpreter_of("pytest -q") == "/w/bin/python"
    assert small.interpreter_of("python -m pytest") == "/w/bin/python"
    assert small.interpreter_of("python3 -m pytest") is None, "not on PATH: none, not ours"
    for gate in ("npm test", "go test ./...", "cargo test", "make check", "dotnet test"):
        assert small.interpreter_of(gate) is None, gate
    assert small.interpreter_of("npm test") is not sys.executable


def test_a_gate_with_no_python_disables_proving_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr(small, "interpreter_of", lambda command, repo=None: None)
    def never(*a, **k):
        raise AssertionError("counterfactual was called with no interpreter")
    monkeypatch.setattr(small, "counterfactual", never)
    repo, sha_range = branch_repo(tmp_path)
    qa = _gate_root(tmp_path)
    assert small.run(repo, qa, _claiming_model(), limit=4, gate=None, reruns=0, prove=True,
                     sha_range=sha_range) == 0
    lines = state_of(qa)["not_tested"]
    assert any("proving disabled: no Python interpreter in the gate" in x for x in lines), lines


# ── the replacement line is code too (0.90.3, the orchestrator's addition) ───────────
#
# The expression is a syntax tree the harness has read; the line the model writes in
# place of the suspected one runs as well — in the scratch, under the allowlisted
# environment, but with the operator's privileges. A fix may use only what the function
# already uses.

@pytest.mark.parametrize("fix", [
    "    import os; os.system('x')",
    "    return __import__('os').system('x')",
    "    return open('/etc/passwd').read()",
    "    return x.__class__.__mro__",
    '    return f"{x}"',
    "    return eval('x')",
    "    return subprocess.run(['x'])",
    "    from os import system",
])
def test_a_fix_that_introduces_a_name_is_refused_before_any_copy(fix, tmp_path, monkeypatch):
    repo, chunk = _probe_repo(tmp_path)
    _refuse_subprocess(monkeypatch)
    proof = small.counterfactual(
        FakeModel([{"expression": "m.f(1)", "fix_line": 2, "fix_replacement": fix}]),
        repo, chunk, {"mechanism": "off by one", "line": 2}, sys.executable)
    assert proof["status"] == "unavailable", proof
    assert proof["reason"].startswith("fix_unsafe"), proof
    assert proof["scratch"] is None, "no copy was made for a refused fix"


@pytest.mark.parametrize("fix", [
    "    return x + 2", "    return max(x, 0) + 1", "    return x if x else 0",
    "    return abs(x) - 1  # the boundary",
])
def test_a_fix_made_of_the_functions_own_names_is_allowed(fix):
    assert small.safe_replacement(fix, "def f(x):\n    return x + 1\n") is None
