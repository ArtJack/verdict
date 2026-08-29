#!/usr/bin/env python3
"""Mutation census — the denominator for measuring what Verdict *misses*.

The eval fixtures measure precision against a hand-authored answer key: eight
defects someone wrote on purpose, which the prompt has effectively been tuned
against. They say nothing about recall on defects nobody anticipated.

So: take a module that is *correct*, break it one line at a time with
mechanical operators, and ask two questions of each mutant.

  1. Does the suite kill it?  Run the tests. A mutant the suite kills is a
     defect the project already defends against — the tester should report the
     red test, but finding it takes no insight.

  2. Does it change behaviour at all?  Run the fixture's `probe.py` against
     clean and mutant and compare fingerprints. Identical output everywhere
     means an *equivalent mutant*: the source changed, the program did not. It
     is not a defect, and scoring a tester for missing it would be scoring a
     question with no answer.

What is left — survived the suite, provably changed behaviour — is the
population that matters: real defects the tests do not catch, which can only be
found by reading. That is the honest denominator for a recall number, and
`eval/run_mutation.py` runs the agent against a sample of it.

Usage:
    python3 eval/mutate.py --fixture pricer_clean [--module pricer.py] [--json]
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parent

# One site at a time, source-level, deterministic. Each operator is a pattern
# and a rewrite; every match in the module is its own mutant.
OPERATORS = [
    ("comparison", r">=", "> "),
    ("comparison", r"(?<![<>=!])<(?![=<])", "<="),
    ("comparison", r"(?<![<>=!])>(?![=>])", ">="),
    ("comparison", r"<=", "< "),
    ("comparison", r"==", "!="),
    ("arithmetic", r"(?<![*\w])\*(?!\*)", "/"),
    ("arithmetic", r"(?<=\w) \+ ", " - "),
    ("arithmetic", r"(?<=\w) - ", " + "),
    ("constant", r"\b0\.9\b", "0.95"),
    ("constant", r"\b0\.12\b", "0.1"),
    ("constant", r"\b10\b", "11"),
    ("constant", r"\b0\b(?!\.)", "1"),
    # Whole-condition mutations: the classic way to ask "is this guard tested
    # at all?" — the match spans the condition, so the rewrite is literal.
    ("condition", r"\bif .+:$", "if False:"),
    ("condition", r"\bif .+:$", "if True:"),
    ("rounding", r"ROUND_HALF_UP", "ROUND_HALF_EVEN"),
    ("rounding", r'Decimal\("0\.01"\)', 'Decimal("0.1")'),
]

# Lines that are documentation or imports carry no behaviour worth breaking;
# mutating them produces noise, not defects.
_SKIP = re.compile(r'^\s*(#|"""|\'\'\'|from |import )')


def generate(source: str):
    """Every single-site mutant of this source, as (operator, line_no, before, after)."""
    mutants, seen = [], set()
    for i, line in enumerate(source.splitlines(), start=1):
        if _SKIP.match(line) or not line.strip():
            continue
        for name, pattern, replacement in OPERATORS:
            for m in re.finditer(pattern, line):
                mutated = line[:m.start()] + replacement + line[m.end():]
                if mutated == line:
                    continue
                key = (i, mutated)
                if key in seen:
                    continue
                seen.add(key)
                mutants.append({
                    "operator": name, "line": i,
                    "before": line.strip(), "after": mutated.strip(),
                })
    for n, mutant in enumerate(mutants, start=1):
        mutant["id"] = f"M{n:02d}"
    return mutants


def apply_to(source: str, mutant: dict) -> str:
    lines = source.splitlines(keepends=True)
    idx = mutant["line"] - 1
    ending = "\n" if lines[idx].endswith("\n") else ""
    indent = re.match(r"\s*", lines[idx]).group(0)
    lines[idx] = indent + mutant["after"] + ending
    return "".join(lines)


def _run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120)


def census(fixture_dir: Path, module: str, python: str) -> dict:
    source = (fixture_dir / module).read_text(encoding="utf-8")
    mutants = generate(source)
    work = Path(tempfile.mkdtemp(prefix="verdict-mutants-"))
    clean = work / "clean"
    shutil.copytree(fixture_dir, clean)

    baseline = _run([python, "-m", "pytest", "-q"], clean)
    if baseline.returncode != 0:
        raise SystemExit(
            f"the mutation base must be green before anything is broken:\n{baseline.stdout[-2000:]}")
    probe = clean / "probe.py"
    clean_print = _run([python, str(probe)], clean).stdout if probe.is_file() else None

    for mutant in mutants:
        trial = work / mutant["id"]
        shutil.copytree(fixture_dir, trial)
        (trial / module).write_text(apply_to(source, mutant), encoding="utf-8")

        suite = _run([python, "-m", "pytest", "-q"], trial)
        mutant["killed_by_suite"] = suite.returncode != 0

        if clean_print is None:
            mutant["behaviour_changed"] = None
        else:
            out = _run([python, str(trial / "probe.py")], trial)
            mutant["behaviour_changed"] = (out.stdout != clean_print) or out.returncode != 0
        shutil.rmtree(trial, ignore_errors=True)

    shutil.rmtree(work, ignore_errors=True)

    # Disjoint buckets, killed first: a mutant the suite catches is out of the
    # recall population whatever the probe says about it.
    for m in mutants:
        m["bucket"] = ("killed" if m["killed_by_suite"]
                       else "equivalent" if m["behaviour_changed"] is False
                       else "survivor")
    survivors = [m for m in mutants if m["bucket"] == "survivor"]

    # A mutant the suite killed but the probe could not see is a hole in the
    # *oracle*, not a result: the same blindness would silently drop a real
    # survivor out of the denominator. Surfaced rather than swallowed — the
    # first grid had no negative prices, and removing a negative-price guard
    # looked like a no-op.
    probe_gaps = [m["id"] for m in mutants
                  if m["killed_by_suite"] and m["behaviour_changed"] is False]
    return {
        "fixture": fixture_dir.name,
        "module": module,
        "mutants": len(mutants),
        "killed_by_suite": sum(1 for m in mutants if m["bucket"] == "killed"),
        "equivalent": sum(1 for m in mutants if m["bucket"] == "equivalent"),
        "survivors": len(survivors),
        "survivor_ids": [m["id"] for m in survivors],
        "probe_blind_to": probe_gaps,
        "detail": mutants,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fixture", default="pricer_clean")
    ap.add_argument("--module", default="pricer.py")
    ap.add_argument("--python", default=sys.executable)
    ap.add_argument("--json", action="store_true", help="full census as JSON")
    args = ap.parse_args(argv)

    result = census(EVAL_DIR / "fixtures" / args.fixture, args.module, args.python)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"{result['mutants']} mutants of {result['fixture']}/{result['module']}")
    print(f"  {result['killed_by_suite']:>3} killed by the suite")
    print(f"  {result['equivalent']:>3} equivalent (source changed, behaviour did not)")
    print(f"  {result['survivors']:>3} survivors that change behaviour "
          f"— defects the tests do not catch")
    if result["probe_blind_to"]:
        print(f"  note: the probe could not see {len(result['probe_blind_to'])} mutant(s) "
              f"the suite killed ({', '.join(result['probe_blind_to'])}) — its input grid "
              f"has a hole, and the same hole would drop a real survivor")
    print()
    for m in result["detail"]:
        if m["bucket"] != "survivor":
            continue
        print(f"  {m['id']}  line {m['line']:>2}  {m['operator']:<10} {m['before']}")
        print(f"       {'':>16}{'':<10} -> {m['after']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
