"""`verdict-replay` (0.90.12): a finding's `repro` command run again on a fresh checkout.

The pass that made the 2026-10-16/17 stranger reports credible — a fresh clone, the
finding's script, the expected value — was done by hand six times and never appeared in a
report built on the tester's own scratch. This is that pass as a command, and the gate
reading its ledger.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import git, judgment
from verdict_mcp import replay
from verdict_mcp.gate import _fmt_comment, _fmt_text, evaluate
from verdict_mcp.harness import facts_main, finalize_main
from verdict_mcp.validate import validate_finding

PY = sys.executable
TEMPLATE = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "templates" / "finding.example.json"

DEFECT = "def to_cents(amount):\n    return int(amount * 100)\n"
FIXED = ("from decimal import Decimal, ROUND_HALF_UP\n"
         "def to_cents(amount):\n"
         "    return int(Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP) * 100)\n")


def _repo(tmp_path):
    """A team-mode repo (`<repo>/.qa`) with the defect at HEAD and the FIX in the working tree:
    a replay that tested the tester's own tree would come back clean."""
    r = tmp_path / "pricer"
    (r / "src" / "pricer").mkdir(parents=True)
    (r / ".qa").mkdir()
    git(["init", "-qb", "main"], r)
    (r / "src" / "pricer" / "__init__.py").write_text("", encoding="utf-8")
    (r / "src" / "pricer" / "money.py").write_text(DEFECT, encoding="utf-8")
    (r / "probe.py").write_text("import os; print(__file__.replace(os.sep, '/'))\n", encoding="utf-8")
    git(["add", "-A"], r)
    git(["commit", "-qm", "defect at HEAD"], r)
    (r / "src" / "pricer" / "money.py").write_text(FIXED, encoding="utf-8")
    return r


def _finding(fid, repro=None, **over):
    """A finding as state.json carries it (finalize's computed keys included)."""
    f = {"id": fid, "title": f"finding {fid}", "severity": "Major", "priority": "P1",
         "status": "open", "confidence": "proven", "first_seen": "2026-10-17", "age_days": 0,
         "delta": "NEW", "evidence": ["src/pricer/money.py:2 — int() truncates"]}
    if repro is not None:
        f["repro"] = repro
    f.update(over)
    return f


def _filed(fid, repro=None, **over):
    """A finding as its author writes it to findings/<ID>.json: judgment only."""
    return {k: v for k, v in _finding(fid, repro, **over).items()
            if k not in ("first_seen", "age_days", "delta")}


def _state(repo, findings, **over):
    state = {"schema_version": 3, "project": "PRICER", "run_number": 7, "verdict": "fail",
             "last_run": {"timestamp_utc": "2026-10-17T08:00:00Z", "git_sha": "x",
                          "sha_range": "a..b"},
             "release_blockers": [], "not_tested": [], "findings": findings}
    state.update(over)
    (repo / ".qa" / "state.json").write_text(json.dumps(state), encoding="utf-8")
    return state


ASSERT_CMD = f'{PY} -c "from pricer.money import to_cents; assert to_cents(1.005) == 101, to_cents(1.005)"'
TRUNCATES = {"command": ASSERT_CMD, "cwd": "repo",
             "expect": {"exit": 1, "stderr_contains": "AssertionError: 100"}}


def _rows(repo):
    return [json.loads(line) for line in (repo / ".qa" / "replays.jsonl").read_text(encoding="utf-8").splitlines()]


def _worktrees(repo):
    out = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                         capture_output=True, text=True, check=True).stdout
    return [str(Path(line.split(" ", 1)[1])) for line in out.splitlines() if line.startswith("worktree ")]


# ── the replay itself ─────────────────────────────────────────────────────

def test_the_defect_at_head_reproduces_on_a_fresh_checkout_not_the_dirty_tree(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES)])
    assert replay.main([str(repo)]) == 0, capsys.readouterr().err
    (row,) = _rows(repo)
    head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()
    assert row["result"] == "reproduced" and row["id"] == "PRICER-F-3"
    assert row["checkout"] == head and row["run_number"] == 7 and row["at"].endswith("Z")
    assert row["exit"] == 1 and "stderr_contains found" in " ".join(row["checks"])
    assert "AssertionError: 100" in row["output_tail"]
    # the working tree still holds the fix: the replay did not read it
    assert (repo / "src" / "pricer" / "money.py").read_text(encoding="utf-8") == FIXED
    assert _worktrees(repo) == [str(repo)], "the fresh worktree is removed afterwards"
    assert "✓ PRICER-F-3 reproduced" in capsys.readouterr().err


def test_a_missed_expectation_is_not_reproduced_and_exit_1(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES),
                  _finding("PRICER-F-4", {"command": f"{PY} -c \"import pricer; print('ok')\"",
                                           "expect": {"stdout_contains": "never printed"}})])
    assert replay.main([str(repo)]) == 1
    by_id = {r["id"]: r for r in _rows(repo)}
    assert by_id["PRICER-F-3"]["result"] == "reproduced"
    assert by_id["PRICER-F-4"]["result"] == "not reproduced"
    assert by_id["PRICER-F-4"]["checks"] == ["stdout_contains MISSING: 'never printed'"]
    err = capsys.readouterr().err
    assert "1 reproduced · 1 not reproduced · 0 could not run" in err


def test_a_wrong_exit_code_is_not_reproduced_and_no_expect_means_exit_0(tmp_path):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", {"command": ASSERT_CMD, "expect": {"exit": 0}}),
                  _finding("PRICER-F-4", {"command": f"{PY} -c \"import pricer\""})])
    assert replay.main([str(repo)]) == 1
    by_id = {r["id"]: r for r in _rows(repo)}
    assert by_id["PRICER-F-3"]["result"] == "not reproduced"
    assert by_id["PRICER-F-3"]["checks"] == ["exit 1 (expected 0)"]
    assert by_id["PRICER-F-4"]["result"] == "reproduced" and by_id["PRICER-F-4"]["expect"] == {"exit": 0}


def test_a_command_that_cannot_start_or_times_out_is_could_not_run(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-5", {"command": "no-such-tool-xyz --flag", "expect": {"exit": 0}}),
                  _finding("PRICER-F-6", {"command": f"{PY} -c \"import time; time.sleep(6)\"",
                                           "expect": {"exit": 0}})])
    assert replay.main([str(repo), "--timeout", "2"]) == 2, "nothing could be replayed"
    by_id = {r["id"]: r for r in _rows(repo)}
    assert by_id["PRICER-F-5"]["result"] == "could not run"
    assert by_id["PRICER-F-5"]["checks"] == ["the command could not start (exit 127)"]
    assert by_id["PRICER-F-6"]["result"] == "could not run"
    assert by_id["PRICER-F-6"]["checks"] == ["timed out after 2s"]
    assert "? PRICER-F-5 could not run" in capsys.readouterr().err
    assert _worktrees(repo) == [str(repo)]


def test_a_path_into_the_original_checkout_is_rewritten_to_the_fresh_tree(tmp_path):
    """An editable install's `.pth`, a script named by its absolute path: both point at the
    tester's tree. The command runs where the fresh checkout is."""
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-7", {"command": f"{PY} {repo / 'probe.py'}",
                                           "expect": {"stdout_contains": "verdict-replay-"}})])
    assert replay.main([str(repo)]) == 0
    (row,) = _rows(repo)
    assert row["result"] == "reproduced"
    assert str(repo) not in row["command"] and row["command"].endswith("/tree/probe.py")


def test_a_path_the_fresh_tree_lacks_stays_where_it_is(tmp_path):
    """The interpreter in the checkout's own `.venv` is untracked: rewriting it to the fresh
    tree finds nothing (exit 127 on every real record, 2026-10-17). It stays; the fresh tree
    still comes first on the import path."""
    repo = _repo(tmp_path)
    (repo / ".venv").mkdir()
    tool = repo / ".venv" / "tool.py"      # untracked, like the interpreter in a checkout's venv
    tool.write_text("import runpy, sys; runpy.run_path(sys.argv[1], run_name='__main__')\n", encoding="utf-8")
    _state(repo, [_finding("PRICER-F-7", {"command": f"{PY} {tool} {repo / 'probe.py'}",
                                           "expect": {"stdout_contains": "/tree/probe.py"}})])
    assert replay.main([str(repo)]) == 0
    (row,) = _rows(repo)
    assert row["result"] == "reproduced", row
    assert row["command"] == f"{PY} {tool} {row['scratch']}{os.sep}probe.py"


def test_from_qa_root_the_fresh_tree_is_first_on_the_import_path(tmp_path):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-7", {"command": f"{PY} -c \"import pricer, os; print(pricer.__file__.replace(os.sep, '/'))\"",
                                           "cwd": "qa_root",
                                           "expect": {"stdout_contains": "/tree/src/pricer/"}})])
    assert replay.main([str(repo)]) == 0
    (row,) = _rows(repo)
    assert row["result"] == "reproduced" and row["cwd"] == str(repo / ".qa")


def test_cwd_is_a_directory_inside_the_fresh_checkout_or_the_command_does_not_run(tmp_path):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-8", {"command": f"{PY} -c \"import os; print(os.getcwd().replace(os.sep, '/'))\"",
                                           "cwd": "src", "expect": {"stdout_contains": "/tree/src"}}),
                  _finding("PRICER-F-9", {"command": "true", "cwd": "../.."}),
                  _finding("PRICER-F-10", {"command": "true", "cwd": "/"}),
                  _finding("PRICER-F-11", {"command": "true", "cwd": "no-such-dir"})])
    assert replay.main([str(repo)]) == 2
    by_id = {r["id"]: r for r in _rows(repo)}
    assert by_id["PRICER-F-8"]["result"] == "reproduced"
    for fid in ("PRICER-F-9", "PRICER-F-10"):
        assert by_id[fid]["result"] == "could not run" and "outside the fresh checkout" in by_id[fid]["checks"][0]
    assert by_id["PRICER-F-11"]["result"] == "could not run" and "not a directory" in by_id["PRICER-F-11"]["checks"][0]


def test_default_scope_is_open_major_plus_and_named_ids_replay_anything(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES),
                  _finding("PRICER-F-12", {"command": "true"}, severity="Minor", priority="P3"),
                  _finding("PRICER-F-13", {"command": "false"}, status="resolved"),
                  _finding("PRICER-F-14")])
    assert replay.main([str(repo)]) == 0
    assert [r["id"] for r in _rows(repo)] == ["PRICER-F-3"]
    err = capsys.readouterr().err
    assert "PRICER-F-14 has no structured repro" in err and "1 without a repro" in err
    assert replay.main([str(repo), "PRICER-F-12", "PRICER-F-13"]) == 1
    assert [(r["id"], r["result"]) for r in _rows(repo)[1:]] == [("PRICER-F-12", "reproduced"),
                                                                 ("PRICER-F-13", "not reproduced")]


def test_show_prints_the_commands_and_runs_nothing(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES)])
    assert replay.main([str(repo), "--show"]) == 0
    out = capsys.readouterr().out
    assert ASSERT_CMD in out and 'expect={"exit": 1, "stderr_contains": "AssertionError: 100"}' in out
    assert not (repo / ".qa" / "replays.jsonl").exists() and _worktrees(repo) == [str(repo)]


def test_keep_leaves_the_worktree_for_a_look(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES)])
    assert replay.main([str(repo), "--keep"]) == 0
    (row,) = _rows(repo)
    assert row["scratch"] in _worktrees(repo)
    subprocess.run(["git", "-C", str(repo), "worktree", "remove", "--force", row["scratch"]], check=True)


def test_nothing_to_replay_and_no_repository_are_exit_2(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-14"), _finding("PRICER-F-15", severity="Minor")])
    assert replay.main([str(repo)]) == 2
    assert "nothing to replay" in capsys.readouterr().err
    assert not (repo / ".qa" / "replays.jsonl").exists()
    assert replay.main([str(tmp_path / "nowhere")]) == 2


def test_replay_one_without_a_repro_block_is_could_not_run_not_a_crash(tmp_path):
    row = replay.replay_one(_finding("PRICER-F-9"), tmp_path, tmp_path / "tree", tmp_path, 5)
    assert row["result"] == "could not run" and "no structured repro" in row["checks"][0]


def test_remove_checkout_only_removes_the_directory_it_made(tmp_path):
    keep = tmp_path / "mine" / "tree"
    keep.mkdir(parents=True)
    (tmp_path / "mine" / "precious.txt").write_text("x", encoding="utf-8")
    replay._remove_checkout(tmp_path, keep)
    assert (tmp_path / "mine" / "precious.txt").exists()


def test_without_repro_names_the_open_proven_major_plus_findings_only():
    findings = [_finding("A-F-1"), _finding("A-F-2", TRUNCATES), _finding("A-F-3", severity="Minor"),
                _finding("A-F-4", confidence="likely"), _finding("A-F-5", status="resolved"),
                _finding("A-F-6", severity="Critical"), _finding("A-F-7", {"command": "   "})]
    assert replay.without_repro(findings) == ["A-F-1", "A-F-6", "A-F-7"]


def test_an_editable_install_of_the_original_checkout_is_disarmed_at_startup(tmp_path):
    """A `.pth` line (emulated: the original's `src` already on PYTHONPATH) and a meta-path
    finder carrying the original's build directory (meson-python) both import the tester's
    own tree, PYTHONPATH order notwithstanding — numpy-financial, 2026-10-17. The guard runs
    after site-packages and before the command; the interpreter's own prefix is kept."""
    repo = _repo(tmp_path)
    # the probe learns the original's path at run time: a literal in the command would be
    # rewritten to the fresh tree, which is the point of the rewrite
    probe = ("import os, sys; n = lambda p: os.path.normcase(os.path.normpath(p)); "
             "o = n(os.environ['VERDICT_REPLAY_ORIGINAL'].split(os.pathsep)[0]) + os.sep; "
             "print([p for p in sys.path if n(p).startswith(o)]); "
             "print(any(n(getattr(f, '_build_path', 'x')).startswith(o) for f in sys.meta_path))")
    _state(repo, [_finding("PRICER-F-7", {"command": f"{PY} -c \"{probe}\"",
                                           "expect": {"stdout_contains": "[]\nFalse"}})])
    import os
    env = dict(os.environ, PYTHONPATH=str(repo / "src"))
    with pytest.MonkeyPatch.context() as mp:
        for k, v in env.items():
            mp.setenv(k, v)
        rc = replay.main([str(repo)])
    (row,) = _rows(repo)
    assert rc == 0 and row["result"] == "reproduced" and row["isolated"] is True, row
    # the guard itself, as a function, on a finder like meson-python's
    ns = {}
    exec(compile(replay.GUARD, "sitecustomize.py", "exec"), ns)
    class Finder:
        def __init__(self, build):
            self._top_level_modules = ("pkg",)
            self._build_path = build
            self._cmd = ["ninja", "-C", build]
    orig = str(repo)
    venv = str(repo / ".venv")
    path, finders = ns["disarm"](
        [f"{orig}/src", orig, f"{venv}/lib/python3/site-packages", "/usr/lib/python3", f"{orig}-other"],
        [Finder(f"{orig}/build/cp312"), Finder("/elsewhere/build"), object()],
        [orig], [venv])
    assert path == [f"{venv}/lib/python3/site-packages", "/usr/lib/python3", f"{orig}-other"]
    assert [getattr(f, "_build_path", None) for f in finders] == ["/elsewhere/build", None]


def test_output_naming_the_original_checkout_marks_the_replay_not_isolated(tmp_path, capsys):
    repo = _repo(tmp_path)
    # a path the fresh tree lacks (a build directory, as meson-python prints) is not rewritten,
    # so the output names the original — the shape of the 2026-10-17 numpy-financial replay
    spelled = str(repo).replace(os.sep, "/")      # a backslash inside a Python literal is an escape
    _state(repo, [_finding("PRICER-F-3", {"command": f"{PY} -c \"print('from {spelled}/build/cp312/pricer/money.py')\"",
                                           "expect": {"stdout_contains": "from"}}),
                  _finding("PRICER-F-4", {"command": f"{PY} -c \"print('{spelled}/.venv/lib/site-packages/x.py: warning')\"",
                                           "expect": {"stdout_contains": "warning"}})])
    assert replay.main([str(repo)]) == 0
    by_id = {r["id"]: r for r in _rows(repo)}
    assert by_id["PRICER-F-3"]["result"] == "reproduced" and by_id["PRICER-F-3"]["isolated"] is False
    assert "the output names the original checkout" in by_id["PRICER-F-3"]["checks"][-1]
    assert by_id["PRICER-F-4"]["isolated"] is True, "a warning from the checkout's venv is not the tree"
    err = capsys.readouterr().err
    assert "✓ PRICER-F-3 reproduced (NOT isolated)" in err and "1 not isolated (PRICER-F-3)" in err
    r = evaluate(str(repo), fail_on="fail", max_age_hours=None, min_run_number=None)
    assert r["replays"]["not_isolated"] == ["PRICER-F-3"]
    assert "PRICER-F-3 · replay ✓ reproduced, NOT isolated" in _fmt_text(r, 10)
    assert "1 NOT isolated (PRICER-F-3)" in _fmt_text(r, 10)


def test_a_claimed_reproduction_that_crashed_needs_a_stderr_expectation(tmp_path):
    """`expect: {exit: 1}` is met by any crash on the way to the defect."""
    repo = _repo(tmp_path)
    crash = f"{PY} -c \"raise RuntimeError('boom')\""
    _state(repo, [_finding("PRICER-F-3", {"command": crash, "expect": {"exit": 1}}),
                  _finding("PRICER-F-4", {"command": crash,
                                           "expect": {"exit": 1, "stderr_contains": "RuntimeError: boom"}}),
                  _finding("PRICER-F-5", {"command": crash, "expect": {"exit": 0}})])
    assert replay.main([str(repo)]) == 1
    by_id = {r["id"]: r for r in _rows(repo)}
    assert by_id["PRICER-F-3"]["result"] == "could not run"
    assert "an exit code alone cannot tell a crash from the defect" in by_id["PRICER-F-3"]["checks"][-1]
    assert by_id["PRICER-F-4"]["result"] == "reproduced"
    assert by_id["PRICER-F-5"]["result"] == "not reproduced", "only a claimed reproduction is downgraded"


def test_a_fresh_tree_that_cannot_be_imported_is_could_not_run_not_a_refutation(tmp_path):
    """numpy-financial, 2026-10-17: with the editable finder disarmed the fresh tree has no
    built `_cfinancial`, and the replay read "not reproduced" — a refutation it had not
    earned. The command never reached the defect."""
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", {"command": f"{PY} -c \"import pricer.compiled_ext; print('RESULT: bad')\"",
                                           "expect": {"exit": 1, "stdout_contains": "RESULT: bad"}})])
    assert replay.main([str(repo)]) == 2
    (row,) = _rows(repo)
    assert row["result"] == "could not run", row
    assert "the fresh tree could not be imported (ModuleNotFoundError:" in row["checks"][-1]
    assert "compiled extensions needs its build step" in row["checks"][-1]


# ── the gate reads the ledger ─────────────────────────────────────────────

def test_the_gate_marks_each_open_finding_with_its_latest_replay(tmp_path, capsys):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES),
                  _finding("PRICER-F-4", {"command": "true", "expect": {"stdout_contains": "never"}}),
                  _finding("PRICER-F-5", {"command": "no-such-tool-xyz"}),
                  _finding("PRICER-F-6"),
                  _finding("PRICER-F-7", severity="Minor", priority="P3")])
    assert replay.main([str(repo)]) == 1
    # a later row for the same finding supersedes the earlier one
    with (repo / ".qa" / "replays.jsonl").open("a", encoding="utf-8") as h:
        h.write(json.dumps({"id": "PRICER-F-4", "result": "reproduced", "at": "2026-10-18T00:00:00Z",
                            "checkout": "abc"}) + "\n")
    r = evaluate(str(repo), fail_on="fail", max_age_hours=None, min_run_number=None)
    assert r["replays"] == {"reproduced": ["PRICER-F-3", "PRICER-F-4"], "not_reproduced": [],
                            "could_not_run": ["PRICER-F-5"], "not_isolated": [],
                            "unreplayed_proven": ["PRICER-F-6"]}
    by_id = {f["id"]: f for f in r["findings_open"]}
    assert by_id["PRICER-F-4"]["replay"] == {"result": "reproduced", "at": "2026-10-18T00:00:00Z",
                                             "checkout": "abc", "isolated": True}
    assert "replay" not in by_id["PRICER-F-6"] and "replay" not in by_id["PRICER-F-7"]
    text = _fmt_text(r, 10)
    assert ("replay: 2 reproduced on a fresh checkout · 1 could not run (PRICER-F-5) · "
            "1 proven Major+ never replayed") in text
    assert "PRICER-F-3 Major/P1 finding PRICER-F-3 · replay ✓ reproduced" in text
    assert "PRICER-F-5 Major/P1 finding PRICER-F-5 · replay ? could not run" in text
    comment = _fmt_comment(r, 10)
    assert "**Replay:** 2 reproduced on a fresh checkout" in comment
    assert "| finding PRICER-F-3 · replay ✓ reproduced |" in comment
    assert json.dumps(r)  # the JSON format carries it


def test_a_record_nobody_replayed_shows_nothing(tmp_path):
    repo = _repo(tmp_path)
    _state(repo, [_finding("PRICER-F-3", TRUNCATES)])
    r = evaluate(str(repo), fail_on="fail", max_age_hours=None, min_run_number=None)
    assert "replays" not in r and "replay" not in r["findings_open"][0]
    assert "replay" not in _fmt_text(r, 10) and "Replay" not in _fmt_comment(r, 10)


def test_an_unreadable_ledger_line_is_skipped(tmp_path):
    repo = _repo(tmp_path)
    (repo / ".qa" / "replays.jsonl").write_text(
        'not json\n{"id": "PRICER-F-3", "result": "reproduced"}\n[1, 2]\n', encoding="utf-8")
    assert replay.load_replays(repo / ".qa") == {"PRICER-F-3": {"id": "PRICER-F-3", "result": "reproduced"}}
    assert replay.load_replays(tmp_path / "missing") == {}


# ── the validator and the template ────────────────────────────────────────

@pytest.mark.parametrize("repro, phrase", [
    ("python -c pass", "repro must be an object"),
    ({"cwd": "repo"}, "repro.command must be the shell command"),
    ({"command": "  "}, "repro.command must be the shell command"),
    ({"command": "true", "cwd": "/tmp"}, "repro.cwd must be 'repo', 'qa_root' or a relative path"),
    ({"command": "true", "cwd": "../x"}, "repro.cwd must be 'repo', 'qa_root' or a relative path"),
    ({"command": "true", "expect": []}, "repro.expect must be an object"),
    ({"command": "true", "expect": {}}, "repro.expect must be an object"),
    ({"command": "true", "expect": {"returncode": 1}}, "unknown keys ['returncode']"),
    ({"command": "true", "expect": {"exit": True}}, "repro.expect.exit must be an integer"),
    ({"command": "true", "expect": {"exit": "1"}}, "repro.expect.exit must be an integer"),
    ({"command": "true", "expect": {"stdout_contains": ""}}, "repro.expect.stdout_contains must be a non-empty string"),
    ({"command": "true", "expect": {"stderr_contains": 3}}, "repro.expect.stderr_contains must be a non-empty string"),
])
def test_a_malformed_repro_is_refused_as_it_is_written(repro, phrase):
    bad = validate_finding(_filed("PRICER-F-3", repro), "findings/PRICER-F-3.json", set())
    assert any(phrase in b for b in bad), bad


def test_a_well_formed_or_absent_repro_passes_and_the_template_is_one():
    assert validate_finding(_filed("PRICER-F-3"), "f", set()) == []
    assert validate_finding(_filed("PRICER-F-3", TRUNCATES), "f", set()) == []
    assert validate_finding(_filed("PRICER-F-3", {"command": "true", "cwd": "tests",
                                                    "expect": {"stdout_contains": "x"}}), "f", set()) == []
    example = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    assert example["repro"]["expect"] == {"exit": 1, "stderr_contains": "AssertionError: 100"}
    assert validate_finding(example, "template", set()) == []


# ── finalize carries the block and says who has none ──────────────────────

def test_finalize_keeps_repro_on_the_finding_and_names_the_proven_findings_without_one(
        repo, qa_root, capsys):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    with_block = {"id": "W-F-1", "title": "off-by-one at line 42", "severity": "Major", "priority": "P1",
                  "status": "open", "failure_classification": "REAL_DEFECT", "confidence": "proven",
                  "evidence": ["a.py:1 the guard"],
                  "repro": {"command": "python -c \"import a; assert a.x == 2, a.x\"",
                            "expect": {"exit": 1, "stderr_contains": "AssertionError: 1"}}}
    prose_only = dict(with_block, id="W-F-2", title="a second defect in a.py", repro=None)
    del prose_only["repro"]
    minor = dict(prose_only, id="W-F-3", title="a third thing in a.py", severity="Minor", priority="P3")
    j = judgment(findings=[with_block, prose_only, minor])
    (qa_root / "judgment.json").write_text(json.dumps(j), encoding="utf-8")
    rc = finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")])
    err = capsys.readouterr().err
    assert rc == 0, err
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in state["findings"]}
    assert by_id["W-F-1"]["repro"] == with_block["repro"], "the block rides into the state verdict-replay reads"
    assert "no structured repro on 1 proven Major+ finding(s): W-F-2" in err
    assert "W-F-3" not in err.split("no structured repro")[1].splitlines()[0]
