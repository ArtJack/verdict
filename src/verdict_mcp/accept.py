#!/usr/bin/env python3
"""verdict-accept — the maintainer's pen: record that a finding's risk is accepted.

The tester can write three statuses — `open`, `resolved`, `withdrawn` — and none
of them fits a defect the maintainer has decided not to fix. Left open, a
correct finding is re-reported as an open Major in every banner and every
report for the life of the project: the "same twenty findings until you stop
reading" failure this tool was built against. Withdrawn, it is scored as the
tester's error in the track record, which it was not. VERDICT-F-21 sat in
exactly that gap for eight runs — a residual risk accepted and written down in
a decision journal that no artifact here could record as anything but open.

So there is a fourth status, and the tester cannot write it. `accepted` is set
only through this command, which writes `accepted.json` beside `outcomes.json`
in the QA root; the scope guards refuse that file to the verdict agent, and
`validate_judgment` refuses the status in a judgment. `verdict-finalize` folds
the ledger into the next run's state, where the finding reads `accepted`,
leaves the open counts and the release blockers, appears under **Accepted
risks** in every report with its citation, and settles in the outcome ledger
as `confirmed` on the maintainer's word (`outcome_basis: accepted`): the
finding was right; fixing it was declined.

Every entry needs a citation and a reason. An acceptance without a reason is a
mute button, and a mute button is what this status exists to not be.

Usage:
    verdict-accept <project> <finding-id> --cite <ref> --reason <text> [--by <name>]
    verdict-accept <project> <finding-id> --revoke --reason <text> [--by <name>]
    verdict-accept <project> --list

`<project>` is a solo key or a repository path (team mode resolves `<repo>/.qa/`),
exactly as for `verdict-gate`. An acceptance leaves the open counts at once —
the session banner, `verdict-gate`, the MCP server — and leaves the verdict at
the next run: a decision changes the next verdict, never the last one.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from .state import ACCEPTED_FILE, is_open, load_state, norm_status
except ImportError:  # invoked as a bare script
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import ACCEPTED_FILE, is_open, load_state, norm_status  # type: ignore

# A citation or a reason shorter than this is a placeholder, not a record.
MIN_TEXT = 8


def _who() -> str:
    """The name that signs the entry: git's, else the login, else a word."""
    try:
        out = subprocess.run(["git", "config", "user.name"], capture_output=True,
                             text=True, timeout=3)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("USER") or os.environ.get("USERNAME") or "maintainer"


def read_ledger(root: Path) -> dict:
    """The whole file, revoked entries included — this command edits it.

    A corrupt ledger is an error here rather than the empty dict the readers
    use: silently starting a new ledger over a damaged one would lose every
    decision it held."""
    path = Path(root) / ACCEPTED_FILE
    if not path.is_file():
        return {"schema_version": 1, "accepted": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("accepted"), dict):
        raise ValueError(f"{path} is not an accepted-risk ledger")
    return data


def write_ledger(root: Path, data: dict) -> None:
    """Atomic, like every other state write here: a torn ledger would read as
    empty and quietly reopen every accepted finding."""
    path = Path(root) / ACCEPTED_FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _too_short(flag: str, text: str) -> str | None:
    if len((text or "").strip()) < MIN_TEXT:
        return (f"{flag} needs a real {flag[2:]}, not {text!r} — an acceptance without "
                "one is a mute button")
    return None


def accept(root: Path, state: dict, fid: str, citation: str, reason: str,
           by: str, today: str) -> tuple[int, str]:
    """Record the acceptance → (exit code, message)."""
    finding = next((f for f in state.get("findings") or [] if str(f.get("id")) == fid), None)
    if finding is None:
        return 2, (f"no finding {fid!r} in {Path(root) / 'state.json'} — ids are "
                   "case-sensitive; `verdict-gate --format text` lists the open ones")
    status = norm_status(finding.get("status"))
    if not is_open(finding) and status != "accepted":
        return 2, f"{fid} is {status} — a defect that is gone has nothing left to accept"
    for flag, text in (("--cite", citation), ("--reason", reason)):
        problem = _too_short(flag, text)
        if problem:
            return 2, problem
    ledger = read_ledger(root)
    prior = ledger["accepted"].get(fid)
    if prior and not prior.get("revoked"):
        return 2, (f"{fid} is already accepted ({prior.get('on')} by {prior.get('by')}, "
                   f"citing {prior.get('citation')!r}); --revoke it first to change the record")
    entry = {"hash": finding.get("hash"), "severity": finding.get("severity"),
             "title": finding.get("title"), "by": by, "on": today,
             "citation": citation.strip(), "reason": reason.strip()}
    if prior:
        # Accepted, revoked, accepted again: the reversal stays on the record.
        entry["previously"] = prior
    ledger["accepted"][fid] = entry
    write_ledger(root, ledger)
    return 0, (f"accepted {fid} ({finding.get('severity')}) — by {by} on {today}, "
               f"citing {citation.strip()!r}\n"
               f"  ledger: {Path(root) / ACCEPTED_FILE}\n"
               "  effect: out of the open counts now; out of the verdict from the next run")


def revoke(root: Path, state: dict, fid: str, reason: str, by: str, today: str) -> tuple[int, str]:
    ledger = read_ledger(root)
    prior = ledger["accepted"].get(fid)
    if not prior or prior.get("revoked"):
        return 2, (f"{fid} is not an accepted risk in {Path(root) / ACCEPTED_FILE}"
                   + (" — its acceptance was already revoked" if prior else ""))
    problem = _too_short("--reason", reason)
    if problem:
        return 2, problem
    prior["revoked"] = {"by": by, "on": today, "reason": reason.strip()}
    write_ledger(root, ledger)
    return 0, (f"revoked the acceptance of {fid} — by {by} on {today}: {reason.strip()}\n"
               "  effect: counts as open again now; back in the verdict from the next run")


def listing(root: Path) -> str:
    rows = read_ledger(root)["accepted"]
    if not rows:
        return f"no accepted risks recorded in {Path(root) / ACCEPTED_FILE}"
    lines = []
    for fid, e in rows.items():
        standing = (f"revoked {e['revoked'].get('on', '')}" if e.get("revoked") else "in force")
        lines.append(f"{fid:16} {str(e.get('severity') or '?'):9} {standing:20} "
                     f"{e.get('on')} by {e.get('by')} — {e.get('citation')}")
        lines.append(f"{'':16} {e.get('reason')}")
    return "\n".join(lines)


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")   # the Windows cp1252 trap, every CLI
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(
        prog="verdict-accept",
        description="Record a maintainer's decision to accept a finding's risk — the one "
                    "status the tester cannot write.")
    ap.add_argument("project", help="solo project key, or a repository path (team mode)")
    ap.add_argument("finding", nargs="?", help="the finding id, e.g. PRICER-F-007")
    ap.add_argument("--cite", default="", metavar="REF",
                    help="where the decision is written down: a decision log entry, a "
                         "ticket, an ADR, a PR")
    ap.add_argument("--reason", default="", metavar="TEXT",
                    help="why the risk is accepted — in one or two sentences")
    ap.add_argument("--by", default=None, metavar="NAME",
                    help="who accepts it (default: git config user.name)")
    ap.add_argument("--revoke", action="store_true",
                    help="reverse an acceptance; needs --reason")
    ap.add_argument("--list", action="store_true", help="print the ledger and stop")
    ap.add_argument("--today", default=None, help=argparse.SUPPRESS)   # test seam
    args = ap.parse_args(argv)

    state, err = load_state(args.project)
    if err:
        print(f"verdict-accept: {err['error']}", file=sys.stderr)
        return 4
    root = Path(state["_qa_root"])
    try:
        if args.list:
            print(listing(root))
            return 0
        if not args.finding:
            print("verdict-accept: a finding id is required (or --list)", file=sys.stderr)
            return 2
        by = args.by or _who()
        today = args.today or datetime.now(timezone.utc).date().isoformat()
        if args.revoke:
            code, msg = revoke(root, state, args.finding, args.reason, by, today)
        else:
            code, msg = accept(root, state, args.finding, args.cite, args.reason, by, today)
    except ValueError as exc:
        print(f"verdict-accept: {exc}", file=sys.stderr)
        return 2
    print(("verdict-accept: " if code else "") + msg, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    sys.exit(main())
