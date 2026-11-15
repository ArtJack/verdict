"""What a run carries from the last one: replayed and fresh findings, the outcome stamped
on each, accepted risks folded in, the run's date, and the survivor and read-first
accounting.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

try:
    from .replay import major_first, measure_findings, model_written
    from .state import accepted_block, in_force, is_open, norm_status
    from . import clock
    from .harness_common import _chosen
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import clock
    from replay import major_first, measure_findings, model_written
    from state import accepted_block, in_force, is_open, norm_status
    from harness_common import _chosen


DECIDED = ("confirmed", "refuted")


SEVERITIES_ASKED = ("Blocker", "Critical", "Major")


def _replay_fresh_findings(state: dict, facts: dict, qa_root: Path) -> list[str]:
    """Run the repro of every open finding this run filed - new, regressed, or carrying a repro
    the previous record lacked - on a fresh worktree at HEAD, Major+ first, stamp the reading,
    and name the Major+ ones filed `proven` that did not reproduce. A Minor's repro runs too
    (0.93.0) and its reading is stamped, but only a Major+ claim refuses the run: a capped run
    refused over a Minor near its cap would write no state at all."""
    repo_dir = facts.get("repo")
    repo = Path(repo_dir) if repo_dir and Path(repo_dir).is_dir() else None
    if repo is None:
        return []
    measured = facts.get("replay") if isinstance(facts.get("replay"), dict) else {}
    def unmeasured(f):
        rec = measured.get(str(f.get("id")))
        return not rec or rec.get("command") != f["repro"].get("command")   # re-filed with a new repro
    fresh = major_first(f for f in state.get("findings") or []
                        if isinstance(f.get("repro"), dict) and unmeasured(f) and is_open(f)
                        and str(f["repro"].get("command") or "").strip())
    if not fresh:
        return []
    records, notes = measure_findings(repo, fresh, None, qa_root,
                                      str(facts.get("measured_at") or ""), refs=("HEAD",),
                                      source="finalize")
    for note in notes:
        print(f"verdict-finalize: {note}", file=sys.stderr)
    problems, minor = [], []
    for f in fresh:
        rec = records.get(str(f.get("id")))
        if not rec:
            continue
        f["replay"] = rec
        if rec.get("at_head") == "not reproduced" and f.get("confidence") == "proven" \
                and rec.get("isolated") is not False:
            (problems if f.get("severity") in SEVERITIES_ASKED else minor).append(
                f"{f.get('id')}: {'; '.join(rec.get('checks_head') or [])}")
    if minor:
        print(f"verdict-finalize: {len(minor)} Minor-or-lower finding(s) filed `proven` did not reproduce "
              "on a fresh worktree at HEAD; the reading is on each, the run stands:\n  " + "\n  ".join(minor),
              file=sys.stderr)
    return problems


def _apply_replay(entry: dict, prior: dict | None, replays: dict,
                  measured_at: str | None = None) -> None:
    """Stamp the repro measurement on a finding, and let it decide what prose cannot.

    `at_head: reproduced` refuses a resolution — claimed or by silence — the way a
    cited test that still fails does. `at_previous: reproduced` with `at_head: not
    reproduced` is a fix the harness watched: a claimed resolution becomes
    `fix_verified`, and a finding nobody re-reported is resolved by measurement, which
    is what a record that carried thirteen fixed findings open was missing (trace
    2026-10-15). Anything inconclusive — could not run, not isolated, no previous
    reading — is silence, and silence changes nothing.
    """
    key = str(entry.get("id") or (prior or {}).get("id") or "")
    rec = replays.get(key) if replays else None
    if not rec:
        return
    entry["replay"] = rec
    if rec.get("at_head") in ("reproduced", "not reproduced") and measured_at:
        entry["last_verified_at"] = measured_at
    if rec.get("isolated") is False:
        return                                   # the fresh tree may not be what ran
    resolving = entry.get("delta") == "RESOLVED"
    if rec.get("at_head") == "reproduced":
        if resolving:
            entry["status"] = "open"
            entry["delta"] = "STILL_OPEN"
            entry.pop("fix_verified", None)
            entry["resolution_refused"] = ("its repro still reproduces on a fresh worktree at "
                                           "HEAD — measured by verdict-facts, so the resolution "
                                           "is not accepted")
            if "carried_forward" in entry:
                entry["carried_forward"] = ("not reported this run, but its repro still "
                                            "reproduces at HEAD — held open by measurement")
        return
    if rec.get("at_head") == "not reproduced" and rec.get("at_previous") == "reproduced":
        sha7 = str(rec.get("previous_sha") or "")[:7]
        line = (f"replay (measured): the repro reproduces at {sha7} and not at HEAD, on fresh "
                "worktrees of each")
        if model_written(entry.get("repro") or (prior or {}).get("repro")):
            # A model wrote this repro (verdict-backfill), and one checked by hand on 2026-10-18
            # tested something near its finding rather than the finding itself. When it stops
            # reproducing, an unrelated change may be why: the finding stays open and is named
            # for a run with judgment, and nothing is verified on its word (0.92.0).
            if not resolving:
                entry["fix_suspected"] = (f"its model-written repro reproduces at {sha7} and not at "
                                          "HEAD — read it, then resolve or keep it")
            return
        if not resolving:
            entry["status"] = "resolved"
            entry["delta"] = "RESOLVED"
        if not resolving or entry.get("carried_forward"):
            # The harness settled it: a finding held open, or resolved by nobody's claim.
            entry["resolved_by"] = "measurement (repro)"
            if "carried_forward" in entry:
                entry["carried_forward"] = ("not reported this run; its repro reproduces at the "
                                            "previous commit and not at HEAD — resolved by "
                                            "measurement")
        entry["fix_verified"] = True
        if measured_at:
            entry["fixed_at"] = measured_at[:10]
        entry["evidence"] = [*(str(e) for e in (entry.get("evidence") or [])), line]


def _stamp_outcome(finding: dict, prior: dict | None = None) -> dict:
    """Derive the outcome from what the finding did — never from asking.

    Three things settle a finding. It regressed (it was fixed and came back, so
    it was real). It was resolved and the fix was verified by re-injection (§6:
    absence is not evidence, a failing guard is). Or the tester withdrew it,
    which is the one event that says it was never real.

    A settled outcome then *sticks*. Without that, a finding confirmed by
    regression on run 12 and still open on run 13 would quietly return to
    undecided, and the track record would erode every time a finding changed
    state. Withdrawal is the sole exception: an explicit correction outranks an
    earlier inference, because it is the tester saying it got this wrong.
    """
    delta, status = finding.get("delta"), norm_status(finding.get("status"))
    if delta == "WITHDRAWN" or status == "withdrawn":
        return {"outcome": "refuted",
                "outcome_reason": "withdrawn by the tester as never real"}
    prior_outcome = (prior or {}).get("outcome")
    if prior_outcome in DECIDED:
        return {"outcome": prior_outcome,
                "outcome_reason": (prior or {}).get("outcome_reason")
                or "settled by an earlier run"}
    if status == "accepted":
        # The maintainer's word, recorded through `verdict-accept` and folded
        # in by `_fold_accepted`: the defect is real and the fix is declined.
        # Confirmed, on a basis of its own — neither a measurement nor the
        # tester's claim — and the tally keeps the three apart.
        acc = finding.get("accepted") or {}
        return {"outcome": "confirmed", "outcome_basis": "accepted",
                "outcome_reason": (f"risk accepted by {acc.get('by')} on {acc.get('on')}: "
                                   "the maintainer confirmed the defect and declined the "
                                   f"fix ({acc.get('citation')})")}
    if delta == "REGRESSED":
        return {"outcome": "confirmed",
                "outcome_reason": "regressed: it was fixed and came back, so it was real"}
    # Measurement outranks the claim; silence does not. `fix_verified` reaches a
    # finding from two places — the harness sets it when its own re-injection
    # measured fail→pass, and a judgment may claim it for a re-injection done by
    # hand — and the branch that turns a resolution into a ledger row could not
    # tell them apart, so it recorded `confirmed` over a measurement that never
    # happened (VERDICT-F-32).
    #
    # 0.62.0 fixed that by demoting a claim whenever a measurement had been
    # *attempted*, and which test gets attempted is the prose lottery of
    # VERDICT-F-26: the same hand-verified claim landed `confirmed` when the
    # write-up quoted no node id and `unknown` when it did. Four findings
    # verified identically, two outcomes, decided by prose (VERDICT-F-35). So an
    # inconclusive measurement — pass at both commits, an error, nothing
    # runnable — is silence, and silence changes nothing. Only a measurement
    # that *contradicts* the claim does, and `_apply_verification` has already
    # reopened the finding by the time one does.
    #
    # What the ledger keeps is which of the two it was: `outcome_basis`, so a
    # tally can separate what the harness proved from what the tester asserted
    # rather than adding them up as one integer (VERDICT-F-36).
    v = finding.get("verification")
    attempted = isinstance(v, dict)
    # …on a test somebody chose. A fail→pass on a test merely quoted in prose
    # is recorded and settles nothing (VERDICT-F-72).
    shows_fix = (attempted and v.get("at_previous") == "fail" and v.get("at_head") == "pass"
                 and _chosen(v))
    # …but not one the harness itself declined to weigh. `_apply_verification`
    # stamps `not_weighed` on a test chosen by prose order from several
    # candidates and refuses to reopen the finding with it; reading the same
    # record here as a contradiction denied the row anyway, under a reason that
    # said the opposite of the note beside it (VERDICT-F-40).
    contradicts = (attempted and v.get("at_head") == "fail"
                   and not v.get("not_weighed"))
    r = finding.get("replay") if isinstance(finding.get("replay"), dict) else {}
    shows_fix_by_repro = (r.get("at_previous") == "reproduced" and r.get("at_head") == "not reproduced"
                          and r.get("isolated") is not False)
    contradicts = contradicts or (r.get("at_head") == "reproduced" and r.get("isolated") is not False)
    claimed = finding.get("fix_verified") is True
    if delta == "RESOLVED" and shows_fix:
        return {"outcome": "confirmed", "outcome_basis": "measured",
                "outcome_reason": "fix-verified: the guarding test failed on re-injection"}
    if delta == "RESOLVED" and shows_fix_by_repro:
        return {"outcome": "confirmed", "outcome_basis": "measured",
                "outcome_reason": "fix-verified: the repro reproduces at the previous commit "
                                  "and not at HEAD"}
    if delta == "RESOLVED" and claimed and contradicts:
        return {"outcome": "unknown",
                "outcome_reason": "claimed fix-verified, but the cited test still fails at HEAD"}
    if delta == "RESOLVED" and claimed:
        return {"outcome": "confirmed", "outcome_basis": "claimed",
                "outcome_reason": "fix-verified: claimed by the tester, and no harness "
                                  "measurement contradicts it"}
    if delta == "RESOLVED" and finding.get("carried_forward"):
        # Weaker still than an unverified resolution: nobody claimed anything.
        return {"outcome": "unknown",
                "outcome_reason": "not re-reported; no one verified anything"}
    if delta == "RESOLVED":
        return {"outcome": "unknown",
                "outcome_reason": "resolved but not fix-verified — absence is not proof"}
    return {"outcome": "unknown", "outcome_reason": "still open; nothing has settled it"}


# Silence-as-resolution has a blast radius. A judgment that stops mentioning a
# finding usually means it is gone, and that is how a backlog drains without
# ceremony. But a *scoped* run — a merge gate over three files, a charter aimed
# at one subsystem — legitimately says nothing about the rest of the backlog,
# and reading that silence as "fixed" closes findings nobody looked at. Verdict
# shipped exactly that: a merge-gate run on sales resolved 62 open findings, 14
# of them Critical, because the judgment only spoke to the diff.
#
# So silence still resolves, but not at a scale better explained by a narrow run
# than by that many fixes. Above the line the findings are held open and carry
# the reason; a run that really did sweep everything declares `full_sweep` and
# gets the old behaviour back. Holding open is the recoverable error — a stale
# open finding costs a re-read, a wrongly-closed Critical costs the gate. Below
# the floor, proportion is noise: two of three is not evidence of anything.
CARRY_RESOLVE_FLOOR = 5


CARRY_RESOLVE_SHARE = 0.5


def run_date(facts: dict | None) -> date:
    """The calendar date of the run, read from the run's own UTC timestamp.

    Not `date.today()`. Every other clock in this module is UTC, and the local
    one disagrees with them for part of every day — seven hours wide on the
    machine where this was found, which filed five findings dated the day
    before the state, report filename and INDEX row that carry them
    (VERDICT-F-54). Reading the date off `last_run.timestamp_utc` rather than
    off a second clock call also makes the two agree by construction when a
    long run straddles midnight. The stamp is permanent — `first_seen` is
    copied forward for the life of a finding, and `age_days` is measured from
    it — so a wrong date never washes out.
    """
    stamp = str(((facts or {}).get("last_run") or {}).get("timestamp_utc") or "")
    try:
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return clock.today()
    if when.tzinfo is not None:
        when = when.astimezone(timezone.utc)
    return when.date()


def _fold_accepted(entry: dict, ledger: dict | None) -> None:
    """Apply the maintainer's ledger to one finding, in place, before its
    outcome is derived.

    The tester writes `open`; the ledger says whether the maintainer has
    accepted that finding's risk. In force: the finding reads `accepted`,
    delta `ACCEPTED`, and carries who, when, the citation and the reason.
    Gone or revoked while the state still says `accepted`: the finding is open
    again, `STILL_OPEN`, with the revocation on it. Resolved and withdrawn
    findings are never touched — a defect that is gone has nothing left to
    accept, and a resolution can still be fix-verified as usual.
    """
    row = (ledger or {}).get(str(entry.get("id") or ""))
    status = norm_status(entry.get("status"))
    if status == "open" and in_force(row):
        entry["status"] = "accepted"
        entry["delta"] = "ACCEPTED"
        entry["accepted"] = accepted_block(row)
        entry.pop("accepted_revoked", None)
    elif status == "open":
        # A judgment may not carry the maintainer's block, and one that does
        # is stripped rather than folded: a tester could otherwise decorate
        # its own finding with an acceptance nobody made, and the block would
        # sit in the trust artifact verbatim (run 13, reported not filed).
        entry.pop("accepted", None)
    elif status == "accepted":
        if in_force(row):
            entry["delta"] = "ACCEPTED"
            entry["accepted"] = accepted_block(row)
        else:
            entry["status"] = "open"
            entry["delta"] = "STILL_OPEN"
            entry.pop("accepted", None)
            if row and isinstance(row.get("revoked"), dict):
                entry["accepted_revoked"] = dict(row["revoked"])


READ_FIRST_ACCOUNTED = 10


def survivor_accounting(facts: dict, state: dict) -> dict | None:
    """The census's survivor functions, accounted like read_first's items; stamped on the state
    as `assertion_gaps_accounting` when the census ran and found any."""
    survived = ((facts.get("assertion_gaps") or {}).get("survived")) or []
    items, seen = [], set()
    for g in survived:
        key = (str(g.get("path") or ""), str(g.get("function") or ""))
        if key[0] and key[1] and key not in seen:
            seen.add(key)
            items.append({"path": key[0], "function": key[1]})
    if not items:
        state.pop("assertion_gaps_accounting", None)
        return None
    acc = read_first_accounting(items, state.get("findings") or [], state.get("not_tested") or [])
    state["assertion_gaps_accounting"] = {"functions": len(items), **acc}
    return acc


def read_first_accounting(items, findings, not_tested) -> dict:
    """Each ranked function: cited by an open or resolved finding (the file among its anchors
    or evidence, and the function's name in its text), named in `not_tested`, or neither."""
    nt = " ".join(str(x) for x in not_tested or []).lower()
    cited, untested, unaccounted = [], [], []
    for it in items:
        path = str(it.get("path") or "")
        fn = str(it.get("function") or "")
        short = fn.rsplit(".", 1)[-1].lower() if fn and fn != "(module)" else ""
        key = f"{path}::{fn}" if fn else path
        base = path.rsplit("/", 1)[-1].lower()

        def cites(f):
            text = " ".join([str(f.get("title") or "")] + [str(e) for e in f.get("evidence") or []]).lower()
            files = {str((a or {}).get("path") or "").replace("\\", "/") for a in f.get("anchors") or []
                     if isinstance(a, dict)}
            in_file = path in files or any(p.endswith("/" + path) or path.endswith("/" + p) for p in files if p) \
                or base in text
            return in_file and (not short or short in text)

        if any(isinstance(f, dict) and cites(f) for f in findings or []):
            cited.append(key)
        elif (short and short in nt) or (path and path.lower() in nt):
            untested.append(key)
        else:
            unaccounted.append(key)
    return {"cited": cited, "declared_untested": untested, "unaccounted": unaccounted}
