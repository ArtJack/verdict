"""The units a question is asked about: source chunks per language, the notes a language
needs, and the functions a coverage gap names.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:
    from . import braces, languages, reach, readers
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import braces
    import languages
    import reach
    import readers


MAX_SOURCE_LINES = 120          # one question's worth of code


class Chunk:
    """One function, with the line numbers it really occupies in its file.

    `lang` is the language it is written in, which picks the question's wording and whether a
    counterfactual can run at all (Python only). `context` is the head of the type that holds a
    function in another language — the attributes on a whole controller, a Rails controller's
    `before_action` — a guard outside every method of it, and a question without them reads an
    unguarded method. `unit` is what the lines are: a `function`, an `excerpt` of a language read
    without function boundaries, or a `template`."""

    def __init__(self, path: str, name: str, start: int, end: int, source: str,
                 lang: str = "python", context: str | None = None, note: str = "",
                 unit: str = "function", reached: list | None = None):
        self.path, self.name, self.start, self.end, self.source = path, name, start, end, source
        self.lang, self.context, self.note, self.unit = lang, context, note, unit
        self.reached = reached or []

    def numbered(self) -> str:
        return "\n".join(f"{self.start + i:4d}| {line}"
                         for i, line in enumerate(self.source.splitlines()))


BRACE_LANGUAGES = braces.BRACE_LANGUAGES


def _source_chunks(repo: Path, rel: str, lines) -> list | None:
    """The questions a file in a language other than Python raises — every outermost function
    when `lines` is None, else the ones the changed `lines` sit in — or None for Python and for
    a file in no language at all. `readers` hands each file to the reader its language needs."""
    lang = languages.language_of(rel)
    if lang is None or lang == "python":
        return None
    try:
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    found = readers.read(rel, text, lines, MAX_SOURCE_LINES) or []
    # A function in a file its own language's reader cut is asked about with what it reaches for
    # one step outside itself: the callee that checks, the state it shares, the type it names.
    whole_file = languages.family_of(lang) in ("braces", "ends")
    return [Chunk(rel, p.name, p.start, p.end, p.source, p.lang, p.context,
                  language_note(repo, rel, p.lang), p.unit,
                  reach.reached(repo, rel, text, p.lang, p.start, p.end)
                  if whole_file and p.unit == "function" else None) for p in found]


_brace_chunks = _source_chunks


# What a project's own build settings declare about absent values. Measured on a .NET range
# (2026-11-06): of the first C# claims a 120B reader made, most were a NullReferenceException on
# a reference the project's nullable annotations already declare non-null. The settings are the
# code's own statement, so the question carries them; a project that does not declare them gets
# no sentence at all.
_NULLABLE_NOTES = {
    "csharp": (("*.csproj", "Directory.Build.props"), r"<Nullable>\s*enable\s*</Nullable>",
               "The project enables nullable reference types: a reference type without `?` is "
               "declared non-null, so report a null dereference only where this code shows the "
               "value can be null (a `?` type, a `null` assigned, a lookup that can miss)."),
    "typescript": (("tsconfig*.json",), r'"(?:strict|strictNullChecks)"\s*:\s*true',
                   "The project compiles with strict null checks: a value whose type has no `?`, "
                   "`| null` or `| undefined` is declared present, so report a missing null or "
                   "undefined check only where this code shows the value can be absent."),
}


_NOTE_CACHE: dict = {}


# Languages whose type system itself rules out an unchecked absent value: the same false claim,
# answered by the language rather than by a project setting.
_LANGUAGE_NOTES = {
    "kotlin": ("Kotlin's types say which values can be null: a type without `?` cannot hold null, "
               "so report a null dereference only where this code shows a `?` type, a `!!`, a "
               "`lateinit` or a platform type from Java."),
    "swift": ("Swift's optionals say which values can be absent: report a nil problem only where "
              "this code force-unwraps (`!`, `try!`, `as!`) or an optional is shown."),
    "rust": ("Rust has no null: an absent value is an `Option` the compiler makes the code handle. "
             "Report an `unwrap()`, `expect()` or index that can panic, not a missing null check."),
    "dart": ("Dart's sound null safety says which values can be null: a type without `?` cannot "
             "hold null, so report a null problem only where this code shows a `?` type or a `!`."),
}


def language_note(repo: Path, rel: str, lang: str) -> str:
    """The sentence about absent values the nearest project file declares for `rel`, or the
    language itself declares, or ""."""
    if lang in _LANGUAGE_NOTES:
        return _LANGUAGE_NOTES[lang]
    if lang not in _NULLABLE_NOTES:
        return ""
    patterns, rule, sentence = _NULLABLE_NOTES[lang]
    root = Path(repo).resolve()
    here = (root / rel).parent
    key = (str(here), lang)
    if key not in _NOTE_CACHE:
        said = False
        while not said:
            for pattern in patterns:
                for found in sorted(here.glob(pattern)):
                    try:
                        said = said or bool(re.search(rule, found.read_text(encoding="utf-8",
                                                                            errors="replace")))
                    except OSError:
                        continue
            if here == root or here == here.parent or root not in here.parents:
                break
            here = here.parent
        _NOTE_CACHE[key] = sentence if said else ""
    return _NOTE_CACHE[key]


def chunks_of(repo: Path, rel: str) -> list:
    """Every top-level function and method of a module, as its own question.

    Line numbers come from the file, not from the excerpt: a model asked to point at a
    line in a pasted block counts from 1 and is wrong by the offset every time. Here the
    numbers are printed in the excerpt, so the answer is checkable against the file.
    Every other language is read by its own reader (`readers`), the same way: the file's
    own line numbers, one function to a question.
    """
    other = _source_chunks(repo, rel, None)
    if other is not None:
        return other
    try:
        text = (repo / rel).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(text)
    except (OSError, SyntaxError):
        return []
    lines = text.splitlines()
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start, end = node.lineno, getattr(node, "end_lineno", node.lineno)
        if end - start > MAX_SOURCE_LINES:
            end = start + MAX_SOURCE_LINES
        out.append(Chunk(rel, node.name, start, end, "\n".join(lines[start - 1:end])))
    return out


def gap_functions(facts: dict) -> dict:
    """`{path: {function name: [survivors]}}` from facts' assertion-gap census (0.91.1): the
    lines a mechanical mutant left the tests that run them green. The most precise free target
    there is: a line the suite executes and checks nothing about."""
    out: dict = {}
    for g in ((facts.get("assertion_gaps") or {}).get("survived") or []):
        if not isinstance(g, dict):
            continue
        path = str(g.get("path") or "").replace("\\", "/")
        name = str(g.get("function") or "").rsplit(".", 1)[-1]
        if path and name:
            out.setdefault(path, {}).setdefault(name, []).append(g)
    return out


def gap_hint(survivors: list) -> str:
    """What the census saw, as one sentence the reader can check against the source."""
    shown = "; ".join(f"line {g.get('line')} `{str(g.get('before'))[:80]}` -> `{str(g.get('after'))[:60]}`"
                      for g in survivors[:2])
    return ("A mutation test changed this function and the tests that execute it stayed green ("
            f"{shown}): nothing the suite asserts depends on those lines. Read them first.")
