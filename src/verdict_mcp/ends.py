"""Functions out of Ruby, Elixir and Lua for `verdict-local`: the languages whose blocks close on `end`.

Their blocks open on words (`def`, `do`, `if`, `function`) and close on `end`, and Ruby's
`return x if y` opens nothing. Pairing the words means parsing the language. Their code is laid out
by indentation instead, which RuboCop, `mix format` and every editor keep, and this module reads
that: a definition runs from its head to the `end` at its own indentation, or to the last line
before one indented less.

1. **Blank what is not code.** Comments, strings, heredocs, `%w[]` literals and sigils, `=begin`
   blocks and everything after `__END__` become spaces, newlines kept. A heredoc's lines at column 0
   would otherwise end the method around them.
2. **Find the definitions**: `def` and `def self.`, `defp` and `defmacro`, `function` and
   `local function`, `x = function`.
3. **Answer for a changed line.** The question is about the definition that holds the line if it
   fits in one question, and a window of it around the line if it does not. A line in no
   definition is read with the paragraph around it: a Rails `before_action`, a route, a Phoenix
   `plug`, a validation.

A Rails controller's `before_action` and a Phoenix controller's `plug` guard every action in it from
outside the method. So the question about a method carries its class's head and those lines, as a
C# question carries the attributes on its controller.
"""

from __future__ import annotations

import re

ENDS_LANGUAGES = ("ruby", "elixir", "lua")

# ── 1. what is not code becomes spaces ───────────────────────────────────────

_RUBY_HEREDOC = re.compile(r"<<([~-]?)(['\"`]?)([A-Za-z_]\w*)\2")
_RUBY_PERCENT = re.compile(r"%[qQwWiIrsx]?([^\w\s=])")
_CLOSERS = {"(": ")", "[": "]", "{": "}", "<": ">"}
# After these a `/` or a `%` starts a literal; after a name or a `)` it is arithmetic.
_LITERAL_AFTER = frozenset("(,=:[!&|?{};+-*%~^<>")
_LITERAL_WORDS = frozenset({"if", "unless", "when", "while", "until", "and", "or", "not", "return",
                            "puts", "print", "case", "in", "do", "then", "else", "elsif"})


def mask(text: str, lang: str) -> str:
    """`text` with comments, strings, heredocs and sigils turned to spaces, newlines kept."""
    if lang == "ruby":
        return _mask_ruby(text)
    if lang == "elixir":
        return _mask_elixir(text)
    return _mask_lua(text)


class _Out:
    def __init__(self, text: str):
        self.chars = list(text)
        self.n = len(text)

    def blank(self, a: int, b: int) -> None:
        for k in range(max(a, 0), min(b, self.n)):
            if self.chars[k] not in "\r\n":
                self.chars[k] = " "

    def text(self) -> str:
        return "".join(self.chars)


def _quoted_end(text: str, i: int, quote: str, holes: str = "", closer: str = "") -> int:
    """Just past the string opening at `i` with `quote` (or closing on `closer`, nesting on
    `quote`, for `%w[...]`), where `holes` opens interpolated code (`#{`) that may hold strings."""
    n = len(text)
    end_char = closer or quote
    depth = 0
    j = i + 1
    while j < n:
        ch = text[j]
        if ch == "\\":
            j += 2
            continue
        if holes and text.startswith(holes, j):
            j = _hole_end(text, j + len(holes))
            continue
        if closer and ch == quote:
            depth += 1
        elif ch == end_char:
            if depth == 0:
                return j + 1
            depth -= 1
        j += 1
    return n


def _hole_end(text: str, j: int) -> int:
    """Just past the `}` that closes `#{` code starting at `j`, past any strings inside it."""
    n = len(text)
    depth = 0
    while j < n:
        ch = text[j]
        if ch in "'\"":
            j = _quoted_end(text, j, ch, "#{" if ch == '"' else "")
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth == 0:
                return j + 1
            depth -= 1
        j += 1
    return n


def _mask_ruby(text: str) -> str:
    out = _Out(text)
    n = len(text)
    end_marker = re.search(r"^__END__\r?$", text, re.M)
    stop = end_marker.start() if end_marker else n
    out.blank(stop, n)
    i, last, word, line_start = 0, "", "", True
    pending: list = []                            # heredocs opened on this line, bodies next
    while i < stop:
        c = text[i]
        if c == "\n":
            j = i + 1
            for squiggly, ident in pending:
                close = re.compile((r"^[ \t]*" if squiggly else r"^") + re.escape(ident) + r"[ \t]*\r?$",
                                   re.M)
                found = close.search(text, j, stop)
                end = stop if found is None else found.end()
                out.blank(j, end)
                j = end
            pending = []
            line_start = True
            i = j if j > i + 1 else i + 1
            continue
        if c in " \t\r":
            i += 1
            continue
        if line_start and text.startswith("=begin", i):
            found = re.compile(r"^=end\b.*$", re.M).search(text, i, stop)
            end = stop if found is None else found.end()
            out.blank(i, end)
            i = end
            continue
        line_start = False
        if c == "#":
            j = text.find("\n", i, stop)
            j = stop if j < 0 else j
            out.blank(i, j)
            i = j
            continue
        regex_ok = last in _LITERAL_AFTER or last == "" or word in _LITERAL_WORDS
        end = None
        if c in "'\"`":
            end = _quoted_end(text, i, c, "" if c == "'" else "#{")
        elif c == ":" and i + 1 < n and text[i + 1] in "'\"":
            end = _quoted_end(text, i + 1, text[i + 1], "#{" if text[i + 1] == '"' else "")
        elif c == "<" and text.startswith("<<", i):
            m = _RUBY_HEREDOC.match(text, i)
            if m and (m.group(1) or m.group(2) or m.group(3).isupper()):
                pending.append((bool(m.group(1)), m.group(3)))
                end = m.end()
        elif c == "%" and regex_ok:
            m = _RUBY_PERCENT.match(text, i)
            if m:
                opener = m.group(1)
                end = _quoted_end(text, m.end() - 1, opener, "#{", _CLOSERS.get(opener, ""))
        elif c == "/" and regex_ok:
            j = i + 1
            while j < stop and text[j] not in "/\n":
                j += 2 if text[j] == "\\" else 1
            if j < stop and text[j] == "/":
                end = j + 1
        elif c == "?" and i + 1 < n and text[i + 1] in "'\"#" and (i + 2 >= n or not text[i + 2].isalnum()):
            end = i + 2                           # `?"`: a character, not a string
        if end is not None:
            out.blank(i, end)
            i, last, word = end, '"', ""
            continue
        if c.isalnum() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_?!"):
                j += 1
            word, last, i = text[i:j], "w", j
            continue
        last, word = c, ""
        i += 1
    return out.text()


_SIGIL = re.compile(r"~[A-Za-z]+(\"\"\"|'''|[/|\"'(\[{<])")


def _mask_elixir(text: str) -> str:
    out = _Out(text)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        end = None
        if c == "#":
            j = text.find("\n", i)
            end = n if j < 0 else j
        elif c == "?" and i + 1 < n:
            end = i + 3 if text[i + 1] == "\\" else i + 2      # `?a`, `?\n`, `?"`: a character
        elif c == "~":
            m = _SIGIL.match(text, i)
            if m:
                opener = m.group(1)
                if len(opener) == 3:
                    j = text.find(opener, m.end())
                    end = n if j < 0 else j + 3
                else:
                    end = _quoted_end(text, m.end() - 1, opener, "#{" if opener not in "'" else "",
                                      _CLOSERS.get(opener, ""))
        elif c in "\"'":
            if text.startswith(c * 3, i):
                j = text.find(c * 3, i + 3)
                end = n if j < 0 else j + 3
            else:
                end = _quoted_end(text, i, c, "#{")
        if end is not None:
            out.blank(i, end)
            i = end
            continue
        if c.isalnum() or c == "_":                # a name, so `x?` and `a_b` are not literals
            while i < n and (text[i].isalnum() or text[i] in "_?!"):
                i += 1
            continue
        i += 1
    return out.text()


_LUA_LONG = re.compile(r"\[(=*)\[")


def _mask_lua(text: str) -> str:
    out = _Out(text)
    n = len(text)
    i = 0
    while i < n:
        c = text[i]
        end = None
        if text.startswith("--", i):
            m = _LUA_LONG.match(text, i + 2)
            if m:
                close = "]" + m.group(1) + "]"
                j = text.find(close, m.end())
                end = n if j < 0 else j + len(close)
            else:
                j = text.find("\n", i)
                end = n if j < 0 else j
        elif c == "[":
            m = _LUA_LONG.match(text, i)
            if m:
                close = "]" + m.group(1) + "]"
                j = text.find(close, m.end())
                end = n if j < 0 else j + len(close)
        elif c in "\"'":
            j = i + 1
            while j < n and text[j] not in (c, "\n"):
                j += 2 if text[j] == "\\" else 1
            end = min(j + 1, n)
        if end is not None:
            out.blank(i, end)
            i = end
            continue
        i += 1
    return out.text()


# ── 2. definitions and what holds them ───────────────────────────────────────

_DEFS = {
    "ruby": re.compile(r"^([ \t]*)(?:(?:private|protected|public|module_function|"
                       r"private_class_method|memoize)\s+)?def\s+((?:self\.)?[A-Za-z_]\w*[?!=]?|"
                       r"[^\s(]+)"),
    "elixir": re.compile(r"^([ \t]*)(?:defp?|defmacrop?|defguardp?|defdelegate|defnp?)\s+"
                         r"([A-Za-z_]\w*[?!]?)"),
    "lua": re.compile(r"^([ \t]*)(?:local\s+)?function\s+([\w.:]+)|"
                      r"^([ \t]*)(?:local\s+)?([\w.:]+)\s*=\s*function\b"),
}
_CONTAINERS = {
    "ruby": re.compile(r"^([ \t]*)(?:class|module)\s+(?!<<)([A-Z][\w:]*)"),
    "elixir": re.compile(r"^([ \t]*)(?:defmodule|defimpl|defprotocol)\s+([\w.]+)"),
}
# Lines inside a class or module that guard or shape every action in it from outside the method.
_GUARDS = {
    "ruby": re.compile(r"^\s*(?:before_action|prepend_before_action|skip_before_action|around_action|"
                       r"before_filter|protect_from_forgery|skip_forgery_protection|"
                       r"http_basic_authenticate_with|load_and_authorize_resource|authorize_resource|"
                       r"skip_authorization_check|after_action|include)\b"),
    "elixir": re.compile(r"^\s*(?:plug|use|action_fallback)\b"),
}
_END = re.compile(r"^\s*end\b")
# Words at a definition's own indentation that go on with it: Ruby's method-level `rescue`.
_GOES_ON = re.compile(r"^\s*(?:rescue|ensure|else|catch|after)\b")


def _indent(line: str) -> int:
    expanded = line.expandtabs(8)
    return len(expanded) - len(expanded.lstrip(" "))


class Definition:
    __slots__ = ("name", "start", "head", "end", "indent", "context")

    def __init__(self, name, start, head, end, indent, context):
        self.name, self.start, self.head, self.end = name, start, head, end
        self.indent, self.context = indent, context


class Source:
    """A Ruby, Elixir or Lua file, read once: its masked lines and its definitions."""

    def __init__(self, text: str, lang: str):
        self.text, self.lang = text, lang
        self.lines = text.split("\n")
        self.masked = mask(text, lang).split("\n")
        self.defs = self._definitions()

    def code(self, k: int) -> bool:
        """Whether line `k` (1-based) has code: not blank, not only a comment, not only `end`."""
        line = self.masked[k - 1].strip()
        return bool(line) and line not in ("end", "end)", "end,", "end.", "do", "->", "}", "})",
                                           "private", "protected", "public", "module_function")

    def _definitions(self) -> list:
        pattern = _DEFS[self.lang]
        out = []
        for k, line in enumerate(self.masked, 1):
            m = pattern.match(line)
            if not m:
                continue
            groups = m.groups()
            indent_text = groups[0] if groups[0] is not None else groups[2]
            name = groups[1] if groups[1] is not None else groups[3]
            indent = _indent(indent_text or "")
            out.append(Definition(name, self._doc_start(k), k, self._end_of(k, indent), indent,
                                  self._context(k, indent)))
        return out

    def _doc_start(self, k: int) -> int:
        """The first line of the comments, `@doc` and `@spec` directly above line `k`."""
        start = k
        while start > 1:
            raw, masked = self.lines[start - 2], self.masked[start - 2]
            if not raw.strip():
                break
            if masked.strip() and not masked.strip().startswith("@"):
                break
            start -= 1
        return start

    def _end_of(self, k: int, indent: int) -> int:
        """The last line of the definition whose head is line `k`: its `end`, or the last line
        before one indented as little as it, or less."""
        last = k
        for j in range(k + 1, len(self.masked) + 1):
            line = self.masked[j - 1]
            if not line.strip():
                continue
            here = _indent(line)
            if here < indent:
                break
            if here == indent:
                if _END.match(line):
                    return j
                if _GOES_ON.match(line):
                    last = j
                    continue
                break
            last = j
        return last

    def _context(self, k: int, indent: int) -> str | None:
        """The head of the class or module that holds line `k`, with the lines in it that guard
        every method: `class OrdersController < ApplicationController; before_action ...`."""
        pattern = _CONTAINERS.get(self.lang)
        if pattern is None:
            return None
        for j in range(k - 1, 0, -1):
            line = self.masked[j - 1]
            if not line.strip() or _indent(line) >= indent:
                continue
            m = pattern.match(line)
            if not m:
                continue
            outer = _indent(m.group(1))
            parts = [self.lines[j - 1].strip()]
            guard = _GUARDS.get(self.lang)
            for g in range(j + 1, k):
                body = self.masked[g - 1]
                if body.strip() and _indent(body) <= outer:
                    break
                if guard is not None and guard.match(body):
                    parts.append(self.lines[g - 1].strip())
            text = "; ".join(parts)
            return text[:300]
        return None

    def source(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start - 1:end])


# ── 3. the questions a file holds ─────────────────────────────────────────────

def functions(text: str, lang: str, max_lines: int) -> list:
    """Every outermost definition of a file → `[(name, start, end, source, context)]`, clamped to
    `max_lines`."""
    src = Source(text, lang)
    out, covered_to = [], 0
    for d in src.defs:
        if d.head <= covered_to:
            continue                                # nested in the one before
        end = min(d.end, d.start + max_lines)
        out.append((d.name, d.start, end, src.source(d.start, end), d.context))
        covered_to = d.end
    return out


def around(text: str, lang: str, lines, max_lines: int) -> list:
    """The questions the changed `lines` of a file raise → `[(name, start, end, source, context)]`:
    the largest definition holding a line that fits in `max_lines`, a window of the innermost one
    when none does, and the paragraph around a line that sits in no definition."""
    src = Source(text, lang)
    total = len(src.lines)
    wanted = sorted({int(n) for n in lines if 1 <= int(n) <= total and src.code(int(n))})
    holding_of = {n: sorted((d for d in src.defs if d.start <= n <= d.end),
                            key=lambda d: d.start - d.end) for n in wanted}
    out, covered, last_paragraph = [], [], None
    for line in [n for n in wanted if holding_of[n]] + [n for n in wanted if not holding_of[n]]:
        if any(s <= line <= e for s, e in covered):
            continue
        holding = holding_of[line]
        chosen = next((d for d in holding if d.end - d.start <= max_lines), None)
        if chosen is not None:
            start, end, name, context = chosen.start, chosen.end, chosen.name, chosen.context
        elif holding:
            inner = holding[-1]
            start = max(inner.start, line - max_lines // 2)
            end = min(inner.end, start + max_lines)
            name, context = inner.name, inner.context
        else:
            start, end = _paragraph(src, line, max_lines)
            name, context = f"lines {start}-{end}", src._context(line, _indent(src.masked[line - 1]))
            if last_paragraph is not None:
                p_name, p_start, p_end, _source, p_context = out[last_paragraph]
                if start <= p_end + 2 and max(end, p_end) - p_start <= max_lines:
                    start, end = p_start, max(end, p_end)
                    covered[last_paragraph] = (start, end)
                    out[last_paragraph] = (f"lines {start}-{end}", start, end,
                                           src.source(start, end), p_context)
                    continue
            last_paragraph = len(out)
        covered.append((start, end))
        out.append((name, start, end, src.source(start, end), context))
    return sorted(out, key=lambda c: c[1])


def _paragraph(src: Source, line: int, max_lines: int) -> tuple:
    """The lines around `line` up to the nearest empty line on each side, at most `max_lines`."""
    total = len(src.lines)
    start = line
    while start > 1 and src.lines[start - 2].strip() and line - start < max_lines // 2:
        start -= 1
    end = line
    while end < total and src.lines[end].strip() and end - start < max_lines:
        end += 1
    return start, end
