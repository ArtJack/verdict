"""Tier 3, line-level leads: SQL built from strings, paid APIs called from the browser,
compose files with default passwords, and env placeholders.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

try:
    from .hygiene_const import LONG_LINE
    from .hygiene_patterns import (_COMMENT_MARKS, _COMPOSE_PASSWORD, _COMPOSE_PORT,
                                   _COMPOSE_PORTS, _CONSTANT_NAME, _DB_PORTS, _DEFAULT_PASSWORDS,
                                   _ENV_TEMPLATE, _JS_SQL_CONCAT, _JS_TEMPLATE, _LINE_LEADS,
                                   _PAID_API, _PLACEHOLDER_SECURITY_DEFAULT, _PUBLIC_ENV_SECRET,
                                   _SQL_BRACES, _SQL_IN_VALUES, _SQL_PERCENT, _SQL_SHAPE,
                                   _SQL_SLOT, _SQL_SLOT_LINE, _SQL_WHY, _USE_CLIENT)
    from .hygiene_scrub import _item, _scrub
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import LONG_LINE
    from hygiene_patterns import (_COMMENT_MARKS, _COMPOSE_PASSWORD, _COMPOSE_PORT, _COMPOSE_PORTS,
                                  _CONSTANT_NAME, _DB_PORTS, _DEFAULT_PASSWORDS, _ENV_TEMPLATE,
                                  _JS_SQL_CONCAT, _JS_TEMPLATE, _LINE_LEADS, _PAID_API,
                                  _PLACEHOLDER_SECURITY_DEFAULT, _PUBLIC_ENV_SECRET, _SQL_BRACES,
                                  _SQL_IN_VALUES, _SQL_PERCENT, _SQL_SHAPE, _SQL_SLOT,
                                  _SQL_SLOT_LINE, _SQL_WHY, _USE_CLIENT)
    from hygiene_scrub import _item, _scrub


# ── tier 3, line-level ────────────────────────────────────────────────────
def _line_leads(rel, lines):
    out = []
    for i, line in enumerate(lines, 1):
        if len(line) > LONG_LINE:
            continue
        for kind, rx, why in _LINE_LEADS:
            if rx.search(line) and not _PUBLIC_ENV_SECRET.search(line):
                context = _comments_above(lines, i)
                out.append(_item(kind, 3, rel, i, line,
                                 why + (f" (just above: {context})" if context else "")))
    return out


def _sql_slot(before: str) -> bool:
    """Whether the SQL text before an interpolation leaves it in a value's place."""
    return bool(_SQL_SLOT.search(before) or _SQL_IN_VALUES.search(before))


def _sql_safe_value(node) -> bool:
    """A value that cannot carry outside text: a literal, an ALL_CAPS constant, a cast."""
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Name):
        return bool(_CONSTANT_NAME.match(node.id))
    if isinstance(node, ast.Attribute):
        return bool(_CONSTANT_NAME.match(node.attr))
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("int", "float", "len"))


def _sql_line(lines, node) -> int:
    """The line of a multi-line SQL string where the value goes in, else where it starts."""
    end = min(getattr(node, "end_lineno", None) or node.lineno, len(lines))
    for n in range(node.lineno, end + 1):
        if _SQL_SLOT_LINE.search(lines[n - 1]):
            return n
    return node.lineno


def _sql_py(rel, tree, lines):
    """Python: an f-string, a `%` or `.format()` on a SQL literal, or a `+` chain, that puts
    a value in a value's place."""
    out, inner = [], set()

    def lead(line):
        out.append(_item("sql_from_string", 3, rel, line,
                         lines[line - 1] if 0 < line <= len(lines) else "", _SQL_WHY))

    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values
                           if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if not _SQL_SHAPE.search(text):
                continue
            before = ""
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    before += v.value
                elif isinstance(v, ast.FormattedValue):
                    if _sql_slot(before) and not _sql_safe_value(v.value):
                        lead(_sql_line(lines, node))
                        break
                    before += "?"
        elif (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mod)
              and isinstance(node.left, ast.Constant) and isinstance(node.left.value, str)
              and _SQL_SHAPE.search(node.left.value)):
            s = node.left.value
            if any(_sql_slot(s[:m.start()]) for m in _SQL_PERCENT.finditer(s)):
                lead(node.lineno)
        elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
              and node.func.attr == "format" and isinstance(node.func.value, ast.Constant)
              and isinstance(node.func.value.value, str)
              and _SQL_SHAPE.search(node.func.value.value)):
            s = node.func.value.value
            if any(_sql_slot(s[:m.start()]) for m in _SQL_BRACES.finditer(s)):
                lead(node.lineno)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add) and id(node) not in inner:
            parts, stack = [], [node]
            while stack:            # the whole `+` chain once, left to right
                n = stack.pop()
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                    inner.add(id(n))
                    stack += [n.right, n.left]
                else:
                    parts.append(n)
            text = "".join(p.value for p in parts if isinstance(p, ast.Constant) and isinstance(p.value, str))
            if not _SQL_SHAPE.search(text):
                continue
            before = ""
            for p in parts:
                if isinstance(p, ast.Constant) and isinstance(p.value, str):
                    before += p.value
                elif _sql_slot(before) and not _sql_safe_value(p):
                    lead(node.lineno)
                    break
                else:
                    before += "?"
    return out


def _sql_js(rel, lines):
    """JS/TS: a template literal or a `+` on a SQL literal that puts a value in a value's
    place. A tagged template — sql`…`, Prisma.sql`…` — binds its values: nothing to say."""
    out = []
    for i, line in enumerate(lines, 1):
        if len(line) > LONG_LINE or not _SQL_SHAPE.search(line):
            continue
        hit = False
        for m in _JS_TEMPLATE.finditer(line):
            body = m.group(1)
            if (m.start() and re.match(r"[\w$]", line[m.start() - 1])) or not _SQL_SHAPE.search(body):
                continue
            if any(_sql_slot(body[:k.start()]) for k in re.finditer(r"\$\{", body)):
                hit = True
                break
        if not hit:
            hit = any(_SQL_SHAPE.search(m.group(2)) and _sql_slot(m.group(2))
                      for m in _JS_SQL_CONCAT.finditer(line))
        if hit:
            out.append(_item("sql_from_string", 3, rel, i, line, _SQL_WHY))
    return out


def _browser_side(rel: str, suffix: str, lines) -> bool:
    """Code that runs in the browser: a Vue or Svelte component, a file under public/ or
    static/, or a module that opens with 'use client'."""
    if suffix in (".vue", ".svelte"):
        return True
    if {"public", "static"} & set(rel.lower().split("/")[:-1]):
        return True
    for line in lines[:20]:
        s = line.strip()
        if s and not s.startswith(("//", "/*", "*")):
            return bool(_USE_CLIENT.match(s))
    return False


def _paid_api_from_browser(rel, suffix, lines):
    if not _browser_side(rel, suffix, lines):
        return []
    return [_item("paid_api_from_browser", 3, rel, i, line,
                  "a paid API is called from code that runs in the browser — whatever key it "
                  "sends, every visitor can read")
            for i, line in enumerate(lines, 1)
            if len(line) <= LONG_LINE and _PAID_API.search(line)]


def _compose(rel, lines):
    """A compose file's database password left at a default, and its database ports
    published on every interface. A port counts only under a `ports:` key, read by
    indentation: `expose:` publishes nothing."""
    out, ports_at = [], None
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        # YAML lets a list sit level with its key, so a dash at the key's own depth is
        # still one of its items.
        if ports_at is not None and (indent < ports_at
                                     or (indent == ports_at and not stripped.startswith("-"))):
            ports_at = None
        key = _COMPOSE_PORTS.match(line)
        if key:
            ports_at = len(key.group("indent"))
            continue
        if ports_at is not None:
            p = _COMPOSE_PORT.match(line)
            ip = (p.group("ip") or "") if p else ""
            loopback = ip.startswith("127.") or ip in ("localhost", "[::1]")
            if p and int(p.group("container")) in _DB_PORTS and not loopback:
                out.append(_item("compose_db_port_published", 3, rel, i, line,
                                 "a database port is published on every interface of the host — "
                                 "Docker's rules sit ahead of its firewall; bind it to 127.0.0.1 "
                                 "or leave it unpublished"))
            continue
        pw = _COMPOSE_PASSWORD.match(line)
        if pw and pw.group("value").lower() in _DEFAULT_PASSWORDS:
            out.append(_item("compose_default_password", 3, rel, i, line,
                             "a database password left at a well-known default — check this "
                             "file never runs anywhere but a laptop"))
    return out


def _comments_above(lines, i):
    """What the author wrote in the two lines above line i — comments only. Code is
    never carried: the line above a TLS switch is as likely the key it guards."""
    notes = [s for s in (ln.strip() for ln in lines[max(0, i - 3):i - 1]) if s.startswith(_COMMENT_MARKS)]
    return _scrub(" | ".join(notes))[:160]


def _env_placeholders(rel, name, lines):
    if not (name.startswith(".env") and _ENV_TEMPLATE.search(name)) and not name.endswith(".env.example"):
        return []
    return [_item("placeholder_security_default", 3, rel, i, line,
                  f"{m.group(1)} ships with a placeholder — check that startup refuses it")
            for i, line in enumerate(lines, 1) if (m := _PLACEHOLDER_SECURITY_DEFAULT.match(line))]
