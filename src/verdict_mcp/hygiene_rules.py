"""Tier 1, rules: database rules that allow everyone, row-level security switched off, and
debuggers left in shipped code.

Split out of hygiene.py by the structure pass (2026-11-15) as a pure move: every block below is
byte-identical to what it was there, and hygiene.py imports back what its callers use.
"""
from __future__ import annotations

import bisect
import re
import sys
from pathlib import Path

try:
    from .hygiene_const import LONG_LINE
    from .hygiene_patterns import (_C_TOKENS, _DOWN_MIGRATION, _DOWN_SECTION, _JS_DEBUGGER,
                                   _PUBLIC_RULE_WHY, _RLS_OPEN_POLICY, _RLS_SWITCH, _RTDB_RULE,
                                   _RULES_TOKEN, _SQL_TOKENS)
    from .hygiene_paths import is_test_path
    from .hygiene_scrub import _item
    from .hygiene_secrets import _uncomment
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hygiene_const import LONG_LINE
    from hygiene_patterns import (_C_TOKENS, _DOWN_MIGRATION, _DOWN_SECTION, _JS_DEBUGGER,
                                  _PUBLIC_RULE_WHY, _RLS_OPEN_POLICY, _RLS_SWITCH, _RTDB_RULE,
                                  _RULES_TOKEN, _SQL_TOKENS)
    from hygiene_paths import is_test_path
    from hygiene_scrub import _item
    from hygiene_secrets import _uncomment


def _line_starts(text: str) -> list:
    return [0] + [m.end() for m in re.finditer("\n", text)]


def _line_at(starts: list, pos: int) -> int:
    """The 1-based line holding offset `pos` of a joined text."""
    return bisect.bisect_right(starts, pos)


def _database_rules(rel, low, suffix, lines, found):
    if low.endswith(".rules.json"):
        _realtime_rules(rel, lines, found)
    elif low.endswith(".rules"):
        _allow_rules(rel, low, lines, found)
    elif suffix == ".sql" and not _DOWN_MIGRATION.search(rel.lower()):
        _sql(rel, lines, found)


def _realtime_rules(rel, lines, found):
    """Realtime Database rules, read as one text so that `".write":` and its `true`
    on the next line are one rule: one finding per line with an open write, one
    lead per line with an open read and no open write."""
    text = "\n".join(_uncomment(lines, _C_TOKENS))
    starts = _line_starts(text)
    writes, reads = [], []
    for m in _RTDB_RULE.finditer(text):
        (writes if m.group("op") == "write" else reads).append(_line_at(starts, m.start()))
    for i in sorted(set(writes)):
        found["items"].append(_item("open_database_rules", 1, rel, i, lines[i - 1],
                                    'anyone can write here: the rule sets ".write" to true'))
    for i in sorted(set(reads) - set(writes)):
        found["leads"].append(_item("public_database_rule", 3, rel, i, lines[i - 1], _PUBLIC_RULE_WHY))


def _allow_rules(rel, low, lines, found):
    """Firestore and Storage `allow` statements with `if true` or no condition. An
    allow belongs to the innermost match still open, tracked with a brace stack: an
    allow after a recursive child block closes is its parent's, not recursive. The
    file is read as one text, so a `{` on the line after its match, or an `if true`
    on the line after its allow, is still where it belongs."""
    text = "\n".join(_uncomment(lines, _C_TOKENS))
    starts = _line_starts(text)
    firestore = low == "firestore.rules" or "cloud.firestore" in text
    stack: list = []
    for m in _RULES_TOKEN.finditer(text):
        if m.group("path") is not None:
            stack.append(m.group("path"))
        elif m.group("methods") is not None:
            i = _line_at(starts, m.start())
            inside = next((p for p in reversed(stack) if p is not None), "")
            _open_allow(rel, i, lines[i - 1], m.group("methods"), inside, firestore, found)
        elif m.group("brace") == "{":
            stack.append(None)
        elif m.group("brace") == "}":
            stack = stack[:-1]
        # anything else is a string: its braces are text, not blocks


def _open_allow(rel, i, line, methods, inside, firestore, found):
    said = "allow " + ", ".join(x.strip() for x in methods.split(","))
    if any(x.strip() in ("write", "update", "delete") for x in methods.split(",")):
        found["items"].append(_item("open_database_rules", 1, rel, i, line,
                                    f"anyone can change or delete data here: `{said}` has no condition"))
    elif firestore and "**" in inside:
        found["items"].append(_item(
            "open_database_rules", 1, rel, i, line,
            f"every document is open to anyone: `{said}` has no condition under the recursive "
            f"match {inside}"))
    else:
        found["leads"].append(_item("public_database_rule", 3, rel, i, line, _PUBLIC_RULE_WHY))


def _sql(rel, lines, found):
    """Row-level security switches, kept as events and judged once every file is
    read: a table counts by its final state, not by a disable a later migration
    undid. The file is cut at its down marker before anything else, then its
    comments, so prose that says "disable" is not a switch. A seed file runs on a
    developer's machine, never in production, so it records no switch."""
    up = next((lines[:n] for n, ln in enumerate(lines) if _DOWN_SECTION.match(ln)), lines)
    text = "\n".join(_uncomment(up, _SQL_TOKENS))
    starts = _line_starts(text)
    events = []
    if not _seed(rel):
        for m in _RLS_SWITCH.finditer(text):
            i = _line_at(starts, m.start())
            events.append((rel, i, _table(m.group(1)), m.group(2).lower(), lines[i - 1]))
    leads = [_item("rls_policy_using_true", 3, rel, i, lines[i - 1],
                   "a row-level-security policy that lets every row through — check it is meant to be public")
             for i in sorted({_line_at(starts, m.start()) for m in _RLS_OPEN_POLICY.finditer(text)})]
    found["events"] += events   # whole or not at all: a file that fails leaves none half-told
    found["leads"] += leads


def _seed(rel: str) -> bool:
    parts = rel.lower().split("/")
    return ((parts[-1].startswith("seed") and parts[-1].endswith(".sql"))
            or any(p in ("seed", "seeds") for p in parts[:-1]))


def _rls_source(rel: str) -> bool:
    """A SQL file whose switches decide a table's state, were it read."""
    low = rel.lower()
    return (low.endswith(".sql") and not is_test_path(rel) and not _DOWN_MIGRATION.search(low)
            and not _seed(rel))


def _table(raw: str) -> str:
    name = re.sub(r"\s+", "", raw.replace('"', "")).lower()
    return name[len("public."):] if name.startswith("public.") else name


def _rls_disabled(events):
    last: dict = {}
    for event in sorted(events, key=lambda e: (e[0], e[1])):
        last[event[2]] = event
    return [_item("open_database_rules", 1, rel, line, text,
                  "row-level security is switched off: the anon key can read every row")
            for rel, line, _table_name, action, text in last.values() if action == "disable"]


def _js_debuggers(rel, text, lines):
    """`debugger` alone on its line once comments are gone: one inside a block
    comment, or in a comment's prose, stops nothing."""
    if "debugger" not in text:
        return []
    code = _uncomment(lines, _C_TOKENS)
    return [_item("debugger_statement", 1, rel, i, lines[i - 1], "execution stops here in production")
            for i, line in enumerate(code, 1)
            if len(lines[i - 1]) <= LONG_LINE and _JS_DEBUGGER.match(line)]
