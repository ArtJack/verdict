#!/usr/bin/env python3
"""Verdict Bash guard (PreToolUse hook) — active under VERDICT_STRICT only.

Closes the obvious Bash write channels — output redirection, `tee`, `sed -i`,
`rm`/`mv`/`cp` and friends, mutating `git` verbs — when the target lies outside
a QA root. Complements enforce_write_scope.py, which guards the Write/Edit
tools; together they make VERDICT_STRICT=1 sessions (headless / CI / scheduled
QA runs) enforce "read-only on the code under test" at the tool boundary.

This is a deny-HEURISTIC, not a sandbox:

  - Unknown commands are ALLOWED — a QA run must be able to run pytest,
    coverage, linters, git reads, and whatever else the project's gates need.
  - Package installs are deliberately not denied: the published eval run
    legitimately provisions pytest out-of-tree.
  - A determined command can evade string analysis. OS sandboxing remains the
    real boundary; this guard raises the cost of the *accidental* mutation.

In non-strict sessions this hook is a no-op: the same PreToolUse event fires
for the user's own shell commands, where write heuristics would be intolerable.

Fail-open rules: malformed hook input exits 0 (a broken hook must never brick
a session), and a command that cannot be parsed is only denied when a deny
pattern is positively visible in the raw string. A target that still contains
an unresolved `$variable` after environment substitution is denied — strict
mode is strict; use literal paths inside the QA root.
"""

import json
import os
import re
import shlex
import sys
import tempfile

from qa_paths import is_allowed_path

# Commands whose non-flag arguments name files they (may) mutate.
_MUTATORS = {
    "rm", "rmdir", "unlink", "mv", "cp", "install", "touch", "mkdir", "ln",
    "chmod", "chown", "truncate", "shred", "rsync", "tee", "patch",
}
# git verbs that mutate the working tree, index, refs, or config.
_GIT_MUTATORS = {
    "commit", "push", "checkout", "switch", "restore", "reset", "clean",
    "apply", "am", "rebase", "merge", "revert", "cherry-pick", "rm", "mv",
    "stash", "worktree", "config", "tag", "branch",
}
# git global flags that consume the following token as their value. -C and
# --work-tree also re-point the checkout the mutation lands in.
_GIT_TREE_FLAGS = {"-C", "--work-tree"}
_GIT_VALUE_FLAGS = {"-c", "--git-dir", "--namespace", "--exec-path",
                    "--super-prefix", "--config-env", "--attr-source"}
_WRAPPERS = {"env", "sudo", "command", "nohup", "time", "exec"}
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `> path`, `>> path`, `2> path`, `&> path`, `>| path` — captures the target token.
_REDIRECT = re.compile(r"(?:^|[^<>])(?:\d?>{1,2}|&>{1,2}|>\|)\s*([^\s;|&<>]+)")
_VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")


def _strict() -> bool:
    return os.environ.get("VERDICT_STRICT", "") not in ("", "0", "false")


def _tmp_roots():
    roots = {"/tmp", "/private/tmp",
             tempfile.gettempdir(), os.environ.get("TMPDIR") or ""}
    return [os.path.realpath(r) for r in roots if r]


def _resolve(target: str, cwd: str) -> str | None:
    """Expand env vars and cwd; None means an unresolved variable remains."""
    expanded = _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), target)
    if "$" in expanded:
        return None
    expanded = os.path.expanduser(expanded)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normpath(expanded)


def _in_checkout(path: str, stop_at: str) -> bool:
    """Is `path` inside a git working tree that lives below `stop_at`?

    Walks up only as far as the temp root, so the scratch tree itself stays
    writable while anything that is a repository inside it does not.
    """
    d = path if os.path.isdir(path) else os.path.dirname(path)
    while d and d != stop_at and d.startswith(stop_at + os.sep):
        if os.path.exists(os.path.join(d, ".git")):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return False


def _target_ok(target: str, cwd: str) -> tuple[bool, str]:
    """(allowed, resolved-or-reason) for one candidate write target."""
    if not target or target.startswith(("&", "-")):
        return True, target  # fd duplication or a flag, not a file
    if target.startswith("/dev/"):
        return True, target  # POSIX device sink — check the raw token, before
        # path normalization turns it into \dev\null on Windows
    resolved = _resolve(target, cwd)
    if resolved is None:
        return False, f"{target} (unresolved $variable — use a literal path)"
    # realpath BEFORE the scratch check: a symlink sitting inside /tmp (or
    # inside .qa/) that points outside must not launder the write through the
    # allow-list — VERDICT-F-1, applied consistently.
    resolved = os.path.realpath(resolved)
    # QA scope first, and deliberately: a team `.qa/` inside a repository that
    # happens to live under /tmp is still QA state, and the tester must always
    # be able to write its own findings.
    if is_allowed_path(resolved):
        return True, resolved
    for root in _tmp_roots():
        if resolved == root or resolved.startswith(root + os.sep):
            # Scratch under a temp root is fine — but a checkout under one is
            # code under test, not scratch. The eval harness builds its repo in
            # mkdtemp and CI commonly clones there, so blanket-allowing the
            # temp root left the guard with no jurisdiction over the very code
            # it exists to protect, and made "zero false-positive blocks" in a
            # temp-rooted eval a statement about nothing.
            if _in_checkout(resolved, root):
                return False, f"{resolved} (a git checkout under {root})"
            return True, resolved
    return False, resolved


def _segments(command: str):
    return [s for s in re.split(r"(?:&&|\|\||[;|\n])", command) if s.strip()]


def _tokens(segment: str):
    try:
        # posix=True on Windows would eat path backslashes as escapes,
        # mangling every target it is supposed to judge.
        toks = shlex.split(segment, posix=(os.name != "nt"))
    except ValueError:
        toks = segment.split()
    while toks and (_ASSIGNMENT.match(toks[0]) or
                    os.path.basename(toks[0]) in _WRAPPERS):
        toks = toks[1:]
    return toks


def _edits_in_place(tok: str) -> bool:
    """Does this sed/perl option turn on in-place editing?"""
    if tok == "--in-place" or tok.startswith("--in-place="):
        return True
    if not tok.startswith("-") or tok.startswith("--"):
        return False
    # A short-option cluster, possibly with a backup suffix: -i, -i.bak, -pi.
    return "i" in tok[1:].split(".", 1)[0]


def _check_segment(toks, cwd):
    """Yield (description, candidate-target) pairs for one simple command."""
    if not toks:
        return
    head = os.path.basename(toks[0])
    args = toks[1:]
    if head == "dd":
        for t in args:
            if t.startswith("of="):
                yield "dd of=", t[3:]
    elif head in ("sed", "perl"):
        # `-i` is rarely written alone. `perl -pi -e` clusters it behind -p,
        # and `sed --in-place` spells it out; a startswith("-i") test saw
        # neither, so both edited files in place with the guard silent.
        if any(_edits_in_place(t) for t in args):
            it = iter(args)
            for t in it:
                if t in ("-e", "-E", "-f"):
                    next(it, None)    # the script/expression, not a target
                elif not t.startswith("-"):
                    yield f"{head} in-place", t
    elif head == "git":
        if any(t in ("--dry-run", "--check") for t in args):
            return
        repo, verb, it = cwd, None, iter(args)
        for t in it:
            # A global flag that takes a value must have that value eaten, or
            # the value becomes the "verb" and every mutator hides behind it:
            # `git -c core.editor=true commit -am x` read as verb
            # "core.editor=true", which is in no mutator set, and passed.
            if t in _GIT_TREE_FLAGS:
                repo = next(it, repo) or repo
            elif t in _GIT_VALUE_FLAGS:
                next(it, None)
            elif t.startswith("--work-tree="):
                repo = t.split("=", 1)[1] or repo
            elif t.startswith("-"):
                continue          # boolean flag, or --flag=value: no argument
            else:
                verb = t
                break
        if verb in _GIT_MUTATORS:
            yield f"git {verb} (mutates the checkout)", repo
    elif head == "find":
        mutates = "-delete" in args
        for i, t in enumerate(args):
            if t in ("-exec", "-execdir") and i + 1 < len(args):
                mutates = mutates or os.path.basename(args[i + 1]) in _MUTATORS
        if mutates:
            roots = []
            for t in args:
                if t.startswith("-"):
                    break
                roots.append(t)
            for t in (roots or [cwd]):
                yield "find -delete/-exec", t
    elif head in _MUTATORS:
        for t in args:
            if not t.startswith("-"):
                yield head, t


def main() -> int:
    if not _strict():
        return 0
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command", "")
    except Exception:
        return 0  # fail open: never brick the session on malformed input
    if not isinstance(command, str) or not command:
        return 0
    cwd = data.get("cwd") or os.getcwd()

    denials = []
    for target in _REDIRECT.findall(command):
        ok, resolved = _target_ok(target, cwd)
        if not ok:
            denials.append(("output redirection", resolved))
    for segment in _segments(command):
        for what, target in _check_segment(_tokens(segment), cwd):
            ok, resolved = _target_ok(target, cwd)
            if not ok:
                denials.append((what, resolved))

    if not denials:
        return 0
    what, resolved = denials[0]
    sys.stderr.write(
        f"verdict bash guard (VERDICT_STRICT): {what} targets {resolved!r}, "
        "outside the QA root. Strict QA sessions may only write inside a .qa/ "
        "directory, $VERDICT_HOME (default ~/.claude/verdict), /dev/*, or scratch "
        "under a temp dir — but not a git checkout sitting in one. Findings "
        "are reported, never patched in place.\n"
    )
    return 2  # block the tool call and show Claude the reason


if __name__ == "__main__":
    sys.exit(main())
