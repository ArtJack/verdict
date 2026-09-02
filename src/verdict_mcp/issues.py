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

import argparse
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from .state import is_open, load_state, order_findings, repo_for_root
except ImportError:  # bare-script execution
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import is_open, load_state, order_findings, repo_for_root

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


def render_issue(finding: dict, state: dict) -> tuple[str, str]:
    """(title, body). The body is the finding as the report would show it —
    evidence and all — plus a marker so the issue can be found again."""
    fid = str(finding.get("id") or "?")
    sev = finding.get("severity") or "?"
    title = f"[Verdict] {fid} · {sev}: {finding.get('title') or '(untitled)'}"[:250]
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
    lines += ["", f"Filed by Verdict run {state.get('run_number')} "
                  f"(verdict `{state.get('verdict')}`, {last.get('timestamp_utc')}) · "
                  f"report `{last.get('report')}`",
              "", MARKER.format(id=fid)]
    return title, "\n".join(lines)


def plan(state: dict, ledger: dict, limit: int | None = None) -> list[tuple[dict, str]]:
    """Open findings paired with the action they need: `create` or `exists`.
    Severity order, so a cap files the worst first."""
    out = []
    for f in order_findings([f for f in state.get("findings", []) if is_open(f)]):
        fid = str(f.get("id") or "")
        out.append((f, "exists" if fid in ledger else "create"))
    if limit is not None:
        creates = 0
        kept = []
        for f, action in out:
            if action == "create":
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
    ledger = load_ledger(root)
    todo = plan(state, ledger, args.limit)
    creates = [(f, a) for f, a in todo if a == "create"]
    exists = sum(1 for _, a in todo if a == "exists")
    deferred = sum(1 for _, a in todo if a == "deferred")

    if not args.create:
        if args.format == "json":
            print(json.dumps({"would_create": [{"id": f.get("id"), "severity": f.get("severity"),
                                                "title": render_issue(f, state)[0]}
                                               for f, _ in creates],
                              "already_filed": exists, "deferred": deferred}, indent=2))
        else:
            print(f"verdict-issues: dry run — {len(creates)} would be created, "
                  f"{exists} already filed, {deferred} deferred by --limit")
            for f, _ in creates:
                print("  " + render_issue(f, state)[0])
            if creates:
                print("re-run with --create to file them")
        return 0

    cwd = repo_for_root(root)
    filed, failed = [], None
    for f, _ in creates:
        fid = str(f.get("id"))
        title, body = render_issue(f, state)
        try:
            made = create_issue(args.gh_cmd, cwd, title, body, args.label, args.repo)
        except (RuntimeError, OSError) as exc:
            failed = (fid, str(exc))
            break
        ledger[fid] = {**made, "hash": f.get("hash"),
                       "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "run_number": state.get("run_number")}
        save_ledger(root, ledger)  # after every success: a crash mid-run files nothing twice
        filed.append((fid, made))
    if args.format == "json":
        print(json.dumps({"created": [{"id": i, **m} for i, m in filed],
                          "already_filed": exists, "deferred": deferred,
                          "failed": ({"id": failed[0], "error": failed[1]} if failed else None)},
                         indent=2))
    else:
        for fid, made in filed:
            print(f"verdict-issues: {fid} → {made.get('url') or made.get('number')}")
        print(f"verdict-issues: created {len(filed)}, {exists} already filed, "
              f"{deferred} deferred by --limit")
        if failed:
            print(f"verdict-issues: stopped at {failed[0]}: {failed[1]} — the ledger records "
                  "what was filed before it; re-run to continue", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
