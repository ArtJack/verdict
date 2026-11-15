"""Merging a judgment into the stored state: the findings, their outcomes, the carried and
the accepted ones, and the keys that belong to one run only.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

try:
    from .anchors import anchors_for
    from .hygiene import (is_hygiene, leads_followed, ledger as hygiene_ledger,
                          reconcile as reconcile_hygiene)
    from .state import calibration, in_force, is_open, merge_outcomes, norm_status
    from .facts_verify import _apply_verification
    from .hygiene_facts import hygiene_evidence, hygiene_previous, tier2_items
    from .finalize_ids import (_anchor, _earlier_hygiene, _introduce, _suggest_tests, finding_hash,
                               next_finding_id)
    from .finalize_carry import (CARRY_RESOLVE_FLOOR, CARRY_RESOLVE_SHARE, READ_FIRST_ACCOUNTED,
                                 _apply_replay, _fold_accepted, _stamp_outcome,
                                 read_first_accounting, run_date)
    from .finalize_write import _ignored_hygiene_ids
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from anchors import anchors_for
    from hygiene import (is_hygiene, leads_followed, ledger as hygiene_ledger,
                         reconcile as reconcile_hygiene)
    from state import calibration, in_force, is_open, merge_outcomes, norm_status
    from facts_verify import _apply_verification
    from hygiene_facts import hygiene_evidence, hygiene_previous, tier2_items
    from finalize_ids import (_anchor, _earlier_hygiene, _introduce, _suggest_tests, finding_hash,
                              next_finding_id)
    from finalize_carry import (CARRY_RESOLVE_FLOOR, CARRY_RESOLVE_SHARE, READ_FIRST_ACCOUNTED,
                                _apply_replay, _fold_accepted, _stamp_outcome,
                                read_first_accounting, run_date)
    from finalize_write import _ignored_hygiene_ids


# State keys that describe one run and must not be carried into the next one.
RUN_SCOPED_KEYS = ("run_label",)


def merge(facts: dict, judgment: dict, previous: dict | None, today: date | None = None,
          ledger: dict | None = None, accepted: dict | None = None, qa_root=None) -> dict:
    """Facts + judgment → a state file, with identity and deltas computed.

    `ledger` is the permanent outcome ledger (`outcomes.json`); passing it in
    keeps this function pure while letting the calibration block count every
    finding this project ever filed, not just the ones still in state.
    `accepted` is the maintainer's ledger (`accepted.json`), applied after the
    tester's statuses and before outcomes: the one status a judgment cannot
    write. `qa_root` is where the hygiene side file sits (default: the one
    facts.json names).
    """
    today = today or run_date(facts)
    # finalize runs from the QA root; facts says where the code is. An older
    # facts.json names no repo, and then nothing is anchored — said in the
    # state, never silently.
    repo_path = facts.get("repo")
    repo = Path(repo_path) if repo_path and Path(repo_path).is_dir() else None
    measured_at = str(facts.get("measured_at")
                      or (facts.get("last_run") or {}).get("timestamp_utc") or "") or None
    prev_by_hash, prev_by_id = {}, {}
    for f in ((previous or {}).get("findings") or []):
        if f.get("hash"):
            prev_by_hash[str(f["hash"])] = f
        if f.get("id"):
            prev_by_id[str(f["id"])] = f

    findings = []
    seen = set()
    for f in judgment.get("findings", []) or []:
        if is_hygiene(f):
            continue  # a `still_open` copy of the harness's own finding — reconciled below
        entry = dict(f)
        h = finding_hash(entry)
        prior = prev_by_hash.get(h)
        if prior is None:
            # Fall back to the id. The hash is a *content fingerprint* — cited
            # path plus normalized title — and it drifts the moment the tester
            # rewords its own finding, which it does constantly as evidence
            # accumulates. The id does not drift: §6 mints it once and forbids
            # reuse, so a re-reported id is a deliberate identity claim.
            #
            # Without this, a reworded re-report is filed as NEW *and* carried
            # forward as resolved — two entries, one id, and a state the
            # validator rightly refuses to write. Every hash in four live
            # projects was hand-authored before the harness existed and matches
            # nothing computable, so without the fallback no project could ever
            # take its first harness-driven run.
            prior = prev_by_id.get(str(entry.get("id") or ""))
            if prior is not None and prior.get("hash"):
                h = str(prior["hash"])  # identity is continuous; the fingerprint moved
        entry["hash"] = h
        seen.add(h)
        first_seen = (prior or {}).get("first_seen") or today.isoformat()
        entry["first_seen"] = first_seen
        try:
            entry["age_days"] = (today - date.fromisoformat(str(first_seen))).days
        except ValueError:
            entry["age_days"] = 0
        status = norm_status(entry.get("status", "open")) or "open"
        entry["status"] = status
        if entry.get("delta") == "WITHDRAWN":
            # The tester's own correction; the delta is never overwritten, and
            # the status follows from it — a finding that was never real cannot
            # also be open, and left to drift it would keep counting toward
            # blockers it has already been retracted from.
            entry["status"] = status = "withdrawn"
        elif prior is None:
            entry["delta"] = "NEW"
        elif status == "resolved":
            entry["delta"] = "RESOLVED"
        elif prior.get("status") == "resolved":
            entry["delta"] = "REGRESSED"
        else:
            entry["delta"] = "STILL_OPEN"

        # When a finding came back, recorded once and carried forever after.
        # `delta` describes only the transition this run computed, so a
        # regression was visible for exactly one run: anything downstream that
        # did not look on that run — `verdict-issues` filing a recurrence, for
        # one — could never learn it happened (VERDICT-F-34).
        if entry["delta"] == "REGRESSED":
            entry["regressed_at_run"] = facts.get("run_number")
        elif prior and prior.get("regressed_at_run") is not None:
            entry["regressed_at_run"] = prior["regressed_at_run"]

        # The claim is frozen at filing. Calibration scores a prediction, and a
        # confidence revised after the outcome is known is hindsight wearing a
        # prediction's clothes.
        if prior and prior.get("confidence"):
            entry["confidence"] = prior["confidence"]
        _fold_accepted(entry, accepted)
        _apply_verification(entry, prior, facts.get("verification") or {}, measured_at)
        _apply_replay(entry, prior, facts.get("replay") or {}, measured_at)
        _introduce(entry, prior, repo)
        if repo is not None:
            _anchor(entry, prior, repo, facts.get("run_number"))
        _suggest_tests(entry, facts)
        entry.update(_stamp_outcome(entry, prior))
        findings.append(entry)

    # A finding the previous run had and this run did not mention is resolved —
    # silence is not the same as an assertion, so it is carried, not dropped.
    unmentioned, prior_open = [], 0
    for h, prior in prev_by_hash.items():
        if is_hygiene(prior):
            continue  # owned by the harness: re-measured below, never resolved by silence
        st = norm_status(prior.get("status"))
        # The maintainer's decision outlives the tester's attention: a finding
        # that is accepted — in the previous state, or in the ledger since —
        # is not part of the open backlog whose silence the guardrail below
        # weighs, and it is never resolved by silence. It stays accepted, or
        # comes back open if the ledger says the acceptance was revoked.
        maintainers = st == "accepted" or (
            st == "open" and in_force((accepted or {}).get(str(prior.get("id") or ""))))
        if st == "open" and not maintainers:
            prior_open += 1
        if h in seen:
            continue
        if st == "withdrawn":
            # A withdrawal is the tester's own error record. Resolutions age out
            # of state into the reports and the ledger; this one stays visible,
            # because a tester that files a false positive and lets it fall off
            # the page next run is hiding the number that weighs all the others.
            findings.append({k: v for k, v in prior.items() if k != "re_reported"})
            continue
        if maintainers:
            carried = {k: v for k, v in prior.items() if k != "re_reported"}
            _fold_accepted(carried, accepted)
            carried.update(_stamp_outcome(carried, prior))
            findings.append(carried)
            continue
        if st == "resolved":
            continue
        unmentioned.append(prior)

    # One decision for the whole set: whether this run's silence is credible as
    # resolution at all. Judged on the incoming open backlog, not on what came
    # back, because the question is how much of it this run actually looked at.
    held = (not judgment.get("full_sweep")
            and len(unmentioned) >= CARRY_RESOLVE_FLOOR
            and len(unmentioned) > CARRY_RESOLVE_SHARE * prior_open)
    for prior in unmentioned:
        carried = {k: v for k, v in prior.items() if k != "re_reported"}
        if held:
            carried.update(
                status="open", delta="STILL_OPEN",
                carried_forward=(
                    f"not reported this run, and not resolved: {len(unmentioned)} of "
                    f"{prior_open} open findings went unmentioned, which reads as a "
                    "scoped run rather than that many fixes — held open. Re-report "
                    "it, resolve it explicitly, or declare full_sweep."))
        else:
            carried.update(status="resolved", delta="RESOLVED",
                           carried_forward="not reported this run; no longer observed")
        # Silence is not verification — but measurement is. A finding nobody
        # re-reported proves nothing by itself; its cited test, re-run at both
        # commits, can still settle it either way.
        _apply_verification(carried, prior, facts.get("verification") or {}, measured_at)
        _apply_replay(carried, prior, facts.get("replay") or {}, measured_at)
        _suggest_tests(carried, facts)
        carried.update(_stamp_outcome(carried, prior))
        findings.append(carried)

    # Hygiene findings are the harness's own (T-28): re-measured every run, resolved
    # only on evidence — every file the item lives in was scanned, or has left the
    # tree — and never by the tester's silence.
    hyg = facts.get("hygiene")
    root = Path(qa_root or facts.get("qa_root") or ".")
    sha_now = str((facts.get("last_run") or {}).get("git_sha") or "")
    # The side file is read only as this facts run's own (`_side_doc`).
    bind = {"git_sha": (facts.get("last_run") or {}).get("git_sha"),
            "measured_at": facts.get("measured_at")}
    evidence = hygiene_evidence(hyg, root, repo, sha_now, bind)
    taken = [{"id": f.get("id")} for f in findings] + [
        {"id": f.get("id")} for f in ((previous or {}).get("findings") or []) if isinstance(f, dict)]

    def _mint() -> str:
        fid = next_finding_id(facts["project"], {"findings": taken}, ledger)
        taken.append({"id": fid})
        return fid

    for entry in reconcile_hygiene(hyg, (previous or {}).get("findings") or [], _mint,
                                   today.isoformat(), facts.get("run_number"), sha_now,
                                   evidence=evidence,
                                   earlier=_earlier_hygiene(ledger, {str(f["id"]) for f in taken
                                                                     if f.get("id")})):
        _fold_accepted(entry, accepted)
        entry.update(_stamp_outcome(entry, prev_by_id.get(str(entry.get("id")))))
        findings.append(entry)

    # §10: a `pass` cannot stand over an open Critical. One the scan filed is one the
    # tester may not have weighed, and the local tier and the sweep weigh nothing:
    # refusing the state would lose every such run, so the harness caps its own
    # filing at `pass with risks`, and says so in the ledger block.
    verdict = judgment.get("verdict")
    capped_by = [str(f.get("id")) for f in findings if is_hygiene(f) and is_open(f)
                 and f.get("severity") in ("Critical", "Blocker")]
    if verdict == "pass" and capped_by:
        verdict = "pass with risks"

    state = {
        "project": facts["project"],
        "schema_version": facts.get("schema_version", 1),
        "run_type": facts["run_type"],
        "run_number": facts["run_number"],
        "last_run": {**facts["last_run"], "report": judgment.get("report", "")},
        "isolation_check": judgment.get("isolation_check", {}),
        "gates": facts.get("gates", {}),
        # `gates: {}` alone is overloaded: a design review that ran no suite and
        # a profile missing its gates block look identical downstream. facts
        # says which one happened (`no_gates`); it used to be dropped right
        # here, so the validator could only see the ambiguous shape and chose
        # leniency — an unqualified `pass` over zero measurement (VERDICT-F-17).
        **({"no_gates": facts["no_gates"]} if facts.get("no_gates") else {}),
        **({"verification_notes": facts["verification_notes"]}
           if facts.get("verification_notes") else {}),
        "findings": findings,
        "verdict": verdict,
        "release_blockers": judgment.get("release_blockers", []),
        "not_tested": judgment.get("not_tested", []),
        # What was checked and HELD. The first external user said it plainly:
        # the invariants of his money were verified intact, the report said so
        # in the middle where nobody reads, and that confirmation is the thing
        # people actually pay a tester for. Optional — a run that verified
        # nothing intact must not be pushed to invent entries.
        "verified_intact": judgment.get("verified_intact", []),
    }
    for optional in ("run_label", "next_run_focus", "flaky_quarantine", "coverage"):
        if judgment.get(optional) is not None:
            state[optional] = judgment[optional]
    if "run_label" not in state and facts.get("run_label"):
        state["run_label"] = facts["run_label"]     # a gate in a root of its own says so
    # Always assigned, so the end-of-merge carry of unknown keys cannot resurrect a
    # stale ledger.
    prev_ledger = hygiene_previous((previous or {}).get("hygiene"), root,
                                   (previous or {}).get("run_number"))
    state["hygiene"] = hygiene_ledger(hyg, tier2_items(hyg, root, bind), prev_ledger,
                                      today.isoformat(), facts.get("run_number"), sha_now,
                                      evidence=evidence)
    if state["hygiene"].get("status") == "measured":
        state["hygiene"]["leads"]["followed"] = leads_followed(
            hyg.get("leads") if isinstance(hyg, dict) else None, findings)
    # A hygiene finding the judgment named — in `still_open` or `resolved`, or as a
    # copy — was ignored: the scan settles it. Said where a reader sees it rather than
    # refused, since a refusal loop costs a run more than it teaches the tester.
    ignored = _ignored_hygiene_ids(judgment, previous)
    if ignored:
        state["hygiene"]["ignored_judgment_ids"] = ignored
    if verdict != judgment.get("verdict"):
        state["hygiene"]["verdict_capped"] = {"from": judgment.get("verdict"), "to": verdict,
                                            "by": capped_by}
    # Every cited line, hashed, so the next run is told where the code moved.
    # The verified-intact items are strings and stay strings; their anchors
    # sit beside them, aligned by index.
    if repo is not None:
        state["verified_intact_anchors"] = [anchors_for(repo, [str(t)])
                                            for t in (judgment.get("verified_intact") or [])]
        refs = [a for f in findings for a in (f.get("anchors") or [])]
        refs += [a for group in state["verified_intact_anchors"] for a in group]
        state["evidence_anchors"] = {
            "status": "measured", "refs": len(refs),
            "unresolvable": sum(1 for a in refs if a.get("status") == "unresolvable")}
    else:
        state["verified_intact_anchors"] = []
        state["evidence_anchors"] = {
            "status": "unavailable",
            "reason": "facts.json names no repository path (`repo`) — measured by a "
                      "verdict-facts older than 0.83.0, so nothing was anchored this run"}
    if isinstance(facts.get("evidence_drift"), dict):
        state["evidence_drift"] = facts["evidence_drift"]
    if isinstance(facts.get("reading_map"), dict):
        state["reading_map"] = facts["reading_map"]
    else:
        state.pop("reading_map", None)
    # The ranked functions the run accounted for (0.91.0): cited by a finding, or named in
    # not_tested. The third question the Opus check asked by hand — "which changed code does no
    # finding and no not_tested line cover?" — answered without a model.
    rf = facts.get("read_first") if isinstance(facts.get("read_first"), dict) else None
    if rf and rf.get("items"):
        state["read_first"] = {"basis": rf.get("basis"), "items": rf["items"][:READ_FIRST_ACCOUNTED],
                               **read_first_accounting(rf["items"][:READ_FIRST_ACCOUNTED], findings,
                                                       state.get("not_tested") or [])}
    else:
        state.pop("read_first", None)
    # Measured coverage outranks written coverage. The judgment may still carry
    # its own block when the harness had nothing to measure with.
    if isinstance(facts.get("coverage"), dict) and facts["coverage"].get("status"):
        state["coverage"] = facts["coverage"]
    if facts.get("tests"):
        state["tests"] = facts["tests"]
    # Computed here rather than left to a consumer: the next run reads
    # state.json anyway, so its own track record arrives without asking for it.
    # Folded once, and carried: computing it here from `today` and again in
    # write_state from the run timestamp gave two different `decided_on` dates
    # across a UTC-midnight run, so the calibration block inside the state
    # could disagree with the ledger persisted beside it.
    decided_on = str((state.get("last_run") or {}).get("timestamp_utc") or "")[:10] \
        or today.isoformat()
    state["_ledger"] = merge_outcomes(ledger or {}, findings, decided_on)
    state["calibration"] = calibration(state, ledger=state["_ledger"])
    if facts.get("test_ids"):
        state["test_ids"] = facts["test_ids"]
    # Unknown keys from the previous state survive (schema rule) — except a run's own label.
    # Nothing a local or sweep night writes replaces it, so run 32's "EMPTY main-line range …
    # HEAD == 93fb6a82" headed every Sales report for a month (found 2026-10-15).
    for key, value in (previous or {}).items():
        if key in RUN_SCOPED_KEYS:
            continue
        state.setdefault(key, value)
    state.pop("_qa_root", None)
    return state
