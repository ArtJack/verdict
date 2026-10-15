#!/usr/bin/env python3
"""Evidence anchors — where the code a finding cites lives, hashed — and drift.

A finding cites `path:line`. `verdict-finalize` turns every such reference
into an anchor: the file's git blob id and a hash of that one line. The next
`verdict-facts` re-hashes the same references and writes `evidence_drift`:
`unchanged`, `moved` (the line is elsewhere in the file), `changed` (the line
is gone), `missing` (the file is gone) or `unresolvable` (the reference never
named a file this repository has). The tester reads where the code moved
instead of everything; "the code under an accepted risk changed" is a fact
rather than a courtesy; a verified-intact invariant carries its own anchors,
so the next run knows whether the lines it stood on are still there.

Nothing here decides anything on its own. An anchor that resolves to nothing
is recorded `unresolvable` and costs nothing; the rule that will read drift
(a `still_open` id whose cited code changed is refused) stays quiet on it.

Stdlib only, like the rest of the harness. git's blob id is computed here —
`sha1("blob <size>\\0" + bytes)` — so an uncommitted file anchors the same way
a committed one does and no subprocess runs per reference.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

# `src/pricer/money.py:14` — a path with an extension, a colon, a line number.
# Not a pytest node id (`::` — a colon is not a digit), not a URL (the
# lookbehind refuses a reference that starts right after `/`, `.` or `:`,
# which is where `//host:8080/x.py` would otherwise match), not a time of
# day; `path:line:col` reads as `path:line`.
_REF = re.compile(r"(?<![\w/.\\:-])((?:[\w.-]+[/\\])*[\w.-]+\.[A-Za-z0-9_]+):(\d+)(?!\d)")
MAX_REFS = 20          # per finding: evidence is prose and can run long
DRIFTED = ("moved", "changed", "missing")
_SEVERITY = {"unchanged": 0, "moved": 1, "changed": 2, "missing": 3}


def refs_in(texts) -> list[tuple[str, int]]:
    """Every `path:line` in the given strings, first occurrence first, capped."""
    seen, out = set(), []
    for text in texts:
        for m in _REF.finditer(str(text)):
            ref = (m.group(1).replace("\\", "/"), int(m.group(2)))
            if ref in seen:
                continue
            seen.add(ref)
            out.append(ref)
            if len(out) >= MAX_REFS:
                return out
    return out


def blob_sha(data: bytes) -> str:
    """git's own object id for a file's content — an anchor on a committed
    file equals `git rev-parse HEAD:<path>`, and an uncommitted one hashes
    the same way."""
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def line_sha(line: bytes) -> str:
    return hashlib.sha256(line.rstrip(b"\r\n")).hexdigest()[:16]


def _file(repo: Path, path: str) -> Path | None:
    """The file a reference names, or None when it is not a file inside the
    repository — a reference is text, and text can name anything."""
    try:
        root = repo.resolve()
        p = (root / path).resolve()
    except OSError:
        return None
    if p != root and root not in p.parents:
        return None
    return p if p.is_file() else None


def anchor(repo: Path, path: str, line: int) -> dict:
    ref = f"{path}:{line}"
    p = _file(repo, path)
    if p is None:
        return {"ref": ref, "status": "unresolvable",
                "reason": "no such file in the repository"}
    data = p.read_bytes()
    lines = data.splitlines()
    if line < 1 or line > len(lines):
        return {"ref": ref, "status": "unresolvable",
                "reason": f"line {line} is beyond the end of the file ({len(lines)} lines)"}
    return {"ref": ref, "path": path, "line": line,
            "blob": blob_sha(data)[:12], "line_sha": line_sha(lines[line - 1])}


def anchors_for(repo: Path, texts) -> list[dict]:
    return [anchor(repo, path, line) for path, line in refs_in(texts)]


def drift_of(repo: Path, anchors) -> dict:
    """Re-measure a list of anchors → `{drift, refs[]}`. `drift` is the worst
    of the resolvable references, or `unresolvable` when none was."""
    refs = []
    for a in anchors or []:
        if not isinstance(a, dict) or not a.get("ref"):
            continue
        if a.get("status") == "unresolvable" or not a.get("path"):
            refs.append({"ref": a["ref"], "status": "unresolvable"})
            continue
        p = _file(repo, str(a["path"]))
        if p is None:
            refs.append({"ref": a["ref"], "status": "missing"})
            continue
        data = p.read_bytes()
        if blob_sha(data)[:12] == a.get("blob"):
            refs.append({"ref": a["ref"], "status": "unchanged"})
            continue
        lines = data.splitlines()
        n = int(a.get("line") or 0)
        want = a.get("line_sha")
        if 1 <= n <= len(lines) and line_sha(lines[n - 1]) == want:
            # The file changed elsewhere; the cited line is where it was.
            refs.append({"ref": a["ref"], "status": "unchanged", "file_changed": True})
            continue
        hits = [i + 1 for i, ln in enumerate(lines) if line_sha(ln) == want]
        if hits:
            now = min(hits, key=lambda i: abs(i - n))
            refs.append({"ref": a["ref"], "status": "moved", "now_line": now})
        else:
            refs.append({"ref": a["ref"], "status": "changed"})
    resolvable = [r for r in refs if r["status"] != "unresolvable"]
    if not resolvable:
        return {"drift": "unresolvable", "refs": refs}
    worst = max(resolvable, key=lambda r: _SEVERITY[r["status"]])
    return {"drift": worst["status"], "refs": refs}


def evidence_drift(repo: Path, open_findings, accepted_findings, intact) -> dict | None:
    """The fact `verdict-facts` writes from the previous state's anchors.

    `intact` is a list of `(text, anchors)` pairs for the verified-intact
    items. Returns None when the previous state carries no anchors at all — a
    state written by a finalize older than this module — so a reader can tell
    "nothing drifted" from "nothing was measured".
    """
    findings, accepted, intact_out = {}, {}, []
    anchored = 0
    for bucket, src in ((findings, open_findings), (accepted, accepted_findings)):
        for f in src or []:
            if not isinstance(f, dict) or not f.get("anchors") or not f.get("id"):
                continue
            anchored += 1
            bucket[str(f["id"])] = drift_of(repo, f["anchors"])
    for text, anchors in intact or []:
        if not anchors:
            continue
        anchored += 1
        intact_out.append({"text": str(text)[:120], **drift_of(repo, anchors)})
    if not anchored:
        return None
    return {
        "status": "measured",
        "findings": findings,
        "accepted": accepted,
        "verified_intact": intact_out,
        "summary": {
            "drifted_findings": [k for k, v in findings.items() if v["drift"] in DRIFTED],
            "drifted_accepted": [k for k, v in accepted.items() if v["drift"] in DRIFTED],
            "drifted_intact": [i for i, v in enumerate(intact_out) if v["drift"] in DRIFTED],
        },
    }
