"""Code inside markup, and code read as excerpts, for `verdict-local`.

Two kinds of file hold code that the brace and `end` readers cannot take whole:

- **Code inside markup.** Vue and Svelte components, Astro pages, HTML pages and Razor views keep
  their code in regions: `<script>`, Astro's front matter, Razor's `@code { }`. Each region is read
  by its own language's reader on a copy of the file where everything outside it is blank, so every
  line keeps its number. A component's template is code too, with its bindings, conditions and
  handlers, and it is read as a template. So is an HTML page's markup when it carries a template
  language's tags. Styles are not read.
- **Everything else.** Every other programming language, and every template language, is read as
  excerpts: each changed line with the lines around it, neighbours merged, at most one question
  long. No function boundary is claimed, and the question says it shows lines, not a function.
"""

from __future__ import annotations

import re
from typing import NamedTuple

try:
    from . import braces, languages
except ImportError:  # imported as a plain module beside small.py
    import braces
    import languages


class Piece(NamedTuple):
    """One question's worth of a file: its lines, what holds them, and how to ask about them."""
    name: str
    start: int
    end: int
    source: str
    context: str | None
    lang: str
    unit: str                    # function, excerpt or template


# Lines either side of a changed line in an excerpt: enough to see the statement and its guard.
AROUND = 6

_SCRIPT = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.S | re.I)
_STYLE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.S | re.I)
_FRONT_MATTER = re.compile(r"\A(\s*---[ \t]*\r?\n)(.*?)(\r?\n---[ \t]*)(?:\r?\n|\Z)", re.S)
_TEMPLATE_BLOCK = re.compile(r"<template\b[^>]*>", re.I)
_RAZOR_CODE = re.compile(r"@(?:code|functions)\s*\{|@\{")
_TYPE = re.compile(r"""\btype\s*=\s*["']?([^"'\s>]+)""", re.I)
_LANG = re.compile(r"""\blang\s*=\s*["']?([^"'\s>]+)""", re.I)
_SRC = re.compile(r"\bsrc\s*=", re.I)
# A script type that is code. Anything else (`application/ld+json`, `text/x-template`, `importmap`)
# is data or markup.
_SCRIPT_TYPES = {"", "module", "text/javascript", "application/javascript", "text/babel",
                 "text/jsx", "text/typescript", "application/typescript", "text/ecmascript"}
# Tags that make an HTML page a template: Jinja and Django, Handlebars, Angular, Vue and Alpine
# attributes, htmx, Thymeleaf.
_TEMPLATE_SYNTAX = re.compile(r"\{%|\{\{|\*ng[A-Z]|\[\(?[\w.]+\)?\]=|\(\w+\)=|\bv-(?:if|for|bind|on|"
                              r"model|show|html)\b|\bx-(?:data|if|on|bind|show|html)\b|\bhx-[a-z]+=|"
                              r"\bth:[a-z]+=|@click")
_COMMENT_ONLY = re.compile(r"^\s*(?:<!--.*-->|\{#.*#\}|\{\{!.*\}\}|<%#.*%>|@\*.*\*@)\s*$")


def _view(text: str, spans) -> str:
    """`text` with everything outside `spans` blank and every newline kept."""
    out = [c if c in "\r\n" else " " for c in text]
    for a, b in spans:
        out[a:b] = text[a:b]
    return "".join(out)


def _script_lang(attrs: str, default: str) -> str | None:
    """The language of a `<script>` from its attributes, or None for one that holds no code."""
    lang = _LANG.search(attrs)
    if lang:
        value = lang.group(1).lower()
        return "typescript" if value in ("ts", "tsx", "typescript") else "javascript"
    kind = _TYPE.search(attrs)
    value = kind.group(1).lower() if kind else ""
    if value not in _SCRIPT_TYPES:
        return None
    return "typescript" if "typescript" in value else default


def code_regions(text: str, lang: str) -> list:
    """`[(inner language, start, end)]`: the code a markup file holds, by offset."""
    out = []
    default = "typescript" if lang == "astro" else "javascript"
    if lang == "astro":
        m = _FRONT_MATTER.match(text)
        if m:
            out.append(("typescript", m.start(2), m.end(2)))
    if lang == "razor":
        for m in _RAZOR_CODE.finditer(text):
            close = _matching_brace(text, m.end() - 1)
            if close is not None:
                out.append(("csharp", m.end(), close))
        return out
    for m in _SCRIPT.finditer(text):
        inner = _script_lang(m.group(1), default)
        body = m.group(2)
        if inner is None or (_SRC.search(m.group(1)) and not body.strip()):
            continue
        out.append((inner, m.start(2), m.end(2)))
    return out


def _matching_brace(text: str, open_: int) -> int | None:
    """The offset of the `}` that closes the C# block opening at `open_` in a Razor view."""
    view = " " * open_ + text[open_:]
    masked = braces.mask(view, "csharp")
    depth = 0
    for k in range(open_, len(masked)):
        if masked[k] == "{":
            depth += 1
        elif masked[k] == "}":
            depth -= 1
            if depth == 0:
                return k
    return None


def template_spans(text: str, lang: str, regions) -> list:
    """`[(start, end)]`: the template a markup file holds, outside its code and its styles. An
    HTML page has one only when its markup carries a template language's tags."""
    taken = sorted([(a, b) for _lang, a, b in regions] + [m.span() for m in _STYLE.finditer(text)])
    if lang == "vue":
        first = _TEMPLATE_BLOCK.search(text)
        last = text.lower().rfind("</template")
        bounds = [(first.start(), last)] if first and last > first.start() else []
    elif lang == "astro":
        m = _FRONT_MATTER.match(text)
        bounds = [(m.end() if m else 0, len(text))]
    else:
        bounds = [(0, len(text))]
    out = []
    for lo, hi in bounds:
        at = lo
        for a, b in taken:
            if b <= at or a >= hi:
                continue
            if a > at:
                out.append((at, a))
            at = max(at, b)
        if at < hi:
            out.append((at, hi))
    if lang == "html" and not any(_TEMPLATE_SYNTAX.search(text, a, b) for a, b in out):
        return []
    return out


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def read(text: str, lang: str, lines, max_lines: int) -> list:
    """The questions a Vue, Svelte, Astro, HTML or Razor file raises → `[Piece]`: its code by its
    own language's reader, its template as excerpts. `lines` None reads the whole file."""
    regions = code_regions(text, lang)
    out = []
    by_lang: dict = {}
    for inner, a, b in regions:
        by_lang.setdefault(inner, []).append((a, b))
    for inner, spans in by_lang.items():
        view = _view(text, spans)
        inside = [(_line_of(text, a), _line_of(text, b)) for a, b in spans]
        if lines is None:
            found = braces.functions(view, inner, max_lines)
        else:
            mine = [n for n in lines if any(s <= n <= e for s, e in inside)]
            found = braces.around(view, inner, mine, max_lines) if mine else []
        out += [Piece(name, start, end, "\n".join(text.split("\n")[start - 1:end]), context, inner,
                      "function") for name, start, end, _source, context in found]
    spans = template_spans(text, lang, regions)
    if spans:
        view = _view(text, spans)
        inside = [(_line_of(text, a), _line_of(text, b)) for a, b in spans]
        mine = None if lines is None else [n for n in lines if any(s <= n <= e for s, e in inside)]
        if mine is None or mine:
            out += windows(view, lang, mine, max_lines, unit="template", shown=text)
    return sorted(out, key=lambda p: p.start)


_CLOSING_TAG = re.compile(r"^(?:</[\w.:-]+>\s*)+$")


def _has_code(line: str, comment: str) -> bool:
    """Whether a line holds something to read: not blank, not only a comment or a closing tag."""
    s = line.strip()
    if not s or (comment and s.lower().startswith(comment)) or _COMMENT_ONLY.match(s) \
            or _CLOSING_TAG.match(s):
        return False
    return bool(s.strip("{}()[];,") and s not in ("end", "fi", "done", "esac", "endif", "})"))


def windows(text: str, lang: str, lines, max_lines: int, unit: str = "excerpt",
            shown: str | None = None) -> list:
    """Excerpts → `[Piece]`: each changed line with `AROUND` lines either side, neighbours merged,
    none longer than `max_lines`. With `lines` None, the whole file in paragraphs. `shown` is the
    text the excerpt prints when `text` is a view with parts blanked."""
    comment = languages.comment_of(lang).lower()
    all_lines = text.split("\n")
    printed = (shown if shown is not None else text).split("\n")
    total = len(all_lines)

    def _foreign(k):
        return not all_lines[k - 1].strip() and bool(printed[k - 1].strip())

    if lines is None:
        spans = _paragraphs(all_lines, comment, max_lines)
    else:
        spans = []
        for n in sorted({int(n) for n in lines if 1 <= int(n) <= total}):
            if not _has_code(all_lines[n - 1], comment):
                continue
            lo, hi = n, n
            # Out to `AROUND` lines either side, stopping at code that belongs to another reader
            # (blank here, written in the file): a Razor view's `@code` block, a component's script.
            while lo > max(1, n - AROUND) and not _foreign(lo - 1):
                lo -= 1
            while hi < min(total, n + AROUND) and not _foreign(hi + 1):
                hi += 1
            while lo < n and not all_lines[lo - 1].strip():
                lo += 1
            while hi > n and not all_lines[hi - 1].strip():
                hi -= 1
            if spans and lo <= spans[-1][1] + 1:
                p_lo, p_hi = spans[-1]
                if max(hi, p_hi) - p_lo <= max_lines:
                    spans[-1] = (p_lo, max(hi, p_hi))
                    continue
                lo = p_hi + 1
                if lo > n:
                    continue
            spans.append((lo, min(hi, lo + max_lines)))
    return [Piece(f"lines {a}-{b}", a, b, "\n".join(printed[a - 1:b]), None, lang, unit)
            for a, b in spans]


def _paragraphs(all_lines, comment: str, max_lines: int) -> list:
    """The file as runs of non-empty lines, short runs merged, long ones cut, each with code."""
    runs, start = [], None
    for k, line in enumerate(all_lines + [""], 1):
        if line.strip() and start is None:
            start = k
        elif not line.strip() and start is not None:
            runs.append((start, k - 1))
            start = None
    out = []
    for a, b in runs:
        while b - a > max_lines:
            out.append((a, a + max_lines))
            a += max_lines + 1
        if out and b - out[-1][0] <= max_lines and a - out[-1][1] <= 2:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return [(a, b) for a, b in out
            if any(_has_code(all_lines[k - 1], comment) for k in range(a, b + 1))]
