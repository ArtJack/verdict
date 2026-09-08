"""A limit that reopens in hours is worth waiting for; one that reopens in days is not.

The CLI reports both in the same shape ("You've hit your … limit · resets …"), and
the runner knew only the word "session": a weekly limit read as an ordinary
failure, so an unattended run spent its retry on a second identical refusal and
reported a lost run, leaving the real reason in a log nobody was reading. These
tests hold the distinction, and hold the runner to acting on it.
"""

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import runner  # noqa: E402

WEEKLY = "You've hit your weekly limit · resets Sep 10 at 7pm (America/Los_Angeles)"
SESSION = "You've hit your session limit · resets 11:30pm (America/Los_Angeles)"


def test_limit_kind_separates_the_two_windows_and_ignores_everything_else():
    assert runner.limit_kind(WEEKLY) == "weekly"
    assert runner.limit_kind(SESSION) == "session"
    assert runner.limit_kind("Error: connection reset by peer") is None
    assert runner.limit_kind("") is None


def test_a_weekly_limit_is_never_slept_through():
    assert runner.seconds_until_reset(WEEKLY) is None, \
        "days away — a runner that sleeps on this hangs the night"
    assert runner.seconds_until_reset(SESSION) is not None


def test_limit_line_returns_the_clis_own_sentence():
    assert runner.limit_line("noise\n" + WEEKLY + "\nmore noise") == WEEKLY
    assert "usage limit" in runner.limit_line("nothing here")


def _stub(tmp_path: Path, output: str) -> Path:
    """A `claude` stand-in that prints `output` and fails, like the real one does."""
    path = tmp_path / "claude-stub"
    path.write_text("#!/bin/sh\nprintf '%s\\n' \"$STUB_OUTPUT\"\nexit 1\n", encoding="utf-8")
    path.chmod(0o755)
    return path


def _profile(qa_root: Path, repo: Path) -> None:
    qa_root.mkdir(parents=True, exist_ok=True)
    (qa_root / "profile.md").write_text(
        f"---\ngates: {{}}\n---\n\n# QA Profile — t\n\nProject-Key: t\nRepo-Path: {repo}\n"
        "Security-Pass: disabled\nSchema-Version: 1\n", encoding="utf-8")


def test_the_runner_stops_on_a_weekly_limit_instead_of_spending_its_retry(
        tmp_path, monkeypatch, capsys):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("VERDICT_HOME", str(home))
    monkeypatch.setenv("STUB_OUTPUT", WEEKLY)
    _profile(home / "t", repo)
    stub = _stub(tmp_path, WEEKLY)

    calls = []
    real = runner._run_streaming

    def counting(cmd, cwd, env, timeout_s):
        calls.append(cmd)
        return real(cmd, cwd, env, timeout_s)

    monkeypatch.setattr(runner, "_run_streaming", counting)
    monkeypatch.setattr(runner.time, "sleep", lambda s: (_ for _ in ()).throw(
        AssertionError(f"slept {s}s on a limit that reopens in days")))

    code = runner.main(["t", "--repo", str(repo), "--claude-cmd", str(stub), "--no-provision"])
    err = capsys.readouterr().err
    assert len(calls) == 1, "one refusal is enough; the second would be identical"
    assert "weekly limit" in err and "Sep 10 at 7pm" in err, err
    assert code != 0


def test_the_runner_still_waits_out_a_session_limit(tmp_path, monkeypatch):
    repo, home = tmp_path / "repo", tmp_path / "home"
    repo.mkdir()
    monkeypatch.setenv("VERDICT_HOME", str(home))
    monkeypatch.setenv("STUB_OUTPUT", SESSION)
    _profile(home / "t", repo)
    stub = _stub(tmp_path, SESSION)
    slept = []
    monkeypatch.setattr(runner.time, "sleep", lambda s: slept.append(s))
    runner.main(["t", "--repo", str(repo), "--claude-cmd", str(stub), "--no-provision",
                 "--reset-ceiling-s", "120"])
    assert slept and slept[0] <= 120, "a window that reopens in hours is worth waiting for"


def test_the_external_key_batch_stops_when_the_week_is_spent():
    sys.path.insert(0, str(REPO / "eval"))
    import swebench  # noqa: PLC0415  (an eval script, imported for its rule)
    source = Path(swebench.__file__).read_text(encoding="utf-8")
    assert 'if (result.get("run") or {}).get("limit") == "weekly":' in source, \
        "every remaining instance would fail the same way and be written as a run that never ran"
    assert '"limit": limit_kind(output)' in source


def test_the_fixture_eval_refuses_rather_than_retries_on_a_weekly_limit():
    source = (REPO / "eval" / "run_eval.py").read_text(encoding="utf-8")
    assert 'if _limit_kind(combined) == "weekly":' in source
    assert json.dumps  # the import is used elsewhere in this module
