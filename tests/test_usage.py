"""The bill beside the score.

A model comparison is not a comparison until what each arm spent is on the table:
a cheaper model that scores the same is only cheaper if it did not spend three
times the tokens getting there. These tests keep the arithmetic honest — the
same request counted once, the subagent's tokens counted at all (that is where a
Verdict run does its work), and a missing transcript reported as unknown rather
than as zero.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import usage  # noqa: E402


def _assistant(request_id, **tokens):
    return json.dumps({"type": "assistant", "requestId": request_id,
                       "message": {"usage": tokens}})


def _session(base: Path, session_id: str, main_rows, sub_rows=None):
    base.mkdir(parents=True, exist_ok=True)
    (base / f"{session_id}.jsonl").write_text("\n".join(main_rows) + "\n", encoding="utf-8")
    if sub_rows:
        subs = base / session_id / "subagents"
        subs.mkdir(parents=True)
        (subs / "agent-abc.jsonl").write_text("\n".join(sub_rows) + "\n", encoding="utf-8")


def test_project_dir_matches_claude_codes_own_key(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    got = usage.project_dir("/Users/x/.cache/verdict/psf__requests-1")
    assert got == tmp_path / ".claude" / "projects" / "-Users-x--cache-verdict-psf--requests-1"


def test_usage_sums_the_subagent_and_counts_a_request_once(tmp_path, monkeypatch):
    home, cwd = tmp_path / "home", tmp_path / "work" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    _session(
        usage.project_dir(cwd), "sess-1",
        main_rows=[_assistant("req-1", input_tokens=10, output_tokens=100),
                   # the same request written again as the turn streamed: the later
                   # record wins, it is not added twice
                   _assistant("req-1", input_tokens=10, output_tokens=140),
                   json.dumps({"type": "user", "message": {"content": []}})],
        sub_rows=[_assistant("req-2", output_tokens=900, cache_read_input_tokens=50_000),
                  _assistant("req-3", output_tokens=60)])
    got = usage.usage_of(cwd)
    assert got["requests"] == 3 and got["files"] == 2 and got["sessions"] == 1
    assert got["output_tokens"] == 140 + 900 + 60, "the subagent's tokens are the run's tokens"
    assert got["cache_read_input_tokens"] == 50_000
    assert got["input_tokens"] == 10


def test_usage_covers_every_session_recorded_for_the_checkout(tmp_path, monkeypatch):
    home, cwd = tmp_path / "home", tmp_path / "work" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    base = usage.project_dir(cwd)
    _session(base, "sess-1", [_assistant("a", output_tokens=10)])
    _session(base, "sess-2", [_assistant("b", output_tokens=5)])
    both = usage.usage_of(cwd)
    assert both["output_tokens"] == 15 and both["sessions"] == 2, \
        "a two-phase fixture run is two sessions and one bill"
    one = usage.usage_of(cwd, "sess-2")
    assert one["output_tokens"] == 5 and one["sessions"] == 1


def test_usage_is_none_when_there_is_no_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path / "home"))
    assert usage.usage_of(tmp_path / "nowhere") is None, "unknown, not zero"


def test_usage_survives_a_truncated_transcript(tmp_path, monkeypatch):
    home, cwd = tmp_path / "home", tmp_path / "work" / "repo"
    cwd.mkdir(parents=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))
    base = usage.project_dir(cwd)
    base.mkdir(parents=True)
    (base / "sess-1.jsonl").write_text(
        _assistant("a", output_tokens=7) + "\n{\"type\": \"assist", encoding="utf-8")
    assert usage.usage_of(cwd)["output_tokens"] == 7


def test_add_totals_two_arms_and_tolerates_a_missing_one():
    left = {"requests": 2, "files": 1, "sessions": 1, "input_tokens": 1, "output_tokens": 10,
            "cache_creation_input_tokens": 0, "cache_read_input_tokens": 5}
    right = dict(left, output_tokens=90)
    assert usage.add(left, right)["output_tokens"] == 100
    assert usage.add(left, right)["requests"] == 4
    assert usage.add(None, right) == right and usage.add(left, None) == left
    assert usage.add(None, None) is None


def test_brief_reads_as_a_bill():
    text = usage.brief({"requests": 59, "output_tokens": 64_268, "cache_read_input_tokens": 3_735_693})
    assert text == "64k out · 3735k cache read · 59 requests"
    assert usage.brief(None) == "usage unknown"
