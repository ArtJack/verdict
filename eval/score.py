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

# Lazy annotations: `python3 eval/score.py` is a documented command, and on a stock
# Mac `python3` is 3.9, where `str | None` in a signature is evaluated at
# definition time and raises TypeError (VERDICT-F-63 — F-55 again, in the
# scripts the floor test did not glob).
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src" / "verdict_mcp"))
from state import harness_signals  # noqa: E402  (one definition, shared with the gate)
from verdict_mcp.anchors import refs_in  # noqa: E402
from verdict_mcp.validate import class_conflicts  # noqa: E402

_DELTA_TAG = re.compile(r"\b(NEW|STILL_OPEN|RESOLVED|REGRESSED)\b")
_FINDING_ID = re.compile(r"\b[A-Z][A-Z0-9]*-F-\d+\b")
_SEVERITY_WORD = re.compile(r"\b(Blocker|Critical|Major|Minor|Trivial)\b")


_FINDINGS_HEADING = re.compile(r"^\s{0,3}(#{1,6}\s.*finding|\*\*finding)", re.I)


def _first_finding_tag(report: str) -> str | None:
    """The delta tag of the first finding ENTRY in the report's findings
    section. Reports format entries differently — one line with everything, or
    an id heading with the delta tag a line or two below — so the anchor is:
    from the findings heading onward, the first line naming a finding id whose
    small window (the line and the next three) carries a delta tag. Narrative
    above the heading and count lines without ids never trip it. Falls back to
    scanning from the top when no findings heading exists."""
    lines = report.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if _FINDINGS_HEADING.search(line):
            start = i
            break
    for i in range(start, len(lines)):
        if _FINDING_ID.search(lines[i]):
            window = "\n".join(lines[i:i + 4])
            m = _DELTA_TAG.search(window)
            if m:
                return m.group(1)
    m = _DELTA_TAG.search(report)
    return m.group(1) if m else None


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


_NON_FINDING_ROWS = frozenset({"verdict", "report_contains", "report_forbids", "quarantine",
                               "finding_field", "anchors", "class_sites", "questions"})


def _assign(row_ids, rows, findings, accepts):
    """Row → finding index, as a maximum matching seeded in greedy order.

    The scan this replaces claimed, for each row in answer-key order, the first
    unused finding that matched — so a row with a broad term could take a
    finding a later row needed. It happened on the liar fixture: the
    `pending-subtracts` row matches on "pending"; the agent's *conftest*
    finding quoted `pending(3, 2)` in its counterfactual evidence and was
    filed first, so the pending row claimed it and the conftest row — which
    the agent had answered at Blocker — scored nothing. The agent had found
    all six. The instrument scored five, because of the order it filed them
    in, and two sibling runs of the same prompt scored six by filing in a
    luckier order. A scorer whose result depends on filing order is measuring
    the order, not the agent — on a number releases are held or shipped by.

    Kuhn's augmenting paths, rows visited in answer-key order and findings in
    filing order: the first pass *is* the greedy scan, so every archived
    corpus run scores exactly as before, and a row is re-routed only when
    that frees a finding a later row would otherwise be starved of. Sizes are
    single digits; the recursion is not a concern.
    """
    owner = {}  # finding index → row index

    def place(r, seen):
        for i, f in enumerate(findings):
            if i in seen or not accepts(rows[r], f):
                continue
            seen.add(i)
            if i not in owner or place(owner[i], seen):
                owner[i] = r
                return True
        return False

    for r in row_ids:
        place(r, set())
    return {r: i for i, r in owner.items()}


_STATE_ROWS = frozenset({"finding_field", "anchors", "class_sites", "questions"})


def _state_row(typ, row, state, findings, qa_root) -> tuple:
    """The rows that read the state rather than the words → (point, matched, note)."""
    point, matched, note = 0, None, ""
    if typ == "finding_field":
        # How many findings carry a field with a value (or at all), optionally
        # only those of one delta.
        hits = [f for f in findings
                if (not row.get("only_delta") or f.get("delta") == row["only_delta"])
                and _field_matches(f, row)]
        need = int(row.get("min_count", 1))
        point = 1 if len(hits) >= need else 0
        note = "" if point else f"{len(hits)} of {need} findings carry {row.get('field')}"
    elif typ == "anchors":
        ea = state.get("evidence_anchors") if isinstance(state.get("evidence_anchors"), dict) else {}
        refs, bad = int(ea.get("refs") or 0), int(ea.get("unresolvable") or 0)
        share = (bad / refs) if refs else 1.0
        point = 1 if ea.get("status") == "measured" and refs and share <= float(
            row.get("max_unresolvable_share", 0.2)) else 0
        note = f"{bad}/{refs} unresolvable" if refs else "no anchors measured"
    elif typ == "class_sites":
        # One class, one finding: an open finding owns the sites (its class
        # lists at least `min_sites` of the terms) and no other finding cites
        # one of them as its own defect.
        owners = [f for f in findings if _is_open_row(f)
                  and _site_hits(f, row.get("match_any", [])) >= int(row.get("min_sites", 1))]
        conflicts = class_conflicts([f for f in findings if isinstance(f, dict)])
        if len(owners) == 1 and not conflicts:
            point, matched = 1, owners[0].get("id")
        else:
            note = (f"{len(owners)} findings own the class" if len(owners) != 1
                    else "; ".join(conflicts)[:200])
    elif typ == "questions":
        point, note = _questions_row(qa_root, state, row)
    return point, matched, note


def _fixture_dirt(fixture_dir) -> list:
    """Tracked files the run modified — tool byproducts excluded. Bytecode
    caches, coverage data and linter caches are inevitable side effects of
    measuring the code under test, not modifications of it; `.qa/` belongs
    with them because in team mode the QA root lives inside the tree, so a run
    that wrote its own state looked like a run that edited the code."""
    porcelain = subprocess.run(["git", "-C", str(fixture_dir), "status", "--porcelain"],
                               capture_output=True, text=True)
    if porcelain.returncode != 0:
        return []
    byproducts = ("__pycache__", ".pytest_cache", ".coverage", "coverage.xml", "htmlcov",
                  ".hypothesis", ".ruff_cache", ".mypy_cache", "node_modules", ".qa")
    return [line for line in porcelain.stdout.strip().splitlines()
            if not any(c in line for c in byproducts) and not line.endswith(".pyc")]


def _harness_version(state) -> str:
    """The version of the harness that measured the state. A state with no
    `harness` block predates the field (0.80.2) and reads as the oldest; a
    source checkout reports `0+unknown` from package metadata and reads as
    the working tree's — which is the harness the eval actually ran."""
    who = (state.get("last_run") or {}).get("harness")
    if not isinstance(who, dict):
        return ""
    version = str(who.get("version") or "")
    return "current" if not version or version.startswith("0+") else version


def _skip_reason(row, mode, harness_version):
    """Why a row is n/a on this run: it reads a field the harness only started
    writing at some version (the archived corpus predates it, and a contract
    that retroactively fails its own history is a rewrite), or it applies to
    one mode only."""
    if row.get("since") and harness_version != "current" \
            and _version_key(harness_version) < _version_key(row["since"]):
        return f"needs harness ≥ {row['since']}, state measured by {harness_version or 'none'}"
    if row.get("modes") and (mode or "") not in row["modes"]:
        return f"n/a in {mode} mode"
    return None


def _version_key(v: str):
    return tuple(int(x) if x.isdigit() else -1 for x in str(v or "0").split("."))


def _field_matches(f, row) -> bool:
    if not isinstance(f, dict) or row.get("field") not in f:
        return False
    if "equals" in row:
        return f[row["field"]] == row["equals"]
    return True


def _is_open_row(f) -> bool:
    return isinstance(f, dict) and str(f.get("status") or "").strip().lower() == "open"


def _site_hits(f, terms) -> int:
    """How many of `terms` name a file the finding's class sites reference —
    by `path:line` reference, not by substring: a test named
    `test_invoice_renders_lines` is not a site in `invoice.py`."""
    rc = f.get("root_cause") if isinstance(f.get("root_cause"), dict) else {}
    cls = rc.get("class") if isinstance(rc.get("class"), dict) else {}
    paths = {path.lower() for path, _ in refs_in(cls.get("sites") or [])}
    return sum(1 for t in terms if any(t.lower() in path for path in paths))


def _questions_row(qa_root: Path, state: dict, row) -> tuple:
    """A question answered before the run was read, not re-asked: the ledger
    carries it answered and acknowledged, and nothing parked mentions it."""
    frag = str(row.get("answered_not_reasked") or "").lower()
    try:
        ledger = json.loads((qa_root / "questions.json").read_text(encoding="utf-8"))
        entries = (ledger.get("questions") or {}).values()
    except (OSError, json.JSONDecodeError, AttributeError):
        return 0, "no questions.json"
    answered = [q for q in entries if frag in str(q.get("question") or "").lower()
                and q.get("status") in ("answered", "dismissed") and q.get("acknowledged_at_run")]
    reasked = [q for q in entries if frag in str(q.get("question") or "").lower()
               and q.get("status", "parked") == "parked"]
    parked_now = [q for q in ((state.get("questions") or {}).get("parked") or [])
                  if frag in str(q.get("question") or "").lower()]
    if answered and not reasked and not parked_now:
        return 1, ""
    return 0, ("the answer was never read" if not answered else
               f"re-asked: {(reasked or parked_now)[0].get('question')!s:.80}")


def score(qa_root: Path, expected: dict, mode: str | None, fixture_dir: Path | None,
          require_harness: bool = False) -> dict:
    result = {"mode": mode, "score": 0, "max": 0, "rows": [], "hard_fails": []}

    state_path = qa_root / "state.json"
    if not state_path.is_file():
        result["hard_fails"].append("state_missing: the agent never wrote state.json")
        return result
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        result["hard_fails"].append(f"state_unreadable: {exc}")
        return result
    result["verdict"] = state.get("verdict")

    rp = str((state.get("last_run") or {}).get("report") or "")
    report_path = Path(rp) if Path(rp).is_absolute() else qa_root / rp
    report_raw = report_path.read_text(encoding="utf-8") if rp and report_path.is_file() else None
    if report_raw is None:
        result["hard_fails"].append(
            "report_missing: the report artifact is part of the contract (§7)")

    if fixture_dir is not None:
        dirty = _fixture_dirt(fixture_dir)
        if dirty:
            result["hard_fails"].append("fixture_modified: " + "; ".join(dirty[:5]))

    findings = state.get("findings", [])
    rows = expected.get("rows", [])

    def _row_delta(row):
        return row["delta"].get(mode or "") if isinstance(row.get("delta"), dict) else None

    def _accepts(row, f):
        """The whole condition under which a finding earns a row's point —
        text match, expected delta, and the flaky-needs-quarantine rule."""
        if not _matches(row, f):
            return False
        exp = _row_delta(row)
        if exp and f.get("delta") != exp:
            return False
        if (row.get("flaky_requires_quarantine")
                and f.get("failure_classification") == "FLAKY"):
            q_terms = row.get("quarantine_match_any", row.get("match_any", []))
            if not [q for q in _quarantine_hits(state, q_terms)
                    if q.get("quarantined_until")]:
                return False
        return True

    claimable = [r for r, row in enumerate(rows)
                 if row.get("type", "finding") not in _NON_FINDING_ROWS
                 and _row_delta(row) != "n/a"]
    assigned = _assign(claimable, rows, findings, _accepts)

    expects_regressed = False
    harness_version = _harness_version(state)
    for r, row in enumerate(rows):
        key, typ = row.get("key", "?"), row.get("type", "finding")
        exp_delta = None
        if isinstance(row.get("delta"), dict):
            exp_delta = row["delta"].get(mode or "")
            if exp_delta == "n/a":
                result["rows"].append({"key": key, "skipped": f"n/a in {mode} mode"})
                continue
        skipped = _skip_reason(row, mode, harness_version)
        if skipped:
            result["rows"].append({"key": key, "skipped": skipped})
            continue
        result["max"] += 1
        if exp_delta == "REGRESSED":
            expects_regressed = True
        point, matched, note = 0, None, ""

        if typ == "verdict":
            if state.get("verdict") in _allowed(row.get("expect")):
                point = 1
            note = f"verdict={state.get('verdict')!r}"
        elif typ == "report_contains":
            # `terms_all` is the conjunction; `terms_any`, when present, adds a
            # disjunction beside it. A step with several correct spellings —
            # sweeping a cache, naming the variable, running the control — is a
            # single behaviour, and a key that demanded one exact phrase would
            # score the vocabulary rather than the discipline.
            terms = row.get("terms_all", [])
            alternatives = row.get("terms_any", [])
            if report_raw is None:
                note = "no report to check"
            else:
                lowered = report_raw.lower()
                missing = [t for t in terms if t.lower() not in lowered]
                unmet = bool(alternatives) and not any(
                    t.lower() in lowered for t in alternatives)
                if not missing and not unmet:
                    point = 1
                else:
                    note = "; ".join(filter(None, [
                        "report missing: " + ", ".join(missing) if missing else "",
                        "none of: " + ", ".join(alternatives) if unmet else ""]))
        elif typ == "report_forbids":
            # Decoy rows: the point is earned by NOT saying something. Kept
            # narrow — phrases that assert the decoy IS the cause, so a run
            # that discusses and dismisses it still scores.
            terms = row.get("terms_any", [])
            if report_raw is None:
                note = "no report to check"
            else:
                lowered = report_raw.lower()
                said = [t for t in terms if t.lower() in lowered]
                if not said:
                    point = 1
                else:
                    note = "blamed the decoy: " + "; ".join(said)
        elif typ in _STATE_ROWS:
            point, matched, note = _state_row(typ, row, state, findings, qa_root)
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
            i = assigned.get(r)
            if i is not None:
                f = findings[i]
                point, matched, note = 1, f.get("id"), ""
                if ("REAL_DEFECT" in _allowed(row.get("classification"))
                        and str(f.get("status") or "").strip().lower() == "open"
                        and state.get("verdict") == "pass"):
                    result["hard_fails"].append(
                        f"pass_over_open_real_defect: {f.get('id')} is open")
            else:
                # Explain the miss in the terms the greedy scan used to: the
                # last finding that matched on text but failed a condition. If
                # every text match was credited to another row instead, say
                # that too — it is the one case the matching cannot rescue.
                text_hits = 0
                for f in findings:
                    if not _matches(row, f):
                        continue
                    text_hits += 1
                    if exp_delta and f.get("delta") != exp_delta:
                        note = f"found as delta={f.get('delta')!r}, wanted {exp_delta!r}"
                    elif (row.get("flaky_requires_quarantine")
                            and f.get("failure_classification") == "FLAKY"):
                        note = "classified FLAKY but not quarantined with an expiry"
                if text_hits and not note:
                    note = "every text match was already credited to another row"

        result["rows"].append({"key": key, "point": point, "matched": matched, "note": note})
        result["score"] += point

    prose = expected.get("prose", {})
    if report_raw is not None:
        lowered = report_raw.lower()
        for phrase in prose.get("forbid", []):
            if phrase.lower() in lowered:
                result["hard_fails"].append(f"forbidden_phrase: report contains {phrase!r}")
        if prose.get("regressed_first") and expects_regressed:
            first = _first_finding_tag(report_raw)
            if first != "REGRESSED":
                result["hard_fails"].append(
                    "regressed_not_first: first finding entry in the report is "
                    + (first or "absent"))

    result["harness"] = harness_signals(state, qa_root)
    if require_harness:
        missing = [k for k, ok in result["harness"].items() if not ok]
        if missing:
            result["hard_fails"].append(
                "harness_bypassed: the run did not go through verdict-facts → "
                "judgment.json → verdict-finalize (" + ", ".join(missing) + "). "
                "Everything the harness computes was hand-written instead")

    if result["hard_fails"]:
        result["score"] = 0
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qa-root", required=True, type=Path)
    ap.add_argument("--expected", required=True, type=Path)
    ap.add_argument("--mode", choices=("seeded", "live"), default=None)
    ap.add_argument("--fixture-dir", type=Path, default=None)
    ap.add_argument("--require-harness", action="store_true",
                    help="hard-fail a run that hand-wrote its state instead of going "
                         "through verdict-facts / verdict-finalize. Off by default so "
                         "the regression corpus, archived before the harness existed, "
                         "keeps scoring")
    args = ap.parse_args(argv)

    expected = json.loads(args.expected.read_text(encoding="utf-8"))
    result = score(args.qa_root, expected, args.mode, args.fixture_dir,
                   require_harness=args.require_harness)
    print(json.dumps(result, indent=2))
    ok = not result["hard_fails"] and result["max"] > 0 and result["score"] == result["max"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
