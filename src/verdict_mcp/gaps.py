"""Assertion gaps — the code a passing suite executes without checking.

Measured 2026-10-17: on fava the known defect sat in code the suite runs at ~100% line
coverage without asserting the case. Line coverage cannot see that; a mutant can. For each
function on a money or auth path that tests execute, a few mechanical mutants (a comparison
flipped, `and` for `or`, a condition negated, `+` for `-`, 0 for 1) go into a fresh worktree,
one at a time, and only the tests whose coverage contexts executed that line are run against
it. A mutant those tests do not kill marks a line the suite executes and does not check — an
assertion gap, the place a defect hides behind a green suite.

Two controls keep the census honest. The selected tests must pass on the unmutated tree, or
the function is skipped (the environment, not the code, would be failing). And a canary — a
line that raises — must make them fail, or the fresh tree is not what they import, and every
mutant would survive for that reason alone; the function is skipped and the census says so.

Opt-in (`assertion_gaps: on` in the profile, with `test_one_cmd` and `coverage_suite_cmd`):
it costs suite time, never model time, and stops at its budget.
"""

from __future__ import annotations

import ast
import os
import re
import shlex
import subprocess
import time
from pathlib import Path

try:
    from .readfirst import risk_of
    from .replay import ORIGINAL_ENV, _fresh_checkout, _guard_dir, _outside_quotes, _remove_checkout
except ImportError:  # executed as a bare script
    from readfirst import risk_of
    from replay import ORIGINAL_ENV, _fresh_checkout, _guard_dir, _outside_quotes, _remove_checkout

BUDGET_S = 480
MAX_FUNCTIONS = 16
LINES_PER_FUNCTION = 3
MUTANTS_PER_LINE = 2
TESTS_PER_LINE = 6
RUN_TIMEOUT_S = 120

# Behaviour-changing first: a comparison, a boolean, a condition — then arithmetic and constants.
# Whole-statement mutants (`_structural`) come before all of these on a line that is one.
OPERATORS = [
    ("comparison", r">=", ">"),
    ("comparison", r"<=", "<"),
    ("comparison", r"(?<![<>=!])<(?![=<])", "<="),
    ("comparison", r"(?<![<>=!-])>(?![=>])", ">="),
    ("comparison", r"==", "!="),
    ("comparison", r"!=", "=="),
    ("boolean", r"\band\b", "or"),
    ("boolean", r"\bor\b", "and"),
    ("condition", r"^(\s*)(if|elif|while) (.+):\s*$", r"\1\2 not (\3):"),
    ("arithmetic", r"(?<=[\w)\]]) \+ ", " - "),
    ("arithmetic", r"(?<=[\w)\]]) - ", " + "),
    ("arithmetic", r"(?<=[\w)\]]) \* (?!\*)", " / "),
    ("constant", r"(?<![\w.])0(?![\w.])", "1"),
    ("constant", r"(?<![\w.])1(?![\w.])", "0"),
    ("constant", r"\bTrue\b", "False"),
    ("constant", r"\bFalse\b", "True"),
]
_SKIP = re.compile(r'^\s*(#|@|"""|\'\'\'|from |import |def |async def |class |return\s*$|pass\s*$|\)|\]|\})')


def _structural(line: str) -> list[tuple[str, str]]:
    """Whole-statement mutants: a call made for its effect, an attribute set, or a raise becomes
    `pass`; a returned value becomes `None`. The first asks whether anything checks that the
    effect happened — a save, a status change, a field written — which no operator inside an
    expression can ask."""
    stripped = line.strip()
    indent = line[:len(line) - len(line.lstrip())]
    try:
        node = ast.parse(stripped).body[0]
    except (SyntaxError, IndexError, ValueError):
        return []
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        return [("statement", indent + "pass")]
    if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if any(isinstance(t, ast.Attribute) for t in targets):
            return [("statement", indent + "pass")]
    if isinstance(node, ast.Raise):
        return [("statement", indent + "pass")]
    if isinstance(node, ast.Return) and node.value is not None \
            and not (isinstance(node.value, ast.Constant) and node.value.value is None):
        return [("return", indent + "return None")]
    return []


def mutants_of(line: str, cap: int = MUTANTS_PER_LINE) -> list[dict]:
    """Up to `cap` single-site mutants of one source line, never inside a string: a whole-statement
    mutant first when the line is one, then the expression operators."""
    if _SKIP.match(line) or not line.strip():
        return []
    masked = _outside_quotes(line)
    out, seen = [], set()
    for name, mutated in _structural(line):
        seen.add(mutated)
        out.append({"operator": name, "before": line.strip(), "after": mutated})
    for name, pattern, repl in OPERATORS:
        flags = re.M if name == "condition" else 0
        m = re.search(pattern, masked, flags)
        if not m:
            continue
        if name == "condition":
            mutated = re.sub(pattern, repl, line, count=1, flags=flags)
        else:
            mutated = line[:m.start()] + repl + line[m.end():]
        if mutated == line or mutated in seen:
            continue
        seen.add(mutated)
        out.append({"operator": name, "before": line.strip(), "after": mutated})
        if len(out) >= cap:
            break
    return out


_ADMIN_UI = ("dashboard", "admin", "templatetags", "migrations")


def _rank(path: str, name: str, globs) -> tuple:
    """Money logic first: a function whose own name is on a risk path, outside admin UI; then
    one whose file is; admin UI last. Measured 2026-10-17: ranked by tested lines alone, the
    budget went on admin list filters while a discount calculation waited."""
    admin = any(seg in _ADMIN_UI for seg in path.replace("\\", "/").split("/"))
    named = bool(risk_of("", name, None)) if not globs else False
    return (admin, not named)


def candidates(files: dict, globs=None, changed=None, is_test=lambda p: False,
               test_id=lambda c: c, cap: int = MAX_FUNCTIONS) -> list[dict]:
    """Functions on a risk path that tests execute, with their tested lines and the tests that
    ran each — money logic first (`_rank`), the most-tested first within a rank."""
    out = []
    for path, f in (files or {}).items():
        p = str(path).replace("\\", "/")
        if is_test(p):
            continue
        contexts = (f or {}).get("contexts") or {}
        for name, fb in ((f or {}).get("functions") or {}).items():
            risk = risk_of(p, name, globs) if name else ""
            if not risk:
                continue
            tested = {}
            for ln in (fb or {}).get("executed_lines") or []:
                if changed is not None and ln not in changed.get(p, ()):
                    continue
                ids = sorted({t for c in contexts.get(str(ln), []) if c for t in [test_id(c)] if t})
                if ids:
                    tested[ln] = ids
            if tested:
                out.append({"path": p, "function": name, "risk": risk, "lines": tested})
    out.sort(key=lambda c: (*_rank(c["path"], c["function"], globs), -len(c["lines"]), c["path"], c["function"]))
    return out[:cap]


def _parses(lines) -> bool:
    try:
        ast.parse("".join(lines))
    except (SyntaxError, ValueError):
        return False
    return True


def _env(repo: Path, scratch: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(_guard_dir(scratch.parent)), str(scratch / "src"), str(scratch)]
                                        + ([os.environ["PYTHONPATH"]] if os.environ.get("PYTHONPATH") else []))
    env[ORIGINAL_ENV] = os.pathsep.join(dict.fromkeys([str(repo.resolve()), str(repo)]))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["GIT_NO_LAZY_FETCH"] = "1"
    return env


def _quote(test_id: str) -> str:
    """A test id for the profile's shell: cmd.exe reads double quotes, never single ones."""
    return ('"' + test_id.replace('"', '') + '"') if os.name == "nt" else shlex.quote(test_id)


def _run_tests(cmd: str, ids, scratch: Path, env: dict, detail: list | None = None) -> str:
    """`pass`, `fail` (a test failed), or `error` (nothing ran, a usage error, a timeout).
    `detail`, when given, receives the last lines of the output."""
    command = cmd.replace("{id}", " ".join(_quote(i) for i in ids))
    try:
        proc = subprocess.run(command, shell=True, cwd=str(scratch), env=env, capture_output=True,
                              text=True, errors="replace", timeout=RUN_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        if detail is not None:
            detail.append(f"timed out after {RUN_TIMEOUT_S}s")
        return "error"
    if detail is not None:
        tail = [ln for ln in (proc.stdout + proc.stderr).splitlines()
                if ln.startswith(("FAILED", "ERROR")) or " passed" in ln or " failed" in ln]
        detail.append("; ".join(tail[-3:])[:240] or f"exit {proc.returncode}")
    if proc.returncode == 0:
        return "pass"
    if proc.returncode == 1:
        return "fail"
    return "error"            # pytest 2 interrupted, 3 internal, 4 usage, 5 nothing collected


def clean_tests(cmd: str, ids, scratch: Path, env: dict, detail: list) -> list:
    """The tests that pass on the clean tree: the set at once, and when it does not pass, each
    one alone — a functional test that needs a built asset the fresh tree lacks, or one that
    depends on the order the suite runs in, must not mark the function as unmeasurable."""
    if _run_tests(cmd, ids, scratch, env, detail) == "pass":
        return list(ids)
    return [i for i in ids if _run_tests(cmd, [i], scratch, env) == "pass"]


def census(repo: Path, files: dict, test_one_cmd: str, globs=None, changed=None,
           is_test=lambda p: False, test_id=lambda c: c, budget_s: int = BUDGET_S) -> dict:
    """The assertion-gap census: survivors, with the tests that ran them and stayed green."""
    started = time.monotonic()
    if not test_one_cmd or "{id}" not in test_one_cmd:
        return {"status": "unavailable", "reason": "needs test_one_cmd with {id} in the profile"}
    targets = candidates(files, globs, changed, is_test, test_id)
    if not targets:
        return {"status": "measured", "functions": 0, "mutants": 0, "killed": 0, "survived": [],
                "note": "no function on a risk path is executed by a test"}
    scratch, sha, problem = _fresh_checkout(repo)
    if scratch is None:
        return {"status": "unavailable", "reason": problem}
    env = _env(repo, scratch)
    survived, killed, errors, skipped, tried = [], 0, 0, [], 0
    try:
        for t in targets:
            if time.monotonic() - started > budget_s:
                skipped.append(f"{t['path']}::{t['function']} (budget)")
                continue
            target = scratch / t["path"]
            try:
                original = target.read_text(encoding="utf-8")
            except OSError:
                skipped.append(f"{t['path']}::{t['function']} (not in the fresh tree)")
                continue
            src = original.splitlines(keepends=True)
            first = min(t["lines"])
            detail: list = []
            ids = clean_tests(test_one_cmd, t["lines"][first][:TESTS_PER_LINE], scratch, env, detail)
            if not ids:
                skipped.append(f"{t['path']}::{t['function']} (its tests do not pass on the clean tree: "
                               f"{detail[0] if detail else 'no output'})")
                continue
            dropped = set(t["lines"][first][:TESTS_PER_LINE]) - set(ids)
            indent = re.match(r"\s*", src[first - 1]).group(0)
            canary = src[:first - 1] + [f"{indent}raise AssertionError('verdict canary')\n"] + src[first - 1:]
            if not _parses(canary):
                skipped.append(f"{t['path']}::{t['function']} (no line to put a canary on)")
                continue
            target.write_text("".join(canary), encoding="utf-8")
            verdict = _run_tests(test_one_cmd, ids, scratch, env)
            target.write_text(original, encoding="utf-8")
            if verdict != "fail":
                skipped.append(f"{t['path']}::{t['function']} (a canary did not fail its tests: the "
                               "fresh tree may not be what they import)")
                continue
            lines = sorted(t["lines"], key=lambda ln: -len(t["lines"][ln]))[:LINES_PER_FUNCTION * 3]
            used = 0
            for ln in lines:
                if used >= LINES_PER_FUNCTION or time.monotonic() - started > budget_s:
                    break
                ms = mutants_of(src[ln - 1].rstrip("\n"))
                if not ms:
                    continue
                used += 1
                for m in ms:
                    mutated = src[:ln - 1] + [m["after"] + "\n"] + src[ln:]
                    if not _parses(mutated):
                        continue                      # a line inside a bracket, not a statement
                    target.write_text("".join(mutated), encoding="utf-8")
                    line_ids = [i for i in t["lines"][ln] if i not in dropped][:TESTS_PER_LINE]
                    if not line_ids:
                        continue
                    verdict = _run_tests(test_one_cmd, line_ids, scratch, env)
                    target.write_text(original, encoding="utf-8")
                    tried += 1
                    if verdict == "fail":
                        killed += 1
                    elif verdict == "pass":
                        survived.append({"path": t["path"], "function": t["function"], "risk": t["risk"],
                                         "line": ln, "operator": m["operator"], "before": m["before"],
                                         "after": m["after"].strip(), "tests": line_ids})
                    else:
                        errors += 1
    finally:
        _remove_checkout(repo, scratch)
    return {"status": "measured", "checkout": sha, "functions": len(targets), "mutants": tried,
            "killed": killed, "errors": errors, "survived": survived,
            **({"skipped": skipped} if skipped else {}),
            "duration_s": round(time.monotonic() - started, 1),
            "reading": ("a survivor is a line the listed tests execute and do not check: a mechanical "
                        "change there leaves them green. A lead for where to read, never a finding.")}
