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
# Of those, the ones that COPY: everything but the last operand is a source it
# only reads. Treating them all as targets refused `cp -a <checkout> <scratch>`
# — the re-injection step the agent contract asks for — in the same words as
# overwriting source, and the guard exists to tell those two apart
# (VERDICT-F-37). `-t/--target-directory` names the destination instead, and
# then every operand really is a source.
_COPIERS = {"cp", "mv", "install", "rsync", "ln"}
_TARGET_FLAGS = ("-t", "--target-directory")
# git verbs that mutate the working tree, index, refs, or config.
_GIT_MUTATORS = {
    "commit", "push", "checkout", "switch", "restore", "reset", "clean",
    "apply", "am", "rebase", "merge", "revert", "cherry-pick", "rm", "mv",
    "stash", "worktree", "config", "tag", "branch",
    # `pull` is `fetch` plus `merge`: it rewrites the working tree, and its
    # absence here was the widest git-shaped hole left after the 0.44.0 sweep.
    "pull", "submodule", "bisect", "update-ref", "update-index", "gc",
    "prune", "filter-branch", "sparse-checkout", "notes", "replace", "reflog",
}
# Sub-verbs that only read. Denying `git submodule status` would be the kind
# of false positive that gets strict mode switched off.
_GIT_READONLY_SUBVERBS = {
    "submodule": {"status", "summary"},
    "bisect": {"log", "view", "help"},
    "notes": {"list", "show"},
    "sparse-checkout": {"list"},
    "stash": {"list", "show"},
    "reflog": {"show"},
    "worktree": {"list"},
    "tag": {"list"},
    "branch": {"list"},
    "config": {"get", "list", "--get", "--list", "--get-all", "-l"},
}
# Verbs whose bare form only reports: `git branch` lists, it does not create.
# `stash`, `gc` and `prune` are deliberately absent — bare, they all act.
_GIT_READONLY_BARE = {"branch", "tag", "reflog", "notes", "worktree",
                      "submodule", "bisect", "sparse-checkout", "config"}
# git global flags that consume the following token as their value. -C and
# --work-tree also re-point the checkout the mutation lands in.
_GIT_TREE_FLAGS = {"-C", "--work-tree"}
_GIT_VALUE_FLAGS = {"-c", "--git-dir", "--namespace", "--exec-path",
                    "--super-prefix", "--config-env", "--attr-source"}
_WRAPPERS = {"env", "sudo", "doas", "command", "nohup", "time", "exec",
             "timeout", "nice", "ionice", "stdbuf", "setsid", "chrt",
             "taskset", "script"}
# A wrapper's own flags take values too — `sudo -u nobody rm x` left "nobody"
# as the head and the rm went unseen. Same defect class as the git flags.
_WRAPPER_VALUE_FLAGS = {"-u", "-g", "-C", "-p", "-U", "-s", "-k", "-n", "-c",
                        "-P", "--chdir", "--signal", "--kill-after", "--user"}
_DURATION = re.compile(r"^\d+(?:\.\d+)?[smhd]?$")
# Shells re-enter the same parser: `bash -c "rm x"` is not opaque the way an
# interpreter's `-c` is, and refusing to look inside it would be a choice.
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash"}
# A target that cannot be read off the command line at all. Distinct from a
# path so it can never be mistaken for one — "-" was, and _target_ok waved it
# through as a flag.
_UNKNOWABLE = "\x00stdin"
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
    if target == _UNKNOWABLE:
        return False, "a target read from stdin (pipe the list to a file and name it)"
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
        wrapper = os.path.basename(toks[0])
        toks = toks[1:]
        # Eat the wrapper's own options so the real command surfaces as head.
        while toks:
            if toks[0] in _WRAPPER_VALUE_FLAGS:
                toks = toks[2:]
            elif toks[0].startswith("-"):
                toks = toks[1:]
            elif wrapper in ("timeout", "nice", "ionice") and _DURATION.match(toks[0]):
                toks = toks[1:]      # timeout's duration, nice's level
            else:
                break
    return toks


def _edits_in_place(tok: str) -> bool:
    """Does this sed/perl option turn on in-place editing?"""
    if tok == "--in-place" or tok.startswith("--in-place="):
        return True
    if not tok.startswith("-") or tok.startswith("--"):
        return False
    # A short-option cluster, possibly with a backup suffix: -i, -i.bak, -pi.
    return "i" in tok[1:].split(".", 1)[0]


def _check_shell(args, cwd, depth):
    """`bash -c "rm x"` is shell inside shell, and this module parses shell:
    declining to look would be a choice, not a limit."""
    for i, t in enumerate(args):
        if t == "-c" and i + 1 < len(args):
            nested = args[i + 1]
            # _tokens runs shlex with posix=False on Windows (so path
            # backslashes survive), and that mode *keeps* the quotes around a
            # token. Without stripping them the nested command arrived as the
            # single token '"rm f.txt"' and parsed as nothing at all — the
            # recursion worked on POSIX and was dead on Windows.
            if len(nested) >= 2 and nested[0] == nested[-1] and nested[0] in "\"'":
                nested = nested[1:-1]
            for seg in _segments(nested):
                yield from _check_segment(_tokens(seg), cwd, depth + 1)
            return


def _check_xargs(head, args):
    """`xargs rm` mutates targets that arrive on stdin — unknowable from the
    command line, which is the case the unresolved-$variable rule refuses."""
    rest = list(args)
    while rest:
        if rest[0] in ("-I", "-i", "-n", "-P", "-d", "-L", "-s", "-a", "-E"):
            rest = rest[2:]
        elif rest[0].startswith("-"):
            rest = rest[1:]
        else:
            break
    if rest and os.path.basename(rest[0]) in _MUTATORS | {"git", "sed", "perl"}:
        yield (f"{head} {os.path.basename(rest[0])} (targets arrive on stdin "
               "and cannot be checked)"), _UNKNOWABLE


def _check_stream_editor(head, args):
    """`-i` is rarely written alone: `perl -pi -e` clusters it behind -p and
    `sed --in-place` spells it out. A startswith("-i") test saw neither."""
    if not any(_edits_in_place(t) for t in args):
        return
    it = iter(args)
    for t in it:
        if t in ("-e", "-E", "-f"):
            next(it, None)        # the script, not a target
        elif not t.startswith("-"):
            yield f"{head} in-place", t


def _check_git(args, cwd):
    if any(t in ("--dry-run", "--check") for t in args):
        return
    repo, verb, it = cwd, None, iter(args)
    for t in it:
        # A global flag that takes a value must have that value eaten, or the
        # value becomes the "verb" and every mutator hides behind it:
        # `git -c core.editor=true commit -am x` read as verb
        # "core.editor=true", which is in no mutator set, and passed.
        if t in _GIT_TREE_FLAGS:
            repo = next(it, repo) or repo
        elif t in _GIT_VALUE_FLAGS:
            next(it, None)
        elif t.startswith("--work-tree="):
            repo = t.split("=", 1)[1] or repo
        elif t.startswith("-"):
            continue              # boolean flag, or --flag=value
        else:
            verb = t
            break
    if verb not in _GIT_MUTATORS:
        return
    rest = list(it)
    # `--get` and `--list` are flags, so a first-non-flag scan walked straight
    # past them and denied `git config --get user.name`.
    if any(t in _GIT_READONLY_SUBVERBS.get(verb, set()) for t in rest):
        return
    if not rest and verb in _GIT_READONLY_BARE:
        return                    # `git branch`, `git tag`: listings
    yield f"git {verb} (mutates the checkout)", repo


def _check_awk(args):
    if not (any(t.startswith("inplace") for t in args)
            and any(t in ("-i", "--load", "-f") for t in args)):
        return
    for t in args:
        if not t.startswith("-") and t != "inplace" and "{" not in t:
            yield "awk -i inplace", t


def _check_tar(args, cwd):
    extracting = (any(t.startswith("-") and "x" in t.lstrip("-") for t in args)
                  or (args and not args[0].startswith("-") and "x" in args[0]))
    if not extracting:
        return
    target, it = cwd, iter(args)
    for t in it:
        if t in ("-C", "--directory"):
            target = next(it, cwd)
    yield "tar extract (overwrites in place)", target


def _check_find(args, cwd):
    mutates = "-delete" in args
    for i, t in enumerate(args):
        if t in ("-exec", "-execdir") and i + 1 < len(args):
            mutates = mutates or os.path.basename(args[i + 1]) in _MUTATORS
    if not mutates:
        return
    roots = []
    for t in args:
        if t.startswith("-"):
            break
        roots.append(t)
    for t in (roots or [cwd]):
        yield "find -delete/-exec", t


def _check_segment(toks, cwd, depth=0):
    """Yield (description, candidate-target) pairs for one simple command.

    A dispatcher: each command family reads its own arguments, because the
    combined form outgrew the complexity budget once wrappers, nested shells
    and six more git verbs went in — and a guard nobody can follow is one
    nobody extends.
    """
    if not toks:
        return
    head = os.path.basename(toks[0])
    args = toks[1:]
    if head in _SHELLS and depth < 3:
        yield from _check_shell(args, cwd, depth)
    elif head in ("xargs", "parallel"):
        yield from _check_xargs(head, args)
    elif head == "dd":
        for t in args:
            if t.startswith("of="):
                yield "dd of=", t[3:]
    elif head in ("sed", "perl"):
        yield from _check_stream_editor(head, args)
    elif head == "git":
        yield from _check_git(args, cwd)
    elif head in ("awk", "gawk"):
        yield from _check_awk(args)
    elif head == "tar":
        yield from _check_tar(args, cwd)
    elif head == "find":
        yield from _check_find(args, cwd)
    elif head in _COPIERS:
        yield from _check_copier(head, args)
    elif head in _MUTATORS:
        for t in args:
            if not t.startswith("-"):
                yield head, t


def _check_copier(head: str, args: list):
    """`cp SRC... DST` writes DST and reads the rest. With an explicit
    `-t DIR`, DIR is the destination and every operand is a source."""
    operands, target, expect_dir = [], None, False
    for a in args:
        if expect_dir:
            target, expect_dir = a, False
            continue
        if a in _TARGET_FLAGS:
            expect_dir = True
            continue
        for flag in _TARGET_FLAGS:
            if a.startswith(flag + "="):
                target = a[len(flag) + 1:]
                break
        else:
            if not a.startswith("-"):
                operands.append(a)
            continue
    if target is None:
        # Nothing to write without a destination; a lone operand is the target
        # (`ln -s x` and friends land beside the cwd).
        if not operands:
            return
        target = operands[-1]
    yield head, target


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
