"""Tests the suite switches off: skips with no expiry and no condition, the files they are
read from, and the findings filed for them.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import re
import subprocess
import sys
from datetime import date
from pathlib import Path

try:
    from . import clock, testmarks
    from .gitenv import git_env
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    import testmarks
    from gitenv import git_env


SKIP_MARKER = re.compile(
    r"^[ \t]*(?:@(?:pytest\.mark|unittest)\.(?P<marker>skip|skipif)|(?P<call>pytest\.skip))"
    r"\(\s*(?P<args>[^)]*)", re.M)


# A condition that is not a constant makes the skip a guard, not a graveyard.
_ALWAYS = re.compile(r"^\s*(?:True|1)\s*(?:,|$)")


_DATE = re.compile(r"\b(20\d\d)-(\d\d)-(\d\d)\b")


def skips_without_expiry(repo: Path, files: list, read: set | None = None) -> list:
    """Every skip marker whose reason names no expiry — a quarantine with no end is a
    test that has been deleted without anyone deciding to delete it.

    `read`, when given, collects every file this pass actually read: a file it could not
    open found nothing, and that is not the same as a file with nothing in it
    (`local_skip_close.py` closes a finding only over a file that was read)."""
    out = []
    for rel in files:
        try:
            text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if read is not None:
            read.add(rel)
        lang = testmarks.suite_language(rel)
        if lang is not None:
            # Every other test framework: `it.skip`, `xit`, `@Disabled`, `t.Skip`, `#[ignore]`,
            # and the focus markers (`it.only`, `fit`) that switch off everything around them.
            for mark in testmarks.marks(text, lang):
                if mark["kind"] == "focus" or not has_expiry(mark["reason"]):
                    out.append({"path": rel, "line": mark["line"], "reason": mark["reason"],
                                "kind": mark["kind"]})
            continue
        for m in SKIP_MARKER.finditer(text):
            args = m.group("args") or ""
            if m.group("marker") == "skipif" and not _ALWAYS.match(args):
                # `skipif(sys.version_info < (3, 9))` is a guard: it runs wherever it can,
                # and it has no expiry because it needs none. Measured on boltons, where
                # every version guard came back as a finding until this line existed.
                continue
            line = text[:m.start()].count("\n") + 1
            if m.group("call") and _under_a_condition(text, line):
                # `if not shutil.which("tar"): pytest.skip(...)` is the same guard written
                # as a call. The trace of 2026-10-15 counted seven of them on Verdict's own
                # suite, filed as abandoned tests every run.
                continue
            if not has_expiry(args):
                out.append({"path": rel, "line": line, "reason": args.strip()[:200]})
    return out


_CONDITION = re.compile(r"^\s*(?:if|elif|else|except|for|while)\b")


def _under_a_condition(text: str, line: int) -> bool:
    """True when the statement on `line` sits inside an `if`/`except`/loop block: the nearest
    line above it with less indentation opens one. A skip call at the top of a function or
    a module is unconditional, and that is the graveyard this scan is for."""
    lines = text.splitlines()
    own = lines[line - 1]
    depth = len(own) - len(own.lstrip())
    for prev in reversed(lines[:line - 1]):
        if not prev.strip():
            continue
        indent = len(prev) - len(prev.lstrip())
        if indent < depth:
            return bool(_CONDITION.match(prev))
    return False


def collected_test_files(repo: Path, qa_root: Path) -> list | None:
    """The files the suite collects, from the test-id ledger `verdict-facts` writes — or None
    when there is no ledger with `path::name` ids to read. A test-looking file pytest never
    collects (an eval fixture, a vendored suite) is not a quarantine: Verdict's own release
    gates filed `eval/fixtures/pricer/test_pricer.py` as an abandoned skip for weeks."""
    try:
        ids = (qa_root / "test-ids.txt").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    files = sorted({i.split("::", 1)[0].strip().replace("\\", "/") for i in ids if "::" in i})
    files = [f for f in files if f and (repo / f).is_file()]
    return files or None


def skip_scan_files(repo: Path, qa_root: Path) -> list:
    """The Python files the suite collects (or the test-shaped ones, without a ledger), and the
    project's own test files in every other language this scan reads."""
    python = collected_test_files(repo, qa_root) or test_files(repo)
    return python + [f for f in other_test_files(repo) if f not in python]


def other_test_files(repo: Path) -> list:
    """The tracked test files of the project's own suite in languages other than Python: a Jest
    spec, an RSpec file, a JUnit class, a Go `_test.go`. Not an eval's fixtures or an example."""
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True,
                          env=git_env())
    if proc.returncode != 0:
        return []
    return [n for n in proc.stdout.decode("utf-8", "replace").split("\0")
            if n and not n.endswith(".py") and testmarks.is_suite_file(n)]


def has_expiry(reason: str) -> bool:
    """True only when the reason names a date still in the future.

    "temporarily disabled 2026-05-02" is not an expiry — it is the day someone disabled
    it and moved on, which is exactly the shape of a test that will never run again. A
    naive date match read that as a deadline and let the whole class through.
    """
    today = clock.today()
    for match in _DATE.finditer(reason or ""):
        try:
            when = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        except ValueError:
            continue
        if when > today:
            return True
    return False


def test_files(repo: Path) -> list:
    out = []
    for path in sorted(repo.rglob("*.py")):
        if ".venv" in path.parts or ".git" in path.parts:
            continue
        name = path.name
        if name.startswith("test_") or name.endswith("_test.py") or "tests" in path.parts:
            # Forward slashes on every platform, as pytest spells its ids: the ledger and
            # the tree walk name the same file the same way.
            out.append(str(path.relative_to(repo)).replace("\\", "/"))
    return out


def group_skips(skips: list) -> list:
    """One finding per file and reason, citing every line that carries it.

    Measured on Sales (2026-09-18): two skip markers in one test file with the same reason
    became two findings with one identity — path and title are what a finding's hash is
    made of — and finalize refused the night for it. They are one decision somebody did
    not make, in two places; they are filed as one finding with both sites."""
    grouped: dict = {}
    for skip in skips:
        grouped.setdefault((skip["path"], skip["reason"], skip.get("kind", "skip")),
                           []).append(skip["line"])
    return [{"path": path, "reason": reason, "line": lines[0], "lines": lines, "kind": kind}
            for (path, reason, kind), lines in grouped.items()]


# The line every finding this scan files carries — `skip_finding` here and `focus_finding` in
# local_suite.py — and the line `local_skip_close.py` knows the scan's findings by.
SCAN_EVIDENCE = "found by a regular expression over the test files, not by a model"


def skip_finding(skip: dict, ident: str) -> dict:
    lines = skip.get("lines") or [skip["line"]]
    return {
        "id": ident,
        "title": f"A test is skipped with no expiry: {skip['reason'][:90]}"[:200],
        "severity": "Minor", "priority": "P2", "status": "open",
        "failure_classification": "BRITTLE_TEST", "confidence": "proven",
        "evidence": [f"{skip['path']}:{line} — skip marker with reason "
                     f"{skip['reason'][:200]!r}; no date or expiry in the reason"
                     for line in lines]
                    + [SCAN_EVIDENCE],
        "root_cause": {"mechanism": "A skip with no expiry is a deleted test that nobody "
                                    "decided to delete: it never runs again and no one is "
                                    "told.",
                       "origin": "not investigated in local mode"},
        "narrative": "A skipped test with no expiry silently removes coverage. Either give "
                     "the skip an expiry date or delete the test deliberately.",
    }
