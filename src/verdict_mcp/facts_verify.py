"""Re-running the tests a finding cites, in a scratch checkout, to see whether the
finding still reproduces: which test, which command, and what its exit means.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .state import is_open
    from .harness_common import _chosen, _run
    from .facts_suite import _counts, _summary_line
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import is_open
    from harness_common import _chosen, _run
    from facts_suite import _counts, _summary_line


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


VERIFY_CANDIDATES_SHOWN = 5


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
    # Never let a cached module decide what ran. CPython validates bytecode on
    # the source's modification time in WHOLE SECONDS plus its size, so two
    # same-size writes inside one second are indistinguishable and the second
    # silently executes the first's bytecode. Fix verification is exactly that
    # shape: the same test id is run against two versions of a tree, and this
    # scratch has files copied into it from HEAD (VERDICT-F-50).
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
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


def _drop_bytecode(root: Path) -> None:
    """Remove every `__pycache__` under `root`.

    Belt to `PYTHONDONTWRITEBYTECODE`'s braces: the variable stops this run
    writing a cache, and this stops it reading one an earlier run left. The
    measurement that named the cost: a re-injection campaign against this
    project killed 4 of 5 mutants with the cache in place and 5 of 5 with it
    swept, while the check the contract prescribed — printing the loaded
    module's `__file__` — was correct in both cases, because the path was never
    what was wrong (VERDICT-F-50).
    """
    for cache in Path(root).rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


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

    # Which test, decided before anything runs. A node id in prose is text,
    # not a citation, however many there are. Several with none declared was
    # refused first (run 12 verified VERDICT-F-26 against an id quoted inside
    # another finding's evidence); a single one was kept as "the conservative
    # direction" in 0.79.0 — it could only hold a finding open — and then
    # mis-selected on six consecutive runs, never once refusing anything, while
    # stamping a measurement of an unrelated test on the finding every time.
    # So a prose citation, one or several, gets a record that says so and no
    # run at all. `verification_test` is how a test becomes somebody's choice.
    results: dict = {}
    runnable, unselectable = [], []
    for finding, tests in cited:
        test_id, how = select_test(finding, tests, preferred)
        if how == "first_cited":
            n = len(tests)
            results[str(finding.get("id"))] = {
                "test": None, "selected_by": "unselectable", "candidates": n,
                "candidate_tests": tests[:VERIFY_CANDIDATES_SHOWN],
                "previous_sha": previous_sha,
                "at_previous": "unavailable", "at_head": "unavailable",
                "summary": (f"not run: {n} test{'s' if n != 1 else ''} cited in prose, "
                            "none declared as verification_test")}
            unselectable.append(str(finding.get("id") or "?"))
        else:
            runnable.append((finding, tests, test_id, how))
    if unselectable:
        shown = ", ".join(unselectable[:5])
        more = f" and {len(unselectable) - 5} more" if len(unselectable) > 5 else ""
        notes.append(f"nothing was run for {shown}{more}: each cites tests only in prose "
                     "and declares none as `verification_test` — a node id in prose is "
                     "text, not a citation; declare it to make the measurement count")
    if not runnable:
        return results, notes

    scratch = None
    if previous_sha:
        scratch = _scratch_checkout(repo, str(previous_sha))
        if scratch is None:
            notes.append(f"previous commit {str(previous_sha)[:7]} is not in this repository "
                         "— verification ran at HEAD only")
    else:
        notes.append("no previous commit recorded — verification ran at HEAD only")

    try:
        for finding, tests, test_id, how in runnable:
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
                _drop_bytecode(scratch)
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


def _apply_verification(entry: dict, prior: dict | None, verification: dict,
                        measured_at: str | None = None) -> None:
    """Stamp the measurement on a finding, and refuse a resolution it contradicts.

    Runs before the outcome is derived, so a verified fix reaches the ledger as
    `confirmed` and a refused one stays undecided. A cited test that still
    fails at HEAD overrides both an explicit `resolved` and silence: neither a
    claim nor an absence can close a finding whose demonstrating test fails on
    the code being judged.
    """
    key = str(entry.get("id") or (prior or {}).get("id") or "")
    # The last time the harness ran this finding's test is a date the finding
    # keeps: "STILL_OPEN 12d, measured yesterday" and "STILL_OPEN 12d, never
    # measured" are two different sentences, and only one of them is a reason
    # to declare a `verification_test`.
    if prior and prior.get("last_verified_at") and not entry.get("last_verified_at"):
        entry["last_verified_at"] = prior["last_verified_at"]
    rec = verification.get(key) if verification else None
    if not rec:
        return
    entry["verification"] = rec
    if rec.get("at_head") in ("pass", "fail") and measured_at:
        # A measurement is a test that ran on the code under judgment. An
        # `error` or an `unavailable` did not run it, and dates nothing.
        entry["last_verified_at"] = measured_at
    resolving = entry.get("delta") == "RESOLVED"
    # Two directions, two bars. A prose citation, one or several, no longer
    # reaches here from `verify_findings` at all — it is reported
    # `unselectable` and nothing runs (VERDICT-F-26) — so a record here rests
    # on a chosen test, or arrived by hand. Refusing is the conservative
    # direction: a finding held open costs a re-read, so a test that fails on
    # the code under judgment may refuse, whatever chose it.
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
        if not _chosen(rec):
            # The flattering direction needs a chosen test. A pytest id merely
            # quoted in a finding's prose wrote `fix_verified: true`, a
            # "verification (measured)" evidence line and a confirmed row into
            # the track record that grades the tester — the same pick that was
            # already too weak to refuse with (VERDICT-F-72). Recorded, not
            # weighed; `_stamp_outcome` reads the same mark.
            rec["not_weighed"] = ("measured fail→pass on a test cited only in prose — a "
                                  "confirmation must rest on a test somebody chose; declare "
                                  "`verification_test` to make it count")
            return
        entry["fix_verified"] = True
        if measured_at:
            # The verified-fix date — when the harness watched the guard fail
            # at the old commit and pass at HEAD — not the fix commit's own
            # date, which nobody bisected. Fix latency is measured from here.
            entry["fixed_at"] = measured_at[:10]
        sha7 = str(rec.get("previous_sha") or "")[:7]
        entry["evidence"] = [*(str(e) for e in (entry.get("evidence") or [])),
                             f"verification (measured): {rec['test']} fails at {sha7} "
                             "and passes at HEAD"]
