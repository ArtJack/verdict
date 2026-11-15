"""Rendering a run's report from its state: the one function that writes the Markdown
report, built from the sections in report_sections.

Split out of harness.py by the structure pass (2026-11-15) as a pure move: every block below
is byte-identical to what it was there, and harness.py imports back what its callers use.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from .state import is_open, norm_status, order_findings
    from .harness_common import _chosen
    from .report_sections import (_days_between, _drifted_refs, _hygiene_lines, _judge_line,
                                  _measured_lines, _render_calibration, _render_questions,
                                  _render_read_first, _render_reading_map)
except ImportError:  # executed as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import is_open, norm_status, order_findings
    from harness_common import _chosen
    from report_sections import (_days_between, _drifted_refs, _hygiene_lines, _judge_line,
                                 _measured_lines, _render_calibration, _render_questions,
                                 _render_read_first, _render_reading_map)


# ── the report, rendered ──────────────────────────────────────────────────


def render_report(state: dict, prose: dict | None = None) -> str:
    """Render the report from the state, injecting the agent's prose.

    Everything countable comes from the state, so the report and the state
    cannot disagree — they did, once, when the state pointed at a stale file.
    Everything that requires a sentence comes from `prose`, because a rendered
    table is not an explanation and nobody should pretend otherwise.
    """
    # Belt and braces: `validate_judgment` rejects a non-object `prose` with a
    # message its author can act on, but a renderer that raises AttributeError
    # on unexpected input is a renderer that loses a whole run to a typo.
    prose = prose if isinstance(prose, dict) else {}
    last = state.get("last_run") or {}
    out = [f"# QA report — {state.get('project')} · run {state.get('run_number')} "
           f"({state.get('run_type')})", ""]
    if state.get("run_label"):
        out += [f"*{state['run_label']}*", ""]
    out += [f"**VERDICT: {state.get('verdict')}**", ""]
    rule = state.get("verdict_rule") if isinstance(state.get("verdict_rule"), dict) else None
    if rule:
        detail = rule.get("reason") or ", ".join(rule.get("raised_by") or [])
        out += [f"> Set by the harness ({rule.get('rule')}): the judgment said "
                f"`{rule.get('was')}`; {detail}.", ""]

    out += ["## Scope", "",
            f"- Range: `{last.get('sha_range') or last.get('git_sha') or 'n/a'}`"
            + (f" · {last['diff_stat']}" if last.get("diff_stat") else ""),
            f"- Branch: `{last.get('git_branch') or 'n/a'}` · measured {last.get('timestamp_utc')}"]
    harness = last.get("harness") or {}
    if harness.get("path"):
        prompt = harness.get("prompt_sha256")
        out.append(f"- Harness: verdict-qa-mcp {harness.get('version') or '?'}"
                   + (f" · prompt {prompt[:12]}" if prompt else "")
                   + f" · `{harness['path']}`")
    out += _judge_line(state, last)
    drift = state.get("evidence_drift") if isinstance(state.get("evidence_drift"), dict) else {}
    if drift.get("status") == "measured":
        summary = drift.get("summary") or {}
        moved = summary.get("drifted_findings") or []
        moved_acc = summary.get("drifted_accepted") or []
        out.append(f"- Evidence drift: {len(moved)} of {len(drift.get('findings') or {})} "
                   "anchored open findings cite code that moved or changed since the "
                   "evidence was written"
                   + (f" ({', '.join(moved)})" if moved else "")
                   + (f"; under accepted risks: {', '.join(moved_acc)}" if moved_acc else ""))
    elif drift.get("status") == "unavailable":
        out.append(f"- Evidence drift: not measured — {drift.get('reason')}")
    iso = state.get("isolation_check") or {}
    if iso:
        detail = iso.get("method") or iso.get("note") or ""
        out.append(f"- Isolation check: **{iso.get('result', iso.get('status', 'n/a'))}**"
                   + (f" — {detail}" if detail else ""))
    out += _hygiene_lines(state)
    if prose.get("scope"):
        out += ["", prose["scope"]]

    gates = state.get("gates") or {}
    if gates:
        out += ["", "## Gates", "", "| Gate | Result | Exit | Duration | Summary |",
                "|---|---|---|---|---|"]
        for name, g in gates.items():
            out.append(f"| `{name}` | {g.get('result', '?')} | {g.get('exit_code', '?')} "
                       f"| {g.get('duration_s', '?')}s | {str(g.get('summary', ''))[:120]} |")
    tests = state.get("tests") or {}
    if tests:
        counted = ", ".join(f"{k} {v}" for k, v in tests.items() if k != "duration_s")
        out += ["", f"Tests: {counted}"]
    ids = state.get("test_ids") or {}
    if ids.get("status") == "measured":
        # Counts, not list lengths: the lists are capped at 50 for display and a
        # state from before the counts travelled falls back to the old reading.
        added_n = ids.get("added_count", len(ids.get("added", [])))
        removed_n = ids.get("removed_count", len(ids.get("removed", [])))
        out.append(f"Test-id ledger: {ids['count']} ids · +{added_n} / −{removed_n} "
                   "(set-diff, not summary arithmetic)"
                   + (" — id lists truncated to 50 each" if ids.get("truncated") else ""))
    elif ids.get("status") == "unavailable":
        out.append(f"Test-id ledger: **unavailable** — {ids.get('reason', '')}")
    measured = [f for f in state.get("findings", []) if isinstance(f.get("verification"), dict)]
    if measured or state.get("verification_notes"):
        # Counted from the measurement, never from `fix_verified` — that is the
        # one judgment field here, and counting it inside a block selected by
        # measurement published run 5's error/error record as "1 verified"
        # (VERDICT-F-30). Both halves below are the harness's own: `at_*` come
        # from the re-run, `delta` from merge.
        def _shows_fix(f):
            v = f["verification"]
            return v.get("at_previous") == "fail" and v.get("at_head") == "pass" and _chosen(v)
        verified = sum(1 for f in measured if _shows_fix(f) and f.get("delta") == "RESOLVED")
        refused = sum(1 for f in measured if f.get("resolution_refused"))
        not_run = sum(1 for f in measured
                      if f["verification"].get("selected_by") == "unselectable")
        prose_only = sum(1 for f in measured if f["verification"].get("not_weighed"))
        out.append(f"Fix verification: {verified} verified · {refused} refused (cited test "
                   f"still fails at HEAD) · {len(measured) - verified - refused - not_run} "
                   "measured but not verifiable"
                   + (f" · {not_run} not run (tests cited in prose only, none declared "
                      "as `verification_test`)" if not_run else "")
                   + (f" · {prose_only} measured on a prose citation only — recorded, not "
                      "confirmed; declare `verification_test`" if prose_only else ""))
        unconfirmed = [str(f.get("id")) for f in measured
                       if f.get("fix_verified") is True and not _shows_fix(f)]
        if unconfirmed:
            out.append("  - claims fix_verified the measurement does not show: "
                       + ", ".join(unconfirmed))
        for note in state.get("verification_notes") or []:
            out.append(f"  - {note}")
    cov = state.get("coverage") or {}
    if cov.get("status") == "measured":
        if cov.get("changed_lines"):
            out.append(f"Diff coverage: {cov['changed_lines_executed']}/{cov['changed_lines']} "
                       f"changed lines executed ({cov.get('percent')}%) across "
                       f"{cov['changed_files']} file(s); "
                       f"{len(cov.get('tests_touching_diff') or [])} test(s) touch the diff")
            kinds = cov.get("by_kind") or {}
            prod, tests_ = kinds.get("production") or {}, kinds.get("tests") or {}
            if prod.get("changed_lines") or tests_.get("changed_lines"):
                out.append(
                    f"  - production {prod.get('changed_lines_executed', 0)}/"
                    f"{prod.get('changed_lines', 0)}"
                    + (f" ({prod['percent']}%)" if prod.get("percent") is not None else "")
                    + f" · test code {tests_.get('changed_lines_executed', 0)}/"
                    f"{tests_.get('changed_lines', 0)}"
                    + (f" ({tests_['percent']}%)" if tests_.get("percent") is not None else "")
                    + " — read production first; a test file's fixtures and `def` lines "
                      "never carry a test context, so the blended number moves with the "
                      "shape of the diff")
            if cov.get("changed_lines_executed_in_subprocess"):
                out.append(f"  - {cov['changed_lines_executed_in_subprocess']} of them only in a "
                           "subprocess the suite spawned — measured, but no test to name")
            for path, pf in (cov.get("per_file") or {}).items():
                if pf.get("unexercised_ranges"):
                    rng = ", ".join(f"{a}-{b}" if a != b else str(a)
                                    for a, b in pf["unexercised_ranges"])
                    fns = ", ".join(pf.get("unexercised_functions") or [])
                    out.append(f"  - {path}: unexercised lines {rng}"
                               + (f" — functions never entered: {fns}" if fns else "")
                               + (f" ({pf['note']})" if pf.get("note") else ""))
        else:
            out.append("Diff coverage: no .py lines changed in the range")
    elif cov.get("status") == "unavailable":
        out.append(f"Diff coverage: **unmeasurable** — {cov.get('reason', '')}")

    if prose.get("risks"):
        out += ["", "## Risks", "", prose["risks"]]

    # The gate, the MCP surface and this report must agree on what "REGRESSED
    # first" means. They did not: this module carried its own copy of the sort,
    # and a severity with a stray space already sorted differently in the two.
    findings = order_findings(state.get("findings") or [])
    open_f = [f for f in findings if is_open(f)]
    accepted_f = [f for f in findings if norm_status(f.get("status")) == "accepted"]
    out += ["", f"## Findings — REGRESSED first ({len(open_f)} open of {len(findings)} tracked"
            + (f" · {len(accepted_f)} accepted" if accepted_f else "") + ")", ""]
    if not findings:
        out.append("_None recorded this run._")
    # Who carried the findings: a local engine or a sweep carries an unmoved one by id
    # without reading it; only a judging tester "looked at" it.
    carried_unread = ((state.get("last_run") or {}).get("engine") == "verdict-local"
                      or state.get("run_type") == "sweep")
    for f in findings:
        cls = f.get("failure_classification")
        dwell = _days_between(f.get("introduced_at"), f.get("first_seen"))
        latency = _days_between(f.get("first_seen"), f.get("fixed_at"))
        out.append(f"### {f.get('id')} — {f.get('delta', '?')} — "
                   f"{f.get('severity')}/{f.get('priority')}"
                   + (f" — {cls}" if cls else "")
                   + (f" — age {f['age_days']}d" if f.get("age_days") else "")
                   + (f" · lived {dwell}d before detection" if dwell is not None else "")
                   + (f" · fix verified {latency}d after detection" if latency is not None else ""))
        out.append("")
        out.append(str(f.get("title", "")))
        for e in (f.get("evidence") or []):
            out.append(f"- {e}")
        out += _measured_lines(f, drift, carried_unread)
        rc = f.get("root_cause") or {}
        if rc:
            chain = " → ".join(str(rc[k]) for k in ("mechanism", "origin") if rc.get(k))
            if chain:
                out.append(f"- Root cause: {chain}")
            if rc.get("class"):
                out.append(f"- Class: {json.dumps(rc['class'])[:200]}")
        if f.get("carried_forward"):
            out.append(f"- _{f['carried_forward']}_")
        acc = f.get("accepted") if norm_status(f.get("status")) == "accepted" else None
        if acc:
            out.append(f"- _Accepted risk — {acc.get('on')} by {acc.get('by')}, citing "
                       f"{acc.get('citation')}: {acc.get('reason')}_")
        if isinstance(f.get("accepted_revoked"), dict):
            r = f["accepted_revoked"]
            out.append(f"- _Acceptance revoked {r.get('on')} by {r.get('by')}: {r.get('reason')}_")
        narrative = prose.get("findings")
        if isinstance(narrative, dict) and narrative.get(str(f.get("id"))):
            out += ["", narrative[str(f.get("id"))]]
        out.append("")

    if accepted_f:
        # Apart from the open list and after it, never instead of it: a risk
        # somebody accepted is out of the counts, not out of sight.
        out += ["", f"## Accepted risks ({len(accepted_f)})", "",
                "_The maintainer's decision, recorded with `verdict-accept`, never the "
                "tester's: each is a real defect whose fix was declined, with the reason and "
                "where the decision is written down. Out of the open counts and the release "
                "blockers; not out of sight._", ""]
        for f in accepted_f:
            a = f.get("accepted") or {}
            moved_refs = _drifted_refs(drift, f)
            out.append(f"- **{f.get('id')}** ({f.get('severity')}/{f.get('priority')}, age "
                       f"{f.get('age_days', 0)}d) — accepted {a.get('on')} by {a.get('by')}, "
                       f"citing {a.get('citation')}: {a.get('reason')}"
                       + (f" — **the code under it {moved_refs[0]}** since the evidence was "
                          f"written: {', '.join(moved_refs[1])}" if moved_refs else ""))
        out.append("")

    out += _render_calibration(state.get("calibration") or {})

    blockers = state.get("release_blockers") or []
    out += ["## Release blockers", "",
            "\n".join(f"- {b}" for b in blockers) if blockers else "_None._", ""]
    vi = state.get("verified_intact") or []
    if vi:
        # Placed directly after the blockers, not buried mid-report: the
        # confirmation that named invariants held is a headline, not a footnote.
        out += ["## Verified intact", "",
                "\n".join(f"- {v}" for v in vi), ""]
    out += _render_questions(state)
    out += _render_read_first(state)
    out += _render_reading_map(state)
    out += ["## Not tested", ""]
    nt = state.get("not_tested") or []
    out.append("\n".join(f"- {n}" for n in nt) if nt else
               "_Nothing listed — which is itself a reporting failure if the surface was not covered._")
    if prose.get("fix_order"):
        out += ["", "## Fix order", "", prose["fix_order"]]
    if state.get("next_run_focus"):
        out += ["", "## Next run focus", "",
                "\n".join(f"- {n}" for n in state["next_run_focus"])]
    quarantine = state.get("flaky_quarantine") or []
    if quarantine:
        out += ["", "## Quarantine", ""]
        for q in quarantine:
            out.append(f"- `{q.get('test_id')}` until {q.get('quarantined_until')} "
                       f"({q.get('fail_count', '?')}/{q.get('run_count', '?')} runs)")
    if prose.get("notes"):
        out += ["", "## Notes", "", prose["notes"]]
    out += ["", "---", "",
            "*Countable sections rendered from `state.json` by `verdict-finalize`; the "
            "prose is the agent's. They cannot disagree.*"]
    return "\n".join(out).rstrip() + "\n"
