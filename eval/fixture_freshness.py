#!/usr/bin/env python3
"""Tamper-evidence for the delta fixture. Stdlib only.

`eval/fixtures/pricer-delta.diff` is the committed record of how rev-A differs
from rev-B. If either fixture drifts, the seeded eval quietly starts measuring
something other than what its answer key describes — so the diff is regenerated
and compared, and any difference fails.

The obvious implementation was `git diff --no-index pricer pricer_rev_b`, and it
was wrong in a way that took a QA run to notice: **`--no-index` does not honour
`.gitignore`.** Run the fixture's own tests once — which the eval does, which
any developer does — and `__pycache__/` appears, the regenerated diff grows by
dozens of lines, and the gate reports tampering of a file nobody touched. A
tamper alarm that fires on `__pycache__` is a tamper alarm people learn to
ignore, which is worse than not having one.

So the comparison runs over **tracked files only**, copied to a scratch tree:
`git ls-files` is the same definition of "the fixture" that the repository uses,
so build artifacts cannot enter and a genuine edit — staged or not — still
shows up.
"""

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

EVAL = Path(__file__).resolve().parent
REPO = EVAL.parent
PAIR = ("eval/fixtures/pricer", "eval/fixtures/pricer_rev_b")
ANCHOR = EVAL / "fixtures" / "pricer-delta.diff"


def _git(args, cwd, check=True):
    proc = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode not in (0, 1):   # diff exits 1 when files differ
        raise SystemExit(f"fixture_freshness: git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def regenerate() -> str:
    """The rev-A → rev-B diff, reproducing the fixture rather than its text.

    `copyfile` copies bytes: it drops the mode and follows symlinks, so an
    executable bit flipped or a symlink swapped for a regular file reproduced
    identically and the gate saw nothing. `copy2(follow_symlinks=False)` carries
    both, and `git diff` reports them as the mode and type changes they are
    (VERDICT-F-13).
    """
    listed = _git(["ls-files", "-z", *PAIR], REPO).split("\0")
    tracked = [p for p in listed if p]
    if not tracked:
        raise SystemExit("fixture_freshness: no tracked files under the fixture pair — "
                         "either the paths moved or this is not the repository root")
    # A file git knows about and the working tree does not is a broken fixture,
    # not a crash. It used to reach `copyfile` and traceback.
    missing = [rel for rel in tracked if not (REPO / rel).exists()
               and not (REPO / rel).is_symlink()]
    if missing:
        raise SystemExit("fixture_freshness: tracked file(s) missing from the working "
                         "tree, so the fixture cannot be reproduced: " + ", ".join(missing))
    # Untracked files under the fixture are invisible to a diff built from
    # `ls-files`, so an eval run would read a fixture the anchor never described.
    # `--exclude-standard` keeps .gitignore'd scratch out of it.
    planted = [p for p in _git(["ls-files", "-z", "--others", "--exclude-standard", *PAIR],
                               REPO).split("\0") if p]
    if planted:
        raise SystemExit("fixture_freshness: untracked file(s) under the fixture pair, "
                         "which no committed diff can describe: " + ", ".join(planted))
    work = Path(tempfile.mkdtemp(prefix="verdict-freshness-"))
    try:
        for rel in tracked:
            dest = work / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest, follow_symlinks=False)
        return _git(["diff", "--no-index", "pricer", "pricer_rev_b"],
                    work / "eval" / "fixtures", check=False)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    fresh = regenerate()
    committed = ANCHOR.read_text(encoding="utf-8")
    if fresh == committed:
        print(f"fixture_freshness: OK — {ANCHOR.name} still describes the fixture pair "
              f"({len(committed.splitlines())} lines)")
        return 0
    print(f"fixture_freshness: {ANCHOR.name} no longer describes the fixture pair.\n"
          f"  committed: {len(committed.splitlines())} lines\n"
          f"  regenerated: {len(fresh.splitlines())} lines\n"
          "  Either a fixture was edited without refreshing the diff, or the diff was "
          "edited without the fixture. Regenerate with:\n"
          "    python3 eval/fixture_freshness.py --write", file=sys.stderr)
    return 1


if __name__ == "__main__":
    if "--write" in sys.argv[1:]:
        ANCHOR.write_text(regenerate(), encoding="utf-8")
        print(f"fixture_freshness: rewrote {ANCHOR}")
        sys.exit(0)
    sys.exit(main())
