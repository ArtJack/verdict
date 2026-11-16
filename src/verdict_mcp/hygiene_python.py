"""The Python checks: broad excepts, handlers that do nothing, debugger calls, unused and
commented-out code, TODOs, duplicated function bodies and unimported modules.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import ast
import hashlib
import io
import re
import sys
import tokenize
from pathlib import Path

try:
    from .hygiene_const import DUPLICATE_MIN_LINES
    from .hygiene_patterns import (_PY_DEBUGGER_MODULES, _READ_CALL, _RICH, _SENSITIVE, _TODO,
                                   _WRITE_CALL)
    from .hygiene_paths import is_test_path
    from .hygiene_scrub import _item
    from .hygiene_lines import _sql_py
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import DUPLICATE_MIN_LINES
    from hygiene_patterns import (_PY_DEBUGGER_MODULES, _READ_CALL, _RICH, _SENSITIVE, _TODO,
                                  _WRITE_CALL)
    from hygiene_paths import is_test_path
    from hygiene_scrub import _item
    from hygiene_lines import _sql_py


# ── Python ────────────────────────────────────────────────────────────────
def _broad(handler) -> bool:
    return handler.type is None or (isinstance(handler.type, ast.Name)
                                    and handler.type.id in ("Exception", "BaseException"))


def _does_nothing(body) -> bool:
    if len(body) != 1:
        return False
    s = body[0]
    return isinstance(s, (ast.Pass, ast.Continue)) or (
        isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant) and s.value.value is Ellipsis)


def _empty_value(v) -> bool:
    if isinstance(v, ast.Constant):
        return v.value in (None, False, "", 0)
    if isinstance(v, (ast.List, ast.Tuple, ast.Set)):
        return not v.elts
    if isinstance(v, ast.Dict):
        return not v.keys
    return False


def _empties(body) -> bool:
    return bool(body) and all(isinstance(s, ast.Assign) and _empty_value(s.value) for s in body)


def _catches_import_error(handler) -> bool:
    names = {"ImportError", "ModuleNotFoundError"}
    t = handler.type
    if isinstance(t, ast.Name):
        return t.id in names
    if isinstance(t, ast.Tuple):
        return any(isinstance(e, ast.Name) and e.id in names for e in t.elts)
    return False


def _debugger_call(node) -> bool:
    """breakpoint(), or set_trace() on pdb, ipdb or pudb — a call the parser saw, so
    a comment, a docstring or a bare `import pdb` never counts."""
    f = node.func
    if isinstance(f, ast.Name):
        return f.id == "breakpoint"
    return (isinstance(f, ast.Attribute) and f.attr == "set_trace"
            and isinstance(f.value, ast.Name) and f.value.id in _PY_DEBUGGER_MODULES)


def _python(rel, text, lines, test, items, leads, imported, generated=False):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return None             # the line checks have run; a file the parser refuses gets no more
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                imported.add(node.module.split(".")[0])
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.Call):
            if not test and _debugger_call(node):
                items.append(_item("debugger_statement", 1, rel, node.lineno, lines[node.lineno - 1],
                                   "execution stops here in production"))
        elif isinstance(node, ast.Try):
            span = "\n".join(lines[node.lineno - 1:(node.body[-1].end_lineno or node.lineno)])
            for h in node.handlers:
                if not _broad(h):
                    continue
                if _does_nothing(h.body):
                    if not test:
                        items.append(_item("broad_swallow", 2, rel, h.lineno, lines[h.lineno - 1],
                                           "a broad exception handler that does nothing"))
                    if not test and _WRITE_CALL.search(span) and _SENSITIVE.search(span):
                        leads.append(_item(
                            "swallow_around_sensitive_write", 3, rel, h.lineno, lines[h.lineno - 1],
                            "a write to security or persisted state can fail here with nobody told — "
                            "check what the caller then assumes happened"))
                elif not test and _empties(h.body) and _READ_CALL.search(span) and _SENSITIVE.search(span):
                    leads.append(_item(
                        "security_read_fails_open", 3, rel, h.lineno, lines[h.lineno - 1],
                        "a failed read of security state becomes an empty value — check whether the "
                        "check it feeds then passes"))
    if not test:
        if not generated:       # a vendored module's imports are its authors' business
            _unused_imports(rel, tree, lines, items)
            leads.extend(_sql_py(rel, tree, lines))
        _commented_out_python(rel, lines, items)
        _todo_python(rel, text, items)
    return tree


def _unused_imports(rel, tree, lines, items):
    if rel.endswith("__init__.py"):
        return
    guarded = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(_catches_import_error(h) for h in node.handlers):
            guarded.update(id(n) for n in ast.walk(node))
        if isinstance(node, ast.If) and (
                (isinstance(node.test, ast.Name) and node.test.id == "TYPE_CHECKING")
                or (isinstance(node.test, ast.Attribute) and node.test.attr == "TYPE_CHECKING")):
            guarded.update(id(n) for n in ast.walk(node))
    used = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            used.add(node.id)
        elif isinstance(node, ast.Attribute):
            root = node
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                used.add(root.id)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and len(node.value) < 300:
            used.update(re.findall(r"[A-Za-z_]\w*", node.value))
    for node in tree.body:
        if id(node) in guarded or not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            continue
        text = lines[node.lineno - 1]
        if "noqa" in text:
            continue
        for a in node.names:
            bound = a.asname or a.name.split(".")[0]
            if a.name != "*" and bound not in used:
                items.append(_item("unused_import", 2, rel, node.lineno, f"{bound}: {text}",
                                   f"`{bound}` is imported and never used"))


def _commented_out_python(rel, lines, items):
    block = []
    for i, line in enumerate(lines + [""], 1):
        s = line.strip()
        if s.startswith("#") and not s.startswith(("#!", "# -*-", "# type:", "# noqa", "# pragma")):
            body = s[1:]
            block.append((i, body[1:] if body.startswith(" ") else body))
            continue
        if len(block) >= 2:
            try:
                tree = ast.parse("\n".join(t for _, t in block))
            except (SyntaxError, ValueError, RecursionError, MemoryError):
                tree = None
            if tree is not None and any(isinstance(n, _RICH) for n in ast.walk(tree)):
                first = block[0][0]
                items.append(_item("commented_out_code", 2, rel, first, lines[first - 1],
                                   "code kept as a comment: dead, and it reads as live"))
        block = []


def _todo_python(rel, text, items):
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type == tokenize.COMMENT and _TODO.search(tok.string):
                items.append(_item("todo_comment", 2, rel, tok.start[0], tok.string,
                                   "a TODO/FIXME/HACK left in the code"))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return


def _function_bodies(rel, tree):
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            span = (node.end_lineno or node.lineno) - node.lineno + 1
            if span < DUPLICATE_MIN_LINES:
                continue
            try:
                dump = ast.dump(ast.Module(body=node.body, type_ignores=[]), annotate_fields=False)
            except RecursionError:
                continue        # an expression too deep to print is no copy anyone made by hand
            out.append((hashlib.sha1(dump.encode("utf-8")).hexdigest()[:16], rel, node.lineno, node.name))
    return out


def _duplicates(bodies):
    groups: dict = {}
    for h, rel, line, name in bodies:
        groups.setdefault(h, []).append((rel, line, name))
    out = []
    for h, sites in groups.items():
        if len(sites) < 2:
            continue
        rel, line, name = sites[0]
        where = ", ".join(f"{r}:{ln} {n}" for r, ln, n in sites[:4])
        it = _item("duplicate_function", 2, rel, line, "",
                   f"{len(sites)} identical function bodies — a fix to one misses the others: {where}",
                   redacted=f"def {name} — {len(sites)} identical copies", key=h)
        it["sites"] = sorted({r for r, _ln, _n in sites})   # resolved only once every copy's file is read
        out.append(it)
    return out


def _unimported(files, imported, entry_text):
    out = []
    for rel in files:
        if "/" in rel or not rel.endswith(".py") or is_test_path(rel):
            continue
        stem = rel[:-3]
        if stem in ("setup", "conftest", "manage", "__init__", "noxfile", "tasks"):
            continue
        if stem not in imported and not re.search(r"\b" + re.escape(stem) + r"\b", entry_text):
            out.append(_item("module_never_imported", 3, rel, 1, rel,
                             "no module imports it and no documented command runs it — check whether it is dead"))
    return out
