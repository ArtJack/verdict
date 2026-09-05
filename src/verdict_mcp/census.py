#!/usr/bin/env python3
"""Deterministic censuses over the code under review. Stdlib only.

Verdict increasingly reviews code that a model wrote, and models fail in
characteristic ways — hallucinated dependencies, placeholders that never get
revisited, errors swallowed to make a demo work. Some of those signatures are
*mechanically countable*, and this project's standing rule applies: what can be
measured is never left to the model to notice.

Three censuses, attached to facts.json as `code_census`:

  imports       import roots that match no declared dependency, no stdlib
                module, and no local module — the hallucinated-dependency
                check, which is also a supply-chain check (slopsquatting
                registers packages under plausible hallucinated names).
  placeholders  TODO/FIXME/"for now"/stub markers, and silently swallowed
                exceptions (`except: pass`, empty `catch {}`).
  provenance    how much of the range under review is AI-attributed, from
                commit trailers — measured, not assumed.

A census is a **lead, not a finding**. Ten TODOs may all be legitimate; one
`except: pass` may be load-bearing. The counts and locations tell judgment
where to look; judgment decides what they mean. Every census also states its
own scope — "added lines in <range>" or "tree scan, capped" — because a census
that silently covered less than the reader assumed is worse than none.
"""

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
_SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".qa",
              "dist", "build", ".mypy_cache", ".ruff_cache", ".pytest_cache"}
_TREE_CAP = 300  # a baseline census is a sample, and says so, not a crawl

# Anchored at the start of the line with at most a little indentation, and the
# module root must be followed by end-of-line, a dot, a comma, or the words
# that finish a real import. Matched as loose text it read the prose of a
# docstring — "from a `releases/latest` URL" — and reported the English word
# "a" as an undeclared dependency, which was this range's only lead
# (VERDICT-F-79).
_PY_IMPORT = re.compile(
    r"^[ \t]{0,8}(?:from|import)[ \t]+([A-Za-z_][A-Za-z0-9_]*)"
    r"(?=[ \t]*(?:$|[.,;]|\bimport\b|\bas\b|#))")
_JS_IMPORT = re.compile(r"""(?:from\s+|require\(\s*)['"]([^'"./][^'"/]*)""")

# The famous import-name / package-name mismatches. Anything not listed is
# compared by normalized name, and the output carries the caveat — this map is
# why the census reports *candidates*, not convictions.
_ALIASES = {
    "yaml": "pyyaml", "PIL": "pillow", "cv2": "opencv_python",
    "bs4": "beautifulsoup4", "sklearn": "scikit_learn", "dotenv": "python_dotenv",
    "dateutil": "python_dateutil", "attr": "attrs", "git": "gitpython",
    "jose": "python_jose", "OpenSSL": "pyopenssl", "magic": "python_magic",
}

_PLACEHOLDER_PATTERNS = (
    ("todo", re.compile(r"\b(?:TODO|FIXME|XXX|HACK)\b")),
    ("for_now", re.compile(r"\bfor now\b|\btemporar(?:y|ily)\b|\bplaceholder\b|\bstub\b",
                           re.IGNORECASE)),
    # both the block form `catch (e) {}` and the arrow form `.catch(e => {})`
    ("swallowed_catch", re.compile(
        r"catch\s*(?:\([^)]*\))?\s*\{\s*\}"
        r"|\.catch\(\s*(?:\([^)]*\)|[A-Za-z_$][\w$]*)?\s*=>\s*\{\s*\}\s*\)")),
)
_EXCEPT_LINE = re.compile(r"^\s*except\b[^:]*:\s*(#.*)?$")
_PASS_LINE = re.compile(r"^\s*pass\b")

_AI_TRAILER = re.compile(
    r"Co-Authored-By:.*(claude|gpt|copilot|cursor|aider|codex|devin|gemini)"
    r"|Generated with.*(Claude|Copilot|Codex)"
    r"|\U0001F916",  # the robot emoji several tools stamp
    re.IGNORECASE)

_SAMPLE_CAP = 12  # locations shown per category; the count is always complete


def _git(args, repo):
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)
    return proc.stdout if proc.returncode == 0 else None


def _added_lines(repo, sha_range):
    """(path, new_lineno, text) for every line the range added."""
    diff = _git(["diff", "--unified=0", sha_range], repo)
    if diff is None:
        return None
    out, path, lineno = [], None, 0
    for raw in diff.splitlines():
        if raw.startswith("+++ b/"):
            path = raw[6:]
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            lineno = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            if path is not None:
                out.append((path, lineno, raw[1:]))
            lineno += 1
    return out


def _tree_lines(repo):
    """(path, lineno, text) over the tree, capped — with the cap reported."""
    files, capped = [], False
    for p in sorted(Path(repo).rglob("*")):
        if p.suffix not in _SOURCE_SUFFIXES or not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.relative_to(repo).parts):
            continue
        files.append(p)
        if len(files) >= _TREE_CAP:
            capped = True
            break
    out = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = p.relative_to(repo).as_posix()
        out.extend((rel, i, line) for i, line in enumerate(text.splitlines(), 1))
    return out, len(files), capped


def _normalize(name: str) -> str:
    return re.split(r"[<>=!~\[; ]", name.strip(), maxsplit=1)[0].lower().replace("-", "_")


def _declared_dependencies(repo: Path) -> set[str]:
    declared = set()
    pyproject = repo / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="replace")
        block = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.S)
        if block:
            declared.update(_normalize(m.group(1))
                            for m in re.finditer(r'"([^"]+)"', block.group(1)))
    for req in sorted(repo.glob("requirements*.txt")):
        for line in req.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-")):
                declared.add(_normalize(line))
    package = repo / "package.json"
    if package.is_file():
        import json
        try:
            data = json.loads(package.read_text(encoding="utf-8", errors="replace"))
            for key in ("dependencies", "devDependencies"):
                declared.update(_normalize(k) for k in (data.get(key) or {}))
        except ValueError:
            pass
    return declared


def _local_names(repo: Path) -> set[str]:
    names = set()
    for base in (repo, repo / "src"):
        if not base.is_dir():
            continue
        for p in base.iterdir():
            if p.name.startswith("."):
                continue
            if p.is_dir() or p.suffix == ".py":
                names.add(p.stem.lower().replace("-", "_"))
    return names


def imports_census(repo: Path, lines) -> dict:
    declared = _declared_dependencies(repo)
    local = _local_names(repo)
    stdlib = {m.lower() for m in getattr(sys, "stdlib_module_names", ())}
    hits: dict[str, list[str]] = {}
    for path, lineno, text in lines:
        suffix = Path(path).suffix
        pattern = _PY_IMPORT if suffix == ".py" else (
            _JS_IMPORT if suffix in _SOURCE_SUFFIXES else None)
        if pattern is None:
            continue
        for m in pattern.finditer(text) if pattern is _JS_IMPORT else (
                [m] if (m := pattern.match(text)) else []):
            root = m.group(1)
            key = root.lower().replace("-", "_")
            resolved = _normalize(_ALIASES.get(root, key))
            if key in stdlib or key in local or resolved in declared or key in declared:
                continue
            hits.setdefault(root, []).append(f"{path}:{lineno}")
    return {
        "undeclared": {name: locs[:_SAMPLE_CAP] for name, locs in sorted(hits.items())},
        "declared_count": len(declared),
        "caveat": ("candidates, not convictions: import names and package names differ "
                   "(a small alias map covers the famous cases) — verify before filing"),
    }


def placeholders_census(lines) -> dict:
    counts: dict[str, int] = {}
    samples: dict[str, list[str]] = {}

    def hit(kind, path, lineno, text):
        counts[kind] = counts.get(kind, 0) + 1
        if len(samples.setdefault(kind, [])) < _SAMPLE_CAP:
            samples[kind].append(f"{path}:{lineno} {text.strip()[:80]}")

    previous: dict[str, tuple[int, str]] = {}
    for path, lineno, text in lines:
        for kind, pattern in _PLACEHOLDER_PATTERNS:
            if pattern.search(text):
                hit(kind, path, lineno, text)
        # `except:` followed by `pass` — the two-line swallow. Consecutive in
        # the source, which for diff-scoped lines means consecutive numbers.
        prev = previous.get(path)
        if (prev and _EXCEPT_LINE.match(prev[1]) and _PASS_LINE.match(text)
                and lineno == prev[0] + 1):
            hit("swallowed_except", path, lineno, prev[1].strip() + " / pass")
        previous[path] = (lineno, text)
    return {"counts": counts, "samples": samples}


def provenance_census(repo: Path, sha_range: str | None) -> dict:
    """How much of the range under review is AI-attributed. Trailers are the
    only measurable signal; their absence proves nothing (plenty of tooling
    strips them), which is why the profile can also declare `authorship`."""
    ref = sha_range if sha_range else "-30"
    args = (["log", sha_range, "--pretty=%B%x00"] if sha_range
            else ["log", "-30", "--pretty=%B%x00"])
    raw = _git(args, repo)
    if raw is None:
        return {"scope": "unavailable (not a git repository or bad range)"}
    bodies = [b for b in raw.split("\x00") if b.strip()]
    attributed = sum(1 for b in bodies if _AI_TRAILER.search(b))
    return {
        "scope": f"commits in {ref}" if sha_range else "last 30 commits",
        "commits": len(bodies),
        "ai_attributed": attributed,
        "caveat": "absence of trailers is not evidence of human authorship",
    }


def code_census(repo: Path, sha_range: str | None) -> dict:
    """The full census block for facts.json."""
    if sha_range:
        lines = _added_lines(repo, sha_range)
        scope = {"scope": f"lines added in {sha_range}"}
        if lines is None:
            lines, scanned, capped = _tree_lines(repo)
            scope = {"scope": f"tree scan of {scanned} source files"
                              + (" (capped)" if capped else ""),
                     "note": "diff unavailable; fell back to the tree"}
    else:
        lines, scanned, capped = _tree_lines(repo)
        scope = {"scope": f"tree scan of {scanned} source files"
                          + (" (capped — a sample, not a crawl)" if capped else "")}
    return {
        **scope,
        "imports": imports_census(Path(repo), lines),
        "placeholders": placeholders_census(lines),
        "provenance": provenance_census(Path(repo), sha_range),
        "reading": ("leads, not findings: counts tell judgment where to look; "
                    "judgment decides what they mean"),
    }
