#!/usr/bin/env python3
"""Deterministic censuses over the code under review. Stdlib only.

Verdict increasingly reviews code that a model wrote, and models fail in
characteristic ways — hallucinated dependencies, placeholders that never get
revisited, errors swallowed to make a demo work. Some of those signatures are
*mechanically countable*, and this project's standing rule applies: what can be
measured is never left to the model to notice.

Four censuses, attached to facts.json as `code_census`:

  imports       import roots that match no declared dependency, no stdlib
                module, and no local module — the hallucinated-dependency
                check, which is also a supply-chain check (slopsquatting
                registers packages under plausible hallucinated names).
  placeholders  TODO/FIXME/"for now"/stub markers, and silently swallowed
                exceptions (`except: pass`, empty `catch {}`).
  provenance    how much of the range under review is AI-attributed, from
                commit trailers — measured, not assumed.
  dependencies  for every third-party import in the range, the version actually
                installed in this checkout and the path to read it at — so a
                claim about a library's behaviour can cite the artifact instead
                of the model's recollection of it.

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


def _git(args, repo, text=True):
    proc = subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=text)
    return proc.stdout if proc.returncode == 0 else None


# git diff as this module parses it, whatever the user's configuration says: names
# unquoted where git allows it, no colour codes, no external diff or text
# conversion standing in for the content, and the a/ b/ prefixes the headers are
# read with.
_DIFF = ("-c", "core.quotePath=false", "diff", "--unified=0", "--no-color", "--no-ext-diff",
         "--no-textconv", "--src-prefix=a/", "--dst-prefix=b/")
_C_ESCAPES = {"a": "\a", "b": "\b", "t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r",
              '"': '"', "\\": "\\"}


def _added_lines(repo, sha_range):
    """(path, new_lineno, text) for every line the range added.

    Read by position, never by prefix alone. Each `diff --git` starts a file with no
    name yet; its `+++ ` header names it, and is read only before the first `@@`.
    From there on every line starting with "+" is content: an added `++i;`, or an
    added `++ b/x.py` under a removed `-- comment`, was once taken for a header —
    the one line dropped and every later one misnumbered or charged to a file that
    does not exist.

    Lines are numbered as git numbers them, at "\\n" alone: CRLF is folded, and a
    lone CR stays inside its line, as `_tree_lines` leaves it. A -U0 diff cannot see
    a CR in a line it did not change, so breaking at one anywhere would number the
    tree and the diff apart. The diff is read as bytes: in text mode every CR became
    a newline across the whole diff, and the piece after one, no longer starting
    with "+", was dropped."""
    diff = _git([*_DIFF, sha_range], repo, text=False)
    if diff is None:
        return None
    out, path, lineno, in_hunk = [], None, 0, False
    for raw in diff.decode("utf-8", errors="replace").replace("\r\n", "\n").split("\n"):
        if raw.startswith("diff --git "):
            path, in_hunk = None, False
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            in_hunk, lineno = True, int(m.group(1)) if m else 0
        elif not in_hunk:
            if raw.startswith("+++ "):
                path = _header_path(raw[4:])
        elif raw.startswith("+"):
            if path is not None:
                out.append((path, lineno, raw[1:]))
            lineno += 1
    return out


def _header_path(name: str):
    """The file a `+++ ` header names, or None: /dev/null, or a name this cannot read,
    so that nothing is charged to the wrong file. git ends a name holding a space
    with a tab, and still quotes one holding a quote or a control character."""
    if name.endswith("\t"):
        name = name[:-1]
    if name.startswith('"'):
        name = _unquote(name)
    return name[2:] if name and name.startswith("b/") else None


def _unquote(quoted: str):
    """A name git wrote in C-style quotes, read back — None when it is not one."""
    if len(quoted) < 2 or not quoted.endswith('"'):
        return None
    body, out, i = quoted[1:-1], bytearray(), 0
    while i < len(body):
        if body[i] != "\\":
            out += body[i].encode("utf-8")
            i += 1
        elif body[i + 1:i + 2] in _C_ESCAPES:
            out += _C_ESCAPES[body[i + 1]].encode("utf-8")
            i += 2
        elif re.fullmatch(r"[0-7]{3}", body[i + 1:i + 4]):
            out.append(int(body[i + 1:i + 4], 8))     # a byte of a name, in octal
            i += 4
        else:
            return None
    try:
        return out.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _tree_lines(repo):
    """(path, lineno, text) over the tree, capped — with the cap reported. Each file
    is read as bytes and numbered the way `_added_lines` numbers a diff, at "\\n"
    alone with CRLF folded, rather than by the platform's text mode, which also
    breaks at a lone CR."""
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
            text = p.read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
        except OSError:
            continue
        rel = p.relative_to(repo).as_posix()
        out.extend((rel, i, line) for i, line in enumerate(text.split("\n"), 1))
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


# A package specifier as the dependency census needs it, which is not the same
# question `_JS_IMPORT` asks: that one wants the root to compare against declared
# names, this one wants the thing you can actually open on disk, scope included
# (`@scope/name` lives at `node_modules/@scope/name`, not `node_modules/@scope`).
_JS_PACKAGE = re.compile(
    r"""(?:from\s+|require\(\s*)['"](@[^'"/]+/[^'"/]+|[^'"./][^'"/]*)""")

_DIST_CAP = 500  # dist-info dirs read per environment; a venv has far fewer


def _site_packages(repo: Path) -> list[Path]:
    """Every site-packages under a venv inside the checkout. Nothing outside it:
    the interpreter running this census is the harness's, not the project's, and
    its own site-packages would answer a different question entirely."""
    out, seen = [], set()

    def keep(sp: Path) -> None:
        # A case-insensitive filesystem answers to both "lib" and "Lib", so the
        # two spellings below reach one directory twice on a Mac — and
        # `resolve()` does not fold case there, so the identity has to come from
        # the inode. Without this the census reports two environments where a
        # reader can only open one.
        if not sp.is_dir():
            return
        try:
            info = sp.stat()
        except OSError:
            return
        key = (info.st_dev, info.st_ino)
        if key not in seen:
            seen.add(key)
            out.append(sp)

    for venv in (".venv", "venv"):
        for lib in ("lib", "Lib"):
            base = repo / venv / lib
            if not base.is_dir():
                continue
            keep(base / "site-packages")             # Windows layout
            for py in sorted(base.glob("python*")):  # posix layout
                keep(py / "site-packages")
    return out


def _python_installed(repo: Path) -> dict:
    """import root -> {distribution, version, path}, read from `*.dist-info`.

    `top_level.txt` is what maps an import root to the distribution that owns it
    (`yaml` -> PyYAML); where it is absent the normalized distribution name is the
    best available guess. Nothing here imports the package: resolving a dependency
    by importing it would execute the code under test, which §0 forbids outright.
    """
    index: dict[str, dict] = {}
    for sp in _site_packages(repo):
        for i, info in enumerate(sorted(sp.glob("*.dist-info"))):
            if i >= _DIST_CAP:
                break
            dist, _, version = info.name[: -len(".dist-info")].rpartition("-")
            if not dist or not version:
                continue
            tops: list[str] = []
            top_file = info / "top_level.txt"
            if top_file.is_file():
                try:
                    tops = [ln.strip() for ln
                            in top_file.read_text(encoding="utf-8",
                                                  errors="replace").splitlines()
                            if ln.strip()]
                except OSError:
                    tops = []
            for top in tops or [_normalize(dist)]:
                key = top.lower().replace("-", "_")
                if key in index:
                    continue
                package_dir, module = sp / top, sp / f"{top}.py"
                where = (package_dir if package_dir.is_dir()
                         else module if module.is_file() else info)
                index[key] = {"distribution": dist, "version": version,
                              "path": where.relative_to(repo).as_posix()}
    return index


def _node_installed(repo: Path, spec: str) -> dict | None:
    """Resolve one specifier under `node_modules`, read lazily — a crawl of
    node_modules costs more than every other census put together."""
    parts = spec.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    package = repo.joinpath("node_modules", *parts)
    manifest = package / "package.json"
    if not manifest.is_file():
        return None
    import json
    try:
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (ValueError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return {"distribution": str(data.get("name") or spec),
            "version": str(data.get("version") or "unknown"),
            "path": package.relative_to(repo).as_posix()}


def _iter_import_specs(lines):
    for path, lineno, text in lines:
        suffix = Path(path).suffix
        if suffix == ".py":
            m = _PY_IMPORT.match(text)
            if m:
                yield m.group(1), path, lineno, suffix
        elif suffix in _SOURCE_SUFFIXES:
            for m in _JS_PACKAGE.finditer(text):
                yield m.group(1), path, lineno, suffix


def dependencies_census(repo: Path, lines) -> dict:
    """What this checkout would actually import, at the version it would import.

    A finding about a library's behaviour is only as good as the version it was
    checked against, and the model's recollection is of neither this project nor
    this pin. `resolved` gives judgment the file to open; `unresolved` says the
    contract cannot be read here, which caps such a finding at `hypothesis`
    rather than licensing a guess.
    """
    repo = Path(repo)
    stdlib = {m.lower() for m in getattr(sys, "stdlib_module_names", ())}
    local = _local_names(repo)
    py_index: dict | None = None
    node_seen: dict[str, dict | None] = {}
    resolved: dict[str, dict] = {}
    unresolved: dict[str, list[str]] = {}

    for spec, path, lineno, suffix in _iter_import_specs(lines):
        key = spec.lower().replace("-", "_")
        if suffix == ".py":
            if key in stdlib or key in local:
                continue
            if py_index is None:
                py_index = _python_installed(repo)
            hit = py_index.get(key) or py_index.get(
                _normalize(_ALIASES.get(spec, key)))
        else:
            if spec not in node_seen:
                node_seen[spec] = _node_installed(repo, spec)
            hit = node_seen[spec]
        location = f"{path}:{lineno}"
        if hit:
            entry = resolved.setdefault(spec, {**hit, "cited_at": []})
            if location not in entry["cited_at"] and len(entry["cited_at"]) < _SAMPLE_CAP:
                entry["cited_at"].append(location)
        else:
            seen = unresolved.setdefault(spec, [])
            if location not in seen and len(seen) < _SAMPLE_CAP:
                seen.append(location)

    environments = [sp.relative_to(repo).as_posix() for sp in _site_packages(repo)]
    if (repo / "node_modules").is_dir():
        environments.append("node_modules")
    return {
        "environments": environments,
        "resolved": dict(sorted(resolved.items())),
        "unresolved": dict(sorted(unresolved.items())),
        "reading": ("read the installed artifact before filing a finding about its "
                    "behaviour — recollection of an API is not evidence, and does not "
                    "know this project's pin. No environment here means the contract "
                    "is unreadable from this checkout: say so, and file at most a "
                    "hypothesis."),
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
        "dependencies": dependencies_census(Path(repo), lines),
        "reading": ("leads, not findings: counts tell judgment where to look; "
                    "judgment decides what they mean"),
    }
