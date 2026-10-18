#!/usr/bin/env python3
"""Packet recall: does an escalation run's packet point at the defects known to be there? No Claude tokens.

`verdict-run --escalate` hands the tester a packet the breadth pass composed, and the tester reads
little beyond it, so a defect the packet never points at is found only by luck. This harness
measures that ceiling for each case of the recall benchmark: it measures the case's commit
(`verdict-facts`, into a scratch QA root holding only the case's profile), runs the breadth pass
exactly as `--escalate` does (`verdict-local` in a scratch copy, the same caps), composes the packet,
and counts a known defect as pointed at when the packet cites one of its anchor files. It prints
which kind of item cited it: a claim the local tier proved, a census survivor, the reading map, an
unproven reading, a lead.

    python3 eval/recall/packet_recall.py ~/.claude/verdict-bench/recall-cases.json \\
        --env-file ~/.config/verdict-gateway.env --model chat-120b --out /tmp/packet.json

The local model's calls are the only model calls. A score is n=1 until repeated: the breadth pass
reads with a sampling model.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from verdict_mcp import escalate  # noqa: E402

KINDS = ("Proven by counterfactual", "Census survivor", "Read first", "Named in the risk focus",
         "Unproven reading", "Lead", "Owed a model run")
BIN = Path(sys.executable).parent


def _head(repo: Path) -> str:
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True).stdout.strip()


def cited_by(packet: str, anchors) -> list:
    """The kinds of packet item that cite any of the anchor files, in packet order."""
    kinds = []
    for line in packet.splitlines():
        m = re.match(r"- \*\*(.+?)\*\* ·", line)
        if m and any(str(a) in line for a in anchors or []) and m.group(1) not in kinds:
            kinds.append(m.group(1))
    return kinds


def score(case: dict, packet: str, out: dict) -> dict:
    out["per_defect"] = []
    for d in case.get("defects") or []:
        kinds = cited_by(packet, d.get("anchors"))
        out["per_defect"].append({"id": d.get("id"), "pointed": bool(kinds), "by": kinds})
    out["pointed"] = sum(1 for p in out["per_defect"] if p["pointed"])
    return out


def recompose(case: dict, work: Path) -> dict:
    """Score a new packet from a kept run (`--keep`): the breadth pass is not repeated."""
    key = case["key"]
    out = {"key": key, "defects": len(case.get("defects") or [])}
    scratch, root = work / f"{key}.scratch", work / key
    if not scratch.is_dir():
        out["skipped"] = f"no kept scratch root in {work}"
        return out
    measured = json.loads((root / "facts.json").read_text(encoding="utf-8"))
    # The focus is recomputed from the profile, so a change to focus.py is measured too; the
    # breadth pass's own readings are the kept ones.
    from verdict_mcp.focus import risk_focus
    from verdict_mcp.harness import is_test_file
    refocused = risk_focus(Path(measured.get("repo") or "."),
                           (root / "profile.md").read_text(encoding="utf-8"), is_test_file)
    if refocused:
        measured["risk_focus"] = refocused
    packet, summary = escalate.compose(scratch, measured, 2.5)
    (work / f"{key}.packet.md").write_text(packet, encoding="utf-8")
    out["summary"] = {k: summary.get(k) for k in ("leads", "not_listed", "proven_local", "unproven_local",
                                                  "unfiled_leads", "survivor_functions", "local_calls")}
    out["census"] = (measured.get("assertion_gaps") or {}).get("status")
    out["read_first"] = len(((measured.get("read_first") or {}).get("items")) or [])
    return score(case, packet, out)


def run_case(case: dict, repos: Path, work: Path, args) -> dict:
    key = case["key"]
    repo = repos / key
    out = {"key": key, "defects": len(case.get("defects") or [])}
    if not repo.is_dir() or _head(repo) != case["sha"]:
        out["skipped"] = f"{repo} is not at {case['sha'][:12]}"
        return out
    root = work / key
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    shutil.copy2(Path(case["qa_root_of_record"]).expanduser() / "profile.md", root / "profile.md")
    env = dict(os.environ, VERDICT_ASSERTION_GAPS="on", PYTHONDONTWRITEBYTECODE="1")
    env.pop("CLAUDECODE", None)
    started = time.monotonic()
    facts = subprocess.run([str(BIN / "verdict-facts"), "--repo", str(repo), "--qa-root", str(root)],
                           env=env, capture_output=True, text=True, timeout=args.facts_timeout)
    out["facts_s"] = round(time.monotonic() - started)
    if facts.returncode != 0:
        out["skipped"] = f"verdict-facts exited {facts.returncode}: {(facts.stderr or '').strip()[-200:]}"
        return out
    scratch = escalate.scratch_copy(root)
    try:
        argv = escalate.local_argv(repo, scratch, root, args.model, args.limit, None, args.env_file)
        if args.max_functions:
            i = argv.index("--max-functions")
            argv[i + 1] = str(args.max_functions)
        started = time.monotonic()
        local = subprocess.run([str(BIN / "verdict-local"), *argv], env=env, capture_output=True,
                               text=True, timeout=args.local_timeout)
        out["local_s"] = round(time.monotonic() - started)
        (work / f"{key}.local.log").write_text(local.stdout + local.stderr, encoding="utf-8")
        if local.returncode != 0:
            out["skipped"] = f"verdict-local exited {local.returncode}"
            return out
        measured = json.loads((root / "facts.json").read_text(encoding="utf-8"))
        packet, summary = escalate.compose(scratch, measured, 2.5)
    finally:
        if args.keep:
            shutil.rmtree(work / f"{key}.scratch", ignore_errors=True)
            shutil.move(str(scratch), str(work / f"{key}.scratch"))
        else:
            shutil.rmtree(scratch, ignore_errors=True)
    (work / f"{key}.packet.md").write_text(packet, encoding="utf-8")
    out["summary"] = {k: summary.get(k) for k in ("leads", "not_listed", "proven_local", "unproven_local",
                                                  "unfiled_leads", "survivor_functions", "local_calls")}
    out["census"] = (measured.get("assertion_gaps") or {}).get("status")
    out["read_first"] = len(((measured.get("read_first") or {}).get("items")) or [])
    return score(case, packet, out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="packet_recall", description=__doc__.split("\n\n")[0])
    ap.add_argument("cases", type=Path)
    ap.add_argument("--keys", nargs="*", default=None, help="cases to run (default: all)")
    ap.add_argument("--repos", type=Path, default=Path.home() / "src")
    ap.add_argument("--env-file", type=Path, required=True)
    ap.add_argument("--model", default="chat-120b")
    ap.add_argument("--limit", type=int, default=6, help="files the breadth pass may read (as --escalate)")
    ap.add_argument("--max-functions", type=int, default=None)
    ap.add_argument("--work", type=Path, default=None, help="scratch directory (default: a new temp dir)")
    ap.add_argument("--facts-timeout", type=int, default=3600)
    ap.add_argument("--local-timeout", type=int, default=1800)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--keep", action="store_true", help="keep each breadth pass's scratch root in --work")
    ap.add_argument("--recompose", action="store_true",
                    help="score new packets from the scratch roots a --keep run left in --work")
    args = ap.parse_args(argv)
    data = json.loads(args.cases.read_text(encoding="utf-8"))
    cases = data["cases"] if isinstance(data, dict) and "cases" in data else data
    work = args.work or Path(tempfile.mkdtemp(prefix="packet-recall-"))
    work.mkdir(parents=True, exist_ok=True)
    results = []
    for case in cases:
        if args.keys and case["key"] not in args.keys:
            continue
        r = recompose(case, work) if args.recompose else run_case(case, args.repos, work, args)
        results.append(r)
        if r.get("skipped"):
            print(f"{r['key']:16} skipped — {r['skipped']}")
            continue
        s = r["summary"]
        print(f"{r['key']:16} pointed {r['pointed']}/{r['defects']} · items {s['leads']} (+{s['not_listed']} cut) · "
              f"survivors {s['survivor_functions']} · read_first {r['read_first']} · census {r['census']}"
              + (f" · facts {r.get('facts_s')}s local {r.get('local_s')}s" if "facts_s" in r else ""))
        for p in r["per_defect"]:
            print(f"   {p['id']:24} {'pointed by ' + ', '.join(p['by']) if p['pointed'] else 'NOT in the packet'}")
    done = [r for r in results if not r.get("skipped")]
    total = sum(r["defects"] for r in done)
    pointed = sum(r["pointed"] for r in done)
    print(f"\n{len(done)} case(s): the packet pointed at {pointed}/{total} known defect(s) · work {work}")
    if args.out:
        args.out.write_text(json.dumps({"results": results, "pointed": pointed, "defects": total},
                                       indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
