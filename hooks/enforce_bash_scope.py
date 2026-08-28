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
    return [os.path.normpath(r) for r in roots if r]


def _resolve(target: str, cwd: str) -> str | None:
    """Expand env vars and cwd; None means an unresolved variable remains."""
    expanded = _VAR.sub(lambda m: os.environ.get(m.group(1), m.group(0)), target)
    if "$" in expanded:
        return None
    expanded = os.path.expanduser(expanded)
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normpath(expanded)


def _target_ok(target: str, cwd: str) -> tuple[bool, str]:
    """(allowed, resolved-or-reason) for one candidate write target."""
    if not target or target.startswith(("&", "-")):
        return True, target  # fd duplication or a flag, not a file
    resolved = _resolve(target, cwd)
    if resolved is None:
        return False, f"{target} (unresolved $variable — use a literal path)"
    if resolved.startswith("/dev/"):
        return True, resolved
    for root in _tmp_roots():
        if resolved == root or resolved.startswith(root + os.sep):
            return True, resolved
    return is_allowed_path(resolved), resolved


def _segments(command: str):
    return [s for s in re.split(r"(?:&&|\|\||[;|\n])", command) if s.strip()]


def _tokens(segment: str):
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        toks = segment.split()
    while toks and (_ASSIGNMENT.match(toks[0]) or
                    os.path.basename(toks[0]) in _WRAPPERS):
        toks = toks[1:]
    return toks


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
        if any(t == "-i" or t.startswith("-i") for t in args):
            for t in args:
                if not t.startswith("-"):
                    yield f"{head} -i", t
    elif head == "git":
        if any(t in ("--dry-run", "--check") for t in args):
            return
        repo, verb, it = cwd, None, iter(args)
        for t in it:
            if t == "-C":
                repo = next(it, cwd)
            elif not t.startswith("-"):
                verb = t
                break
        if verb in _GIT_MUTATORS:
            yield f"git {verb} (mutates the checkout)", repo
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
        "directory, $VERDICT_HOME (default ~/.claude/verdict), /dev/*, or temp "
        "dirs. Findings are reported, never patched in place.\n"
    )
    return 2  # block the tool call and show Claude the reason


if __name__ == "__main__":
    sys.exit(main())
