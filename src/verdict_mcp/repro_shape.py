"""The command shapes the harness runs without a person: one interpreter call, never a shell.

Split out of replay.py as a pure move: every block below is byte-identical to what it was there,
and replay.py imports back what its callers use. It stands alone so that the finding hook, which
runs on the interpreter floor with none of the harness loaded, can tell a tester whether the
repro it just wrote is one the harness will run.
"""
from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


# What the harness runs without a person: an interpreter on a script in the QA root or the
# fresh tree, a `-c` string, or pytest — argv, never a shell. `verdict-facts` and
# `verdict-finalize` run a command the tester wrote, outside the Bash guard that watches the
# tester's own commands, so a pipeline, a redirection or an arbitrary program is not theirs
# to run; `verdict-replay`, typed by a person who can read it first (`--show`), runs anything.
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_INTERPRETER = re.compile(r"^(?:python(?:\d+(?:\.\d+)?)?|pypy\d*(?:\.\d+)?|pytest)$")
_MODULES = ("pytest", "unittest", "doctest")
_REFUSED_ENV = ("LD_", "DYLD_")
_SHELL_OPERATORS = (";", "&", "|", "<", ">", "`", "$(", "\n")


def _outside_quotes(command: str) -> str:
    """The command with every quoted span blanked — what a shell would read as operators."""
    out, quote, i = [], None, 0
    while i < len(command):
        c = command[i]
        if quote:
            if c == "\\" and quote == '"' and i + 1 < len(command):
                out.append("  ")
                i += 2
                continue
            if c == quote:
                quote = None
            out.append(" ")
        elif c in "'\"":
            quote = c
            out.append(" ")
        elif c == "\\" and os.name != "nt" and i + 1 < len(command):
            out.append("  ")
            i += 2
            continue
        else:
            out.append(c)
        i += 1
    return "".join(out)


def _split(command: str) -> list[str]:
    if os.name != "nt":
        return shlex.split(command)
    words = shlex.split(command, posix=False)          # a Windows path's backslashes stay
    return [w[1:-1] if len(w) >= 2 and w[0] == w[-1] and w[0] in "'\"" else w for w in words]


def unattended_argv(command: str, scratch: Path, qa_root: Path, cwd: Path):
    """(argv, env, problem): the command as argv when its shape is one the harness runs
    unattended, else (None, {}, why)."""
    bare = _outside_quotes(command)
    for op in _SHELL_OPERATORS:
        if op in bare:
            shown = "a newline" if op == "\n" else f"`{op}`"
            return None, {}, f"the command uses {shown}, a shell operator"
    try:
        words = _split(command)
    except ValueError as exc:
        return None, {}, f"the command cannot be split into words ({exc})"
    env: dict = {}
    if len(words) > 1 and Path(words[0]).name == "env" and not words[1].startswith("-"):
        # `env A=1 python x.py` says what `A=1 python x.py` says; a tester writes it that way often
        # (2026-10-18: a proven Major's repro went unreplayed over the word). `env -i` is not that.
        words = words[1:]
    while words and _ENV_ASSIGN.match(words[0]):
        name, _, value = words.pop(0).partition("=")
        if name.startswith(_REFUSED_ENV):
            return None, {}, f"the command sets {name}"
        env[name] = value
    if not words:
        return None, {}, "the command names no program"
    prog = Path(words[0]).name.lower()
    prog = prog[:-4] if prog.endswith(".exe") else prog
    if not _INTERPRETER.match(prog):
        return None, {}, f"`{Path(words[0]).name}` is not python or pytest"
    if prog == "pytest":
        return words, env, ""
    i = 1
    while i < len(words) and words[i].startswith("-") and words[i] not in ("-c", "-m"):
        i += 2 if words[i] in ("-W", "-X") else 1
    if i >= len(words):
        return None, {}, "python with no script, `-c` or `-m` reads its program from stdin"
    if words[i] == "-c":
        return words, env, ""
    if words[i] == "-m":
        module = words[i + 1] if i + 1 < len(words) else ""
        if module not in _MODULES:
            return None, {}, f"`-m {module}` is not one of {', '.join(_MODULES)}"
        return words, env, ""
    script = Path(words[i])
    script = (script if script.is_absolute() else Path(cwd) / script).resolve()
    roots = [Path(qa_root).resolve(), Path(scratch).resolve()]
    if not any(script == r or r in script.parents for r in roots):
        return None, {}, f"the script {words[i]} is outside the QA root and the fresh checkout"
    return words, env, ""


# An empty directory of the repro's own, filled in when the repro runs: what `d=$(mktemp -d) &&
# …` gave a repro, without the shell the harness does not run unattended. An asked run on a
# PDF (2026-11-17) wrote two of its three repros around `mktemp -d`, and neither ran.
TMP = "{tmp}"

_SHAPES = ("one interpreter call: `python -c \"…\"`, `python` on a script in the QA root or "
           "the checkout, or `pytest`, with no shell, so no `&&`, `;`, `|`, `>` or `$(…)`")


def shape_note(finding, qa_root, repo=None) -> str:
    """What a tester reads as it writes `finding` when the harness will not replay its repro
    unattended, or "" when it will, or there is no repro to judge.

    `verdict-facts` and `verdict-finalize` replay a repro only in the shapes above, and said
    so only in the replay record, after the run: the tester learnt it once nothing could be
    rewritten. With no checkout known, a script's location is not judged."""
    repro = finding.get("repro") if isinstance(finding, dict) else None
    if not (isinstance(repro, dict) and isinstance(repro.get("command"), str)
            and repro["command"].strip()):
        return ""
    qa_root = Path(qa_root)
    tree = Path(repo) if repo else qa_root
    command = (repro["command"].replace("{repo}", str(tree))
               .replace("{qa_root}", str(qa_root)).replace(TMP, str(qa_root / "tmp")))
    where = str(repro.get("cwd") or "repo")
    cwd = qa_root if where == "qa_root" else (tree if where == "repo" else tree / where)
    argv, _, why = unattended_argv(command, tree, qa_root, cwd)
    if argv is not None or (not repo and why.startswith("the script")):
        return ""
    return (f"{finding.get('id') or 'this finding'}'s repro will not be replayed unattended "
            f"({why}). The harness replays a repro by itself only as {_SHAPES}. `{{repo}}`, "
            f"`{{qa_root}}` and `{TMP}`, an empty directory of the repro's own, are filled in. "
            "Rewrite it in that shape if the defect allows. If not, leave it: a person running "
            "`verdict-replay` still runs it as written.")
