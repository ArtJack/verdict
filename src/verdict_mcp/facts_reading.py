"""Which tests read which source files: the reading map and the exercised-by index
the coverage contexts give, for the tracked Python files of the repository.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from .state import is_open, norm_status
    from .harness_common import _git
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import is_open, norm_status
    from harness_common import _git


SUBPROCESS_CONTEXT = "verdict:subprocess"


_TEST_FILE = re.compile(r"(^|/)(tests?|testing)/|(^|/)(test_[^/]+|[^/]+_test|conftest)\.py$")


def is_test_file(path: str) -> bool:
    """Test code or production code, for a coverage number that means something.

    The executed-under-a-test-context rule is right for production code and
    structurally wrong for test code: a fixture body and a `def test_*` line
    never carry a context, so every test file pays a permanent unexercised tax.
    Blended, the percent then moves with the test/production composition of the
    diff rather than with coverage — 91% to 78% across two runs of this
    repository while production coverage rose from 97% to 100% (VERDICT-F-44).
    """
    return bool(_TEST_FILE.search(str(path).replace("\\", "/")))


_CONTEXT_SUFFIX = re.compile(r"\|(run|setup|teardown|call)$")


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


def _tracked_python(repo: Path) -> list[str]:
    """Every .py file git tracks — coverage.py reports only the files the
    suite imported, and a module nothing imports is the least-tested code
    there is: 0%, and invisible to the tracer."""
    out = _git(["ls-files", "--", "*.py", "**/*.py"], repo) or ""
    return sorted({ln.strip().replace("\\", "/") for ln in out.splitlines() if ln.strip()})


def reading_map_from(files: dict, findings, tracked=None) -> dict:
    """Every production module the suite saw, least covered first, with the
    findings that cite it (from the anchors 0.83.0 keeps) and the modules no
    finding has ever cited. Boltons runs 2–4 produced 13 of the project's 15
    highest-severity findings from its six lowest-coverage modules, and the
    agent re-derived this ranking by hand on every run."""
    modules = []
    for path, f in (files or {}).items():
        p = str(path).replace("\\", "/")
        if is_test_file(p):
            continue
        summ = (f or {}).get("summary") or {}
        n = int(summ.get("num_statements") or 0)
        if n == 0:
            continue
        pct = summ.get("percent_covered")
        modules.append({"path": p, "percent": round(float(pct)) if pct is not None else None,
                        "statements": n, "missed": int(summ.get("missing_lines") or 0)})
    seen = {m["path"] for m in modules}
    # The roots the suite imports from (`boltons/` for boltons; `.` for a
    # flat repository). A tracked file outside them — docs/conf.py, a bench
    # script under misc/ — is not a module to read, and the first acceptance
    # run put four of them at the top of the map.
    roots = {m["path"].rsplit("/", 1)[0] if "/" in m["path"] else "." for m in modules}
    outside = []
    for path in tracked or []:
        if path in seen or is_test_file(path):
            continue
        root = path.rsplit("/", 1)[0] if "/" in path else "."
        if not any(root == r or root.startswith(r + "/") for r in roots):
            outside.append(path)
            continue
        # Tracked, never imported by anything the suite ran: 0%, size unknown
        # to the tracer, and the first thing to read.
        modules.append({"path": path, "percent": 0, "statements": None, "missed": None,
                        "never_imported": True})
    modules.sort(key=lambda m: (m["percent"] if m["percent"] is not None else 101,
                                -(m["statements"] or 10 ** 9)))
    by_module: dict = {}
    for f in findings or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        st = norm_status(f.get("status"))
        if st in ("resolved", "withdrawn"):
            continue
        for a in f.get("anchors") or []:
            path = str((a or {}).get("path") or "").replace("\\", "/")
            if not path:
                continue
            entry = by_module.setdefault(path, {"open": 0, "ids": [], "last_cited_run": None})
            if f["id"] in entry["ids"]:
                continue
            entry["ids"].append(f["id"])
            if st == "open":
                entry["open"] += 1
            run = f.get("anchored_at_run")
            if isinstance(run, int) and (entry["last_cited_run"] is None or run > entry["last_cited_run"]):
                entry["last_cited_run"] = run
    lowest = []
    for m in modules[:25]:
        cited = by_module.get(m["path"])
        lowest.append({**m, "open_findings": cited["open"] if cited else 0,
                       "last_cited_run": cited["last_cited_run"] if cited else None})
    total = sum(m["statements"] or 0 for m in modules)
    missed = sum(m["missed"] or 0 for m in modules)
    # Functions no test ever entered (0.91.0): `read_first` ranks them on a baseline, where
    # there is no range to rank changed lines by.
    unentered = []
    for path, f in (files or {}).items():
        p = str(path).replace("\\", "/")
        if is_test_file(p):
            continue
        for name, fb in ((f or {}).get("functions") or {}).items():
            gone = len((fb or {}).get("missing_lines") or [])
            if name and gone and not (fb or {}).get("executed_lines"):
                unentered.append({"path": p, "function": name, "missed": gone})
    unentered.sort(key=lambda u: (-u["missed"], u["path"], u["function"]))
    return {"status": "measured", "modules": len(modules),
            **({"functions_never_entered": unentered[:60]} if unentered else {}),
            "overall_percent": (round(100 * (total - missed) / total) if total else None),
            "lowest": lowest,
            "never_examined": [m["path"] for m in modules if m["path"] not in by_module][:10],
            **({"outside_package": outside[:20]} if outside else {}),
            "findings_by_module": by_module}


def exercised_by_from(files: dict, findings, repo: Path) -> dict:
    """For every open finding with anchors, the tests whose coverage contexts
    executed its cited lines, ranked by how many of those lines each covers.

    Not candidates for `verification_test`, and the first acceptance run said
    so: a defect filed under a green suite is, by construction, executed by
    tests that do not fail on it — these are the tests that exercise the
    defect and stay green, which is an assertion-quality lead (§3: green tests
    are under review too) and the place a regression test belongs. A guard
    that fails on the defect is what `verification_test` names; the harness
    finds it on its own once a fix lands with its test (`added_this_run`)."""
    out: dict = {}
    for f in findings or []:
        if not isinstance(f, dict) or not f.get("id") or not is_open(f):
            continue
        counts: dict = {}
        anchored = 0
        for a in f.get("anchors") or []:
            path = (a or {}).get("path")
            if not path:
                continue
            fj = (files or {}).get(path) or (files or {}).get(str(path).replace("/", "\\"))
            if not fj:
                continue
            anchored += 1
            for c in (fj.get("contexts") or {}).get(str(a.get("line")), []):
                if not c or c == SUBPROCESS_CONTEXT:
                    continue
                t = _test_id_from_context(c, repo)
                if t:
                    counts[t] = counts.get(t, 0) + 1
        if counts:
            ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:5]
            out[str(f["id"])] = {"tests": [t for t, _ in ranked],
                                 "lines_covered": {t: n for t, n in ranked},
                                 "anchored_lines": anchored, "source": "coverage contexts"}
    return out
