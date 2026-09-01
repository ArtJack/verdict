#!/usr/bin/env python3
"""verdict-gate — exit-code release gate over Verdict QA state. Stdlib only.

Reads the state file the Verdict agent maintains and turns it into a CI
decision. Runs as an installed console script (`verdict-gate`) or as a bare
script (`python3 src/verdict_mcp/gate.py`) with zero installs — the GitHub
Action's gate mode relies on the latter, so this module must never import
`mcp` or anything else outside the standard library.

Exit codes — distinct on purpose; "the tester never ran" must not look like
"the tester said no":

  0  pass — or "pass with risks" under the default --fail-on fail
  1  fail — or "pass with risks" when --fail-on risks
  2  usage error (argparse convention)
  3  blocked — the tester ran and could not verify
  4  no state / unreadable state — the tester never ran
  5  stale state — --max-age-hours exceeded, run_number below
     --min-run-number, or the code has moved past what was tested
     (--max-commits-behind)
  6  hand-written state — --require-harness set and the run did not go
     through verdict-facts / verdict-finalize

The stale check exists to close the loop race: capture run_number before
launching the QA run, then gate with --min-run-number <n+1> — a run that died
without writing state can no longer launder the previous verdict.

--max-commits-behind closes the other half. A verdict ages in commits as well
as in hours, and this repository's own state once carried a `pass with risks`
whose three open Majors had all been fixed and merged. Gating a merge on a
verdict measured against code that has since moved is a false green at the
most expensive moment there is. Opt-in, like the other two staleness flags,
and deliberately silent when the distance cannot be measured — a gate that
fails on a shallow clone is a gate people route around.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .project_key import derive_key
    from .state import (code_drift, harness_signals, is_open, load_runs,
                    load_state, missing_durable, order_findings,
                    parse_timestamp, repo_for_root, resolve_root,
                    verify_chain)
except ImportError:  # executed as a bare script (GitHub Action gate mode)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from project_key import derive_key
    from state import (code_drift, harness_signals, is_open, load_runs,
                   load_state, missing_durable, order_findings,
                   parse_timestamp, repo_for_root, resolve_root,
                   verify_chain)

MARKER = "<!-- verdict-gate -->"


def _resolve_project(arg):
    if arg:
        return arg, arg
    if resolve_root(".") is not None:
        return ".", "team-mode .qa/ in the working directory"
    key, source = derive_key(".")
    return key, f"solo key {key!r} (from {source})"


def evaluate(project, fail_on, max_age_hours, min_run_number, now=None,
             require_harness=False, max_commits_behind=None):
    """Pure gate decision → a dict with exit_code, reason, and the state facts."""
    state, err = load_state(project)
    if err:
        return {"exit_code": 4, "verdict": None, "reason": err["error"],
                "known_projects": err.get("known_projects", []), "project": project}
    verdict = state.get("verdict")
    last = state.get("last_run") or {}
    out = {
        "project": state.get("project", project),
        "verdict": verdict,
        "run_number": state.get("run_number"),
        "run_type": state.get("run_type"),
        "last_run_utc": last.get("timestamp_utc"),
        "sha_range": last.get("sha_range"),
        "report": last.get("report"),
        "release_blockers": state.get("release_blockers", []),
        "not_tested": state.get("not_tested", []),
        "findings_open": order_findings(
            [f for f in state.get("findings", []) if is_open(f)]),
    }
    if verdict not in ("pass", "pass with risks", "blocked", "fail"):
        out.update(exit_code=4, reason=f"state has no usable verdict: {verdict!r}")
        return out
    if min_run_number is not None and (state.get("run_number") or 0) < min_run_number:
        out.update(exit_code=5, reason=(
            f"stale: run_number {state.get('run_number')} < required {min_run_number} "
            "— the expected QA run never wrote state"))
        return out
    if max_age_hours is not None:
        ts = parse_timestamp(str(last.get("timestamp_utc") or ""))
        now = now or datetime.now(timezone.utc)
        if ts is None or (now - ts).total_seconds() > max_age_hours * 3600:
            out.update(exit_code=5, reason=(
                f"stale: last run at {last.get('timestamp_utc')!r} is older than "
                f"{max_age_hours}h (or unparseable)"))
            return out
    # Drift is measured on every run and gated only on request. Tying the
    # measurement to `--max-commits-behind` meant a gate invoked without the
    # flag could not say the verdict describes a different commit — and the PR
    # comment, the one surface an outside reader actually sees, is exactly the
    # invocation that runs without it. This repository's own comment advertised
    # three long-fixed Majors as `NEW · 0d` with nothing marking the state as
    # measured elsewhere, while the SessionStart banner, computing the same
    # drift unconditionally, said so plainly. Reporting welded to enforcing goes
    # silent the moment enforcing is off, which is the same shape as a check
    # that cannot fire: what the reader sees is a clean, current-looking report.
    # Recorded unconditionally, including `unknown`: a JSON consumer that sees
    # the key can tell "we looked and could not tell" from "we never looked",
    # and those are different facts. Whether any of it is worth *saying* is one
    # decision, made once, in `_drift_note` — which stays silent on `unknown`,
    # because a staleness note nobody can act on costs the real one its
    # credibility.
    drift = out["code_drift"] = code_drift(
        repo_for_root(resolve_root(project)), last.get("git_sha"))
    if max_commits_behind is not None:
        if drift["status"] == "diverged":
            out.update(exit_code=5, reason=(
                "stale: the tested commit is not in this branch's history — the "
                "stored verdict describes code this checkout never had"))
            return out
        if drift["status"] == "behind" and drift["commits"] > max_commits_behind:
            out.update(exit_code=5, reason=(
                f"stale: measured {drift['commits']} commits ago, limit is "
                f"{max_commits_behind} — the code has moved past what was tested"))
            return out

    # A state whose recorded verdict contradicts its own recorded findings is
    # not a verdict, it is a contradiction, and serving it green is how a
    # false pass reaches a merge. §10 is the arbiter: an open Blocker admits
    # no verdict but `fail`, and an open Critical caps at `pass with risks`.
    # The gate does not re-adjudicate — it refuses to launder.
    blockers = [f.get("id") for f in out["findings_open"]
                if f.get("severity") == "Blocker"]
    criticals = [f.get("id") for f in out["findings_open"]
                 if f.get("severity") == "Critical"]
    if blockers and verdict != "fail":
        out.update(exit_code=1, reason=(
            f"the recorded verdict {verdict!r} stands over open Blocker(s) "
            f"{', '.join(str(b) for b in blockers)} — §10 admits no verdict but `fail` "
            "over an open Blocker, so this state contradicts itself"))
        return out
    if criticals and verdict == "pass":
        out.update(exit_code=1, reason=(
            f"the recorded verdict is `pass` over open Critical(s) "
            f"{', '.join(str(c) for c in criticals)} — §10 caps that at `pass with risks`, "
            "so this state contradicts itself"))
        return out

    if require_harness:
        signals = harness_signals(state, state.get("_qa_root"))
        # Only the durable traces decide. A team-mode `.qa/` checked out fresh
        # has no facts.json or judgment.json — they are per-run scratch — and
        # refusing over their absence would fail the exact deployment this
        # check exists for.
        # An unsigned history is not a failure — every project is unsigned until
        # its next harness run, and failing them all would be a migration by
        # ambush. It is said out loud, because a project that silently cannot be
        # protected looks exactly like one that is.
        rows, _ = load_runs(state.get("_qa_root") or ".")
        if verify_chain(rows)["status"] == "unchained":
            out["chain"] = "unchained"
        missing = missing_durable(signals)
        if missing:
            out.update(exit_code=6, harness=signals, reason=(
                "hand-written state: this run did not go through verdict-facts → "
                "judgment.json → verdict-finalize (" + ", ".join(missing) + "). "
                "Everything the harness measures was composed instead of measured"))
            return out
        out["harness"] = signals
    if verdict == "blocked":
        out.update(exit_code=3, reason="blocked: the tester could not verify")
    elif verdict == "fail":
        out.update(exit_code=1, reason="fail")
    elif verdict == "pass with risks":
        if fail_on == "risks":
            out.update(exit_code=1, reason="pass with risks, and --fail-on risks is set")
        else:
            out.update(exit_code=0, reason="pass with risks (accepted under --fail-on fail)")
    else:
        out.update(exit_code=0, reason="pass")
    return out


def _drift_note(r):
    """One line saying the verdict describes different code, or nothing at all.

    Shared by the text and comment renderers so the two surfaces cannot drift
    apart — the failure being fixed here was precisely one surface knowing
    something the other could not say.
    """
    drift = r.get("code_drift") or {}
    if drift.get("status") == "diverged":
        return ("measured on a commit that is not in this branch's history — this "
                "verdict describes different code")
    if drift.get("status") == "behind" and drift.get("commits"):
        n = drift["commits"]
        return (f"measured {n} commit{'s' if n != 1 else ''} ago — the code has moved "
                "since this verdict was written")
    return None


def _fmt_text(r, n):
    lines = [f"VERDICT: {r.get('verdict') or 'no state'} → exit {r['exit_code']} ({r['reason']})"]
    if r.get("run_number") is not None:
        lines.append(f"run {r['run_number']} ({r.get('run_type')}) · {r.get('last_run_utc')} · {r.get('sha_range')}")
    if note := _drift_note(r):
        lines.append(note)
    if r.get("release_blockers"):
        lines.append("release blockers: " + ", ".join(r["release_blockers"]))
    for f in (r.get("findings_open") or [])[:n]:
        lines.append(f"  {f.get('delta', '?'):<10} {f.get('id')} "
                     f"{f.get('severity')}/{f.get('priority')} {f.get('title', '')}")
    if r.get("not_tested"):
        lines.append("not tested: " + "; ".join(map(str, r["not_tested"])))
    if r.get("chain") == "unchained":
        lines.append("note: this run history is unsigned — one verdict-finalize run "
                     "signs it, after which a hand-edited state cannot pass")
    if r.get("report"):
        lines.append(f"report: {r['report']}")
    if r.get("known_projects"):
        lines.append("known projects: " + ", ".join(r["known_projects"]))
    return "\n".join(lines)


def _fmt_comment(r, n):
    v = r.get("verdict") or "no state"
    head = [MARKER,
            f"## Verdict: **{v}** — {r.get('project')} "
            f"(run {r.get('run_number')}, {r.get('run_type')})",
            "", f"_{r['reason']}_", ""]
    # Above the findings table, not below it: every row beneath this line has to
    # be read differently once you know the verdict was measured elsewhere, and
    # a note under the table arrives after the reader has already believed it.
    if note := _drift_note(r):
        head += ["> [!WARNING]", f"> Stale: {note}.", ""]
    if r.get("release_blockers"):
        head.append("**Release blockers:** " + ", ".join(r["release_blockers"]))
        head.append("")
    rows = (r.get("findings_open") or [])[:n]
    if rows:
        head += ["| Δ | ID | Sev/Pri | Age | Finding |", "|---|---|---|---|---|"]
        for f in rows:
            title = str(f.get("title", "")).replace("|", "\\|")
            head.append(
                f"| {f.get('delta', '')} | {f.get('id', '')} "
                f"| {f.get('severity', '')}/{f.get('priority', '')} "
                f"| {f.get('age_days', '')}d | {title} |")
        overflow = len(r.get("findings_open") or []) - len(rows)
        if overflow > 0:
            head.append(f"\n<sub>…and {overflow} more open findings — see the report.</sub>")
        head.append("")
    if r.get("not_tested"):
        head.append("**Not tested:** " + "; ".join(map(str, r["not_tested"])))
        head.append("")
    tail = [f"<sub>Report: `{r.get('report')}` · {r.get('sha_range')} · "
            f"last run {r.get('last_run_utc')} · gate exit {r['exit_code']}</sub>"]
    return "\n".join(head + tail)


_SARIF_LEVEL = {"Blocker": "error", "Critical": "error",
                "Major": "warning", "Minor": "note", "Trivial": "note"}
_EVIDENCE_LOC = re.compile(r"([\w./\\-]+\.[A-Za-z0-9_]+):(\d+)")


def _fmt_sarif(r):
    """SARIF 2.1.0 over the open findings — one result each, level mapped from
    severity, location parsed from the first file:line in the evidence. Feed it
    to github/codeql-action/upload-sarif and findings land in the Security tab."""
    results, rules = [], {}
    for f in r.get("findings_open") or []:
        fid = str(f.get("id") or "VERDICT-F-?")
        sev = str(f.get("severity") or "").strip().capitalize()
        if fid not in rules:
            rules[fid] = {
                "id": fid,
                "shortDescription": {"text": str(f.get("title") or fid)[:120]},
            }
        message = str(f.get("title") or fid)
        evidence = [str(e) for e in f.get("evidence") or []]
        if evidence:
            message += " — evidence: " + "; ".join(evidence)[:400]
        result = {
            "ruleId": fid,
            "level": _SARIF_LEVEL.get(sev, "warning"),
            "message": {"text": message},
        }
        for ev in evidence:
            m = _EVIDENCE_LOC.search(ev)
            if m:
                result["locations"] = [{
                    "physicalLocation": {
                        "artifactLocation": {"uri": m.group(1).replace("\\", "/")},
                        "region": {"startLine": int(m.group(2))},
                    }
                }]
                break
        results.append(result)
    return json.dumps({
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "verdict-gate",
                "informationUri": "https://github.com/ArtJack/verdict",
                "rules": list(rules.values()),
            }},
            "results": results,
        }],
    }, indent=2)


def _fmt_github_output(r):
    return "\n".join([
        f"verdict={r.get('verdict') or 'none'}",
        f"exit-code={r['exit_code']}",
        f"blockers={json.dumps(r.get('release_blockers', []))}",
        f"report-path={r.get('report') or ''}",
    ])


def main(argv=None) -> int:
    try:
        # The comment format contains Δ and · — Windows consoles default to a
        # legacy codepage that cannot encode them.
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass
    ap = argparse.ArgumentParser(
        prog="verdict-gate",
        description="Exit-code release gate over Verdict QA state.",
        epilog="Exit codes: 0 gate passes · 1 verdict fails the gate · 2 usage "
               "· 3 blocked · 4 no state (tester never ran) · 5 stale state.")
    ap.add_argument("project", nargs="?", default=None,
                    help="project key or repo path; default: team .qa/ here, "
                         "else the solo key derived from this checkout")
    ap.add_argument("--fail-on", choices=("fail", "risks"), default="fail",
                    help="which verdicts fail the gate; 'risks' also fails "
                         "'pass with risks'. 'blocked' always exits 3.")
    ap.add_argument("--max-age-hours", type=float, default=None)
    ap.add_argument("--min-run-number", type=int, default=None)
    ap.add_argument("--max-commits-behind", type=int, default=None,
                    help="fail when the tested commit is more than N behind "
                         "HEAD, or not in its history at all")
    ap.add_argument("--require-harness", action="store_true",
                    help="exit 6 unless the state was produced by verdict-facts / "
                         "verdict-finalize rather than written by hand")
    ap.add_argument("--findings", type=int, default=10, metavar="N",
                    help="max findings rendered (default 10)")
    ap.add_argument("--format",
                    choices=("text", "json", "github-comment", "github-output", "sarif"),
                    default="text")
    args = ap.parse_args(argv)

    project, how = _resolve_project(args.project)
    result = evaluate(project, args.fail_on, args.max_age_hours, args.min_run_number,
                      max_commits_behind=args.max_commits_behind,
                      require_harness=args.require_harness)
    result["resolved_via"] = how

    if args.format == "json":
        print(json.dumps(result, indent=2))
    elif args.format == "github-comment":
        print(_fmt_comment(result, args.findings))
    elif args.format == "github-output":
        print(_fmt_github_output(result))
    elif args.format == "sarif":
        print(_fmt_sarif(result))
    else:
        print(_fmt_text(result, args.findings))
    return result["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
