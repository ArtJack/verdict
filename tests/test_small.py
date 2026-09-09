"""Local mode: the harness drives, the model answers.

Everything deterministic here is Python's job, and these tests hold it — because the
whole premise of running on a 7B model is that the model is asked as little as possible.
A wrong line number, a JSON reply the parser refuses, or a claim filed as `proven` would
each turn a cheap run into a misleading one.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small  # noqa: E402
from verdict_mcp.validate import validate_finding  # noqa: E402

MODULE = '''"""A module."""


def alpha(price, floor):
    """At or above the floor."""
    return price > floor


class Holder:
    def beta(self):
        """Two lines."""
        return 1
'''


def test_extract_json_survives_prose_and_fences():
    assert small.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert small.extract_json('Sure! Here it is:\n{"a": 1}\nHope that helps.') == {"a": 1}
    assert small.extract_json('[1,2]\n{"a": 2}') == {"a": 2}, "an array first is skipped"
    assert small.extract_json("no json at all") is None
    assert small.extract_json("") is None


def test_chunks_carry_the_files_own_line_numbers(tmp_path):
    (tmp_path / "m.py").write_text(MODULE, encoding="utf-8")
    chunks = {c.name: c for c in small.chunks_of(tmp_path, "m.py")}
    assert set(chunks) == {"alpha", "beta"}, "methods are questions too"
    alpha = chunks["alpha"]
    assert alpha.start == 4 and alpha.end == 6
    assert alpha.numbered().splitlines()[0].startswith("   4| def alpha")
    assert "   6|     return price > floor" in alpha.numbered(), \
        "the model points at a line of the file, not of the excerpt"


def test_chunks_clamp_a_huge_function_and_survive_a_broken_file(tmp_path):
    body = "\n".join(f"    x = {i}" for i in range(400))
    (tmp_path / "big.py").write_text(f"def huge():\n{body}\n", encoding="utf-8")
    chunk = small.chunks_of(tmp_path, "big.py")[0]
    assert chunk.end - chunk.start == small.MAX_SOURCE_LINES
    (tmp_path / "bad.py").write_text("def broken(:\n", encoding="utf-8")
    assert small.chunks_of(tmp_path, "bad.py") == []
    assert small.chunks_of(tmp_path, "absent.py") == []


def test_candidates_follow_the_reading_map_then_fall_back(tmp_path):
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("x = 1\n", encoding="utf-8")
    facts = {"reading_map": {"lowest": [{"path": "b.py"}, {"path": "a.py"}, {"path": "gone.py"}],
                             "never_imported": [{"path": "a.py"}]}}
    assert small.candidates(facts, tmp_path) == ["b.py", "a.py"], \
        "least covered first, missing files dropped, no duplicates"
    got = small.candidates({}, tmp_path)
    assert set(got) == {"a.py", "b.py"}, "no coverage measured: read the tracked source"


class FakeModel:
    """Answers from a script, so the deterministic half can be tested without a model."""

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def ask_json(self, prompt, max_tokens=1200):
        self.asked.append(prompt)
        return self.answers.pop(0) if self.answers else None


def _chunk():
    return small.Chunk("m.py", "alpha", 4, 6, "def alpha(price, floor):\n    return price > floor")


def test_examine_files_a_claim_only_when_both_answers_agree():
    model = FakeModel([
        {"verdict": "mismatch", "line": 5, "mechanism": "returns price > floor, spec says >="},
        {"is_real": True, "severity": "Critical", "title": "boundary excludes the floor",
         "impact": "a price exactly at the floor is refused"},
    ])
    claim = small.examine(model, _chunk())
    assert claim["line"] == 5 and claim["severity"] == "Critical"
    assert "floor" in claim["title"]
    assert len(model.asked) == 2
    assert "mechanism" in model.asked[1] or "Claim:" in model.asked[1], \
        "the second question carries the claim as text, not as conversation history"


def test_examine_stops_at_the_first_answer_when_the_code_matches():
    model = FakeModel([{"verdict": "matches", "line": None, "mechanism": "fine"}])
    assert small.examine(model, _chunk()) is None
    assert len(model.asked) == 1, "no second call is spent on a function that is fine"


def test_examine_refuses_an_empty_mechanism_and_a_denied_second_opinion():
    assert small.examine(FakeModel([{"verdict": "mismatch", "mechanism": "bad"}]), _chunk()) is None
    model = FakeModel([{"verdict": "mismatch", "mechanism": "returns > instead of >="},
                       {"is_real": False, "severity": "Major", "title": "x"}])
    assert small.examine(model, _chunk()) is None


@pytest.mark.parametrize("line", [1, 999, None, "five"])
def test_a_line_outside_the_function_falls_back_to_its_first_line(line):
    model = FakeModel([{"verdict": "mismatch", "line": line,
                        "mechanism": "returns > instead of >="},
                       {"is_real": True, "severity": "Major", "title": "t", "impact": "i"}])
    assert small.examine(model, _chunk())["line"] == 4


def test_an_unknown_severity_is_not_trusted():
    model = FakeModel([{"verdict": "mismatch", "line": 5, "mechanism": "returns > not >="},
                       {"is_real": True, "severity": "CATASTROPHIC", "title": "t", "impact": "i"}])
    assert small.examine(model, _chunk())["severity"] == "Minor"


def test_a_finding_from_local_mode_is_a_hypothesis_and_validates():
    claim = {"function": "alpha", "path": "m.py", "line": 5, "severity": "Critical",
             "title": "boundary excludes the floor", "mechanism": "returns > instead of >=",
             "impact": "a price at the floor is refused"}
    entry = small.finding_of(claim, "PRICER-F-1", "def alpha(price, floor):")
    assert entry["confidence"] == "hypothesis", \
        "nothing was executed; claiming proof is the flattery this project rejects"
    assert entry["evidence"][0].startswith("m.py:5")
    assert "not executed" in entry["evidence"][0]
    assert validate_finding(entry, "findings/PRICER-F-1.json", set()) == []


def test_ask_json_retries_then_gives_up():
    class Flaky(small.Model):
        def __init__(self, replies):
            super().__init__("m", "http://x", "t")
            self.replies = list(replies)

        def ask(self, prompt, max_tokens=1200):
            return self.replies.pop(0)

    good = Flaky(["not json", '{"ok": 1}'])
    assert good.ask_json("q") == {"ok": 1} and good.retries == 1
    # three attempts, because a small model's reply parses about half the time
    bad = Flaky(["nope", "still nope", "and again"])
    assert bad.ask_json("q") is None and bad.retries == 3


def test_read_env_file_and_a_missing_one(tmp_path, capsys):
    path = tmp_path / "e"
    path.write_text("# c\nANTHROPIC_BASE_URL='http://gw:4000'\n", encoding="utf-8")
    assert small.read_env_file(path) == {"ANTHROPIC_BASE_URL": "http://gw:4000"}
    assert small.main(["--env-file", str(tmp_path / "absent")]) == 2
    assert "does not exist" in capsys.readouterr().err


def test_the_run_refuses_without_an_endpoint(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    assert small.main([]) == 2
    assert "ANTHROPIC_BASE_URL" in capsys.readouterr().err


def test_the_console_script_is_declared():
    assert 'verdict-local = "verdict_mcp.small:main"' in \
        (REPO / "pyproject.toml").read_text(encoding="utf-8")


def test_the_judgment_says_what_local_mode_did_not_do():
    source = (REPO / "src" / "verdict_mcp" / "small.py").read_text(encoding="utf-8")
    assert '"not_tested"' in source
    assert "no origin was traced" in source, \
        "a pass must always name what was not tested; local mode tests almost nothing"


def test_finding_json_is_written_only_after_the_validator_accepts_it():
    source = (REPO / "src" / "verdict_mcp" / "small.py").read_text(encoding="utf-8")
    i, j = source.index("problems = validate_finding"), source.index("write_text(json.dumps(entry")
    assert i < j, "a rejected finding must never reach the findings directory"


def test_an_error_class_the_interpreter_names_needs_no_model():
    """Asking a model whether a FileNotFoundError is an environment failure spends a call
    to learn nothing — and when its reply is not JSON, loses the finding entirely."""
    assert small.deterministic_kind("FileNotFoundError: [Errno 2] no such file") == "ENVIRONMENT"
    assert small.deterministic_kind("ModuleNotFoundError: No module named 'httpx'") == "ENVIRONMENT"
    assert small.deterministic_kind("ConnectionRefusedError: [Errno 61]") == "ENVIRONMENT"
    assert small.deterministic_kind("assert 0.12 == 0.13") is None, "a wrong number is judgement"
    assert small.deterministic_kind("") is None


def test_a_skip_expires_only_on_a_future_date():
    """`temporarily disabled 2026-05-02` is the day someone switched it off and moved on,
    not a deadline. Reading any date as an expiry let the whole class through."""
    assert not small.has_expiry('reason="temporarily disabled 2026-05-02 - flaky?"')
    assert not small.has_expiry("no date at all")
    assert small.has_expiry("skip until 2099-01-01")
    assert not small.has_expiry("2026-13-45 is not a date")


def test_words_split_identifiers_so_a_changelog_can_be_found():
    got = [w.lower() for w in small.words_of("def test_net_proceeds_hundred(): # 10% fee")]
    assert "test_net_proceeds_hundred" in got and "proceeds" in got and "fee" not in got[:1]
    assert got.count("proceeds") == 1, "each word once"


def test_unstable_is_the_symmetric_difference_across_runs():
    first = [{"id": "a"}, {"id": "b"}]
    assert small.unstable(first, [{"a"}, {"a"}]) == {"b"}, "b failed once, passed twice"
    assert small.unstable(first, [{"a", "b"}]) == set(), "failing every time is not flaky"
    assert small.unstable(first, []) == set(), "one run cannot show instability"


def test_a_quarantine_entry_uses_the_key_the_validator_reads():
    entry = {"test_id": "t.py::test_x", "quarantined_until": "2099-01-01",
             "first_seen": "2026-01-01", "fail_count": 1, "run_count": 3, "reason": "r"}
    finding = small.flaky_finding(entry, 3, "P-F-1")
    assert finding["failure_classification"] == "FLAKY"
    assert "t.py::test_x" in finding["title"]
    assert validate_finding(finding, "findings/P-F-1.json", set()) == []


def test_the_verdict_is_arithmetic_over_the_findings():
    assert small.verdict_for([]) == "pass"
    assert small.verdict_for([{"severity": "Minor"}]) == "pass with risks"
    assert small.verdict_for([{"severity": "Minor"}, {"severity": "Critical"}]) == "fail"
    assert small.verdict_for([{"severity": "Blocker"}]) == "fail"


def test_ids_from_a_report_use_the_harnesss_own_parser():
    source = (REPO / "src" / "verdict_mcp" / "small.py").read_text(encoding="utf-8")
    assert "read_report(path)" in source, \
        "a second parser gave a second id shape, and every rerun looked unstable"


def test_a_version_guard_is_not_an_abandoned_skip(tmp_path):
    """`skipif(sys.version_info < (3, 9))` runs wherever it can and needs no expiry.
    Found on boltons, where every version guard came back as a finding."""
    (tmp_path / "test_x.py").write_text(
        "import sys, pytest, unittest\n"
        "@pytest.mark.skipif(sys.version_info < (3, 9), reason='needs 3.9')\n"
        "def test_guarded(): pass\n"
        "@pytest.mark.skip(reason='temporarily disabled 2026-05-02')\n"
        "def test_abandoned(): pass\n"
        "@pytest.mark.skipif(True, reason='switched off')\n"
        "def test_always(): pass\n"
        "@pytest.mark.skip(reason='until 2099-01-01')\n"
        "def test_dated(): pass\n", encoding="utf-8")
    found = small.skips_without_expiry(tmp_path, ["test_x.py"])
    reasons = " ".join(f["reason"] for f in found)
    assert "temporarily disabled" in reasons, "an unconditional skip with a past date is a graveyard"
    assert "switched off" in reasons, "skipif(True) is unconditional in disguise"
    assert "needs 3.9" not in reasons, "a real condition is a guard, not a graveyard"
    assert "2099" not in reasons, "a future expiry is a decision someone made"
    assert len(found) == 2


# ── the counterfactual ────────────────────────────────────────────────────────

def test_module_name_reads_an_import_path_from_a_file(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    assert small.module_name(tmp_path, "src/pkg/mod.py") == "pkg.mod", "src is a source root"
    assert small.module_name(tmp_path, "pricer.py") == "pricer"
    assert small.module_name(tmp_path, "pkg/__init__.py") == "pkg"
    assert small.source_root(tmp_path, "src/pkg/mod.py") == tmp_path / "src"
    assert small.source_root(tmp_path, "pricer.py") == tmp_path


def test_a_probe_refuses_a_tree_that_imports_the_original_source(tmp_path):
    """The scratch must run its own code. Measured on this project: 0 of 4 injected
    defects were caught without that check, 4 of 4 with it."""
    real, other = tmp_path / "real", tmp_path / "other"
    for d in (real, other):
        d.mkdir()
    (real / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    value, err = small.run_probe(sys.executable, real, "m", "m.f()")
    assert value == 1 and err is None
    # a tree with no copy of the module: the import escapes, and the assert catches it
    value, err = small.run_probe(sys.executable, other, "m", "m.f()")
    assert value is None and err, "an import from outside the tree must not be trusted"


def test_the_probe_sweeps_bytecode_before_it_runs(tmp_path):
    """CPython validates a cached file on mtime-in-seconds plus size, so a same-size edit
    within one second re-runs the old bytecode — the trap that produced VERDICT-F-50."""
    root = tmp_path / "t"
    root.mkdir()
    src = root / "m.py"
    src.write_text("def f():\n    return 111\n", encoding="utf-8")
    assert small.run_probe(sys.executable, root, "m", "m.f()")[0] == 111
    src.write_text("def f():\n    return 222\n", encoding="utf-8")   # same size
    assert small.run_probe(sys.executable, root, "m", "m.f()")[0] == 222


def test_scratch_copy_leaves_out_what_must_not_be_copied(tmp_path):
    repo, into = tmp_path / "repo", tmp_path / "into"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: x", encoding="utf-8")
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").write_text("x", encoding="utf-8")
    (repo / "m.py").write_text("x = 1\n", encoding="utf-8")
    assert small.scratch_copy(repo, into) is True
    assert (into / "m.py").is_file()
    assert not (into / ".git").exists() and not (into / ".venv").exists(), \
        "copying the virtualenv is how a scratch ends up importing the original source"


def test_a_counterfactual_that_flips_the_value_proves_the_claim(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def listable(price, floor):\n    return price > floor\n",
                               encoding="utf-8")
    chunk = small.Chunk("m.py", "listable", 1, 2,
                        "def listable(price, floor):\n    return price > floor")
    claim = {"mechanism": "returns > where the rule says >=", "line": 2}
    model = FakeModel([{"expression": "m.listable(5, 5)", "actual": False, "expected": True,
                        "fix_line": 2, "fix_replacement": "    return price >= floor"}])
    proof = small.counterfactual(model, repo, chunk, claim, sys.executable)
    assert proof["status"] == "proven"
    assert proof["before"] is False and proof["after"] is True
    entry = small.finding_of({**claim, "path": "m.py", "severity": "Critical", "title": "t",
                              "impact": "i", "function": "listable"}, "P-F-1",
                             chunk.source, proof)
    assert entry["confidence"] == "proven"
    assert "COUNTERFACTUAL" in entry["evidence"][0]
    assert validate_finding(entry, "findings/P-F-1.json", set()) == []


def test_a_counterfactual_that_changes_nothing_disproves_it(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def f(x):\n    return x + 1\n", encoding="utf-8")
    chunk = small.Chunk("m.py", "f", 1, 2, "def f(x):\n    return x + 1")
    model = FakeModel([{"expression": "m.f(1)", "actual": 2, "expected": 3,
                        "fix_line": 1, "fix_replacement": "def f(x):"}])
    proof = small.counterfactual(model, repo, chunk, {"mechanism": "off by one", "line": 2},
                                 sys.executable)
    assert proof["status"] == "disproven"
    assert "did not move" in proof["reason"]


def test_a_probe_the_model_malformed_is_refused_and_says_why(tmp_path):
    """A proof that silently does not happen looks exactly like one never attempted, so
    every refusal carries its reason into the run's output."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "m.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    chunk = small.Chunk("m.py", "f", 1, 2, "def f():\n    return 1")
    claim = {"mechanism": "wrong", "line": 2}
    for answer in ({"expression": "m.f()\nimport os", "fix_line": 2, "fix_replacement": "x"},
                   {"expression": "m.f()", "fix_line": 99, "fix_replacement": "x"},
                   {"expression": "", "fix_line": 2, "fix_replacement": "x"},
                   {"expression": "m.f()", "fix_line": 2, "fix_replacement": None}):
        proof = small.counterfactual(FakeModel([answer]), repo, chunk, claim, sys.executable)
        assert proof["status"] == "unavailable" and proof["reason"]
    assert small.counterfactual(FakeModel([None]), repo, chunk, claim,
                                sys.executable)["reason"] == "the model did not answer with JSON"


def test_the_interpreter_comes_from_the_projects_own_gate():
    assert small.interpreter_of("PYTHONDONTWRITEBYTECODE=1 /x/.venv/bin/python -m pytest") \
        == "/x/.venv/bin/python"
    assert small.interpreter_of("npm test") == sys.executable


def test_severity_from_reading_is_capped_until_something_is_executed():
    """Measured on boltons: 35 findings from reading alone, 34 of them Major or above.
    A tester whose every finding is Critical has no severity at all."""
    claim = {"path": "m.py", "line": 5, "severity": "Critical", "title": "t",
             "mechanism": "wrong", "impact": "i", "function": "f"}
    unproven = small.finding_of(claim, "P-F-1", "def f(): pass")
    assert unproven["severity"] == "Minor" and unproven["priority"] == "P2"
    assert "held at Minor" in unproven["narrative"]
    proof = {"status": "proven", "expression": "m.f()", "before": 1, "after": 2,
             "line": 5, "was": "a", "now": "b", "reason": "the value follows the line"}
    proven = small.finding_of(claim, "P-F-2", "def f(): pass", proof)
    assert proven["severity"] == "Critical" and proven["priority"] == "P1"
    assert small.capped("Trivial", False) == "Minor" and small.capped("Trivial", True) == "Trivial"
