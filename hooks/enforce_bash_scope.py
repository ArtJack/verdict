#!/usr/bin/env python3
"""Verdict Bash guard (PreToolUse hook) — armed by VERDICT_STRICT, or by the caller.

Closes the obvious Bash write channels — output redirection, `tee`, `sed -i`,
`rm`/`mv`/`cp` and friends, mutating `git` verbs, formatters in their writing
shape — when the target lies outside a QA root. Complements
enforce_write_scope.py, which guards the Write/Edit tools; together they
enforce "read-only on the code under test" at the tool boundary.

Armed in two ways:

  1. VERDICT_STRICT=1: every Bash command of the session is judged, whoever
     issued it. For headless / CI / scheduled QA runs, where the whole session
     IS the QA run.
  2. Otherwise, only when the event names the Verdict agent as its caller
     (`qa_paths.caller_is_verdict`; Claude Code sends `agent_type` with every
     hook input fired inside a subagent). Until 0.90.3 this hook returned
     before it had read the event, so in every interactive session the
     tester's Write and Edit were refused while its `rm`, `sed -i` and
     `git checkout` went through (T0-4). An event that names no agent is the
     user's own shell command and is never judged: write heuristics on those
     would be intolerable.

This is a deny-HEURISTIC, not a sandbox:

  - Unknown commands are ALLOWED — a QA run must be able to run pytest,
    coverage, linters, git reads, and whatever else the project's gates need.
  - Package installs are deliberately not denied: the published eval run
    legitimately provisions pytest out-of-tree.
  - A program that writes through its own code is not seen at all: an
    interpreter (`python3 -c`, `node -e`, `awk '… > f'`), a build step, a
    script the shell reads from a file or a pipe, a function, an alias.
  - A determined command can evade string analysis. OS sandboxing remains the
    real boundary; this guard raises the cost of the *accidental* mutation.

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

from qa_paths import (caller_is_verdict, is_allowed_path, is_maintainer_file, maintainer_pen,
                      utf8_stderr)

# Commands whose non-flag arguments name files they (may) mutate.
_MUTATORS = {
    "rm", "rmdir", "unlink", "mv", "cp", "install", "touch", "mkdir", "ln",
    "chmod", "chown", "truncate", "shred", "rsync", "tee", "patch",
    # Three that write the file they are handed and were unknown commands, so
    # allowed (K-D-11): `sponge` soaks up stdin and then overwrites its
    # operand, `mkfifo` creates one, `ditto` is macOS's `cp`.
    "sponge", "mkfifo", "ditto",
}
# Of those, the ones that COPY: everything but the last operand is a source it
# only reads. Treating them all as targets refused `cp -a <checkout> <scratch>`
# — the re-injection step the agent contract asks for — in the same words as
# overwriting source, and the guard exists to tell those two apart
# (VERDICT-F-37). `-t/--target-directory` names the destination instead, and
# then every operand really is a source.
_COPIERS = {"cp", "install", "rsync", "ln", "ditto"}
# `mv` is NOT one of them: it writes its destination and *removes* its source.
# Reading it as a copy let `mv <checkout>/hooks/enforce_bash_scope.py /tmp/`
# through — the agent moving the guard itself out of the way — one commit after
# that exact command was denied (VERDICT-F-39). Both ends are targets here.
_MOVERS = {"mv"}
# Mutators whose FIRST operand is a mode, owner or size rather than a path.
# `chmod +x` was denied because `+x` resolved against the cwd (VERDICT-F-77);
# the files after it are the real targets and are still checked.
_MODE_FIRST = {"chmod", "chown", "chgrp", "install"}
_TARGET_FLAGS = ("-t", "--target-directory")
# Options of a generic mutator whose value is the next token, and so not a
# path: (letters, long names). `truncate -s 0 .qa/log` was refused because `0`
# resolved to `<checkout>/0` (T3-9). Read as an option's value rather than
# dropped as "the first operand" the way _MODE_FIRST drops a mode: that would
# let `truncate -s0 FILE` and `truncate --size=0 FILE`, whose size is attached,
# through with FILE unread.
_MUTATOR_VALUE_OPTS = {"truncate": ("sr", ("--size", "--reference")),
                       "mkfifo": ("m", ("--mode",))}
# Replace the file they are handed with a compressed (or decompressed) one.
# `gzip src/app.py` was an unknown command: measured, the source file was gone
# and `app.py.gz` stood in its place (K-D-11).
_COMPRESSORS = {"gzip", "gunzip", "bzip2", "bunzip2", "xz", "unxz", "zstd", "unzstd"}
# …unless told to write to stdout, or only to test or list. Keeping the
# original (`-k`) is not on this list: the new file still lands beside it.
_COMPRESSOR_READS = ("-c", "--stdout", "--to-stdout", "-t", "--test", "-l", "--list",
                     "-h", "--help", "-V", "--version", "-L", "--license")
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
    # The siblings the 0.44.0 sweep left out, each one a write to the working
    # tree, the index, the refs or the remotes (K-D-3): `git checkout-index -a
    # -f` and `git read-tree -m -u HEAD` rewrite the working tree outright.
    # `init` and `clone` are here for what they make possible as much as for
    # what they write: a `.git` in a subdirectory turns `<subdir>/.qa/` into a
    # QA root (qa_paths._in_team_qa_root asks only for a `.git` beside it).
    "checkout-index", "read-tree", "add", "mergetool", "fetch", "remote",
    "symbolic-ref", "clone", "init",
}
# What stays out, on purpose: the verbs that write only objects or packs under
# `.git` and never a file, ref or index entry a checkout would show —
# `hash-object -w`, `commit-tree`, `fast-import`, `unpack-objects`, `repack`,
# `pack-refs`, `maintenance`, `fsck --lost-found`, `lfs`.
# Read-only spellings that are a SUB-VERB: the word has to be the first
# operand after the verb. `git stash list` reads; `git branch list` CREATES A
# BRANCH CALLED list — measured, and the reason these two kinds had to be
# split (VERDICT-F-75). Denying `git submodule status` would still be the kind
# of false positive that gets strict mode switched off.
_GIT_READONLY_SUBVERBS = {
    "submodule": {"status", "summary"},
    "bisect": {"log", "view", "visualize", "help"},
    "notes": {"list", "show"},
    "sparse-checkout": {"list", "check-rules"},
    "stash": {"list", "show"},
    "reflog": {"show", "list", "exists"},
    "worktree": {"list"},
    "remote": {"show", "get-url"},
    # git 2.46's spelling of `git config --get` and `--list`. On an older git
    # both are an error (a key needs a section), so neither writes anywhere.
    "config": {"get", "list"},
}
# `git reflog` reads unless told to rewrite the log: its default sub-verb is
# `show`, so `git reflog HEAD` and `git reflog -n 5` name a ref and a count, not
# an action, and both were refused as mutations (T3-9).
_GIT_REFLOG_WRITES = {"expire", "delete", "drop"}
# Verbs whose bare form only reports: `git branch` lists, it does not create.
# `stash`, `gc` and `prune` are deliberately absent — bare, they all act.
# Read-only spellings that are a FLAG. For these verbs a bare operand is a
# name to create, so the word can never earn the exemption: `git branch --list`
# reads, `git branch list` does not. Measured against git 2.x before the model
# was written — the previous table gave `branch` and `tag` the word `list`,
# which is exactly backwards.
_GIT_READONLY_FLAGS = {
    "branch": {"--list", "-l", "--show-current", "-v", "-vv", "--verbose", "-a",
               "--all", "-r", "--remotes", "--contains", "--no-contains",
               "--merged", "--no-merged", "--points-at", "--format", "--sort",
               "--column", "-i", "--ignore-case"},
    "tag": {"--list", "-l", "-n", "--contains", "--no-contains", "--merged",
            "--no-merged", "--points-at", "--format", "--sort", "-i",
            "--ignore-case", "--column"},
    "config": {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--list",
               "-l", "--show-origin", "--show-scope"},
    "mergetool": {"--tool-help"},
}
# Flags that mutate whatever else is on the line. Present, the exemptions above
# do not apply: `git branch --list -D x` is a deletion with a listing flag on it.
_GIT_MUTATING_FLAGS = {
    "branch": {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy",
               "-f", "--force", "-u", "--set-upstream-to", "--unset-upstream",
               "--edit-description"},
    "tag": {"-d", "--delete", "-f", "--force", "-a", "--annotate", "-s",
            "--sign", "-m", "--message", "-F", "--file"},
    "config": {"--unset", "--unset-all", "--replace-all", "--add", "--rename-section",
               "--remove-section", "--edit", "-e"},
    "symbolic-ref": {"-d", "--delete"},
}
# The verbs for which `-n` is `--dry-run`, measured against git 2.50 (`git
# <verb> -h`) rather than assumed: for `commit` it is `--no-verify`, for
# `fetch` `--no-tags`, for `merge` and `pull` `--no-stat`. `git clean -n` was
# refused as a deletion (T3-9).
_GIT_DRY_RUN_N = {"clean", "add", "rm", "mv", "push", "prune", "read-tree"}
# Options whose value is a separate token. Their value is a value, whatever it
# looks like: `git commit -m "--dry-run"` really commits, and the guard read
# that message as a dry-run flag and stood aside (VERDICT-F-75). Deliberately
# short and certain — an option left out is read as boolean, which can only add
# a denial, while one wrongly listed swallows the token behind it.
_GIT_VALUE_OPTS = {"-m", "--message", "-F", "--file", "-C", "--reuse-message",
                   "--reedit-message", "--author", "--date", "--cleanup",
                   "--fixup", "--squash", "-t", "--track", "--onto",
                   "--contains", "--no-contains", "--merged", "--no-merged",
                   "--points-at", "--sort", "--format", "--set-upstream-to",
                   "-b", "-B", "--exec", "--strategy", "-s", "--strategy-option",
                   # `git notes --ref x list`: the ref's name was read as the
                   # sub-verb, and a listing refused as a mutation (T3-9).
                   "--ref"}
# The same, as short letters that can be bundled: `-am wip` is `-a -m wip`.
_GIT_VALUE_SHORTS = set("mFCtbBu")
_GIT_READONLY_BARE = {"branch", "tag", "reflog", "notes", "worktree",
                      "submodule", "bisect", "sparse-checkout", "config", "remote"}
# `git clone`'s options that take a separate value. Its operands decide where
# the new checkout lands, so a value misread as one names the wrong directory.
_GIT_CLONE_OPTS = ("boucj", ("--branch", "--origin", "--upload-pack", "--config", "--jobs",
                             "--depth", "--reference", "--reference-if-able",
                             "--separate-git-dir", "--template", "--filter",
                             "--shallow-since", "--shallow-exclude", "--server-option",
                             "--bundle-uri", "--revision"))
# git global flags that consume the following token as their value. -C and
# --work-tree also re-point the checkout the mutation lands in.
_GIT_TREE_FLAGS = {"-C", "--work-tree"}
_GIT_VALUE_FLAGS = {"-c", "--git-dir", "--namespace", "--exec-path",
                    "--super-prefix", "--config-env", "--attr-source"}
# What a wrapper reads before the command it runs: (letters that take a value,
# long options that take one as the next token, positional words of its own).
# A wrapper's own flags take values too — `sudo -u nobody rm x` left "nobody"
# as the head and the rm went unseen — but which flags is the wrapper's
# business. One set used to serve them all, and `-n` and `-p` were in it:
# booleans to sudo, time and command. So `sudo -n rm f`, `time -p rm f` and
# `command -p rm f` handed `rm` to the flag as its value, the FILE became the
# head, and no mutator was seen at all (K-D-7). An option left out of a row is
# read as a boolean, which can only add a denial; one wrongly listed swallows
# the command.
_WRAPPERS = {
    "env": ("uCPS", ("--unset", "--chdir", "--split-string"), 0),
    "sudo": ("ugCDhpRrTtU", ("--user", "--group", "--chdir", "--host", "--prompt",
                             "--chroot", "--role", "--type", "--other-user",
                             "--close-from", "--command-timeout"), 0),
    "doas": ("uC", (), 0),
    "command": ("", (), 0),
    "builtin": ("", (), 0),
    "nohup": ("", (), 0),
    "time": ("fo", ("--format", "--output"), 0),
    "exec": ("a", (), 0),
    "timeout": ("sk", ("--signal", "--kill-after"), 1),       # then DURATION
    "gtimeout": ("sk", ("--signal", "--kill-after"), 1),
    "nice": ("n", ("--adjustment",), 0),
    "ionice": ("cnpPu", ("--class", "--classdata", "--pid", "--pgid", "--uid"), 0),
    "stdbuf": ("ioe", ("--input", "--output", "--error"), 0),
    "setsid": ("", (), 0),
    "chrt": ("TPD", ("--sched-runtime", "--sched-period", "--sched-deadline"), 1),  # PRIORITY
    "taskset": ("", (), 1),                                   # then MASK, or after -c a LIST
    "caffeinate": ("tw", (), 0),
}
# Runners that start a program out of the project's own environment: (the
# sub-commands that run something — () when the runner itself does — then value
# letters and value longs, as above). A formatter is rarely typed bare: `uvx
# ruff format`, `npx prettier --write` and `python -m black` are the spellings a
# QA run uses, and this repository's own lint command is `uvx ruff check`. So
# the command behind a runner is read like any other.
_RUNNERS = {
    "uv": (("run",), "p", ("--python", "--with", "--with-editable", "--with-requirements",
                           "--project", "--package", "--group", "--extra", "--env-file",
                           "--index")),
    "uvx": ((), "p", ("--python", "--from", "--with", "--index")),
    "pipx": (("run",), "", ("--spec", "--python", "--pip-args")),
    "poetry": (("run",), "", ()),
    "pipenv": (("run",), "", ()),
    "pdm": (("run",), "p", ("--project",)),
    "hatch": (("run",), "", ()),
    "npx": ((), "pc", ("--package", "--call")),
    "bunx": ((), "", ()),
    "pnpm": (("exec", "dlx"), "", ()),
    "yarn": (("exec", "dlx"), "", ()),
    "npm": (("exec", "x"), "", ()),
}
_PYTHON = re.compile(r"^(?:python|pypy)[0-9.]*$")
# Formatters and fixers, in the shape in which they rewrite files (K-D-1, T0-8).
# Every one of these was an unknown command, and unknown commands are allowed:
# `black .`, `ruff format`, `gofmt -w`, `prettier --write`, `eslint --fix`,
# `isort .` and `pre-commit run` all passed. A tester running the project's own
# format step rewrites the code under test, and of every mutation this guard
# exists to stop it is the likeliest to happen by accident. The same commands
# asked only to report — `black --check`, `ruff format --diff`, `gofmt -l`,
# `prettier --check`, `cargo fmt --check` — are the lint gates of a QA run and
# stay allowed.
#
# (tool, sub-command or None): (how its options are spelled,
#     options that make it write — () for one that writes unless told not to,
#     options that make it only report,
#     value letters, value longs — for _WORDS, the bare names that take a value)
_GETOPT, _WORDS = "getopt", "words"
_RUFF_VALUES = ("--config", "--select", "--ignore", "--extend-select", "--extend-ignore",
                "--fixable", "--unfixable", "--line-length", "--target-version", "--exclude",
                "--extend-exclude", "--per-file-ignores", "--output-format", "--output-file",
                "--cache-dir", "--stdin-filename", "--range")
_BIOME = (_GETOPT, ("--write", "--apply", "--apply-unsafe", "--fix"), (), "",
          ("--config-path", "--max-diagnostics", "--indent-style", "--indent-width",
           "--line-width", "--files-max-size", "--stdin-file-path", "--colors",
           "--log-level", "--log-kind", "--diagnostic-level", "--reporter", "--since"))
_FORMATTERS = {
    ("black", None): (_GETOPT, (), ("--check", "--diff", "-c", "--code"), "ltWc",
                      ("--line-length", "--target-version", "--include", "--exclude",
                       "--extend-exclude", "--force-exclude", "--config", "--workers",
                       "--stdin-filename", "--required-version", "--code")),
    ("isort", None): (_GETOPT, (),
                      ("-c", "--check-only", "--check", "--diff", "--df", "-d", "--stdout",
                       "--show-files", "--show-config"), "abfijlmopstw",
                      ("--profile", "--settings-path", "--sp", "--settings-file", "--settings",
                       "--src", "--src-path", "--line-length", "--line-width", "--skip",
                       "--skip-glob", "--sg", "--multi-line", "--python-version", "--py",
                       "--jobs", "--filename")),
    ("autopep8", None): (_GETOPT, ("-i", "--in-place"), ("-d", "--diff"), "jp",
                         ("--max-line-length", "--ignore", "--select", "--exclude",
                          "--global-config", "--jobs", "--pep8-passes", "--indent-size")),
    ("yapf", None): (_GETOPT, ("-i", "--in-place"), ("-d", "--diff"), "el",
                     ("--style", "--exclude", "--lines")),
    ("ruff", "format"): (_GETOPT, (), ("--check", "--diff"), "", _RUFF_VALUES),
    # `--add-noqa` writes the suppression comments into the files it judged.
    ("ruff", "check"): (_GETOPT, ("--fix", "--fix-only", "--add-noqa"), ("--diff",), "o",
                        _RUFF_VALUES),
    ("gofmt", None): (_WORDS, ("w",), (), "", ("r", "cpuprofile")),
    ("goimports", None): (_WORDS, ("w",), (), "",
                          ("local", "srcdir", "cpuprofile", "memprofile", "trace")),
    ("prettier", None): (_GETOPT, ("--write", "-w"), (), "",
                         ("--config", "--ignore-path", "--parser", "--plugin", "--print-width",
                          "--tab-width", "--log-level", "--stdin-filepath", "--end-of-line",
                          "--quote-props", "--trailing-comma", "--arrow-parens",
                          "--prose-wrap", "--cache-location", "--cache-strategy")),
    ("eslint", None): (_GETOPT, ("--fix",), (), "cfo",
                       ("--config", "--ext", "--rule", "--rulesdir", "--plugin", "--parser",
                        "--parser-options", "--env", "--global", "--ignore-path",
                        "--ignore-pattern", "--format", "--output-file", "--max-warnings",
                        "--fix-type", "--cache-location", "--resolve-plugins-relative-to",
                        "--stdin-filename")),
    ("biome", "format"): _BIOME,
    ("biome", "check"): _BIOME,
    ("biome", "lint"): _BIOME,
    ("rustfmt", None): (_GETOPT, (), ("--check", "--print-config"), "",
                        ("--edition", "--style-edition", "--config", "--config-path", "--emit",
                         "--color", "--file-lines")),
    ("cargo", "fmt"): (_GETOPT, (), ("--check",), "p",
                       ("--package", "--manifest-path", "--message-format")),
    ("clang-format", None): (_WORDS, ("i",),
                             ("n", "dry-run", "output-replacements-xml", "dump-config"), "",
                             ("style", "assume-filename", "lines", "offset", "length", "files",
                              "fallback-style", "cursor")),
    ("swiftformat", None): (_GETOPT, (), ("--lint", "--dryrun"), "",
                            ("--config", "--swiftversion", "--rules", "--disable", "--enable",
                             "--exclude", "--indent", "--cache")),
    ("dart", "format"): (_GETOPT, (), (), "ol",
                         ("--output", "--line-length", "--language-version", "--page-width")),
    ("terraform", "fmt"): (_WORDS, (), ("check",), "", ()),
    ("shfmt", None): (_WORDS, ("w", "write"), (), "",
                      ("i", "indent", "ln", "language-dialect", "filename")),
    ("pre-commit", "run"): (_GETOPT, (), (), "cso",
                            ("--config", "--source", "--origin", "--from-ref", "--to-ref",
                             "--hook-stage")),
}
_FORMAT_TOOLS = {tool for tool, _verb in _FORMATTERS}
_FORMAT_VERBS = {tool for tool, verb in _FORMATTERS if verb}
_FORMAT_HELP = {_GETOPT: ("--help", "-h", "--version", "-V"), _WORDS: ("help", "h", "version")}
# Shells re-enter the same parser: `bash -c "rm x"` is not opaque the way an
# interpreter's `-c` is, and refusing to look inside it would be a choice.
_SHELLS = {"bash", "sh", "zsh", "dash", "ksh", "ash"}
# A shell's own options that take a separate value. Everything else before the
# script or the command string is a flag.
_SHELL_VALUE_FLAGS = ("-o", "+o", "-O", "+O", "--rcfile", "--init-file")
# How deep a shell inside a shell is followed. It was 3, and four levels of
# `bash -c "sh -c …"` walked out past it (K-D-9). The recursion is bounded by
# the command itself — every level parses a strictly shorter string — so this
# is a ceiling on pathology, not a budget.
_MAX_DEPTH = 8
# Words the shell reads in front of a command without their being part of it.
# `if true; then rm f; fi` handed `then` to the dispatcher as the command's
# name, and `rm` hid behind it as an argument (K-D-9). The condition of an
# `if` or a `while` is a command too.
_PREFIX_WORDS = {"{", "!", "then", "do", "else", "elif", "if", "while", "until"}
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
# The maintainer's two pens, as commands. The ledger FILES are refused to every
# writer (K-D-12), but the commands that write them were an unknown command to
# this guard: a tester could run `verdict-accept <project> <its own finding>
# --cite … --reason …` through Bash and accept its own findings' risks, or
# answer its own questions with `verdict-answer`. Found while K-D-12 was being
# closed (0.90.3). Reading a ledger is not writing it: `--list` and `--help`
# pass. Module name on the right: `python -m verdict_mcp.<module>` and
# `python …/verdict_mcp/<module>.py` are the same pens by another spelling.
_PENS = {"verdict-accept": "accept", "verdict-answer": "questions"}
_PEN_READS = frozenset({"--list", "--help", "-h"})
_PEN = "\x00pen"
# Targets that are not paths. They pass through every resolver untouched: joined to a
# directory, `\x00pen` became a path with a NUL in it and `realpath` raised — exit 1,
# which Claude Code reads as "the hook broke", not as a refusal.
_SENTINELS = (_UNKNOWABLE, _PEN)
# The head of a segment the walker made up: a heredoc body about to be read by
# a shell (`bash <<EOF`), handed on as the script it is.
_HEREDOC = "\x00heredoc"
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
# `<>` opens its target for reading AND writing, with or without a descriptor
# in front. The `>` in it follows a `<`, which is exactly what the pattern
# above refuses to start on, so `echo x 1<> src/app.py` was no redirect at all
# — measured, it wrote the file (K-D-10).
_REDIRECT_RW = re.compile(r"\d?<>")
# Every redirection operator, input ones included — not to judge them, but to
# take them OUT of a command before it is read as words. The tokenizer used to
# be handed the redirections along with the command, so `rm -f .qa/x
# 2>/dev/null` gave `rm` an operand called `2>/dev/null`, which resolved into
# the checkout and refused a deletion inside the QA root.
_REDIRECTION = re.compile(r"(?:(?<![^\s;|&(])\d+)?(?:&>>?|>\||>>?&?|<<<|<<-?|<>|<&?)")
_HEREDOC_OP = re.compile(r"(?<!<)<<(?!<)")
# One character standing in for text the shell would not read as syntax.
_MASK = "\x01"
# …and one for a heredoc body, which is not quoted text: it is a line of its
# own, and the walker has to be able to tell it from a command made only of
# quoted words (`"rm" "src/app.py"` is still an rm).
_BODY = "\x02"
# The `|` of a `>|` clobber-redirect is part of the operator, not a pipe. The
# whole command used to be scanned for redirects before it was split, so this
# never came up; scanning per segment made the split able to cut a redirect in
# half and lose its target.
_SEPARATOR = re.compile(r"(?:&&|\|\||[;\n]|(?<!>)\|)")
# A lone `&` ends a command too. Left in, `true & rm src/app.py` was one
# command called `true`. Not the `&` of `&&`, `&>`, `>&`, `<&` or `|&`.
_BACKGROUND = re.compile(r"(?<![<>&|])&(?![>&])")
_VAR = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
# `$(pwd)` and its backtick spelling: the one command substitution whose value
# the guard knows, because it is the directory the guard is tracking.
_PWD = re.compile(r"\$\(\s*pwd\s*\)|`\s*pwd\s*`")


def _strict() -> bool:
    return os.environ.get("VERDICT_STRICT", "") not in ("", "0", "false")


def _tmp_roots():
    # `/var/tmp` is as standard a scratch directory as `/tmp`, and a write
    # there was refused as a write outside every root (K-D-15). `/var/folders`
    # is not listed on purpose: the per-user directory under it is what
    # gettempdir() returns, and the rest of that tree is not scratch.
    roots = {"/tmp", "/private/tmp", "/var/tmp", "/private/var/tmp",
             tempfile.gettempdir(), os.environ.get("TMPDIR") or ""}
    return [os.path.realpath(r) for r in roots if r]


def _expand(target: str, cwd: str) -> str | None:
    """Substitute what can be known; None means an unresolved variable remains.

    `$PWD` is the directory the guard tracked to this command, not the one the
    hook process inherited: `cd .qa && echo x > $PWD/out` was judged against
    wherever Claude Code happened to start the hook.
    """
    expanded = _PWD.sub(lambda m: cwd, target)
    expanded = _VAR.sub(
        lambda m: cwd if m.group(1) == "PWD" else os.environ.get(m.group(1), m.group(0)),
        expanded)
    if "$" in expanded:
        return None
    return os.path.expanduser(expanded)


def _resolve(target: str, cwd: str) -> str | None:
    """Expand env vars and cwd; None means an unresolved variable remains."""
    expanded = _expand(target, cwd)
    if expanded is None:
        return None
    if not os.path.isabs(expanded):
        expanded = os.path.join(cwd, expanded)
    return os.path.normpath(expanded)


def _anchor(target: str, base: str) -> str:
    """Pin a relative target to the directory its command ran in.

    A nested shell that has done its own `cd`, `env -C DIR` and `git -C DIR`
    all run a command somewhere other than where the line stands. Their
    targets leave already resolved, or whoever reads them next resolves them
    against its own directory: `cd .qa && bash -c 'cd .. && echo x >
    src/app.py'` was a write into `.qa/src/`. Anything that is not a path —
    the stdin sentinel, a flag, a device — passes through untouched.
    """
    if not target or target in _SENTINELS or target.startswith(("&", "-", "/dev/")):
        return target
    expanded = _expand(target, base)
    if expanded is None:
        return target                # still a $variable: _target_ok refuses it by name
    return expanded if os.path.isabs(expanded) else os.path.join(base, expanded)


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
    if target == _PEN:
        return False, ("the maintainer's ledger — a decision about the tester's findings, "
                       "made by the maintainer from outside any QA session")
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
        return False, (f"{resolved} (the maintainer's ledger — written by "
                       f"{maintainer_pen(resolved)}, never by the tester)")
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
                out[k] = _BODY
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
    cuts = sorted([*_SEPARATOR.finditer(view), *_BACKGROUND.finditer(view)],
                  key=lambda m: m.start())
    for m in cuts:
        if command[start:m.start()].strip():
            out.append((sep, command[start:m.start()], view[start:m.start()]))
        start, sep = m.end(), m.group(0)
    if command[start:].strip():
        out.append((sep, command[start:], view[start:]))
    return out


def _word_at(text: str, i: int):
    """Read one shell word out of `text` starting at `i`, honouring quotes:
    (the word, the index just past it).

    A `)` ends the word unless the word opened it: `(echo x > src/app.py)`
    names `src/app.py`, while `$(pwd)/out` and `>(tee f)` are one word each.
    """
    n = len(text)
    while i < n and text[i] in " \t":
        i += 1
    out, depth = [], 0
    while i < n:
        ch = text[i]
        if depth == 0 and (ch in " \t\n;|&<>" or ch == ")"):
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
        depth += (ch == "(") - (ch == ")")
        out.append(ch)
        i += 1
    return "".join(out), i


def _token_after(text: str, i: int) -> str:
    return _word_at(text, i)[0]


def _redirect_targets(text: str, view: str):
    for m in _REDIRECT.finditer(view):
        end = m.end()
        if text[end:end + 1] == "&":
            # `>&` is two things. `>&2` and `>&-` duplicate or close a
            # descriptor; `>&file` is `&>file` spelled the csh way, and
            # truncates the file. Every `&…` target used to be waved through
            # as the first kind, so `echo x >& src/app.py` wrote the file —
            # measured (K-D-10). A word that is a number or `-` is a
            # descriptor; anything else is a file.
            word = _token_after(text, end + 1)
            if word and word != "-" and not word.isdigit():
                yield word
            continue
        target = _token_after(text, end)
        if target:
            yield target
    for m in _REDIRECT_RW.finditer(view):
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


def _own_shell(toks):
    """Past the words that still run a builtin in THIS shell: `command cd x`,
    `builtin cd x`, `time cd x`. No other wrapper is one of them — `sudo cd x`
    and `env cd x` move a process that then exits, and the line stays where it
    was."""
    while toks and os.path.basename(toks[0]) in ("command", "builtin", "time"):
        toks = toks[1:]
        while toks and toks[0].startswith("-"):
            if toks[0] in ("-v", "-V"):
                return []           # `command -v cd` asks about cd; it does not run it
            toks = toks[1:]
    return toks


def _moves(toks) -> bool:
    toks = _own_shell(toks)
    return bool(toks) and os.path.basename(toks[0]) in ("cd", "pushd", "popd")


class _Trail:
    """The directory each simple command of one command line runs in.

    The guard used to follow `cd DIR` and nothing else, and to forget even that
    at every `|` (K-D-8). Both directions were measured. A relative write that
    really landed in the checkout was allowed — `cd .qa && cd - && echo x >
    src/app.py`, `pushd .qa && echo x > ../src/app.py` — because the guard
    still believed it stood in `.qa`. And a write into `.qa` was refused: `cd
    .qa && pytest 2>&1 | tee report.log` put `report.log` in the checkout,
    because a pipe reset the directory to the tool's own.

    What it follows now: `cd DIR`, `cd -`, bare `cd`, `pushd` and `popd`; `$PWD`
    and `$OLDPWD` as it has tracked them; a `( … )` subshell, which puts the
    directory back when it closes. Every stage of a pipeline runs in the
    directory in effect where the pipeline starts, and a `cd` inside one moves
    nobody — except in the LAST stage, which zsh runs in the current shell and
    bash does not; that leaves the directory unknown.

    Unknown is a state, not a guess. A `cd "$(git rev-parse --show-toplevel)"`
    or a `cd $VAR` the environment cannot resolve leaves `here` as None, and
    from there a relative target is judged against `root` — the directory the
    line started in: the tool's cwd, or for a nested shell the directory of the
    command that started it. Denied if that resolution is outside scope,
    allowed if it is inside. The alternatives were to keep believing the last
    directory that was known, which is how `cd .qa && cd "$X" && echo x > f`
    would be judged a write into `.qa`, or to refuse every relative target
    after such a `cd`, which refuses `cd "$(git rev-parse --show-toplevel)" &&
    pytest > .qa/out.txt` — the commonest way a run gets to the top of a
    repository.

    A `cd` is taken to succeed, as it always was: this is the directory the
    command line asks for, not the one it gets.
    """

    def __init__(self, root):
        self.root = root            # where the line starts, and where it is judged once lost
        self.here = root            # None once a `cd` could not be followed
        self.old = None             # $OLDPWD: where `cd -` goes
        self.stack = []             # pushd / popd
        self.scopes = []            # an open `(`: what its `)` puts back
        self.base = root            # the directory of the segment in hand — always a real one

    def walk(self, command, view=None):
        """Yield (separator-before, text, masked) for each simple command,
        with `base` set to the directory that command runs in."""
        segments = _segments(command, view)
        script = False
        for i, (sep, segment, seg_view) in enumerate(segments):
            if _BODY in seg_view and not seg_view.strip(_BODY + " \t\r"):
                # A heredoc body, and nothing else. It used to be tokenized as a
                # command: main() scanned redirects on the masked view and then
                # handed the RAW text to the tokenizer, so `cat > .qa/notes.md
                # <<'EOF'` whose body began with `rm` or `cp` was refused for a
                # deletion it only quoted (K-D-4, the half of VERDICT-F-22 that
                # was not fixed). A body is data — unless the command it feeds
                # is a shell, and then it is the script.
                if script:
                    self.base = self.here or self.root
                    yield sep, _HEREDOC + _heredoc_script(segment), ""
                script = False
                continue
            toks = _tokens(segment, seg_view)
            feeds_shell = "<<" in seg_view and _reads_script_from_stdin(toks, self.root)
            if feeds_shell and _HEREDOC_OP.search(seg_view):
                script = True
            opened = 0
            for ch in seg_view:
                if ch == "(":
                    opened += 1
                elif ch not in " \t":
                    break
            for _ in range(opened):
                self.scopes.append((self.here, self.old, list(self.stack)))
            self.base = self.here or self.root
            yield sep, segment, seg_view
            if feeds_shell and "<<<" in seg_view:
                # `bash <<<'rm f'`: the same script, handed over as one word.
                word = _word_at(segment, seg_view.index("<<<") + 3)[0]
                yield sep, _HEREDOC + word + "\n", ""
            piped_on = i + 1 < len(segments) and segments[i + 1][0] == "|"
            if sep != "|" and not piped_on:
                self._step(toks)
            elif not piped_on and _moves(toks):
                self.here = None    # the last stage: the current shell in zsh, a subshell in bash
            net = seg_view.count("(") - opened - seg_view.count(")")
            for _ in range(net):
                self.scopes.append((self.here, self.old, list(self.stack)))
            for _ in range(-net):
                if self.scopes:
                    self.here, self.old, self.stack = self.scopes.pop()

    def _step(self, toks):
        """Follow one `cd`, `pushd` or `popd`."""
        if not _moves(toks):
            return
        toks = _own_shell(toks)
        head = os.path.basename(toks[0])
        # (unquoted: the Windows tokenizer leaves the quotes on `cd "…"`)
        words = [_unquote_nested(t) for t in toks[1:]
                 if t == "-" or not t.startswith(("-", "+"))]
        if head == "popd" or (head == "pushd" and not words):
            # `popd` returns to the top of the stack; a bare `pushd` swaps with
            # it. `pushd +2` rotates, and that arithmetic is not followed.
            there = self.stack.pop() if (self.stack and len(toks) == 1) else None
            if head == "pushd":
                self.stack.append(self.here)
        else:
            if head == "pushd":
                self.stack.append(self.here)
            if not words:
                there = os.path.expanduser("~")     # a bare `cd` goes home
            elif words[0] == "-":
                there = self.old
            else:
                there = self._follow(words[0])
        self.old, self.here = self.here, there

    def _follow(self, word):
        """Where `cd WORD` lands, or None when the command line does not say."""
        def known(m):
            name = m.group(1)
            if name in ("PWD", "OLDPWD"):
                return (self.here if name == "PWD" else self.old) or m.group(0)
            return os.environ.get(name, m.group(0))
        word = _VAR.sub(known, _PWD.sub(lambda m: self.here or m.group(0), word))
        if "$" in word or "`" in word:
            return None             # a substitution only the shell can make
        if self.here is None and not os.path.isabs(os.path.expanduser(word)):
            return None             # relative to a directory already lost
        return _cd_target(["cd", word], self.here or self.root)


def _heredoc_script(segment: str) -> str:
    """A heredoc body without its closing delimiter, as the script it is.

    The newline at the end is load-bearing: `_unquote_nested` strips a pair of
    quotes that wrap the whole text, and a script that merely starts and ends
    on a quote is not wrapped in them."""
    lines = segment.rstrip().split("\n")
    return "\n".join(lines[:-1]) + "\n"


def _reads_script_from_stdin(toks, cwd) -> bool:
    """Is this command a shell that will run what arrives on its stdin?

    `bash <<EOF` and `bash -s <<EOF` do. `bash -c '…' <<EOF` and `bash run.sh
    <<EOF` have their script already, and the heredoc is its input."""
    while toks and os.path.basename(toks[0]) in _WRAPPERS:
        toks = _unwrap(os.path.basename(toks[0]), toks[1:], cwd)[0]
    if not toks or os.path.basename(toks[0]) not in _SHELLS:
        return False
    args, stdin, i = toks[1:], False, 0
    while i < len(args):
        tok = args[i]
        if _command_string_flag(tok):
            return False
        if tok in _SHELL_VALUE_FLAGS:
            i += 1
        elif tok == "-s":
            stdin = True
        elif not tok.startswith(("-", "+")):
            return stdin
        i += 1
    return True


def _getopt(args, shorts="", longs=(), stop=False):
    """Walk `args` the way getopt would and return (options, operands).

    `shorts` are the letters that take a value — attached (`-oFILE`) or as the
    next token — and `longs` the long names that take one as their next token;
    `--name=VALUE` always carries its own. An option that is not listed is
    read as a boolean, the same choice `_GIT_VALUE_OPTS` makes and for the
    same reason: left out, its value falls through as an operand, which can
    only add a denial, while one wrongly listed swallows the token behind it.

    `stop` ends the options at the first operand, which is how a wrapper reads
    its own line — everything from there on belongs to the command it runs.
    """
    options, operands = [], []
    i, n = 0, len(args)
    while i < n:
        tok = args[i]
        i += 1
        if tok == "--":
            operands.extend(args[i:])
            break
        if tok.startswith("--"):
            name, sep, value = tok.partition("=")
            if not sep and name in longs and i < n:
                sep, value, i = "=", args[i], i + 1
            options.append((name, value if sep else None))
        elif tok.startswith("-") and len(tok) > 1:
            letters = tok[1:]
            while letters:
                ch, letters = letters[0], letters[1:]
                if ch not in shorts:
                    options.append(("-" + ch, None))
                elif letters:
                    options.append(("-" + ch, letters))
                    letters = ""
                else:
                    options.append(("-" + ch, args[i] if i < n else None))
                    i += 1
        elif stop:
            operands.extend(args[i - 1:])
            break
        else:
            operands.append(tok)
    return options, operands


def _without_redirections(text: str, view: str) -> str:
    """`text` with every redirection — operator and word — blanked out.

    Where they are is decided on the masked view, so a `>` inside quotes stays
    text. A `<(…)` or `>(…)` is not a redirection: it is an operand that
    happens to be a pipe, and stays."""
    out, done = list(text), 0
    for m in _REDIRECTION.finditer(view):
        if m.start() < done:
            continue                # inside a word an earlier operator already took
        if m.group(0)[-1] in "<>" and text[m.end():m.end() + 1] == "(":
            continue
        done = _word_at(text, m.end())[1]
        for k in range(m.start(), done):
            out[k] = " "
    return "".join(out)


def _tokens(segment: str, view: str | None = None):
    """One simple command as words: its redirections taken out, and the
    syntax the shell allows in front of a command taken off."""
    if segment.startswith(_HEREDOC):
        return [_HEREDOC, segment[len(_HEREDOC):]]
    if view is None:
        view = _mask_quoted(segment)[0]
    text = _without_redirections(segment, view)
    try:
        # posix=True on Windows would eat path backslashes as escapes,
        # mangling every target it is supposed to judge.
        toks = shlex.split(text, posix=(os.name != "nt"))
    except ValueError:
        toks = text.split()
    # What a command word can hide behind (K-D-9). `(rm src/app.py)` made the
    # head `(rm`, `{ rm src/app.py; }` made it `{`, and `if true; then rm
    # src/app.py; fi` made it `then` — measured for the first: the file was
    # gone. `|&` leaves its `&` on the next command the same way.
    opened = 0
    while toks:
        head = toks[0]
        if head in _PREFIX_WORDS or _ASSIGNMENT.match(head):
            toks = toks[1:]
        elif head[:1] in ("(", "&"):
            opened += head[0] == "("
            toks = ([head[1:]] if head[1:] else []) + toks[1:]
        else:
            break
    # …and the `)` that closes a subshell, off the last word: as many as this
    # command closes without having opened them after its first word.
    closing = opened + view.count(")") - view.count("(")
    while closing > 0 and toks and toks[-1].endswith(")"):
        toks[-1] = toks[-1][:-1]
        closing -= 1
        if not toks[-1]:
            toks.pop()
    return toks


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


def _command_string_flag(tok: str) -> bool:
    """Is this the shell option that takes a command string — alone or bundled?

    `bash -lc 'rm f'`, `-ec` and `-xc` are how a command string is usually
    passed, and an exact match on `-c` read none of them: measured, the file
    was gone (K-D-9). One dash and letters only: a long option has a `c` in it
    too (`--norc`, `--rcfile`), and read as this flag it would take the word
    after it for the command and stop looking for the real one.
    """
    return tok[:1] == "-" and tok[1:].isalpha() and "c" in tok[1:]


def _check_shell(args, cwd, depth):
    """`bash -c "rm x"` is shell inside shell, and this module parses shell:
    declining to look would be a choice, not a limit."""
    trail = _Trail(cwd)
    for what, target in _shell_hits(args, trail, depth):
        # A nested shell does its own `cd`. Its targets leave pinned to the
        # directory it had reached, or the caller reads them against its own.
        yield what, _anchor(target, trail.base)


def _shell_hits(args, trail, depth):
    skip = False
    for i, t in enumerate(args):
        if skip:
            skip = False
            continue
        if _command_string_flag(t) and i + 1 < len(args):
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
            for _sep, seg, seg_view in trail.walk(nested):
                cwd = trail.base
                for target in _redirect_targets(seg, seg_view):
                    yield "output redirection", target
                yield from _check_segment(_tokens(seg), cwd, depth + 1)
            return
        if t in _SHELL_VALUE_FLAGS:
            skip = True
        elif not t.startswith(("-", "+")):
            return          # a script file: what follows are its arguments, not the shell's


def _check_eval(args, cwd, depth):
    """`eval` re-enters the parser with its arguments joined — a shell by
    another name, and this module parses shell.

    It earns its own branch because of how redirects are found now: the outer
    scan reads a masked view, where everything inside `eval "... > file"` is
    quoted text. The raw scan used to catch that by accident; nothing else
    would.
    """
    yield from _check_shell(["-c", " ".join(args)], cwd, depth)


def _check_xargs(head, args, cwd, depth):
    """`xargs CMD` runs CMD on operands that arrive on stdin.

    Those operands cannot be read off the command line, which is the case the
    unresolved-$variable rule refuses. But whether that MATTERS is a question
    about CMD, and it used to be answered by its name: `rm`, `git`, `sed` and
    `perl` were refused whatever they were asked to do, and nothing else was.
    So `git ls-files | xargs git log --` and `xargs sed -n p` were refused —
    reads — while `xargs bash -c 'rm $0'` went through (K-D-6).

    Now CMD is read the way any command is, with the sentinel standing where
    stdin's words will land: after the last argument, or wherever `-I {}` puts
    them. A target that turns out to BE the sentinel is refused; one the
    command line spells out is judged as written.
    """
    values = "jNnLSaI" if head == "parallel" else "adEILnPsJRS"
    options, command = _getopt(args, values, ("--max-args", "--max-procs", "--delimiter",
                                              "--arg-file", "--max-chars", "--jobs"),
                               stop=True)
    if not command:
        return
    slot = "{}" if head == "parallel" else None
    for name, value in options:
        if name in ("-I", "-J") and value:
            slot = value
        elif name in ("-i", "--replace"):
            slot = value or "{}"
    for tok in args[:len(args) - len(command)]:
        if tok.startswith("-i") and len(tok) > 2 and not tok.startswith("--"):
            slot = tok[2:]          # GNU's `-i{}`: the replacement string rides on the flag
    if slot and any(slot in tok for tok in command):
        command = [tok.replace(slot, _UNKNOWABLE) for tok in command]
    else:
        command = command + [_UNKNOWABLE]
    for what, target in _check_segment(command, cwd, depth):
        if _UNKNOWABLE in target:
            yield (f"{head} {what} (targets arrive on stdin and cannot be checked)",
                   _UNKNOWABLE)
        else:
            yield f"{head} {what}", target


def _is_backup_suffix(word: str) -> bool:
    """Could this word be the backup suffix BSD sed reads after `-i`?"""
    word = _unquote_nested(word)
    return word == "" or word[:1] in (".", "~", "_")


def _check_stream_editor(head, args):
    """Which files does this sed or perl command edit in place?

    `-i` is rarely written alone: `perl -pi -e` clusters it behind -p and
    `sed --in-place` spells it out. A startswith("-i") test saw neither. Nor
    is a token an `-i` because it has an `i` in it: `perl -Mstrict -ne print
    f` was read as an in-place edit, and options are walked the way the tool
    walks them now.

    And the files are not "every word that is not a flag". The script is a
    word too, and it used to be yielded as a path: `sed -i 's/a/b/'
    .qa/notes.md` was refused because `s/a/b/` resolved into the checkout,
    with the script named as the target — every in-place edit inside the QA
    root, on every platform (K-D-5). With no `-e` or `-f`, the first operand
    is the script and the files follow it.
    """
    perl = head.startswith("perl")
    in_place = scripted = False
    operands, suffix = [], ""
    i, n = 0, len(args)
    while i < n:
        tok = args[i]
        i += 1
        if tok == "--":
            operands.extend(args[i:])
            break
        if tok.startswith("--"):
            name, sep, _value = tok.partition("=")
            if name == "--in-place":
                in_place = True
            elif name in ("--expression", "--file", "--line-length"):
                scripted = scripted or name != "--line-length"
                i += 0 if sep else 1
            continue
        if not tok.startswith("-") or len(tok) == 1:
            operands.append(tok)
            continue
        letters = tok[1:]
        while letters:
            ch, letters = letters[0], letters[1:]
            if ch == "i" or (ch == "I" and not perl):
                # What is left of the token is the backup suffix. BSD sed wants
                # the suffix as a word of its own — `sed -i '' …`, `sed -i .bak
                # …` — where GNU sed would take that word for the script. A
                # word that is empty, or that starts like a suffix and like no
                # sed command, is read the BSD way: to GNU sed it is a script
                # that does not run, so neither reading loses a file.
                in_place = True
                if not perl and not letters and i < n and _is_backup_suffix(args[i]):
                    suffix = _unquote_nested(args[i])
                    i += 1
                letters = ""
            elif (ch in "ef" and not (perl and ch == "f")) or (perl and ch == "E"):
                scripted = True     # the script: attached, or the next word
                i += 0 if letters else 1
                letters = ""
            elif perl and ch == "I":
                i += 0 if letters else 1
                letters = ""
            elif perl and ch in "MmFxCDdV":
                letters = ""        # the rest of the token is this switch's own value
            elif perl and ch in "0l":
                letters = letters.lstrip("01234567")
            elif not perl and ch == "l" and not letters and i < n and args[i].isdigit():
                i += 1              # GNU sed's `-l N`; BSD's `-l` takes nothing
    if not in_place:
        return
    files = operands if scripted else operands[1:]
    if suffix and (scripted or not files):
        # …except where GNU sed's reading does run: the script came by `-e`, so
        # the word after `-i` is not the script but the first FILE. `sed -e
        # s/a/b/ -i .env` edits `.env` there, and is an error under BSD.
        files = [suffix] + files
    for path in files:
        yield f"{head} in-place", path


def _git_operands(rest):
    """(flags, operands) after the verb, with option values consumed.

    A token is only a flag if it arrives in a flag's position. Scanning for a
    name in ANY role is what let `git commit -m "--dry-run"` through: the
    message was read as a dry-run flag and the whole authorization decision
    stood aside (VERDICT-F-75). Short options bundle and may carry their value
    attached, exactly as tar's do.
    """
    flags, operands = [], []
    it = iter(rest)
    for t in it:
        if t == "--":
            operands.extend(it)
            break
        if t.startswith("--"):
            name, sep, _ = t.partition("=")
            flags.append(name)
            if not sep and name in _GIT_VALUE_OPTS:
                next(it, None)
        elif t.startswith("-") and len(t) > 1:
            letters = t[1:]
            while letters:
                ch, letters = letters[0], letters[1:]
                flags.append("-" + ch)
                if ch in _GIT_VALUE_SHORTS:
                    if not letters:
                        next(it, None)      # the value is the next token
                    letters = ""            # …or the rest of this one
        else:
            operands.append(t)
    return flags, operands


def _git_outputs(verb, rest, there):
    """The files a READ verb is told to write (K-D-2).

    `git log --output=src/app.py` overwrites a tracked file — measured — and
    the handler returned before it looked, because `log` is in no mutator set.
    Every verb that can print a diff takes `--output`, and that includes `stash
    show` and `reflog show`, whose sub-verbs had earned them a read-only
    exemption: measured on git 2.50, both write the file. `shortlog` and
    `archive` have an `--output` of their own, `format-patch` writes a
    directory of patches, and `bundle create` writes a pack. So the option is
    looked for on every verb, before anything asks whether the verb mutates.
    """
    words = rest[:rest.index("--")] if "--" in rest else rest    # past `--`: pathspecs
    lettered = verb in ("format-patch", "archive")    # the two verbs whose `-o` is an output
    named = False
    for i, tok in enumerate(words):
        name, sep, value = tok.partition("=")
        if len(name) > 2 and ("--output".startswith(name) or (
                verb == "format-patch" and name.startswith("--output")
                and "--output-directory".startswith(name))):
            value = value if sep else "".join(words[i + 1:i + 2])
        elif lettered and tok.startswith("-o") and not tok.startswith("--"):
            name, value = "-o", tok[2:] or "".join(words[i + 1:i + 2])
        else:
            continue
        named = True
        if value:
            yield f"git {verb} {name} (writes the file it names)", _anchor(value, there)
    if verb == "bundle":
        operands = [t for t in words if not t.startswith("-")]
        if operands[:1] == ["create"] and len(operands) > 1:
            yield "git bundle create (writes the bundle)", _anchor(operands[1], there)
    elif verb == "format-patch" and not named and "--stdout" not in words:
        yield "git format-patch (writes its patches where it stands)", there


def _check_git(args, cwd, depth=0):
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
    rest = list(it)
    if verb is None or rest[:1] == ["--help"]:
        # `git commit --help` opens the manual, and was refused as a commit
        # (T3-9). Only as the first word after the verb, which is where git
        # itself turns it into `git help <verb>`: further along it can be a
        # value — `git commit -m "--help" -a` really commits, measured.
        return
    there = _anchor(repo, cwd)
    yield from _git_outputs(verb, rest, there)
    if verb not in _GIT_MUTATORS:
        return
    if verb in ("clone", "init"):
        # Both make a repository: in the directory they are given, or in the
        # one they stand in. Judged by where it lands, because cloning INTO
        # scratch is how a run gets a copy it may change.
        values = _GIT_CLONE_OPTS if verb == "clone" else (
            "b", ("--template", "--separate-git-dir", "--object-format", "--initial-branch"))
        operands = _getopt(rest, *values)[1]
        where = operands[1:2] if verb == "clone" else operands[:1]
        yield (f"git {verb} (creates a repository)",
               _anchor(where[0], there) if where else repo)
        return
    flags, operands = _git_operands(rest)
    if verb == "submodule" and operands[:1] == ["foreach"]:
        # Runs a command in every submodule. What that command does is its own
        # business, and it is read like any other: `git submodule foreach git
        # status` was refused as a mutation (T3-9).
        command = rest[rest.index("foreach") + 1:]
        while command and command[0] in ("--recursive", "-q", "--quiet"):
            command = command[1:]
        if len(command) == 1:
            yield from _check_shell(["-c", command[0]], there, depth)
        else:
            yield from _check_segment(command, there, depth)
        return
    # A dry run is a flag in a flag's position, and only for the verbs that
    # have one. `--check` belongs to `apply`/`am`; elsewhere git rejects it,
    # and reading it as an exemption made `git push origin main --check` an
    # allowed push-shaped command (VERDICT-F-75).
    #
    # And a dry run can be taken back. git spells the option `--[no-]dry-run`:
    # measured on 2.50, `git clean -n --no-dry-run -f` deletes, and so does the
    # abbreviation `--no-dry`. Either one anywhere on the line and this is not
    # a dry run, whatever else it says.
    if not any(len(f) > 5 and "--no-dry-run".startswith(f) for f in flags):
        if "--dry-run" in flags or ("--check" in flags and verb in ("apply", "am")):
            return
        if "-n" in flags and verb in _GIT_DRY_RUN_N:
            return
    mutating = _GIT_MUTATING_FLAGS.get(verb, set())
    if not any(f in mutating for f in flags):
        # A sub-verb exemption must be the FIRST operand: `git stash list`
        # reads, and `git stash push list` does not.
        if operands and operands[0] in _GIT_READONLY_SUBVERBS.get(verb, set()):
            return
        readonly = _GIT_READONLY_FLAGS.get(verb, set())
        if readonly and any(f in readonly for f in flags):
            return                # `git branch --show-current`, `git tag -n`
        if not operands and verb in _GIT_READONLY_BARE:
            return                # `git branch`, `git tag`: listings
        if verb == "config" and len(operands) <= 1:
            return                # `git config user.name` reads; a value writes
        if verb == "symbolic-ref" and len(operands) <= 1:
            return                # `git symbolic-ref HEAD` reads; a second name writes
        if verb == "reflog" and operands[0] not in _GIT_REFLOG_WRITES:
            return                # `git reflog HEAD`, `git reflog -n 5`: the default is `show`
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


def _is_relative(target: str) -> bool:
    return (bool(target) and target not in _SENTINELS
            and not target.startswith(("&", "-", "/dev/", "~", "$"))
            and not os.path.isabs(target))


def _check_find(args, cwd, depth=0):
    """Which paths does this find command delete, write, or hand to a command
    that does?

    `-delete` aside, this used to ask one question: is the word after `-exec`
    a known mutator? So `find src -exec sed -i s/a/b/ {} \\;` went through —
    measured, it rewrote the file — and with it `-exec sh -c …`, `-ok`, which
    is `-exec` with a prompt, and `-fprint FILE`, which writes a file without
    running anything (K-D-6). The command after `-exec` is a simple command
    and is read as one. Where it names `{}`, the file is whatever find
    matched: somewhere under its starting points.
    """
    i = 0
    while i < len(args) and (args[i] in ("-H", "-L", "-P", "-E", "-X", "-d", "-s", "-x")
                             or args[i].startswith("-O")):
        i += 1                      # find's own options come before its starting points
    roots = []
    while i < len(args) and not args[i].startswith(("-", "(", "!")):
        roots.append(args[i])
        i += 1
    roots = roots or [cwd]
    expr = args[i:]
    j = 0
    while j < len(expr):
        tok = expr[j]
        if tok == "-delete":
            for root in roots:
                yield "find -delete", root
        elif tok in ("-fprint", "-fprint0", "-fprintf", "-fls") and j + 1 < len(expr):
            j += 1
            yield f"find {tok} (writes the file it names)", expr[j]
        elif tok in ("-exec", "-execdir", "-ok", "-okdir"):
            end = j + 1
            while end < len(expr) and expr[end] not in (";", "+"):
                end += 1
            beside = tok in ("-execdir", "-okdir")      # runs in each match's own directory
            for what, target in _check_segment(expr[j + 1:end], cwd, depth):
                if "{}" in target or (beside and _is_relative(target)):
                    for root in roots:
                        yield f"find {tok} {what}", root
                else:
                    yield f"find {tok} {what}", target
            j = end
        j += 1


def _unwrap(head, args, cwd):
    """Read one wrapper's own arguments: (the command behind it, the directory
    it runs that command in, the files the wrapper itself writes)."""
    shorts, longs, positionals = _WRAPPERS[head]
    options, rest = _getopt(args, shorts, longs, stop=True)
    values = dict(options)
    there, writes = cwd, []
    if head == "env":
        split = values.get("-S") or values.get("--split-string")
        if split:                   # `env -S 'rm f'`: the command, as one string
            split = _unquote_nested(split)
            try:
                rest = shlex.split(split) + rest
            except ValueError:
                rest = split.split() + rest
        while rest and _ASSIGNMENT.match(rest[0]):
            rest = rest[1:]
    if head in ("env", "sudo"):
        chdir = values.get("-C" if head == "env" else "-D") or values.get("--chdir")
        if chdir:
            there = _anchor(chdir, cwd)
    if head == "time":
        report = values.get("-o") or values.get("--output")
        if report:
            writes.append(("time -o (writes its report)", report))
    if head == "command" and ("-v" in values or "-V" in values):
        rest = []                   # asks where a command is; runs nothing
    return rest[positionals:], there, writes


def _check_wrapper(head, args, cwd, depth):
    """`sudo -n rm f`, `timeout 5 rm f`, `env -C src rm f`: the command behind
    a wrapper is a simple command, read in the directory the wrapper runs it
    in."""
    there = cwd
    while True:
        stood = there
        command, there, writes = _unwrap(head, args, there)
        for what, target in writes:
            yield what, (target if stood == cwd else _anchor(target, stood))
        head = os.path.basename(command[0]) if command else ""
        if head not in _WRAPPERS:
            break                   # `sudo env nice timeout 5 …`: walked, not recursed into
        args = command[1:]
    for what, target in _check_segment(command, there, depth):
        yield what, (target if there == cwd else _anchor(target, there))


def _check_runner(head, args, cwd, depth):
    """`uvx ruff format`, `npx prettier --write`, `poetry run black .`: the
    program a runner starts, read as if it had been typed bare. A runner's
    other sub-commands (`uv pip install`, `npm test`) run nothing this guard
    can read, and pass."""
    verbs, shorts, longs = _RUNNERS[head]
    if verbs:
        i = 0
        while i < len(args) and args[i].startswith("-"):
            i += 1
        if i >= len(args) or args[i] not in verbs:
            return
        args = args[i + 1:]
    options, command = _getopt(args, shorts, longs, stop=True)
    values = dict(options)
    call = head == "npx" and (values.get("-c") or values.get("--call"))
    if call:
        yield from _check_shell(["-c", call], cwd, depth)
    elif command:
        # `ruff@0.6.9`, `@biomejs/biome@1.9`: a package, by the name it runs under.
        name = os.path.basename(command[0])
        yield from _check_segment([name.split("@", 1)[0] or name] + command[1:], cwd, depth)


def _python_module(args):
    """`python -m black .` is black: [module, *its arguments]. None when python
    is running anything else — a script, stdin, `-c` — which is an interpreter
    at work, and this guard does not read those."""
    i = 0
    while i < len(args):
        tok = args[i]
        if (tok.endswith("m") and tok.startswith("-") and not tok.startswith("--")
                and tok[1:].isalpha() and i + 1 < len(args)):
            return [args[i + 1].replace("_", "-")] + args[i + 2:]
        if tok in ("-W", "-X"):
            i += 1
        elif not tok.startswith("-") or tok in ("-", "-c"):
            return None
        i += 1
    return None


def _word_options(args, valued):
    """Options the way Go's `flag` and LLVM's `cl` read them: one word each,
    one dash or two, never bundled. `-check` is one flag, not five letters."""
    options, operands = [], []
    i, n = 0, len(args)
    while i < n:
        tok = args[i]
        i += 1
        if tok == "--":
            operands.extend(args[i:])
            break
        if tok.startswith("-") and len(tok) > 1:
            name, sep, value = tok.lstrip("-").partition("=")
            if not sep and name in valued and i < n:
                sep, value, i = "=", args[i], i + 1
            options.append((name, value if sep else None))
        else:
            operands.append(tok)
    return options, operands


def _nearest(start: str, marker: str) -> str:
    """The closest directory at or above `start` that holds `marker`, else `start`."""
    d = start
    while True:
        if os.path.exists(os.path.join(d, marker)):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            return start
        d = parent


def _check_formatter(head, args, cwd):
    """Is this formatter being run in the shape that rewrites files, and which?

    See _FORMATTERS. The files are its operands, or where it stands when it is
    given none — a run over a scratch copy, or over notes inside `.qa/`, is
    nobody's code under test.
    """
    verb = None
    if head in _FORMAT_VERBS:
        # The sub-command is the first word that is not an option (or cargo's
        # `+toolchain`).
        for i, tok in enumerate(args):
            if not tok.startswith(("-", "+")):
                verb, args = tok, args[:i] + args[i + 1:]
                break
    rule = _FORMATTERS.get((head, verb))
    if rule is None:
        return
    style, writes, reads, shorts, longs = rule
    if style == _WORDS:
        options, operands = _word_options(args, longs)
    else:
        options, operands = _getopt(args, shorts, longs)
    values = dict(options)
    names = set(values)
    if names.intersection(_FORMAT_HELP[style]) or names.intersection(reads):
        return
    if writes and not names.intersection(writes):
        return
    # Four that say "only report" through a value rather than a flag of its own.
    if head == "terraform" and values.get("write") == "false":
        return
    if head == "terraform" and values.get("chdir"):
        cwd = _anchor(values["chdir"], cwd)     # and that is where it formats
        operands = [_anchor(p, cwd) for p in operands]
    if head == "dart" and (values.get("-o") or values.get("--output")) in ("show", "json", "none"):
        return
    if head == "rustfmt" and values.get("--emit") not in (None, "files"):
        return
    if head == "cargo" and "--check" in args:
        return                      # `cargo fmt -- --check`: handed on to rustfmt
    what = f"{head}{' ' + verb if verb else ''} (rewrites files in place)"
    if head == "pre-commit":
        # Runs its hooks over the repository it stands in, wherever inside it.
        yield what, _nearest(cwd, ".git")
    elif head == "cargo":
        manifest = values.get("--manifest-path")
        yield what, ((os.path.dirname(manifest) or cwd) if manifest
                     else _nearest(cwd, "Cargo.toml"))
    else:
        paths = [p for p in operands if not p.isdigit()]
        if paths == ["-"]:
            return                  # stdin to stdout
        for path in paths or [cwd]:
            yield what, path


def _command_behind(words, command, cwd, depth):
    """What `script` and `flock` run: the words after their file, or a `-c STRING`."""
    if not command and words[:1] == ["-c"] and len(words) > 1:
        command = words[1]
    if command:
        yield from _check_shell(["-c", command], cwd, depth)
    else:
        yield from _check_segment(words, cwd, depth)


def _check_script(args, cwd, depth):
    """`script FILE CMD…` records a session into FILE, and runs CMD.

    It was listed with the wrappers, whose arguments are all options: FILE was
    read as the command, and the command behind it not at all. So `script -q
    src/app.py pytest` wrote the file and `script -q /dev/null rm src/app.py`
    removed one (K-D-7). util-linux spells the command `-c STRING` instead.
    """
    options, words = _getopt(args, "FtcTOIBmEo",
                             ("--command", "--log-out", "--log-in", "--log-io", "--log-timing",
                              "--logging-format", "--echo", "--output-limit"), stop=True)
    values = dict(options)
    for name in ("-O", "--log-out", "-I", "--log-in", "-B", "--log-io", "-T", "--log-timing"):
        if values.get(name):
            yield f"script {name} (writes its log)", values[name]
    yield "script (writes the typescript)", words[0] if words else "typescript"
    yield from _command_behind(words[1:], values.get("-c") or values.get("--command"),
                               cwd, depth)


def _check_flock(args, cwd, depth):
    """`flock FILE CMD…` creates FILE if it is not there, and runs CMD."""
    options, words = _getopt(args, "wEc", ("--timeout", "--conflict-exit-code", "--command"),
                             stop=True)
    values = dict(options)
    if not words:
        return
    if not words[0].isdigit():      # a number is a descriptor that is already open
        yield "flock (creates its lock file)", words[0]
    yield from _command_behind(words[1:], values.get("-c") or values.get("--command"),
                               cwd, depth)


def _check_compressor(head, args, cwd):
    values = {"zstd": "oD", "unzstd": "oD", "xz": "STM", "unxz": "STM"}.get(head, "S")
    options, operands = _getopt(args, values, ("--suffix", "--output-dir-flat",
                                               "--output-dir-mirror"))
    names = {name for name, _value in options}
    if names.intersection(_COMPRESSOR_READS):
        return
    named = [value for name, value in options
             if value and name in ("-o", "--output-dir-flat", "--output-dir-mirror")]
    for path in named:
        yield f"{head} (writes the file it names)", path
    if named and "--rm" not in names:
        return                      # zstd -o: the output is elsewhere and the source stays
    for path in operands:
        if path != "-":
            yield f"{head} (replaces the file in place)", path


def _named_outputs(head, args, shorts, longs, outputs):
    """A file a command names through an option: `sort -o FILE`, `iconv -o FILE`."""
    for name, value in _getopt(args, shorts, longs)[0]:
        if name in outputs and value:
            yield f"{head} {name} (writes the file it names)", value


def _check_sort(head, args, cwd):
    # `sort -o src/app.py src/app.py` overwrites its own input — measured (K-D-11).
    yield from _named_outputs(head, args, "ktSTo",
                              ("--output", "--key", "--field-separator", "--buffer-size",
                               "--temporary-directory", "--parallel", "--batch-size",
                               "--compress-program", "--files0-from", "--random-source",
                               "--sort"), ("-o", "--output"))


def _check_iconv(head, args, cwd):
    yield from _named_outputs(head, args, "fto", ("--from-code", "--to-code", "--output"),
                              ("-o", "--output"))


def _check_split(head, args, cwd):
    """`split FILE PREFIX` writes PREFIXaa, PREFIXab, …; `csplit` writes xx00, xx01, …
    — where they stand, unless told a prefix."""
    if head == "csplit":
        options, _operands = _getopt(args, "fbn", ("--prefix", "--suffix-format", "--digits"))
        values = dict(options)
        yield "csplit (writes its pieces)", (values.get("-f") or values.get("--prefix")
                                             or os.path.join(cwd, "xx"))
    else:
        operands = _getopt(args, "ablCnpt", ("--suffix-length", "--bytes", "--line-bytes",
                                             "--lines", "--number", "--separator",
                                             "--additional-suffix", "--filter"))[1]
        yield "split (writes its pieces)", (operands[1] if len(operands) > 1
                                            else os.path.join(cwd, "x"))


def _check_dos2unix(head, args, cwd):
    options, operands = _getopt(args, "c", ("--convmode",))
    names = {name for name, _value in options}
    if names.intersection(("-O", "--to-stdout", "-i", "--info", "-h", "--help", "-V",
                           "--version")):
        return
    # `-n IN OUT` writes OUT and leaves IN alone; otherwise every file is converted in place.
    paired = bool(names.intersection(("-n", "--newfile")))
    for path in (operands[1::2] if paired else operands):
        yield f"{head} (converts the file in place)", path


def _check_rename(head, args, cwd):
    """Perl's `rename EXPR FILES…` and util-linux's `rename FROM TO FILES…`."""
    options, operands = _getopt(args, "e", ("--expr",))
    names = {name for name, _value in options}
    if names.intersection(("-n", "--nono", "--no-act", "--dry-run", "-h", "--help", "-V",
                           "--version")):
        return
    if not names.intersection(("-e", "--expr")):
        # The expression is not a file. A Perl one has punctuation in it; a
        # plain word is util-linux's FROM, and the word after it is its TO.
        plain = bool(operands) and not any(ch in operands[0] for ch in "/$=;({~ ")
        operands = operands[2 if plain else 1:]
    for path in operands:
        yield "rename", path


def _check_mknod(head, args, cwd):
    operands = _getopt(args, "mZ", ("--mode", "--context"))[1]
    if operands:                    # NAME TYPE MAJOR MINOR: only the first is a path
        yield "mknod", operands[0]


def _check_patch(head, args, cwd):
    """`patch` rewrites the files its input names — where it stands, or under `-d DIR`
    — unless it is told one file, or one output."""
    options, operands = _getopt(args, "pidoDBFVgYzr",
                                ("--strip", "--input", "--directory", "--output", "--ifdef",
                                 "--prefix", "--fuzz", "--version-control", "--get",
                                 "--basename-prefix", "--suffix", "--reject-file"))
    values = dict(options)
    if set(values).intersection(("--dry-run", "-C", "--check", "--help", "-v", "--version")):
        return
    output = values.get("-o") or values.get("--output")
    there = values.get("-d") or values.get("--directory")
    if output:
        yield "patch -o (writes the file it names)", output
    elif operands:
        yield "patch", operands[0] if not there else os.path.join(there, operands[0])
    else:
        yield "patch (rewrites the files its input names)", there or cwd


def _check_unzip(head, args, cwd):
    options, _operands = _getopt(args, "dP")
    names = {name for name, _value in options}
    if names.intersection(("-l", "-t", "-p", "-c", "-v", "-z", "-Z", "-h")):
        return                      # lists, tests, or extracts to stdout
    where = [value for name, value in options if name == "-d" and value]
    yield "unzip (extracts in place)", where[-1] if where else cwd


def _check_zip(head, args, cwd):
    if any(a in ("-sf", "--show-files", "-h", "-h2", "--help", "-L", "--license",
                 "--version") for a in args):
        return
    options, operands = _getopt(args, "bntO", ("--out", "--output-file", "--temp-path"))
    values = dict(options)
    output = values.get("-O") or values.get("--out") or values.get("--output-file")
    if output or operands:
        yield "zip (writes the archive)", output or operands[0]
    if set(values).intersection(("-m", "--move")):
        for path in operands[1:]:
            yield "zip -m (removes what it archived)", path


def _check_7z(head, args, cwd):
    switches = [a for a in args if a.startswith("-")]
    words = [a for a in args if not a.startswith("-")]
    verb = words[0] if words else ""
    if verb in ("x", "e") and "-so" not in switches:
        out = [s[2:] for s in switches if s.startswith("-o") and len(s) > 2]
        yield f"{head} {verb} (extracts in place)", out[-1] if out else cwd
    elif verb in ("a", "u", "d", "rn") and len(words) > 1:
        yield f"{head} {verb} (writes the archive)", words[1]


def _check_cpio(head, args, cwd):
    options, operands = _getopt(args, "FIODHCEMR",
                                ("--file", "--directory", "--format", "--pattern-file",
                                 "--owner", "--rsh-command", "--io-size", "--block-size"))
    values = dict(options)
    names = set(values)
    if names.intersection(("-t", "--list", "--help", "--version")):
        return
    if names.intersection(("-p", "--pass-through")):
        if operands:
            yield "cpio -p (copies into the directory)", operands[-1]
    elif names.intersection(("-i", "--extract")):
        yield "cpio -i (extracts in place)", (values.get("-D") or values.get("--directory")
                                             or cwd)
    elif names.intersection(("-o", "--create")):
        archive = values.get("-F") or values.get("-O") or values.get("--file")
        if archive:
            yield "cpio -o (writes the archive)", archive


def _check_pax(head, args, cwd):
    options, operands = _getopt(args, "fbsopxEGUTB")
    values = dict(options)
    reads, writes = "-r" in values, "-w" in values
    if reads and writes:
        if operands:
            yield "pax -rw (copies into the directory)", operands[-1]
    elif reads:
        yield "pax -r (extracts in place)", cwd
    elif writes and values.get("-f"):
        yield "pax -w (writes the archive)", values["-f"]


def _check_unrar(head, args, cwd):
    words = [a for a in args if not a.startswith("-")]
    if words[:1] and words[0] in ("x", "e"):
        yield f"{head} {words[0]} (extracts in place)", words[-1] if len(words) > 2 else cwd


_CURL_VALUES = ("--output", "--output-dir", "--dump-header", "--cookie-jar", "--trace",
                "--trace-ascii", "--stderr", "--etag-save", "--libcurl", "--data", "--data-raw",
                "--data-binary", "--data-urlencode", "--json", "--header", "--user",
                "--user-agent", "--request", "--url", "--form", "--form-string", "--cookie",
                "--referer", "--max-time", "--connect-timeout", "--retry", "--retry-delay",
                "--retry-max-time", "--proxy", "--cacert", "--cert", "--key", "--write-out",
                "--range", "--upload-file", "--config", "--resolve", "--max-redirs",
                "--limit-rate", "--interface", "--unix-socket", "--oauth2-bearer",
                "--max-filesize", "--proto", "--ciphers", "--connect-to", "--noproxy",
                "--proxy-user", "--speed-limit", "--speed-time", "--capath", "--time-cond",
                "--continue-at", "--aws-sigv4")
_CURL_WRITES = ("-o", "--output", "-D", "--dump-header", "-c", "--cookie-jar", "--trace",
                "--trace-ascii", "--stderr", "--etag-save", "--libcurl")


def _check_curl(head, args, cwd):
    """`curl -o FILE` writes FILE and `curl -O` saves under the URL's own name
    where it stands. A plain `curl URL` prints, and passes."""
    options = _getopt(args, "AbcCdDeEFHKmoPQrtTuUwxXyYz", _CURL_VALUES)[0]
    values = dict(options)
    folder = values.get("--output-dir")
    for name, value in options:
        if name in _CURL_WRITES and value:
            if folder and name in ("-o", "--output") and _is_relative(value):
                value = os.path.join(folder, value)
            yield f"curl {name} (writes the file it names)", value
    if set(values).intersection(("-O", "--remote-name", "--remote-name-all")):
        yield "curl -O (saves into the directory)", folder or cwd


_WGET_VALUES = ("--output-document", "--directory-prefix", "--output-file", "--append-output",
                "--tries", "--timeout", "--wait", "--quota", "--user-agent", "--level",
                "--accept", "--reject", "--domains", "--input-file", "--base", "--header",
                "--user", "--password", "--post-data", "--post-file", "--execute",
                "--limit-rate", "--referer", "--method", "--body-data", "--load-cookies",
                "--save-cookies")


def _check_wget(head, args, cwd):
    """`wget URL` saves the document where it stands — writing is what it does
    by default — unless `-O` names the file or `-P` the directory."""
    values = dict(_getopt(args, "OPoaetTwQUlARDIXiB", _WGET_VALUES)[0])
    if set(values).intersection(("--spider", "-h", "--help", "-V", "--version")):
        return
    for name in ("-o", "--output-file", "-a", "--append-output", "--save-cookies"):
        if values.get(name):
            yield f"wget {name} (writes the file it names)", values[name]
    document = values.get("-O") or values.get("--output-document")
    if document:
        yield "wget -O (writes the document)", document
    else:
        yield "wget (saves into the directory)", (values.get("-P")
                                                  or values.get("--directory-prefix") or cwd)


# Commands that write through an option or a rule of their own, none of which
# the guard read before 0.90.3 (K-D-11). Each handler takes (head, args, cwd).
_HANDLERS = {
    "sort": _check_sort, "iconv": _check_iconv, "split": _check_split,
    "csplit": _check_split, "dos2unix": _check_dos2unix, "unix2dos": _check_dos2unix,
    "mac2unix": _check_dos2unix, "unix2mac": _check_dos2unix, "rename": _check_rename,
    "mknod": _check_mknod, "patch": _check_patch, "unzip": _check_unzip, "zip": _check_zip,
    "7z": _check_7z, "7za": _check_7z, "7zr": _check_7z, "7zz": _check_7z,
    "cpio": _check_cpio, "pax": _check_pax, "unrar": _check_unrar,
    "curl": _check_curl, "wget": _check_wget,
}
for _name in _COMPRESSORS:
    _HANDLERS[_name] = _check_compressor


def _check_ln(args, cwd):
    """`ln [-s] SRC... DST`: the destination is written, as for any copier — and the
    source is judged too, whenever the link is a way to write it.

    A link is a second name for a file somewhere else. Two cases matter here:

    * **A hard link, wherever it lands.** Every other rule in this file judges a
      write by its path, and a hard link gives a file in the checkout a path in
      scratch: `ln src/app.py /tmp/x/alias && echo junk > /tmp/x/alias` was a
      write to the code under test that named only scratch. No `realpath` can
      see it, so the link itself is the write.
    * **A symlink inside a QA root.** The harness writes the root's files by
      name: `ln -s ../src/app.py .qa/facts.json` followed by `verdict-facts` put
      the facts over the code under test (the release's own Opus gate,
      2026-10-03). The harness refuses such a root now; this refuses to build
      one. A symlink in scratch is left alone — `_target_ok` resolves a later
      write through it — and a relative source is read against the link's own
      directory, which is how the filesystem reads it.
    """
    symbolic = any((a.startswith("-") and not a.startswith("--") and "s" in a[1:])
                   or a == "--symbolic" for a in args)
    destination = None
    for what, target in _check_copier("ln", args):
        yield what, target
        destination = target
    if destination is None:
        return
    sources = [a for a in args if not a.startswith("-") and a != destination]
    if not symbolic:
        for source in sources:
            yield "ln (a second name for the same file)", source
        return
    base = os.path.join(cwd, os.path.expanduser(destination))
    dst_dir = base if os.path.isdir(base) else os.path.dirname(base)
    if not is_allowed_path(dst_dir):
        return            # scratch, or already refused as a destination out of scope
    for source in sources:
        if not os.path.isabs(os.path.expanduser(source)):
            source = os.path.join(dst_dir, source)
        yield "ln (a link out of the QA root)", source


def _check_pen(pen, args):
    """`verdict-accept` / `verdict-answer` in any writing form. `--list` reads."""
    if not _PEN_READS.intersection(args):
        yield f"{pen} (the maintainer's pen)", _PEN


def _python_pen(args):
    """`python -m verdict_mcp.accept …` or `python …/verdict_mcp/accept.py …` → the
    pen it is, or None. Only the first module or script on the line counts."""
    for i, tok in enumerate(args):
        if tok == "-m":
            name = args[i + 1] if i + 1 < len(args) else ""
            for pen, module in _PENS.items():
                if name == "verdict_mcp." + module:
                    return pen
            return None
        if not tok.startswith("-"):
            path = tok.replace("\\", "/")
            for pen, module in _PENS.items():
                if path.endswith("verdict_mcp/" + module + ".py"):
                    return pen
            return None
    return None


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
    if head == _HEREDOC:
        # A heredoc body fed to a shell: the walker hands it over as a script.
        if depth < _MAX_DEPTH:
            yield from _check_shell(["-c", args[0]], cwd, depth)
    elif head in _SHELLS and depth < _MAX_DEPTH:
        yield from _check_shell(args, cwd, depth)
    elif head == "eval" and depth < _MAX_DEPTH:
        yield from _check_eval(args, cwd, depth)
    elif head in _WRAPPERS:
        yield from _check_wrapper(head, args, cwd, depth)
    elif head in _RUNNERS:
        yield from _check_runner(head, args, cwd, depth)
    elif head in _PENS:
        yield from _check_pen(head, args)
    elif head == "verdict-issues":
        # Posting findings to a tracker leaves the machine under the maintainer's
        # name. The dry run reads; `--create` is the maintainer's to run.
        if "--create" in args:
            yield "verdict-issues --create (the maintainer's pen)", _PEN
    elif head == "ln":
        yield from _check_ln(args, cwd)
    elif _PYTHON.match(head):
        pen = _python_pen(args)
        if pen:
            yield from _check_pen(pen, args)
        module = _python_module(args)
        if module and module[0] in _FORMAT_TOOLS:
            yield from _check_formatter(module[0], module[1:], cwd)
    elif head in ("xargs", "parallel"):
        yield from _check_xargs(head, args, cwd, depth)
    elif head == "dd":
        for t in args:
            if t.startswith("of="):
                yield "dd of=", t[3:]
    elif head in ("sed", "gsed", "perl"):
        yield from _check_stream_editor(head, args)
    elif head == "git":
        yield from _check_git(args, cwd, depth)
    elif head in ("awk", "gawk"):
        yield from _check_awk(args)
    elif head in ("tar", "gtar", "bsdtar"):
        # By every name it is installed under. On macOS `/usr/bin/tar` is
        # bsdtar, which cannot `--remove-files` at all, and the GNU tar that
        # can is Homebrew's `gtar` — a name the exact match never read, so on
        # the one binary able to do the thing no tar rule fired (VERDICT-F-67).
        yield from _check_tar(args, cwd)
    elif head == "find":
        yield from _check_find(args, cwd, depth)
    elif head == "script":
        yield from _check_script(args, cwd, depth)
    elif head == "flock":
        yield from _check_flock(args, cwd, depth)
    elif head in _HANDLERS:
        yield from _HANDLERS[head](head, args, cwd)
    elif head in _FORMAT_TOOLS:
        yield from _check_formatter(head, args, cwd)
    elif head in _COPIERS or head in _MOVERS:
        # rsync only removes sources when told to; asked to, it is a move.
        moves = head in _MOVERS or "--remove-source-files" in args
        yield from _check_copier(head, args, moves=moves)
    elif head in _MUTATORS:
        # The first operand of some mutators is not a path: `chmod +x f` names
        # a mode, `chown user f` an owner, `truncate -s 0 f` a size. Resolved
        # as a path it became `<checkout>/+x` and the guard refused a chmod
        # inside the QA root it exists to permit (VERDICT-F-77).
        operands = _getopt(args, *_MUTATOR_VALUE_OPTS.get(head, ("", ())))[1]
        if head in _MODE_FIRST and operands:
            operands = operands[1:]
        for t in operands:
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
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command", "")
    except Exception:
        return 0  # fail open: never brick the session on malformed input
    strict = _strict()
    if not (strict or caller_is_verdict(data)):
        # Nobody's QA run. The same event fires for the user's own shell
        # commands, which name no agent, and for every other agent's; write
        # heuristics on those would be intolerable. This used to be decided
        # before the event was read, on VERDICT_STRICT alone — so an
        # interactive session's tester was never guarded at all (T0-4).
        return 0
    if not isinstance(command, str) or not command:
        return 0
    if "\x00" in command:
        # bash drops a NUL and runs what is left; every path function here raises on
        # one. `echo x > src/app.py\u0000` crashed the guard — exit 1, "the hook
        # broke" — and the write went through. Nothing a QA run types carries a NUL.
        sys.stderr.write(
            "verdict bash guard: this command line carries a NUL byte, which the shell "
            "drops and this guard cannot read past — retype it without one.\n")
        return 2
    cwd = data.get("cwd")
    if not isinstance(cwd, str) or not cwd:
        cwd = os.getcwd()

    view, balanced = _mask_quoted(command)
    # An unbalanced command is scanned twice: once as the shell would read it,
    # and once as raw text, so a deny pattern behind an unclosed quote is still
    # positively visible. Both passes only ever add denials.
    denials = []
    armed = "VERDICT_STRICT" if strict else "the caller is the verdict agent"
    try:
        for scan in ([view] if balanced else [view, command]):
            trail = _Trail(cwd)
            for _separator, segment, seg_view in trail.walk(command, scan):
                here = trail.base
                for target in _redirect_targets(segment, seg_view):
                    ok, resolved = _target_ok(target, here)
                    if not ok:
                        denials.append(("output redirection", resolved))
                for what, target in _check_segment(_tokens(segment, seg_view), here):
                    ok, resolved = _target_ok(target, here)
                    if not ok:
                        denials.append((what, resolved))
    except RecursionError:
        # `xargs xargs xargs …`, several hundred deep: each level is read by
        # the one before it, and Python runs out of stack first. Not malformed
        # hook input, which fails open — a command built so that it cannot be
        # read, which an interpreter's own exit 1 would have waved through.
        sys.stderr.write(
            f"verdict bash guard ({armed}): this command is nested too deeply to be "
            "read, so whether it writes outside the QA root cannot be told — "
            "run it in smaller steps.\n")
        return 2
    except Exception as exc:  # noqa: BLE001 — the reason is the next comment
        # The same rule for any other failure while a well-formed event's command
        # is being read. Malformed hook input fails open, above, before the guard
        # is armed; from here on the guard IS armed, and an uncaught exception is
        # exit 1 — which the platform reads as a broken hook and lets the command
        # run. A parser bug must cost the tester a retyped command, never the
        # checkout a write nobody judged (found on this guard's own new rule,
        # 0.90.3: a sentinel joined into a path).
        sys.stderr.write(
            f"verdict bash guard ({armed}): this command could not be read "
            f"({type(exc).__name__}), so whether it writes outside the QA root cannot "
            "be told — run it in simpler steps.\n")
        return 2

    if not denials:
        return 0
    what, resolved = denials[0]
    if resolved.startswith("the maintainer's ledger"):
        sys.stderr.write(
            f"verdict bash guard ({armed}): `{what.split(' ', 1)[0]}` is the maintainer's "
            "pen. It records the maintainer's decision about the tester's findings and "
            "questions, and a tester that could run it would be grading its own paper. "
            "Read a ledger with `--list`; put a question for the maintainer in "
            "judgment.json.\n")
        return 2
    sys.stderr.write(
        f"verdict bash guard ({armed}): {what} targets {resolved!r}, "
        "outside the QA root. A QA run may only write inside a .qa/ "
        "directory, $VERDICT_HOME (default ~/.claude/verdict), /dev/*, or scratch "
        "under a temp dir — but not a git checkout sitting in one. Findings "
        "are reported, never patched in place.\n"
    )
    return 2  # block the tool call and show Claude the reason


if __name__ == "__main__":
    sys.exit(main())
