"""verdict-run measures before the tester starts; the tester's verdict-facts adopts it (0.91.1)."""

import json
import subprocess
import sys

from verdict_mcp import harness, runner
from verdict_mcp.harness import facts_main


def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


def test_the_testers_facts_call_adopts_a_premeasurement_of_this_head(repo, qa_root, capsys, monkeypatch):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0      # verdict-run's measurement
    capsys.readouterr()
    first = (qa_root / "facts.json").read_text(encoding="utf-8")
    monkeypatch.setenv(harness.PREMEASURED_ENV, _head(repo))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "tester-session")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0      # the tester's call
    out, err = capsys.readouterr()
    assert json.loads(out)["reused"]["why"].startswith("measured by verdict-run before the tester started")
    assert "reusing facts measured" in err and "next id" in err
    assert (qa_root / "facts.json").read_text(encoding="utf-8") == first, "nothing was re-measured"
    marker = json.loads((qa_root / "run-in-progress.json").read_text(encoding="utf-8"))
    assert marker.get("session_id") == "tester-session", marker


def test_a_premeasurement_of_another_commit_is_not_adopted(repo, qa_root, capsys, monkeypatch):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    capsys.readouterr()
    monkeypatch.setenv(harness.PREMEASURED_ENV, "0" * 40)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    out, _ = capsys.readouterr()
    assert "reused" not in json.loads(out), "a stale or foreign measurement is measured again"


def test_verdict_run_premeasures_outside_the_session_and_names_the_head(repo, qa_root, capsys):
    calls = {}

    def fake_run(cmd, env=None, **kw):
        calls["cmd"], calls["env"] = cmd, env
        return subprocess.CompletedProcess(cmd, 0, "{}", "")

    env = {"CLAUDECODE": "1", "CLAUDE_CODE_ENTRYPOINT": "cli", "VERDICT_ASSERTION_GAPS": "on", "PATH": "/usr/bin:/bin"}
    head = runner.premeasure(repo, qa_root, env, "a..b", run=fake_run)
    assert head == _head(repo)
    assert calls["cmd"][:4] == [sys.executable, "-m", "verdict_mcp.harness", "facts"]
    assert calls["cmd"][-2:] == ["--range", "a..b"]
    assert "CLAUDECODE" not in calls["env"] and "CLAUDE_CODE_ENTRYPOINT" not in calls["env"], \
        "outside a session: the census gets its whole budget"
    assert calls["env"]["VERDICT_ASSERTION_GAPS"] == "on"
    assert "facts measured before the tester started" in capsys.readouterr().err


def test_a_failed_premeasurement_leaves_the_tester_to_measure(repo, qa_root, capsys):
    head = runner.premeasure(repo, qa_root, {}, None,
                             run=lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "profile unreadable"))
    assert head is None and "the tester measures on its own" in capsys.readouterr().err


def test_a_tester_asking_for_another_range_measures_it(repo, qa_root, capsys, monkeypatch):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    capsys.readouterr()
    monkeypatch.setenv(harness.PREMEASURED_ENV, _head(repo))
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root), "--range", "HEAD~0..HEAD"]) == 0
    out, _ = capsys.readouterr()
    assert "reused" not in json.loads(out), "verdict-run measured no range; the tester asked for one"
