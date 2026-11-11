"""What a function reaches for one step outside itself, shown beside the question about it.

`verdict-local` asks about one function at a time, and a model shown one function judges its
callees, its module's state and the types it names as unseen. Its false readings came from there.
Measured 2026-11-11 on a Next.js site: of 11 readings filed from single functions, none was a real
defect. About half had their answer one step away:

- A missing token check: the callee checked it on its first line.
- A null file: a validation call above it returned first.
- A body typed `Response`: the file declared its own `Response` type.

So a question about a function in another language than Python now carries, below the function,
the code it reaches for:

- **The functions it calls** that this file defines, and in TypeScript and JavaScript the ones it
  imports from this repository (`./x`, `@/lib/x`).
- **The module state it touches**: a `const seenEvents = new Set()`, a rate limiter, a constant.
- **The shapes it names**: a `type`, an `interface`, an `enum` declared beside it.

A short definition is shown whole and a long one by its head, and all of it fits in a budget of
lines. It is shown as reference, not as code under review.

Python's question is unchanged: the evals measured its words.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

try:
    from . import braces, ends, languages
except ImportError:  # imported as a plain module beside small.py
    import braces
    import ends
    import languages

BUDGET = 80          # lines in all, below one function
WHOLE = 40           # a definition this long or shorter is shown whole: a callee's check sits
HEAD = 16            # past its first dozen lines; of a longer one, its first lines

_IDENT = re.compile(r"[A-Za-z_$][\w$]*")
_KEYWORDS = frozenset(
    "if else for while do switch case default return break continue new delete typeof instanceof "
    "void this super true false null undefined await async function class const let var import "
    "export from as try catch finally throw in of with yield static public private protected "
    "readonly interface type enum extends implements fn func fun def end val struct impl self "
    "Self nil None string number boolean any never unknown object int long float double bool "
    "char byte decimal Promise Array Record String Number Boolean Object Map Set Date Error JSON "
    "Math console window document process".split())
# A declaration outside every function: `const x =`, `val x =`, `static X:`, `let mut x`.
_DECLARED = re.compile(r"^\s*(?:export\s+)?(?:(?:public|private|protected|internal|static|readonly|"
                       r"final|override|lateinit|lazy|pub(?:\([^)]*\))?)\s+)*(?:const|let|var|val|"
                       r"static)\s+(?:mut\s+)?(\$?[A-Za-z_][\w$]*)")
# A typed field in a class: `private static readonly HttpClient Client = …;`, `private $repo;`.
_FIELD = re.compile(r"^\s*(?:(?:public|private|protected|internal|static|readonly|final|const|"
                    r"volatile|transient|required)\s+)+[\w<>\[\],.?]+\s+(\$?[A-Za-z_][\w$]*)\s*(?:=|;)")
_TYPE_ALIAS = re.compile(r"^\s*(?:export\s+)?(?:declare\s+)?type\s+([A-Za-z_$][\w$]*)\b[^=]*=")
_IMPORT = re.compile(r"""^\s*import\s+(?:type\s+)?(?P<what>[^;'"]*?)\s*from\s*['"](?P<spec>[^'"]+)['"]""",
                     re.M)


class Reached(NamedTuple):
    name: str
    path: str
    start: int
    end: int
    source: str
    kind: str        # function, state or shape
    hidden: int      # lines of the definition not shown


# ── what a file defines ──────────────────────────────────────────────────────

def definitions(text: str, lang: str) -> dict:
    """`{name: (start, end, kind)}` for what a file defines outside function bodies: its named
    functions and methods, its declared state and constants, and its shapes."""
    family = languages.family_of(lang)
    if family == "ends":
        return {d.name.split(".")[-1]: (d.start, d.end, "function")
                for d in ends.Source(text, lang).defs}
    if family != "braces":
        return {}
    src = braces.Source(text, lang)
    out: dict = {}
    inside_function = []
    for b in src.blocks:
        start, end = src.span(b)
        if b.kind in braces.FUNCTION_KINDS:
            inside_function.append((src.line_of(b.open), end))
            name = (b.name or "").rsplit(".", 1)[-1]
            if b.kind == "lambda" and not _assigned(b.head, name):
                continue                        # `useEffect(() => …)` defines no `useEffect`
            if name and not name.startswith(("line ", "lines ")) and name != "lambda" \
                    and _IDENT.fullmatch(name):
                out.setdefault(name, (start, end, "function"))
        elif b.kind == "shape" and b.name:
            out.setdefault(b.name.rsplit(".", 1)[-1], (start, end, "shape"))
    masked = src.masked.split("\n")
    for k, line in enumerate(masked, 1):
        if any(a < k <= e for a, e in inside_function):
            continue                            # a local of some function, not module state
        alias = _TYPE_ALIAS.match(line)
        m = alias or _DECLARED.match(line) or _FIELD.match(line)
        if m and m.group(1) not in out:
            out[m.group(1)] = (k, _declaration_end(src, k), "shape" if alias else "state")
    return out


def _assigned(head: str, name: str) -> bool:
    """Whether a lambda's head assigns it to `name` (`const handler = async () =>`), rather than
    passing it to a call that gave the block its name."""
    return bool(name) and re.search(r"(?<![\w$.])" + re.escape(name) + r"\s*(?::[^=]*)?:?=(?![=>])",
                                    " ".join(head.split())) is not None


def _declaration_end(src, k: int) -> int:
    """The last line of the declaration that starts on line `k`: its `;`, or the line where its
    brackets close and nothing carries it on."""
    masked, n = src.masked, len(src.masked)
    j = src.starts[k - 1]
    depth = 0
    while j < n:
        ch = masked[j]
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth < 0:
                break
        elif ch == ";" and depth == 0:
            break
        elif ch == "\n" and depth == 0 and braces._ends_statement(masked, src.text, j):
            j -= 1
            break
        j += 1
    return min(src.line_of(min(j, n - 1)), k + 40)


# ── what a function reaches for ──────────────────────────────────────────────

def names_used(text: str, lang: str, start: int, end: int) -> list:
    """The identifiers lines `start`..`end` use, in the order they first appear, strings and
    comments left out."""
    family = languages.family_of(lang)
    masked = (braces.mask(text, lang) if family == "braces" else
              ends.mask(text, lang) if family == "ends" else text).split("\n")
    seen, out = set(), []
    for line in masked[start - 1:end]:
        for m in _IDENT.finditer(line):
            word = m.group(0)
            if word not in seen and word not in _KEYWORDS:
                seen.add(word)
                out.append(word)
    return out


def _imports(text: str) -> dict:
    """`{local name: (module, exported name)}` for a JavaScript or TypeScript file's imports."""
    out: dict = {}
    for m in _IMPORT.finditer(text):
        what, spec = m.group("what"), m.group("spec")
        if what.startswith("*"):
            continue
        named = re.search(r"\{([^}]*)\}", what)
        default = what.split("{")[0].strip().rstrip(",").strip()
        if default and _IDENT.fullmatch(default):
            out[default] = (spec, "default")
        for part in (named.group(1).split(",") if named else []):
            part = re.sub(r"^\s*type\s+", "", part).strip()
            if not part:
                continue
            exported, _, local = part.partition(" as ")
            local = (local or exported).strip()
            if _IDENT.fullmatch(local) and _IDENT.fullmatch(exported.strip()):
                out[local] = (spec, exported.strip())
    return out


_EXTENSIONS = ("", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
               "/index.ts", "/index.tsx", "/index.js", "/index.jsx")


def resolve(repo: Path, rel: str, spec: str) -> str | None:
    """The repository file an import names, as a path relative to `repo`, or None for a package
    or for anything that would leave the repository."""
    root = Path(repo).resolve()
    if spec.startswith("."):
        bases = [(root / rel).parent / spec]
    elif spec.startswith(("@/", "~/")):
        bases = [root / "src" / spec[2:], root / spec[2:], root / "app" / spec[2:]]
    else:
        return None
    for base in bases:
        for suffix in _EXTENSIONS:
            candidate = Path(str(base) + suffix)
            try:
                found = candidate.resolve()
            except OSError:
                continue
            if found.is_file() and root in found.parents:
                return found.relative_to(root).as_posix()
    return None


def reached(repo: Path, rel: str, text: str, lang: str, start: int, end: int,
            budget: int = BUDGET) -> list:
    """What lines `start`..`end` of `rel` reach for one step outside themselves → `[Reached]`,
    in the order the function first uses each name, within `budget` lines in all."""
    if languages.family_of(lang) not in ("braces", "ends"):
        return []
    try:
        defs = definitions(text, lang)
    except Exception:       # noqa: BLE001 — context is a help; a file it cannot cut asks without
        return []
    lines = text.split("\n")
    imports = _imports(text) if lang in ("typescript", "javascript") else {}
    out, used = [], 0
    for name in names_used(text, lang, start, end):
        if used >= budget:
            break
        item = None
        if name in defs:
            a, b, kind = defs[name]
            if a <= end and b >= start:
                continue                        # the function itself, or what holds it
            item = _shown(name, rel, lines, a, b, kind, budget - used)
        elif name in imports:
            item = _imported(repo, rel, name, imports[name], budget - used)
        if item is not None:
            out.append(item)
            used += item.end - item.start + 1
    return out


def _shown(name, rel, lines, a, b, kind, room) -> Reached | None:
    total = b - a + 1
    keep = total if total <= WHOLE else HEAD
    keep = min(keep, room)
    if keep <= 0:
        return None
    return Reached(name, rel, a, a + keep - 1, "\n".join(lines[a - 1:a + keep - 1]), kind, total - keep)


def _imported(repo, rel, name, origin, room) -> Reached | None:
    spec, exported = origin
    target = resolve(repo, rel, spec)
    if target is None:
        return None
    lang = languages.language_of(target)
    if languages.family_of(lang) != "braces":
        return None
    try:
        text = (Path(repo) / target).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    if languages.looks_generated(text):
        return None
    defs = definitions(text, lang)
    wanted = exported if exported != "default" else _default_export(text) or name
    if wanted not in defs:
        return None
    a, b, kind = defs[wanted]
    return _shown(wanted, target, text.split("\n"), a, b, kind, room)


def _default_export(text: str) -> str | None:
    m = re.search(r"^\s*export\s+default\s+(?:async\s+)?(?:function\s*\*?\s*|class\s+)?([A-Za-z_$][\w$]*)",
                  text, re.M)
    return m.group(1) if m else None


def block(items: list, fence: str) -> str:
    """The reached code as the paragraph a question carries below its function, or ""."""
    if not items:
        return ""
    parts = ["\nIt reaches for this code one step outside it. It is shown for reference, not under "
             "review, and a check made here is made:"]
    for item in items:
        more = f" (and {item.hidden} more lines)" if item.hidden else ""
        numbered = "\n".join(f"{item.start + i:4d}| {line}"
                             for i, line in enumerate(item.source.split("\n")))
        parts.append(f"{item.path}, `{item.name}`{more}:\n```{fence}\n{numbered}\n```")
    return "\n".join(parts)
