"""What a run says at the end: the written verdict, the leads, the not-tested lines, the
printed summary, the range it ran over and the env file it read.

Split out of small.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and small.py imports back what its callers use.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from .harness import _git
    from .local_model import Model
    from .local_questions import FAILURE_CEILING, UNPROVEN_CEILING
    from .local_leads import LEADS_IN_REPORT, NO_CODE_READ
    from .local_budget import Budget
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from harness import _git
    from local_model import Model
    from local_questions import FAILURE_CEILING, UNPROVEN_CEILING
    from local_leads import LEADS_IN_REPORT, NO_CODE_READ
    from local_budget import Budget


def written_verdict(qa_root: Path, fallback: str) -> str:
    """The verdict the state holds. This engine's own arithmetic cannot see a Critical
    the hygiene scan files at finalize, which caps a `pass` at `pass with risks`."""
    try:
        state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return fallback
    return str(state.get("verdict") or fallback) if isinstance(state, dict) else fallback


def leads_text(leads) -> str:
    """The report's list of what was read and not proven — for a person, or for the next
    run that can judge it. Capped, and it says so when it is."""
    if not leads:
        return ""
    shown = leads[:LEADS_IN_REPORT]
    lines = [f"\n\n**Leads — read by a small model, not proven, not filed ({len(leads)}).** "
             "Each is a question for a run that can judge it; none is on the record."]
    for x in shown:
        lines.append(f"- `{x['path']}:{x['line']}` `{x['function']}` — {x['title']} "
                     f"(read as {x['severity']}; {x['why']})")
    if len(leads) > len(shown):
        lines.append(f"- … and {len(leads) - len(shown)} more, not listed")
    return "\n".join(lines)


def set_aside_text(items) -> str:
    """The report's list of claims a fact of this run answered: read, set aside with that fact,
    and neither filed nor listed as a lead. Capped like the leads, and it says so."""
    if not items:
        return ""
    shown = items[:LEADS_IN_REPORT]
    lines = [f"\n\n**Set aside — claims a fact of this run already answers ({len(items)}).** "
             "A build that passed, or the code's own declaration; none was filed or listed as a lead."]
    for x in shown:
        lines.append(f"- `{x['path']}:{x['line']}` `{x['function']}` — {x['title']} ({x['why']})")
    if len(items) > len(shown):
        lines.append(f"- … and {len(items) - len(shown)} more, in facts.json `set_aside`")
    return "\n".join(lines)


def not_tested_lines(model: Model, files: list, examined: int, prior_open: list,
                     still_open: list, refiled: list, prove: bool, budget: Budget,
                     quarantine_notes: list, non_python: bool,
                     disabled: str | None = None, unread_survivors: list | None = None) -> list:
    """What a night like this one does not do, counted rather than described.

    The temptation with a cheap engine is to let its report read like the
    expensive one's. This list is what stops that: every line is a number the run
    measured, so a local `pass` is visibly a different sentence from an agent's.
    `disabled` is why no counterfactual ran, when none did — the profile's switch, a
    flag, or a gate with no Python interpreter — named rather than summarised.
    """
    out = [
        f"no agent ran: {model.answered + model.unanswered} bounded question(s) went to "
        f"{model.name} — no exploratory charter, no archaeology, no adversarial reading of "
        "the suite",
        "the commit history: no origin was traced, and no `git log -S` was run",
        f"{len(still_open)} of {len(prior_open)} prior open finding(s) were carried unread, "
        f"and {len(refiled)} re-filed because the code they cite changed and no model looked "
        "at the change",
        f"{len(files)} file(s) and {examined} function(s) were read; nothing else in the "
        "repository was",
        ("claims the counterfactual could not reach — a probe that would not run leaves its "
         f"finding a hypothesis, and an unproven severity is held at {UNPROVEN_CEILING} for a "
         f"reading and at {FAILURE_CEILING} for a failing test the model classified"
         if prove else
         f"everything a counterfactual would show: {disabled or 'proving was disabled this run'}"
         ", so every finding from reading is a hypothesis, and a failing test the model "
         f"classified is held at {FAILURE_CEILING}"),
        "nothing outside the checkout was read — no database, no MCP tools, no production "
        "numbers — so a standing blocker that quotes one was NOT re-read",
        f"{model.unanswered} question(s) the model did not answer"
        + (f", {model.errors} of which the gateway never received" if model.errors else ""),
    ]
    if budget.stopped:
        out.append(f"{budget.skipped} candidate function(s) were never asked about: "
                   f"{budget.stopped}")
    out.extend(f"{path}::{name} — an assertion-gap survivor this run did not read"
               for path, name in (unread_survivors or []))
    if non_python:
        out.append(NO_CODE_READ)
    out.extend(quarantine_notes)
    return out


def print_summary(model: Model, files: list, examined: int, filed: list, refiled: list,
                  resolved: list, still_open: list, verdict: str, owed: dict,
                  budget: Budget, engine_verdict: str | None = None, set_aside=None) -> None:
    """At most fifteen lines, ending on the number this whole release is about.
    `verdict` is the one the state holds; `engine_verdict`, this engine's own, is
    named when finalize capped it."""
    lines = [
        f"verdict-local: verdict {verdict!r}"
        + (f" (this engine's {engine_verdict!r}, capped at finalize by a Critical the "
           "hygiene scan filed)" if engine_verdict and engine_verdict != verdict else ""),
        f"  read       {examined} function(s) in {len(files)} file(s)"
        + (f", {budget.skipped} skipped — {budget.stopped}" if budget.stopped else ""),
        f"  filed      {len(filed)} finding(s), {len(refiled)} of them re-filed unread"
        + (f" · {len(set_aside)} claim(s) set aside, answered by the build or a declaration"
           if set_aside else ""),
        f"  carried    {len(still_open)} by id · resolved {len(resolved)} by measurement",
        f"  model      {model.name} · {model.calls} call(s) · "
        f"{model.input_tokens + model.output_tokens:,} token(s) · "
        f"{model.unanswered} unanswered · {model.errors} transport error(s)",
    ]
    for key, value in sorted(owed.items()):
        lines.append(f"  needs a model run: {key} — {value}")
    print("\n".join(lines[:14] + ["  Claude tokens: 0"]), file=sys.stderr)


def resolve_range(repo: Path, explicit, base) -> str | None:
    """`BASE..HEAD` from `--range`, or from `--base` through the merge base.

    A branch is judged against where it left the trunk, not against the trunk's
    tip: `main..HEAD` after somebody else merges reads their commits as this
    branch's change. `git merge-base` asks the question that was meant.
    """
    if explicit:
        return str(explicit)
    if not base:
        return None
    merge_base = _git(["merge-base", str(base), "HEAD"], repo)
    if not merge_base:
        print(f"verdict-local: --base {base} has no merge base with HEAD in {repo}",
              file=sys.stderr)
        return None
    return f"{merge_base}..HEAD"


def read_env_file(path: Path) -> dict:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out
