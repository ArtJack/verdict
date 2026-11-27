"""The import names a JavaScript project gives its own files: TypeScript's `paths` and
`baseUrl`, read from the `tsconfig.json` or `jsconfig.json` nearest each importing file.

With `"@components/*": ["src/components/*"]`, `@components/Button` is spelled like a
scoped npm package and is the project's own file. Until 2026-11-27 both censuses read such
a name as a dependency: the imports census as undeclared, the dependencies census as
unresolved. An unresolved contract caps a finding at hypothesis.

A config is JSON with comments and trailing commas, which is what `tsc` accepts. It may
`extends` another by relative path, and a `paths` or `baseUrl` of its own replaces the one
it extends, as `tsc` reads it. A config that cannot be read is named in `unreadable`; it
is never taken for a config with no aliases. A bundler's own aliases (Vite's
`resolve.alias`, webpack's) live in code, not data, and are not read.
"""
from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

_CONFIGS = ("tsconfig.json", "jsconfig.json")  # tsc's own order: a tsconfig wins
_EXTENDS_DEPTH = 8
_MODULE_SUFFIXES = (".ts", ".tsx", ".d.ts", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts",
                    ".vue", ".svelte", ".json")


def _string_end(text: str, i: int) -> int:
    """The index just past the JSON string that opens at `text[i]`."""
    j, n = i + 1, len(text)
    while j < n:
        if text[j] == "\\":
            j += 2
        elif text[j] == '"':
            return j + 1
        else:
            j += 1
    return n


def _without_comments(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            j = _string_end(text, i)
            out.append(text[i:j])
            i = j
        elif text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


def _without_trailing_commas(text: str) -> str:
    out, i, n = [], 0, len(text)
    while i < n:
        if text[i] == '"':
            j = _string_end(text, i)
            out.append(text[i:j])
            i = j
            continue
        if text[i] == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(text[i])
        i += 1
    return "".join(out)


def read_config(path: Path) -> dict:
    """A tsconfig as data. Raises ValueError or OSError when it cannot be read as one."""
    text = path.read_text(encoding="utf-8-sig")
    data = json.loads(_without_trailing_commas(_without_comments(text)))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} is not a JSON object")
    return data


def _inside(path: Path, repo: Path) -> bool:
    try:
        path.relative_to(repo)
        return True
    except ValueError:
        return False


def names_own_files(pattern: str, root: str) -> bool:
    """Whether a `paths` pattern maps the imports whose package root reads as `root`.

    The censuses read an import to its package root: `@components/Button` stays whole,
    `utils/date` is read as `utils`. So `"utils/*"` names the root `utils`. A lone `"*"` is
    tsc's fallback for every name; it is no alias, or every package would vanish."""
    star = pattern.find("*")
    head = pattern if star < 0 else pattern[:star]
    if not head:
        return False
    if star < 0:
        return pattern == root or pattern.startswith(root + "/")
    return root.startswith(head) or (root + "/").startswith(head)


class Aliases:
    """Which import roots name the project's own files, for each importing file."""

    def __init__(self, repo: Path):
        self.repo = Path(repo).resolve()
        self.unreadable: list[str] = []
        self._by_dir: dict[str, dict] = {}

    def own(self, root: str, importer: str) -> bool:
        options = self._for(PurePosixPath(importer).parent)
        if any(names_own_files(p, root) for p in options.get("paths", ())):
            return True
        base = options.get("baseUrl")
        return base is not None and self._under(base, root)

    def _under(self, base: Path, root: str) -> bool:
        target = base.joinpath(*root.split("/"))
        if not _inside(target, self.repo):
            return False
        return target.is_dir() or any(
            target.with_name(target.name + s).is_file() for s in ("", *_MODULE_SUFFIXES))

    def _for(self, rel_dir: PurePosixPath) -> dict:
        key = rel_dir.as_posix()
        if key in self._by_dir:
            return self._by_dir[key]
        here = self.repo.joinpath(*rel_dir.parts)
        found = None
        for name in _CONFIGS:
            if (here / name).is_file():
                found = self._options((here / name).resolve(), frozenset())
                break
        if found is None:
            found = self._for(rel_dir.parent) if key not in ("", ".") else {}
        self._by_dir[key] = found
        return found

    def _options(self, path: Path, seen: frozenset) -> dict:
        """`paths` (its patterns) and `baseUrl` (a directory) as the config at `path` has
        them, what it `extends` applied first and its own options over it."""
        if path in seen or len(seen) >= _EXTENDS_DEPTH or not _inside(path, self.repo):
            return {}
        try:
            data = read_config(path)
        except (OSError, ValueError) as exc:
            said = f"{path.relative_to(self.repo).as_posix()}: {type(exc).__name__}"
            if said not in self.unreadable:  # a base config is read once per config extending it
                self.unreadable.append(said)
            return {}
        merged: dict = {}
        extends = data.get("extends")
        for parent in [extends] if isinstance(extends, str) else (
                extends if isinstance(extends, list) else []):
            # A package's shared config (`@tsconfig/node20/…`) names no project files.
            if isinstance(parent, str) and parent.startswith("."):
                target = (path.parent / parent).resolve()
                if not target.is_file() and target.suffix != ".json":
                    target = target.with_name(target.name + ".json")
                merged.update(self._options(target, seen | {path}))
        own = data.get("compilerOptions")
        if isinstance(own, dict):
            if isinstance(own.get("paths"), dict):
                merged["paths"] = list(own["paths"])
            if isinstance(own.get("baseUrl"), str):
                merged["baseUrl"] = (path.parent / own["baseUrl"]).resolve()
        return merged
