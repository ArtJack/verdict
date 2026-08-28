#!/usr/bin/env python3
"""Deterministic scorer for Verdict's eval fixtures.

Scores the STATE FILE, not the prose: the state schema is the interface —
findings carry `failure_classification`, `delta`, and `evidence[]`, and free
prose is unscoreable without judgment. Exactly two prose checks run against
the report file: the forbidden-phrase check ("no bugs found" is an automatic
fail) and, when the answer key demands it, that the first delta tag the report
mentions is REGRESSED.

Usage:
    python3 eval/score.py --qa-root <dir> --expected eval/expected.json \
        [--mode seeded|live] [--fixture-dir <dir>]

Output: one JSON object on stdout. Exit 0 iff every scored row earned its
point and no hard-fail tripped. Hard fails zero the whole score — a run that
modified the fixture, skipped the state file or report, or called `pass` over
an open expected REAL_DEFECT has failed regardless of rows found.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

_DELTA_TAG = re.compile(r"\b(NEW|STILL_OPEN|RESOLVED|REGRESSED)\b")


def _finding_text(finding) -> str:
    parts = [str(finding.get("title", ""))]
    parts += [str(e) for e in finding.get("evidence", [])]
    return " ".join(parts).lower()


def _any_term(terms, text: str) -> bool:
    return any(t.lower() in text for t in terms)


def _allowed(value):
    return [value] if isinstance(value, str) else list(value or [])


def _matches(row, finding) -> bool:
    if not _any_term(row.get("match_any", []), _finding_text(finding)):
        return False
    want = row.get("classification")
    if want and finding.get("failure_classification") not in _allowed(want):
        return False
    req = row.get("require_evidence_any")
    if req:
        ev = " ".join(str(e) for e in finding.get("evidence", [])).lower()
        if not _any_term(req, ev):
            return False
    sev = row.get("require_severity_any")
    if sev and finding.get("severity") not in sev:
        return False
    return True


def _quarantine_hits(state, terms):
    return [
        q for q in state.get("flaky_quarantine", [])
        if _any_term(terms, str(q.get("test_id", "")).lower())
    ]


def score(qa_root: Path, expected: dict, mode: str | None, fixture_dir: Path | None) -> dict:
    result = {"mode": mode, "score": 0, "max": 0, "rows": [], "hard_fails": []}

    state_path = qa_root / "state.json"
    if not state_path.is_file():
        result["hard_fails"].append("state_missing: the agent never wrote state.json")
        return result
    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        result["hard_fails"].append(f"state_unreadable: {exc}")
        return result
    result["verdict"] = state.get("verdict")

    rp = str((state.get("last_run") or {}).get("report") or "")
    report_path = Path(rp) if Path(rp).is_absolute() else qa_root / rp
    report_raw = report_path.read_text() if rp and report_path.is_file() else None
    if report_raw is None:
        result["hard_fails"].append(
            "report_missing: the report artifact is part of the contract (§7)")

    if fixture_dir is not None:
        porcelain = subprocess.run(
            ["git", "-C", str(fixture_dir), "status", "--porcelain"],
            capture_output=True, text=True)
        if porcelain.returncode == 0 and porcelain.stdout.strip():
            dirty = porcelain.stdout.strip().splitlines()[:5]
            result["hard_fails"].append("fixture_modified: " + "; ".join(dirty))

    findings = state.get("findings", [])
    used = set()
    expects_regressed = False
    for row in expected.get("rows", []):
        key, typ = row.get("key", "?"), row.get("type", "finding")
        exp_delta = None
        if isinstance(row.get("delta"), dict):
            exp_delta = row["delta"].get(mode or "")
            if exp_delta == "n/a":
                result["rows"].append({"key": key, "skipped": f"n/a in {mode} mode"})
                continue
        result["max"] += 1
        if exp_delta == "REGRESSED":
            expects_regressed = True
        point, matched, note = 0, None, ""

        if typ == "verdict":
            if state.get("verdict") in _allowed(row.get("expect")):
                point = 1
            note = f"verdict={state.get('verdict')!r}"
        elif typ == "quarantine":
            hits = _quarantine_hits(state, row.get("match_any", []))
            if row.get("expect_absent"):
                point = 1 if not hits else 0
                note = "" if point else f"still quarantined: {hits[0].get('test_id')}"
            else:
                ok = [q for q in hits if q.get("quarantined_until")]
                if ok:
                    point, matched = 1, ok[0].get("test_id")
                elif hits:
                    note = "quarantine entry has no expiry"
        else:
            for i, f in enumerate(findings):
                if i in used or not _matches(row, f):
                    continue
                if exp_delta and f.get("delta") != exp_delta:
                    note = f"found as delta={f.get('delta')!r}, wanted {exp_delta!r}"
                    continue
                if (row.get("flaky_requires_quarantine")
                        and f.get("failure_classification") == "FLAKY"):
                    q_terms = row.get("quarantine_match_any", row.get("match_any", []))
                    if not [q for q in _quarantine_hits(state, q_terms)
                            if q.get("quarantined_until")]:
                        note = "classified FLAKY but not quarantined with an expiry"
                        continue
                used.add(i)
                point, matched, note = 1, f.get("id"), ""
                if ("REAL_DEFECT" in _allowed(row.get("classification"))
                        and f.get("status") == "open"
                        and state.get("verdict") == "pass"):
                    result["hard_fails"].append(
                        f"pass_over_open_real_defect: {f.get('id')} is open")
                break

        result["rows"].append({"key": key, "point": point, "matched": matched, "note": note})
        result["score"] += point

    prose = expected.get("prose", {})
    if report_raw is not None:
        lowered = report_raw.lower()
        for phrase in prose.get("forbid", []):
            if phrase.lower() in lowered:
                result["hard_fails"].append(f"forbidden_phrase: report contains {phrase!r}")
        if prose.get("regressed_first") and expects_regressed:
            first = _DELTA_TAG.search(report_raw)
            if not first or first.group(1) != "REGRESSED":
                result["hard_fails"].append(
                    "regressed_not_first: first delta tag in the report is "
                    + (first.group(1) if first else "absent"))

    if result["hard_fails"]:
        result["score"] = 0
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qa-root", required=True, type=Path)
    ap.add_argument("--expected", required=True, type=Path)
    ap.add_argument("--mode", choices=("seeded", "live"), default=None)
    ap.add_argument("--fixture-dir", type=Path, default=None)
    args = ap.parse_args(argv)

    expected = json.loads(args.expected.read_text())
    result = score(args.qa_root, expected, args.mode, args.fixture_dir)
    print(json.dumps(result, indent=2))
    ok = not result["hard_fails"] and result["max"] > 0 and result["score"] == result["max"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
