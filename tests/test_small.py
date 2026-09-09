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


def test_ask_json_retries_once_then_gives_up():
    class Flaky(small.Model):
        def __init__(self, replies):
            super().__init__("m", "http://x", "t")
            self.replies = list(replies)

        def ask(self, prompt, max_tokens=1200):
            return self.replies.pop(0)

    good = Flaky(["not json", '{"ok": 1}'])
    assert good.ask_json("q") == {"ok": 1} and good.retries == 1
    bad = Flaky(["nope", "still nope"])
    assert bad.ask_json("q") is None and bad.retries == 2


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
    assert "no test was run against a claim" in source, \
        "a pass must always name what was not tested; local mode tests almost nothing"


def test_finding_json_is_written_only_after_the_validator_accepts_it():
    source = (REPO / "src" / "verdict_mcp" / "small.py").read_text(encoding="utf-8")
    i, j = source.index("problems = validate_finding"), source.index("write_text(json.dumps(entry")
    assert i < j, "a rejected finding must never reach the findings directory"
