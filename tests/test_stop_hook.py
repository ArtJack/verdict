"""Tests for the run-contract stop hook.

Its job is enforcement that does not depend on the model remembering anything.
Its risk is that it runs at the end of every turn in every session where the
plugin is enabled — so most of what follows tests **silence**: a hook that
speaks when it should not is worse than the hole it fills, and one that bricks a
session is worse still.
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parent.parent / "hooks" / "enforce_run_contract.py"


def fire(event, home=None):
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    if home:
        env["VERDICT_HOME"] = str(home)
    return subprocess.run([sys.executable, str(HOOK)], input=json.dumps(event),
                          capture_output=True, text=True, env=env)


def qa_root(tmp_path, *, harnessed: bool, fresh: bool = True, name="widget"):
    """A QA root holding a state written either by the harness or by hand."""
    root = tmp_path / "home" / name
    (root / "reports").mkdir(parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    state = {
        "project": name, "schema_version": 1, "run_type": "baseline", "run_number": 1,
        "last_run": {"timestamp_utc": stamp, "git_sha": "abc", "report": "reports/r.md"},
        "isolation_check": {"result": "pass"}, "gates": {}, "tests": {},
        "flaky_quarantine": [], "findings": [], "verdict": "pass",
        "release_blockers": [], "not_tested": ["nothing"],
    }
    footer = ("*Countable sections rendered from `state.json` by `verdict-finalize`; "
              "the prose is the agent's.*")
    if harnessed:
        state["calibration"] = {"decided_outcomes": 0}
        (root / "facts.json").write_text(json.dumps({"measured_at": stamp}), encoding="utf-8")
        (root / "judgment.json").write_text("{}", encoding="utf-8")
        (root / "reports" / "r.md").write_text(f"# report\n\n{footer}\n", encoding="utf-8")
    else:
        (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    if not fresh:
        # Old by its *own* record — the file may have been touched a second ago
        # by a checkout, which is precisely the case that fooled version one.
        stale = dict(state, last_run=dict(state["last_run"],
                                          timestamp_utc="2026-08-01T12:00:00Z"))
        (root / "state.json").write_text(json.dumps(stale), encoding="utf-8")
    return root


@pytest.fixture()
def repo(tmp_path):
    """A git repo whose §0 key is `widget`, matching the QA root above."""
    r = tmp_path / "Widget"
    r.mkdir()
    for args in (["init", "-qb", "main"], ["add", "-A"]):
        subprocess.run(["git", *args], cwd=r, check=True, capture_output=True)
    (r / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=r, check=True, capture_output=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "first"], cwd=r, check=True, capture_output=True)
    return r


# ── the one case it exists for ────────────────────────────────────────────

def test_hand_written_state_written_this_turn_blocks_the_stop(tmp_path, repo):
    """The demonstrated failure: a run composed its state instead of measuring
    it, and every downstream guard stayed silent because nothing invoked them."""
    home = qa_root(tmp_path, harnessed=False).parent
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 2
    assert "without going through the harness" in proc.stderr
    assert "verdict-facts" in proc.stderr and "§6" in proc.stderr


# ── everything else must be silent ────────────────────────────────────────

def test_a_harness_written_state_says_nothing(tmp_path, repo):
    home = qa_root(tmp_path, harnessed=True).parent
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_an_old_state_in_an_ordinary_coding_session_says_nothing(tmp_path, repo):
    """The common case by far: a project has a QA baseline from last night and
    the session is doing something else entirely."""
    home = qa_root(tmp_path, harnessed=False, fresh=False).parent
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_a_project_with_no_qa_root_says_nothing(tmp_path, repo):
    proc = fire({"cwd": str(repo)}, home=tmp_path / "empty")
    assert proc.returncode == 0 and proc.stderr == ""


def test_it_never_blocks_twice(tmp_path, repo):
    """Blocking a stop sends the agent back to work; blocking the *next* stop
    for the same reason is a loop, which is worse than a miss."""
    home = qa_root(tmp_path, harnessed=False).parent
    proc = fire({"cwd": str(repo), "stop_hook_active": True}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_a_freshly_checked_out_repo_says_nothing(tmp_path, repo):
    """This repo's own CI caught the first version of this hook firing on
    Verdict's committed team-mode `.qa/`: `git checkout` stamps every file with
    the current time, so mtime is not evidence that a run happened. Recency now
    comes from the timestamp the run itself recorded, which copying cannot
    forge."""
    root = repo / ".qa"
    (root / "reports").mkdir(parents=True)
    (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "schema_version": 1, "run_type": "baseline", "run_number": 1,
        "last_run": {"timestamp_utc": "2026-08-01T12:00:00Z", "report": "reports/r.md"},
        "isolation_check": {}, "gates": {}, "findings": [], "verdict": "pass",
        "release_blockers": [], "not_tested": ["x"]}), encoding="utf-8")
    os.utime(root / "state.json", None)          # as a fresh checkout leaves it
    proc = fire({"cwd": str(repo)}, home=tmp_path / "empty")
    assert proc.returncode == 0 and proc.stderr == ""


def test_a_state_with_no_usable_run_time_says_nothing(tmp_path, repo):
    home = tmp_path / "home"
    root = home / "widget"
    (root / "reports").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps({"project": "widget", "last_run": {}}),
                                     encoding="utf-8")
    proc = fire({"cwd": str(repo)}, home=home)
    assert proc.returncode == 0 and proc.stderr == ""


def test_every_broken_input_fails_open(tmp_path):
    """A hook that bricks sessions is worse than the problem it polices."""
    for payload in ("not json", "", "[]", "null", '{"cwd": null}',
                    '{"cwd": "/nonexistent/nowhere"}'):
        proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                              capture_output=True, text=True)
        assert proc.returncode == 0, payload
        assert proc.stderr == "", payload


def test_a_team_mode_qa_root_inside_the_repo_is_found(tmp_path, repo):
    """Team mode keeps the QA root in the tree; the hook must see it there too."""
    root = repo / ".qa"
    (root / "reports").mkdir(parents=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    (root / "reports" / "r.md").write_text("# report\n", encoding="utf-8")
    (root / "state.json").write_text(json.dumps({
        "project": "widget", "schema_version": 1, "run_type": "baseline", "run_number": 1,
        "last_run": {"timestamp_utc": stamp, "report": "reports/r.md"},
        "isolation_check": {}, "gates": {}, "findings": [], "verdict": "pass",
        "release_blockers": [], "not_tested": ["x"]}), encoding="utf-8")
    proc = fire({"cwd": str(repo)}, home=tmp_path / "empty")
    assert proc.returncode == 2 and "without going through the harness" in proc.stderr


# ── one definition of "went through the harness", shared with the gate ──────
#
# This hook used to require all five signals and promise `verdict-gate
# --require-harness` would exit 6 on any gap. The gate decides on the three
# durable ones. A harness-produced state copied between checkouts — its
# facts.json and judgment.json are per-run scratch git never carries — tripped
# the hook, which then predicted a gate failure that did not happen. Seen on
# this repository's own run-4 state, copied from the clone that ran it.

def test_a_harness_state_whose_scratch_is_elsewhere_does_not_block(tmp_path, repo):
    root = qa_root(tmp_path, harnessed=True)
    (root / "facts.json").unlink()
    (root / "judgment.json").unlink()
    proc = fire({"cwd": str(repo)}, home=root.parent)
    assert proc.returncode == 0, proc.stderr
    assert "expected after a checkout or copy" in proc.stderr
    assert "exit 6" not in proc.stderr, "the gate will pass this state; do not say otherwise"


def test_the_block_names_a_durable_signal_before_promising_exit_6(tmp_path, repo):
    """When it does block, the gap it names is one the gate will refuse over."""
    proc = fire({"cwd": str(repo)}, home=qa_root(tmp_path, harnessed=False).parent)
    assert proc.returncode == 2
    assert "state_computed" in proc.stderr or "report_rendered" in proc.stderr
    assert "facts_measured" not in proc.stderr.split("harness (")[1].split(")")[0], \
        "per-run scratch is not what the block is about"
    assert "exit 6" in proc.stderr


# ── the run that never finalized (0.89.0) ─────────────────────────────────

def _marker(root: Path, *, session="sess-1", minutes_ago=5, **extra):
    from datetime import timedelta
    root.mkdir(parents=True, exist_ok=True)
    started = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    doc = {"started_utc": started.strftime("%Y-%m-%dT%H:%M:%SZ"), "repo": "/x", "git_sha": "abc"}
    if session:
        doc["session_id"] = session
    doc.update(extra)
    (root / "run-in-progress.json").write_text(json.dumps(doc), encoding="utf-8")
    return root / "run-in-progress.json"


def _tester_stops(repo, session="sess-1", agent_type="verdict:verdict", **extra):
    return {"cwd": str(repo), "hook_event_name": "SubagentStop", "session_id": session,
            "agent_type": agent_type, **extra}


def test_a_tester_that_measured_and_never_finalized_is_told_once(tmp_path, repo):
    """The recorded signature of a cheaper model: the facts are measured, the code is
    read, the turn ends — and there is no state, no report, a lost run. The marker
    `verdict-facts` leaves and only `verdict-finalize` removes is the evidence."""
    root = qa_root(tmp_path, harnessed=True, fresh=False)      # last night's state, untouched
    marker = _marker(root)
    proc = fire(_tester_stops(repo), home=root.parent)
    assert proc.returncode == 2
    assert "verdict-finalize" in proc.stderr and "never did" in proc.stderr
    assert "Traceback" not in proc.stderr
    assert json.loads(marker.read_text(encoding="utf-8")).get("stop_told"), "the marker remembers"
    again = fire(_tester_stops(repo), home=root.parent)
    assert again.returncode == 0 and again.stderr == "", "told once per marker, never a loop"


def test_a_first_run_that_never_finalized_has_no_state_at_all(tmp_path, repo):
    """The case the hook used to leave at its first `is_file()`: no state.json exists,
    because the run that would have written the first one is the run that stopped."""
    root = tmp_path / "home" / "widget"
    _marker(root)
    proc = fire(_tester_stops(repo, agent_type="verdict"), home=root.parent)
    assert proc.returncode == 2 and "verdict-finalize" in proc.stderr

    team = repo / ".qa"
    _marker(team, session="sess-2")
    proc = fire(_tester_stops(repo, session="sess-2", agent_type="verdict-rc"),
                home=tmp_path / "empty")
    assert proc.returncode == 2, "a team-mode root inside the repo is found by its marker too"


@pytest.mark.parametrize("why, marker_kw, event_kw", [
    ("another session's marker — last night's, or a run next door",
     {"session": "someone-else"}, {}),
    ("a parallel agent finishing while the tester is still at work",
     {}, {"agent_type": "Explore"}),
    ("an agent the CLI did not name", {}, {"agent_type": None}),
    ("the main session ending its turn while a background tester runs",
     {}, {"hook_event_name": "Stop"}),
    ("a marker written by a harness that recorded no session", {"session": None}, {}),
    ("a marker too old to be the run that is ending now", {"minutes_ago": 7 * 60}, {}),
    ("a marker from the future — a clock, not a run", {"minutes_ago": -30}, {}),
    ("already continuing because of this hook", {}, {"stop_hook_active": True}),
])
def test_everything_short_of_identity_says_nothing(tmp_path, repo, why, marker_kw, event_kw):
    root = qa_root(tmp_path, harnessed=True, fresh=False)
    _marker(root, **marker_kw)
    event = _tester_stops(repo)
    event.update(event_kw)
    proc = fire({k: v for k, v in event.items() if v is not None}, home=root.parent)
    assert proc.returncode == 0 and proc.stderr == "", why


def test_an_unreadable_marker_fails_open(tmp_path, repo):
    root = qa_root(tmp_path, harnessed=True, fresh=False)
    (root / "run-in-progress.json").write_text("{not json", encoding="utf-8")
    proc = fire(_tester_stops(repo), home=root.parent)
    assert proc.returncode == 0 and proc.stderr == ""
    (root / "run-in-progress.json").write_text("[]", encoding="utf-8")
    assert fire(_tester_stops(repo), home=root.parent).returncode == 0


def test_a_finalized_run_leaves_no_marker_and_the_old_rule_still_speaks(tmp_path, repo):
    """The new rule runs first; it must not swallow the rule this hook was written for."""
    home = qa_root(tmp_path, harnessed=False).parent
    proc = fire(_tester_stops(repo), home=home)
    assert proc.returncode == 2 and "without going through the harness" in proc.stderr
