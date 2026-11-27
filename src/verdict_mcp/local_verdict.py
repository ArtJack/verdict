"""The verdict, which may never improve on its own: a failed gate, counts that were not
measured, a diff no test executed, a carried block, and the verdict over the findings.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations



# ── the verdict, which may never improve on its own ───────────────────────────


def gate_failed(facts: dict) -> bool:
    """Did any gate this run come back red? A suite with failing tests is the plainest
    thing a QA run can know, and it outranks everything this engine reads.

    Measured 2026-09-17, and the reason this function exists: on the seeded delta fixture
    the local tier carried all five prior findings honestly, filed the new defect — and
    reported `pass with risks` over a suite with three failing tests, because the verdict
    was computed from finding severities alone and an unproven reading is held at Minor.
    A strong model classifies a failure (stale expectation, brittle test, flaky) and may
    still ship; this engine cannot be trusted to make that call from a few hundred tokens
    of context, so a red gate is a `fail` and a person or a real model decides otherwise.
    """
    for gate in (facts.get("gates") or {}).values():
        if isinstance(gate, dict) and str(gate.get("result")) == "fail":
            return True
    return False


def counts_measured(facts: dict) -> bool:
    """Did any gate this run produce test counts? Nothing else establishes that a
    test executed at all, and a verdict over that is `blocked`, not `pass`."""
    if facts.get("no_gates"):
        return False
    gates = facts.get("gates") or {}
    return bool(gates) and any(isinstance(g, dict) and g.get("counts") for g in gates.values())


def unexercised_diff(facts: dict) -> int:
    """How many changed lines no test executed — 0 when coverage was not measured."""
    cov = facts.get("coverage") if isinstance(facts.get("coverage"), dict) else {}
    if cov.get("status") != "measured":
        return 0
    changed = int(cov.get("changed_lines") or 0)
    return changed - int(cov.get("changed_lines_executed") or 0) if changed else 0


def local_verdict(previous_verdict, filed: list, carried: list, measured: bool,
                  cold_lines: int = 0, ceiling: str | None = None,
                  gates_failed: bool = False) -> str:
    """The verdict of a local run — arithmetic, and monotone downwards.

    The rule that matters is the one this engine cannot be trusted without: a run
    that read six functions with an 8B model may never improve the standing
    verdict. Two verdicts are sticky, and for different reasons.

    A `fail` stays `fail` because something with judgment found a defect and
    nothing here has the standing to say it is gone. A `blocked` stays `blocked`
    because a previous run could not test at all — an environment, a tool, a
    requirement nobody answered — and this engine cannot tell whether what
    blocked it has cleared. Letting `blocked` improve was the worse of the two:
    the gate turns exit 3 into exit 0 on the word of a run that read six
    functions, which is precisely the false green this tier exists to make
    impossible.
    """
    if not measured:
        return "blocked"
    if gates_failed:
        # Red suite, red verdict. Not "pass with risks over three failing tests".
        return "fail"
    severities = [str(f.get("severity")) for f in list(filed) + list(carried)]
    if "Blocker" in severities:
        return "fail"
    if previous_verdict is None:
        # A baseline has nothing to carry and nothing to protect, so this
        # engine's own arithmetic stands — capped by what it could not read.
        standing = verdict_for(filed)
        return "pass with risks" if standing == "pass" and (cold_lines or ceiling) else standing
    if previous_verdict in ("fail", "blocked"):
        return str(previous_verdict)
    if "Critical" in severities or filed or cold_lines or ceiling:
        return "pass with risks"
    return str(previous_verdict or "pass")


CARRIED_BLOCKED = ("the previous run was blocked and this engine cannot tell whether what "
                   "blocked it has cleared — the verdict is carried, not re-judged")


def verdict_for(filed: list) -> str:
    """The verdict is arithmetic over the findings, not an opinion: an open Blocker
    forces `fail`, and so does a Critical this mode could not disprove."""
    severities = {f.get("severity") for f in filed}
    if "Blocker" in severities or "Critical" in severities:
        return "fail"
    return "pass with risks" if filed else "pass"
