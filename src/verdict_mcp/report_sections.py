"""The report's sections: calibration, the reading map, read-first, the questions, the
measured lines, the drifted references, the judgment line and the hygiene lines.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

try:
    from .anchors import DRIFTED
    from .state import is_open
    from .harness_common import HYGIENE_LEDGER_FILE
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from anchors import DRIFTED
    from state import is_open
    from harness_common import HYGIENE_LEDGER_FILE


def _render_calibration(cal: dict) -> list[str]:
    """The tester's own track record, or nothing at all.

    Nothing at all until something has actually been settled: a section reading
    "0 of 0" trains the reader to skip it, and by the time there is a number
    worth seeing they no longer look. Rates stay hidden until the bucket has
    enough decided outcomes to earn one — `reading` carries the counts either
    way, so the section is honest at every sample size.
    """
    if not cal or not cal.get("decided_outcomes"):
        return []
    lines = ["", "## Track record", "",
             f"{cal.get('findings_tracked', 0)} findings tracked across this project's "
             f"history · {cal['decided_outcomes']} settled, "
             f"{cal.get('undecided_outcomes', 0)} still undecided.", ""]
    for label, store in (("Confidence claimed", cal.get("by_confidence") or {}),
                         ("Proof method", cal.get("by_proof_method") or {})):
        rows = [(k, v) for k, v in store.items() if v.get("decided")]
        if not rows:
            continue
        # The split, in the artifact a human reads. 0.64.0 recorded
        # `outcome_basis` and split the counts in the state, and this renderer —
        # the only place most readers ever see the number — kept printing one
        # column under a footnote saying a resolution nobody measured settles
        # nothing, which since that release is false (VERDICT-F-36).
        split = any(v.get("confirmed_claimed") or v.get("confirmed_accepted") for _, v in rows)
        acc_col = any(v.get("confirmed_accepted") for _, v in rows)
        header = ("| Held up | of those, measured |"
                  + (" accepted by the maintainer |" if acc_col else "")
                  + " Withdrawn | Rate |" if split else "| Held up | Withdrawn | Rate |")
        lines += [f"| {label} {header}", "|---|" + "---|" * ((4 + acc_col) if split else 3)]
        for key, v in sorted(rows, key=lambda kv: -kv[1]["decided"]):
            rate = f"{v['precision']:.0%}" if v.get("precision") is not None else "_not yet_"
            measured = f" {v.get('confirmed_measured', 0)} |" if split else ""
            if acc_col:
                measured += f" {v.get('confirmed_accepted', 0)} |"
            lines.append(f"| {key} | {v['confirmed']} |{measured} {v['refuted']} | {rate} |")
        lines.append("")
    buckets = [v for store in (cal.get("by_confidence") or {},
                               cal.get("by_proof_method") or {})
               for v in store.values()]
    any_claimed = any(v.get("confirmed_claimed") for v in buckets)
    # Rows written before `outcome_basis` existed carry neither, and the state
    # deliberately refuses to relabel them. The table showed `19 | 0` under a
    # caveat calling the two kinds exhaustive, so a reader subtracted and read
    # 19 as the tester's word — the state careful, the renderer not, which is
    # the split-brain shape VERDICT-F-36 was about, one release later
    # (VERDICT-F-45).
    # `buckets` is two stores concatenated, and each one partitions the same
    # settled outcomes — so the count has to be summed WITHIN a store and
    # compared ACROSS them, never taken over the concatenation. Taking a
    # maximum over the individual buckets reported the largest single row where
    # the sentence beneath says "those confirmations", meaning the whole
    # column: `Up to 17` where 21 of 28 were unrecorded, leaving a reader to
    # subtract 17 from 28 and credit 11 to the tester's word when the real
    # figure was 7 (VERDICT-F-51). The maximum across stores is a guard against
    # one of them carrying fewer rows than the other.
    def _unrecorded(store):
        return sum(max(0, v.get("confirmed", 0) - v.get("confirmed_measured", 0)
                       - v.get("confirmed_claimed", 0) - v.get("confirmed_accepted", 0))
                   for v in store.values())
    unrecorded = max((_unrecorded(store) for store in
                      (cal.get("by_confidence") or {}, cal.get("by_proof_method") or {})
                      if store), default=0)
    lines += [f"*A rate appears once a row has {cal.get('min_sample')} settled outcomes. "
              "Settled means fix-verified or regressed (it held up) against withdrawn "
              "(it did not); a resolution nobody checked at all settles nothing.*"]
    if any_claimed:
        lines += ["", "*`held up` covers two things and they are not equal: a re-injection "
                  "the harness measured, and one the tester asserted where no measurement "
                  "contradicts it. The `measured` column is the first kind. Read them "
                  "apart.*"]
    if any(v.get("confirmed_accepted") for v in buckets):
        lines += ["", "*`accepted by the maintainer` is a third kind: the defect was confirmed "
                  "by the person who owns the code and the fix was declined (`verdict-accept`). "
                  "It held up on their word, not under a check.*"]
    if unrecorded:
        lines += ["", f"*{unrecorded} of those confirmations were settled before "
                  "`outcome_basis` was recorded and are neither kind. They are counted in "
                  "`held up` and in no other column, because calling them the tester's word "
                  "would be a claim of its own.*"]
    lines.append("")
    return lines


def _render_reading_map(state: dict) -> list[str]:
    """Where the least-tested code is, and which of it no finding has touched."""
    rm = state.get("reading_map") if isinstance(state.get("reading_map"), dict) else {}
    if rm.get("status") != "measured" or not rm.get("lowest"):
        return []
    out = [f"## Reading map ({rm.get('modules')} production modules, "
           f"{rm.get('overall_percent')}% covered overall)", "",
           "| Module | Covered | Statements | Open findings | Last cited |",
           "|---|---|---|---|---|"]
    for m in rm["lowest"][:10]:
        cited = f"run {m['last_cited_run']}" if m.get("last_cited_run") is not None else "never"
        out.append(f"| `{m['path']}` | {m.get('percent')}% | {m.get('statements')} "
                   f"| {m.get('open_findings', 0)} | {cited} |")
    never = rm.get("never_examined") or []
    if never:
        out += ["", "Never cited by any finding, least covered first: "
                + ", ".join(f"`{p}`" for p in never[:10])]
    out.append("")
    return out


def _render_read_first(state: dict) -> list[str]:
    """The ranked functions, and which of them the run accounted for."""
    rf = state.get("read_first") if isinstance(state.get("read_first"), dict) else {}
    if not rf.get("items"):
        return []
    status = {k: "finding" for k in rf.get("cited") or []}
    status.update({k: "not_tested" for k in rf.get("declared_untested") or []})
    out = [f"## Read first — {rf.get('basis')}", "",
           "| Function | Risk | Accounted for |", "|---|---|---|"]
    for it in rf["items"]:
        key = f"{it.get('path')}::{it.get('function')}" if it.get("function") else str(it.get("path"))
        out.append(f"| `{key}` | {it.get('risk') or '—'} | {status.get(key, '**no** — neither cited nor declared untested')} |")
    if rf.get("unaccounted"):
        out += ["", f"{len(rf['unaccounted'])} of {len(rf['items'])} ranked functions were neither cited by a "
                "finding nor named in Not tested."]
    out.append("")
    return out


def _render_questions(state: dict) -> list[str]:
    """The questions parked for a person, and the answers no run had read yet."""
    asked = state.get("questions") if isinstance(state.get("questions"), dict) else {}
    parked, fresh = asked.get("parked") or [], asked.get("answered_since_last_run") or []
    if not parked and not fresh:
        return []
    out = [f"## Needs human decision ({len(parked)} parked)", ""]
    for q in parked:
        meta = f"asked run {q.get('asked_at_run')}"
        if q.get("age_days") is not None:
            meta += f", {q['age_days']}d ago"
        if q.get("finding"):
            meta += f" · about {q['finding']}"
        out.append(f"- **{q.get('id')}** ({meta}) — {q.get('question')}")
        if q.get("context"):
            out.append(f"  _{q['context']}_")
    if not parked:
        out.append("_None parked._")
    if fresh:
        out += ["", "### Answered since the last run", ""]
        for q in fresh:
            decided = (f"dismissed: {q.get('reason')}" if q.get("status") == "dismissed"
                       else str(q.get("answer")))
            out.append(f"- **{q.get('id')}** — {q.get('question')}\n"
                       f"  → {decided} ({q.get('by')}, {q.get('on')})")
    out += ["", f"_Answer with `verdict-answer {state.get('project')} <Q-id> --answer "
            "\"…\"`; the next run reads the decision instead of asking again._", ""]
    return out


def _measured_lines(f: dict, drift: dict, carried_unread: bool = False) -> list[str]:
    """Measured, not remembered: when the harness last ran this finding's
    test, whether the code it cites is still where the evidence says, and
    whether the tester re-reported it by id."""
    out = []
    if f.get("last_verified_at"):
        v = f.get("verification") if isinstance(f.get("verification"), dict) else {}
        at_head = v.get("at_head") if v.get("at_head") in ("pass", "fail") else None
        out.append(f"- Last measured {str(f['last_verified_at'])[:10]}"
                   + (f" — {'passes' if at_head == 'pass' else 'fails'} at HEAD"
                      if at_head else ""))
    elif is_open(f) and not f.get("verification_test"):
        out.append("- Never measured — no `verification_test` declared")
    ex = f.get("exercised_by_tests") or []
    if ex and is_open(f):
        out.append("- Exercised and green: " + ", ".join(f"`{t}`" for t in ex[:5])
                   + " — these run the cited lines and do not fail on the defect; the "
                     "assertion to review, and where a regression test belongs")
    moved_refs = _drifted_refs(drift, f)
    if moved_refs:
        out.append(f"- Cited code {moved_refs[0]} since the evidence was written: "
                   + ", ".join(moved_refs[1]))
    if f.get("re_reported") == "still_open" and carried_unread:
        # A local or sweep night carries an unmoved finding by id without reading it. Its
        # report said "looked at, still there" 73 times a night while its own not_tested
        # said "carried unread" (Sales, every night since 2026-09-27).
        out.append("- _Carried by id, not re-read this run: the cited code did not move; "
                   "the evidence is as last filed_")
    elif f.get("re_reported"):
        out.append(f"- _Re-reported by id (`{f['re_reported']}`): looked at, "
                   f"{'still there' if f['re_reported'] == 'still_open' else 'gone'}; "
                   "the evidence is as last filed_")
    return out


def _days_between(start, end) -> int | None:
    """Whole days from one recorded date to another, or None when either is
    missing or unreadable — a clock the report prints only when both ends
    were measured."""
    try:
        a = date.fromisoformat(str(start)[:10])
        b = date.fromisoformat(str(end)[:10])
    except (TypeError, ValueError):
        return None
    return (b - a).days


def _drifted_refs(drift: dict, finding: dict):
    """(worst drift, [rendered refs]) for a finding whose cited code moved, or None."""
    fid = str(finding.get("id") or "")
    d = (drift.get("findings") or {}).get(fid) or (drift.get("accepted") or {}).get(fid)
    if not isinstance(d, dict) or d.get("drift") not in DRIFTED:
        return None
    refs = [r for r in (d.get("refs") or []) if r.get("status") in DRIFTED]
    shown = [str(r.get("ref")) + (f" (now line {r['now_line']})" if r.get("now_line")
                                  else f" ({r.get('status')})") for r in refs[:6]]
    return d["drift"], shown


def _judge_line(state: dict, last: dict) -> list:
    """Who answered, and what it cost — beside the Harness line, never inferred.

    A report that names its harness and not its judge reads the same whether an
    Opus session spent four dollars on it or an 8B model on the desk answered
    forty bounded questions for nothing. Those are different reports, and the
    difference is exactly what a reader weighing the verdict needs first. A
    sweep says so too: "none" is a judge, and a run nobody judged must not look
    like a run somebody did.

    The model names the judge; the gateway it answered through is not on the line,
    even for a state written before the host left `last_run.local`. A team commits
    this report, and a network address is the payer's, not the reader's.
    """
    engine = last.get("engine")
    if not engine:
        return (["- Judge: none (model-free sweep) — no model was called, so nothing here "
                 "was judged this run"] if state.get("run_type") == "sweep" else [])
    local = last.get("local") if isinstance(last.get("local"), dict) else {}
    parts = [f"- Judge: {engine} · model `{last.get('model') or '?'}`"]
    parts.append(f"{local.get('calls', 0)} call(s), {local.get('tokens', 0)} token(s)")
    if local.get("errors"):
        parts.append(f"{local['errors']} transport error(s)")
    parts.append(f"{local.get('unanswered', 0)} question(s) unanswered")
    parts.append("no Claude tokens spent")
    return [" · ".join(parts)]


def _hygiene_lines(state: dict) -> list[str]:
    """What the scan's ledger could not do this run, and what a judgment said that it
    ignored — said under the scope, where a reader looks before trusting the counts."""
    block = state.get("hygiene") if isinstance(state.get("hygiene"), dict) else {}
    out = []
    if (block.get("summary") or {}).get("prior_unread"):
        out.append(f"- Hygiene ledger: last run's hygiene rows could not be read ({HYGIENE_LEDGER_FILE} "
                   "missing, unreadable, or written by another run) — nothing was carried forward: "
                   "every row this run is NEW, and none was resolved")
    ids = block.get("ignored_judgment_ids") or []
    if ids:
        out.append(f"- Hygiene findings the judgment named, and ignored: {', '.join(map(str, ids))} — "
                   "the scan's own: each resolves when the scan stops seeing it, never on a "
                   "judgment's word")
    return out
