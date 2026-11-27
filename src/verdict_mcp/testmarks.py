"""Tests a suite will not run, in every test framework a website is tested with.

`verdict-local` files a skipped test with no expiry as a finding: a quarantine with no end is a test
somebody deleted without deciding to. It read pytest's markers only, so a Jest suite's `it.skip`, an
RSpec `xit` or a JUnit `@Disabled` stayed silent forever. Worse than a skip is a focus. A committed
`it.only`, `fdescribe` or `fit` runs one test and silently drops every other in its file, and under
Mocha in the whole run. The suite stays green while it checks almost nothing.

Each framework's markers are read here with a regular expression, and no model is involved:

- JavaScript and TypeScript (Jest, Vitest, Mocha, Jasmine, Playwright, Cypress, `node:test`):
  `it.skip`, `xit`, `test.fixme`, `{ skip: true }`, and the focus markers `.only`, `fit`,
  `fdescribe` and `{ only: true }`.
- Ruby (RSpec, Minitest): `xit`, `xdescribe`, `skip`, `skip: true`, and the focus markers `fit`,
  `fdescribe` and `focus: true`.
- Go: `t.Skip`. Java, Kotlin, Scala and Groovy: `@Disabled`, `@Ignore`. C#: `Skip =`,
  `[Ignore]`, `[Explicit]`. PHP: `markTestSkipped`, Pest's `->skip()`. Rust: `#[ignore]`. Swift:
  `throw XCTSkip`. Elixir: `@tag :skip`. Dart: `skip:`.

A skip under a condition is a guard, not a graveyard, as with pytest's `skipif`: `if
testing.Short() { t.Skip() }`, Playwright's `test.skip(browserName === 'webkit')`, Ruby's
`skip unless ENV["CI"]`. None of those is reported.
"""

from __future__ import annotations

import re

try:
    from . import languages
except ImportError:  # imported as a plain module beside small.py
    import languages

_TITLE = re.compile(r"""^\s*(['"`])(.*?)(?<!\\)\1""")
_JS_RUNNERS = r"(?:it|test|describe|context|suite|specify|scenario|feature)"

# (kind, pattern, how): `how` says what the marker's arguments mean.
#   "titled"  — the first argument is the test's title: a string is a named test switched off; a
#               `true` is unconditional; anything else is a condition, a guard.
#   "call"    — a call inside a test: unconditional unless a condition encloses it.
#   "mark"    — an annotation, an attribute or an option: always unconditional.
_MARKS = {
    "js": (
        ("skip", re.compile(r"(?<![\w.$])" + _JS_RUNNERS + r"\.(?:skip|fixme)\s*\((?P<args>.*)$"), "titled"),
        ("skip", re.compile(r"(?<![\w.$])x(?:it|test|describe|context|specify)\s*\((?P<args>\s*['\"`].*)$"),
         "titled"),
        ("skip", re.compile(r"(?<![\w.$])" + _JS_RUNNERS + r"\s*\((?P<args>\s*['\"`].*?)[,{]\s*skip\s*:\s*"
                            r"(?:true|['\"`])"), "mark"),
        ("focus", re.compile(r"(?<![\w.$])" + _JS_RUNNERS + r"\.only\s*\((?P<args>.*)$"), "titled"),
        ("focus", re.compile(r"(?<![\w.$])f(?:it|describe)\s*\((?P<args>\s*['\"`].*)$"), "titled"),
        ("focus", re.compile(r"(?<![\w.$])" + _JS_RUNNERS + r"\s*\((?P<args>\s*['\"`].*?)[,{]\s*only\s*:\s*true\b"),
         "mark"),
    ),
    "ruby": (
        ("skip", re.compile(r"^\s*x(?:it|describe|context|specify|feature|scenario|example)\b\s*\(?"
                            r"(?P<args>\s*['\"].*)$"), "titled"),
        ("skip", re.compile(r"^\s*(?:it|specify|example|scenario|describe|context)\b\s*\(?"
                            r"(?P<args>\s*['\"].*?),\s*skip:\s*(?:true|['\"])"), "mark"),
        ("skip", re.compile(r"^\s*skip\b\s*\(?(?P<args>\s*['\"].*)?$"), "call"),
        ("focus", re.compile(r"^\s*f(?:it|describe|context|specify)\b\s*\(?(?P<args>\s*['\"].*)$"), "titled"),
        ("focus", re.compile(r"^\s*(?:it|specify|example|scenario|describe|context)\b\s*\(?"
                             r"(?P<args>\s*['\"].*?),\s*(?:focus:\s*true|:focus)\b"), "mark"),
    ),
    "go": (
        ("skip", re.compile(r"\b(?:t|b|f|tb)\.Skip(?:f|Now)?\s*\((?P<args>.*)$"), "call"),
    ),
    "jvm": (
        ("skip", re.compile(r"^\s*@(?:Disabled|Ignore)\b(?:\s*\((?P<args>.*))?$"), "mark"),
        ("skip", re.compile(r"@Test\s*\(\s*enabled\s*=\s*false(?P<args>)"), "mark"),
    ),
    "csharp": (
        ("skip", re.compile(r"\[[^\]]*\b(?:Fact|Theory|Test|TestCase|TestMethod)\s*\([^\]]*\bSkip\s*=\s*"
                            r"(?P<args>[^\]]*)\]"), "mark"),
        ("skip", re.compile(r"\[\s*(?:[^\]]*,\s*)?Ignore\b(?:\s*\((?P<args>[^\]]*))?"), "mark"),
        ("skip", re.compile(r"\[\s*(?:[^\]]*,\s*)?Explicit\b(?P<args>)"), "mark"),
    ),
    "php": (
        ("skip", re.compile(r"\$this->mark(?:TestSkipped|TestIncomplete)\s*\((?P<args>.*)$"), "call"),
        ("skip", re.compile(r"\)\s*->\s*skip\s*\((?P<args>.*)$"), "call"),
    ),
    "rust": (
        ("skip", re.compile(r"^\s*#\[\s*ignore\b\s*(?:=\s*(?P<args>[^\]]*))?\]"), "mark"),
    ),
    "swift": (
        ("skip", re.compile(r"\bthrow\s+XCTSkip\s*\((?P<args>.*)$"), "call"),
    ),
    "elixir": (
        ("skip", re.compile(r"^\s*@(?:module)?tag\s+(?::skip\b|skip:\s*)(?P<args>.*)$"), "mark"),
    ),
    "dart": (
        ("skip", re.compile(r"(?<![\w.$])(?:test|testWidgets|group)\s*\((?P<args>\s*['\"].*?)[,(]\s*skip\s*:\s*"
                            r"(?:true|['\"])"), "mark"),
    ),
}
_GROUPS = {"typescript": "js", "javascript": "js", "vue": "js", "svelte": "js", "ruby": "ruby",
           "go": "go", "java": "jvm", "kotlin": "jvm", "scala": "jvm", "groovy": "jvm",
           "csharp": "csharp", "php": "php", "rust": "rust", "swift": "swift", "elixir": "elixir",
           "dart": "dart"}

# A line that opens a conditional block, in the languages above.
_OPENS_CONDITION = re.compile(r"^\s*(?:\}\s*)?(?:if|else|elsif|elif|unless|guard|switch|case|when|"
                              r"select|catch|rescue|for|foreach|while|until)\b")
# A condition on the marker's own line: `skip unless ENV["CI"]`, `if (x) $this->markTestSkipped()`.
_SAME_LINE_CONDITION = re.compile(r"\b(?:if|unless|guard|when)\b|\?|&&|\|\|")


def _indent(line: str) -> int:
    expanded = line.expandtabs(8)
    return len(expanded) - len(expanded.lstrip())


def _under_a_condition(lines: list, k: int) -> bool:
    """True when the statement on line `k` (0-based) sits inside a conditional block: the nearest
    line above it with less indentation opens one."""
    depth = _indent(lines[k])
    for prev in reversed(lines[:k]):
        if not prev.strip():
            continue
        if _indent(prev) < depth:
            return bool(_OPENS_CONDITION.match(prev))
    return False


def _reason(args: str | None) -> str:
    """The test's title or the skip's reason: the first string in the arguments, else them."""
    args = (args or "").strip()
    m = _TITLE.match(args)
    if m:
        return m.group(2).strip()[:200]
    return args.rstrip("{(,; ").strip()[:200]


def marks(text: str, lang: str) -> list:
    """`[{"line", "reason", "kind"}]` for every unconditional skip and every focus in a test file:
    `kind` is "skip" or "focus"."""
    table = _MARKS.get(_GROUPS.get(lang, ""), ())
    if not table:
        return []
    lines = text.split("\n")
    out, seen = [], set()
    for k, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith(("//", "#", "*", "/*", "--")) and not stripped.startswith(("#[", "#!")):
            continue                            # a comment that mentions `it.only` is no focus
        for kind, pattern, how in table:
            m = pattern.search(line)
            if not m or (k, kind) in seen:
                continue
            args = m.groupdict().get("args")
            if how == "titled":
                first = (args or "").strip()
                if not (_TITLE.match(first) or re.match(r"true\b", first)):
                    continue                    # `test.skip(isWebKit, ...)`: a condition, a guard
            if how == "call":
                # The reason's own words are text: `skip "why?"` has no condition, while
                # `skip "x" unless ENV["CI"]` and `if (...) markTestSkipped()` do.
                tail = (args or "").strip()
                title = _TITLE.match(tail)
                after = tail[title.end():] if title else tail
                if _SAME_LINE_CONDITION.search(line[:m.start()]) or _SAME_LINE_CONDITION.search(
                        after) or _under_a_condition(lines, k):
                    continue
            seen.add((k, kind))
            reason = _reason(args)
            if how == "titled" and re.match(r"true\b", (args or "").strip()):
                reason = _reason((args or "").strip()[4:].lstrip(", "))
            out.append({"line": k + 1, "reason": reason or "(no reason given)", "kind": kind})
    return out


def suite_language(path) -> str | None:
    """The language of a test file this module reads, or None."""
    lang = languages.language_of(path)
    return lang if lang in _GROUPS else None


# Test-shaped files that are not the project's tests: an eval's fixtures, a framework's examples.
_NOT_A_SUITE = re.compile(r"(?:^|/)(?:fixtures?|__fixtures__|testdata|examples?|samples?|"
                          r"eval|evals)/", re.I)


def is_suite_file(path) -> bool:
    """A test file in a language other than Python that belongs to the project's own suite."""
    p = str(path).replace("\\", "/")
    return suite_language(p) is not None and languages.is_test_path(p) \
        and not languages.is_generated(p) and not _NOT_A_SUITE.search(p)
