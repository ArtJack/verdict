#!/usr/bin/env python3
"""verdict-issues: file each open finding as a GitHub issue, once.

The findings live in a state file only the QA loop reads. The people who fix
things live in the issue tracker. Until these met, a finding waited for someone
to open the report — and on Sales, 75 open findings waited across four runs.

Dry-run by default. Nothing leaves the machine until `--create`, and what would
leave is printed first, title by title. Creation goes through the `gh` CLI, so
the credential is the operator's own login and never a token this tool holds.
A ledger beside the state (`issues.json`) records which finding became which
issue, so a re-run files nothing twice; the state itself is never touched — it
is finalize's, and it is chain-signed.

Not in this version, on purpose: closing or commenting on issues when findings
resolve. A closed issue is a human's claim; `fix_verified` is the harness's.
Conflating them would let the tracker overrule the measurement.

Usage:
    verdict-issues [PROJECT_OR_PATH]              # dry run: what would be filed
    verdict-issues [PROJECT_OR_PATH] --create     # file them
    verdict-issues . --create --label verdict --limit 10
"""

# Lazy annotations, so this module IMPORTS on the interpreter it is actually
# invoked with. `hooks.json` and the agent contract both spell it `python3`, and on
# a stock Mac that is /usr/bin/python3 = 3.9, where `str | None` is evaluated at
# function-definition time and raises TypeError. The Bash guard died that way while
# the write guard beside it kept denying, so a strict session looked armed with half
# its controls missing (VERDICT-F-55). `requires-python` binds pip; a plugin is not
# installed by pip.
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .state import fold_accepted, is_open, load_accepted, load_state, order_findings, repo_for_root
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import fold_accepted, is_open, load_accepted, load_state, order_findings, repo_for_root

ISSUES_FILE = "issues.json"
MARKER = "<!-- verdict-finding:{id} -->"


def load_ledger(root: Path) -> dict:
    path = Path(root) / ISSUES_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_ledger(root: Path, ledger: dict) -> None:
    path = Path(root) / ISSUES_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def render_issue(finding: dict, state: dict, prior: dict | None = None) -> tuple[str, str]:
    """(title, body). The body is the finding as the report would show it —
    evidence and all — plus a marker so the issue can be found again. `prior`
    is the ledger entry this finding was filed under before it came back."""
    fid = str(finding.get("id") or "?")
    sev = finding.get("severity") or "?"
    again = " (recurrence)" if prior else ""
    title = f"[Verdict] {fid} · {sev}{again}: {finding.get('title') or '(untitled)'}"[:250]
    last = state.get("last_run") or {}
    lines = [
        f"**{sev} / {finding.get('priority') or '?'}** · "
        f"{finding.get('failure_classification') or 'unclassified'} · "
        f"confidence {finding.get('confidence') or 'n/a'} · "
        f"first seen {finding.get('first_seen') or '?'} · open {finding.get('age_days', '?')}d",
        "",
        "**Evidence**",
    ]
    lines += [f"- {e}" for e in (finding.get("evidence") or [])] or ["- (none cited)"]
    if finding.get("root_cause"):
        rc = finding["root_cause"]
        lines += ["", f"**Root cause** — {rc.get('mechanism') or ''}".rstrip()]
    if prior:
        was = prior.get("url") or (f"#{prior['number']}" if prior.get("number") else "an earlier run")
        lines += ["", f"**Recurrence** — this finding was resolved and has come back. "
                      f"Previously filed as {was} (run {prior.get('run_number')})."]
    lines += ["", f"Filed by Verdict run {state.get('run_number')} "
                  f"(verdict `{state.get('verdict')}`, {last.get('timestamp_utc')}) · "
                  f"report `{last.get('report')}`",
              "", MARKER.format(id=fid)]
    return title, "\n".join(lines)


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def plan(state: dict, ledger: dict, limit: int | None = None) -> list[tuple[dict, str]]:
    """Open findings paired with the action they need: `create`, `refile` or
    `exists`. Severity order, so a cap files the worst first.

    The ledger key is the finding id, which by contract is minted once and
    never reused — so membership answers "has this finding ever been filed",
    while the question a tracker needs answered is "has this *occurrence* been
    filed". A REGRESSED finding — the class the contract ranks first — was
    therefore never re-filed, and the run reported it as already filed while
    its issue sat closed (VERDICT-F-27).

    The discriminator is `regressed_at_run`, which the harness stamps when the
    finding came back and carries forward afterwards — not `delta`, which
    describes only the transition one run computed and made the filing window
    exactly one run wide (VERDICT-F-34). A recurrence is filed once per
    regression, whenever this next runs; filing again over the same regression
    is what the recorded run number prevents.
    """
    out = []
    for f in order_findings([f for f in state.get("findings", []) if is_open(f)]):
        prior = ledger.get(str(f.get("id") or ""))
        came_back = f.get("regressed_at_run")
        if came_back is None and f.get("delta") == "REGRESSED":
            came_back = state.get("run_number")  # a state written before 0.63.0
        if not prior:
            action = "create"
        elif came_back is not None and _num(came_back) > _num(prior.get("run_number")):
            action = "refile"
        else:
            action = "exists"
        out.append((f, action))
    if limit is not None:
        creates = 0
        kept = []
        for f, action in out:
            if action in ("create", "refile"):
                if creates >= limit:
                    kept.append((f, "deferred"))
                    continue
                creates += 1
            kept.append((f, action))
        out = kept
    return out


def create_issue(gh_cmd: str, cwd, title: str, body: str, labels: list, repo: str | None):
    """→ {"number", "url"} or raises RuntimeError with gh's own words.

    The body travels as a file, not an argument: it is multi-line, and a
    multi-line argument survives neither cmd.exe nor a long evidence list.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
        fh.write(body)
        body_path = fh.name
    cmd = [gh_cmd, "issue", "create", "--title", title, "--body-file", body_path]
    for label in labels:
        cmd += ["--label", label]
    if repo:
        cmd += ["--repo", repo]
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    finally:
        try:
            os.unlink(body_path)
        except OSError:
            pass
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout).strip() or f"gh exited {proc.returncode}")
    url = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    number = url.rstrip("/").rsplit("/", 1)[-1]
    return {"number": int(number) if number.isdigit() else None, "url": url}


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(
        prog="verdict-issues",
        description="File each open finding as a GitHub issue, once. Dry-run unless --create.")
    ap.add_argument("project", nargs="?", default=".",
                    help="project key or path (default: team-mode .qa/ in the cwd)")
    ap.add_argument("--create", action="store_true",
                    help="actually create the issues (default: print what would be created)")
    ap.add_argument("--repo", default=None,
                    help="owner/name to file in (default: whatever `gh` infers from the repository)")
    ap.add_argument("--label", action="append", default=[],
                    help="label to apply; repeatable. Must already exist in the repository")
    ap.add_argument("--limit", type=int, default=20,
                    help="at most N new issues per run, worst severity first (default 20)")
    ap.add_argument("--format", choices=("text", "json"), default="text")
    ap.add_argument("--gh-cmd", default="gh", help=argparse.SUPPRESS)  # test seam
    args = ap.parse_args(argv)

    state, err = load_state(args.project)
    if err:
        print(f"verdict-issues: {err['error']}", file=sys.stderr)
        return 4
    root = Path(state.get("_qa_root") or ".")
    # An accepted risk is the maintainer's decision, not an issue to open on them.
    state["findings"] = fold_accepted(state.get("findings", []), load_accepted(root))
    ledger = load_ledger(root)
    todo = plan(state, ledger, args.limit)
    creates = [(f, a) for f, a in todo if a in ("create", "refile")]
    refiles = sum(1 for _, a in creates if a == "refile")
    exists = sum(1 for _, a in todo if a == "exists")
    deferred = sum(1 for _, a in todo if a == "deferred")

    if not args.create:
        if args.format == "json":
            print(json.dumps({"would_create": [
                {"id": f.get("id"), "severity": f.get("severity"), "recurrence": a == "refile",
                 "title": render_issue(f, state, ledger.get(str(f.get("id"))) if a == "refile"
                                       else None)[0]}
                for f, a in creates],
                "already_filed": exists, "deferred": deferred, "recurrences": refiles}, indent=2))
        else:
            print(f"verdict-issues: dry run — {len(creates)} would be created "
                  f"({refiles} of them recurrences), {exists} already filed, "
                  f"{deferred} deferred by --limit")
            for f, a in creates:
                prior = ledger.get(str(f.get("id"))) if a == "refile" else None
                print("  " + render_issue(f, state, prior)[0])
            if creates:
                print("re-run with --create to file them")
        return 0

    cwd = repo_for_root(root)
    filed, failed = [], None
    for f, action in creates:
        fid = str(f.get("id"))
        prior = ledger.get(fid) if action == "refile" else None
        title, body = render_issue(f, state, prior)
        try:
            made = create_issue(args.gh_cmd, cwd, title, body, args.label, args.repo)
        except (RuntimeError, OSError) as exc:
            failed = (fid, str(exc))
            break
        ledger[fid] = {**made, "hash": f.get("hash"),
                       "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "run_number": state.get("run_number")}
        if prior:
            # The issue this recurrence replaces is not lost: someone closed it,
            # and the trail from the new one back to it is the whole story.
            ledger[fid]["previous"] = [*(prior.get("previous") or []),
                                       {k: prior.get(k) for k in
                                        ("number", "url", "created_at", "run_number")}]
        save_ledger(root, ledger)  # after every success: a crash mid-run files nothing twice
        filed.append((fid, made))
    if args.format == "json":
        print(json.dumps({"created": [{"id": i, **m} for i, m in filed],
                          "already_filed": exists, "deferred": deferred, "recurrences": refiles,
                          "failed": ({"id": failed[0], "error": failed[1]} if failed else None)},
                         indent=2))
    else:
        for fid, made in filed:
            print(f"verdict-issues: {fid} → {made.get('url') or made.get('number')}")
        print(f"verdict-issues: created {len(filed)} ({refiles} recurrence), "
              f"{exists} already filed, {deferred} deferred by --limit")
        if failed:
            print(f"verdict-issues: stopped at {failed[0]}: {failed[1]} — the ledger records "
                  "what was filed before it; re-run to continue", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
