"""`eval/pin_check.py` scores a mutant from pytest's summary line, never from
the exit code alone.

pytest exits non-zero for a usage error, an internal error, a failed collection
and "no tests ran" exactly as it does for a failing test. Read as `rc != 0`, a
mutant that leaves a module unimportable is scored as a defended rule when in
truth nothing ran (VERDICT-F-68) — the reading run 11 had already recorded a
lesson about, one release earlier.
"""

import json
import os
import pathlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import pin_check  # noqa: E402

classify = pin_check.classify


def test_a_failed_test_is_a_kill():
    assert classify(1, "FAILED tests/test_x.py::test_a - assert 1 == 2\n"
                       "2 failed, 790 passed in 70.11s\n") == "killed"


def test_an_errored_test_is_a_kill():
    """A fixture that blows up under the mutant is the suite noticing too."""
    assert classify(1, "1 error, 5 passed in 1.02s\n") == "killed"
    assert classify(1, "3 errors, 5 passed in 1.02s\n") == "killed"


def test_a_green_suite_is_a_survivor():
    assert classify(0, "795 passed in 70.00s\n") == "survived"


def test_a_collection_error_is_not_a_kill():
    """The exact case: a mutant that breaks an import exits 2 with `1 error`
    on the summary line, and nothing was measured."""
    out = ("ERROR collecting tests/test_hooks.py\n"
           "ImportError while importing test module ...\n"
           "!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!\n"
           "1 error in 0.31s\n")
    assert classify(2, out) == "error"


def test_a_usage_error_is_not_a_kill():
    assert classify(4, "ERROR: usage: pytest [options] [file_or_dir]\n") == "error"


def test_no_tests_ran_is_not_a_kill():
    assert classify(5, "no tests ran in 0.01s\n") == "error"


def test_a_failing_exit_without_a_summary_is_not_a_kill():
    """A traceback from pytest itself, or a runner that never reached the
    summary: exit 1, nothing counted, not a kill."""
    assert classify(1, "Traceback (most recent call last):\n  ...\nRuntimeError: boom\n") == "error"
    assert classify(1, "") == "error"


def test_only_the_final_summary_line_counts():
    """A test that itself runs pytest prints a nested `1 failed in …` into the
    captured output; the verdict is the last summary line, not any line."""
    nested_green = ("--- Captured stdout call ---\n1 failed in 0.10s\n"
                    "795 passed in 70.00s\n")
    assert classify(0, nested_green) == "survived"
    nested_red = "1 failed in 0.10s\n792 passed, 3 failed in 70.00s\n"
    assert classify(1, nested_red) == "killed"
    # exit 1 whose last summary shows nothing failed is the tool disagreeing
    # with itself — not a kill.
    assert classify(1, "1 failed in 0.10s\n795 passed in 70.00s\n") == "error"


def test_the_readme_badge_states_the_catalogue_size():
    """A badge that goes stale is a claim that quietly stops being true: the
    README carried "mutation kill 66.4%" from an early campaign long after the
    suite had tripled. The pinned-rules badge states the catalogue's scored
    size, and any change to the catalogue must move it."""
    import json
    import re
    root = Path(__file__).resolve().parent.parent
    catalogue = json.loads((root / "eval" / "pinned_mutants.json").read_text(encoding="utf-8"))
    scored = sum(1 for m in catalogue if not m.get("equivalent"))
    readme = (root / "README.md").read_text(encoding="utf-8")
    m = re.search(r"pinned_rules-(\d+)%2F(\d+)_killed", readme)
    assert m, "the README has no pinned-rules badge"
    assert (int(m.group(1)), int(m.group(2))) == (scored, scored), (
        f"badge says {m.group(1)}/{m.group(2)}, the catalogue scores {scored}")


def test_every_catalogue_anchor_matches_exactly_once():
    """A mutant is applied by exact replacement, and an `old` that does not
    occur exactly once is reported STALE and counted as a survivor. So an edit
    that moves an anchored line quietly takes a rule out of the measurement
    while the badge above goes on counting it. Four scored entries went that
    way and stayed there through 0.89.0: T02 when `_git_operands` repeated the
    tar parser's `--` line (0.80.0), 0.78.0 R2 when the call beside the fold
    gained an argument (0.83.0), 0.78.0 R5 and 0.79.0 S7 when the finding
    checks moved into `validate_finding` one indent shallower (0.84.0). A full
    `pin_check` could not have produced the number the badge stated, and
    nothing in the suite said so — they were found by checking every anchor
    while 0.89.0's own mutants were being added.

    So it is checked on every run of the suite, and the edit that moves the
    line is the edit that goes red. Equivalent entries too: out of the score,
    they are still claims somebody re-measures.

    Mutation runs leave this test out (`pin_check.SUITE` deselects it):
    applying a mutant takes its own anchor out of the tree, so this test goes
    red under the mutant rather than for the rule, and the failure would score
    as a kill.
    """
    stale = []
    for m in json.loads(pin_check.CATALOGUE.read_text(encoding="utf-8")):
        target = pin_check.ROOT / m["path"]
        if not target.is_file():
            stale.append(f"{m['label']} — {m['path']}: no such file")
            continue
        hits = target.read_text(encoding="utf-8").count(m["old"])
        if hits != 1:
            stale.append(f"{m['label']} — {m['path']}: anchor matched {hits}")
    assert not stale, (
        "pin_check would score these as survivors. Re-anchor each on the rule's current "
        "code (`git log -S` on the old text names the change that moved it):\n  "
        + "\n  ".join(stale))


def test_mutation_runs_leave_the_anchor_test_out():
    """Inside a mutant the test above fails whatever the rule, because the
    mutant has just deleted its own anchor — so a whole-suite run that kept it
    would score every entry killed, including the ones nothing defends.
    pin_check and the sweep both run `pin_check.SUITE`, which deselects it.

    By the function's own name: pytest says nothing about a deselect that
    matches no test, so a rename would quietly put it back into every mutant
    run, and every rule would score killed again."""
    node = f"tests/test_pin_check.py::{test_every_catalogue_anchor_matches_exactly_once.__name__}"
    suite = pin_check.SUITE
    assert any(suite[i:i + 2] == ["--deselect", node] for i in range(len(suite) - 1)), (
        f"pin_check.SUITE runs {node} inside every mutant: {suite}")


def test_a_mutation_is_written_atomically(tmp_path):
    """A kill between the truncate and the flush left a source file EMPTY —
    measured on this repository when a whole-catalogue run was interrupted:
    `harness.py` came back 2286 lines shorter, and the lock had already been
    released, so nothing said the tree was broken.

    Two properties: the swap never truncates the original in place, and the
    file that lands is the whole new content.
    """
    target = tmp_path / "module.py"
    target.write_text("original\n" * 100, encoding="utf-8")
    inode_before = target.stat().st_ino
    pin_check.write_atomic(target, "mutated\n" * 100)
    assert target.read_text(encoding="utf-8") == "mutated\n" * 100
    assert target.stat().st_ino != inode_before, (
        "the file was rewritten in place, so a kill mid-write can still empty it")
    assert not list(tmp_path.glob("*.pin_check.tmp")), "the temp file outlived the swap"


def test_the_restorer_puts_a_file_back_whole(tmp_path):
    """The other end of the same guarantee: what `hold` captured is what
    `restore` writes, atomically.

    Constructing one installs signal handlers and an atexit hook in whatever
    process it runs in, so this test puts both back — a test that leaves the
    runner holding a foreign SIGINT handler is a test that changes what
    Ctrl-C does to the suite.
    """
    import atexit
    import signal

    target = tmp_path / "module.py"
    original = "def rule():\n    return True\n"
    target.write_text(original, encoding="utf-8")
    handlers = {name: signal.getsignal(getattr(signal, name))
                for name in ("SIGINT", "SIGTERM") if hasattr(signal, name)}
    keeper = pin_check.Restorer()
    try:
        keeper.hold(target, original)
        pin_check.write_atomic(target, "def rule():\n    return False\n")
        assert target.read_text(encoding="utf-8") != original
        keeper.restore()
        assert target.read_text(encoding="utf-8") == original
    finally:
        atexit.unregister(keeper.restore)
        for name, handler in handlers.items():
            signal.signal(getattr(signal, name), handler)


def test_the_restorer_is_constructible_where_a_signal_is_missing(monkeypatch):
    """Windows has no SIGHUP, and the tuple that named it raised before the
    `try` that was written to forgive it — so the whole class could not be
    built there, and the except clause naming AttributeError was dead code.
    Simulated rather than skipped, because CI's Windows legs are the only
    place this fires and they must not be the only place it is checked.
    """
    import atexit
    import signal

    monkeypatch.delattr(signal, "SIGHUP", raising=False)
    handlers = {name: signal.getsignal(getattr(signal, name))
                for name in ("SIGINT", "SIGTERM") if hasattr(signal, name)}
    keeper = pin_check.Restorer()          # must not raise
    atexit.unregister(keeper.restore)
    for name, handler in handlers.items():
        signal.signal(getattr(signal, name), handler)


def _fake_repo(tmp_path):
    root = tmp_path / "repo"
    (root / "pkg").mkdir(parents=True)
    target = root / "pkg" / "rule.py"
    original = "def rule():\n    return True\n"
    target.write_text(original, encoding="utf-8")
    catalogue = root / "catalogue.json"
    catalogue.write_text(json.dumps([{
        "label": "T1 the rule stops holding", "path": "pkg/rule.py",
        "old": "    return True\n", "new": "    return False\n"}]), encoding="utf-8")
    return root, target, original, catalogue


def test_the_in_tree_campaign_swaps_and_restores_the_file_it_mutates(tmp_path, monkeypatch):
    """The driver, not the helper. `write_atomic` is covered directly above,
    and both of its call sites live in a loop nothing exercised — running the
    real one means running the whole suite once per mutant, so the campaign
    itself was the untested part, and the whole-suite check said so by leaving
    both call sites alive.

    So the loop is run for real against a trivial "suite" and a one-entry
    catalogue in a temp root: the file must be swapped rather than rewritten in
    place, and put back byte for byte afterwards.
    """
    root, target, original, catalogue = _fake_repo(tmp_path)
    swapped = {}
    real_write = pin_check.write_atomic

    def spy(path, text):
        swapped.setdefault(str(path), []).append(pathlib.Path(path).stat().st_ino)
        return real_write(path, text)

    monkeypatch.setattr(pin_check, "ROOT", root)
    monkeypatch.setattr(pin_check, "CATALOGUE", catalogue)
    monkeypatch.setattr(pin_check, "SUITE", [sys.executable, "-c", "pass"])   # a green "suite"
    monkeypatch.setattr(pin_check, "write_atomic", spy)

    rc = pin_check.main(["--in-tree"])
    assert rc == 1, "a green suite means the mutant survived, which is a failing run"
    assert target.read_text(encoding="utf-8") == original, "the tree was left mutated"
    inodes = swapped.get(str(target), [])
    assert len(inodes) == 2, f"expected an atomic apply and an atomic restore, saw {inodes}"
    assert not list(root.rglob("*.pin_check.tmp")), "a temp file outlived the swap"


def test_the_default_campaign_never_touches_the_tree(tmp_path, monkeypatch):
    """Run 14's runner, adopted: the mutant lands in a scratch copy of the
    tree and the real file is not written at all — not swapped, not restored,
    not read while mutated. The copy is what gets measured, and it is gone
    afterwards."""
    root, target, original, catalogue = _fake_repo(tmp_path)
    inode = target.stat().st_ino
    written, copies = {}, []
    real_write, real_copy = pin_check.write_atomic, pin_check.scratch_copy

    def spy(path, text):
        written.setdefault(str(path), []).append(text)
        return real_write(path, text)

    def remember(r):
        copies.append(real_copy(r))
        return copies[-1]

    monkeypatch.setattr(pin_check, "ROOT", root)
    monkeypatch.setattr(pin_check, "CATALOGUE", catalogue)
    monkeypatch.setattr(pin_check, "SUITE", [sys.executable, "-c", "pass"])   # a green "suite"
    monkeypatch.setattr(pin_check, "write_atomic", spy)
    monkeypatch.setattr(pin_check, "scratch_copy", remember)
    # Inside the scratch the import must resolve to the scratch; the fake repo
    # has no package to import, so the check is stood in for by the answer it
    # would give on a good copy.
    monkeypatch.setattr(pin_check, "runs_its_own_code", lambda scratch, env: None)

    rc = pin_check.main([])
    assert rc == 1, "a green suite means the mutant survived, which is a failing run"
    assert str(target) not in written, "the real file was written"
    assert target.stat().st_ino == inode and target.read_text(encoding="utf-8") == original
    assert len(copies) == 1
    scratch_target = str(copies[0] / "pkg" / "rule.py")
    assert [t.count("False") for t in written.get(scratch_target, [])] == [1, 0], (
        "expected the mutant applied to the copy, then the copy put back")
    assert not (root / ".pin_check.lock").exists(), "the scratch mode needs no tree lock"


def test_a_scratch_that_runs_the_original_checkout_is_refused(tmp_path, monkeypatch, capsys):
    """The instrument control run 9 wrote a lesson about: a re-injection in a
    scratch copy that measured the original checkout, because the editable
    install outranked the copy. A copy that cannot prove it runs its own code
    produces no number at all — not a control, not a mutant.

    The suite here is GREEN on purpose: a red one would make `main` return 1
    for the wrong reason and the refusal could be deleted unnoticed (it was —
    the first version of this test let mutant G5 survive)."""
    root, target, original, catalogue = _fake_repo(tmp_path)
    monkeypatch.setattr(pin_check, "ROOT", root)
    monkeypatch.setattr(pin_check, "CATALOGUE", catalogue)
    monkeypatch.setattr(pin_check, "SUITE", [sys.executable, "-c", "pass"])   # green
    monkeypatch.setattr(pin_check, "IMPORT_CHECK",
                        [sys.executable, "-c", f"print({str(target)!r})"])   # resolves OUTSIDE
    rc = pin_check.main([])
    out, err = capsys.readouterr()
    assert rc == 1
    assert "ISOLATION FAILED" in err and str(target) in err, err
    assert "control:" not in out and "SURVIVED" not in out, (
        "the suite ran against a copy that had not proved itself")
    assert target.read_text(encoding="utf-8") == original


def test_runs_its_own_code_reads_the_resolved_path(tmp_path, monkeypatch):
    inside = tmp_path / "scratch" / "src" / "verdict_mcp" / "__init__.py"
    inside.parent.mkdir(parents=True)
    inside.write_text("", encoding="utf-8")
    scratch = tmp_path / "scratch"
    monkeypatch.setattr(pin_check, "IMPORT_CHECK", [sys.executable, "-c", f"print({str(inside)!r})"])
    assert pin_check.runs_its_own_code(scratch, dict(os.environ)) is None
    outside = tmp_path / "elsewhere" / "verdict_mcp" / "__init__.py"
    monkeypatch.setattr(pin_check, "IMPORT_CHECK", [sys.executable, "-c", f"print({str(outside)!r})"])
    assert pin_check.runs_its_own_code(scratch, dict(os.environ)) == str(outside)


def test_the_scratch_copy_is_the_working_tree_not_the_last_commit(tmp_path):
    """`git archive HEAD` would snapshot the commit; the mutants a maintainer
    runs before committing must see the edits in hand. Tracked, modified and
    new files come along; ignored ones stay behind."""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "tracked.py").write_text("v1\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t",
                    "commit", "-q", "-m", "one"], check=True)
    (repo / "tracked.py").write_text("v2 — edited, not committed\n", encoding="utf-8")
    (repo / "new.py").write_text("untracked but not ignored\n", encoding="utf-8")
    (repo / ".venv").mkdir()
    (repo / ".venv" / "big").write_text("ignored\n", encoding="utf-8")
    scratch = pin_check.scratch_copy(repo)
    try:
        assert (scratch / "tracked.py").read_text(encoding="utf-8").startswith("v2")
        assert (scratch / "new.py").is_file()
        assert not (scratch / ".venv").exists()
        # A repository of its own — code that lists files as git sees them runs in it (the
        # control went red on 2026-09-18 without one) — holding the tree in hand, not the
        # original's history.
        def git(*args):
            return subprocess.run(["git", "-C", str(scratch), *args], capture_output=True,
                                  text=True).stdout.split("\n")
        assert [x for x in git("log", "--format=%s") if x] == ["pin_check scratch"]
        assert sorted(x for x in git("ls-files") if x) == [".gitignore", "new.py", "tracked.py"]
    finally:
        import shutil
        shutil.rmtree(scratch, ignore_errors=True)
