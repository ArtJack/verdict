#!/usr/bin/env python3
"""A code-enumerated mutation sweep over named functions of this repository.

`eval/pin_check.py` asks whether the rules we fixed are pinned; its catalogue is
a list somebody wrote. VERDICT-F-65 named the gap: a kill rate over a
hand-written list is a rate over the rules somebody remembered. This asks the
mechanical question instead — take every line of a named function, break it
every way `eval/mutate.py`'s operators know, run the whole suite, and list what
survives — so the denominator is the code, not a memory of it.

The first attempt used mutmut over the same scope. It enumerated 3,638 mutants
across two files, ran 37, and then its worker died on a cache lookup
(`Attribute Mutant.line is required`) with the main process waiting on a queue
forever, output buffered behind a pipe. Sixty lines of our own runner cost
less than diagnosing that, and the mutants it enumerates are the same ones
`eval/mutate.py` already applies to the fixtures.

Every mutant runs in a scratch copy of the working tree (`pin_check.scratch_copy`)
that must first prove it runs its own code; the real tree is never touched.
The suite runs with `-x`, because a kill is a kill at the first red test and
the survivors are what you came for — each survivor costs one full suite.
Classification is `pin_check.classify`: KILLED, SURVIVED, or ERROR (pytest
broke instead of failing, counted apart, never a kill).

Survivors are candidates, not convictions. A survivor is either a rule the suite
does not defend or an equivalent mutant; the sweep cannot tell them apart and
says so. Judge each one by driving the original and the mutant side by side
over the input space, as run 14's lesson demands, before writing a test.

Usage:
    python3 eval/sweep.py --list                                # enumerate, run nothing
    python3 eval/sweep.py --functions _ago,run_date             # the clock only
    python3 eval/sweep.py --json out.json                        # full record
Defaults: harness.py's judgment-adjacent functions plus the dialect table, and
state.outcome_row — the scope VERDICT-F-65's closure was owed on.
"""

from __future__ import annotations

import argparse
import ast
import atexit
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time

EVAL = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(EVAL))
import mutate      # noqa: E402  — the operators and the single-site rewrite
import pin_check   # noqa: E402  — scratch copy, isolation check, classifier

ROOT = EVAL.parent
DEFAULT_SCOPE = {
    "src/verdict_mcp/harness.py": ["_DIALECTS", "duration_regressed", "_counts", "_ago",
                                   "_chosen", "select_test", "verify_findings",
                                   "_apply_verification", "_stamp_outcome", "run_date"],
    "src/verdict_mcp/state.py": ["outcome_row"],
}


def line_ranges(source: str, names: list[str]) -> list[tuple[int, int]]:
    """(first, last) line of each named top-level function or assignment.

    A name may own several ranges — `_DIALECTS` is assigned as a tuple and
    then reassigned compiled — and every one of them is in scope. A name
    that owns none is an error, not a silent empty sweep.
    """
    tree = ast.parse(source)
    wanted, ranges, found = set(names), [], set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            ranges.append((node.lineno, node.end_lineno))
            found.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    ranges.append((node.lineno, node.end_lineno))
                    found.add(target.id)
    missing = wanted - found
    if missing:
        raise SystemExit(f"not a top-level def or assignment, so not swept: {sorted(missing)}")
    return sorted(ranges)


def _code_part(line: str) -> str:
    """The line up to its trailing comment — a `#` outside any string literal."""
    quote = None
    for i, ch in enumerate(line):
        if quote:
            if ch == "\\":
                continue
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def comment_only(before: str, after: str) -> bool:
    """A mutant that changes nothing outside a trailing comment is not a
    mutant: the first sweep's first two "survivors" were `0` -> `1` inside
    `# Failed: 0, Passed: 5, Total: 5` beside the dotnet dialect, 95 seconds
    each to learn that a comment does not run."""
    return _code_part(before) == _code_part(after)


def enumerate_scope(root: pathlib.Path, scope: dict) -> list[dict]:
    """Every single-site mutant inside the named ranges, tagged with its file."""
    out = []
    for rel, names in scope.items():
        source = (root / rel).read_text(encoding="utf-8")
        ranges = line_ranges(source, names)
        for m in mutate.generate(source):
            if comment_only(m["before"], m["after"]):
                continue
            if any(a <= m["line"] <= b for a, b in ranges):
                out.append({**m, "path": rel, "id": f"{rel.rsplit('/', 1)[-1]}:{m['line']}:{m['operator']}:{len(out) + 1}"})
    return out


def run_suite(cmd: list[str], cwd: pathlib.Path, env: dict):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, env=env)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--functions", default="",
                    help="comma-separated names to sweep (default: the F-65 scope)")
    ap.add_argument("--path", default="", help="file the --functions live in")
    ap.add_argument("--list", action="store_true", help="enumerate and stop")
    ap.add_argument("--json", default="", help="write the full record here")
    ap.add_argument("--limit", type=int, default=0, help="run at most N mutants")
    args = ap.parse_args(argv)

    scope = DEFAULT_SCOPE
    if args.functions:
        scope = {args.path or "src/verdict_mcp/harness.py": args.functions.split(",")}
    mutants = enumerate_scope(ROOT, scope)
    if args.limit:
        mutants = mutants[:args.limit]
    if args.list:
        for m in mutants:
            print(f"{m['id']:44} {m['before'][:60]!s}  ->  {m['after'][:60]}")
        print(f"\n{len(mutants)} mutants over {sum(len(v) for v in scope.values())} names")
        return 0

    tree = pin_check.scratch_copy(ROOT)
    atexit.register(shutil.rmtree, tree, True)
    env = pin_check.scratch_env(tree)
    elsewhere = pin_check.runs_its_own_code(tree, env)
    if elsewhere:
        print(f"ISOLATION FAILED: the scratch copy imports {elsewhere}", file=sys.stderr)
        return 1
    suite = [*pin_check.SUITE, "-x"]
    pin_check.sweep(tree)
    started = time.monotonic()
    control = run_suite(suite, tree, env)
    if control.returncode != 0:
        print("CONTROL FAILED — the suite is red before any mutation.", file=sys.stderr)
        print(control.stdout[-1500:], file=sys.stderr)
        return 1
    print(f"scratch copy: {tree} · runs its own code · control green in "
          f"{time.monotonic() - started:.0f}s · {len(mutants)} mutants\n", flush=True)

    record, survivors, broken = [], [], []
    for i, m in enumerate(mutants, 1):
        path = tree / m["path"]
        original = path.read_text(encoding="utf-8")
        pin_check.write_atomic(path, mutate.apply_to(original, m))
        pin_check.sweep(tree)
        t0 = time.monotonic()
        try:
            result = run_suite(suite, tree, env)
        finally:
            pin_check.write_atomic(path, original)
        outcome = pin_check.classify(result.returncode, result.stdout)
        secs = time.monotonic() - t0
        record.append({**m, "outcome": outcome, "seconds": round(secs, 1)})
        tag = {"killed": "KILLED  ", "survived": "SURVIVED", "error": "ERROR   "}[outcome]
        print(f"[{i:3}/{len(mutants)}] {tag} {m['id']:40} {secs:5.0f}s  "
              f"{m['before'][:50]} -> {m['after'][:50]}", flush=True)
        (survivors if outcome == "survived" else broken if outcome == "error" else []).append(m)

    killed = len(record) - len(survivors) - len(broken)
    print(f"\n{killed} of {len(record) - len(broken)} killed by the whole suite"
          + (f" ({len(broken)} not measured: pytest broke instead of failing)" if broken else ""))
    if survivors:
        print("\nsurvivors — each is a rule the suite does not defend OR an equivalent mutant; "
              "drive both versions over the input space before writing a test:")
        for m in survivors:
            print(f"  · {m['path']}:{m['line']} [{m['operator']}]  {m['before']}  ->  {m['after']}")
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(record, indent=1, ensure_ascii=False) + "\n",
                                           encoding="utf-8")
    return 1 if survivors or broken else 0


if __name__ == "__main__":
    sys.exit(main())
