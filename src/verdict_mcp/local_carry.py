"""Every prior finding is mentioned: drift, measured resolutions, carried and refiled
findings, and the invariant that none silently disappears.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from .state import norm_status
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import norm_status


# ── every prior finding is mentioned ──────────────────────────────────────────
#
# This is the safety-critical half of a local delta, and the reason 0.88.0's
# local mode was only ever safe over a fresh project. It wrote `still_open: []`,
# and `merge()`'s silence rule reads an unmentioned finding as resolved unless
# five or more AND over half the backlog went quiet at once. A key with four
# open findings therefore lost all four to a run that never looked at them, and
# a key with sixty lost the ten whose code had drifted. Silence is not a verdict
# and this engine is never allowed to speak it: every prior open finding leaves
# here in exactly one of three places, and the invariant below is asserted
# before anything is finalized.


_CARRY_FIELDS = ("id", "title", "severity", "priority", "failure_classification",
                 "root_cause")


def drift_of(facts: dict, fid: str) -> tuple:
    """(worst drift, the refs that moved) for one finding, from `evidence_drift`."""
    drift = facts.get("evidence_drift") if isinstance(facts.get("evidence_drift"), dict) else {}
    rec = (drift.get("findings") or {}).get(str(fid))
    if not isinstance(rec, dict):
        return "", []
    moved = [str(r.get("ref")) for r in rec.get("refs") or []
             if isinstance(r, dict) and r.get("status") in ("changed", "missing")]
    return str(rec.get("drift") or ""), moved


def measured_resolution(facts: dict, fid: str) -> dict | None:
    """The one record that closes a finding with no model in the room: its cited
    test failed at the previous commit and passes at HEAD, on a test somebody
    chose — `explicit`, or collected for the first time this run.

    A test that merely passes at HEAD proves nothing: it may never have
    demonstrated the defect at all. `harness._chosen` draws the same line for the
    agent, and this engine gets no weaker rule because it is cheaper.
    """
    rec = (facts.get("verification") or {}).get(str(fid))
    if not isinstance(rec, dict):
        return None
    if rec.get("at_previous") != "fail" or rec.get("at_head") != "pass":
        return None
    if rec.get("selected_by") not in ("explicit", "added_this_run"):
        return None
    return rec


def partition_prior(previous: dict | None, facts: dict) -> tuple:
    """Every prior open finding, sorted into the only three honest outcomes.

    A. a measured fix — the ONLY path to `resolved`;
    B. the cited code is where it was — carried by id, unread;
    C. the cited code changed or vanished — re-filed under its own id with the
       drift as a fresh evidence line, because `still_open` over changed code is
       refused by the harness (rightly: the evidence no longer says what the
       finding says) and silence would resolve it.

    → (resolved ids, still-open ids, [(prior finding, drift, moved refs)])
    """
    resolved, still_open, refile = [], [], []
    for f in (previous or {}).get("findings") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        if norm_status(f.get("status")) != "open" or f.get("source") == "hygiene":
            # accepted, resolved and withdrawn are the harness's to carry — and so is a
            # hygiene finding, which the scan re-measures every run
            continue
        fid = str(f["id"])
        drift, moved = drift_of(facts, fid)
        if measured_resolution(facts, fid):
            resolved.append(fid)
        elif drift in ("changed", "missing"):
            refile.append((f, drift, moved))
        else:
            still_open.append(fid)
    return resolved, still_open, refile


_REFILE_NARRATIVE = (
    "Carried by re-filing rather than by the words 'still open'. That is not this finding "
    "confirmed — it is the same claim standing over code nobody has read since, and the line "
    "added to its evidence says which measurement moved. A model run should read it before "
    "anyone acts on the severity above.")


def refiled_finding(prior: dict, note: str, collected, narrative=_REFILE_NARRATIVE) -> dict:
    """A prior finding, re-filed under its own id, with one measured line added.

    Everything the tester wrote is copied verbatim; the one thing added is `note`,
    which says in measured terms what changed and that nothing read it this run.
    No `confidence` — the claim was made once and `merge` freezes it — and
    `verification_test` survives only while the collector still knows that id.
    """
    entry = {k: json.loads(json.dumps(prior[k])) for k in _CARRY_FIELDS if k in prior}
    entry["status"] = "open"
    entry["evidence"] = [str(e) for e in (prior.get("evidence") or [])] + [note]
    test = prior.get("verification_test")
    if isinstance(test, str) and (collected is None
                                  or test.strip().replace("\\", "/") in collected):
        entry["verification_test"] = test
    entry["narrative"] = narrative
    return entry


def drift_note(drift: str, moved: list) -> str:
    where = ", ".join(moved[:5]) or "the cited lines"
    return (f"re-filed unread: the code this finding cites {drift} since the evidence above "
            f"was written ({where}) — measured by verdict-facts' anchors; no model read the "
            "new code this run")


def carry_invariant(prior_open: list, resolved: list, still_open: list, filed_ids) -> list:
    """Every prior open id must leave this run in one of the three places, or the
    run does not finalize. Asserted rather than trusted: the failure it guards is
    silent by construction — a finding that nobody mentions becomes RESOLVED in a
    state file nobody re-reads."""
    accounted = set(resolved) | set(still_open) | set(filed_ids)
    missing = [fid for fid in prior_open if fid not in accounted]
    return missing
