"""What a model would still have to answer: the reasons a run needs Claude, the leads it
leaves in the leads file, and the limits on how many reach the focus and the report.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from .local_verdict import unexercised_diff
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from local_verdict import unexercised_diff


# ── what a model would still have to answer ───────────────────────────────────


def needs_claude(facts: dict, filed: list, refiled: list, touched: list,
                 parked: int, over_limit: bool, non_python: bool) -> dict:
    """The measured reasons a real model run is still owed, for a gate's summary.

    Not advice and not a score: each entry is something the harness counted, so
    "this gate is green and here is what it did not ask" is checkable rather than
    reassuring.
    """
    out: dict = {}
    cold = unexercised_diff(facts)
    if cold:
        out["unexercised_changed_lines"] = cold
    if touched:
        out["touches_open_finding"] = sorted(touched)[:20]
    unproven = sorted({str(f.get("id")) for f in filed
                       if f.get("confidence") != "proven"
                       and str(f.get("severity")) in ("Blocker", "Critical", "Major")})
    if unproven:
        out["unprovable_high_severity"] = unproven[:20]
    if refiled:
        out["drift_unsettled"] = sorted(str(f.get("id")) for f in refiled)[:20]
    if non_python:
        # The key keeps its name (state-schema.md documents it); since every language is read
        # it means "nothing in the range this engine reads".
        out["non_python_diff"] = ("no source this engine reads in the range: only configuration, "
                                  "data, styles, documentation, tests or generated files — it read "
                                  "no code at all")
    if parked:
        out["questions_parked"] = parked
    if over_limit:
        out["diff_over_limit"] = ("the range is larger than the caps this engine runs under; "
                                  "part of it was never read")
    return out


LEADS_FILE = "leads.json"


NO_CODE_READ = ("No code was read this run: the range changed no source this engine reads, "
                "only configuration, data, styles, documentation, tests or generated files. A "
                "green gate here means the suite did not fail; it is not a QA pass.")


# Why a reading of any other language stays unproven: a counterfactual flips a line and re-runs
# an expression in a Python interpreter, and there is no such seam for them here.
NO_PROBE = "no counterfactual: this engine executes Python only, and this code is {language}"


# The ceiling for a range whose code in another language was read. Read is not run: the verdict
# over code no question could ever prove stays below `pass`, as it did when that code was not read
# at all.
READ_NOT_RUN = ("Code in the range in a language other than Python was read, one function or "
                "excerpt at a time, and none of it was executed: this engine runs counterfactuals "
                "in Python only, so every reading there is unproven, and a green gate is not a QA "
                "pass of that code.")


# A focus list that only ever grows is a focus list nobody reads, which is the
# same as not having one.
FOCUS_LINES = 20


LEADS_IN_FOCUS = 5


LEADS_IN_REPORT = 25


def _unique(items) -> list:
    """The list with its order kept and its repeats dropped."""
    seen, out = set(), []
    for item in items:
        text = str(item)
        if text in seen:
            continue
        seen.add(text)
        out.append(item)
    return out
