"""`eval/pin_check.py` scores a mutant from pytest's summary line, never from
the exit code alone.

pytest exits non-zero for a usage error, an internal error, a failed collection
and "no tests ran" exactly as it does for a failing test. Read as `rc != 0`, a
mutant that leaves a module unimportable is scored as a defended rule when in
truth nothing ran (VERDICT-F-68) — the reading run 11 had already recorded a
lesson about, one release earlier.
"""

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
