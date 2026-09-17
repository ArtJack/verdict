"""Who spent it, not just how much.

The census exists because a cost decision was about to be made on a guess — that the
scheduled nightly was what ate the subscription — and the transcripts said the nightly
was a sixth of it. These tests pin the three things that make its table worth believing:
a request counted once however many times it streamed, a run attributed to whoever
launched it and to the model that actually answered, and an agent that is not Verdict
left out of Verdict's bill.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import usage_census as census  # noqa: E402


def _assistant(request_id, model="claude-opus-5", stamp="2026-09-10T10:00:00Z",
               entrypoint="claude-desktop", **tokens):
    return json.dumps({"type": "assistant", "requestId": request_id, "timestamp": stamp,
                       "entrypoint": entrypoint, "message": {"model": model, "usage": tokens}})


def _run(config: Path, project: str, session: str, agent_id: str, rows, agent_type="verdict:verdict",
         description="delta run", spawn_model=None):
    subs = config / "projects" / project / session / "subagents"
    subs.mkdir(parents=True, exist_ok=True)
    (subs / f"agent-{agent_id}.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    meta = {"agentType": agent_type, "description": description}
    if spawn_model:
        meta["model"] = spawn_model
    (subs / f"agent-{agent_id}.meta.json").write_text(json.dumps(meta), encoding="utf-8")


def test_a_request_streamed_twice_is_billed_once_and_the_context_is_the_largest_seen(tmp_path):
    _run(tmp_path, "-Users-x-Sales", "s1", "a1", [
        _assistant("r1", output_tokens=100, cache_read_input_tokens=20_000),
        _assistant("r1", output_tokens=140, cache_read_input_tokens=20_000),   # the same turn, later
        _assistant("r2", output_tokens=60, cache_read_input_tokens=90_000,
                   cache_creation_input_tokens=5_000, input_tokens=10,
                   stamp="2026-09-10T10:12:00Z"),
        "{\"type\": \"assist"])                                                 # cut off mid-line
    [row] = census.runs(tmp_path)
    assert row["requests"] == 2
    assert row["output_tokens"] == 140 + 60
    assert row["cache_read_input_tokens"] == 110_000
    assert row["max_context"] == 95_010, "what the largest request carried in, output excluded"
    assert row["minutes"] == 12.0
    assert row["project"] == "-Users-x-Sales" and row["description"] == "delta run"


def test_the_launcher_and_the_answering_model_are_read_from_the_transcript(tmp_path):
    _run(tmp_path, "-Users-x-Sales", "s1", "a1",
         [_assistant("r1", output_tokens=10)])
    _run(tmp_path, "-Users-x-Sales--nightly", "s2", "a2",
         [_assistant("r2", model="claude-sonnet-5", entrypoint="sdk-cli", output_tokens=7),
          _assistant("r3", model="claude-sonnet-5", entrypoint="sdk-cli", output_tokens=5)],
         agent_type="verdict", spawn_model="sonnet")
    summary = census.summarize(census.runs(tmp_path))
    assert summary["by_launch"]["interactive"]["runs"] == 1
    assert summary["by_launch"]["headless"]["output_tokens"] == 12
    assert set(summary["by_model"]) == {"claude-opus-5", "claude-sonnet-5"}
    assert summary["inherited_model"] == 1, "one run named no model and took the session's"
    assert summary["total"]["runs"] == 2 and summary["total"]["requests"] == 3


def test_another_agents_run_is_not_verdicts_bill(tmp_path):
    _run(tmp_path, "-Users-x-Sales", "s1", "a1", [_assistant("r1", output_tokens=10)],
         agent_type="Explore")
    _run(tmp_path, "-Users-x-Sales", "s1", "a2", [_assistant("r2", output_tokens=20)])
    assert [r["output_tokens"] for r in census.runs(tmp_path)] == [20]
    assert census.runs(tmp_path, agent_types=("Explore",))[0]["output_tokens"] == 10


def test_the_window_is_the_day_the_run_started(tmp_path):
    _run(tmp_path, "-p", "s1", "a1", [_assistant("r1", stamp="2026-09-01T23:59:00Z", output_tokens=1)])
    _run(tmp_path, "-p", "s2", "a2", [_assistant("r2", stamp="2026-09-17T00:01:00Z", output_tokens=2)])
    assert [r["output_tokens"] for r in census.runs(tmp_path, since="2026-09-17")] == [2]
    assert [r["output_tokens"] for r in census.runs(tmp_path, until="2026-09-01")] == [1]
    assert set(census.summarize(census.runs(tmp_path))["by_week"]) == {"2026-W36", "2026-W38"}


def test_a_run_with_no_request_and_a_meta_with_no_transcript_are_left_out(tmp_path):
    _run(tmp_path, "-p", "s1", "a1", [json.dumps({"type": "user", "message": {"content": []}})])
    subs = tmp_path / "projects" / "-p" / "s1" / "subagents"
    (subs / "agent-a9.meta.json").write_text(json.dumps({"agentType": "verdict"}), encoding="utf-8")
    (subs / "agent-a8.meta.json").write_text("{not json", encoding="utf-8")
    assert census.runs(tmp_path) == []
    assert census.render(census.summarize([])) == "no Verdict-agent runs recorded in that window"


def test_the_table_names_the_largest_run_and_the_cli_prints_json(tmp_path, capsys):
    _run(tmp_path, "-Users-x-Sales", "s1", "a1",
         [_assistant("r1", output_tokens=10, cache_read_input_tokens=1_000)], description="small")
    _run(tmp_path, "-Users-x-Sales", "s1", "a2",
         [_assistant("r2", output_tokens=10, cache_read_input_tokens=9_000_000)],
         description="gate on the stock fix")
    text = census.render(census.summarize(census.runs(tmp_path)))
    assert "who launched it" in text and "gate on the stock fix" in text
    assert text.index("gate on the stock fix") < text.index("small"), "largest first"
    assert census.main(["--config-dir", str(tmp_path), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["total"]["runs"] == 2 and doc["largest"][0]["description"] == "gate on the stock fix"
