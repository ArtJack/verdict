"""Functions out of C#, TypeScript and JavaScript for `verdict-local`, with no parser dependency.

`ast` hands the local engine every Python function with the lines it really occupies, and the
standard library has nothing like it for a brace language. So the engine read Python only: a range
that changed C# or TypeScript had its gates measured and no code read, and the report said so in a
fixed sentence. That was honest, and on a .NET or web project it left most of the code unread on
every run.

This module does the least that lets the same bounded question be asked of a brace language:

1. **Blank what is not code.** Strings, characters, comments, template literals and regular
   expressions become spaces, newlines kept, so every brace and parenthesis left is structure and
   every offset is still on its own line.
2. **Pair the braces** and judge each block by the text before its `{`: a type, a control
   statement, an object or initializer, or something a question can be asked about — a method, a
   constructor, an accessor, a local function, a lambda, a C# property.
3. **Answer for a changed line.** The question is about the largest function around the line that
   still fits in one question. A function too long for that is read as a window around the change,
   and a line inside no function — a field, an expression-bodied member, a top-level statement — as
   the statement that holds it.

It is a reader, not a compiler. A block it misjudges still hands the model the right lines with the
file's own numbers, which is all the question needs; the tests pin the shapes that matter.
"""

from __future__ import annotations

import bisect
import re

LANGUAGES = {".cs": "csharp", ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript",
             ".cts": "typescript", ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript",
             ".cjs": "javascript"}
NAMES = {"python": "Python", "csharp": "C#", "typescript": "TypeScript", "javascript": "JavaScript"}
FENCES = {"python": "python", "csharp": "csharp", "typescript": "ts", "javascript": "js"}

# Code nobody here wrote by hand, or wrote but does not own: a question about it is spent on what
# the project cannot fix.
_GENERATED = re.compile(r"(?:\.min\.js|\.d\.[cm]?ts|\.g\.cs|\.g\.i\.cs|\.designer\.cs|"
                        r"\.generated\.[a-z]+|modelsnapshot\.cs|assemblyinfo\.cs)$")
_VENDORED = frozenset({"node_modules", "bin", "obj", "dist", ".next", ".nuxt", "coverage",
                       "vendor", ".git", ".venv", "venv", "migrations"})
_TEST_PATH = re.compile(r"(?:^|/)(?:tests?|__tests__|__mocks__|e2e|specs?)/|"
                        r"[._](?:test|spec)\.[cm]?[jt]sx?$|tests?\.cs$|(?:^|/)[^/]*\.tests?/")


def language_of(path) -> str | None:
    """`python`, `csharp`, `typescript`, `javascript`, or None for a file this engine cannot read."""
    lower = str(path).lower()
    if lower.endswith(".py"):
        return "python"
    for ext, lang in LANGUAGES.items():
        if lower.endswith(ext):
            return lang
    return None


def is_test_path(path) -> bool:
    """A C#, TypeScript or JavaScript test by its name or folder."""
    return bool(_TEST_PATH.search(str(path).replace("\\", "/").lower()))


def is_generated(path) -> bool:
    """Generated, minified, vendored or built: not code anyone here would fix."""
    lower = str(path).replace("\\", "/").lower()
    parts = set(lower.split("/")[:-1])
    return bool(_GENERATED.search(lower)) or bool(parts & _VENDORED) or "/wwwroot/lib/" in f"/{lower}"


def readable(path) -> bool:
    """A brace-language source file this engine asks questions about: not a test, not generated."""
    lang = language_of(path)
    return lang in ("csharp", "typescript", "javascript") and not is_generated(path) \
        and not is_test_path(path)


# ── 1. what is not code becomes spaces ───────────────────────────────────────

_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%~^")
_REGEX_WORDS = frozenset({"return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
                          "void", "throw", "yield", "await", "instanceof"})


def mask(text: str, lang: str) -> str:
    """`text` with every string, character, comment, template and regular-expression literal turned
    to spaces, newlines kept: the same length, the same lines, and every brace left is code."""
    out = list(text)
    n = len(text)

    def blank(a, b):
        for k in range(a, min(b, n)):
            if out[k] not in "\r\n":
                out[k] = " "

    i, last, word, line_start = 0, "", "", True
    while i < n:
        c = text[i]
        if c == "\n":
            line_start = True
            i += 1
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if lang == "csharp" and line_start and c == "#":        # #if, #region, #nullable ...
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        line_start = False
        nxt = text[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = text.find("\n", i)
            j = n if j < 0 else j
            blank(i, j)
            i = j
            continue
        if c == "/" and nxt == "*":
            j = text.find("*/", i + 2)
            j = n if j < 0 else j + 2
            blank(i, j)
            i = j
            continue
        if lang == "csharp":
            end = _cs_literal(text, i) if c in "$@\"'" else None
        else:
            regex_ok = c == "/" and (last == "" or last in _REGEX_AFTER or word in _REGEX_WORDS)
            end = _js_literal(text, i, regex_ok) if c in "'\"`/" else None
        if end is not None:
            blank(i, end)
            i, last, word = end, '"', ""
            continue
        if c.isalnum() or c in "_$":
            j = i
            while j < n and (text[j].isalnum() or text[j] in "_$"):
                j += 1
            word, last, i = text[i:j], text[j - 1], j
            continue
        last, word = c, ""
        i += 1
    return "".join(out)


def _cs_literal(text: str, i: int) -> int | None:
    """The end of the C# string or character literal starting at `i`, or None if none starts there:
    regular, verbatim (`@"`), interpolated (`$"`, `$@"`, `@$"`) and raw (`\"\"\"`)."""
    n = len(text)
    k, dollars, verbatim = i, 0, False
    while k < n and text[k] in "$@" and k - i < 4:
        dollars += text[k] == "$"
        verbatim = verbatim or text[k] == "@"
        k += 1
    if k >= n:
        return None
    if text[k] == "'" and k == i:
        return _char_end(text, k)
    if text[k] != '"':
        return None
    quotes = 0
    while k + quotes < n and text[k + quotes] == '"':
        quotes += 1
    if quotes >= 3 and not verbatim:                    # a raw literal closes on its own run
        j = text.find('"' * quotes, k + quotes)
        return n if j < 0 else j + quotes
    j = k + 1
    while j < n:
        ch = text[j]
        if verbatim and ch == '"':
            if j + 1 < n and text[j + 1] == '"':
                j += 2
                continue
            return j + 1
        if not verbatim:
            if ch == "\\":
                j += 2
                continue
            if ch == '"':
                return j + 1
            if ch == "\n":
                return None                             # a regular string never spans lines
        if dollars and ch == "{":
            if j + 1 < n and text[j + 1] == "{":
                j += 2
                continue
            j = _hole_end(text, j + 1, "csharp")
            continue
        j += 1
    return n if verbatim else None


def _char_end(text: str, k: int) -> int | None:
    n = len(text)
    if k + 1 >= n:
        return None
    if text[k + 1] == "\\":
        j = text.find("'", k + 3, k + 12)
        return None if j < 0 else j + 1
    return k + 3 if k + 2 < n and text[k + 2] == "'" and text[k + 1] != "\n" else None


def _js_literal(text: str, i: int, regex_ok: bool) -> int | None:
    """The end of the JavaScript or TypeScript literal starting at `i`, or None."""
    n = len(text)
    c = text[i]
    if c in "'\"":
        j = i + 1
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == c:
                return j + 1
            if ch == "\n":
                return None                 # not a string: JSX text, an apostrophe in prose
            j += 1
        return None
    if c == "`":
        j = i + 1
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "`":
                return j + 1
            if ch == "$" and j + 1 < n and text[j + 1] == "{":
                j = _hole_end(text, j + 2, "javascript")
                continue
            j += 1
        return n
    if c == "/" and regex_ok:
        j, in_class = i + 1, False
        while j < n:
            ch = text[j]
            if ch == "\\":
                j += 2
                continue
            if ch == "\n":
                return None
            if in_class:
                in_class = ch != "]"
            elif ch == "[":
                in_class = True
            elif ch == "/":
                j += 1
                while j < n and text[j].isalpha():
                    j += 1
                return j
            j += 1
        return None
    return None


def _hole_end(text: str, j: int, lang: str) -> int:
    """The end of an interpolation hole that starts at `j` (just past its `{`): code, which may
    hold literals of its own, up to the `}` that closes it."""
    n = len(text)
    depth, last = 0, "{"
    while j < n:
        ch = text[j]
        if ch == "/" and j + 1 < n and text[j + 1] in "/*":
            k = text.find("\n" if text[j + 1] == "/" else "*/", j + 2)
            j = n if k < 0 else (k if text[j + 1] == "/" else k + 2)
            continue
        if lang == "csharp" and ch in "$@\"'":
            end = _cs_literal(text, j)
        elif lang != "csharp" and ch in "'\"`/":
            end = _js_literal(text, j, ch != "/" or last in _REGEX_AFTER)
        else:
            end = None
        if end is not None:
            j, last = end, '"'
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            if depth == 0:
                return j + 1
            depth -= 1
        if not ch.isspace():
            last = ch
        j += 1
    return n


# ── 2. blocks, and what each one is ──────────────────────────────────────────

FUNCTION_KINDS = frozenset({"function", "lambda", "accessor", "property"})

_ATTRIBUTES = re.compile(r"^(?:\s*\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\])+")
_DECORATORS = re.compile(r"^(?:\s*@[\w.$]+(?:\(\))?)+")
_CONTROL = re.compile(r"^(?:else|if|for|foreach|while|do|switch|try|catch|finally|using|lock|fixed|"
                      r"unsafe|checked|unchecked|with|case\b[^{]*:|default\s*:)(?![\w$])")
_CS_TYPE = re.compile(r"(?<![\w$.])(?:class|struct|interface|record|enum|namespace)(?![\w$])")
_JS_TYPE = re.compile(r"(?<![\w$.])(?:class|interface|enum|namespace|module)(?![\w$.])|"
                      r"^(?:export\s+)?(?:declare\s+)?(?:global|type\s+[\w$]+)")
_GENERIC = r"(?:<[^<>]*(?:<[^<>]*(?:<[^<>]*>[^<>]*)*>[^<>]*)*>)?"
_CALLABLE = re.compile(r"(#?[A-Za-z_$][\w$]*|\[[^\]]*\])\s*" + _GENERIC + r"\s*\(\)\s*(?::.*)?$")
_ACCESSOR = re.compile(r"^(?:(?:public|private|protected|internal|readonly)\s+)*(get|set|init|add|remove)$")
_PROPERTY = re.compile(r"^[\w<>\[\],.?\s:@]*?[\w>\]?]\s+([A-Za-z_][\w]*(?:\.[A-Za-z_]\w*)*)$")
_INDEXER = re.compile(r"\bthis\s*\[[^\]]*\]$")
_AUTO_PROPERTY = re.compile(r"^\s*(?:(?:(?:public|private|protected|internal|required)\s+)*"
                            r"(?:get|set|init)\s*;\s*)+$")
_NOT_A_NAME = frozenset({"if", "for", "foreach", "while", "switch", "catch", "using", "lock", "fixed",
                         "return", "new", "typeof", "nameof", "sizeof", "default", "checked",
                         "unchecked", "function", "await", "throw", "else", "do", "with", "in",
                         "of", "case", "when", "where", "base", "this"})
_ASSIGNED = re.compile(r"([A-Za-z_$#][\w$]*)\s*(?::[^=]*)?=\s*(?:async\s*)?(?:<[^<>]*>\s*)?"
                       r"(?:\(\)|[\w$]+)?\s*(?::[^=]*)?=>$")
_OPEN_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*" + _GENERIC + r"\s*\((?:[^()]|\(\))*$")
_FUNCTION_KEYWORD = re.compile(r"(?<![\w$])function\s*\*?\s*([\w$]*)\s*" + _GENERIC + r"\s*\(\)")


def _flatten(head: str) -> str:
    """Every closed `(...)` becomes `()`, innermost first, and whitespace collapses."""
    head = " ".join(head.split())
    previous = None
    while previous != head:
        previous, head = head, re.sub(r"\([^()]*\)", "()", head)
    return head


def classify(head: str, lang: str) -> tuple[str, str]:
    """`(kind, name)` for the block whose `{` follows `head` (masked text, comments blanked)."""
    bare = _ATTRIBUTES.sub("", head) if lang == "csharp" else _DECORATORS.sub("", head)
    bare = _flatten(bare)
    if lang == "csharp":
        bare = re.sub(r"\s+where\s+[\w.]+\s*:.*$", "", bare)                    # generic constraints
        bare = re.sub(r"(\(\))\s*:\s*(?:base|this)\s*\(\)$", r"\1", bare)        # ctor initializer
    bare = bare.strip()
    if not bare:
        return "other", ""
    if _CONTROL.match(bare):
        return "control", ""
    if (_CS_TYPE if lang == "csharp" else _JS_TYPE).search(bare.split("(")[0]):
        m = re.search(r"(class|struct|interface|record|enum|namespace|module|type)\s+([\w$.]+)", bare)
        # An interface, an enum or a type alias declares a shape and does nothing: a line in one
        # asks no question. A class, a record, a struct or a namespace holds code.
        shape = m is not None and m.group(1) in ("interface", "enum", "type")
        return ("shape" if shape else "type"), (m.group(2) if m else "")
    if lang == "csharp" and (m := _ACCESSOR.match(bare)):
        return "accessor", m.group(1)
    if bare.endswith("=>"):
        m = _ASSIGNED.search(bare) or _OPEN_CALL.search(bare)
        return "lambda", (m.group(1) if m else "lambda")
    if lang != "csharp" and (m := _FUNCTION_KEYWORD.search(bare)):
        if m.group(1):
            return "function", m.group(1)
        m = _ASSIGNED.search(bare.replace("function", "") + "=>") or _OPEN_CALL.search(
            bare[:bare.rfind("function")])
        return "function", (m.group(1) if m else "function")
    if re.search(r"(?:^|[=(,:?\[&|]|\breturn|\bnew\b[\w.<>\[\]\s]*?(?:\(\))?|\bswitch|\bwith)\s*$", bare):
        return "object", ""
    if m := _CALLABLE.search(bare):
        name = m.group(1)
        before = bare[:m.start()].rstrip()
        if name in _NOT_A_NAME or before.endswith("new") or before.endswith("."):
            return "other", ""
        return "function", name
    if lang == "csharp":
        if _INDEXER.search(bare):
            return "property", "this[]"
        if "=" not in bare and (m := _PROPERTY.match(bare)):
            return "property", m.group(1).rsplit(".", 1)[-1]
    return "other", ""


def _head_start(masked: str, open_: int) -> int:
    """Where the head of the block opening at `open_` starts: just past the nearest `;`, `{` or `}`
    that is not inside a parenthesized or bracketed group. A destructured parameter
    (`function Card({ title }: Props) {`), an object passed as an argument or a `for (;;)` is part
    of the head, not the end of the statement before it."""
    depth = 0                                   # groups closed after this point, read backwards
    j = open_ - 1
    while j >= 0:
        ch = masked[j]
        if ch in ")]":
            depth += 1
        elif ch in "([":
            depth = max(depth - 1, 0)           # an unclosed group: the head runs on through it
        elif ch == "}" and depth > 0:
            nested = 1
            j -= 1
            while j >= 0 and nested:
                nested += {"}": 1, "{": -1}.get(masked[j], 0)
                j -= 1
            continue
        elif ch in ";{}" and depth == 0:
            return j + 1
        j -= 1
    return 0


class Block:
    """One `{ ... }` pair: where its head starts, what it is, and what encloses it."""

    __slots__ = ("open", "close", "head_at", "kind", "name", "parent", "head")

    def __init__(self, open_, close, head_at, kind, name, parent, head):
        self.open, self.close, self.head_at = open_, close, head_at
        self.kind, self.name, self.parent, self.head = kind, name, parent, head


class Source:
    """A brace-language file, read once: masked text, line offsets and its blocks."""

    def __init__(self, text: str, lang: str):
        self.text, self.lang = text, lang
        self.masked = mask(text, lang)
        self.starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
        self.lines = text.splitlines()
        self.blocks = self._blocks()

    def line_of(self, offset: int) -> int:
        return bisect.bisect_right(self.starts, offset)

    def _blocks(self) -> list:
        stack, pairs = [], []
        for i, ch in enumerate(self.masked):
            if ch == "{":
                stack.append(i)
            elif ch == "}" and stack:
                pairs.append((stack.pop(), i))
        pairs.sort()
        blocks, open_stack = [], []
        for open_, close in pairs:
            while open_stack and blocks[open_stack[-1]].close < open_:
                open_stack.pop()
            parent = open_stack[-1] if open_stack else None
            begin = _head_start(self.masked, open_)
            head = self.masked[begin:open_]
            head_at = begin + (len(head) - len(head.lstrip()))
            # The head starts at its first character in the file as written, so the doc comment
            # and the attributes above a member come with it.
            raw = self.text[begin:open_]
            raw_at = begin + (len(raw) - len(raw.lstrip()))
            kind, name = classify(head, self.lang)
            inside = parent
            while inside is not None and blocks[inside].kind not in FUNCTION_KINDS:
                inside = blocks[inside].parent
            if inside is not None and kind in ("type", "shape"):
                # Inside a function a "type" is markup that says "class" (JSX text) or a local
                # declaration: either way it is part of the function's own question.
                kind = "other"
            if kind == "property" and _AUTO_PROPERTY.match(self.masked[open_ + 1:close]):
                kind = "shape"          # `{ get; init; }` holds no code to ask about
            if kind == "accessor" and parent is not None:
                name = f"{blocks[parent].name}.{name}" if blocks[parent].name else name
            blocks.append(Block(open_, close, min(head_at, raw_at), kind, name, parent, head))
            open_stack.append(len(blocks) - 1)
        return blocks

    def span(self, block: Block) -> tuple:
        return self.line_of(block.head_at), self.line_of(block.close)

    def context(self, offset: int) -> str | None:
        """The head of the type that holds `offset` — its attributes, name and bases — as one line:
        the guard an attribute puts on a whole controller is outside every method of it."""
        best = None
        for b in self.blocks:
            if b.kind == "type" and b.open < offset <= b.close and (best is None or b.open > best.open):
                best = b
        if best is None:
            return None
        raw = self.text[best.head_at:best.open]
        kept = [ln.strip() for ln in raw.splitlines()
                if ln.strip() and not ln.strip().startswith(("//", "/*", "*"))]
        line = " ".join(" ".join(kept).split())
        return line[:300] if line else None

    def source(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start - 1:end])


# ── 3. the questions a file holds ─────────────────────────────────────────────

def _outermost_functions(src: Source) -> list:
    def inside_function(b):
        p = b.parent
        while p is not None:
            if src.blocks[p].kind in FUNCTION_KINDS:
                return True
            p = src.blocks[p].parent
        return False
    return [b for b in src.blocks if b.kind in FUNCTION_KINDS and not inside_function(b)]


def functions(text: str, lang: str, max_lines: int) -> list:
    """Every outermost function of a file → `[(name, start, end, source, context)]`, clamped to
    `max_lines` the way the Python reader clamps a long function."""
    src = Source(text, lang)
    out = []
    for b in _outermost_functions(src):
        start, end = src.span(b)
        end = min(end, start + max_lines)
        out.append((b.name or f"line {start}", start, end, src.source(start, end), src.context(b.open)))
    return out


def around(text: str, lang: str, lines, max_lines: int) -> list:
    """The questions the changed `lines` of a file raise → `[(name, start, end, source, context)]`.

    For each line: the largest function holding it that fits in `max_lines`; failing that, a
    window of the innermost one around the line; and for a line inside no function, the statement
    that holds it. Lines inside a function are answered first, so a statement never swallows one.
    A line already inside an earlier answer adds nothing, and a line that is only a type's head,
    a brace, a comment or an import asks nothing at all."""
    src = Source(text, lang)
    funcs = [b for b in src.blocks if b.kind in FUNCTION_KINDS]
    spans = {id(b): src.span(b) for b in funcs}
    heads = [(src.line_of(b.head_at), src.line_of(b.open)) for b in src.blocks if b.kind == "type"]
    heads += [(src.line_of(b.head_at), src.line_of(b.close)) for b in src.blocks if b.kind == "shape"]
    wanted = sorted({int(n) for n in lines if 1 <= int(n) <= len(src.lines)})
    wanted = [n for n in wanted if _has_code(src, n) and not any(s <= n <= e for s, e in heads)]
    holding_of = {n: sorted((b for b in funcs if spans[id(b)][0] <= n <= spans[id(b)][1]),
                            key=lambda b: spans[id(b)][0] - spans[id(b)][1]) for n in wanted}
    out, covered, last_statement = [], [], None
    for line in [n for n in wanted if holding_of[n]] + [n for n in wanted if not holding_of[n]]:
        if any(s <= line <= e for s, e in covered):
            continue
        holding = holding_of[line]                                            # largest first
        chosen = next((b for b in holding if spans[id(b)][1] - spans[id(b)][0] <= max_lines), None)
        if chosen is not None:
            start, end = spans[id(chosen)]
            name, at = chosen.name or f"line {start}", chosen.open
        elif holding:
            inner = holding[-1]
            lo, hi = spans[id(inner)]
            start = max(lo, line - max_lines // 2)
            end = min(hi, start + max_lines)
            name, at = inner.name or f"line {lo}", inner.open
        else:
            found = _statement(src, line, max_lines)
            if found is None:
                continue
            start, end, name = found
            at = src.starts[line - 1]
            # Statements next to each other are one question: a pipeline of top-level calls is
            # judged by its order, and three one-line members read better together than apart.
            if last_statement is not None:
                p_name, p_start, p_end, _source, p_context = out[last_statement]
                if start <= p_end + 2 and max(end, p_end) - p_start <= max_lines:
                    start, end = p_start, max(end, p_end)
                    name = p_name if p_name == name else f"lines {start}-{end}"
                    covered[last_statement] = (start, end)
                    out[last_statement] = (name, start, end, src.source(start, end), p_context)
                    continue
            last_statement = len(out)
        covered.append((start, end))
        out.append((name, start, end, src.source(start, end), src.context(at)))
    return sorted(out, key=lambda c: c[1])


def _has_code(src: Source, line: int) -> bool:
    """Code on the line once strings and comments are blanked — not only braces and separators."""
    begin = src.starts[line - 1]
    end = src.starts[line] if line < len(src.starts) else len(src.masked)
    return bool(src.masked[begin:end].strip(" \t\r\n{}();,"))


_MEMBER_NAMES = (
    re.compile(r"(?:const|let|var|function\*?|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"([A-Za-z_$][\w$]*)\s*" + _GENERIC + r"\s*(?:\(\)\s*)?=>"),
    re.compile(r"([A-Za-z_$][\w$]*)\s*(?:=(?!=)|;|$)"),
)
# Statements that ask nothing: imports, `using` directives, a file-scoped namespace, a directive
# string. They are read as masked and flattened text, so their string parts are already blank.
_NOTHING_TO_ASK = re.compile(r"^(?:global\s+)?using\s+(?:static\s+)?[\w.]+(?:\s*=\s*[\w.<>,\s]+)?;?$|"
                             r"^namespace\s+[\w.]+\s*;?$|^import\b|^export\s+(?:type\s+)?(?:\*|\{[^}]*\})"
                             r"(?:\s+as\s+[\w$]+)?\s+from\b|^;?$")


_BARE_NEW = re.compile(r"\bnew\b\s*[\w.<>\[\],?\s]*\(\)")


def _statement(src: Source, line: int, max_lines: int) -> tuple | None:
    """`(start, end, name)` of the statement holding `line`, at most `max_lines` long, or None
    when it is one that asks nothing. A `{` at its own depth ends it unless that block is an object
    or an initializer: a statement never runs on into a type, a function or a control block."""
    offset = src.starts[line - 1]
    masked, n = src.masked, len(src.masked)
    cut = max(masked.rfind(d, 0, offset) for d in ";{}")
    begin = cut + 1
    raw = src.text[begin:offset]
    begin += len(raw) - len(raw.lstrip())
    opens = {b.open: b for b in src.blocks}
    depth, j = 0, begin
    while j < n:
        ch = masked[j]
        if ch == "{" and depth == 0 and j in opens and opens[j].kind not in ("object", "other"):
            j -= 1
            break
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
            if depth < 0:
                break
        elif ch == ";" and depth == 0:
            break
        j += 1
    head = _flatten(masked[begin:min(j + 1, n)])
    if _NOTHING_TO_ASK.match(head):
        return None
    # A declaration with nothing to run — a field, a constant, a literal — has no behaviour to
    # judge, and a model asked about one line of it invents the code it was not shown. `new()`
    # alone is construction, not behaviour.
    behaviour = _BARE_NEW.sub("", head)
    if "=>" not in behaviour and "(" not in behaviour and "{" not in behaviour:
        return None
    start, end = src.line_of(begin), max(src.line_of(min(max(j, begin), n - 1)), line)
    if end - start > max_lines:
        start = max(start, line - max_lines // 2)
        end = min(end, start + max_lines)
    name = ""
    # `const string Prefix = ...` is C#: there the keyword is followed by a type, not a name.
    for pattern in (_MEMBER_NAMES[1:] if src.lang == "csharp" else _MEMBER_NAMES):
        m = pattern.search(head)
        if m and m.group(1) not in _NOT_A_NAME:
            name = m.group(1)
            break
    return start, end, name or f"line {line}"
