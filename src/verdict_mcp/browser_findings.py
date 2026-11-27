"""The browser pass's findings: the marker that ties one to a check and a page, the finding
itself, whether a project configured the check away, and what a later pass resolves by
measurement.

Split out of browser.py before it landed (2026-11-15): every block below is byte-identical to
the browser pass as it was built and measured, and browser.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from .browser_config import ROUTING_FILES, _MARK
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from browser_config import ROUTING_FILES, _MARK


# ── findings ──────────────────────────────────────────────────────────────────


def marker(check: str, path: str, browser: str) -> str:
    return f"measured by the browser check `{check}` on `{path}` in {browser} — not by a model"


def marks_of(finding: dict) -> set:
    """The (check, page) pairs a browser finding was measured on, read back from its evidence."""
    return {(m.group(1), m.group(2)) for e in finding.get("evidence") or []
            for m in _MARK.finditer(str(e))}


def finding(check: str, path: str, source: str | None, title: str, severity: str,
            priority: str, lines: list, mechanism: str, narrative: str, browser: str,
            also: list | None = None) -> dict:
    """One measured finding in the shape `verdict-local` files. The first evidence line starts
    with the page's source file when the routing names one, so the finding's identity holds
    across runs and a person knows which file to open. `also` names the other pages the same
    finding was measured on: each gets its own marker, and a later run resolves the finding
    only after measuring every one of them again."""
    where = source or f"page {path}"
    marks = [marker(check, p, browser) for p in dict.fromkeys([path] + list(also or []))]
    return {
        "title": title[:200],
        "severity": severity, "priority": priority, "status": "open",
        "failure_classification": None, "confidence": "proven",
        "evidence": [f"{where} — {lines[0]}"] + list(lines[1:]) + marks,
        "root_cause": {"mechanism": mechanism, "origin": "not investigated in local mode"},
        "narrative": narrative,
    }


def configured(repo: Path | None, path: str) -> str | None:
    """The routing file in the repository that mentions `path`, if one does."""
    if repo is None or path in ("", "/"):
        return None
    for name in ROUTING_FILES:
        f = Path(repo) / name
        try:
            if f.is_file() and path in f.read_text(encoding="utf-8", errors="replace"):
                return name
        except OSError:
            continue
    return None


def resolved_by_measurement(previous: dict | None, measured: set, refound: set) -> list:
    """Prior open browser findings this pass measured again and did not find: every (check,
    page) the finding was measured on ran to the end this time, and its identity was not filed
    or found again. Anything else — a page not reached, a check that could not run — leaves the
    finding where it was."""
    out = []
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if str(f.get("status") or "open").lower() != "open" or str(f["id"]) in refound:
            continue
        marks = marks_of(f)
        if marks and marks <= measured:
            out.append(str(f["id"]))
    return out
