"""What a test runner's output says: the summary line, the counts in each runner's
dialect, a command that never started, a suite that ran nothing, and a gate that got
dramatically slower than its own history.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import os
import re


# Exit codes that mean the command never ran: 126 "found, not executable" and 127 "not
# found" in every POSIX shell, 9009 "is not recognized" in cmd.exe. A gate that ends with
# one measured the environment, not the code (second-brain in a fresh worktree, 2026-10-15:
# `.venv/bin/python` and `vitest` missing, both read as red gates).
CANNOT_START_EXITS = (126, 127, 9009)


# cmd.exe /c exits 1, not 9009, when the command is not found, so on Windows its own message
# is the signal (CI's Windows runners, 2026-10-15).
_WINDOWS_NOT_FOUND = ("is not recognized as an internal or external command",
                      "The system cannot find the path specified")


def cannot_start(returncode, output: str) -> bool:
    """Did the command never run? Exit 126/127/9009, or cmd.exe's not-found message."""
    if returncode in CANNOT_START_EXITS:
        return True
    return os.name == "nt" and returncode == 1 and any(m in (output or "")
                                                       for m in _WINDOWS_NOT_FOUND)


# Runner dialects. Each carries a *signature* — a phrase only that runner
# prints — and is tried in order of how distinctive that signature is.
#
# The earlier design was a flat union of patterns that only spoke pytest, so
# for Go, Ruby, PHP, .NET and JVM projects the counts came back empty, and
# *silently*: the "a silent drop in test count is a finding" gate and the
# test-id set-diff simply never fired. A feature that is unavailable is a
# problem; one that is unavailable without saying so is a defect.
#
# Signatures rather than ordering alone, because these vocabularies overlap:
# `1 failure` appears in both gotestsum and rspec, `Failures: 1` in both
# surefire and phpunit, and `5 passed` in pytest, cargo, jest and vitest. Read
# by the wrong dialect the numbers are not wrong so much as incomplete — cargo
# read as pytest silently drops `ignored`, which is the skip count the gate
# cares about.
_DIALECTS = (
    # signature                          name            fields
    # Node's own runner (`node --test`), whose totals close both of its reporters: `# tests 6`
    # in TAP, `ℹ tests 6` in spec. First, because a test's own name can carry another
    # runner's words ("3 failed retries") and these totals are the one reading that is
    # Node's. A cancelled test did not finish: an error. Unread, every TypeScript project
    # tested this way measured no counts at all (45 gate runs, 2026-11-20).
    (r"(?m)^(?:# |ℹ )tests \d+\s*$", "node", {
        "collected": r"(?m)^(?:# |ℹ )tests (\d+)\s*$",
        "passed": r"(?m)^(?:# |ℹ )pass (\d+)\s*$",
        "failed": r"(?m)^(?:# |ℹ )fail (\d+)\s*$",
        "errors": r"(?m)^(?:# |ℹ )cancelled (\d+)\s*$",
        "skipped": r"(?m)^(?:# |ℹ )skipped (\d+)\s*$"}),
    # Python's `unittest`: `Ran 7 tests in 0.001s`, then `OK`, `OK (skipped=1)` or
    # `FAILED (failures=1, errors=1, skipped=1, expected failures=1, …)`. `expected
    # failures=` is not `failures=`.
    (r"(?m)^Ran \d+ tests? in ", "unittest", {
        "collected": r"(?m)^Ran (\d+) tests? in ",
        "failed": r"(?m)^FAILED \(.*?(?<!expected )\bfailures=(\d+)",
        "errors": r"(?m)^FAILED \(.*?\berrors=(\d+)",
        "skipped": r"(?m)^(?:OK|FAILED) \(.*?\bskipped=(\d+)",
        "xfailed": r"(?m)^(?:OK|FAILED) \(.*?\bexpected failures=(\d+)"}),
    (r"Tests run:\s*\d+", "surefire", {                 # JUnit / Maven surefire
        "collected": r"Tests run:\s*(\d+)", "failed": r"Failures:\s*(\d+)",
        "errors": r"Errors:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)"}),
    (r"\bDONE\s+\d+\s+tests?\b", "gotestsum", {        # DONE 12 tests, 1 failure in 0.5s
        "collected": r"DONE\s+(\d+)\s+tests?", "failed": r"(\d+)\s+failures?",
        "skipped": r"(\d+)\s+skipped"}),
    (r"Total:\s*\d+", "dotnet", {                       # Failed: 0, Passed: 5, Total: 5
        "collected": r"Total:\s*(\d+)", "passed": r"Passed:\s*(\d+)",
        "failed": r"Failed:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)"}),
    (r"Assertions:\s*\d+", "phpunit", {                 # Tests: 5, Assertions: 10, Failures: 1.
        "collected": r"Tests:\s*(\d+)", "failed": r"Failures:\s*(\d+)",
        "errors": r"Errors:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)",
        "incomplete": r"Incomplete:\s*(\d+)"}),
    (r"OK \(\d+ tests?", "phpunit", {                    # OK (5 tests, 5 assertions)
        "passed": r"OK \((\d+) tests?", "failed": r"^(?!)"}),
    (r"\d+ examples?\b", "rspec", {                     # 5 examples, 1 failure, 2 pending
        "collected": r"(\d+) examples?", "failed": r"(\d+) failures?",
        "skipped": r"(\d+) pending"}),
    (r"test result:", "cargo", {                        # test result: ok. 5 passed; 1 ignored
        "passed": r"(\d+) passed", "failed": r"(\d+) failed",
        "skipped": r"(\d+) ignored"}),
    # vitest and jest print the FILE tally on the line above the test tally, in
    # the same vocabulary: ` Test Files  1 passed (1)` then ` Tests  28 passed
    # (28)`. Unanchored, every field matched the file line first and a 28-test
    # suite measured `collected: 1` — the first thing the published wheel did
    # on a stranger's TypeScript repository (unjs/ofetch), and it would have
    # been written to state as a measurement. Every field is anchored to the
    # `Tests` line, and the signature no longer needs a `passed` on it: a suite
    # with nothing passing is still a vitest suite.
    (r"(?m)^\s*Tests\s+.*\(\d+\)\s*$", "vitest", {         # Tests  2 failed | 5 passed (7)
        "collected": r"(?m)^\s*Tests\s+.*\((\d+)\)",
        "passed": r"(?m)^\s*Tests\s+.*?(\d+) passed",
        "failed": r"(?m)^\s*Tests\s+.*?(\d+) failed",
        "skipped": r"(?m)^\s*Tests\s+.*?(\d+) skipped"}),
    (r"(?m)^Tests:\s.*\b\d+ total\b", "jest", {           # Tests: 1 failed, 4 passed, 5 total
        "collected": r"(?m)^Tests:.*?(\d+) total",
        "passed": r"(?m)^Tests:.*?(\d+) passed",
        "failed": r"(?m)^Tests:.*?(\d+) failed",
        "skipped": r"(?m)^Tests:.*?(\d+) (?:skipped|todo)"}),
    (r"\d+ (?:passed|failed|skipped|xfailed|error)", "pytest", {
        "passed": r"(\d+) passed", "failed": r"(\d+) failed",
        "skipped": r"(\d+) skipped", "errors": r"(\d+) errors?\b",
        "xfailed": r"(\d+) xfailed"}),
)


_DIALECTS = tuple((re.compile(sig), name,
                   {f: re.compile(pat) for f, pat in fields.items()})
                  for sig, name, fields in _DIALECTS)


# `go test` proper prints no totals at all — only per-test lines under -v. It
# gets counted by tallying those, which is the only signal it offers.
#
# Colour first. A runner that believes it has a terminal wraps every number in
# escape codes, and vitest puts one between `passed` and ` (28)`: the vitest
# signature then fails, the pytest dialect catches `1 passed` off the file
# line, and the wrong runner reports the wrong count with nothing to say it
# happened. The codes carry no information the counts need.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


_GO_VERBOSE = (re.compile(r"^--- PASS: ", re.M), re.compile(r"^--- FAIL: ", re.M),
               re.compile(r"^--- SKIP: ", re.M))


_COUNT_PATTERNS = tuple(
    (sig, name) for sig, name, _ in _DIALECTS) + tuple(
    (p, "go") for p in _GO_VERBOSE)


def _summary_line(output: str) -> str:
    """The last line carrying countable results — the line a human reads."""
    for line in reversed([x.strip() for x in output.splitlines() if x.strip()]):
        if any(p.search(line) for p, _ in _COUNT_PATTERNS):
            return line[:300]
    tail = [x.strip() for x in output.splitlines() if x.strip()]
    return tail[-1][:300] if tail else ""


# A duration jump reads as regression only past both bars: relative (the gate
# got at least this many times slower than its own median) and absolute (and
# slower by at least this many seconds). Either alone cries wolf — a 0.07s gate
# tripling is noise, and a fixed floor alone misses nothing-to-60s jumps on
# fast suites. Two prior samples minimum: one run is not a baseline.
_DURATION_FACTOR = 3.0


_DURATION_ABS_FLOOR_S = 5.0


_DURATION_MIN_PRIOR = 2


def duration_regressed(current_s, prior_durations) -> str | None:
    """Did this gate get dramatically slower than its own history?

    Arithmetic, not judgment — the same contract as `executed_nothing`. The
    motivating case is external and specific: three tests started calling a
    live CLI, the suite went from 3s to 65s, and the run burned a week of
    subscription quota without anyone noticing — while the number sat in
    facts.json the whole time, measured and uncompared. The harness now does
    the comparison, so the judgment step receives "this gate is 21x slower
    than its own median" as an established fact. A lead for §4.5 judgment
    (live-service calls, an accidental sleep, a hung retry), never a finding
    by itself.
    """
    if not isinstance(current_s, (int, float)):
        return None
    priors = sorted(d for d in (prior_durations or [])
                    if isinstance(d, (int, float)) and d >= 0)
    if len(priors) < _DURATION_MIN_PRIOR:
        return None
    median = priors[len(priors) // 2]
    if median <= 0:
        return None
    if current_s >= median * _DURATION_FACTOR and             current_s - median >= _DURATION_ABS_FLOOR_S:
        return (f"took {current_s:.1f}s against a median of {median:.1f}s over the "
                f"last {len(priors)} runs ({current_s / median:.0f}x) — a test may "
                "have started calling a live service, sleeping, or hanging on a retry")
    return None


def executed_nothing(counts: dict) -> str | None:
    """Did this suite collect tests and then run none of them?

    Arithmetic, not judgment — which is the point. A conftest that skips every
    collected test leaves a green exit code over zero executed assertions, and
    it is the most consequential trap there is: every other signal in the run
    becomes theatre. Left for the model to notice, the adversarial fixture
    caught it 1 run in 3. Counted here, the judgment step receives it already
    established, like every other number the harness measures.
    """
    if not counts:
        return None
    executed = sum(counts.get(k, 0) for k in ("passed", "failed", "errors"))
    skipped = counts.get("skipped", 0)
    if executed == 0 and skipped > 0:
        return (f"all {skipped} collected tests were skipped: the suite executed "
                "nothing, so its exit code carries no signal about the code")
    return None


# Runners that print a total and what did not pass, but never a pass count. The passes are
# what the total leaves. Without them a suite of twelve with two pending read as "all 2
# collected tests were skipped", and a passing test re-run to verify a fix read as an error.
# A runner that prints passes is never given derived ones: vitest's `5 failed (5)` has none.
_TOTAL_ONLY = ("surefire", "gotestsum", "phpunit", "rspec", "unittest")


def _with_passes(counts: dict, name: str) -> dict:
    """`counts` with `passed` derived from the total, for a runner that prints none."""
    if name in _TOTAL_ONLY and "passed" not in counts and "collected" in counts:
        rest = sum(counts.get(k, 0) for k in ("failed", "errors", "skipped", "xfailed",
                                              "incomplete"))
        counts["passed"] = max(0, counts["collected"] - rest)
    return counts


def _counts(output: str) -> tuple[dict, str | None]:
    """Parse a runner's summary into counts, and say which dialect was read.

    Naming the dialect is not decoration: a reader who sees empty counts needs
    to know whether the suite reported nothing or whether we failed to
    understand it, and those are different problems with different fixes.
    """
    output = _ANSI.sub("", output)
    for signature, name, fields in _DIALECTS:
        if not signature.search(output):
            continue
        counts = {}
        for field, pattern in fields.items():
            m = pattern.search(output)
            if m:
                counts[field] = int(m.group(1))
        if counts:
            return _with_passes(counts, name), name
    passed, failed, skipped = (len(p.findall(output)) for p in _GO_VERBOSE)
    if passed or failed or skipped:
        return {"passed": passed, "failed": failed, "skipped": skipped}, "go test -v"
    return {}, None
