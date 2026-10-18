"""The scope a profile names: the paths and code names its risk-focus section mentions (0.92.0).

A profile's "Risk focus" section is where its owner says what matters: `openfisca_core/periods/`,
`calculate_add`, `MarginalRateTaxScale`. On a project with no coverage map the local tier used to
read the largest files, or files in alphabetical order, and on 2026-10-18 an escalation run's whole
packet came from six generic helpers while the three known defects sat in the paths the profile
named. This module turns that section into files: the ones under a named path, and the ones that
define a named function or class, so the breadth pass reads there first.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$")
TICKED = re.compile(r"`([^`\n]{2,160})`")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*(?:\(\))?$")
STOP = {"self", "cls", "None", "True", "False", "id", "pass", "return", "yield", "json", "yaml"}
WORD = re.compile(r"[A-Za-z][A-Za-z_]{4,}")
# Words a risk section uses that name no part of a codebase.
PROSE = {"about", "against", "amount", "amounts", "across", "after", "before", "being", "between",
         "change", "changes", "concurrent", "correctness", "decimal", "double", "during", "edits",
         "every", "focus", "including", "inclusive", "exclusive", "leaves", "means", "money",
         "other", "others", "partial", "process", "processed", "provider", "reports", "rounding",
         "should", "sign", "their", "there", "these", "those", "three", "through", "totals", "twice",
         "under", "value", "values", "wrong", "where", "which", "while", "within", "without"}
MAX_FILES = 40
MAX_NAMES = 60


def focus_lines(profile_text: str) -> list:
    """The lines of every section whose heading names a risk, minus the ones that say what is
    out of scope."""
    lines, inside = [], False
    for line in (profile_text or "").splitlines():
        m = HEADING.match(line)
        if m:
            inside = "risk" in m.group(1).lower()
            continue
        if inside and "out of scope" not in line.lower():
            lines.append(line)
    return lines


def _stem(word: str) -> str:
    """Lower case, one trailing plural `s` off: budgets → budget, prices → price; basis, status
    and class keep theirs."""
    word = word.lower()
    return word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith(("ss", "is", "us")) \
        else word


def words(profile_text: str) -> list:
    """The content words of the risk-focus sections outside backticks, stemmed, in order: the
    weaker signal a prose-only section gives ("budgets", "conversions", "inventory")."""
    out = []
    for line in focus_lines(profile_text):
        for word in WORD.findall(TICKED.sub(" ", line)):
            stem = _stem(word)
            if word.lower() not in PROSE and stem not in PROSE and stem not in out:
                out.append(stem)
    return out


BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")


def terms(profile_text: str) -> tuple:
    """(paths, names) the risk-focus sections name in backticks, in order, deduplicated. A bare
    file name is read in the directory its bullet named last: "`src/oscar/apps/offer/` —
    `benefits.py`, `utils.py`" means that directory's files, not every `utils.py` in the tree
    (measured 2026-10-18: thirteen of them came out as named outright)."""
    paths, names = [], []
    context = ""
    for line in focus_lines(profile_text):
        if not line.strip() or BULLET.match(line):
            context = ""
        for token in TICKED.findall(line):
            token = token.strip()
            if "/" in token or token.endswith(".py"):
                path = token.strip("/").removeprefix("./")
                if not path or " " in path:
                    continue
                if "/" in path:
                    context = path.rsplit("/", 1)[0] if path.endswith(".py") else path
                elif context:
                    path = f"{context}/{path}"
                if path not in paths:
                    paths.append(path)
            elif IDENT.match(token):
                name = token.removesuffix("()").rsplit(".", 1)[-1]
                if name not in STOP and name not in names:
                    names.append(name)
    return paths, names[:MAX_NAMES]


def _tracked(repo: Path) -> list:
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "*.py"], capture_output=True,
                          text=True, errors="replace")
    return proc.stdout.splitlines() if proc.returncode == 0 else []


def _defining(repo: Path, names) -> dict:
    """{file: the names it defines} for tracked Python files. A name with an underscore also
    matches its `name_*` variants: `set_input` finds `set_input_dispatch_by_period`."""
    if not names:
        return {}
    # POSIX classes, not \\s or \\b: git grep's extended syntax on macOS knows neither.
    pattern = (r"^[[:space:]]*(async[[:space:]]+)?(def|class)[[:space:]]+("
               + "|".join(re.escape(n) for n in names) + r")(_[A-Za-z0-9_]*)?([^A-Za-z0-9_]|$)")
    proc = subprocess.run(["git", "-C", str(repo), "grep", "-o", "-E", pattern, "--", "*.py"],
                          capture_output=True, text=True, errors="replace")
    out: dict = {}
    for line in proc.stdout.splitlines():
        path, _, match = line.partition(":")
        m = re.search(r"(?:def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", match)
        if not path or not m:
            continue
        defined = m.group(1)
        for n in names:
            if defined == n or ("_" in n and defined.startswith(n + "_")):
                out.setdefault(path, set()).add(n)
    return out


def risk_focus(repo: Path, profile_text: str, is_test=lambda p: False) -> dict | None:
    """`{paths, names, files}` for facts.json, or None when the profile names no scope. `files`
    is ranked: those defining the most named functions first, then those under a named path."""
    paths, names = terms(profile_text)
    stems = words(profile_text)
    if not paths and not names and not stems:
        return None
    tracked = [f for f in _tracked(Path(repo)) if not is_test(f) and "/migrations/" not in f"/{f}"]
    known = set(tracked)
    defining = {k: v for k, v in _defining(Path(repo), names).items() if k in known}
    # A file named outright (a full path, or a bare `benefits.py` next to its directory) is the
    # strongest signal a risk section gives; then files by how specific the names they define are:
    # `calculate_add`, defined once, says more than `sum`, defined in a dozen files.
    dirs = [p.rstrip("/") for p in paths if not p.endswith(".py")]

    def named_by_path(p):
        found = [f for f in tracked if f == p or f.endswith("/" + p)]
        if len(found) > 2:  # a bare name no bullet placed: only the ones under a named directory
            found = [f for f in found if any(f.startswith(d + "/") for d in dirs)]
        return found if len(found) <= 2 else []

    named_files = list(dict.fromkeys(f for p in paths if p.endswith(".py") for f in named_by_path(p)))
    df: dict = {}
    for found in defining.values():
        for n in found:
            df[n] = df.get(n, 0) + 1
    weight = {f: sum(1 / df[n] for n in found) for f, found in defining.items()}
    ranked = sorted((f for f in defining if f not in named_files), key=lambda f: (-weight[f], f))
    taken_now = set(named_files) | set(ranked)
    under = [f for f in tracked if f not in taken_now
             and any(f.startswith(p.rstrip("/") + "/") for p in paths if not p.endswith(".py"))]

    def named_by_words(f):
        parts = [_stem(x) for x in re.split(r"[/_.]", f.lower()) if len(x) >= 4]
        return sum(1 for s in stems if s in parts)

    taken = set(named_files) | set(ranked) | set(under)
    worded = sorted((f for f in tracked if f not in taken and named_by_words(f)),
                    key=lambda f: (-named_by_words(f), f))
    return {"paths": paths, "names": names, "words": stems[:40], "named_files": named_files[:MAX_FILES],
            "files": (named_files + ranked + under + worded)[:MAX_FILES]}
