"""Tests for the session-start memory hook.

It exists because of a measured failure: Verdict filed eleven evidenced
findings on a live site, one a release blocker, and the very next session in
that repository did a full SEO pass and touched none of them. The findings were
in `state.json` the whole time; nothing put them on screen.

So the tests come in two halves. That it *says the useful thing* — the blocker
first, the counts, no repetition. And that it stays quiet everywhere else,
because this runs at the start of every session in every repo the plugin sees.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "report_open_findings.py"


def fire(cwd, home=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    if home:
        env["VERDICT_HOME"] = str(home)
    return subprocess.run([sys.executable, str(HOOK)],
                          input=json.dumps({"cwd": str(cwd)}),
                          # The hook writes UTF-8 by contract; decoding with the
                          # locale codepage would turn its dashes into mojibake
                          # on Windows only, and an assertion on them would lie.
                          capture_output=True, text=True, encoding="utf-8", env=env)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "Widget"
    r.mkdir()
    subprocess.run(["git", "init", "-qb", "main"], cwd=r, check=True, capture_output=True)
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "first"], cwd=r, check=True, capture_output=True)
    return r


def plant(tmp_path, **over):
    root = tmp_path / "home" / "widget"
    (root / "reports").mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {
        "project": "widget", "schema_version": 1, "run_type": "delta", "run_number": 4,
        "last_run": {"timestamp_utc": stamp, "report": "reports/r.md"},
        "isolation_check": {}, "gates": {}, "verdict": "fail",
        "release_blockers": ["W-F-1 — the signer drops the nonce"],
        "not_tested": ["x"], "next_run_focus": ["re-check the signer"],
        "findings": [
            {"id": "W-F-1", "hash": "a", "status": "open", "delta": "STILL_OPEN",
             "severity": "Critical", "age_days": 5, "title": "the signer drops the nonce",
             "evidence": ["s.py:1"]},
            {"id": "W-F-2", "hash": "b", "status": "open", "delta": "STILL_OPEN",
             "severity": "Major", "age_days": 2, "title": "retry loop never terminates",
             "evidence": ["r.py:1"]},
            {"id": "W-F-3", "hash": "c", "status": "resolved", "delta": "RESOLVED",
             "severity": "Major", "age_days": 9, "title": "already fixed",
             "evidence": ["x.py:1"]},
        ],
    }
    state.update(over)
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return root.parent


# ── it says the useful thing ──────────────────────────────────────────────

def test_the_blocker_comes_first_and_the_counts_follow(tmp_path, repo):
    out = fire(repo, home=plant(tmp_path)).stdout
    assert "verdict **fail**" in out
    lines = out.splitlines()
    assert "release blocker" in lines[1], "the blocker leads; everything else is context"
    assert "the signer drops the nonce" in lines[2]
    assert "2 open findings" in out and "1 Critical" in out and "1 Major" in out
    assert "oldest 5d" in out
    assert "re-check the signer" in out


def test_a_finding_already_named_as_a_blocker_is_not_repeated(tmp_path, repo):
    """A session opener that says the same thing twice is one nobody finishes."""
    out = fire(repo, home=plant(tmp_path)).stdout
    assert out.count("W-F-1") == 1
    assert "W-F-2" in out, "the other open findings are still listed"


def test_resolved_findings_are_not_reported_as_outstanding(tmp_path, repo):
    out = fire(repo, home=plant(tmp_path)).stdout
    assert "W-F-3" not in out and "already fixed" not in out


def test_a_clean_project_says_so_in_one_line(tmp_path, repo):
    home = plant(tmp_path, verdict="pass", release_blockers=[], findings=[],
                 next_run_focus=[])
    out = fire(repo, home=home).stdout
    assert "Nothing open" in out and len(out.splitlines()) == 2


def test_stale_memory_is_flagged_rather_than_served_as_current(tmp_path, repo):
    home = plant(tmp_path, last_run={"timestamp_utc": "2026-01-01T00:00:00Z",
                                     "report": "reports/r.md"})
    out = fire(repo, home=home).stdout
    assert "days old" in out and "/verdict:run" in out


def test_findings_are_offered_as_findings_not_as_orders(tmp_path, repo):
    """The hook informs a session; it does not commandeer it."""
    out = fire(repo, home=plant(tmp_path)).stdout
    assert "findings, not instructions" in out


# ── and stays quiet everywhere else ───────────────────────────────────────

def test_a_repo_with_no_qa_state_prints_nothing(tmp_path, repo):
    proc = fire(repo, home=tmp_path / "empty")
    assert proc.returncode == 0 and proc.stdout == ""


def test_a_state_with_no_verdict_prints_nothing(tmp_path, repo):
    home = plant(tmp_path)
    (home / "widget" / "state.json").write_text(json.dumps({"project": "widget"}),
                                                encoding="utf-8")
    assert fire(repo, home=home).stdout == ""


def test_every_broken_input_fails_open(tmp_path):
    for payload in ("not json", "", "[]", "null", '{"cwd": null}',
                    '{"cwd": "/nonexistent/nowhere"}'):
        proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                              capture_output=True, text=True)
        assert proc.returncode == 0, payload
        assert proc.stdout == "", payload


def test_a_team_mode_root_in_the_tree_is_found(tmp_path, repo):
    root = repo / ".qa"
    (root / "reports").mkdir(parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "run_number": 1, "run_type": "baseline",
        "last_run": {"timestamp_utc": stamp}, "verdict": "blocked",
        "release_blockers": [], "findings": []}), encoding="utf-8")
    assert "verdict **blocked**" in fire(repo, home=tmp_path / "empty").stdout


# ── the first-run hint (2026-10-04) ───────────────────────────────────────────
# The directory counted 96 installer accounts and 0 uses, ever: Verdict does nothing
# until it is asked, and nothing said how. One line, once per repository, at most
# three repositories per person — and silence everywhere the line would be noise.

def fire_as(cwd, home, source=None, **env_over):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("VERDICT_") and k != "CLAUDE_CODE_ENTRYPOINT"}
    env["VERDICT_HOME"] = str(home)
    env.update(env_over)
    event = {"cwd": str(cwd), "hook_event_name": "SessionStart"}
    if source is not None:
        event["source"] = source
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                          capture_output=True, text=True, encoding="utf-8", env=env)


def a_tested_repo(tmp_path, name="Shop", marker="tests"):
    r = tmp_path / name
    r.mkdir()
    subprocess.run(["git", "init", "-qb", "main"], cwd=r, check=True, capture_output=True)
    if marker.endswith(".json") or marker.endswith(".toml") or "." in marker:
        (r / marker).write_text("", encoding="utf-8")
    else:
        (r / marker).mkdir()
    return r


def hint_of(proc):
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout) if proc.stdout.strip() else None


def test_a_tested_repository_verdict_never_saw_gets_one_hint(tmp_path):
    repo = a_tested_repo(tmp_path)
    home = tmp_path / "home"
    out = hint_of(fire_as(repo, home, source="startup"))
    assert "/verdict:run" in out["systemMessage"] and "never edits your code" in out["systemMessage"]
    ctx = out["hookSpecificOutput"]
    assert ctx["hookEventName"] == "SessionStart" and "/verdict:run" in ctx["additionalContext"]
    record = json.loads((home / ".first-run.json").read_text(encoding="utf-8"))
    assert list(record["shown"]) == ["shop"]       # the project key, as derive_key spells it
    # the second session in the same repository is silent
    assert fire_as(repo, home, source="startup").stdout == ""


def test_three_repositories_at_most_then_never_again(tmp_path):
    home = tmp_path / "home"
    shown = [hint_of(fire_as(a_tested_repo(tmp_path, f"R{i}"), home)) for i in range(4)]
    assert [s is not None for s in shown] == [True, True, True, False]


@pytest.mark.parametrize("source", ["resume", "compact", "clear"])
def test_only_a_fresh_start_hints(tmp_path, source):
    repo, home = a_tested_repo(tmp_path), tmp_path / "home"
    assert fire_as(repo, home, source=source).stdout == ""
    assert not (home / ".first-run.json").exists(), "a hint not shown must not be spent"


@pytest.mark.parametrize("env", [{"VERDICT_STRICT": "1"}, {"VERDICT_NO_HINT": "1"},
                                 {"CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}])
def test_headless_ci_and_opted_out_sessions_stay_silent(tmp_path, env):
    repo, home = a_tested_repo(tmp_path), tmp_path / "home"
    assert fire_as(repo, home, **env).stdout == ""
    assert not (home / ".first-run.json").exists()


@pytest.mark.parametrize("marker, hints", [
    ("tests", True), ("pytest.ini", True), ("go.mod", True), ("Cargo.toml", True),
    ("README.md", False),
])
def test_only_a_repository_with_a_test_suite_hints(tmp_path, marker, hints):
    repo = a_tested_repo(tmp_path, marker=marker)
    assert (hint_of(fire_as(repo, tmp_path / "home")) is not None) is hints


def test_npm_placeholder_test_script_is_not_a_test_suite(tmp_path):
    home = tmp_path / "home"
    placeholder = a_tested_repo(tmp_path, "A", marker="README.md")
    (placeholder / "package.json").write_text(json.dumps(
        {"scripts": {"test": "echo \"Error: no test specified\" && exit 1"}}), encoding="utf-8")
    real = a_tested_repo(tmp_path, "B", marker="README.md")
    (real / "package.json").write_text(json.dumps({"scripts": {"test": "vitest run"}}),
                                       encoding="utf-8")
    assert hint_of(fire_as(placeholder, home)) is None
    assert hint_of(fire_as(real, home)) is not None


def test_a_repository_already_set_up_for_verdict_is_not_hinted(tmp_path):
    repo = a_tested_repo(tmp_path)
    (repo / ".qa").mkdir()
    assert fire_as(repo, tmp_path / "home").stdout == ""


def test_a_hint_that_cannot_be_recorded_is_not_shown(tmp_path):
    """Shown but not recorded would repeat in every session — worse than never."""
    repo = a_tested_repo(tmp_path)
    home = tmp_path / "home-is-a-file"
    home.write_text("not a directory", encoding="utf-8")
    proc = fire_as(repo, home)
    assert proc.returncode == 0 and proc.stdout == "" and proc.stderr == ""


def test_a_session_inside_a_subdirectory_counts_the_repository(tmp_path):
    repo, home = a_tested_repo(tmp_path), tmp_path / "home"
    (repo / "src" / "pkg").mkdir(parents=True)
    assert hint_of(fire_as(repo / "src" / "pkg", home)) is not None
    assert fire_as(repo, home).stdout == "", "the same repository, already hinted"


def test_a_repository_with_state_still_gets_the_banner_not_the_hint(tmp_path):
    repo = a_tested_repo(tmp_path, "Widget")
    plant(tmp_path)                       # state for "widget" under tmp_path/home
    out = fire_as(repo, tmp_path / "home").stdout
    assert out.startswith("Verdict remembers widget") and "systemMessage" not in out
