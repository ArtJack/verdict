"""Every language `verdict-local` reads, and the reader each one needs.

The local engine asks a bounded question about a bounded piece of code: one function, with the
file's own line numbers. Python has `ast` for that, and the standard library has nothing for any
other language, so for a long time the engine read Python only. On a website that is most of the
code, and none of the code that runs in the browser:

- On 2026-11-06, 38 of a .NET and React project's 73 local runs since 2026-10-13 had read no code at
  all. The three bugs a paid run found that day were all in C#.
- On 2026-11-11 a local run on a Next.js site read 0 files and asked its model nothing.

A language here names its family, and the family names the reader:

- `python`: `ast`, in small.py, as before.
- `braces`: `braces.py` reads C#, TypeScript, JavaScript, Java, Kotlin, Scala, Groovy, Go, Rust,
  Swift, Dart, C, C++, PHP and Solidity. Their blocks are braces, so one brace-pairing reader with
  each language's own literals and declarations covers them all.
- `ends`: `ends.py` reads Ruby, Elixir and Lua, whose blocks close on `end`.
- `regions`: `regions.py` reads files that hold code inside markup: Vue, Svelte and Astro
  components, HTML pages and Razor views. Their code goes to its own language's reader, and a
  component's template is read as a template.
- `lines`: `regions.py` reads every other programming language and every template language as
  excerpts: the changed lines with the lines around them. It knows no function boundaries, and
  the question says so.

What this table does not name is not program source: configuration, data, styles, documentation,
lock files and images. A range that changed only those had no code to read, and the report says so.

No parser is imported. The harness runs on whatever `python3` the machine has, with the standard
library only, and the readers are pinned by tests to the shapes that matter instead.
"""

from __future__ import annotations

import re
from typing import NamedTuple


class Language(NamedTuple):
    key: str
    name: str        # as a question says it: "one Go function"
    fence: str       # the Markdown fence the question's excerpt uses
    family: str      # python, braces, ends, regions or lines
    comment: str     # the line comment, which a line holding nothing else asks nothing about


# key, name, fence, family, line comment, suffixes. A suffix is matched on the file name in lower
# case, the longest first: `.blade.php` is a template before `.php` is PHP.
_TABLE = (
    ("python", "Python", "python", "python", "#", (".py", ".pyw")),
    # ── braces ──
    ("csharp", "C#", "csharp", "braces", "//", (".cs", ".csx")),
    ("typescript", "TypeScript", "ts", "braces", "//", (".ts", ".tsx", ".mts", ".cts")),
    ("javascript", "JavaScript", "js", "braces", "//", (".js", ".jsx", ".mjs", ".cjs")),
    ("java", "Java", "java", "braces", "//", (".java",)),
    ("kotlin", "Kotlin", "kotlin", "braces", "//", (".kt", ".kts")),
    ("scala", "Scala", "scala", "braces", "//", (".scala", ".sc")),
    ("groovy", "Groovy", "groovy", "braces", "//", (".groovy",)),
    ("go", "Go", "go", "braces", "//", (".go",)),
    ("rust", "Rust", "rust", "braces", "//", (".rs",)),
    ("swift", "Swift", "swift", "braces", "//", (".swift",)),
    ("dart", "Dart", "dart", "braces", "//", (".dart",)),
    ("c", "C", "c", "braces", "//", (".c", ".h")),
    ("cpp", "C++", "cpp", "braces", "//", (".cc", ".cpp", ".cxx", ".c++", ".hh", ".hpp", ".hxx",
                                             ".h++", ".ipp", ".tpp", ".inl")),
    ("php", "PHP", "php", "braces", "//", (".php", ".phtml", ".php3", ".php4", ".php5", ".php7",
                                             ".php8", ".inc")),
    ("solidity", "Solidity", "solidity", "braces", "//", (".sol",)),
    # ── ends ──
    ("ruby", "Ruby", "ruby", "ends", "#", (".rb", ".rake", ".ru", ".jbuilder")),
    ("elixir", "Elixir", "elixir", "ends", "#", (".ex", ".exs")),
    ("lua", "Lua", "lua", "ends", "--", (".lua",)),
    # ── regions: code inside markup ──
    ("vue", "Vue", "vue", "regions", "", (".vue",)),
    ("svelte", "Svelte", "svelte", "regions", "", (".svelte",)),
    ("astro", "Astro", "astro", "regions", "", (".astro",)),
    ("html", "HTML", "html", "regions", "", (".html", ".htm", ".xhtml", ".shtml")),
    ("razor", "Razor", "cshtml", "regions", "", (".cshtml", ".razor")),
    # ── lines: templates ──
    ("blade", "Blade template", "blade", "lines", "", (".blade.php",)),
    ("erb", "ERB template", "erb", "lines", "", (".erb",)),
    ("ejs", "EJS template", "ejs", "lines", "", (".ejs",)),
    ("twig", "Twig template", "twig", "lines", "", (".twig",)),
    ("jinja", "Jinja template", "jinja", "lines", "", (".jinja", ".jinja2", ".j2", ".njk")),
    ("liquid", "Liquid template", "liquid", "lines", "", (".liquid",)),
    ("handlebars", "Handlebars template", "handlebars", "lines", "", (".hbs", ".handlebars",
                                                                       ".mustache")),
    ("pug", "Pug template", "pug", "lines", "//", (".pug", ".jade")),
    ("haml", "Haml template", "haml", "lines", "-#", (".haml",)),
    ("slim", "Slim template", "slim", "lines", "/", (".slim",)),
    ("gotemplate", "Go template", "gotemplate", "lines", "", (".tmpl", ".gohtml", ".gotmpl")),
    # ── lines: every other programming language ──
    ("shell", "shell", "sh", "lines", "#", (".sh", ".bash", ".zsh", ".ksh")),
    ("powershell", "PowerShell", "powershell", "lines", "#", (".ps1", ".psm1")),
    ("batch", "batch", "bat", "lines", "::", (".bat", ".cmd")),
    ("sql", "SQL", "sql", "lines", "--", (".sql",)),
    ("perl", "Perl", "perl", "lines", "#", (".pl", ".pm")),
    ("r", "R", "r", "lines", "#", (".r",)),
    ("haskell", "Haskell", "haskell", "lines", "--", (".hs",)),
    ("clojure", "Clojure", "clojure", "lines", ";", (".clj", ".cljs", ".cljc")),
    ("erlang", "Erlang", "erlang", "lines", "%", (".erl", ".hrl")),
    ("fsharp", "F#", "fsharp", "lines", "//", (".fs", ".fsx")),
    ("ocaml", "OCaml", "ocaml", "lines", "", (".ml",)),
    ("elm", "Elm", "elm", "lines", "--", (".elm",)),
    ("julia", "Julia", "julia", "lines", "#", (".jl",)),
    ("crystal", "Crystal", "crystal", "lines", "#", (".cr",)),
    ("nim", "Nim", "nim", "lines", "#", (".nim",)),
    ("zig", "Zig", "zig", "lines", "//", (".zig",)),
    ("objectivec", "Objective-C", "objectivec", "lines", "//", (".m", ".mm")),
    ("vb", "Visual Basic", "vbnet", "lines", "'", (".vb",)),
    ("coffeescript", "CoffeeScript", "coffeescript", "lines", "#", (".coffee",)),
)

LANGUAGES = {key: Language(key, name, fence, family, comment)
             for key, name, fence, family, comment, _suffixes in _TABLE}
_SUFFIXES = {suffix: key for key, *_rest, suffixes in _TABLE for suffix in suffixes}
# Files with no suffix that are code by name.
_NAMED = {"rakefile": "ruby", "guardfile": "ruby", "capfile": "ruby"}

FAMILIES = ("python", "braces", "ends", "regions", "lines")


def language_of(path) -> str | None:
    """The key of the language a file is written in, or None for a file that is not program
    source: configuration, data, styles, documentation, an image."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name in _NAMED:
        return _NAMED[name]
    parts = name.split(".")
    if len(parts) >= 3 and "." + ".".join(parts[-2:]) in _SUFFIXES:
        return _SUFFIXES["." + ".".join(parts[-2:])]
    if len(parts) >= 2 and parts[0] and "." + parts[-1] in _SUFFIXES:
        return _SUFFIXES["." + parts[-1]]
    return None


def name_of(key: str) -> str:
    return LANGUAGES[key].name if key in LANGUAGES else key


def fence_of(key: str) -> str:
    return LANGUAGES[key].fence if key in LANGUAGES else ""


def family_of(key) -> str | None:
    return LANGUAGES[key].family if key in LANGUAGES else None


def comment_of(key: str) -> str:
    return LANGUAGES[key].comment if key in LANGUAGES else ""


def is_template(key) -> bool:
    """A template language: its files are markup with code in its tags (Blade, ERB, Jinja ...)."""
    return key in LANGUAGES and LANGUAGES[key].name.endswith(" template")


# ── what is not worth a question ─────────────────────────────────────────────

# Tests, by the folder or the name every ecosystem gives them: `tests/`, `spec/`, `__tests__/`,
# `src/test/` (Maven and Gradle), `testdata/` (Go), `*.test.ts`, `*_test.go`, `*_spec.rb`,
# `*.cy.ts` (Cypress), `*.stories.tsx` (Storybook), and `Api.Tests/` (.NET).
_TEST_DIRS = re.compile(r"(?:^|/)(?:tests?|testing|__tests__|__mocks__|e2e|specs?|cypress|playwright|"
                        r"testdata|fixtures?|benches|benchmarks?)/|(?:^|/)[^/]*\.tests?/")
_TEST_NAMES = re.compile(r"(?:^|/)[^/]*[._-](?:tests?|specs?|e2e|cy|stories|story|bench)\.[a-z0-9]+$|"
                         r"(?:^|/)test_[^/]*\.py$|(?:^|/)conftest\.py$")
# `OrderTest.java`, `OrdersTests.cs`, `CartSpec.groovy`, `CheckoutIT.java`: tests by their class's
# name, case and all. In lower case `Latest.cs` would read as one.
_TEST_CLASSES = re.compile(r"(?:^|/)[^/]*[a-z0-9](?:Tests?|Spec|IT|TestCase)\.[A-Za-z]+$")


def is_test_path(path) -> bool:
    """A test, a fixture or a story, by its folder or its name, in any language."""
    text = str(path).replace("\\", "/")
    lower = text.lower()
    return bool(_TEST_DIRS.search(lower) or _TEST_NAMES.search(lower) or _TEST_CLASSES.search(text))


# Code nobody here wrote by hand, or wrote but does not own: a question about it is spent on what
# the project cannot fix.
_GENERATED = re.compile(
    r"(?:\.min\.[cm]?js|\.min\.css|\.bundle\.[cm]?js|\.chunk\.[cm]?js|\.d\.[cm]?ts|\.g\.cs|\.g\.i\.cs|"
    r"\.designer\.cs|\.generated\.[a-z]+|modelsnapshot\.cs|assemblyinfo\.cs|\.pb\.go|\.pb\.gw\.go|"
    r"_pb2(?:_grpc)?\.py|\.pb\.(?:cc|h)|_generated\.go|\.gen\.[a-z]+|\.freezed\.dart|\.g\.dart|"
    r"\.mocks\.dart|\.pyi|_mock\.go|(?:^|/)mocks?_[^/]*\.go|(?:^|/)zz_generated[^/]*|"
    r"(?:^|/)bindata\.go)$")
# Folders that hold installed, built or downloaded code, wherever they sit.
_VENDORED = frozenset({
    "node_modules", "bin", "obj", "dist", ".next", ".nuxt", "coverage", "vendor", ".git", ".venv",
    "venv", "migrations", ".svelte-kit", ".astro", ".output", ".vercel", ".netlify", ".turbo",
    ".parcel-cache", ".cache", "bower_components", "jspm_packages", "pods", "carthage",
    "deriveddata", ".dart_tool", ".pub-cache", "__generated__", ".gradle", "site-packages",
    "wp-admin", "wp-includes", "__pycache__", ".tox", "storybook-static", ".angular", ".expo"})
# Folders that hold built code outside a source tree and may be a module's own name inside one:
# `build/` beside `src/` is output, `src/build/` is somebody's code.
_VENDORED_OUTSIDE_SRC = frozenset({"build", "out", "target", "deps", "_build", "generated", "gen",
                                   "third_party", "third-party", "external"})
# A site's static folders hold copied libraries; its own `public/js/app.js` is still read.
_STATIC_LIBRARIES = re.compile(r"(?:^|/)(?:wwwroot|public|static|assets)/(?:lib|libs|plugins)/")


def is_generated(path) -> bool:
    """Generated, minified, vendored or built: not code anyone here would fix."""
    lower = str(path).replace("\\", "/").lower()
    parts = lower.split("/")[:-1]
    if _GENERATED.search(lower) or _STATIC_LIBRARIES.search(lower):
        return True
    if any(p in _VENDORED for p in parts):
        return True
    outside = parts[:parts.index("src")] if "src" in parts else parts
    return any(p in _VENDORED_OUTSIDE_SRC for p in outside)


_GENERATED_HEADER = re.compile(
    r"code generated .{0,80}do not edit|@generated\b|<auto-generated|"
    r"this file (?:is|was|has been) (?:auto(?:matically)?[- ]?)?generated|"
    r"automatically generated by|autogenerated by|do not edit this file", re.I)


def looks_generated(text: str) -> bool:
    """A file that says it was generated, that no one could have typed (a bundle with lines
    thousands of characters long), or that is not text at all: `.ts` is also a video stream.
    Read by content, for what a name does not give away."""
    if "\x00" in text[:8192] or _GENERATED_HEADER.search(text[:1500]):
        return True
    if len(text) < 2048:
        return False
    lines = text.split("\n")
    return max(len(line) for line in lines) > 3000 or len(text) / max(len(lines), 1) > 250


def readable(path) -> bool:
    """A file in a language other than Python that this engine asks questions about: source, not a
    test, not generated or vendored. Python keeps its own rules in small.py, where a test file is
    still read after every source file."""
    lang = language_of(path)
    return lang is not None and lang != "python" and not is_generated(path) \
        and not is_test_path(path)


def source(path) -> bool:
    """Program source in any language, Python included, that is neither generated nor vendored."""
    return language_of(path) is not None and not is_generated(path)


# What a range changed that no reader reads, by kind, for the sentence that says so.
_UNREAD_KINDS = (
    ("stylesheet", (".css", ".scss", ".sass", ".less", ".styl", ".pcss", ".postcss")),
    ("configuration or data file", (".json", ".jsonc", ".json5", ".yaml", ".yml", ".toml", ".xml",
                                    ".ini", ".cfg", ".conf", ".properties", ".env", ".lock",
                                    ".csv", ".tsv", ".plist", ".tf", ".tfvars", ".hcl", ".prisma",
                                    ".graphql", ".gql", ".proto", ".sops", ".example")),
    ("document", (".md", ".mdx", ".rst", ".txt", ".adoc", ".pdf")),
    ("image or font", (".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".svg", ".ico", ".woff",
                       ".woff2", ".ttf", ".otf", ".eot", ".mp4", ".webm", ".mp3")),
)


def unread_kind(path) -> str:
    """What a file no reader reads is: a stylesheet, configuration or data, a document, an image
    or a font, or `other file`."""
    name = str(path).replace("\\", "/").rsplit("/", 1)[-1].lower()
    for kind, suffixes in _UNREAD_KINDS:
        if name.endswith(suffixes) or (kind.startswith("configuration") and name.startswith(".env")):
            return kind
    return "other file"


def unread_summary(paths) -> str:
    """`2 stylesheet(s), 1 document(s)`: the changed files that are not program source, counted by
    kind, or "" when there are none."""
    counts: dict = {}
    for p in paths:
        if language_of(p) is None:
            kind = unread_kind(p)
            counts[kind] = counts.get(kind, 0) + 1
    order = [k for k, _ in _UNREAD_KINDS] + ["other file"]
    return ", ".join(f"{counts[k]} {k}(s)" for k in order if k in counts)
