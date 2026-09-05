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

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations


import json
import os
import re
import shlex
import sys
import tempfile

from qa_paths import is_allowed_path, is_maintainer_file, utf8_stderr

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
_COPIERS = {"cp", "install", "rsync", "ln"}
# `mv` is NOT one of them: it writes its destination and *removes* its source.
# Reading it as a copy let `mv <checkout>/hooks/enforce_bash_scope.py /tmp/`
# through — the agent moving the guard itself out of the way — one commit after
# that exact command was denied (VERDICT-F-39). Both ends are targets here.
_MOVERS = {"mv"}
_TARGET_FLAGS = ("-t", "--target-directory")
# tar's option grammar, only as far as this guard needs it. Short options that
# consume the token after them: under-listing here costs at worst a spurious
# deletion candidate on a command that already carries `--remove-files`, while
# over-listing hides a real one, so the list stays short and certain.
_TAR_SHORT_WITH_ARG = set("bCfFgHIKLNTVX")
# Long options in their `--opt VALUE` form; `--opt=VALUE` carries its own.
_TAR_LONG_WITH_ARG = frozenset({
    "add-file", "after-date", "blocking-factor", "checkpoint-action",
    "directory", "exclude", "exclude-from", "file", "files-from", "format",
    "group", "index-file", "info-script", "label", "listed-incremental",
    "mode", "newer", "newer-mtime", "occurrence", "owner", "quoting-style",
    "record-size", "rmt-command", "rsh-command", "starting-file",
    "strip-components", "suffix", "tape-length", "to-command", "transform",
    "use-compress-program", "volno-file", "warning", "xform",
})
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
# A target that cannot be read off the command line at all: `xargs` taking its
# list from stdin, `tar --remove-files -T` taking it from a file. Distinct from
# a path so it can never be mistaken for one — "-" was, and _target_ok waved it
# through as a flag.
# Backslash is an escape character on POSIX and a path separator on Windows,
# and this module has to pick one. `_tokens` already picked: it runs shlex with
# posix=False on Windows because "posix=True would eat path backslashes as
# escapes, mangling every target it is supposed to judge". The masker and the
# redirect-target reader below must make the same choice or they mangle the
# targets shlex was careful to keep — which is exactly what they did, turning
# `C:\Users\...\repo\src` into `C:Usersreposrc` and reading an absolute path
# as a relative one.
_POSIX = os.name != "nt"
_UNKNOWABLE = "\x00stdin"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
# `>`, `>>`, `2>`, `&>`, `>|` — locates the OPERATOR only. The target used to
# be captured by the same regex out of the raw command line, which read a `>`
# inside a quoted string or a heredoc body as live syntax: a `{rc:>3}` format
# spec, a `->` in a docstring and a quoted `"<tmp>"` each denied a read-only
# command in one QA run (VERDICT-F-22). Operators are now found in a masked
# view and targets read from the original, so quoting decides both.
# `>|` leads the alternation: when operator and target were one pattern, a
# failed target match backtracked into it, and splitting them took that away.
_REDIRECT = re.compile(r"(?:^|[^<>])(?:>\||&>{1,2}|\d?>{1,2})")
# One character standing in for text the shell would not read as syntax.
_MASK = "\x01"
# The `|` of a `>|` clobber-redirect is part of the operator, not a pipe. The
# whole command used to be scanned for redirects before it was split, so this
# never came up; scanning per segment made the split able to cut a redirect in
# half and lose its target.
_SEPARATOR = re.compile(r"(?:&&|\|\||[;\n]|(?<!>)\|)")
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
        return False, ("a target this command reads from somewhere other than its "
                       "own arguments — name the paths on the command line")
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
    if is_maintainer_file(resolved):
        # In scope, and still refused: the accepted-risk ledger is the
        # maintainer's decision about the tester's findings, written by
        # `verdict-accept` from outside any session.
        return False, (f"{resolved} (the maintainer's accepted-risk ledger — written by "
                       "verdict-accept, never by the tester)")
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


def _mask_quoted(command: str) -> str:
    """Blank out quoted text, escapes and heredoc bodies, preserving offsets.

    The result is the same length as the input, so an offset into it is an
    offset into the original — the guard decides *where* syntax is on this
    view and reads *what* it says from the real string. The second value is
    False when the command left a quote or a heredoc open, which is the
    module's fail-closed case: a string that does not parse must not be able
    to hide a visible deny pattern behind a quote it never closes.
    """
    out = list(command)
    i, n, heredocs, balanced = 0, len(command), [], True
    while i < n:
        ch = command[i]
        if ch == "\\" and _POSIX and i + 1 < n:
            out[i] = out[i + 1] = _MASK
            i += 2
        elif ch in "\"'":
            j = i + 1
            while j < n:
                if ch == '"' and _POSIX and command[j] == "\\" and j + 1 < n:
                    j += 2
                    continue
                if command[j] == ch:
                    break
                j += 1
            else:
                balanced = False        # an unterminated quote parses as nothing
            for k in range(i, min(j + 1, n)):
                out[k] = _MASK
            i = j + 1
        elif command.startswith("<<", i) and not command.startswith("<<<", i):
            j = i + 2
            if j < n and command[j] == "-":
                j += 1
            while j < n and command[j] in " \t":
                j += 1
            quote = command[j] if j < n and command[j] in "\"'" else ""
            j += 1 if quote else 0
            start = j
            while j < n and (command[j].isalnum() or command[j] in "_-."):
                j += 1
            delimiter = command[start:j]
            j += 1 if quote and j < n and command[j] == quote else 0
            if delimiter:
                heredocs.append(delimiter)
            i = j
        elif ch == "\n" and heredocs:
            j = i + 1
            while heredocs:
                delimiter = heredocs.pop(0)
                while j < n:
                    end = command.find("\n", j)
                    end = n if end == -1 else end
                    if command[j:end].strip() == delimiter:
                        j = end
                        break
                    j = n if end >= n else end + 1
            for k in range(i + 1, min(j, n)):
                out[k] = _MASK
            i = max(j, i + 1)
        else:
            i += 1
    return "".join(out), balanced and not heredocs


def _segments(command: str, view: str | None = None):
    """Split into simple commands, yielding (separator-before, text, masked).

    Where to split is decided on the masked view — a `;` inside quotes is text,
    not a separator — while the text handed on is the original, so the
    tokenizer still sees real quoting.
    """
    view = _mask_quoted(command)[0] if view is None else view
    out, start, sep = [], 0, ""
    for m in _SEPARATOR.finditer(view):
        if command[start:m.start()].strip():
            out.append((sep, command[start:m.start()], view[start:m.start()]))
        start, sep = m.end(), m.group(0)
    if command[start:].strip():
        out.append((sep, command[start:], view[start:]))
    return out


def _token_after(text: str, i: int) -> str:
    """Read one shell word out of `text` starting at `i`, honouring quotes."""
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    out = []
    while i < n:
        ch = text[i]
        if ch in " \t\n;|&<>":
            break
        if ch in "\"'":
            i += 1
            while i < n and text[i] != ch:
                out.append(text[i])
                i += 1
            i += 1
            continue
        if ch == "\\" and _POSIX and i + 1 < n:
            out.append(text[i + 1])
            i += 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _redirect_targets(text: str, view: str):
    for m in _REDIRECT.finditer(view):
        target = _token_after(text, m.end())
        if target:
            yield target


def _cd_target(toks, cwd: str):
    """Where a `cd` in this segment leaves the shell, or None to keep `cwd`.

    A relative redirect belongs to the directory the same command line changed
    into: `cd <scratch> && cat > note.py` writes into the scratch, and reading
    it against the tool's own cwd refused a temp-file write as a write to the
    checkout (VERDICT-F-22).
    """
    if not toks or os.path.basename(toks[0]) != "cd":
        return None
    rest = [t for t in toks[1:] if not t.startswith("-")]
    if not rest or _VAR.search(rest[0]):
        return None
    return os.path.normpath(os.path.join(cwd, os.path.expanduser(rest[0])))


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


def _unquote_nested(text: str) -> str:
    """Strip one enclosing pair of quotes from a nested command string.

    `_tokens` runs shlex with posix=False on Windows so path backslashes
    survive, and that mode *keeps* the quotes around a token. Left on, the
    nested command is entirely quoted text in the masked view and parses as
    nothing — the same platform split that once made `bash -c` recursion dead
    on Windows while it worked on POSIX.
    """
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        return text[1:-1]
    return text


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
            nested = _unquote_nested(nested)
            # The nested string's own redirects are found here or nowhere: the
            # outer scan reads a masked view, in which everything between these
            # quotes is text.
            for _sep, seg, seg_view in _segments(nested):
                for target in _redirect_targets(seg, seg_view):
                    yield "output redirection", target
                yield from _check_segment(_tokens(seg), cwd, depth + 1)
            return


def _check_eval(args, cwd, depth):
    """`eval` re-enters the parser with its arguments joined — a shell by
    another name, and this module parses shell.

    It earns its own branch because of how redirects are found now: the outer
    scan reads a masked view, where everything inside `eval "... > file"` is
    quoted text. The raw scan used to catch that by accident; nothing else
    would.
    """
    for _sep, seg, seg_view in _segments(_unquote_nested(" ".join(args))):
        for target in _redirect_targets(seg, seg_view):
            yield "output redirection", target
        yield from _check_segment(_tokens(seg), cwd, depth + 1)


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


def _tar_abbrev(name: str, canonical: str) -> bool:
    """Is `name` `canonical`, or a prefix of it GNU tar would accept?

    Three characters is the floor, which is enough to keep `--ext` (only
    `--extract`) and `--rem` (only `--remove-files`) unambiguous while never
    matching a short option letter.
    """
    return len(name) >= 3 and canonical.startswith(name)


def _tar_takes_value(name: str) -> bool:
    """Does this long option, possibly abbreviated, consume the next token?

    GNU tar accepts any unambiguous prefix of a long option. The parser matched
    the table exactly while the handler matched the same options by
    abbreviation, so `--direc <checkout>` was yielded valueless, the directory
    fell through as an operand, and an extraction into the checkout was
    reported against the shell's cwd — every rung of the ladder from `--dir`
    to `--director` allowed, only the two full spellings denied
    (VERDICT-F-71). Measured: `--dir`, `--direc` and `--directory` all extract
    into the named directory. A prefix tar itself calls ambiguous (`--fil`:
    --file, --files-from) makes tar refuse the whole command, so reading it as
    value-taking here costs nothing.
    """
    return name in _TAR_LONG_WITH_ARG or (
        len(name) >= 3 and any(o.startswith(name) for o in _TAR_LONG_WITH_ARG))


def _tar_parse(args):
    """Walk tar's arguments, yielding ("opt", name, value) and ("arg", operand, None).

    `name` is one short letter or a long option's name, and `--opt=V` and
    `--opt V` both arrive the same way. Reading the option grammar by substring
    broke this handler twice in opposite directions: any token containing `f`
    was treated as taking an argument, so `--remove-files` swallowed the
    operand behind it and the deletion went unseen (VERDICT-F-42); and any
    token containing `x` was treated as an extraction, so `--exclude=.venv`
    denied a plain create (VERDICT-F-49).
    """
    args = list(args)
    if args and args[0] and not args[0].startswith("-"):
        # Old style: `tar cf x.tar foo` is `tar -cf x.tar foo`, and its option
        # arguments follow the whole bundle in letter order — which is exactly
        # what the per-letter walk below consumes.
        args[0] = "-" + args[0]
    it = iter(args)
    for t in it:
        if t == "--":
            for rest in it:
                yield "arg", rest, None
            return
        if t.startswith("--"):
            name, sep, inline = t[2:].partition("=")
            if sep:
                yield "opt", name, inline
            elif _tar_takes_value(name):
                yield "opt", name, next(it, None)
            else:
                yield "opt", name, None
        elif t.startswith("-") and len(t) > 1:
            rest = t[1:]
            while rest:
                ch, rest = rest[0], rest[1:]
                if ch not in _TAR_SHORT_WITH_ARG:
                    yield "opt", ch, None
                    continue
                # getopt: the remainder of this token IS the value when there is
                # one. Always taking the next *token* let `-cf<archive>` read
                # `--remove-files` as the archive name, so the deletion had no
                # visible target and real tar removed the checkout with the
                # guard's blessing (VERDICT-F-62). One space was the whole
                # difference between allow and deny. `-C<dir>` was worse: `/`
                # parsed as an option letter.
                yield "opt", ch, (rest if rest else next(it, None))
                rest = ""
        else:
            yield "arg", t, None


def _check_tar(args, cwd):
    """Which paths does this tar command write to or delete?

    Every directory decision here is measured against GNU tar 1.35 rather than
    read off the manual: `-C` changes directory *at the point it appears*, so
    each operand belongs to the `-C` before it and not to the last one on the
    line, and successive `-C` values compound (`-C /a -C b` is `/a/b`). Taking
    the last one and joining every operand to it reported two scratch paths for
    `-C <checkout> hooks -C <scratch> junk`, which real tar answers by deleting
    both `<checkout>/hooks` and `<scratch>/junk` (VERDICT-F-56).
    """
    parsed = list(_tar_parse(args))
    here, operands, archive = cwd, [], None
    for kind, name, value in parsed:
        if kind == "opt" and (name == "C" or _tar_abbrev(name, "directory")) and value:
            here = value if os.path.isabs(value) else os.path.join(here, value)
        elif kind == "opt" and (name == "f" or _tar_abbrev(name, "file")) and value:
            # The archive is a path too. Measured against GNU tar 1.35: it
            # resolves against the shell's cwd wherever `-C` sits on the line,
            # and `-f -` is stdout, not a file.
            archive = None if value == "-" else (
                value if os.path.isabs(value) else os.path.join(cwd, value))
        elif kind == "arg":
            operands.append(name if os.path.isabs(name) else os.path.join(here, name))

    def _mode(*names):
        return any(kind == "opt" and any((name == n) if len(n) == 1 else _tar_abbrev(name, n)
                                         for n in names)
                   for kind, name, _ in parsed)

    if _mode("x", "extract", "get"):
        # Extraction writes into the directory in effect when it runs, which is
        # the last one the walk reached.
        yield "tar extract (overwrites in place)", here
        return
    if archive and not _mode("t", "list", "d", "diff", "compare"):
        # Every mode that is not extract, list or compare — create, append,
        # update, concatenate, delete — writes the archive named by `-f`. The
        # handler's own comment said the archive "is written, not removed"
        # and never yielded it, so `tar -cf <checkout>/hooks/a.py …` turned a
        # tracked source file into a tar archive with the guard's blessing,
        # and did the same to the maintainer's accepted.json that this guard
        # refuses to `cp` (VERDICT-F-70). Measured before it was modelled.
        yield "tar -f (writes the archive)", archive
    # Creating an archive only reads — unless it is told to delete what it read.
    # `tar --remove-files -cf <scratch>/loot.tar <checkout>/hooks` is the
    # archive-then-delete form of the `mv` shape that VERDICT-F-39 was about,
    # and the handler returned early on anything that was not an extraction
    # (VERDICT-F-42). The operands of such a command are all sources it removes;
    # the archive named by `-f` is written, not removed, and arrives here as an
    # option value rather than an operand.
    if not any(kind == "opt" and _tar_abbrev(name, "remove-files")
               for kind, name, _ in parsed):
        return
    if any(kind == "opt" and (name == "T" or _tar_abbrev(name, "files-from"))
           for kind, name, _ in parsed):
        # The operands are in a file, so there is nothing on the command line to
        # judge. The module already has a word for that, and not using it here
        # let `tar --remove-files -cf x.tar -T list.txt` delete whatever the
        # list named (VERDICT-F-59).
        yield "tar --remove-files -T (deletes what a file lists)", _UNKNOWABLE
    for operand in operands:
        yield "tar --remove-files (deletes what it archived)", operand


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
    elif head == "eval" and depth < 3:
        yield from _check_eval(args, cwd, depth)
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
    elif head in ("tar", "gtar", "bsdtar"):
        # By every name it is installed under. On macOS `/usr/bin/tar` is
        # bsdtar, which cannot `--remove-files` at all, and the GNU tar that
        # can is Homebrew's `gtar` — a name the exact match never read, so on
        # the one binary able to do the thing no tar rule fired (VERDICT-F-67).
        yield from _check_tar(args, cwd)
    elif head == "find":
        yield from _check_find(args, cwd)
    elif head in _COPIERS or head in _MOVERS:
        # rsync only removes sources when told to; asked to, it is a move.
        moves = head in _MOVERS or "--remove-source-files" in args
        yield from _check_copier(head, args, moves=moves)
    elif head in _MUTATORS:
        for t in args:
            if not t.startswith("-"):
                yield head, t


def _check_copier(head: str, args: list, moves: bool = False):
    """`cp SRC... DST` writes DST and reads the rest. With an explicit
    `-t DIR`, DIR is the destination and every operand is a source.

    `moves` says the command also *removes* what it read, which makes every
    source a target as well — `mv`, and `rsync --remove-source-files`."""
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
        operands = operands[:-1]
    yield head, target
    if moves:
        for source in operands:
            yield head, source


def main() -> int:
    utf8_stderr()
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

    view, balanced = _mask_quoted(command)
    # An unbalanced command is scanned twice: once as the shell would read it,
    # and once as raw text, so a deny pattern behind an unclosed quote is still
    # positively visible. Both passes only ever add denials.
    denials = []
    for scan in ([view] if balanced else [view, command]):
        here = cwd
        for separator, segment, seg_view in _segments(command, scan):
            if separator == "|":
                here = cwd  # a pipeline stage is a subshell; its `cd` is local
            for target in _redirect_targets(segment, seg_view):
                ok, resolved = _target_ok(target, here)
                if not ok:
                    denials.append(("output redirection", resolved))
            toks = _tokens(segment)
            for what, target in _check_segment(toks, here):
                ok, resolved = _target_ok(target, here)
                if not ok:
                    denials.append((what, resolved))
            here = _cd_target(toks, here) or here

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
