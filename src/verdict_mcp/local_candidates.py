"""What to ask about, decided by the harness and not the model: the candidates of a run,
the changed files and lines of a delta, and their order by risk.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

try:
    from .harness import is_test_file
    from . import languages
    from .local_chunks import _source_chunks, chunks_of, gap_functions
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import languages
    from harness import is_test_file
    from local_chunks import _source_chunks, chunks_of, gap_functions


# ── what to ask about: the harness decides, not the model ─────────────────────


def candidates(facts: dict, repo: Path) -> list:
    """Which files to read: the ones holding an assertion-gap survivor first, then least
    covered first — the reading map when the profile measured coverage, the tracked source
    otherwise."""
    reading = facts.get("reading_map") or {}
    files = list(gap_functions(facts))
    # The scope the profile names (0.92.0), before the coverage order and the largest files.
    files += [f for f in ((facts.get("risk_focus") or {}).get("files") or []) if isinstance(f, str)]
    files += [m["path"] for m in (reading.get("lowest") or []) if m.get("path")]
    files += [m["path"] for m in (reading.get("never_imported") or []) if isinstance(m, dict)
              and m.get("path")]
    if not files:
        census = facts.get("code_census") or {}
        files = [f for f in (census.get("largest_files") or []) if isinstance(f, str)]
    if not files:
        python = [str(p.relative_to(repo)) for p in sorted(repo.rglob("*.py"))
                  if ".venv" not in p.parts and "test" not in p.name]
        others = other_sources(repo)
        # A Python project is read as it always was. A website with no coverage map and no
        # profile scope read nothing at all here (2026-11-11: 0 files on a Next.js site).
        files = python if not others else by_risk(repo, python + others)
    seen, out = set(), []
    for rel in files:
        if rel in seen or not (repo / rel).is_file():
            continue
        seen.add(rel)
        out.append(rel)
    return out


def other_sources(repo: Path) -> list:
    """The tracked source files in languages other than Python that this engine reads: not
    tests, not generated, not vendored. Outside git, none: a directory walk would read whatever
    happens to sit on disk as if it were committed."""
    proc = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True)
    if proc.returncode != 0:
        return []
    return [n for n in proc.stdout.decode("utf-8", "replace").split("\0")
            if n and languages.readable(n)]


# Modules that hold a site's copy and data rather than its behaviour: they change the most lines
# and ask the least. Measured 2026-11-11 on a Next.js site: ranked by lines added, its data files
# took the whole budget and every money and sign-in file sat in the unasked tail.
_CONTENT_PATH = re.compile(r"(?:^|[/_.\-])(?:data|content|copy|strings|i18n|l10n|locales?|messages|"
                           r"translations?|dictionar(?:y|ies)|seo|metadata|constants)(?:$|[/_.\-])", re.I)


def content_rank(rel: str) -> int:
    """1 for a module of copy or data, 0 for code."""
    return 1 if _CONTENT_PATH.search(rel) else 0


# Where a website keeps the code that takes money, signs people in or accepts what strangers send.
_RISKY_PATH = re.compile(r"(?:^|[/_.\-])(?:api|server|actions?|auth\w*|login|session|sign\w*|pay\w*|"
                         r"checkout|stripe|billing|invoice|refund|orders?|cart|webhooks?|admin|"
                         r"middleware|routes?|controllers?|handlers?|uploads?|forms?|contact|"
                         r"accounts?|users?|tokens?|secrets?|prices?|pricing)(?:$|[/_.\-])", re.I)


def by_risk(repo: Path, files: list) -> list:
    """`files` in the order a breadth pass with nothing else to go on should read them: code
    before excerpts and templates, behaviour before copy and data, a path that names money,
    sign-in or input before one that does not, and larger files first."""
    def family_rank(rel):
        lang = languages.language_of(rel)
        family = languages.family_of(lang)
        if family == "lines":
            return 2 if languages.is_template(lang) else 1
        return 0

    def size(rel):
        try:
            return (repo / rel).stat().st_size
        except OSError:
            return 0
    return sorted(files, key=lambda rel: (family_rank(rel), content_rank(rel),
                                          0 if _RISKY_PATH.search(rel) else 1, -size(rel), rel))


def changed_files(repo: Path, sha_range: str | None) -> list:
    """The files a range touched, as git names them — or [] when there is no range."""
    if not sha_range:
        return []
    proc = subprocess.run(["git", "-C", str(repo), "diff", "--name-only", sha_range],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return []
    return sorted({ln.strip().replace("\\", "/") for ln in proc.stdout.splitlines() if ln.strip()})


def changed_lines_of(facts: dict) -> dict:
    """`{path: set(line)}` for the changed lines no test executed, from measured
    coverage. The best free ranking there is: a changed line the suite never ran
    is the code most likely to be wrong and least likely to be caught."""
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    if cov.get("status") != "measured":
        return {}
    out: dict = {}
    for path, entry in (cov.get("per_file") or {}).items():
        if not isinstance(entry, dict):
            continue
        lines = set()
        for span in entry.get("unexercised_ranges") or []:
            if isinstance(span, (list, tuple)) and len(span) == 2:
                lines |= set(range(int(span[0]), int(span[1]) + 1))
            elif isinstance(span, int):
                lines.add(span)
        if lines:
            out[str(path).replace("\\", "/")] = lines
    return out


def drifted_paths(facts: dict) -> list:
    """Files under a finding whose cited code moved or changed since the evidence
    was written — the second-best free ranking, because the harness already knows
    the reader was about to be misled there."""
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    if drift.get("status") != "measured":
        return []
    out = []
    for rec in (drift.get("findings") or {}).values():
        if not isinstance(rec, dict):
            continue
        for ref in rec.get("refs") or []:
            if isinstance(ref, dict) and ref.get("status") in ("changed", "moved", "missing"):
                path = str(ref.get("ref") or "").rsplit(":", 1)[0]
                if path:
                    out.append(path.replace("\\", "/"))
    return out


def delta_candidates(facts: dict, repo: Path, changed: list, sizes: dict | None = None) -> list:
    """What to read when the run is a delta: the change, ranked by what nothing ran.

    Coverage rank is the right question for a baseline and the wrong one for a
    delta — the least-covered module in the repository is the same module it was
    last night, and re-reading it spends the night re-deriving yesterday's
    findings. A delta reads the diff: the changed files whose changed lines no
    test executed first, then the files a drifted finding cites, then the rest of
    the diff.

    The reading map is the fallback for a run with NO range at all, and only
    then. A range that contains nothing this engine reads must come back empty:
    falling through to the whole repository would let a diff of YAML and Markdown
    be reported as an audit of files the change never touched.

    A diff that holds code in any other language ranks the rest of the change by
    how many lines each file added (`sizes`), whatever its language, after the
    files the profile names outright. Python first would be the measured failure
    this ordering exists to stop: a .NET range whose six changed Python helper
    scripts took every question while the C# beside them went unread. A diff of
    Python alone is ranked exactly as before.
    """
    if not changed:
        return candidates(facts, repo)
    cold = changed_lines_of(facts)
    drifted = drifted_paths(facts)
    gapped = gap_functions(facts)
    ranked, seen = [], set()
    if not any(languages.readable(p) for p in changed):
        groups = ([p for p in changed if p in gapped],
                  [p for p in changed if p in cold],
                  [p for p in changed if p in drifted],
                  list(changed))
    else:
        # The code before its tests: a Python test file is still read, after every source file,
        # and a test in any other language is not read here at all.
        named = {str(f) for f in ((facts.get("risk_focus") or {}).get("named_files") or [])}
        groups = ([p for p in changed if p in gapped],
                  [p for p in changed if p in cold],
                  [p for p in changed if p in drifted],
                  [p for p in changed if p in named],
                  sorted(changed, key=lambda p: (is_test_file(p), content_rank(p),
                                                 0 if _RISKY_PATH.search(p) else 1,
                                                 -int((sizes or {}).get(p, 0)), p)))
    for group in groups:
        for rel in group:
            if rel in seen or not (rel.endswith(".py") or languages.readable(rel)):
                continue
            if not (repo / rel).is_file():
                continue
            seen.add(rel)
            ranked.append(rel)
    return ranked


def python_in(paths) -> list:
    """The `.py` files of a set of paths."""
    return [p for p in paths if str(p).endswith(".py")]


def readable_in(paths) -> list:
    """The files of a set of paths this engine reads: Python, and source in any other
    language that is not a test, generated or vendored. A diff with none of them is
    a diff this engine cannot read at all, and that is a fact the run has to state
    rather than a reason to report a clean pass."""
    return [p for p in paths if str(p).endswith(".py") or languages.readable(p)]


def added_lines(repo: Path, sha_range: str | None) -> dict:
    """`{path: lines added}` over the range, from `git diff --numstat` (binary files: 0)."""
    if not sha_range:
        return {}
    proc = subprocess.run(["git", "-C", str(repo), "diff", "--numstat", "--no-color", sha_range],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out = {}
    for line in proc.stdout.splitlines() if proc.returncode == 0 else []:
        parts = line.split("\t")
        if len(parts) == 3:
            out[parts[2].replace("\\", "/")] = int(parts[0]) if parts[0].isdigit() else 0
    return out


_DIFF_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def changed_lines_in(repo: Path, sha_range: str | None, paths) -> dict:
    """`{path: set(line)}`: the lines the range added or changed in `paths`, in the new file's
    numbering. Where a hunk only deleted, the line after the deletion stands for it."""
    paths = [str(p) for p in paths]
    if not sha_range or not paths:
        return {}
    proc = subprocess.run(["git", "-C", str(repo), "diff", "-U0", "--no-color", "--diff-filter=AM",
                           sha_range, "--", *paths],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    out: dict = {}
    current = None
    for line in proc.stdout.splitlines() if proc.returncode == 0 else []:
        if line.startswith("+++ "):
            current = line[6:].replace("\\", "/") if line.startswith("+++ b/") else None
            continue
        m = _DIFF_HUNK.match(line)
        if m and current:
            start, count = int(m.group(1)), int(m.group(2) if m.group(2) is not None else 1)
            out.setdefault(current, set()).update(range(start, start + count) if count
                                                  else {max(start, 1)})
    return out


def chunks_in_range(repo: Path, rel: str, lines: set | None) -> list:
    """The functions of a file that intersect the changed lines — the whole file
    when the range is not known at line granularity. A file in any other language
    answers for its changed lines itself: the function each one sits in, the statement
    or paragraph that holds it, or the lines around it."""
    if lines:
        other = _source_chunks(repo, rel, lines)
        if other is not None:
            return other
    chunks = chunks_of(repo, rel)
    if not lines:
        return chunks
    return [c for c in chunks if any(c.start <= n <= c.end for n in lines)] or chunks
