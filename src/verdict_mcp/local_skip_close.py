"""A finding the skip scan filed is settled by the skip scan, never by silence.

`local_skips.py` files a finding with no model in the room: a regular expression found a
skip marker with no expiry. No test fails at the previous commit and passes at HEAD for such
a finding, and that flip is the only measurement `local_carry` accepts for closing one, so a
skip finding used to stay open for good. Verdict's own record carried nine of them through
three runs after the scan that filed them was corrected (2026-10-16): the scan had stopped
filing them, and nothing ever asked it again.

So the scan is asked again. A prior open finding it filed leaves the open list only on what
this run measured about every line it cites:

- **found again** — the scan filed a skip at a cited line (where the anchor says that line is
  now, or where it was) or under the same identity: it stays where `partition_prior` put it.
- **withdrawn** — the scan read every cited file, filed nothing at the cited lines, and every
  cited line is the line it was (unchanged, or moved by an edit elsewhere): the same text no
  longer reads as a skip with no expiry, so the rule that filed it was wrong. Scored refuted,
  which is what a false positive costs.
- **withdrawn, outside the suite** — this run's test-id ledger was measured, every gate is
  green, the suite collects nothing under the cited file's top-level directory, and every
  cited line is still a decorator, which pytest collects and then skips. A `pytest.skip()`
  call can stop its whole file being collected, so a call never qualifies.
- **resolved** — the scan read every cited file and filed nothing, and a cited line changed
  (an expiry added, the skip removed); or every cited file is gone from the checkout. Absent
  by measurement, not fix-verified, so the outcome stays unknown.

Anything less — a file the scan could not read, a red gate, a ledger this run did not
measure — leaves the finding where it was.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path, PurePosixPath

try:
    from . import clock
    from .local_carry import _CARRY_FIELDS
    from .local_skips import SCAN_EVIDENCE, collected_test_files, skip_scan_files, skips_without_expiry
    from .local_verdict import gate_failed
    from .state import norm_status
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from local_carry import _CARRY_FIELDS
    from local_skips import SCAN_EVIDENCE, collected_test_files, skip_scan_files, skips_without_expiry
    from local_verdict import gate_failed
    from state import norm_status


# The lines `skip_finding` and `focus_finding` cite, one evidence line per marker:
# `tests/test_hooks.py:195 — skip marker with reason …`, `web/a.test.ts:4 — focus marker …`.
_SITE = re.compile(r"^(?P<path>[^\s:][^:]*):(?P<line>\d+) — (?:skip|focus) marker\b")
# Collected, then skipped. A `pytest.skip(..., allow_module_level=True)` call is not.
_DECORATOR = re.compile(r"^[ \t]*@")


class SkipScan:
    """One pass of the skip scan: the markers it found, and the files it actually read."""

    def __init__(self, repo: Path, qa_root: Path):
        self.read: set = set()
        self.skips = skips_without_expiry(repo, skip_scan_files(repo, qa_root), read=self.read)

    def hits(self) -> set:
        return {(s["path"], int(s["line"])) for s in self.skips}


def cited_sites(finding: dict) -> list:
    """[(path, line)] a skip-scan finding cites — [] for a finding the scan did not file."""
    evidence = [str(e) for e in finding.get("evidence") or []]
    if SCAN_EVIDENCE not in evidence:
        return []
    return [(m.group("path"), int(m.group("line"))) for m in map(_SITE.match, evidence) if m]


def _refs(facts: dict, fid: str) -> dict:
    """`path:line` → its re-measured anchor, from the `evidence_drift` verdict-facts wrote."""
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    rec = (drift.get("findings") or {}).get(fid)
    refs = rec.get("refs") if isinstance(rec, dict) else None
    return {str(r.get("ref")): r for r in refs or [] if isinstance(r, dict)}


def _now(site: tuple, refs: dict) -> tuple | None:
    """Where a cited line is now: its own line when unchanged, the anchor's new line when an
    edit elsewhere moved it, None when the line changed, went missing or was never anchored."""
    path, line = site
    ref = refs.get(f"{path}:{line}") or {}
    if ref.get("status") == "unchanged":
        return site
    if ref.get("status") == "moved" and ref.get("now_line"):
        return (path, int(ref["now_line"]))
    return None


def _outside_the_suite(paths: list, now: list, repo: Path, qa_root: Path, facts: dict) -> bool:
    """Every cited file sits under a top-level directory this run's suite collects nothing
    from, and every cited line is a decorator — so the file's absence from the ledger is the
    suite's shape, not a collection that broke or a module-level skip that hid it."""
    ids = facts.get("test_ids") if isinstance(facts.get("test_ids"), dict) else {}
    if ids.get("status") != "measured" or gate_failed(facts):
        return False
    collected = collected_test_files(repo, qa_root) or []
    if not collected:
        return False
    roots = {PurePosixPath(c).parts[0] for c in collected if len(PurePosixPath(c).parts) > 1}
    for path in paths:
        parts = PurePosixPath(path).parts
        if not path.endswith(".py"):
            return False  # the ledger is pytest's collection: it says nothing of a Jest or JUnit file
        if len(parts) < 2 or parts[0] in roots or path in collected:
            return False
    for path, line in now:
        try:
            lines = (repo / path).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return False
        if not 1 <= line <= len(lines) or not _DECORATOR.match(lines[line - 1]):
            return False
    return True


def settled_by_scan(previous: dict | None, scan: SkipScan, facts: dict, repo: Path,
                    qa_root: Path, refound: set) -> list:
    """Every prior open finding the skip scan filed and this run's scan settles
    → [(prior finding, "withdrawn" | "resolved", the evidence line that says why)]."""
    out, hits, today = [], scan.hits(), clock.today().isoformat()
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if norm_status(f.get("status")) != "open" or f.get("source") == "hygiene":
            continue
        fid, sites = str(f["id"]), cited_sites(f)
        if not sites or fid in refound:
            continue
        refs = _refs(facts, fid)
        now = [_now(site, refs) for site in sites]
        if any(site in hits for site in sites) or any(n in hits for n in now if n):
            continue  # found again, where the line is or where it was
        paths = sorted({path for path, _line in sites})
        named = ", ".join(paths)
        if all(path in scan.read for path in paths):
            if all(now):
                out.append((f, "withdrawn",
                            f"withdrawn by the skip scan {today}: it read {named} again and files "
                            "nothing at the cited lines, which are as they were — the same text "
                            "no longer reads as a skip with no expiry, so the rule that filed "
                            "this was wrong"))
            else:
                out.append((f, "resolved",
                            f"resolved by the skip scan {today}: it read {named} again and files "
                            "nothing at the cited lines, which changed since this was filed — "
                            "absent by measurement, not fix-verified"))
        elif not any((repo / path).exists() for path in paths):
            out.append((f, "resolved",
                        f"resolved by the skip scan {today}: {named} is no longer in the "
                        "checkout — absent by measurement, not fix-verified"))
        elif all(now) and _outside_the_suite(paths, now, repo, qa_root, facts):
            out.append((f, "withdrawn",
                        f"withdrawn by the skip scan {today}: the suite collects nothing under "
                        f"the top-level directory of {named} (this run's test-id ledger, every "
                        "gate green), and each cited line is a decorator, which pytest collects "
                        "and then skips — a skip outside the suite removes no coverage it has"))
    return out


_CLOSED_NARRATIVE = {
    "withdrawn": "The skip scan that filed this read the same lines again and no longer files "
                 "them. The finding was a false positive of the rule as it then stood, and it "
                 "stays on the record as one.",
    "resolved": "The skip scan read the cited files again and filed nothing where this finding "
                "points. That is absence measured by the scan, not a verified fix.",
}


def closed_finding(prior: dict, status: str, note: str) -> dict:
    """The prior finding, re-filed under its own id as `status`, with `note` as the line that
    says what was measured. Everything the scan wrote first is copied verbatim."""
    entry = {k: json.loads(json.dumps(prior[k])) for k in _CARRY_FIELDS if k in prior}
    entry["status"] = status
    if status == "withdrawn":
        entry["delta"] = "WITHDRAWN"
    entry["evidence"] = [str(e) for e in prior.get("evidence") or []] + [note]
    entry["narrative"] = _CLOSED_NARRATIVE[status]
    return entry


def close_by_scan(previous: dict | None, scan: SkipScan, facts: dict, repo: Path, qa_root: Path,
                  on_record: list, still_open_ids: list, to_refile: list, file) -> list:
    """Settle what the scan settles. `file(entry, into)` is the run's own `mint`; an id leaves
    `still_open_ids` or `to_refile` only once its record was written, so a closure the
    validator refuses stays exactly where `partition_prior` put it. → the entries written."""
    eligible = set(still_open_ids).union(str(prior.get("id")) for prior, _drift, _moved in to_refile)
    refound = {str(fid) for fid, _status in on_record}
    closed: list = []
    for prior, status, note in settled_by_scan(previous, scan, facts, repo, qa_root, refound):
        fid = str(prior["id"])
        if fid not in eligible:
            continue
        before = len(closed)
        file(closed_finding(prior, status, note), closed)
        if len(closed) > before:
            if fid in still_open_ids:
                still_open_ids.remove(fid)
            to_refile[:] = [t for t in to_refile if str(t[0].get("id")) != fid]
            print(f"verdict-local: {fid} {status} by the skip scan", file=sys.stderr)
    return closed


def closed_text(closed: list) -> str:
    """One sentence for the report's notes, empty when the scan settled nothing."""
    if not closed:
        return ""
    by = {s: [str(f["id"]) for f in closed if f.get("status") == s] for s in ("withdrawn", "resolved")}
    parts = [f"{s} {', '.join(ids)}" for s, ids in by.items() if ids]
    return (" The skip scan read again what it had filed, and settled what it measured: "
            + "; ".join(parts) + ".")
