#!/usr/bin/env python3
"""Are the rules this project claims to have pinned actually pinned?

Not `eval/mutate.py`, which asks what Verdict *misses* on a fixture. This asks a
question about this repository's own tests: **take a rule we fixed, put the
defect back, and does the suite notice?** A rule nothing notices is a rule that
can be deleted by accident, and a green suite says the same thing either way.

It exists because a published number was wrong. v0.74.0's changelog said
"21 mutants, 21 killed", and the run that audited it found two things
(VERDICT-F-57):

  1. **Every mutant ran against one hand-named test.** The mutant and the test
     came from the same reading of the same finding, so the pair could only
     ever confirm a rule already watched. Here every mutant runs against the
     WHOLE suite, which is the claim a reader actually makes when they see a
     kill rate.
  2. **The scripts were not in the repository.** They lived in a scratch
     directory, so nobody could reproduce the number — while the eval half of
     the very same release archived its artifact. The catalogue is now
     `eval/pinned_mutants.json`, beside the claim it supports.

And a third thing, which is why the catalogue grew: every mutant chosen for
0.74.0 changed a function *body*. Deleting the only CALL SITE of
`_drop_bytecode` left all 721 tests passing. Call-site mutants are now in the
catalogue as their own class, because "the code is right" and "the code runs"
are different claims.

Not a CI job. One suite run per mutant, roughly two seconds of thinking and a
lot of waiting — a periodic exam, like the mutmut campaign in eval/README.md.

**While this runs, the working tree is not yours.** Every mutant is applied to
the real files and reverted after the suite finishes, so anything else that
reads the tree meanwhile sees a defect that is not there. That happened during
this tool's own development twice: a second instance read a failure the first
had caused, and a hand-run probe reported a guard bug that was simply the
mutant of the moment. The lock below stops the first; nothing can stop the
second except not doing it. Run this when you are not editing.

Usage:
    python3 eval/pin_check.py                    # every mutant
    python3 eval/pin_check.py --filter tar       # substring match on the label
    python3 eval/pin_check.py --list             # names only, no runs
"""

import argparse
import atexit
import io
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "eval" / "pinned_mutants.json"
SUITE = ["uv", "run", "--group", "dev", "pytest", "-q", "-p", "no:cacheprovider",
         "-o", "addopts="]


def sweep():
    """CPython validates bytecode on mtime-in-whole-seconds plus size, so two
    same-size mutants inside one second run the first one's code. This is the
    same discipline §3 of the contract asks of the agent (VERDICT-F-50)."""
    for cache in ROOT.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def run_suite(env):
    return subprocess.run(SUITE, cwd=ROOT, capture_output=True, text=True, env=env)


class OnlyOne:
    """One mutation run at a time, because they share a working tree.

    Two instances started together here: one mutated the README while the other
    was running the suite, and the second read a failure it had not caused.
    Mutation is a whole-tree operation and there is exactly one tree.
    """

    def __init__(self, lock):
        self.lock = lock
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise SystemExit(
                f"another pin_check is running (lock: {lock}). Wait for it, or "
                f"remove the lock if you are sure nothing else is mutating the tree.")
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        atexit.register(self.release)

    def release(self):
        try:
            os.unlink(self.lock)
        except OSError:
            pass


class Restorer:
    """Put every mutated file back, whatever happens to this process.

    `try/finally` covers an exception; it does not cover Ctrl-C, a `pkill`, or a
    harness timeout — and one of those left a mutation in the working tree
    during this tool's own development, where it read as a test failure rather
    than as a mutant nobody had reverted. A run that can leave the repository
    broken is worse than no run.
    """

    def __init__(self):
        self._saved = {}
        atexit.register(self.restore)
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError, AttributeError):
                pass    # not the main thread, or the platform lacks it

    def hold(self, path, text):
        self._saved[path] = text

    def restore(self):
        while self._saved:
            path, text = self._saved.popitem()
            try:
                io.open(path, "w", encoding="utf-8").write(text)
            except OSError as exc:
                print(f"COULD NOT RESTORE {path}: {exc}", file=sys.stderr)
        sweep()

    def _on_signal(self, signum, _frame):
        print(f"\ninterrupted (signal {signum}) — restoring the tree", file=sys.stderr)
        self.restore()
        raise SystemExit(130)   # atexit still runs, so the lock is released


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--filter", default="", help="substring match on the label")
    ap.add_argument("--list", action="store_true", help="print the catalogue and stop")
    args = ap.parse_args()

    mutants = json.loads(CATALOGUE.read_text(encoding="utf-8"))
    if args.filter:
        mutants = [m for m in mutants if args.filter.lower() in m["label"].lower()]
    if args.list:
        for m in mutants:
            print(f"{m['path']:34} {m['label']}")
        return 0
    if not mutants:
        print("no mutants matched", file=sys.stderr)
        return 2

    OnlyOne(str(ROOT / ".pin_check.lock"))   # held until the process exits
    keeper = Restorer()
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    # Control the instrument before trusting it: a suite that is already red
    # kills every mutant and proves nothing.
    sweep()
    control = run_suite(env)
    if control.returncode != 0:
        print("CONTROL FAILED — the suite is red before any mutation.", file=sys.stderr)
        print(control.stdout[-2000:], file=sys.stderr)
        return 1
    print(f"control: suite green · {len(mutants)} mutants to apply\n")

    survivors, equivalents = [], []
    for i, m in enumerate(mutants, 1):
        path = ROOT / m["path"]
        src = path.read_text(encoding="utf-8")
        hits = src.count(m["old"])
        if hits != 1:
            print(f"[{i:2}/{len(mutants)}] STALE    {m['label']}  (anchor matched {hits})")
            survivors.append(m["label"] + "  [stale anchor]")
            continue
        keeper.hold(path, src)
        io.open(path, "w", encoding="utf-8").write(src.replace(m["old"], m["new"]))
        sweep()
        try:
            result = run_suite(env)
        finally:
            keeper.restore()
        if result.returncode != 0:
            print(f"[{i:2}/{len(mutants)}] KILLED   {m['label']}")
        elif m.get("equivalent"):
            # Documented, not hidden: a mutant that provably cannot change a
            # verdict is a question with no answer, and scoring it as a miss
            # would push someone to write a test that can only ever pass.
            print(f"[{i:2}/{len(mutants)}] EQUIV    {m['label']}")
            equivalents.append(m["label"])
        else:
            print(f"[{i:2}/{len(mutants)}] SURVIVED {m['label']}")
            survivors.append(m["label"])

    killed = len(mutants) - len(survivors) - len(equivalents)
    scored = len(mutants) - len(equivalents)
    print(f"\n{killed} of {scored} killed by the whole suite"
          + (f" ({len(equivalents)} equivalent, excluded)" if equivalents else ""))
    if survivors:
        print("\nsurvivors — each is a rule the suite does not defend:")
        for s in survivors:
            print(f"  · {s}")
    return 1 if survivors else 0


if __name__ == "__main__":
    sys.exit(main())
