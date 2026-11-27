"""Test runners whose summary the harness could not read, and runners that print a total
but no pass count.

Measured 2026-11-20 over the gate records kept on one machine: every gate that ran Node's
own test runner (`node --test`, three TypeScript projects, 45 runs) or Python's `unittest`
(16 runs) recorded `counts_unparsed`. The local tier then had no measured test count and
said `blocked` on every one of those projects, the count-drop gate and the id set-diff
could not fire, and a model was asked for a run the suite had already answered.

The summaries below are the runners' own output, captured from real runs (Node 25.7,
Python 3.14), not written by hand.
"""

import subprocess

import pytest

from verdict_mcp.facts_suite import _counts, executed_nothing
from verdict_mcp.facts_verify import _classify

NODE_TAP_RED = """\
1..2
# tests 6
# suites 1
# pass 3
# fail 1
# cancelled 0
# skipped 1
# todo 1
# duration_ms 127.027708
"""

NODE_TAP_GREEN = """\
ok 1 - one
  ---
  duration_ms: 0.401208
  type: 'test'
  ...
ok 2 - two
  ---
  duration_ms: 0.048292
  type: 'test'
  ...
ok 3 - later # SKIP
  ---
  duration_ms: 0.033375
  type: 'test'
  ...
1..3
# tests 3
# suites 0
# pass 2
# fail 0
# cancelled 0
# skipped 1
# todo 0
# duration_ms 99.876334
"""

# The spec reporter, Node's default on a terminal and on newer releases everywhere. With a
# failure it prints the totals first and the failing tests after them.
NODE_SPEC_RED = """\
▶ add
  ✔ adds (0.401208ms)
  ✔ adds negatives (0.048292ms)
  ✖ is wrong on purpose (0.532375ms)
  ﹣ skipped one (0.033375ms) # not yet
  ﹣ todo one (0.028ms) # TODO
✖ add (1.67625ms)
✔ all good (0.566833ms)
ℹ tests 6
ℹ suites 1
ℹ pass 3
ℹ fail 1
ℹ cancelled 0
ℹ skipped 1
ℹ todo 1
ℹ duration_ms 123.799041

✖ failing tests:

test at a.test.ts:7:3
✖ is wrong on purpose (0.532375ms)
  AssertionError [ERR_ASSERTION]: Expected values to be strictly equal:

  2 !== 3
"""

UNITTEST_RED = """\
FAIL: test_fail (test_x.T.test_fail)
----------------------------------------------------------------------
AssertionError: 2 != 3

----------------------------------------------------------------------
Ran 7 tests in 0.001s

FAILED (failures=1, errors=1, skipped=1, expected failures=1, unexpected successes=1)
"""


@pytest.mark.parametrize("output,expected", [
    (NODE_TAP_RED, {"collected": 6, "passed": 3, "failed": 1, "errors": 0, "skipped": 1}),
    (NODE_TAP_GREEN, {"collected": 3, "passed": 2, "failed": 0, "errors": 0, "skipped": 1}),
    (NODE_SPEC_RED, {"collected": 6, "passed": 3, "failed": 1, "errors": 0, "skipped": 1}),
    # A test the runner cancelled (a timeout, a parent that failed) did not finish: an error.
    ("# tests 4\n# suites 0\n# pass 2\n# fail 0\n# cancelled 2\n# skipped 0\n# todo 0\n",
     {"collected": 4, "passed": 2, "failed": 0, "errors": 2, "skipped": 0}),
], ids=["tap-red", "tap-green", "spec-red", "tap-cancelled"])
def test_node_test_runner_is_read_in_both_reporters(output, expected):
    counts, name = _counts(output)
    assert (counts, name) == (expected, "node")


def test_a_node_test_named_like_another_runners_summary_does_not_steal_the_reading():
    """A test called "3 failed retries" carries pytest's vocabulary on its own line. The
    totals at the bottom are the reading, under Node's name."""
    output = "ok 1 - returns 3 failed retries\n" + NODE_TAP_GREEN
    counts, name = _counts(output)
    assert name == "node" and counts["collected"] == 3, (name, counts)


@pytest.mark.parametrize("output,expected", [
    (UNITTEST_RED,
     {"collected": 7, "failed": 1, "errors": 1, "skipped": 1, "xfailed": 1, "passed": 3}),
    ("Ran 3 tests in 0.000s\n\nOK (skipped=1)\n", {"collected": 3, "skipped": 1, "passed": 2}),
    ("Ran 1 test in 0.000s\n\nOK\n", {"collected": 1, "passed": 1}),
    # `expected failures=` is not `failures=`: read wrongly, a run with no failure at all
    # would have recorded two.
    ("Ran 4 tests in 0.010s\n\nFAILED (errors=1, expected failures=2)\n",
     {"collected": 4, "errors": 1, "xfailed": 2, "passed": 1}),
    ("Ran 0 tests in 0.000s\n\nNO TESTS RAN\n", {"collected": 0, "passed": 0}),
], ids=["red", "green-with-skip", "one-test", "expected-failures", "none-ran"])
def test_unittest_is_read(output, expected):
    counts, name = _counts(output)
    assert (counts, name) == (expected, "unittest")


@pytest.mark.parametrize("output,dialect,passed", [
    ("5 examples, 0 failures, 2 pending", "rspec", 3),
    ("Tests run: 50, Failures: 1, Errors: 2, Skipped: 3", "surefire", 44),
    ("DONE 12 tests, 1 skipped, 1 failure in 0.5s", "gotestsum", 10),
    ("Tests: 9, Assertions: 20, Failures: 1, Skipped: 2, Incomplete: 1.", "phpunit", 5),
])
def test_a_runner_that_prints_only_a_total_gets_its_passes_from_it(output, dialect, passed):
    """These runners print how many tests there were and how many did not pass. What the
    total leaves is the passes; without them a passing test re-run to verify a fix read as
    an error, and a suite with one pending test read as a suite that ran nothing."""
    counts, name = _counts(output)
    assert name == dialect and counts["passed"] == passed, (name, counts)


def test_a_runner_that_prints_its_passes_is_never_given_derived_ones():
    """vitest's `Tests  5 failed (5)` prints no pass count because there were none to print;
    the derivation is for runners that never print one."""
    counts, name = _counts(" Test Files  1 failed (1)\n      Tests  5 failed (5)\n")
    assert name == "vitest" and "passed" not in counts


@pytest.mark.parametrize("output", [
    "5 examples, 0 failures, 2 pending",
    "Tests run: 12, Failures: 0, Errors: 0, Skipped: 2",
    "DONE 12 tests, 2 skipped in 0.5s",
    "Ran 3 tests in 0.000s\n\nOK (skipped=1)\n",
    NODE_TAP_GREEN,
])
def test_a_suite_that_ran_with_a_few_skips_is_not_called_empty(output):
    """The false alarm this removes: "all 2 collected tests were skipped" over a suite of
    twelve that ran ten."""
    counts, _ = _counts(output)
    assert executed_nothing(counts) is None, counts


@pytest.mark.parametrize("output", [
    "3 examples, 0 failures, 3 pending",
    "Ran 3 tests in 0.000s\n\nOK (skipped=3)\n",
    "# tests 2\n# suites 0\n# pass 0\n# fail 0\n# cancelled 0\n# skipped 2\n# todo 0\n",
])
def test_a_suite_that_skipped_everything_is_still_called_empty(output):
    counts, _ = _counts(output)
    assert "executed nothing" in (executed_nothing(counts) or ""), counts


def _done(code: int) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["x"], returncode=code, stdout="", stderr="")


@pytest.mark.parametrize("output,code,expected", [
    ("Ran 1 test in 0.000s\n\nOK\n", 0, "pass"),
    ("Ran 1 test in 0.001s\n\nFAILED (failures=1)\n", 1, "fail"),
    ("Ran 1 test in 0.001s\n\nFAILED (errors=1)\n", 1, "error"),
    ("1 example, 0 failures", 0, "pass"),
    ("# tests 1\n# suites 0\n# pass 1\n# fail 0\n# cancelled 0\n# skipped 0\n# todo 0\n", 0,
     "pass"),
    ("# tests 1\n# suites 0\n# pass 0\n# fail 1\n# cancelled 0\n# skipped 0\n# todo 0\n", 1,
     "fail"),
], ids=["unittest-pass", "unittest-fail", "unittest-error", "rspec-pass", "node-pass", "node-fail"])
def test_one_test_re_run_to_verify_a_fix_reads_as_what_it_did(output, code, expected):
    """A fix is verified by running the cited test at the old commit and at HEAD. A pass
    read as `error` there verifies nothing, whatever the code did."""
    assert _classify(_done(code), output) == expected
