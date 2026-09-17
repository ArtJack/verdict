"""The bill, written down where the run is finalized.

Until 0.89.0 a production run recorded which model signed the verdict only when an
operator exported `VERDICT_MODEL`, and never what it cost. A census of the author's own
machine then found 214 of 232 runs had named no model and had inherited the most
expensive one on the account. These tests pin the arithmetic that makes the record
worth having — this run's transcript and no other agent's, this run's requests and not
the hour before it — and the rule that makes it safe: a bill that cannot be read costs
the run nothing.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conftest import judgment
from verdict_mcp import usage
from verdict_mcp.harness import _record_bill

HARNESS = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "harness.py"
SESSION = "sess-1"


def _env(config: Path, **extra):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("VERDICT_", "CLAUDE_"))}
    env.update(CLAUDE_CONFIG_DIR=str(config), **extra)
    return env


def _harness(*args, env):
    return subprocess.run([sys.executable, str(HARNESS), *args], capture_output=True,
                          text=True, encoding="utf-8", env=env)


def _stamp(offset_s=0):
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_s)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z")


def _assistant(request, model="claude-sonnet-5", offset_s=5, **tokens):
    return json.dumps({"type": "assistant", "requestId": request, "timestamp": _stamp(offset_s),
                       "message": {"model": model, "usage": tokens}})


def _transcript(config: Path, name: str, rows, *, main=False):
    base = config / "projects" / "-Users-x-launch-dir"
    path = base / f"{SESSION}.jsonl" if main else base / SESSION / "subagents" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _measured(repo, qa_root, env):
    proc = _harness("facts", "--repo", str(repo), "--qa-root", str(qa_root), env=env)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _finalize(qa_root, tmp_path, env):
    jpath = tmp_path / "j.json"
    jpath.write_text(json.dumps(judgment()), encoding="utf-8")
    return _harness("finalize", "--qa-root", str(qa_root), "--judgment", str(jpath), env=env)


def _rows(qa_root):
    return [json.loads(line) for line in
            (qa_root / "usage.jsonl").read_text(encoding="utf-8").splitlines()]


def test_the_marker_names_the_session_that_staked_it(repo, qa_root, tmp_path):
    env = _env(tmp_path / "cfg", CLAUDE_CODE_SESSION_ID=SESSION,
               CLAUDE_CODE_ENTRYPOINT="claude-desktop")
    _measured(repo, qa_root, env)
    marker = json.loads((qa_root / "run-in-progress.json").read_text(encoding="utf-8"))
    assert marker["session_id"] == SESSION and marker["entrypoint"] == "claude-desktop"
    _measured(repo, qa_root, _env(tmp_path / "cfg"))
    marker = json.loads((qa_root / "run-in-progress.json").read_text(encoding="utf-8"))
    assert "session_id" not in marker and marker["git_sha"], "outside Claude Code: no guess"


def test_finalize_records_this_runs_bill_and_the_model_that_answered(repo, qa_root, tmp_path):
    cfg = tmp_path / "cfg"
    env = _env(cfg, CLAUDE_CODE_SESSION_ID=SESSION, CLAUDE_CODE_ENTRYPOINT="claude-desktop",
               CLAUDE_EFFORT="high")
    facts = _measured(repo, qa_root, env)
    printed = json.dumps({"type": "user", "message": {"content": [
        {"type": "tool_result", "content": json.dumps({"measured_at": facts["measured_at"]})}]}})
    _transcript(cfg, "agent-tester.jsonl", [
        _assistant("old", offset_s=-3600, output_tokens=999),          # the hour before the run
        printed,
        _assistant("r1", output_tokens=100, cache_read_input_tokens=20_000),
        _assistant("r1", output_tokens=140, cache_read_input_tokens=20_000),   # streamed twice
        _assistant("r2", output_tokens=60, cache_read_input_tokens=30_000, offset_s=9),
        _assistant("r3", model="<synthetic>", output_tokens=0, offset_s=10)])
    decoy = _transcript(cfg, "agent-explorer.jsonl",
                        [_assistant("x1", model="claude-opus-5", output_tokens=5_000)])
    os.utime(decoy, (decoy.stat().st_atime, decoy.stat().st_mtime + 60))   # written last

    proc = _finalize(qa_root, tmp_path, env)
    assert proc.returncode == 0, proc.stderr
    [row] = _rows(qa_root)
    bill = row["usage"]
    assert bill["source"] == "fingerprint" and bill["transcript"] == "agent-tester.jsonl"
    assert bill["requests"] == 3 and bill["output_tokens"] == 200
    assert bill["cache_read_input_tokens"] == 50_000
    assert bill["models"] == {"claude-sonnet-5": 2}, "a synthetic record is not a model"
    assert row["model"] == "claude-sonnet-5" and row["run_number"] == 1
    assert row["entrypoint"] == "claude-desktop" and row["effort"] == "high"
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert state["last_run"]["model"] == "claude-sonnet-5", "measured, because nobody named it"
    history = [json.loads(x) for x in
               (qa_root / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert history[-1]["model"] == "claude-sonnet-5" and "usage" not in history[-1], \
        "the model is part of the signed row; the bill is telemetry and stays out of it"


def test_an_operators_label_wins_and_the_measured_models_stay_in_the_bill(repo, qa_root, tmp_path):
    cfg = tmp_path / "cfg"
    env = _env(cfg, CLAUDE_CODE_SESSION_ID=SESSION, VERDICT_MODEL="opus")
    facts = _measured(repo, qa_root, env)
    _transcript(cfg, "agent-tester.jsonl", [
        json.dumps({"type": "user", "message": {"content": facts["measured_at"]}}),
        _assistant("r1", model="claude-sonnet-5", output_tokens=10)])
    assert _finalize(qa_root, tmp_path, env).returncode == 0
    [row] = _rows(qa_root)
    assert row["model"] == "opus"
    assert row["usage"]["models"] == {"claude-sonnet-5": 1}, "what was said and what ran, both kept"


def test_with_no_fingerprint_the_transcript_still_being_written_is_the_run(repo, qa_root, tmp_path):
    cfg = tmp_path / "cfg"
    env = _env(cfg, CLAUDE_CODE_SESSION_ID=SESSION)
    _measured(repo, qa_root, env)
    older = _transcript(cfg, "agent-a.jsonl", [_assistant("a1", output_tokens=1)])
    os.utime(older, (older.stat().st_atime, older.stat().st_mtime - 600))
    _transcript(cfg, "agent-b.jsonl", [_assistant("b1", output_tokens=7)])
    assert _finalize(qa_root, tmp_path, env).returncode == 0
    bill = _rows(qa_root)[0]["usage"]
    assert bill["source"] == "latest-transcript" and bill["output_tokens"] == 7


def test_an_unknown_bill_is_recorded_as_unknown_not_as_zero(repo, qa_root, tmp_path):
    env = _env(tmp_path / "cfg")                        # no session: not under Claude Code
    _measured(repo, qa_root, env)
    assert _finalize(qa_root, tmp_path, env).returncode == 0
    [row] = _rows(qa_root)
    assert row["usage"] is None and "Unknown, not zero" in row["note"]
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert "model" not in state["last_run"], "nothing measured, nothing claimed"


def test_a_bill_that_cannot_be_written_costs_the_run_nothing(repo, qa_root, tmp_path):
    env = _env(tmp_path / "cfg")
    _measured(repo, qa_root, env)
    (qa_root / "usage.jsonl").mkdir()                   # a directory where the file goes
    proc = _finalize(qa_root, tmp_path, env)
    assert proc.returncode == 0, "the state is written and valid; telemetry is not a gate"
    assert "was not recorded" in proc.stderr and "Traceback" not in proc.stderr
    assert (qa_root / "state.json").is_file()
    assert not (qa_root / "run-in-progress.json").exists()


def test_a_sweep_is_billed_as_the_nothing_it_cost(qa_root):
    state = {"run_number": 7, "run_type": "sweep",
             "last_run": {"timestamp_utc": "2026-09-17T10:15:00Z", "model": "none"}}
    _record_bill(qa_root, state, None)
    [row] = _rows(qa_root)
    assert row["model"] == "none" and row["usage"]["requests"] == 0
    assert row["usage"]["output_tokens"] == 0 and "no model was called" in row["note"]


def test_run_usage_never_raises_and_never_guesses(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "cfg"))
    assert usage.run_usage(None) is None
    assert usage.run_usage("no-such-session") is None
    path = _transcript(tmp_path / "cfg", "agent-t.jsonl",
                       ["{not json", json.dumps({"type": "user"}), json.dumps([1, 2])])
    assert usage.session_transcripts(SESSION) == [path]
    assert usage.session_transcripts("*") == [], "a session id is a name, never a pattern"
    assert usage.run_usage("../../etc") is None and usage.session_transcripts("sess-?") == []
    assert usage.run_usage(SESSION) is None, "a transcript with no request is no bill"
    path.write_text(_assistant("r1", output_tokens=3) + "\n", encoding="utf-8")
    assert usage.run_usage(SESSION, since="not a date")["output_tokens"] == 3


def test_the_main_session_is_read_only_when_no_delegated_agent_carries_the_fingerprint(tmp_path,
                                                                                         monkeypatch):
    """A tester delegated as a subagent prints the facts into its own transcript; the
    session that spawned it may quote them later. Delegated files are read first."""
    cfg = tmp_path / "cfg"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    mark = "2026-09-17T07:00:00Z"
    _transcript(cfg, "", [json.dumps({"type": "user", "message": {"content": mark}}),
                          _assistant("m1", model="claude-fable-5-1", output_tokens=500)], main=True)
    _transcript(cfg, "agent-t.jsonl", [json.dumps({"type": "user", "message": {"content": mark}}),
                                       _assistant("s1", output_tokens=11)])
    got = usage.run_usage(SESSION, fingerprint=mark)
    assert got["transcript"] == "agent-t.jsonl" and got["output_tokens"] == 11
    inline = usage.run_usage(SESSION, fingerprint="only-the-main-session-has-this")
    assert inline["source"] == "latest-transcript"
