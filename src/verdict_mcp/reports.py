#!/usr/bin/env python3
"""Structured test results before summary dialects (T-14).

`verdict-facts` reads a dozen runner dialects off the summary line, and the
stranger's second stumble showed that a dialect is a guess: vitest and jest
counted the *file* line. Every runner Verdict meets can write a report file —
`pytest --junitxml`, `vitest --reporter=junit`, `jest-junit`, `gotestsum
--junitfile`, `cargo-nextest --junit` — and there is a Common Test Report
Format (CTRF, JSON) with reporters for most of them. A gate command may carry
`{report}`; the harness renders it to a scratch path before the gate runs and
parses what the gate wrote: exact counts, per-test durations, the failures
with their messages, and the test ids. Counts from a report outrank the
dialect; the dialects stay as the fallback that says it is a fallback.

Stdlib only: `xml.etree` for JUnit, `json` for CTRF.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_FAILURES = 20
MAX_SLOWEST = 10


def read_report(path) -> tuple[dict, list[str]]:
    """The report a gate wrote → (summary, ids). The summary carries `format`,
    `counts`, `duration_s`, `failures`, `slowest`; ids are every test the
    report names, shaped `classname::name` for JUnit (a pytest node id needs
    `test_ids_cmd`) and `filePath::name` or `suite::name` for CTRF."""
    p = Path(path)
    if not p.is_file():
        return {"status": "missing", "reason": "the gate did not write the report it was "
                                                "given a path for — the runner's report flag "
                                                "may be absent or misspelt"}, []
    try:
        raw = p.read_bytes()
    except OSError as exc:
        return {"status": "unreadable", "reason": str(exc)}, []
    head = raw.lstrip()[:1]
    if head == b"<":
        return _junit(raw)
    if head == b"{":
        return _ctrf(raw)
    return {"status": "unreadable", "reason": "neither JUnit XML nor CTRF JSON"}, []


def _junit(raw: bytes) -> tuple[dict, list[str]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return {"status": "unreadable", "reason": f"JUnit XML did not parse: {exc}"}, []
    cases = list(root.iter("testcase"))
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    failures, timed, ids = [], [], []
    total_s = 0.0
    for case in cases:
        name = case.get("name") or ""
        classname = case.get("classname") or ""
        file = case.get("file")
        tid = (f"{file}::{name}" if file else f"{classname}::{name}" if classname else name)
        ids.append(tid)
        try:
            seconds = float(case.get("time") or 0)
        except ValueError:
            seconds = 0.0
        total_s += seconds
        timed.append((seconds, tid))
        outcome = "passed"
        for child in case:
            tag = child.tag.rsplit("}", 1)[-1]
            if tag in ("failure", "error", "skipped"):
                outcome = {"failure": "failed", "error": "errors", "skipped": "skipped"}[tag]
                if tag != "skipped":
                    message = (child.get("message") or (child.text or "").strip()).strip()
                    failures.append({"id": tid, "kind": tag, "message": message[:300]})
                break
        counts[outcome] += 1
    counts["collected"] = len(cases)
    timed.sort(key=lambda x: -x[0])
    return {"status": "measured", "format": "junit", "tests": len(cases), "counts": counts,
            "duration_s": round(total_s, 3), "failures": failures[:MAX_FAILURES],
            "slowest": [{"id": t, "duration_s": round(s, 3)} for s, t in timed[:MAX_SLOWEST]],
            "id_shape": "file::name" if any(c.get("file") for c in cases) else "classname::name",
            }, ids


def _ctrf(raw: bytes) -> tuple[dict, list[str]]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        return {"status": "unreadable", "reason": f"CTRF JSON did not parse: {exc}"}, []
    results = (data or {}).get("results") if isinstance(data, dict) else None
    tests = (results or {}).get("tests") if isinstance(results, dict) else None
    if not isinstance(tests, list):
        return {"status": "unreadable", "reason": "no `results.tests` — not a CTRF report"}, []
    counts = {"passed": 0, "failed": 0, "skipped": 0, "errors": 0}
    failures, timed, ids = [], [], []
    total_ms = 0.0
    for t in tests:
        if not isinstance(t, dict):
            continue
        name = str(t.get("name") or "")
        where = t.get("filePath") or t.get("suite") or ""
        tid = f"{where}::{name}" if where else name
        ids.append(tid)
        try:
            ms = float(t.get("duration") or 0)
        except (TypeError, ValueError):
            ms = 0.0
        total_ms += ms
        timed.append((ms / 1000, tid))
        status = str(t.get("status") or "other").lower()
        if status == "passed":
            counts["passed"] += 1
        elif status == "failed":
            counts["failed"] += 1
            failures.append({"id": tid, "kind": "failure",
                             "message": str(t.get("message") or t.get("trace") or "")[:300]})
        elif status in ("skipped", "pending"):
            counts["skipped"] += 1
        else:
            counts["errors"] += 1
    counts["collected"] = len(ids)
    timed.sort(key=lambda x: -x[0])
    tool = ((results or {}).get("tool") or {}).get("name") if isinstance(results, dict) else None
    return {"status": "measured", "format": "ctrf", "tests": len(ids), "counts": counts,
            "duration_s": round(total_ms / 1000, 3), "failures": failures[:MAX_FAILURES],
            "slowest": [{"id": t, "duration_s": round(s, 3)} for s, t in timed[:MAX_SLOWEST]],
            "id_shape": "filePath::name", **({"tool": tool} if tool else {})}, ids
