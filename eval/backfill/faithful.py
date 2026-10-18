#!/usr/bin/env python3
"""Backfill faithfulness: does a repro `verdict-backfill` kept test the finding, or something near it?

A kept repro reproduces at the record's commit, which says the script fails there, not that it
fails because of the defect the finding names. The ground truth here is a known fix: a repro that
tests the finding reproduces at the defect's commit and stops reproducing once the fix is applied.
For each case, this harness runs the backfill exactly as the command does (the local model, up to
three drafts, the sandbox), then applies the case's minimal fix to a fresh checkout and runs the
kept repro there.

    python3 eval/backfill/faithful.py ~/.claude/verdict-bench/backfill-cases.json \\
        --env-file ~/.config/verdict-gateway.env --model chat-120b

A case file (it can live outside this repository) lists, per case: the repository and commit,
the finding (inline, or `{"state": path, "id": ...}` to read it from a record), the interpreter,
and the fix as exact replacements `{"path", "old", "new"}`, each of which must match once. No
Claude tokens.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from verdict_mcp import backfill, replay  # noqa: E402
from verdict_mcp.small import Model, read_env_file  # noqa: E402


def finding_of(case: dict) -> dict:
    f = case["finding"]
    if "state" in f:
        state = json.loads(Path(f["state"]).expanduser().read_text(encoding="utf-8"))
        return next(x for x in state["findings"] if str(x.get("id")) == f["id"])
    return f


def with_fix(repo: Path, sha: str, fix: list, qa: Path, repro: dict, timeout: int) -> dict:
    """The kept repro run on a fresh checkout of `sha` with the fix applied."""
    scratch, _sha, problem = replay._fresh_checkout(repo, sha)
    if scratch is None:
        return {"result": "could not run", "checks": [problem]}
    try:
        for r in fix:
            target = scratch / r["path"]
            text = target.read_text(encoding="utf-8")
            if text.count(r["old"]) != 1:
                return {"result": "could not run", "checks": [f"fix does not match once in {r['path']}"]}
            target.write_text(text.replace(r["old"], r["new"], 1), encoding="utf-8")
        row = replay.replay_one({"id": "fix", "repro": repro}, repo, scratch, qa, timeout, unattended=True)
    finally:
        replay._remove_checkout(repo, scratch)
    return {"result": row["result"], "checks": row.get("checks", [])[:2],
            "tail": str(row.get("output_tail") or "")[-300:]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="faithful", description=__doc__.split("\n\n")[0])
    ap.add_argument("cases", type=Path)
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--model", default="chat-120b")
    ap.add_argument("--attempts", type=int, default=backfill.ATTEMPTS)
    ap.add_argument("--timeout", type=int, default=120)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    env = dict(os.environ, **read_env_file(args.env_file))
    model = Model(args.model, env["ANTHROPIC_BASE_URL"], env["ANTHROPIC_AUTH_TOKEN"])
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    results = []
    for case in cases:
        if args.only and case["name"] not in args.only:
            continue
        repo = Path(case["repo"]).expanduser()
        qa = Path(tempfile.mkdtemp(prefix="faithful-"))
        row = backfill.backfill_one(model, repo, qa, finding_of(case), case["python"], args.timeout,
                                    head_ref=case["sha"], attempts=args.attempts)
        out = {"name": case["name"], "verdict": row["verdict"][:90], "attempts": row.get("attempts"),
               **({"draft": row["draft"]} if row.get("draft") else {})}
        if row["verdict"].startswith(backfill.STILL_BROKEN):
            fixed = with_fix(repo, case["sha"], case["fix"], qa, row["repro"], args.timeout)
            out["with_fix"] = fixed["result"]
            out["faithful"] = fixed["result"] == "not reproduced"
            out["fix_checks"] = fixed.get("checks")
            out["script"] = str(Path(qa).joinpath(*backfill.SCRIPT_DIR, f"{row['id']}.py"))
        results.append(out)
        mark = ("faithful" if out.get("faithful") else "NOT faithful" if "with_fix" in out else "no repro kept")
        print(f"{case['name']:28} {mark:14} attempts {out.get('attempts')} · {out['verdict'][:70]}"
              + (f" · with the fix: {out['with_fix']}" if "with_fix" in out else ""))
    kept = [r for r in results if "with_fix" in r]
    print(f"\n{len(results)} case(s): {len(kept)} kept, {sum(1 for r in kept if r['faithful'])} faithful "
          f"(stop reproducing under the known fix) · {model.calls} call(s) to {model.name}, no Claude tokens")
    if args.out:
        args.out.write_text(json.dumps(results, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
