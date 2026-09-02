#!/usr/bin/env python3
"""verdict-facts / verdict-finalize — the deterministic half of a QA run.

Stdlib only, runnable as bare scripts from a checkout.

Roughly two thirds of a state file is arithmetic and transcription: the
timestamp, the SHAs, the diff range, gate exit codes and durations, test
counts, finding hashes, ages, and deltas. None of it is judgment, all of it is
a place to be confidently wrong, and a prompt rule cannot stop a model from
inventing a value it is capable of inventing — two of four production
timestamps sat on exactly `:00` seconds months after `date -u` became a rule.

So the work moves:

    verdict-facts     measures. Runs the gates the caller names, times them,
                      parses their counts, reads git, derives the project key,
                      computes run_number and run_type. Writes facts.json.
                      Touches nothing else; read-only on the repository.

    <the agent>       judges. Writes judgment.json: verdict, findings (title,
                      severity, priority, classification, evidence, status),
                      not_tested, next_run_focus, isolation_check, quarantine.
                      Nothing it writes there is a number it had to compute.

    verdict-finalize  merges. Hashes each finding, matches it against the
                      previous state to assign first_seen, age_days, and the
                      NEW / STILL_OPEN / RESOLVED / REGRESSED delta, writes
                      state.json.prev, validates, and only then writes
                      state.json and the INDEX row.

`finalize` validates before it writes, because the PostToolUse validator hook
matches Write/Edit and would never see a file written by a shell command.
"""

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

try:
    from .census import code_census
    from .profile import ProfileError, gates_from
    from .profile import load as load_profile
    from .project_key import derive_key
    from .state import (OUTCOMES_FILE, calibration, is_open, load_outcomes,
                        merge_outcomes, norm_status, order_findings,
                        project_key_for_root)
    from .state import (RUNS_FILE, chain_link, history_row, load_runs,
                        next_revision)
    from .state import home as state_home
    from .validate import validate, validate_judgment
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from census import code_census
    from profile import ProfileError, gates_from
    from profile import load as load_profile
    from project_key import derive_key
    from state import (OUTCOMES_FILE, calibration, is_open, load_outcomes,
                       merge_outcomes, norm_status, order_findings,
                       project_key_for_root)
    from state import (RUNS_FILE, chain_link, history_row, load_runs,
                       next_revision)
    from state import home as state_home
    from validate import validate, validate_judgment

RE_BASELINE_AFTER_DAYS = 7
# A run marker at the same commit, this recent, is a retry rather than a night
# that was lost. Generous: a mistyped gate command and a re-run can straddle a
# long investigation.
RETRY_WINDOW_HOURS = 6
RE_BASELINE_FILES = 100
RE_BASELINE_LINES = 10_000
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
        "errors": r"Errors:\s*(\d+)", "skipped": r"Skipped:\s*(\d+)"}),
    (r"OK \(\d+ tests?", "phpunit", {                    # OK (5 tests, 5 assertions)
        "passed": r"OK \((\d+) tests?", "failed": r"^(?!)"}),
    (r"\d+ examples?\b", "rspec", {                     # 5 examples, 1 failure, 2 pending
        "collected": r"(\d+) examples?", "failed": r"(\d+) failures?",
        "skipped": r"(\d+) pending"}),
    (r"test result:", "cargo", {                        # test result: ok. 5 passed; 1 ignored
        "passed": r"(\d+) passed", "failed": r"(\d+) failed",
        "skipped": r"(\d+) ignored"}),
    (r"passed \(\d+\)", "vitest", {                       # Tests  2 failed | 5 passed (7)
        "collected": r"passed \((\d+)\)", "passed": r"(\d+) passed",
        "failed": r"(\d+) failed", "skipped": r"(\d+) skipped"}),
    (r"\d+ (?:total|todo)\b", "jest", {                   # Tests: 1 failed, 4 passed, 5 total
        "collected": r"(\d+) total", "passed": r"(\d+) passed",
        "failed": r"(\d+) failed", "skipped": r"(\d+) (?:skipped|todo)"}),
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
_GO_VERBOSE = (re.compile(r"^--- PASS: ", re.M), re.compile(r"^--- FAIL: ", re.M),
               re.compile(r"^--- SKIP: ", re.M))
_COUNT_PATTERNS = tuple(
    (sig, name) for sig, name, _ in _DIALECTS) + tuple(
    (p, "go") for p in _GO_VERBOSE)


def _run(cmd, cwd=None, shell=False):
    return subprocess.run(cmd, cwd=cwd, shell=shell, capture_output=True, text=True)


def _git(args, repo):
    proc = _run(["git", "-C", str(repo), *args])
    return proc.stdout.strip() if proc.returncode == 0 else None


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


def _counts(output: str) -> tuple[dict, str | None]:
    """Parse a runner's summary into counts, and say which dialect was read.

    Naming the dialect is not decoration: a reader who sees empty counts needs
    to know whether the suite reported nothing or whether we failed to
    understand it, and those are different problems with different fixes.
    """
    for signature, name, fields in _DIALECTS:
        if not signature.search(output):
            continue
        counts = {}
        for field, pattern in fields.items():
            m = pattern.search(output)
            if m:
                counts[field] = int(m.group(1))
        if counts:
            return counts, name
    passed, failed, skipped = (len(p.findall(output)) for p in _GO_VERBOSE)
    if passed or failed or skipped:
        return {"passed": passed, "failed": failed, "skipped": skipped}, "go test -v"
    return {}, None


_UNSET = object()


def _parse_marker_time(value):
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


# ── fix verification ───────────────────────────────────────────────────────
#
# `fix_verified` is the one judgment field that feeds the track record, and it
# was almost never set: re-injecting a defect by hand is the step every run
# skipped, so resolutions stayed `unknown` and the calibration ledger starved —
# 95 of 110 Sales findings undecided, no precision rate publishable. The
# harness does the re-injection now, the way the contract asks the tester to:
# run the test that demonstrates the defect at the commit before the fix and at
# HEAD. Measured, bounded, and honest about what it could not tell.

_TEST_ID = re.compile(r"([\w./\\-]+\.py::[\w.:]+(?:\[[^\]\n]*\])?)")
VERIFY_MAX_FINDINGS = 25
VERIFY_TIMEOUT_S = 120


def resolve_test_id(candidate: str, known) -> str | None:
    """The collected test id a citation names, or None.

    Evidence is prose, not an index. `_TEST_ID` matches a node id anywhere in
    it — including inside a quoted source snippet — and running a scraped id
    measures nothing: it errors at both commits, and an error is not a
    verification. Live on run 5 of this repository, VERDICT-F-20's record read
    `t.py::new`, a test that exists in no file here (VERDICT-F-26). So a
    citation is checked against the ids the collector actually reported, and
    only a resolved one is ever run.

    Without a ledger (`test_ids_cmd` unset, or collection failed) there is
    nothing to check against and every citation is tried, as before.
    """
    if not known:
        return candidate
    cand = candidate.replace("\\", "/").strip()
    if cand in known:
        return cand
    tail = [k for k in known if k.endswith("/" + cand)]
    if len(tail) == 1:
        return tail[0]
    base = cand.split("[", 1)[0]
    if any(k.split("[", 1)[0] == base for k in known):
        return base  # pytest expands a base id to its parametrizations
    fam = {k.split("[", 1)[0] for k in known if k.split("[", 1)[0].endswith("/" + base)}
    return fam.pop() if len(fam) == 1 else None


def cited_tests(finding: dict, known=None, preferred=None) -> list[str]:
    """The tests a finding names — an explicit `verification_test`, or pytest
    node ids inside its evidence. `test_x.py:12` is a line reference, not a
    test, and does not count. With `known`, only ids the collector reported
    survive, resolved to their collected form.

    Order is the choice. Evidence order is not relevance, and taking the first
    match meant the harness ran a non-guarding test for every finding it
    verified on run 7 (VERDICT-F-26). An explicit `verification_test` is the
    tester's own citation and leads. Then anything in `preferred` — the ids the
    collector saw for the first time this run, which is what a fix's own
    regression test looks like. Whatever is left is prose, kept last and
    labelled as such by `select_test`.
    """
    explicit = finding.get("verification_test")
    named = [explicit] if isinstance(explicit, str) else [str(x) for x in (explicit or []) if x]
    scraped = []
    for line in finding.get("evidence") or []:
        scraped += _TEST_ID.findall(str(line))
    seen, first, rest = set(), [], []
    for i, raw in [("explicit", x) for x in named] + [("prose", x) for x in scraped]:
        candidate = str(raw).strip().rstrip(".,;:")
        if not candidate:
            continue
        resolved = resolve_test_id(candidate, known)
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        (first if i == "explicit" else rest).append(resolved)
    if preferred:
        pref = {str(x).replace("\\", "/") for x in preferred}
        rest = [x for x in rest if x in pref] + [x for x in rest if x not in pref]
    return first + rest


def select_test(finding: dict, tests: list, preferred=None) -> tuple:
    """(test id, how it was chosen). `explicit` and `added_this_run` are
    reasons to believe this test guards this finding; `first_cited` is only a
    reason to believe the tester mentioned it, and the caller weighs it as
    such."""
    if not tests:
        return None, None
    explicit = finding.get("verification_test")
    named = {explicit} if isinstance(explicit, str) else {str(x) for x in (explicit or []) if x}
    pref = {str(x).replace("\\", "/") for x in (preferred or ())}
    chosen = tests[0]
    if any(resolve_test_id(str(n), {chosen}) == chosen for n in named) or chosen in named:
        return chosen, "explicit"
    if chosen in pref:
        return chosen, "added_this_run"
    return chosen, "first_cited"


def _conftest_chain(repo: Path, test_file: str) -> list[str]:
    """Every `conftest.py` from the repository root down to the test's own
    directory. pytest's helper mechanism, and the commonest thing a regression
    test lands beside: the test travels back to the old commit, and without
    its fixtures it errors there and verifies nothing (VERDICT-F-33)."""
    parts = Path(test_file).parent.parts
    out = []
    for i in range(len(parts) + 1):
        rel = (Path(*parts[:i]) / "conftest.py") if i else Path("conftest.py")
        if (Path(repo) / rel).is_file():
            out.append(rel.as_posix())
    return out


def _one_test_cmd(template: str, test_id: str, repo: Path) -> str:
    """Fill `{id}` in, quoted for the shell, and pin a relative interpreter to
    the repository it was written for: `.venv/bin/python` means nothing inside
    a scratch checkout, and the point of the scratch checkout is the source."""
    quoted = ('"' + test_id.replace('"', '') + '"') if os.name == "nt" else shlex.quote(test_id)
    cmd = template.replace("{id}", quoted)
    head, sep, rest = cmd.partition(" ")
    first = head.strip("\"'")
    if first and not os.path.isabs(first) and ("/" in first or "\\" in first) \
            and (Path(repo) / first).exists():
        cmd = str((Path(repo) / first).resolve()) + sep + rest
    return cmd


def _classify(proc, output: str) -> str:
    """pass / fail / error, read from the runner's parsed summary, never from
    the exit code alone. A setup error exits 1 exactly like a failing assertion
    does, and reading it as `fail` at the old commit would mint a verification
    the code never earned. `fail` is only ever a parsed failure count with no
    errors beside it; an unparsed non-zero exit is `error`."""
    counts, _ = _counts(output)
    if counts:
        if counts.get("errors"):
            return "error"
        if counts.get("failed"):
            return "fail"
        if counts.get("passed"):
            return "pass"
        return "error"  # collected but ran nothing — skipped is not a pass
    if proc is not None and proc.returncode == 0:
        return "pass"
    return "error"


def _run_test(template: str, test_id: str, cwd, repo: Path, timeout: float,
              pythonpath: list | None = None) -> dict:
    cmd = _one_test_cmd(template, test_id, repo)
    env = dict(os.environ)
    if pythonpath:
        env["PYTHONPATH"] = os.pathsep.join([*pythonpath, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    try:
        proc = subprocess.run(cmd, cwd=str(cwd), shell=True, capture_output=True, text=True,
                              timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return {"result": "error", "summary": f"timed out after {timeout:.0f}s"}
    except OSError as exc:
        return {"result": "error", "summary": str(exc)}
    output = proc.stdout + proc.stderr
    return {"result": _classify(proc, output), "summary": _summary_line(output),
            "exit_code": proc.returncode}


def _scratch_checkout(repo: Path, sha: str):
    """A detached worktree of `sha`, or None when the commit is not here. The
    checkout tree itself is never touched; the worktree lives in a temp dir and
    is removed when verification ends."""
    tmp = Path(tempfile.mkdtemp(prefix="verdict-verify-"))
    proc = _run(["git", "-C", str(repo), "worktree", "add", "--detach", "-q", str(tmp), sha])
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        return None
    return tmp


def _remove_scratch(repo: Path, tmp: Path) -> None:
    _run(["git", "-C", str(repo), "worktree", "remove", "--force", str(tmp)])
    shutil.rmtree(tmp, ignore_errors=True)


def verify_findings(repo: Path, previous: dict | None, test_one_cmd: str | None,
                    previous_sha: str | None, known_ids=None,
                    added_ids=None) -> tuple[dict, list[str]]:
    """Re-run each open finding's cited test at HEAD and at the previous
    commit → ({finding id: record}, notes).

    A record's `at_previous`/`at_head` are `pass`, `fail`, `error` or
    `unavailable`. `merge` turns fail→pass into `fix_verified`, refuses a
    resolution whose test still fails at HEAD, and leaves everything else
    alone: pass at both commits means the test did not demonstrate the defect
    — or the old source was not what ran — and the harness cannot tell which.
    """
    notes: list[str] = []
    open_prior = [f for f in ((previous or {}).get("findings") or [])
                  if isinstance(f, dict) and is_open(f)]
    if not open_prior:
        return {}, notes
    if not test_one_cmd:
        notes.append("fix verification off: set `test_one_cmd` in the profile (with `{id}` "
                     "where the test id goes) to re-run each resolved finding's cited test "
                     "at the previous commit and at HEAD")
        return {}, notes
    known = {str(k).replace("\\", "/") for k in known_ids} if known_ids else None
    preferred = {str(k).replace("\\", "/") for k in (added_ids or ())}
    cited, unresolved, uncited = [], [], 0
    for f in open_prior:
        resolved = cited_tests(f, known, preferred)
        if resolved:
            cited.append((f, resolved))
        elif cited_tests(f):
            unresolved.append((str(f.get("id") or "?"), cited_tests(f)[0]))
        else:
            uncited += 1
    if uncited:
        notes.append(f"{uncited} open finding(s) cite no test id, so the harness cannot "
                     "fix-verify them")
    if unresolved:
        shown = ", ".join(f"{fid} ({tid})" for fid, tid in unresolved[:5])
        more = f" and {len(unresolved) - 5} more" if len(unresolved) > 5 else ""
        notes.append("cited test is not in the collected id ledger, so nothing was run for "
                     f"{shown}{more} — a node id in prose is text, not a citation")
    if len(cited) > VERIFY_MAX_FINDINGS:
        notes.append(f"fix verification capped at {VERIFY_MAX_FINDINGS} of {len(cited)} "
                     "findings with a cited test")
        cited = cited[:VERIFY_MAX_FINDINGS]
    if not cited:
        return {}, notes

    scratch = None
    if previous_sha:
        scratch = _scratch_checkout(repo, str(previous_sha))
        if scratch is None:
            notes.append(f"previous commit {str(previous_sha)[:7]} is not in this repository "
                         "— verification ran at HEAD only")
    else:
        notes.append("no previous commit recorded — verification ran at HEAD only")

    results: dict = {}
    try:
        for finding, tests in cited:
            test_id, how = select_test(finding, tests, preferred)
            rec = {"test": test_id, "selected_by": how, "candidates": len(tests),
                   "previous_sha": previous_sha,
                   "at_previous": "unavailable", "at_head": None}
            head = _run_test(test_one_cmd, test_id, repo, repo, VERIFY_TIMEOUT_S)
            rec["at_head"] = head["result"]
            parts = [head.get("summary", "")]
            if scratch is not None:
                # The counterfactual is the NEW test against the OLD source, so
                # the test file always comes from HEAD. Copying only when the
                # file was absent read presence of the file as presence of the
                # test: a regression test appended to an existing test file left
                # the old file in place, which does not contain that test at all,
                # so at_previous read `error` and nothing could ever verify
                # (VERDICT-F-25).
                test_file = test_id.split("::", 1)[0]
                src, dst = Path(repo) / test_file, scratch / test_file
                if src.is_file():
                    differs = (not dst.exists()) or dst.read_bytes() != src.read_bytes()
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
                    if differs:
                        rec["test_copied_from_head"] = True
                # A test is not only its file. A regression test that lands with
                # the fixture it needs left that fixture at HEAD, so the old
                # commit met a test whose conftest it had never seen and
                # errored — which is not a measurement (VERDICT-F-33).
                for conf in _conftest_chain(repo, test_file):
                    csrc, cdst = Path(repo) / conf, scratch / conf
                    if not cdst.exists() or cdst.read_bytes() != csrc.read_bytes():
                        cdst.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(csrc, cdst)
                        rec.setdefault("support_copied_from_head", []).append(conf)
                # The old source must be what runs. An editable install points at
                # the main checkout regardless of cwd; PYTHONPATH outranks it.
                pp = [str(p) for p in (scratch / "src", scratch) if p.is_dir()]
                prev = _run_test(test_one_cmd, test_id, scratch, repo, VERIFY_TIMEOUT_S,
                                 pythonpath=pp)
                rec["at_previous"] = prev["result"]
                rec["pythonpath"] = pp
                parts.insert(0, prev.get("summary", ""))
            rec["summary"] = " → ".join(p for p in parts if p)
            results[str(finding.get("id"))] = rec
    finally:
        if scratch is not None:
            _remove_scratch(repo, scratch)
    return results, notes


def _apply_verification(entry: dict, prior: dict | None, verification: dict) -> None:
    """Stamp the measurement on a finding, and refuse a resolution it contradicts.

    Runs before the outcome is derived, so a verified fix reaches the ledger as
    `confirmed` and a refused one stays undecided. A cited test that still
    fails at HEAD overrides both an explicit `resolved` and silence: neither a
    claim nor an absence can close a finding whose demonstrating test fails on
    the code being judged.
    """
    key = str(entry.get("id") or (prior or {}).get("id") or "")
    rec = verification.get(key) if verification else None
    if not rec:
        return
    entry["verification"] = rec
    resolving = entry.get("delta") == "RESOLVED"
    # Refusing a resolution is the strongest thing a measurement does here, and
    # it may only rest on a test somebody chose. `first_cited` among several
    # candidates is prose order, not a citation: on run 7 the harness picked a
    # non-guarding test for every finding it verified (VERDICT-F-26). The
    # measurement is still recorded; it just does not overrule the tester.
    arbitrary = rec.get("selected_by") == "first_cited" and (rec.get("candidates") or 1) > 1
    if rec.get("at_head") == "fail" and arbitrary:
        rec["not_weighed"] = ("chosen by prose order from "
                              f"{rec['candidates']} cited tests — too weak to refuse a "
                              "resolution; cite `verification_test` to make it count")
        return
    if rec.get("at_head") == "fail":
        if resolving:
            entry["status"] = "open"
            entry["delta"] = "STILL_OPEN"
            entry.pop("fix_verified", None)
            entry["resolution_refused"] = (
                f"{rec['test']} still fails at HEAD — measured by verdict-facts, so the "
                "resolution is not accepted")
            if "carried_forward" in entry:
                entry["carried_forward"] = ("not reported this run, but its cited test still "
                                            "fails at HEAD — held open by measurement")
        return
    if resolving and rec.get("at_previous") == "fail" and rec.get("at_head") == "pass":
        entry["fix_verified"] = True
        sha7 = str(rec.get("previous_sha") or "")[:7]
        entry["evidence"] = [*(str(e) for e in (entry.get("evidence") or [])),
                             f"verification (measured): {rec['test']} fails at {sha7} "
                             "and passes at HEAD"]


# ── diff coverage ──────────────────────────────────────────────────────────
#
# "Coverage on changed files must not decrease" was a gate the agent could
# only declare unmeasurable: the profile named a `coverage_cmd`, nothing ran
# it, and `coverage` in the state was whatever the judgment wrote. Sales
# reported the gate unmeasurable four runs in a row. Measured now, and at a
# finer grain than a percentage — which changed lines no test executed, which
# changed functions were never entered, which tests touch the diff at all.
# coverage.py's dynamic contexts carry the test→line map; pytest-cov's
# `--cov-context=test` writes the same database in node-id form. Both are
# read. Per-test attribution is a lower bound (a tracer may record a line
# under one context and skip it under the next); "executed by any test" is
# exact, and that is what the gate is built on.

SUBPROCESS_CONTEXT = "verdict:subprocess"

COVERAGE_TIMEOUT_S = 1800
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")
_CONTEXT_SUFFIX = re.compile(r"\|(run|setup|teardown|call)$")


def _changed_lines(repo: Path, sha_range: str) -> dict:
    """Added/modified line numbers per .py file, in new-side numbering."""
    diff = _git(["diff", "-U0", "--no-color", "--diff-filter=AM", sha_range, "--", "*.py"], repo)
    changed: dict = {}
    current = None
    for line in (diff or "").splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            changed.setdefault(current, set())
        elif line.startswith("@@") and current is not None:
            m = _HUNK.match(line)
            if m:
                start, count = int(m.group(1)), int(m.group(2) or 1)
                changed[current].update(range(start, start + count))
    return {path: lines for path, lines in changed.items() if lines}


def _test_id_from_context(ctx: str, repo: Path) -> str | None:
    """`tests/test_x.py::test_a|run` → the node id. `tests.test_x.test_a` (coverage's
    own dotted form) → a node id, by finding the longest dotted prefix that is a
    file under the repo; a package dir and a test class look alike in dots."""
    ctx = (ctx or "").strip()
    if not ctx:
        return None
    if "::" in ctx:
        return _CONTEXT_SUFFIX.sub("", ctx)
    parts = ctx.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        if Path(repo, *parts[:cut]).with_suffix(".py").is_file():
            return "/".join(parts[:cut]) + ".py::" + "::".join(parts[cut:])
    return ctx


def _render_cmd(cmd: str, out: Path) -> str:
    """The `coverage json` invocation that matches how the suite was run — same
    interpreter prefix, so the database is read by the coverage that wrote it."""
    q = ('"' + str(out) + '"') if os.name == "nt" else shlex.quote(str(out))
    tail = f"-m coverage json --show-contexts -q -o {q}"
    if "-m coverage run" in cmd:
        return cmd[:cmd.index("-m coverage run")] + tail
    if "-m pytest" in cmd:
        return cmd[:cmd.index("-m pytest")] + tail
    return f"coverage json --show-contexts -q -o {q}"


def _ranges(lines: list) -> list:
    out: list = []
    for n in lines:
        if out and n == out[-1][1] + 1:
            out[-1][1] = n
        else:
            out.append([n, n])
    return out


def measure_diff_coverage(repo: Path, sha_range: str | None, cmd: str | None) -> dict:
    """Run the suite under coverage.py and intersect the result with the diff.

    → {"status": "measured", ...} with changed/executed line counts, per-file
    unexercised ranges and never-entered functions, and the tests that touch
    the diff; or {"status": "unavailable", "reason"} — said, never estimated.
    """
    if not cmd:
        return {"status": "unavailable",
                "reason": "no coverage_suite_cmd in the profile — set one that runs the suite "
                          "under coverage.py (e.g. `.venv/bin/python -m coverage run -m pytest`) "
                          "to measure which changed lines any test executed"}
    if not sha_range:
        return {"status": "unavailable",
                "reason": "no commit range this run (baseline or re-baseline) — diff coverage "
                          "measures the change since the previous run"}
    changed = _changed_lines(repo, sha_range)
    if not changed:
        return {"status": "measured", "sha_range": sha_range, "changed_files": 0,
                "changed_lines": 0, "changed_lines_executed": 0,
                "note": "no .py lines added or modified in the range"}

    # Scratch, not record. These three used to be written into the QA root,
    # which in team mode IS the committed directory: run 5 of this repository
    # left a 94,987,311-byte coverage.json there, ignored by nothing, one
    # `git add .qa` away from a permanent 95 MB blob in the repository
    # (VERDICT-F-29). Nothing here survives the measurement it feeds.
    scratch = Path(tempfile.mkdtemp(prefix="verdict-coverage-"))
    try:
        return _measure_diff_coverage(repo, scratch, sha_range, cmd, changed)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def _measure_diff_coverage(repo: Path, scratch: Path, sha_range: str, cmd: str,
                           changed: dict) -> dict:
    rc, db, out = scratch / "coverage.rc", scratch / "coverage.db", scratch / "coverage.json"
    # `ignore_errors` is not indulgence, it is proportion: measuring the suite's
    # children means the children record whatever they run, including files a
    # test generated in a temp directory that is gone before anything renders.
    # `coverage json` aborts on the first source it cannot read, so one such
    # file cost this repository its entire diff-coverage measurement — 63%
    # measured at run 5, `unavailable` at run 6 (VERDICT-F-31). A file whose
    # source cannot be read is a file no line can be attributed to anyway.
    rc.write_text("[run]\ndynamic_context = test_function\nrelative_files = True\n"
                  f"data_file = {db}\n[report]\nignore_errors = True\n"
                  "[json]\nshow_contexts = True\n", encoding="utf-8")
    # A suite that drives its code through child processes measures none of it:
    # coverage traces the process it starts. Run 5 of this repository read 217
    # changed lines of issues.py as "0 executed, not imported by anything the
    # suite executed" while eight tests exercised every one of them through a
    # CLI subprocess (VERDICT-F-28). coverage ships a startup hook that arms any
    # Python child when COVERAGE_PROCESS_START names a config; this gives those
    # children a config of their own whose static `context` is what tells their
    # lines apart from the parent's import-time execution. Nothing is injected
    # into the environment — no PYTHONPATH, no sitecustomize — and the parent's
    # own data is untouched: its lines keep the empty context, as measured.
    # Where coverage ships no such hook the children go unmeasured and the state
    # says `subprocess_coverage: none recorded`, which is a gap, not a claim.
    child_rc = scratch / "child.rc"
    child_rc.write_text(f"[run]\ncontext = {SUBPROCESS_CONTEXT}\nparallel = True\n"
                        "relative_files = True\n", encoding="utf-8")
    env = dict(os.environ, COVERAGE_RCFILE=str(rc), COVERAGE_FILE=str(db),
               COVERAGE_PROCESS_START=str(child_rc))
    started = time.monotonic()
    try:
        proc = subprocess.run(cmd, cwd=str(repo), shell=True, capture_output=True, text=True,
                              timeout=COVERAGE_TIMEOUT_S, env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"status": "unavailable", "command": cmd,
                "reason": f"coverage run did not complete: {type(exc).__name__}"}
    duration = round(time.monotonic() - started, 2)
    render = _render_cmd(cmd, out)
    try:
        rproc = subprocess.run(render, cwd=str(repo), shell=True, capture_output=True,
                               text=True, timeout=300, env=env)
    except (subprocess.TimeoutExpired, OSError) as exc:
        rproc = None
        rendered_err = type(exc).__name__
    else:
        rendered_err = _summary_line(rproc.stdout + rproc.stderr)
    if rproc is None or rproc.returncode != 0 or not out.is_file():
        return {"status": "unavailable", "command": cmd, "render_command": render,
                "suite_exit_code": proc.returncode, "duration_s": duration,
                "reason": "the suite ran but the coverage database could not be rendered: "
                          + rendered_err}
    try:
        files = (json.loads(out.read_text(encoding="utf-8")) or {}).get("files") or {}
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "unavailable", "command": cmd,
                "reason": f"coverage.json unreadable: {exc}"}

    per_file: dict = {}
    total_measured = total_executed = total_in_child = 0
    touching: set = set()
    never_entered: list = []
    for path, lines in changed.items():
        f = files.get(path) or files.get(path.replace("/", "\\"))
        if not f:
            # coverage reports the files it saw. A changed .py file it never
            # saw was imported by nothing the suite ran — every changed line
            # in it is unexercised, and that is the honest count.
            per_file[path] = {"changed": len(lines), "measured": len(lines), "executed": 0,
                              "unexercised_ranges": _ranges(sorted(lines)), "tests": [],
                              "note": "no test executed it, and no subprocess the suite "
                                      "spawned recorded a line of it"}
            total_measured += len(lines)
            continue
        ctx = f.get("contexts") or {}
        ran = lines & set(f.get("executed_lines") or [])
        # Executed *by a test*. A `def` line runs at import under the empty
        # context and proves nothing about the function it defines; counting it
        # let a brand-new, never-called function read as partly exercised and
        # kept the zero-exercised refusal from ever firing.
        executed = {ln for ln in ran if any(c for c in ctx.get(str(ln), []))}
        # A child process the suite spawned carries its own static context, so
        # its lines are non-empty above and count. Which of them ONLY a child
        # reached is worth saying: they have no test to name.
        in_test = {ln for ln in ran
                   if any(c for c in ctx.get(str(ln), []) if c != SUBPROCESS_CONTEXT)}
        only_child = {ln for ln in ran
                      if SUBPROCESS_CONTEXT in (ctx.get(str(ln)) or [])} - in_test
        missing = (lines & set(f.get("missing_lines") or [])) | (ran - executed)
        tests = {t for ln in executed for c in ctx.get(str(ln), [])
                 if c != SUBPROCESS_CONTEXT
                 for t in [_test_id_from_context(c, repo)] if t}
        fns = [name for name, fb in (f.get("functions") or {}).items()
               if name and not fb.get("executed_lines")
               and (set(fb.get("missing_lines") or []) & lines)]
        per_file[path] = {"changed": len(lines), "measured": len(executed) + len(missing),
                          "executed": len(executed),
                          **({"executed_in_subprocess": len(only_child)} if only_child else {}),
                          "unexercised_ranges": _ranges(sorted(missing)),
                          "tests": sorted(tests)[:10],
                          "unexercised_functions": fns[:10]}
        total_measured += len(executed) + len(missing)
        total_executed += len(executed)
        total_in_child += len(only_child)
        touching |= tests
        never_entered += [f"{path}:{name}" for name in fns]
    return {"status": "measured", "tool": "coverage.py dynamic contexts", "command": cmd,
            "sha_range": sha_range, "suite_exit_code": proc.returncode, "duration_s": duration,
            "changed_files": len(changed), "changed_lines": total_measured,
            "changed_lines_executed": total_executed,
            "changed_lines_executed_in_subprocess": total_in_child,
            "subprocess_coverage": "measured" if total_in_child else "none recorded",
            "percent": (round(100 * total_executed / total_measured) if total_measured else None),
            "per_file": per_file, "tests_touching_diff": sorted(touching)[:50],
            "unexercised_functions": never_entered[:20]}


def collect(repo: Path, qa_root: Path, gates: list[tuple[str, str]],
            test_ids_cmd: str | None = None, abandoned=_UNSET,
            test_one_cmd: str | None = None, coverage_suite_cmd: str | None = None) -> dict:
    """Measure everything about this run that is not a judgment."""
    now = datetime.now(timezone.utc)
    previous = None
    state_path = qa_root / "state.json"
    if state_path.is_file():
        try:
            previous = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = None

    # A marker left by the previous invocation means that run started and never
    # finished — the failure mode that once cost a whole night silently. It is
    # reported as a fact, not swept up: the next reader deserves to know the
    # gap exists.
    # Read from disk only when the caller has not already read it. `facts_main`
    # writes this run's marker before the gates start — so that a run killed
    # mid-suite still leaves one — which means by the time we get here the file
    # describes *this* run. Reading it here unconditionally made every healthy
    # run announce that the previous one had been abandoned, and a warning that
    # fires every time is one nobody reads.
    marker_path = qa_root / "run-in-progress.json"
    if abandoned is _UNSET:
        abandoned = None
        if marker_path.is_file():
            try:
                abandoned = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                abandoned = {"note": "unreadable marker"}

    key, key_source = derive_key(repo)
    # The recorded key is authoritative (§0). A profile that names its
    # Project-Key — or a previous state that already carries one — wins over
    # whatever this directory happens to be called. Nothing in the harness read
    # the header until run 4 of this repository, executed from a clone named
    # `verdict-clone`, re-keyed the committed team-mode state and its INDEX to
    # a second project name (VERDICT-F-23). In team mode `.qa/` is committed
    # and travels with the repository, so any clone, CI checkout or agent
    # worktree with a different directory name would have done the same.
    recorded = project_key_for_root(qa_root)
    if recorded and recorded != key:
        key, key_source = recorded, "profile"
    else:
        prior = _read_json(Path(qa_root) / "state.json") if qa_root else None
        if isinstance(prior, dict) and prior.get("project") and prior["project"] != key:
            key, key_source = str(prior["project"]), "state"
    sha = _git(["rev-parse", "HEAD"], repo)
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], repo)
    prev_sha = ((previous or {}).get("last_run") or {}).get("git_sha")
    sha_range = diff_stat = None
    files_changed = lines_changed = None
    if prev_sha and sha and _git(["cat-file", "-t", prev_sha], repo) == "commit":
        sha_range = f"{prev_sha}..{sha}"
        diff_stat = _git(["diff", "--shortstat", sha_range], repo)
        if diff_stat:
            nums = [int(n) for n in re.findall(r"(\d+)", diff_stat)]
            files_changed = nums[0] if nums else None
            lines_changed = sum(nums[1:]) if len(nums) > 1 else None

    run_number = int((previous or {}).get("run_number") or 0) + 1
    run_type, why = "baseline", "no previous state"
    if previous:
        run_type, why = "delta", "previous state present"
        prev_ts = ((previous or {}).get("last_run") or {}).get("timestamp_utc")
        try:
            age = now - datetime.strptime(str(prev_ts), "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=timezone.utc)
        except (ValueError, TypeError):
            age = None
        if prev_sha and sha_range is None:
            run_type, why = "re-baseline", f"stored sha {prev_sha} is not in this repository"
        elif age is not None and age > timedelta(days=RE_BASELINE_AFTER_DAYS):
            run_type, why = "re-baseline", f"previous run was {age.days} days ago"
        elif (files_changed or 0) > RE_BASELINE_FILES or (lines_changed or 0) > RE_BASELINE_LINES:
            run_type, why = "re-baseline", f"diff spans {files_changed} files / {lines_changed} lines"

    gate_results = {}
    for name, command in gates:
        started = time.monotonic()
        proc = _run(command, cwd=repo, shell=True)
        duration = round(time.monotonic() - started, 2)
        output = proc.stdout + proc.stderr
        counts, dialect = _counts(output)
        gate_results[name] = {
            "command": command,
            "exit_code": proc.returncode,
            "result": "pass" if proc.returncode == 0 else "fail",
            "duration_s": duration,
            "summary": _summary_line(output),
            **({"counts": counts, "counts_dialect": dialect} if counts else
               {"counts_unparsed": "no recognised runner summary — the count-drop gate "
                                   "and the id set-diff cannot fire for this gate"}),
            **({"executed_nothing": nothing_ran} if (nothing_ran := executed_nothing(counts))
               else {}),
        }

    # Compare each gate's duration against its own history. Prior durations
    # come from runs.jsonl rows written by finalize (gate_durations, additive
    # since 0.46.0) — the first runs after an upgrade have no history and stay
    # silent, which is honest: no baseline, no claim.
    prior_rows, _ = load_runs(qa_root)
    for name, g in gate_results.items():
        priors = [r["gate_durations"][name] for r in prior_rows
                  if isinstance(r.get("gate_durations"), dict)
                  and name in r["gate_durations"]][-5:]
        slow = duration_regressed(g.get("duration_s"), priors)
        if slow:
            g["duration_regressed"] = slow

    # Characteristic signatures of model-written code that are mechanically
    # countable — hallucinated imports, placeholders, swallowed exceptions,
    # AI-attribution of the range. Leads for §4.5 judgment, never findings.
    try:
        facts_census = code_census(repo, sha_range)
    except Exception as exc:  # a census must never cost a run
        facts_census = {"scope": f"census failed: {exc}"}

    facts = {
        "measured_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project": key,
        "project_key_source": key_source,
        "qa_root": str(qa_root),
        "schema_version": 1,
        "run_number": run_number,
        "run_type": run_type,
        "run_type_reason": why,
        "last_run": {
            "timestamp_utc": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "git_sha": sha, "git_branch": branch, "sha_range": sha_range,
            "diff_stat": diff_stat,
            # A verdict is only as good as its judge, and which model signed it
            # used to live only in the operator's memory. The runner that
            # launched the session knows; it exports VERDICT_MODEL and the
            # measurement lands here — absent when nothing exported it, never
            # guessed.
            **({"model": os.environ["VERDICT_MODEL"]}
               if os.environ.get("VERDICT_MODEL") else {}),
        },
        "gates": gate_results,
        "code_census": facts_census,
    }
    if abandoned:
        # A marker at this same commit, minutes old, is this run's own earlier
        # attempt — a mistyped gate command, a retry — not a night that was
        # lost. Reported as such and kept out of the alarm, because the alarm
        # exists to make a real gap visible and a reader who sees it fire on
        # every retry stops reading it. A marker at a *different* commit, or an
        # old one, is the real thing: coverage of that commit never happened.
        started = _parse_marker_time(abandoned.get("started_utc"))
        age_h = (now - started).total_seconds() / 3600 if started else None
        retry = (abandoned.get("git_sha") == sha and sha is not None
                 and age_h is not None and age_h <= RETRY_WINDOW_HOURS)
        if retry:
            facts["previous_attempt_this_run"] = {
                **abandoned,
                "age_hours": round(age_h, 2),
                "meaning": "an earlier attempt at this same commit, minutes ago — this "
                           "run's own retry, not a lost run. Nothing is missing",
            }
        else:
            facts["previous_run_incomplete"] = {
                **abandoned,
                **({"age_hours": round(age_h, 2)} if age_h is not None else {}),
                "meaning": "a previous run started and never wrote state; its work is "
                           "lost, not merely unreported",
            }

    tests = {}
    for gate in gate_results.values():
        tests.update(gate.get("counts", {}))
        if "duration_s" not in tests and gate.get("counts"):
            tests["duration_s"] = gate["duration_s"]
    if tests:
        # A runner that reports its own total is more trustworthy than our
        # arithmetic over its parts — several report both, and they disagree
        # when a test errors during collection.
        collected = tests.get("collected") or sum(
            v for k, v in tests.items()
            if k in ("passed", "failed", "skipped", "errors", "xfailed"))
        facts["tests"] = {**tests, "collected": collected}

    if test_ids_cmd:
        proc = _run(test_ids_cmd, cwd=repo, shell=True)
        ids = sorted({x.strip() for x in proc.stdout.splitlines() if "::" in x})
        if not ids:
            # Zero ids is almost never an empty suite; it is a command that
            # printed something else. The commonest cause is verbosity: a
            # project whose addopts already carry -q turns `--collect-only -q`
            # into -qq, which prints per-file counts instead of ids — the same
            # trap this tool's own liar fixture seeds. Reporting count 0 here
            # would be the lie §6 forbids ("0 collected is not 1 failing"), so
            # the ledger is left untouched and the gap is named.
            facts["test_ids"] = {
                "status": "unavailable",
                "reason": ("the id command produced no `::` lines "
                           f"(exit {proc.returncode}) — if the project's addopts already "
                           "set -q, drop the -q from --collect-only, which otherwise "
                           "becomes -qq and prints counts instead of ids"),
                "command": test_ids_cmd,
            }
        else:
            ledger = qa_root / "test-ids.txt"
            # splitlines, not split: parametrised ids contain spaces
            # (`test_rate[west 7kg]`), and whitespace-splitting the ledger
            # turns one id into several — every one of which then reads as
            # added or removed on the next run.
            before = ([x.strip() for x in ledger.read_text(encoding="utf-8").splitlines() if x.strip()]
                      if ledger.is_file() else [])
            added = sorted(set(ids) - set(before))
            removed = sorted(set(before) - set(ids))
            facts["test_ids"] = {
                "status": "measured",
                "count": len(ids),
                # The counts come from the untruncated sets; only the lists are
                # capped, for display. The renderer used to take len() of the
                # capped list, so a mass deletion read as "−50" under a line
                # claiming set-diff accounting — the display cap had silently
                # become the ceiling of the number the gate reported. Live on
                # run 4 of this repository: "+50" where the truth was +166
                # (VERDICT-F-20).
                "added_count": len(added),
                "removed_count": len(removed),
                "added": added[:50],
                "removed": removed[:50],
                "truncated": len(added) > 50 or len(removed) > 50,
                "source": "id set-diff, not summary arithmetic",
            }
            facts["_test_ids"] = ids
            # The ids the collector saw for the first time this run: what a
            # fix's own regression test looks like, and the one signal that
            # tells a guarding test from a mentioned one.
            facts["_added_test_ids"] = added

    verification, vnotes = verify_findings(repo, previous, test_one_cmd, prev_sha,
                                          known_ids=facts.get("_test_ids"),
                                          added_ids=facts.get("_added_test_ids"))
    if verification:
        facts["verification"] = verification
    if vnotes:
        facts["verification_notes"] = vnotes
    facts["coverage"] = measure_diff_coverage(repo, sha_range, coverage_suite_cmd)
    return facts


# ── finalize ──────────────────────────────────────────────────────────────

_LINE_NUMBERS = re.compile(r"\d+")
_WS = re.compile(r"\s+")


def finding_hash(finding: dict) -> str:
    """Stable identity: cited path + normalized title, line numbers stripped.

    Deliberately not the id: ids are minted once for humans, hashes recognise
    the same finding across runs while line numbers move underneath it.
    """
    if finding.get("hash"):
        return str(finding["hash"])
    evidence = " ".join(str(e) for e in (finding.get("evidence") or []))
    m = re.search(r"([A-Za-z0-9_./-]+\.[A-Za-z]{1,5})", evidence)
    path = m.group(1) if m else ""
    title = _WS.sub(" ", _LINE_NUMBERS.sub("", str(finding.get("title", "")))).strip().lower()
    return hashlib.sha256(f"{path}|{title}".encode()).hexdigest()[:8]


DECIDED = ("confirmed", "refuted")


def _stamp_outcome(finding: dict, prior: dict | None = None) -> dict:
    """Derive the outcome from what the finding did — never from asking.

    Three things settle a finding. It regressed (it was fixed and came back, so
    it was real). It was resolved and the fix was verified by re-injection (§6:
    absence is not evidence, a failing guard is). Or the tester withdrew it,
    which is the one event that says it was never real.

    A settled outcome then *sticks*. Without that, a finding confirmed by
    regression on run 12 and still open on run 13 would quietly return to
    undecided, and the track record would erode every time a finding changed
    state. Withdrawal is the sole exception: an explicit correction outranks an
    earlier inference, because it is the tester saying it got this wrong.
    """
    delta, status = finding.get("delta"), norm_status(finding.get("status"))
    if delta == "WITHDRAWN" or status == "withdrawn":
        return {"outcome": "refuted",
                "outcome_reason": "withdrawn by the tester as never real"}
    prior_outcome = (prior or {}).get("outcome")
    if prior_outcome in DECIDED:
        return {"outcome": prior_outcome,
                "outcome_reason": (prior or {}).get("outcome_reason")
                or "settled by an earlier run"}
    if delta == "REGRESSED":
        return {"outcome": "confirmed",
                "outcome_reason": "regressed: it was fixed and came back, so it was real"}
    # Measurement outranks the claim; silence does not. `fix_verified` reaches a
    # finding from two places — the harness sets it when its own re-injection
    # measured fail→pass, and a judgment may claim it for a re-injection done by
    # hand — and the branch that turns a resolution into a ledger row could not
    # tell them apart, so it recorded `confirmed` over a measurement that never
    # happened (VERDICT-F-32).
    #
    # 0.62.0 fixed that by demoting a claim whenever a measurement had been
    # *attempted*, and which test gets attempted is the prose lottery of
    # VERDICT-F-26: the same hand-verified claim landed `confirmed` when the
    # write-up quoted no node id and `unknown` when it did. Four findings
    # verified identically, two outcomes, decided by prose (VERDICT-F-35). So an
    # inconclusive measurement — pass at both commits, an error, nothing
    # runnable — is silence, and silence changes nothing. Only a measurement
    # that *contradicts* the claim does, and `_apply_verification` has already
    # reopened the finding by the time one does.
    #
    # What the ledger keeps is which of the two it was: `outcome_basis`, so a
    # tally can separate what the harness proved from what the tester asserted
    # rather than adding them up as one integer (VERDICT-F-36).
    v = finding.get("verification")
    attempted = isinstance(v, dict)
    shows_fix = attempted and v.get("at_previous") == "fail" and v.get("at_head") == "pass"
    contradicts = attempted and v.get("at_head") == "fail"
    claimed = finding.get("fix_verified") is True
    if delta == "RESOLVED" and shows_fix:
        return {"outcome": "confirmed", "outcome_basis": "measured",
                "outcome_reason": "fix-verified: the guarding test failed on re-injection"}
    if delta == "RESOLVED" and claimed and contradicts:
        return {"outcome": "unknown",
                "outcome_reason": "claimed fix-verified, but the cited test still fails at HEAD"}
    if delta == "RESOLVED" and claimed:
        return {"outcome": "confirmed", "outcome_basis": "claimed",
                "outcome_reason": "fix-verified: claimed by the tester, and no harness "
                                  "measurement contradicts it"}
    if delta == "RESOLVED" and finding.get("carried_forward"):
        # Weaker still than an unverified resolution: nobody claimed anything.
        return {"outcome": "unknown",
                "outcome_reason": "not re-reported; no one verified anything"}
    if delta == "RESOLVED":
        return {"outcome": "unknown",
                "outcome_reason": "resolved but not fix-verified — absence is not proof"}
    return {"outcome": "unknown", "outcome_reason": "still open; nothing has settled it"}


# Silence-as-resolution has a blast radius. A judgment that stops mentioning a
# finding usually means it is gone, and that is how a backlog drains without
# ceremony. But a *scoped* run — a merge gate over three files, a charter aimed
# at one subsystem — legitimately says nothing about the rest of the backlog,
# and reading that silence as "fixed" closes findings nobody looked at. Verdict
# shipped exactly that: a merge-gate run on sales resolved 62 open findings, 14
# of them Critical, because the judgment only spoke to the diff.
#
# So silence still resolves, but not at a scale better explained by a narrow run
# than by that many fixes. Above the line the findings are held open and carry
# the reason; a run that really did sweep everything declares `full_sweep` and
# gets the old behaviour back. Holding open is the recoverable error — a stale
# open finding costs a re-read, a wrongly-closed Critical costs the gate. Below
# the floor, proportion is noise: two of three is not evidence of anything.
CARRY_RESOLVE_FLOOR = 5
CARRY_RESOLVE_SHARE = 0.5


def merge(facts: dict, judgment: dict, previous: dict | None, today: date | None = None,
          ledger: dict | None = None) -> dict:
    """Facts + judgment → a state file, with identity and deltas computed.

    `ledger` is the permanent outcome ledger (`outcomes.json`); passing it in
    keeps this function pure while letting the calibration block count every
    finding this project ever filed, not just the ones still in state.
    """
    today = today or date.today()
    prev_by_hash, prev_by_id = {}, {}
    for f in ((previous or {}).get("findings") or []):
        if f.get("hash"):
            prev_by_hash[str(f["hash"])] = f
        if f.get("id"):
            prev_by_id[str(f["id"])] = f

    findings = []
    seen = set()
    for f in judgment.get("findings", []) or []:
        entry = dict(f)
        h = finding_hash(entry)
        prior = prev_by_hash.get(h)
        if prior is None:
            # Fall back to the id. The hash is a *content fingerprint* — cited
            # path plus normalized title — and it drifts the moment the tester
            # rewords its own finding, which it does constantly as evidence
            # accumulates. The id does not drift: §6 mints it once and forbids
            # reuse, so a re-reported id is a deliberate identity claim.
            #
            # Without this, a reworded re-report is filed as NEW *and* carried
            # forward as resolved — two entries, one id, and a state the
            # validator rightly refuses to write. Every hash in four live
            # projects was hand-authored before the harness existed and matches
            # nothing computable, so without the fallback no project could ever
            # take its first harness-driven run.
            prior = prev_by_id.get(str(entry.get("id") or ""))
            if prior is not None and prior.get("hash"):
                h = str(prior["hash"])  # identity is continuous; the fingerprint moved
        entry["hash"] = h
        seen.add(h)
        first_seen = (prior or {}).get("first_seen") or today.isoformat()
        entry["first_seen"] = first_seen
        try:
            entry["age_days"] = (today - date.fromisoformat(str(first_seen))).days
        except ValueError:
            entry["age_days"] = 0
        status = norm_status(entry.get("status", "open")) or "open"
        entry["status"] = status
        if entry.get("delta") == "WITHDRAWN":
            # The tester's own correction; the delta is never overwritten, and
            # the status follows from it — a finding that was never real cannot
            # also be open, and left to drift it would keep counting toward
            # blockers it has already been retracted from.
            entry["status"] = status = "withdrawn"
        elif prior is None:
            entry["delta"] = "NEW"
        elif status == "resolved":
            entry["delta"] = "RESOLVED"
        elif prior.get("status") == "resolved":
            entry["delta"] = "REGRESSED"
        else:
            entry["delta"] = "STILL_OPEN"

        # When a finding came back, recorded once and carried forever after.
        # `delta` describes only the transition this run computed, so a
        # regression was visible for exactly one run: anything downstream that
        # did not look on that run — `verdict-issues` filing a recurrence, for
        # one — could never learn it happened (VERDICT-F-34).
        if entry["delta"] == "REGRESSED":
            entry["regressed_at_run"] = facts.get("run_number")
        elif prior and prior.get("regressed_at_run") is not None:
            entry["regressed_at_run"] = prior["regressed_at_run"]

        # The claim is frozen at filing. Calibration scores a prediction, and a
        # confidence revised after the outcome is known is hindsight wearing a
        # prediction's clothes.
        if prior and prior.get("confidence"):
            entry["confidence"] = prior["confidence"]
        _apply_verification(entry, prior, facts.get("verification") or {})
        entry.update(_stamp_outcome(entry, prior))
        findings.append(entry)

    # A finding the previous run had and this run did not mention is resolved —
    # silence is not the same as an assertion, so it is carried, not dropped.
    unmentioned, prior_open = [], 0
    for h, prior in prev_by_hash.items():
        if norm_status(prior.get("status")) == "open":
            prior_open += 1
        if h in seen:
            continue
        if norm_status(prior.get("status")) == "withdrawn":
            # A withdrawal is the tester's own error record. Resolutions age out
            # of state into the reports and the ledger; this one stays visible,
            # because a tester that files a false positive and lets it fall off
            # the page next run is hiding the number that weighs all the others.
            findings.append(dict(prior))
            continue
        if norm_status(prior.get("status")) == "resolved":
            continue
        unmentioned.append(prior)

    # One decision for the whole set: whether this run's silence is credible as
    # resolution at all. Judged on the incoming open backlog, not on what came
    # back, because the question is how much of it this run actually looked at.
    held = (not judgment.get("full_sweep")
            and len(unmentioned) >= CARRY_RESOLVE_FLOOR
            and len(unmentioned) > CARRY_RESOLVE_SHARE * prior_open)
    for prior in unmentioned:
        carried = dict(prior)
        if held:
            carried.update(
                status="open", delta="STILL_OPEN",
                carried_forward=(
                    f"not reported this run, and not resolved: {len(unmentioned)} of "
                    f"{prior_open} open findings went unmentioned, which reads as a "
                    "scoped run rather than that many fixes — held open. Re-report "
                    "it, resolve it explicitly, or declare full_sweep."))
        else:
            carried.update(status="resolved", delta="RESOLVED",
                           carried_forward="not reported this run; no longer observed")
        # Silence is not verification — but measurement is. A finding nobody
        # re-reported proves nothing by itself; its cited test, re-run at both
        # commits, can still settle it either way.
        _apply_verification(carried, prior, facts.get("verification") or {})
        carried.update(_stamp_outcome(carried, prior))
        findings.append(carried)

    state = {
        "project": facts["project"],
        "schema_version": facts.get("schema_version", 1),
        "run_type": facts["run_type"],
        "run_number": facts["run_number"],
        "last_run": {**facts["last_run"], "report": judgment.get("report", "")},
        "isolation_check": judgment.get("isolation_check", {}),
        "gates": facts.get("gates", {}),
        # `gates: {}` alone is overloaded: a design review that ran no suite and
        # a profile missing its gates block look identical downstream. facts
        # says which one happened (`no_gates`); it used to be dropped right
        # here, so the validator could only see the ambiguous shape and chose
        # leniency — an unqualified `pass` over zero measurement (VERDICT-F-17).
        **({"no_gates": facts["no_gates"]} if facts.get("no_gates") else {}),
        **({"verification_notes": facts["verification_notes"]}
           if facts.get("verification_notes") else {}),
        "findings": findings,
        "verdict": judgment.get("verdict"),
        "release_blockers": judgment.get("release_blockers", []),
        "not_tested": judgment.get("not_tested", []),
        # What was checked and HELD. The first external user said it plainly:
        # the invariants of his money were verified intact, the report said so
        # in the middle where nobody reads, and that confirmation is the thing
        # people actually pay a tester for. Optional — a run that verified
        # nothing intact must not be pushed to invent entries.
        "verified_intact": judgment.get("verified_intact", []),
    }
    for optional in ("run_label", "next_run_focus", "flaky_quarantine", "coverage"):
        if judgment.get(optional) is not None:
            state[optional] = judgment[optional]
    # Measured coverage outranks written coverage. The judgment may still carry
    # its own block when the harness had nothing to measure with.
    if isinstance(facts.get("coverage"), dict) and facts["coverage"].get("status"):
        state["coverage"] = facts["coverage"]
    if facts.get("tests"):
        state["tests"] = facts["tests"]
    # Computed here rather than left to a consumer: the next run reads
    # state.json anyway, so its own track record arrives without asking for it.
    # Folded once, and carried: computing it here from `today` and again in
    # write_state from the run timestamp gave two different `decided_on` dates
    # across a UTC-midnight run, so the calibration block inside the state
    # could disagree with the ledger persisted beside it.
    decided_on = str((state.get("last_run") or {}).get("timestamp_utc") or "")[:10] \
        or today.isoformat()
    state["_ledger"] = merge_outcomes(ledger or {}, findings, decided_on)
    state["calibration"] = calibration(state, ledger=state["_ledger"])
    if facts.get("test_ids"):
        state["test_ids"] = facts["test_ids"]
    # Unknown keys from the previous state survive (schema rule).
    for key, value in (previous or {}).items():
        state.setdefault(key, value)
    state.pop("_qa_root", None)
    return state


def index_row(state: dict) -> str:
    t = state.get("tests") or {}
    counts = f"{t.get('passed', 'n/a')} / {t.get('skipped', 'n/a')} / {t.get('failed', 'n/a')}"
    sev = {}
    for f in state.get("findings", []):
        if is_open(f):
            sev[f.get("severity")] = sev.get(f.get("severity"), 0) + 1
    bcmm = "/".join(str(sev.get(s, 0)) for s in ("Blocker", "Critical", "Major", "Minor"))
    report = str((state.get("last_run") or {}).get("report") or "")
    name = Path(report).name
    # Measured, not composed. The Date cell came from the local clock while every
    # other stamp in the run is UTC, so a row written after 17:00 on a UTC-7 host
    # carried yesterday's date permanently — run 4 of this repository reads
    # 09-01 against a state stamped 09-02T04:44Z. And the Δ-tests cell was the
    # literal "n/a" whatever the set-diff had measured (VERDICT-F-24).
    stamp = str((state.get("last_run") or {}).get("timestamp_utc") or "")
    day = stamp[:10] if len(stamp) >= 10 else "n/a"
    ids = state.get("test_ids") or {}
    if ids.get("status") == "measured":
        delta = (f"+{ids.get('added_count', len(ids.get('added', [])))}/"
                 f"−{ids.get('removed_count', len(ids.get('removed', [])))}")
    else:
        delta = "n/a"
    return (f"| {day} | {state['project']} | {state['run_type']} "
            f"| {state['verdict']} | {counts} | {delta} | {bcmm} | [{name}]({report}) |")


INDEX_HEADER = ("| Date | Project | Run type | Verdict | Tests (pass/skip/fail) | Δ tests "
                "| Findings (B/C/M/m) | Report |\n|---|---|---|---|---|---|---|---|")


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file and `os.replace`, which is atomic on POSIX and
    Windows alike. Nothing here is large enough for the extra copy to matter,
    and a torn state.json costs a run at best."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def write_state(qa_root: Path, state: dict) -> list[str]:
    """Validate, then write: state.json.prev, state.json, and the INDEX row.

    Validation happens here because the PostToolUse hook matches Write/Edit and
    would never see a file a shell command wrote. An invalid state is not
    written at all — prevention beats notification.
    """
    # The ledger `merge` folded travels on the state under a private key —
    # taken off before anything serialises it, because reusing that result is
    # what keeps the persisted ledger and the state's own calibration block
    # describing the same run, and a leading underscore is not a licence to
    # write internals into the artifact.
    ledger = state.pop("_ledger", None)
    problems = validate(state, qa_root, _read_json(qa_root / "state.json"))
    if problems:
        return problems
    if ledger is None:
        decided_on = str((state.get("last_run") or {}).get("timestamp_utc") or "")[:10] or None
        ledger = merge_outcomes(load_outcomes(qa_root), state.get("findings", []), decided_on)

    # Atomic replace, not a bare write. A crash between truncate and flush
    # leaves the file the whole system pivots on half-written, and §6 already
    # carries a rule for recovering from a corrupt state — cheaper to make it
    # near-impossible than to handle it well.
    _atomic_write(qa_root / "state.json.prev",
                  (qa_root / "state.json").read_text(encoding="utf-8")) \
        if (qa_root / "state.json").is_file() else None
    # The chain link is computed before the state is written, because the state
    # records it: a state that names a link the history does not carry is how a
    # copied literal used to pass. history_row() does not read last_run.chain,
    # so stamping it here cannot change the row the link signs.
    prior, _ = load_runs(qa_root)
    # The correction generation is stamped before the link is computed, because
    # the link signs it: a correction is a new row with new content, and signing
    # it identically to the row it supersedes would make the two rows
    # indistinguishable to the chain.
    row = history_row(state, next_revision(qa_root, state.get("run_number")))
    earlier = [r for r in prior
               if isinstance(r.get("run_number"), int)
               and r["run_number"] < (state.get("run_number") or 0)]
    prev = str(earlier[-1].get("chain") or "") if earlier else ""
    row["chain"] = chain_link(prev, row)
    state.setdefault("last_run", {})["chain"] = row["chain"]

    _atomic_write(qa_root / "state.json", json.dumps(state, indent=2) + "\n")
    _atomic_write(qa_root / OUTCOMES_FILE,
                  json.dumps({"schema_version": 1, "project": state.get("project"),
                              "findings": ledger}, indent=2, sort_keys=True) + "\n")

    # One machine-native line per run. Appended, not rewritten: the file is
    # history, and the tolerant reader (state.load_runs) skips a torn trailing
    # line rather than dying on it.
    with (qa_root / RUNS_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")

    reports = qa_root / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    index = reports / "INDEX.md"
    if index.is_file():
        body = index.read_text(encoding="utf-8").rstrip("\n")
    else:
        body = f"# QA run index — {state['project']}\n\n{INDEX_HEADER}"
    _atomic_write(index, body + "\n" + index_row(state) + "\n")
    return []


def check_artifacts(qa_root: Path, state: dict) -> list[str]:
    """Re-read what finalize just wrote and make the four artifacts agree.

    Run 4 of this repository found two harness defects — a state re-keyed to
    the directory name, an INDEX row dated from the local clock — not by
    reading source but by reading its own artifacts back and comparing them:
    the state, the INDEX row, the runs.jsonl row and the report describe one
    run and must agree, and where they disagree the harness composed a value
    instead of measuring it. That was the agent's discipline; this is the
    harness's. Every check reads from disk, not from the objects in memory,
    because "what did we mean to write" is the question the lesson warns
    against.
    """
    problems: list[str] = []
    root = Path(qa_root)
    run = state.get("run_number")
    last = state.get("last_run") or {}

    on_disk = _read_json(root / "state.json") or {}
    if on_disk.get("run_number") != run or on_disk.get("verdict") != state.get("verdict"):
        problems.append(f"state.json on disk (run {on_disk.get('run_number')}, verdict "
                        f"{on_disk.get('verdict')!r}) is not the state just written "
                        f"(run {run}, verdict {state.get('verdict')!r})")

    rows, _ = load_runs(root)
    row = rows[-1] if rows else {}
    if row.get("run_number") != run:
        problems.append(f"runs.jsonl ends at run {row.get('run_number')}, the state says {run}")
    else:
        if row.get("chain") != last.get("chain"):
            problems.append("runs.jsonl's last link is not the one last_run.chain records")
        if row.get("verdict") != state.get("verdict"):
            problems.append(f"runs.jsonl records verdict {row.get('verdict')!r}, the state "
                            f"says {state.get('verdict')!r}")

    index = root / "reports" / "INDEX.md"
    lines = [ln for ln in index.read_text(encoding="utf-8").splitlines()
             if ln.startswith("| ") and not ln.startswith("| Date")] if index.is_file() else []
    cells = [c.strip() for c in lines[-1].strip().strip("|").split("|")] if lines else []
    stamp = str(last.get("timestamp_utc") or "")[:10]
    if not cells:
        problems.append("INDEX.md has no run row")
    else:
        if cells[0] != stamp:
            problems.append(f"INDEX row is dated {cells[0]}, the state was measured {stamp}")
        if len(cells) > 1 and cells[1] != str(state.get("project")):
            problems.append(f"INDEX row names project {cells[1]!r}, the state says "
                            f"{state.get('project')!r}")
        if len(cells) > 3 and cells[3] != str(state.get("verdict")):
            problems.append(f"INDEX row records verdict {cells[3]!r}, the state says "
                            f"{state.get('verdict')!r}")

    report = str(last.get("report") or "")
    if not report or not (root / report).is_file():
        problems.append(f"the report the state names ({report or 'none'}) is not on disk")
    elif cells and Path(report).name not in lines[-1]:
        problems.append(f"INDEX row does not link the report the state names ({Path(report).name})")
    return problems


def _read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _resolve_root(repo: Path, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    team = repo / ".qa"
    if team.is_dir():
        return team
    home = state_home()  # one spelling of the default, in state.py
    return home / derive_key(repo)[0]


def facts_main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="verdict-facts",
        description="Measure the deterministic half of a QA run. Read-only on the repo.")
    ap.add_argument("--repo", type=Path, default=Path("."))
    ap.add_argument("--qa-root", default=None)
    ap.add_argument("--gate", action="append", default=[], metavar="NAME=COMMAND",
                    help="a gate to run and measure; repeatable")
    ap.add_argument("--test-ids-cmd", default=None,
                    help="command printing one test id per line, for set-diff accounting")
    ap.add_argument("--test-one-cmd", default=None,
                    help="command running one test, `{id}` standing for the node id — "
                         "re-runs each open finding's cited test at the previous commit "
                         "and at HEAD to verify fixes (default: the profile's test_one_cmd)")
    ap.add_argument("--coverage-suite-cmd", default=None,
                    help="command running the suite under coverage.py (e.g. `.venv/bin/python "
                         "-m coverage run -m pytest`) — measures which changed lines any test "
                         "executed (default: the profile's coverage_suite_cmd)")
    ap.add_argument("--out", type=Path, default=None, help="also write facts.json here")
    ap.add_argument("--reuse-if-fresh", action="store_true",
                    help="reuse an existing facts.json when it describes this same HEAD "
                         "and is recent — a retry should not re-run the suite")
    ap.add_argument("--reuse-max-age-min", type=float, default=90.0)
    ap.add_argument("--no-profile", action="store_true",
                    help="ignore the profile's front-matter block (explicit --gate only)")
    args = ap.parse_args(argv)

    gates = []
    for spec in args.gate:
        if "=" not in spec:
            ap.error(f"--gate expects NAME=COMMAND, got {spec!r}")
        name, command = spec.split("=", 1)
        gates.append((name.strip(), command.strip()))

    repo = args.repo.expanduser().resolve()
    qa_root = _resolve_root(repo, args.qa_root)
    qa_root.mkdir(parents=True, exist_ok=True)

    # The profile already records the project's real commands; retyping them
    # into flags on every run is a transcription step, and a transcription step
    # is a place for the model to be confidently wrong. Explicit --gate still
    # wins — a caller narrowing a run should not have to edit the profile.
    profile_notes, profile_source, declared_authorship = [], None, None
    if not args.no_profile:
        try:
            config, profile_notes = load_profile(qa_root)
        except ProfileError as exc:
            print(f"verdict-facts: {exc}", file=sys.stderr)
            return 2
        from_profile = gates_from(config)
        named = {name for name, _ in gates}
        adopted = [(n, c) for n, c in from_profile if n not in named]
        gates.extend(adopted)
        if adopted:
            profile_source = [n for n, _ in adopted]
        if config.get("authorship"):
            declared_authorship = config["authorship"]
        if args.test_ids_cmd is None and config.get("test_ids_cmd"):
            args.test_ids_cmd = config["test_ids_cmd"]
            profile_notes.append("test_ids_cmd taken from the profile")
        if args.test_one_cmd is None and config.get("test_one_cmd"):
            args.test_one_cmd = config["test_one_cmd"]
            profile_notes.append("test_one_cmd taken from the profile")
        if args.coverage_suite_cmd is None and config.get("coverage_suite_cmd"):
            args.coverage_suite_cmd = config["coverage_suite_cmd"]
            profile_notes.append("coverage_suite_cmd taken from the profile")
        overridden = [n for n, _ in from_profile if n in named]
        if overridden:
            profile_notes.append(
                "gates overridden on the command line: " + ", ".join(sorted(overridden)))

    # Reuse, not resume. A model's judgment cannot be continued from the
    # middle, but the gates it was about to judge can be spared a second run —
    # and only while they still describe this commit and are minutes old.
    existing = _read_json(qa_root / "facts.json") if args.reuse_if_fresh else None
    if existing:
        head = _git(["rev-parse", "HEAD"], repo)
        try:
            age = (datetime.now(timezone.utc) - datetime.strptime(
                existing.get("measured_at", ""), "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)).total_seconds() / 60
        except (ValueError, TypeError):
            age = 1e9
        same_head = (existing.get("last_run") or {}).get("git_sha") == head
        if same_head and age <= args.reuse_max_age_min:
            existing["reused"] = {"measured_at": existing.get("measured_at"),
                                  "age_minutes": round(age, 1),
                                  "why": "same HEAD, within the freshness window; "
                                         "gates were not re-run"}
            print(json.dumps(existing, indent=2))
            return 0

    # Order matters: read whatever the last run left behind, *then* stake this
    # run's claim. The marker is written before the gates so a run killed
    # mid-suite still leaves a trace.
    abandoned = _read_json(qa_root / "run-in-progress.json")
    (qa_root / "run-in-progress.json").write_text(json.dumps({
        "started_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repo": str(repo),
        # The commit is what separates "my own retry" from "last night died".
        "git_sha": _git(["rev-parse", "HEAD"], repo)}, indent=2) + "\n",
        encoding="utf-8")
    facts = collect(repo, qa_root, gates, args.test_ids_cmd, abandoned=abandoned,
                    test_one_cmd=args.test_one_cmd, coverage_suite_cmd=args.coverage_suite_cmd)
    if declared_authorship:
        facts.setdefault("code_census", {}).setdefault("provenance", {})[
            "declared"] = declared_authorship
    if profile_source:
        facts["gates_from_profile"] = profile_source
    if profile_notes:
        facts["profile_notes"] = profile_notes
    if not gates:
        # Said out loud rather than left to inference: a run with no gates
        # measured nothing, and "nothing to measure" and "nobody told me what
        # to measure" are different states of the world.
        facts["no_gates"] = ("no gates ran — neither --gate nor a profile front-matter "
                             "block supplied one, so every count and duration gate is "
                             "unmeasurable this run")
    facts.pop("_added_test_ids", None)  # internal, like _test_ids: never written
    ids = facts.pop("_test_ids", None)
    if ids is not None:
        (qa_root / "test-ids.txt").write_text("\n".join(ids) + "\n", encoding="utf-8")
    text = json.dumps(facts, indent=2)
    (args.out or (qa_root / "facts.json")).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


def finalize_main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="verdict-finalize",
        description="Merge measured facts with the agent's judgment into state.json.")
    ap.add_argument("--qa-root", required=True)
    ap.add_argument("--facts", type=Path, default=None, help="default: <qa-root>/facts.json")
    ap.add_argument("--judgment", type=Path, required=True)
    args = ap.parse_args(argv)

    qa_root = Path(args.qa_root).expanduser().resolve()
    facts = _read_json(args.facts or (qa_root / "facts.json"))
    judgment = _read_json(args.judgment)
    if facts is None:
        print("verdict-finalize: facts.json missing or unreadable — run verdict-facts first",
              file=sys.stderr)
        return 2
    if judgment is None:
        print(f"verdict-finalize: {args.judgment} missing or unreadable", file=sys.stderr)
        return 2

    previous = _read_json(qa_root / "state.json")

    # Checked here, where the author of judgment.json still stands. Validating
    # only the merged state stops a bad state reaching disk but explains it in
    # the vocabulary of a structure the agent did not write — a reworded
    # evidence line used to surface as `repeats id`, which says nothing about
    # what to change.
    author_problems = validate_judgment(judgment, previous)
    if author_problems:
        print(f"verdict-finalize: {args.judgment} has {len(author_problems)} problem(s) "
              "— fix the judgment, not the check:\n  " + "\n  ".join(author_problems),
              file=sys.stderr)
        return 1

    state = merge(facts, judgment, previous, ledger=load_outcomes(qa_root))

    # Render the report before validating: the validator requires the file to
    # exist, and writing it here is what makes "the report went missing"
    # impossible rather than merely forbidden.
    report_rel = (state.get("last_run") or {}).get("report") or ""
    if not report_rel or not report_rel.endswith(".md"):
        stamp = facts.get("measured_at", "")[:10]
        topic = judgment.get("topic") or state.get("run_type", "run")
        report_rel = f"reports/{stamp}-{topic}.md".replace(" ", "-")
        state["last_run"]["report"] = report_rel
    report_path = qa_root / report_rel
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(state, judgment.get("prose")), encoding="utf-8")

    problems = write_state(qa_root, state)
    if problems:
        print(f"verdict-finalize: refusing to write an invalid state "
              f"({len(problems)} problem(s)):\n  " + "\n  ".join(problems), file=sys.stderr)
        return 1
    marker = qa_root / "run-in-progress.json"
    marker.unlink(missing_ok=True)
    disagreements = check_artifacts(qa_root, state)
    if disagreements:
        # Loud, on the stream the agent reads, and not a refusal: the run is
        # recorded and the state is valid. What is wrong is a renderer, and a
        # renderer defect is a finding about this harness — file it.
        print("verdict-finalize: WARNING — the artifacts this run wrote disagree with each "
              f"other ({len(disagreements)}); where they disagree the harness composed a "
              "value instead of measuring it. File it as a finding against verdict:\n  "
              + "\n  ".join(disagreements), file=sys.stderr)
    print(f"verdict-finalize: wrote {qa_root / 'state.json'} and {report_path} "
          f"(run {state['run_number']}, {state['run_type']}, verdict {state['verdict']!r}), "
          f"appended the INDEX row, cleared the run marker")
    return 0


def main(argv=None) -> int:
    """Bare-script entry: an explicit subcommand, because dispatching on the
    script's own filename breaks the moment anyone renames or symlinks it."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("facts", "finalize"):
        sub = argv.pop(0)
        return facts_main(argv) if sub == "facts" else finalize_main(argv)
    print("usage: harness.py {facts|finalize} [options]   "
          "(installed as verdict-facts / verdict-finalize)", file=sys.stderr)
    return 2




# ── the report, rendered ──────────────────────────────────────────────────

def _render_calibration(cal: dict) -> list[str]:
    """The tester's own track record, or nothing at all.

    Nothing at all until something has actually been settled: a section reading
    "0 of 0" trains the reader to skip it, and by the time there is a number
    worth seeing they no longer look. Rates stay hidden until the bucket has
    enough decided outcomes to earn one — `reading` carries the counts either
    way, so the section is honest at every sample size.
    """
    if not cal or not cal.get("decided_outcomes"):
        return []
    lines = ["", "## Track record", "",
             f"{cal.get('findings_tracked', 0)} findings tracked across this project's "
             f"history · {cal['decided_outcomes']} settled, "
             f"{cal.get('undecided_outcomes', 0)} still undecided.", ""]
    for label, store in (("Confidence claimed", cal.get("by_confidence") or {}),
                         ("Proof method", cal.get("by_proof_method") or {})):
        rows = [(k, v) for k, v in store.items() if v.get("decided")]
        if not rows:
            continue
        lines += [f"| {label} | Held up | Withdrawn | Rate |", "|---|---|---|---|"]
        for key, v in sorted(rows, key=lambda kv: -kv[1]["decided"]):
            rate = f"{v['precision']:.0%}" if v.get("precision") is not None else "_not yet_"
            lines.append(f"| {key} | {v['confirmed']} | {v['refuted']} | {rate} |")
        lines.append("")
    lines += [f"*A rate appears once a row has {cal.get('min_sample')} settled outcomes. "
              "Settled means fix-verified or regressed (it held up) against withdrawn "
              "(it did not); a finding merely resolved is not evidence either way.*", ""]
    return lines


def render_report(state: dict, prose: dict | None = None) -> str:
    """Render the report from the state, injecting the agent's prose.

    Everything countable comes from the state, so the report and the state
    cannot disagree — they did, once, when the state pointed at a stale file.
    Everything that requires a sentence comes from `prose`, because a rendered
    table is not an explanation and nobody should pretend otherwise.
    """
    # Belt and braces: `validate_judgment` rejects a non-object `prose` with a
    # message its author can act on, but a renderer that raises AttributeError
    # on unexpected input is a renderer that loses a whole run to a typo.
    prose = prose if isinstance(prose, dict) else {}
    last = state.get("last_run") or {}
    out = [f"# QA report — {state.get('project')} · run {state.get('run_number')} "
           f"({state.get('run_type')})", ""]
    if state.get("run_label"):
        out += [f"*{state['run_label']}*", ""]
    out += [f"**VERDICT: {state.get('verdict')}**", ""]

    out += ["## Scope", "",
            f"- Range: `{last.get('sha_range') or last.get('git_sha') or 'n/a'}`"
            + (f" · {last['diff_stat']}" if last.get("diff_stat") else ""),
            f"- Branch: `{last.get('git_branch') or 'n/a'}` · measured {last.get('timestamp_utc')}"]
    iso = state.get("isolation_check") or {}
    if iso:
        detail = iso.get("method") or iso.get("note") or ""
        out.append(f"- Isolation check: **{iso.get('result', iso.get('status', 'n/a'))}**"
                   + (f" — {detail}" if detail else ""))
    if prose.get("scope"):
        out += ["", prose["scope"]]

    gates = state.get("gates") or {}
    if gates:
        out += ["", "## Gates", "", "| Gate | Result | Exit | Duration | Summary |",
                "|---|---|---|---|---|"]
        for name, g in gates.items():
            out.append(f"| `{name}` | {g.get('result', '?')} | {g.get('exit_code', '?')} "
                       f"| {g.get('duration_s', '?')}s | {str(g.get('summary', ''))[:120]} |")
    tests = state.get("tests") or {}
    if tests:
        counted = ", ".join(f"{k} {v}" for k, v in tests.items() if k != "duration_s")
        out += ["", f"Tests: {counted}"]
    ids = state.get("test_ids") or {}
    if ids.get("status") == "measured":
        # Counts, not list lengths: the lists are capped at 50 for display and a
        # state from before the counts travelled falls back to the old reading.
        added_n = ids.get("added_count", len(ids.get("added", [])))
        removed_n = ids.get("removed_count", len(ids.get("removed", [])))
        out.append(f"Test-id ledger: {ids['count']} ids · +{added_n} / −{removed_n} "
                   "(set-diff, not summary arithmetic)"
                   + (" — id lists truncated to 50 each" if ids.get("truncated") else ""))
    elif ids.get("status") == "unavailable":
        out.append(f"Test-id ledger: **unavailable** — {ids.get('reason', '')}")
    measured = [f for f in state.get("findings", []) if isinstance(f.get("verification"), dict)]
    if measured or state.get("verification_notes"):
        # Counted from the measurement, never from `fix_verified` — that is the
        # one judgment field here, and counting it inside a block selected by
        # measurement published run 5's error/error record as "1 verified"
        # (VERDICT-F-30). Both halves below are the harness's own: `at_*` come
        # from the re-run, `delta` from merge.
        def _shows_fix(f):
            v = f["verification"]
            return v.get("at_previous") == "fail" and v.get("at_head") == "pass"
        verified = sum(1 for f in measured if _shows_fix(f) and f.get("delta") == "RESOLVED")
        refused = sum(1 for f in measured if f.get("resolution_refused"))
        out.append(f"Fix verification: {verified} verified · {refused} refused (cited test "
                   f"still fails at HEAD) · {len(measured) - verified - refused} measured but "
                   "not verifiable")
        unconfirmed = [str(f.get("id")) for f in measured
                       if f.get("fix_verified") is True and not _shows_fix(f)]
        if unconfirmed:
            out.append("  - claims fix_verified the measurement does not show: "
                       + ", ".join(unconfirmed))
        for note in state.get("verification_notes") or []:
            out.append(f"  - {note}")
    cov = state.get("coverage") or {}
    if cov.get("status") == "measured":
        if cov.get("changed_lines"):
            out.append(f"Diff coverage: {cov['changed_lines_executed']}/{cov['changed_lines']} "
                       f"changed lines executed ({cov.get('percent')}%) across "
                       f"{cov['changed_files']} file(s); "
                       f"{len(cov.get('tests_touching_diff') or [])} test(s) touch the diff")
            if cov.get("changed_lines_executed_in_subprocess"):
                out.append(f"  - {cov['changed_lines_executed_in_subprocess']} of them only in a "
                           "subprocess the suite spawned — measured, but no test to name")
            for path, pf in (cov.get("per_file") or {}).items():
                if pf.get("unexercised_ranges"):
                    rng = ", ".join(f"{a}-{b}" if a != b else str(a)
                                    for a, b in pf["unexercised_ranges"])
                    fns = ", ".join(pf.get("unexercised_functions") or [])
                    out.append(f"  - {path}: unexercised lines {rng}"
                               + (f" — functions never entered: {fns}" if fns else "")
                               + (f" ({pf['note']})" if pf.get("note") else ""))
        else:
            out.append("Diff coverage: no .py lines changed in the range")
    elif cov.get("status") == "unavailable":
        out.append(f"Diff coverage: **unmeasurable** — {cov.get('reason', '')}")

    if prose.get("risks"):
        out += ["", "## Risks", "", prose["risks"]]

    # The gate, the MCP surface and this report must agree on what "REGRESSED
    # first" means. They did not: this module carried its own copy of the sort,
    # and a severity with a stray space already sorted differently in the two.
    findings = order_findings(state.get("findings") or [])
    open_f = [f for f in findings if is_open(f)]
    out += ["", f"## Findings — REGRESSED first ({len(open_f)} open of {len(findings)} tracked)", ""]
    if not findings:
        out.append("_None recorded this run._")
    for f in findings:
        cls = f.get("failure_classification")
        out.append(f"### {f.get('id')} — {f.get('delta', '?')} — "
                   f"{f.get('severity')}/{f.get('priority')}"
                   + (f" — {cls}" if cls else "")
                   + (f" — age {f['age_days']}d" if f.get("age_days") else ""))
        out.append("")
        out.append(str(f.get("title", "")))
        for e in (f.get("evidence") or []):
            out.append(f"- {e}")
        rc = f.get("root_cause") or {}
        if rc:
            chain = " → ".join(str(rc[k]) for k in ("mechanism", "origin") if rc.get(k))
            if chain:
                out.append(f"- Root cause: {chain}")
            if rc.get("class"):
                out.append(f"- Class: {json.dumps(rc['class'])[:200]}")
        if f.get("carried_forward"):
            out.append(f"- _{f['carried_forward']}_")
        narrative = prose.get("findings")
        if isinstance(narrative, dict) and narrative.get(str(f.get("id"))):
            out += ["", narrative[str(f.get("id"))]]
        out.append("")

    out += _render_calibration(state.get("calibration") or {})

    blockers = state.get("release_blockers") or []
    out += ["## Release blockers", "",
            "\n".join(f"- {b}" for b in blockers) if blockers else "_None._", ""]
    vi = state.get("verified_intact") or []
    if vi:
        # Placed directly after the blockers, not buried mid-report: the
        # confirmation that named invariants held is a headline, not a footnote.
        out += ["## Verified intact", "",
                "\n".join(f"- {v}" for v in vi), ""]
    out += ["## Not tested", ""]
    nt = state.get("not_tested") or []
    out.append("\n".join(f"- {n}" for n in nt) if nt else
               "_Nothing listed — which is itself a reporting failure if the surface was not covered._")
    if prose.get("fix_order"):
        out += ["", "## Fix order", "", prose["fix_order"]]
    if state.get("next_run_focus"):
        out += ["", "## Next run focus", "",
                "\n".join(f"- {n}" for n in state["next_run_focus"])]
    quarantine = state.get("flaky_quarantine") or []
    if quarantine:
        out += ["", "## Quarantine", ""]
        for q in quarantine:
            out.append(f"- `{q.get('test_id')}` until {q.get('quarantined_until')} "
                       f"({q.get('fail_count', '?')}/{q.get('run_count', '?')} runs)")
    if prose.get("notes"):
        out += ["", "## Notes", "", prose["notes"]]
    out += ["", "---", "",
            "*Countable sections rendered from `state.json` by `verdict-finalize`; the "
            "prose is the agent's. They cannot disagree.*"]
    return "\n".join(out).rstrip() + "\n"


if __name__ == "__main__":
    sys.exit(main())
