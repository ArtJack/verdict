"""The page's source file, so a finding cites something a person can open: the route a URL
maps to in a Next.js app or pages folder, and the file that renders it.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations

import urllib.robotparser
from pathlib import Path


# ── the page's source file, so a finding cites something a person can open ───


PAGE_FILES = ("page.tsx", "page.ts", "page.jsx", "page.js", "page.mdx", "page.md")


ROUTE_EXT = (".tsx", ".ts", ".jsx", ".js", ".mdx", ".md", ".astro", ".vue", ".svelte", ".html")


def _dynamic(name: str) -> bool:
    return name.startswith("[") and name.endswith("]")


def _catch_all(name: str) -> bool:
    return name.startswith("[...") or name.startswith("[[...")


def _app_dirs(d: Path) -> list:
    """A directory and every route group `(name)` reachable from it through groups only."""
    out = [d]
    try:
        children = sorted(c for c in d.iterdir() if c.is_dir())
    except OSError:
        return out
    for c in children:
        if c.name.startswith("(") and c.name.endswith(")"):
            out += _app_dirs(c)
    return out


def _app_page(d: Path, segs: list) -> Path | None:
    """The Next.js app-router page a URL path resolves to: exact segments first, then
    dynamic `[x]`, then catch-alls; route groups are transparent."""
    for base in _app_dirs(d):
        if not segs:
            for name in PAGE_FILES:
                if (base / name).is_file():
                    return base / name
            continue
        head, rest = segs[0], segs[1:]
        exact = base / head
        if exact.is_dir() and not _dynamic(head):
            hit = _app_page(exact, rest)
            if hit:
                return hit
    for base in _app_dirs(d):
        try:
            children = sorted(c for c in base.iterdir() if c.is_dir())
        except OSError:
            continue
        for c in children:
            if not _dynamic(c.name):
                continue
            if _catch_all(c.name):
                if segs or c.name.startswith("[[..."):
                    for name in PAGE_FILES:
                        if (c / name).is_file():
                            return c / name
            elif segs:
                hit = _app_page(c, segs[1:])
                if hit:
                    return hit
    return None


def _file_route(d: Path, segs: list, index: str = "index") -> Path | None:
    """`pages/`-style routing: `/a/b` is `a/b.<ext>` or `a/b/index.<ext>`, `[x]` matches."""
    if not segs:
        for ext in ROUTE_EXT:
            if (d / f"{index}{ext}").is_file():
                return d / f"{index}{ext}"
        return None
    head, rest = segs[0], segs[1:]
    if not rest:
        for ext in ROUTE_EXT:
            if (d / f"{head}{ext}").is_file():
                return d / f"{head}{ext}"
    if (d / head).is_dir():
        hit = _file_route(d / head, rest, index)
        if hit:
            return hit
    try:
        children = sorted(d.iterdir())
    except OSError:
        return None
    for c in children:
        stem = c.name.rsplit(".", 1)[0] if c.is_file() else c.name
        if not _dynamic(stem):
            continue
        if c.is_file() and (not rest or _catch_all(stem)) and c.suffix in ROUTE_EXT:
            return c
        if c.is_dir():
            hit = _file_route(c, rest, index)
            if hit:
                return hit
    return None


def source_of(repo: Path | None, path: str) -> str | None:
    """The file in the repository that serves a URL path, when the framework's routing says
    so: Next.js (app and pages), Astro, Nuxt, SvelteKit, or a static `.html` file."""
    if repo is None:
        return None
    repo = Path(repo)
    segs = [s for s in urllib.parse.unquote(path.split("?", 1)[0]).split("/") if s]
    hit = None
    for base in ("app", "src/app"):
        if (repo / base).is_dir():
            hit = _app_page(repo / base, segs)
            if hit:
                break
    if hit is None:
        for base in ("pages", "src/pages"):
            if (repo / base).is_dir():
                hit = _file_route(repo / base, segs)
                if hit:
                    break
    if hit is None and (repo / "src/routes").is_dir():
        d = repo / "src/routes"
        for seg in segs:
            d = d / seg
        if (d / "+page.svelte").is_file():
            hit = d / "+page.svelte"
    if hit is None:
        for base in ("", "public", "static", "site", "docs", "dist"):
            root = repo / base if base else repo
            if not root.is_dir():
                continue
            if segs and segs[-1].endswith((".html", ".htm")):
                candidate = root.joinpath(*segs)
            elif segs:
                candidate = root.joinpath(*segs[:-1], segs[-1] + ".html")
                if not candidate.is_file():
                    candidate = root.joinpath(*segs, "index.html")
            else:
                candidate = root / "index.html"
            if candidate.is_file():
                hit = candidate
                break
    if hit is None:
        return None
    try:
        return hit.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        return None
