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

Three outcomes per mutant, read from pytest's summary line rather than its exit
code: KILLED (a test failed), SURVIVED (the suite stayed green), and ERROR —
pytest exited without a failed test, which is a broken collection or a usage
error, not a defended rule (VERDICT-F-68). An ERROR is reported apart, kept
out of the denominator, and fails the run, because a number that silently
counted it as a kill would be the wrong number.

Not a CI job. One suite run per mutant, roughly two seconds of thinking and a
lot of waiting — a periodic exam, like the mutmut campaign in eval/README.md.

**The working tree is never touched.** Every mutant is applied to a scratch
copy of the tree — tracked and untracked-but-not-ignored files, so what is
about to be committed is what gets measured — and the suite runs there with
the copy's `src/` ahead of the editable install. The copy has to prove it
runs its own code before anything is trusted: an `import verdict_mcp` that
resolves outside the scratch aborts the run, because a re-injection that
measured the original checkout is a thing that happened here (run 9), and
the number it produces is confident and wrong. In-tree mutation was the
first design, and it cost twice: a second instance read a failure the first
had caused, and an interrupted run left `harness.py` 2286 lines shorter.
`--in-tree` keeps that mode for a tree that is not a git checkout; it holds
a lock and restores every file, and while it runs the tree is not yours.

Usage:
    python3 eval/pin_check.py                    # every mutant, in a scratch copy
    python3 eval/pin_check.py --filter tar       # substring match on the label
    python3 eval/pin_check.py --list             # names only, no runs
    python3 eval/pin_check.py --in-tree          # the old way: mutate the real files
"""

from __future__ import annotations

import argparse
import atexit
import io
import json
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
CATALOGUE = ROOT / "eval" / "pinned_mutants.json"
# `--project` pins the environment to the real checkout however the cwd moves;
# PYTHONPATH then puts the scratch copy's own source ahead of it.
SUITE = ["uv", "run", "--project", str(ROOT), "--group", "dev", "pytest", "-q",
         "-p", "no:cacheprovider", "-o", "addopts="]
IMPORT_CHECK = ["uv", "run", "--project", str(ROOT), "--group", "dev", "python", "-c",
                "import verdict_mcp; print(verdict_mcp.__file__)"]


def write_atomic(path, text):
    """Replace a file's contents without ever leaving it half-written.

    `open(path, "w").write(...)` truncates first, so a kill between the
    truncate and the flush leaves an EMPTY SOURCE FILE — measured, on this
    repository, when a whole-catalogue run was interrupted: `harness.py` came
    back 2286 lines shorter and the lock had already been released, so nothing
    said the tree was broken. The rest of this project writes state through a
    temp file and `os.replace` for exactly this reason (`harness._atomic_write`);
    the tool that rewrites every source file in the repository was the one
    place that did not.

    With the swap atomic, an interrupted run leaves either the original or the
    complete mutant, and a kill that outruns the restore leaves the lock behind
    as the signpost it is meant to be.
    """
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".pin_check.tmp")
    with io.open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def sweep(root=None):
    """CPython validates bytecode on mtime-in-whole-seconds plus size, so two
    same-size mutants inside one second run the first one's code. This is the
    same discipline §3 of the contract asks of the agent (VERDICT-F-50)."""
    for cache in (root or ROOT).rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)


def run_suite(env, cwd=None):
    return subprocess.run(SUITE, cwd=cwd or ROOT, capture_output=True, text=True, env=env)


def scratch_copy(root) -> pathlib.Path:
    """A copy of the tree as it is now — what `git` would commit, plus the
    untracked files it would accept — under a fresh temporary directory.

    Not `git archive HEAD`: that snapshots the last commit, and the mutants a
    maintainer runs before committing must run against the edits in hand.
    Ignored files (`.venv`, caches, scratch state) stay behind. A root that is
    not a git checkout is copied whole, minus the obvious.
    """
    root = pathlib.Path(root)
    dest = pathlib.Path(tempfile.mkdtemp(prefix="pin_check-"))
    listing = subprocess.run(["git", "-C", str(root), "ls-files", "-z", "--cached",
                              "--others", "--exclude-standard"],
                             capture_output=True, text=True)
    if listing.returncode == 0:
        for rel in listing.stdout.split("\0"):
            src = root / rel
            if not rel or not src.is_file():
                continue
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    else:
        shutil.copytree(root, dest, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git", ".venv", "__pycache__",
                                                      "node_modules", ".pin_check.lock"))
    return dest


def scratch_env(scratch) -> dict:
    """The copy's own source first, bytecode never written."""
    scratch = pathlib.Path(scratch)
    ahead = [str(p) for p in (scratch / "src", scratch) if p.is_dir()]
    return {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(ahead + [os.environ.get("PYTHONPATH", "")]).rstrip(os.pathsep)}


def runs_its_own_code(scratch, env) -> str | None:
    """Where `import verdict_mcp` resolves from inside the scratch, or None.

    Returns the offending path when the import lands outside the copy, which
    is the one result that makes every number after it meaningless: an
    editable install points at the real checkout regardless of cwd, and only
    PYTHONPATH outranks it (VERDICT-F-48, run 9's lesson).
    """
    probe = subprocess.run(IMPORT_CHECK, cwd=scratch, capture_output=True, text=True, env=env)
    resolved = probe.stdout.strip().splitlines()[-1] if probe.stdout.strip() else ""
    try:
        inside = pathlib.Path(resolved).resolve().is_relative_to(pathlib.Path(scratch).resolve())
    except (OSError, ValueError):
        inside = False
    return None if probe.returncode == 0 and resolved and inside else (resolved or probe.stderr[-300:])


_COUNT = re.compile(r"(\d+) (passed|failed|errors?|skipped|xfailed|xpassed|deselected)\b")
_SUMMARY_TAIL = re.compile(r" in \d+(?:\.\d+)?s\b")


def classify(returncode: int, stdout: str) -> str:
    """`killed`, `survived` or `error` — read off pytest's own summary line,
    never off the exit code alone.

    pytest exits non-zero for a usage error (4), an internal error (3), a
    failed collection (2) and "no tests ran" (5) exactly as it does for a
    failing test (1). Read as `rc != 0`, a mutant that leaves a module
    unimportable scores as *defended* when nothing ran at all (VERDICT-F-68) —
    the misreading run 11 had already written a lesson about. So a kill needs
    pytest's count of failed or errored tests on its final line; any other
    non-zero exit is the instrument breaking, and is reported as that.
    """
    if returncode == 0:
        return "survived"
    summary = ""
    for line in reversed(stdout.splitlines()):
        if _SUMMARY_TAIL.search(line) and _COUNT.search(line):
            summary = line
            break
    counts: dict = {}
    for n, kind in _COUNT.findall(summary):
        kind = "error" if kind.startswith("error") else kind
        counts[kind] = counts.get(kind, 0) + int(n)
    if returncode == 1 and (counts.get("failed") or counts.get("error")):
        return "killed"
    return "error"


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
        # Looked up by name, because Windows has no SIGHUP and building the
        # tuple raised AttributeError before the `try` could catch it — an
        # except clause that names AttributeError "the platform lacks it" and
        # sits one level too deep to ever see it. The whole class was
        # unconstructible there, which nothing noticed until a test made one.
        for name in ("SIGINT", "SIGTERM", "SIGHUP"):
            sig = getattr(signal, name, None)
            if sig is None:
                continue
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError):
                pass    # not the main thread

    def hold(self, path, text):
        self._saved[path] = text

    def restore(self):
        while self._saved:
            path, text = self._saved.popitem()
            try:
                write_atomic(path, text)
            except OSError as exc:
                print(f"COULD NOT RESTORE {path}: {exc}", file=sys.stderr)
        sweep()

    def _on_signal(self, signum, _frame):
        print(f"\ninterrupted (signal {signum}) — restoring the tree", file=sys.stderr)
        self.restore()
        raise SystemExit(130)   # atexit still runs, so the lock is released


def main(argv=None) -> int:
    # Labels carry em dashes and middle dots; a Windows console defaults to
    # cp1252 and a log reader to UTF-8, and the two disagree about both. Every
    # CLI in this repository says UTF-8 out loud for the same reason.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--filter", default="", help="substring match on the label")
    ap.add_argument("--list", action="store_true", help="print the catalogue and stop")
    ap.add_argument("--in-tree", action="store_true",
                    help="mutate the real files under a lock instead of a scratch copy")
    args = ap.parse_args(argv)

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

    if args.in_tree:
        tree = ROOT
        OnlyOne(str(ROOT / ".pin_check.lock"))   # held until the process exits
        keeper = Restorer()
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    else:
        tree = scratch_copy(ROOT)
        atexit.register(shutil.rmtree, tree, True)
        keeper = None
        env = scratch_env(tree)
        elsewhere = runs_its_own_code(tree, env)
        if elsewhere:
            # The path is printed as is, not as a repr: on Windows a repr doubles
            # every backslash and the message stops naming the file it names.
            print("ISOLATION FAILED: inside the scratch copy `import verdict_mcp` resolves to "
                  f"{elsewhere}, not to the copy. Every mutant would measure the original "
                  "checkout.", file=sys.stderr)
            return 1
        print(f"scratch copy: {tree} · runs its own code")
    # Control the instrument before trusting it: a suite that is already red
    # kills every mutant and proves nothing.
    sweep(tree)
    control = run_suite(env, tree)
    if control.returncode != 0:
        print("CONTROL FAILED — the suite is red before any mutation.", file=sys.stderr)
        print(control.stdout[-2000:], file=sys.stderr)
        return 1
    print(f"control: suite green · {len(mutants)} mutants to apply\n")

    survivors, equivalents, broken = [], [], []
    for i, m in enumerate(mutants, 1):
        path = tree / m["path"]
        src = path.read_text(encoding="utf-8")
        hits = src.count(m["old"])
        if hits != 1:
            print(f"[{i:2}/{len(mutants)}] STALE    {m['label']}  (anchor matched {hits})")
            survivors.append(m["label"] + "  [stale anchor]")
            continue
        if keeper is not None:
            keeper.hold(path, src)
        write_atomic(path, src.replace(m["old"], m["new"]))
        sweep(tree)
        try:
            result = run_suite(env, tree)
        finally:
            if keeper is not None:
                keeper.restore()
            else:
                write_atomic(path, src)
        outcome = classify(result.returncode, result.stdout)
        if outcome == "killed":
            print(f"[{i:2}/{len(mutants)}] KILLED   {m['label']}")
        elif outcome == "error":
            # Not a kill and not a survivor: pytest exited without a failed
            # test, so the mutant was never measured. Counted apart, or a
            # mutant that breaks collection reads as a defended rule.
            print(f"[{i:2}/{len(mutants)}] ERROR    {m['label']}  "
                  f"(pytest exited {result.returncode} with no failed test — not a kill)")
            broken.append(m["label"])
        elif m.get("equivalent"):
            # Documented, not hidden: a mutant that provably cannot change a
            # verdict is a question with no answer, and scoring it as a miss
            # would push someone to write a test that can only ever pass.
            print(f"[{i:2}/{len(mutants)}] EQUIV    {m['label']}")
            equivalents.append(m["label"])
        else:
            print(f"[{i:2}/{len(mutants)}] SURVIVED {m['label']}")
            survivors.append(m["label"])

    killed = len(mutants) - len(survivors) - len(equivalents) - len(broken)
    scored = len(mutants) - len(equivalents) - len(broken)
    print(f"\n{killed} of {scored} killed by the whole suite"
          + (f" ({len(equivalents)} equivalent, excluded)" if equivalents else "")
          + (f" ({len(broken)} not measured: pytest broke instead of failing)" if broken else ""))
    if survivors:
        print("\nsurvivors — each is a rule the suite does not defend:")
        for s in survivors:
            print(f"  · {s}")
    if broken:
        print("\nnot measured — the suite could not run against these mutants, which is a "
              "fact about the mutant or the tool, never a kill:")
        for s in broken:
            print(f"  · {s}")
    return 1 if survivors or broken else 0


if __name__ == "__main__":
    sys.exit(main())
