"""The JavaScript and TypeScript checks: empty catches, console calls, commented-out code and
TODOs, and the names a file uses.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from .hygiene_const import LONG_LINE
    from .hygiene_patterns import (_CONSOLE, _JS_CODEY_COMMENT, _JS_COMMENT_TODO, _JS_EMPTY_CATCH,
                                   _JS_IMPORT, _JS_USE, _TODO)
    from .hygiene_paths import _is_script_path
    from .hygiene_scrub import _item
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import LONG_LINE
    from hygiene_patterns import (_CONSOLE, _JS_CODEY_COMMENT, _JS_COMMENT_TODO, _JS_EMPTY_CATCH,
                                  _JS_IMPORT, _JS_USE, _TODO)
    from hygiene_paths import _is_script_path
    from hygiene_scrub import _item


# ── JavaScript / TypeScript ───────────────────────────────────────────────
def _js_names(spec: str) -> list[str]:
    spec = spec.strip()
    m = re.match(r"\*\s+as\s+([\w$]+)$", spec)
    if m:
        return [m.group(1)]
    names = []
    head = spec.split("{", 1)[0].strip().rstrip(",").strip()
    if head:
        names.append(head)
    if "{" in spec:
        for part in spec.split("{", 1)[1].rsplit("}", 1)[0].split(","):
            part = re.sub(r"^\s*type\s+", "", part).strip()
            if part:
                names.append(part.split(" as ")[-1].strip())
    return [n for n in names if re.fullmatch(r"[A-Za-z_$][\w$]*", n)]


def _javascript(rel, text, lines, items):
    """The JS/TS junk checks, for code this project wrote: the caller passes over
    minified, bundled and vendored files entirely."""
    _javascript_lines(rel, lines, items)
    vue = rel.lower().endswith(".vue")
    for m in _JS_IMPORT.finditer(text):
        rest = text[:m.start()] + text[m.end():]
        line_no = text.count("\n", 0, m.start()) + 1
        for name in _js_names(m.group("spec")):
            # The classic JSX runtime needs React in scope whatever the extension.
            if name == "React":
                continue
            if re.search(_JS_USE + re.escape(name) + r"(?![\w$])", rest):
                continue
            # A Vue template may write the component UserCard as <user-card>.
            if vue and re.search("<" + re.escape(_kebab(name)) + r"(?![\w-])", rest):
                continue
            items.append(_item("unused_import", 2, rel, line_no,
                               f"{name}: {m.group(0).splitlines()[0]}",
                               f"`{name}` is imported and never used"))


def _kebab(name: str) -> str:
    """UserCard → user-card, the way Vue hyphenates a component name."""
    return re.sub(r"\B([A-Z])", r"-\1", name).lower()


def _javascript_lines(rel, lines, items):
    run: list = []
    for i, line in enumerate(lines, 1):
        if len(line) > LONG_LINE:
            run = []
            continue
        if _JS_EMPTY_CATCH.search(line):
            items.append(_item("broad_swallow", 2, rel, i, line, "an error handler that does nothing"))
        if _CONSOLE.search(line) and not _is_script_path(rel):
            items.append(_item("console_debug", 2, rel, i, line, "debug logging left in app code"))
        # The cheap test first: the comment pattern alone is quadratic on a line
        # full of `//`, and almost no line holds one of the four marker words.
        if _TODO.search(line) and _JS_COMMENT_TODO.search(line):
            items.append(_item("todo_comment", 2, rel, i, line, "a TODO/FIXME/HACK left in the code"))
        run = run + [i] if _JS_CODEY_COMMENT.match(line) else []
        if len(run) == 2:
            items.append(_item("commented_out_code", 2, rel, run[0], lines[run[0] - 1],
                               "code kept as a comment: dead, and it reads as live"))
