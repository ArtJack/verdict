#!/usr/bin/env python3
"""Findings as files — `<qa-root>/findings/<ID>.json`, one per finding, written
the moment it is proven and validated the moment it is written.

The judgment used to be one JSON written from memory at the end of the run:
boltons paused 3:32 to write 39,500 characters, a third of them findings
re-typed from the previous state; ofetch 5:12. A finding file is written while
the evidence is still in the agent's context, the PostToolUse validator checks
it at once, and a rejection costs one file rather than the whole judgment.
`verdict-finalize` assembles the files; `judgment.json` keeps only the
run-level fields and the two cheap verbs (`still_open`, `resolved`).

`verdict-facts` moves the previous run's files to `findings.prev/` — never
deletes them: an abandoned run's files are evidence, and the next run says
where they went. A retry of the same run keeps its own files in place.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

FINDINGS_DIR = "findings"
PREV_DIR = "findings.prev"
_NAME = re.compile(r"^(?P<id>[A-Za-z0-9_.-]+-F-\d+)\.json$")


def finding_file(path) -> tuple[Path, str] | None:
    """(qa_root, id) when `path` has the shape `<qa-root>/findings/<ID>.json`."""
    p = Path(path)
    m = _NAME.match(p.name)
    if not m or p.parent.name != FINDINGS_DIR:
        return None
    return p.parent.parent, m["id"]


def archive_findings(qa_root: Path, keep: bool) -> dict | None:
    """Move last run's `findings/` aside before this run starts → what was done.

    `keep` is a retry of the same run (a marker at this commit, minutes old):
    the files are this attempt's own and stay. Otherwise they go to
    `findings.prev/`, replacing the older one — moved, not deleted."""
    d = Path(qa_root) / FINDINGS_DIR
    if not d.is_dir():
        return None
    files = sorted(p.name for p in d.iterdir() if p.is_file())
    if not files:
        return None
    if keep:
        return {"kept": len(files), "why": "an earlier attempt at this same commit — "
                                           "this run's own files, left in place"}
    prev = Path(qa_root) / PREV_DIR
    shutil.rmtree(prev, ignore_errors=True)
    d.rename(prev)
    return {"moved": len(files), "to": PREV_DIR,
            "why": "last run's finding files, moved aside so this run starts empty"}


def _stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_filed(qa_root: Path) -> tuple[list[dict], list[str]]:
    """Every finding file, oldest first → (findings, problems).

    Each finding carries two private keys the caller strips: `_file` (its
    path, for messages) and `_filed_at` (the file's modification time, the
    measured moment the finding was written)."""
    d = Path(qa_root) / FINDINGS_DIR
    if not d.is_dir():
        return [], []
    found, problems = [], []
    paths = sorted((p for p in d.iterdir() if p.is_file() and p.suffix == ".json"),
                   key=lambda p: (p.stat().st_mtime, p.name))
    for p in paths:
        rel = f"{FINDINGS_DIR}/{p.name}"
        m = _NAME.match(p.name)
        if not m:
            problems.append(f"{rel}: the filename must be `<PROJECT>-F-<n>.json`, the finding's id")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            problems.append(f"{rel}: unreadable — {exc}")
            continue
        if not isinstance(data, dict):
            problems.append(f"{rel}: not a JSON object")
            continue
        if str(data.get("id") or "") != m["id"]:
            problems.append(f"{rel}: carries id {data.get('id')!r}, but the filename says "
                            f"{m['id']!r} — one finding, one file, one id")
            continue
        data["_file"] = rel
        data["_filed_at"] = _stamp(p.stat().st_mtime)
        found.append(data)
    return found, problems
