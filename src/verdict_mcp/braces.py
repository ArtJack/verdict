"""Functions out of the brace languages for `verdict-local`, with no parser dependency.

`ast` hands the local engine every Python function with the lines it really occupies, and the
standard library has nothing like it for any other language. So the engine read Python only: a
range that changed C# or TypeScript had its gates measured and no code read, and the report said so
in a fixed sentence. That was honest, and on a .NET or web project it left most of the code unread on
every run.

Fifteen languages share one shape: a block is a pair of braces, and what the block is shows in the
text before its `{`. C#, TypeScript and JavaScript were the first (2026-11-06). Java, Kotlin, Scala,
Groovy, Go, Rust, Swift, Dart, C, C++, PHP and Solidity followed (2026-11-11). Each brings its own
literals, among them Go's backtick strings, Rust's `r#"…"#` and lifetimes that look like characters,
the templates of Kotlin, Swift and Dart, and PHP's heredocs and the HTML around its tags. Each also
has its own words for a function and a type. Past those, the reader is one:

1. **Blank what is not code.** Strings, characters, comments, templates, heredocs and regular
   expressions become spaces, newlines kept, so every brace and parenthesis left is structure and
   every offset is still on its own line. In a PHP file, so does the HTML outside `<?php … ?>`.
2. **Pair the braces** and judge each block by the text before its `{`: a type, a control
   statement, an object or initializer, or something a question can be asked about — a method, a
   constructor, an accessor, a local function, a lambda, a property with a body.
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
from typing import NamedTuple

try:
    from . import languages as _languages
except ImportError:  # imported as a plain module beside small.py
    import languages as _languages

BRACE_LANGUAGES = tuple(k for k, lang in _languages.LANGUAGES.items() if lang.family == "braces")
LANGUAGES = {suffix: key for suffix, key in _languages._SUFFIXES.items() if key in BRACE_LANGUAGES}
NAMES = {key: lang.name for key, lang in _languages.LANGUAGES.items()}
FENCES = {key: lang.fence for key, lang in _languages.LANGUAGES.items()}

language_of = _languages.language_of
is_test_path = _languages.is_test_path
is_generated = _languages.is_generated

_C_SHARP_AND_JS = ("csharp", "typescript", "javascript")
_JS = ("typescript", "javascript")


def readable(path) -> bool:
    """A brace-language source file this engine asks questions about: not a test, not generated."""
    return language_of(path) in BRACE_LANGUAGES and not is_generated(path) and not is_test_path(path)


# ── 1. what is not code becomes spaces ───────────────────────────────────────

_REGEX_AFTER = frozenset("(,=:[!&|?{};+-*%~^")
_REGEX_WORDS = frozenset({"return", "typeof", "case", "do", "else", "in", "of", "new", "delete",
                          "void", "throw", "yield", "await", "instanceof"})


class _Spec(NamedTuple):
    """The literals of a brace language other than C#, TypeScript and JavaScript."""
    quotes: str = '"'          # what opens an ordinary string
    multiline: str = ""        # of those, the strings that may run across lines
    char: bool = False         # `'x'` is a character; a `'` that closes nothing is punctuation
    triple: str = ""           # what opens a triple-quoted string
    triple_raw: bool = False   # a backslash in a triple-quoted string is text (Kotlin, Scala)
    holes: tuple = ()          # what opens code inside a string: "${", "{$", "\\("
    hole_quotes: str = '"'     # the strings that have holes
    hole_prefix: bool = False  # holes only after an interpolator, as in Scala's s"…"
    raw: str = ""              # whose raw strings: go, rust, cpp, swift or dart
    heredoc: bool = False      # PHP's <<<ID … ID
    nested: bool = False       # block comments nest


_SPECS = {
    "java": _Spec(char=True, triple='"'),
    "kotlin": _Spec(char=True, triple='"', triple_raw=True, holes=("${",), nested=True),
    "scala": _Spec(char=True, triple='"', triple_raw=True, holes=("${",), hole_prefix=True,
                   nested=True),
    "groovy": _Spec(quotes="\"'", triple="\"'", holes=("${",)),
    "go": _Spec(char=True, raw="go"),
    "rust": _Spec(multiline='"', char=True, raw="rust", nested=True),
    "swift": _Spec(triple='"', holes=("\\(",), raw="swift", nested=True),
    "dart": _Spec(quotes="\"'", triple="\"'", holes=("${",), hole_quotes="\"'", raw="dart",
                  nested=True),
    "c": _Spec(char=True, raw="cpp"),
    "cpp": _Spec(char=True, raw="cpp"),
    "php": _Spec(quotes="\"'`", multiline="\"'`", holes=("{$", "${"), heredoc=True),
    "solidity": _Spec(quotes="\"'"),
}
# Languages whose `#` at the start of a line is a directive: `#if`, `#region`, `#include`.
_PREPROCESSED = frozenset({"csharp", "c", "cpp"})
_PHP_OPEN = re.compile(r"<\?(?:php\b|=|(?!xml))", re.I)
_PHP_TAG = re.compile(r"<\?(?:php\b|=)?|\?>", re.I)
_RUST_RAW = re.compile(r'[bc]?r(#*)"')
_CPP_RAW = re.compile(r'(?:u8|u|U|L)?R"([^()\\\s"]{0,16})\(')
_SWIFT_RAW = re.compile(r'(#+)("""|")')
_PHP_HEREDOC = re.compile(r'<<<[ \t]*(["\']?)([A-Za-z_][A-Za-z0-9_]*)\1[ \t]*\r?\n')


def mask(text: str, lang: str, keep_literals: bool = False) -> str:
    """`text` with every string, character, comment, template and regular-expression literal turned
    to spaces, newlines kept: the same length, the same lines, and every brace left is code.
    `keep_literals` blanks comments and leaves the literals as written: what a line says, for
    deciding whether it says anything."""
    out = list(text)
    n = len(text)

    def blank(a, b, literal=False):
        if literal and keep_literals:
            return
        for k in range(a, min(b, n)):
            if out[k] not in "\r\n":
                out[k] = " "

    spec = _SPECS.get(lang)
    i, last, word, line_start = 0, "", "", True
    html = lang == "php"                # a PHP file is HTML until its first `<?php`
    while i < n:
        if html:
            m = _PHP_OPEN.search(text, i)
            j = n if m is None else m.end()
            blank(i, j)
            i, html, last, word, line_start = j, False, ";", "", False
            continue
        c = text[i]
        if c == "\n":
            line_start = True
            i += 1
            continue
        if c in " \t\r\f\v":
            i += 1
            continue
        if lang in _PREPROCESSED and line_start and c == "#":   # #if, #region, #include ...
            j = _directive_end(text, i, lang)
            blank(i, j)
            i = j
            continue
        line_start = False
        nxt = text[i + 1] if i + 1 < n else ""
        if lang == "php" and c == "?" and nxt == ">":
            blank(i, i + 2)
            i, html = i + 2, True
            continue
        if (c == "/" and nxt == "/") or (lang == "php" and c == "#" and nxt != "["):
            j = text.find("\n", i)
            j = n if j < 0 else j
            if lang == "php":                   # a line comment ends at `?>` too
                k = text.find("?>", i, j)
                j = j if k < 0 else k
            blank(i, j)
            i = j
            continue
        if c == "/" and nxt == "*":
            j = _block_comment_end(text, i, spec is not None and spec.nested)
            blank(i, j)
            i = j
            continue
        if lang == "csharp":
            end = _cs_literal(text, i) if c in "$@\"'" else None
        elif lang in _JS or spec is None:
            regex_ok = c == "/" and (last == "" or last in _REGEX_AFTER or word in _REGEX_WORDS)
            end = _js_literal(text, i, regex_ok) if c in "'\"`/" else None
        else:
            end = _literal(text, i, lang, spec)
        if end is not None:
            blank(i, end, literal=True)
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


def _directive_end(text: str, i: int, lang: str) -> int:
    """The end of a preprocessor directive: its line, and in C and C++ every line a trailing
    backslash continues it onto."""
    n = len(text)
    j = i
    while True:
        k = text.find("\n", j)
        if k < 0:
            return n
        if lang in ("c", "cpp") and text[max(k - 2, 0):k].rstrip("\r").endswith("\\"):
            j = k + 1
            continue
        return k


def _block_comment_end(text: str, i: int, nested: bool) -> int:
    n = len(text)
    if not nested:
        j = text.find("*/", i + 2)
        return n if j < 0 else j + 2
    depth, j = 1, i + 2
    while j < n and depth:
        if text.startswith("/*", j):
            depth, j = depth + 1, j + 2
        elif text.startswith("*/", j):
            depth, j = depth - 1, j + 2
        else:
            j += 1
    return j


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


def _literal(text: str, i: int, lang: str, spec: _Spec) -> int | None:
    """The end of the literal starting at `i` in a brace language other than C#, TypeScript and
    JavaScript, or None when none starts there."""
    n = len(text)
    c = text[i]
    prev = text[i - 1] if i else ""
    fresh = not (prev.isalnum() or prev in "_$")
    if spec.raw == "go" and c == "`":
        j = text.find("`", i + 1)
        return n if j < 0 else j + 1
    if spec.raw == "rust" and c in "rbc" and fresh:
        m = _RUST_RAW.match(text, i)
        if m:
            close = '"' + m.group(1)
            j = text.find(close, m.end())
            return n if j < 0 else j + len(close)
    if spec.raw == "cpp" and c in "uULR" and fresh:
        m = _CPP_RAW.match(text, i)
        if m:
            close = ")" + m.group(1) + '"'
            j = text.find(close, m.end())
            return n if j < 0 else j + len(close)
    if spec.raw == "swift" and c == "#":
        m = _SWIFT_RAW.match(text, i)
        if m:
            close = m.group(2) + m.group(1)
            j = text.find(close, m.end())
            return n if j < 0 else j + len(close)
    if spec.raw == "dart" and c == "r" and fresh and i + 1 < n and text[i + 1] in "'\"":
        q = text[i + 1]
        if text.startswith(q * 3, i + 1):
            j = text.find(q * 3, i + 4)
            return n if j < 0 else j + 3
        j = i + 2
        while j < n and text[j] not in (q, "\n"):
            j += 1
        return j + 1 if j < n and text[j] == q else None
    if spec.heredoc and c == "<" and text.startswith("<<<", i):
        m = _PHP_HEREDOC.match(text, i)
        if m:
            close = re.compile(r"^[ \t]*" + re.escape(m.group(2)) + r"(?![A-Za-z0-9_\x80-￿])",
                               re.M)
            found = close.search(text, m.end())
            return n if found is None else found.end()
    if c == "'" and spec.char:
        return _char_end(text, i)           # None for a lifetime or a stray quote: punctuation
    if c not in spec.quotes:
        return None
    holes = spec.holes if c in spec.hole_quotes else ()
    if spec.hole_prefix and fresh:          # Scala: `"${x}"` is text, `s"${x}"` has a hole
        holes = ()
    if c in spec.triple and text.startswith(c * 3, i):
        j = i + 3
        while j < n:
            if text.startswith(c * 3, j):
                k = j + 3
                while k < n and text[k] == c:      # `""""` closes on the last quote of its run
                    k += 1
                return k
            opened = _hole_open(text, j, holes)
            if opened is not None:
                j = _hole_close(text, opened, lang, spec, holes)
                continue
            j += 2 if text[j] == "\\" and not spec.triple_raw else 1
        return n
    j = i + 1
    while j < n:
        ch = text[j]
        opened = _hole_open(text, j, holes)
        if opened is not None:
            j = _hole_close(text, opened, lang, spec, holes)
            continue
        if ch == "\\":
            j += 2
            continue
        if ch == c:
            return j + 1
        if ch == "\n" and c not in spec.multiline:
            return None                     # an apostrophe in prose, a quote that closes nothing
        j += 1
    return n if c in spec.multiline else None


def _hole_open(text: str, j: int, holes) -> int | None:
    """Where the code of a hole starting at `j` begins, or None. In PHP's `{$x}` the `$` is code."""
    for hole in holes:
        if text.startswith(hole, j):
            return j + 1 if hole == "{$" else j + len(hole)
    return None


def _hole_close(text: str, j: int, lang: str, spec: _Spec, holes) -> int:
    """Just past the bracket that closes a hole whose code starts at `j`: a `}`, or in Swift's
    `\\(…)` a `)`. The code may hold strings of its own."""
    n = len(text)
    opener, closer = ("(", ")") if "\\(" in holes else ("{", "}")
    depth = 0
    while j < n:
        ch = text[j]
        if ch in spec.quotes or ch == "`" and spec.raw == "go":
            end = _literal(text, j, lang, spec)
            if end is not None:
                j = end
                continue
        if ch == opener:
            depth += 1
        elif ch == closer:
            if depth == 0:
                return j + 1
            depth -= 1
        j += 1
    return n


# ── 2. blocks, and what each one is ──────────────────────────────────────────

FUNCTION_KINDS = frozenset({"function", "lambda", "accessor", "property"})
# Blocks whose lines ask nothing: a shape declares and does nothing; a test module is not the code.
QUIET_KINDS = frozenset({"shape", "tests"})

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
                         "of", "case", "when", "where", "base", "this", "synchronized", "alignof",
                         "decltype", "static_assert", "elseif", "match", "guard", "defer", "go",
                         "select", "loop", "unsafe", "try", "super"})
_ASSIGNED = re.compile(r"([A-Za-z_$#][\w$]*)\s*(?::[^=]*)?=\s*(?:async\s*)?(?:<[^<>]*>\s*)?"
                       r"(?:\(\)|[\w$]+)?\s*(?::[^=]*)?=>$")
_OPEN_CALL = re.compile(r"([A-Za-z_$][\w$]*)\s*" + _GENERIC + r"\s*\((?:[^()]|\(\))*$")
_FUNCTION_KEYWORD = re.compile(r"(?<![\w$])function\s*\*?\s*([\w$]*)\s*" + _GENERIC + r"\s*\(\)")


def _flatten(head: str) -> str:
    """Every closed `(...)` becomes `()`, innermost first, and whitespace collapses. An inner group
    is held as a mark until its outer one closes: written back as `()` at once, it left
    `(xs []T, f func(T) U)` with parentheses inside, which no later pass could flatten."""
    head = " ".join(head.split())
    previous = None
    while previous != head:
        previous, head = head, re.sub(r"\([^()]*\)", "\x01", head)
    return head.replace("\x01", "()")


def classify(head: str, lang: str) -> tuple[str, str]:
    """`(kind, name)` for the block whose `{` follows `head` (masked text, comments blanked)."""
    if lang not in _C_SHARP_AND_JS:
        return _classify_other(head, lang)
    # A decorator's arguments are flattened before it is taken off: `@Controller('orders')` and
    # `@Component({ … })` left their parentheses behind, and the class after them was no type.
    bare = _ATTRIBUTES.sub("", head) if lang == "csharp" else _DECORATORS.sub("", _flatten(head))
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


# ── the other brace languages ────────────────────────────────────────────────

_ANNOTATIONS = re.compile(r"^(?:\s*(?:@[\w.$:]+(?:\s*\(\))?|#!?\[[^\]]*\]))+")
_CONTROL_WORDS = {
    "java": "synchronized",
    "kotlin": "when",
    "scala": "match|yield",
    "groovy": "synchronized",
    "go": "select|go|defer",
    "rust": "loop|match|unsafe|async|move|const",
    "swift": "guard|repeat|defer",
    "dart": "on|await\\s+for",
    "php": "foreach|elseif|declare|match",
    "solidity": "unchecked|assembly",
    "c": "",
    "cpp": "",
}
_OTHER_CONTROL = {lang: re.compile(r"^(?:else|if|for|while|do|switch|try|catch|finally|"
                                   + (words + "|" if words else "") + r"case\b[^{]*:|default\s*:)(?![\w$])")
                  for lang, words in _CONTROL_WORDS.items()}
_CONTROL_AT_END = re.compile(r"(?<![\w$.])(?:if|when|try|match|switch|else|do|finally|loop|unsafe|"
                             r"async|select)\s*(?:\(\))?$")
_TYPE_WORDS = {
    "java": "class|interface|enum|record|@interface",
    "kotlin": "class|interface|object",
    "scala": "class|object|trait|enum",
    "groovy": "class|interface|trait|enum",
    "rust": "struct|enum|union|trait|impl|mod",
    "swift": "class|struct|enum|protocol|extension|actor",
    "dart": "class|mixin|extension|enum",
    "c": "struct|union|enum",
    "cpp": "class|struct|union|enum|namespace",
    "php": "class|interface|trait|enum|namespace",
    "solidity": "contract|interface|library|struct|enum",
}
_TYPES = {lang: re.compile(r"(?<![\w$.])(" + words + r")(?![\w$])(?:\s+([\w$.]+))?")
          for lang, words in _TYPE_WORDS.items()}
# Declared as shapes. One that turns out to hold a function body is a type after all: a Java
# interface's default method, a Swift enum's method, a C++ struct's member function.
_SHAPE_WORDS = frozenset({"interface", "enum", "struct", "union", "protocol", "@interface"})
_GO_TYPE = re.compile(r"^type\s+([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)?(?:struct|interface)$|"
                      r"^(?:struct|interface)$")
_RUST_TESTS = re.compile(r"#\[\s*cfg\s*\(\s*test\s*\)\s*\]")
# Languages that declare every function with a word of their own, so a call followed by a block
# (Kotlin's trailing lambda, Go's composite literal) is never taken for one.
_FUNCTION_WORDS = {
    "go": re.compile(r"(?<![\w$])func\s*(?:\(\)\s*)?([A-Za-z_]\w*)\s*(?:\[[^\]]*\]\s*)?\(\)"),
    "rust": re.compile(r"(?<![\w$])fn\s+([A-Za-z_]\w*)"),
    "kotlin": re.compile(r"(?<![\w$])fun\s+(?:<[^>]*>\s*)?(?:[\w.?<>]+\.)?([A-Za-z_]\w*|`[^`]+`)"
                         r"\s*\(\)"),
    "swift": re.compile(r"(?<![\w$])func\s+([^\s(<]+)"),
    "scala": re.compile(r"(?<![\w$])def\s+([^\s(\[:=]+)"),
    "php": re.compile(r"(?<![\w$])function\s*&?\s*([A-Za-z_]\w*)\s*\(\)"),
    "solidity": re.compile(r"(?<![\w$])(?:function|modifier)\s+([A-Za-z_]\w*)"),
    "groovy": re.compile(r"(?<![\w$])def\s+([A-Za-z_]\w*)\s*\(\)"),
}
_KEYWORD_ONLY = frozenset({"go", "rust", "kotlin", "swift", "scala", "php", "solidity"})
# Code that runs and is declared by a name of its own: initializers, constructors, receivers.
_SPECIAL = {
    "java": re.compile(r"^(static)$"),
    "kotlin": re.compile(r"^(init)$|(?<![\w$])(constructor)\s*\(\)"),
    "swift": re.compile(r"(?<![\w$.])(init|deinit|subscript)(?![\w$])"),
    "solidity": re.compile(r"(?<![\w$])(constructor|receive|fallback)\s*\(\)"),
    # Dart's named and factory constructors: `factory Order.fromJson(...)`, `Order.empty()`.
    "dart": re.compile(r"^(?:(?:const|factory|external)\s+)*[A-Za-z_]\w*\.([A-Za-z_]\w*)\s*\(\)"),
}
_OTHER_ACCESSORS = {
    "kotlin": re.compile(r"^(?:(?:private|protected|internal|public|override|inline)\s+)*"
                         r"(get|set)\s*\(\)$"),
    "swift": re.compile(r"^(?:(?:private|fileprivate|internal|public|mutating|nonmutating)\s+)*"
                        r"(get|set|willSet|didSet|_read|_modify)\s*(?:\(\))?$"),
}
_OTHER_PROPERTIES = {
    "swift": re.compile(r"(?<![\w$])var\s+([A-Za-z_]\w*)\s*:\s*[^=]+$"),
    "dart": re.compile(r"(?<![\w$])get\s+([A-Za-z_$][\w$]*)$"),
}
_LAMBDAS = {
    "go": re.compile(r"(?<![\w$])func\s*\(\)"),
    "php": re.compile(r"(?<![\w$])function\s*&?\s*\(\)"),
    "rust": re.compile(r"\|[^|]*\|\s*(?:->\s*[^{|]+)?$|\|\|\s*$"),
    "cpp": re.compile(r"\[[^\]]*\]\s*(?:\(\))?\s*(?:mutable|constexpr|noexcept)?\s*"
                      r"(?:->\s*[\w:<>,*&\s]+)?$"),
}
# What follows a parameter list without ending the head of a method: `throws`, `const`, `async`.
_TRAILERS = {
    "java": re.compile(r"\s+throws\s+[\w.<>,\s?]+$"),
    "groovy": re.compile(r"\s+throws\s+[\w.<>,\s?]+$"),
    "c": re.compile(r"(?:\s+(?:const|volatile))+$"),
    "cpp": re.compile(r"(?:\s+(?:const|noexcept|override|final|volatile|mutable)|\s*&&?|"
                      r"\s*noexcept\(\)|\s*->\s*[\w:<>,*&\s]+)+$"),
    "dart": re.compile(r"\s+(?:async\*?|sync\*)$"),
}
_ASSIGNED_TO = re.compile(r"(\$?[A-Za-z_][\w$]*)\s*(?::=|=)\s*(?:static\s+)?(?:async\s+)?"
                          r"(?:move\s+)?(?:func|function|fn|\||\[)")


def _classify_other(head: str, lang: str) -> tuple[str, str]:
    """`(kind, name)` for a block of Java, Kotlin, Scala, Groovy, Go, Rust, Swift, Dart, C, C++,
    PHP or Solidity."""
    if lang == "rust" and _RUST_TESTS.search(head):
        return "tests", ""
    bare = _ANNOTATIONS.sub("", _flatten(head)).strip()
    if lang in _TRAILERS:
        bare = _TRAILERS[lang].sub("", bare).strip()
    if not bare:
        return "other", ""
    control = _OTHER_CONTROL.get(lang)
    if control is not None and control.match(bare):
        return "control", ""
    # A function's own word before anything its tail could look like: Swift's `func f() async {`
    # ends in a word that also opens a block, and Scala's `def f(): Int = {` in an `=`.
    words = _FUNCTION_WORDS.get(lang)
    if words is not None and (m := words.search(bare)):
        return "function", m.group(1)
    special = _SPECIAL.get(lang)
    if special is not None and (m := special.search(bare)):
        return "function", next(g for g in m.groups() if g)
    if _CONTROL_AT_END.search(bare):            # `val x = when (y) {`, `$z = match($y) {`
        return "control", ""
    if lang == "go" and (m := _GO_TYPE.match(bare)):
        return "shape", m.group(1) or ""
    if lang in ("c", "cpp") and (m := _CALLABLE.search(bare)) and m.group(1) not in _NOT_A_NAME \
            and not m.group(1).startswith("[") \
            and not bare[:m.start()].rstrip().endswith((".", "new")):
        # A C function may return a struct (`struct point make(int x)`): a parameter list
        # makes it a function before its first word can make it a type.
        return "function", m.group(1)
    lam = _LAMBDAS.get(lang)
    if bare.endswith(("->", "=>")) or (lam is not None and lam.search(bare)):
        m = _ASSIGNED_TO.search(bare) or _OPEN_CALL.search(bare)
        return "lambda", (m.group(1) if m else "lambda")
    if re.search(r"(?:^|[=(,:?\[&|]|\breturn|\bnew\b[\w.<>\[\]\s]*?(?:\(\))?)\s*$", bare):
        return "object", ""                     # `struct point p = {`, `int[] a = {`
    types = _TYPES.get(lang)
    if types is not None and (m := types.search(bare.split("(")[0])):
        return ("shape" if m.group(1) in _SHAPE_WORDS else "type"), (m.group(2) or "")
    accessor = _OTHER_ACCESSORS.get(lang)
    if accessor is not None and (m := accessor.match(bare)):
        return "accessor", m.group(1)
    prop = _OTHER_PROPERTIES.get(lang)
    if prop is not None and (m := prop.search(bare)):
        return "property", m.group(1)
    if lang not in _KEYWORD_ONLY and (m := _CALLABLE.search(bare)):
        name = m.group(1)
        before = bare[:m.start()].rstrip()
        if name in _NOT_A_NAME or before.endswith("new") or before.endswith("."):
            return "other", ""
        return "function", name
    return "other", ""


# Where the head of a block starts, in a language whose statements need no `;`: a line ends the
# statement before it unless the next one carries it on, or it is an annotation or a comment that
# belongs to what follows.
_CONTINUES_AFTER = re.compile(r"(?:[,(\[=:?&|+\-*/%<>!.]|->|=>|\b(?:extends|implements|where|"
                              r"throws|with|and|or))\s*$")
# Not `const`, `async` or `override`: they open as many declarations as they continue.
_CONTINUES_BEFORE = re.compile(r"^\s*(?:[.:?&|=)\]{]|->|=>|where\b|throws\b|rethrows\b|extends\b|"
                               r"implements\b|with\b|else\b|catch\b|finally\b)")
_ANNOTATION_LINE = re.compile(r"^\s*(?:@|\[|#!?\[)")
# A label ends in `:` and continues nothing: C++'s `public:`, a `case 1:`, a `default:`.
_LABEL_LINE = re.compile(r"^\s*(?:public|private|protected|internal|signals|slots|default|"
                         r"case\b[^:]*)\s*:\s*$")


def _head_start(masked: str, open_: int, text: str | None = None) -> int:
    """Where the head of the block opening at `open_` starts: just past the nearest `;`, `{` or `}`
    that is not inside a parenthesized or bracketed group. A destructured parameter
    (`function Card({ title }: Props) {`), an object passed as an argument or a `for (;;)` is part
    of the head, not the end of the statement before it.

    Given the text as written, a line break ends it too where the line above is a complete
    statement: Go, Kotlin, Swift and a TypeScript file written without semicolons end their
    statements there, and a head that ran on to the last `;` gave a function the lines above it."""
    depth = 0                                   # groups closed after this point, read backwards
    seen = False                                # code between here and the brace
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
        elif ch == "\n" and depth == 0 and seen and text is not None and _ends_statement(
                masked, text, j):
            return j + 1
        if not ch.isspace():
            seen = True
        j -= 1
    return 0


def _ends_statement(masked: str, text: str, j: int) -> bool:
    """Whether the line break at `j` ends the statement on the line above it."""
    after_end = masked.find("\n", j + 1)
    after = masked[j + 1:len(masked) if after_end < 0 else after_end]
    if _CONTINUES_BEFORE.match(after):          # `-> Int {`, `.then(…`, `: Base() {`
        return False
    above = masked.rfind("\n", 0, j)
    line, written = masked[above + 1:j], text[above + 1:j]
    if not written.strip() or _LABEL_LINE.match(line):  # an empty line, `public:`: a new start
        return True
    if not line.strip() or _ANNOTATION_LINE.match(line) or _CONTINUES_AFTER.search(line):
        return False                            # a comment, `@Override`, `[HttpGet]`, `a &&`
    closes = sum(line.count(c) for c in ")]}") - sum(line.count(c) for c in "([{")
    if closes < 0:                              # `{`, `foo(`: a group left open goes on below
        return False
    if closes > 0:
        # `})` closes a group opened above. It is still the head when that group is an
        # annotation's (`@Component({…})` over a class); a call's (`listOf(…)`) ended there.
        return not _ANNOTATION_LINE.match(_line_opening(masked, j))
    return True


def _line_opening(masked: str, j: int) -> str:
    """The line holding the bracket that the unmatched closer before `j` closes."""
    depth = 0
    for k in range(j - 1, -1, -1):
        ch = masked[k]
        if ch in ")]}":
            depth += 1
        elif ch in "([{":
            depth -= 1
            if depth == 0:
                end = masked.find("\n", k)
                return masked[masked.rfind("\n", 0, k) + 1:len(masked) if end < 0 else end]
    return ""


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
        self._said = None
        self.starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
        self.lines = text.splitlines()
        self.blocks = self._blocks()

    @property
    def said(self) -> str:
        """The text with comments blank and literals kept: what each line says."""
        if self._said is None:
            self._said = mask(self.text, self.lang, keep_literals=True)
        return self._said

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
            begin = _head_start(self.masked, open_, self.text)
            head = self.masked[begin:open_]
            head_at = begin + (len(head) - len(head.lstrip()))
            # The head starts at its first character in the file as written, so the doc comment
            # and the attributes above a member come with it.
            raw_begin = begin
            if self.lang == "php":
                # The HTML before a PHP tag is not the function's doc comment.
                tags = list(_PHP_TAG.finditer(self.text, begin, open_))
                raw_begin = tags[-1].end() if tags else begin
            raw = self.text[raw_begin:open_]
            raw_at = raw_begin + (len(raw) - len(raw.lstrip()))
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
        # A shape that holds a function body holds code: a default interface method, a method on
        # a Swift enum or a C++ struct. It is a type, and the body is a question.
        for b in blocks:
            if b.kind in FUNCTION_KINDS:
                p = b.parent
                while p is not None:
                    if blocks[p].kind == "shape" and not _AUTO_PROPERTY.match(
                            self.masked[blocks[p].open + 1:blocks[p].close]):
                        blocks[p].kind = "type"
                    p = blocks[p].parent
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
                if ln.strip() and not ln.strip().startswith(("//", "/*", "*", "#!", "<?php"))]
        line = " ".join(" ".join(kept).split())
        return line[:300] if line else None

    def source(self, start: int, end: int) -> str:
        return "\n".join(self.lines[start - 1:end])


# ── 3. the questions a file holds ─────────────────────────────────────────────

def _outermost_functions(src: Source) -> list:
    def inside_function(b):
        p = b.parent
        while p is not None:
            if src.blocks[p].kind in FUNCTION_KINDS or src.blocks[p].kind == "tests":
                return True
            p = src.blocks[p].parent
        return False
    return [b for b in src.blocks if b.kind in FUNCTION_KINDS and not inside_function(b)]


def functions(text: str, lang: str, max_lines: int) -> list:
    """Every outermost function of a file → `[(name, start, end, source, context)]`. One too long
    for a question is read as the functions inside it: a React component's handlers, a Go
    function's closures. Cut at its first `max_lines` lines instead, the 2026-11-11 run on a
    Next.js site was shown a submit handler without its `finally` and reported the loading flag
    it resets as never reset. A long function with none inside it is still cut, as Python's is."""
    src = Source(text, lang)
    index = {id(b): i for i, b in enumerate(src.blocks)}
    inner: dict = {}
    for b in src.blocks:
        if b.kind not in FUNCTION_KINDS:
            continue
        p = b.parent
        while p is not None and src.blocks[p].kind not in FUNCTION_KINDS:
            p = src.blocks[p].parent
        if p is not None:
            inner.setdefault(p, []).append(b)
    out = []

    def emit(b):
        start, end = src.span(b)
        nested = inner.get(index[id(b)], [])
        if end - start > max_lines and nested:
            for child in nested:
                emit(child)
            return
        end = min(end, start + max_lines)
        out.append((b.name or f"line {start}", start, end, src.source(start, end), src.context(b.open)))

    for b in _outermost_functions(src):
        emit(b)
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
    heads += [(src.line_of(b.head_at), src.line_of(b.close)) for b in src.blocks
              if b.kind in QUIET_KINDS]
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
    """Something on the line once comments are blanked — not only braces and separators. A line
    that is only a string says something: a CSP directive in a list, a URL, a query."""
    begin = src.starts[line - 1]
    end = src.starts[line] if line < len(src.starts) else len(src.masked)
    return bool(src.masked[begin:end].strip(" \t\r\n{}();,")) \
        or bool(src.said[begin:end].strip(" \t\r\n{}();,"))


_MEMBER_NAMES = (
    re.compile(r"(?:const|let|var|function\*?|class|type|interface|enum)\s+([A-Za-z_$][\w$]*)"),
    re.compile(r"([A-Za-z_$][\w$]*)\s*" + _GENERIC + r"\s*(?:\(\)\s*)?=>"),
    re.compile(r"([A-Za-z_$][\w$]*)\s*(?:=(?!=)|;|$)"),
)
_OTHER_MEMBER_NAMES = (
    re.compile(r"(?:const|let|var|val|static|final|fn|func|fun|def|type|class|struct|enum|"
               r"interface|trait|object)\s+(?:mut\s+)?(\$?[A-Za-z_][\w$]*)"),
    _MEMBER_NAMES[1],
    re.compile(r"(\$?[A-Za-z_][\w$]*)\s*(?::=|=(?!=)|;|$)"),
)
# Statements that ask nothing: imports, `using` directives, a file-scoped namespace, a directive
# string. They are read as masked and flattened text, so their string parts are already blank.
_NOTHING_TO_ASK = re.compile(r"^(?:global\s+)?using\s+(?:static\s+)?[\w.]+(?:\s*=\s*[\w.<>,\s]+)?;?$|"
                             r"^namespace\s+[\w.]+\s*;?$|^import\b|^export\s+(?:type\s+)?(?:\*|\{[^}]*\})"
                             r"(?:\s+as\s+[\w$]+)?\s+from\b|^;?$")
# The same for the other brace languages: Java's `package`, Go's `import (…)`, Rust's `use` and
# `mod x;`, PHP's `use` and `require_once`, Dart's `part of`, Solidity's `pragma`.
_OTHER_NOTHING_TO_ASK = re.compile(
    r"^(?:import|package|use|using|namespace|mod\s+[\w$]+\s*;|extern\s+crate|library|part(?:\s+of)?|"
    r"export\s|pragma|require(?:_once)?|include(?:_once)?|declare\s*\(\)|@file:)(?![\w$])|^;?$")


_BARE_NEW = re.compile(r"\bnew\b\s*[\w.<>\[\],?\s]*\(\)")


def _statement(src: Source, line: int, max_lines: int) -> tuple | None:
    """`(start, end, name)` of the statement holding `line`, at most `max_lines` long, or None
    when it is one that asks nothing. A `{` at its own depth ends it unless that block is an object
    or an initializer: a statement never runs on into a type, a function or a control block."""
    offset = src.starts[line - 1]
    masked, n = src.masked, len(src.masked)
    cut = max(masked.rfind(d, 0, offset) for d in ";{}")
    # A `{` or `}` of an object literal is inside the statement, not its edge: a line in the third
    # object of a `const headers = [{…}, {…}, {…}]` belongs to the whole declaration.
    opened = {b.open: b for b in src.blocks}
    closed = {b.close: b for b in src.blocks}
    while cut >= 0 and masked[cut] in "{}":
        b = opened.get(cut) if masked[cut] == "{" else closed.get(cut)
        if b is None or b.kind not in ("object", "other"):
            break
        cut = max(masked.rfind(d, 0, b.head_at) for d in ";{}")
    begin = cut + 1
    # A line break that ends a statement ends it as a `;` would: Kotlin, Go, Swift and a
    # TypeScript file written without semicolons have nothing else.
    k = line
    while k > 1 and src.starts[k - 1] - 1 > cut:
        if _ends_statement(masked, src.text, src.starts[k - 1] - 1):
            begin = max(begin, src.starts[k - 1])
            break
        k -= 1
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
        elif ch == "\n" and depth == 0 and j >= offset and _ends_statement(masked, src.text, j):
            j -= 1
            break
        j += 1
    head = _flatten(masked[begin:min(j + 1, n)])
    other = src.lang not in _C_SHARP_AND_JS
    if (_OTHER_NOTHING_TO_ASK if other else _NOTHING_TO_ASK).match(head):
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
    patterns = _OTHER_MEMBER_NAMES if other else (
        _MEMBER_NAMES[1:] if src.lang == "csharp" else _MEMBER_NAMES)
    for pattern in patterns:
        m = pattern.search(head)
        if m and m.group(1) not in _NOT_A_NAME:
            name = m.group(1)
            break
    return start, end, name or f"line {line}"
