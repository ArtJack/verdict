#!/usr/bin/env python3
"""The recall benchmark: what a run found, proved and blocked, against defects known to be there.

Every other row in `eval/` scores precision against an answer key somebody authored. This
scores the number a tester is judged on — what did you miss — on defects nobody planted:
findings hand-verified on strangers' repositories (a fresh clone, a standalone script, an
expected value derived by hand), defects fixed upstream and gated at the commit that
introduced them, and clean changes that must not be blocked.

A case file (kept outside this repository — some known defects are undisclosed) lists, per
project, the commit the run saw and each known defect: its anchor files, the words that name
it, its severity, and whether a hand replay verified it. The scorer reads a run's `state.json`
and answers, per defect: **located** (a finding cites one of its anchor files and names it),
**proven** (that finding is filed `proven`, with a `repro` the harness or the command
reproduced), **blocked** (the verdict is `fail` and the finding is a release blocker or
Blocker/Critical). It also counts the run's Major+ findings that match no known defect — the
candidates for false findings, read by hand — and prices the run from `usage.jsonl`.

    python3 eval/recall/score_recall.py ~/.claude/verdict-bench/recall-cases.json \\
        --run fava=~/.claude/verdict/fava --run numpy-financial=~/.cache/verdict-eval/x/qa

Stdlib only; no model, no tokens. A score is n=1 until repeated.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

SEVERE = ("Blocker", "Critical", "Major")
RATES = {"input": 4.0, "output": 20.0, "cache_read": 0.20, "cache_write": 5.0}   # Opus 5.5, $/MTok


def _text(finding: dict) -> str:
    parts = [str(finding.get("title") or "")] + [str(e) for e in finding.get("evidence") or []]
    return " ".join(parts).lower()


def _files(finding: dict) -> set:
    out = set()
    for a in finding.get("anchors") or []:
        path = a.get("path") if isinstance(a, dict) else a
        if path:
            out.add(str(path).replace("\\", "/"))
    for m in re.finditer(r"([\w./-]+\.(?:py|ts|js|go|rs|rb|java|cs))(?::\d+)?", _text(finding)):
        out.add(m.group(1))
    return out


def _cites(finding: dict, anchor_files) -> bool:
    files = _files(finding)
    for want in anchor_files or []:
        want = str(want).replace("\\", "/")
        base = want.rsplit("/", 1)[-1]
        if any(f == want or f.endswith("/" + want) or f.rsplit("/", 1)[-1] == base for f in files):
            return True
    return False


def match_score(defect: dict, finding: dict) -> int:
    """0 when the finding cannot be this defect (no anchor file cited, no naming word);
    else how well it names it — two points per naming word, one per anchor file cited."""
    if not _cites(finding, defect.get("anchors")):
        return 0
    text = _text(finding)
    terms = [t.lower() for t in defect.get("match_any") or []]
    hits = sum(1 for t in terms if t in text)
    if terms and not hits:
        return 0
    cited = sum(1 for a in defect.get("anchors") or [] if _cites(finding, [a]))
    return 2 * hits + cited


def assign(defects, findings) -> dict:
    """One finding per defect and one defect per finding, best matches first — a finding
    that names two defects is credited once, with the one it names best."""
    pairs = sorted(((match_score(d, f), -i, -j, d.get("id"), f)
                    for i, d in enumerate(defects) for j, f in enumerate(findings)
                    if match_score(d, f) > 0), key=lambda p: (p[0], p[1], p[2]), reverse=True)
    taken, out = set(), {}
    for _score, _i, _j, did, f in pairs:
        fid = str(f.get("id"))
        if did in out or fid in taken:
            continue
        out[did] = f
        taken.add(fid)
    return out


def located(defect: dict, findings) -> dict | None:
    """The finding that best cites an anchor file and names the defect, or None."""
    return assign([defect], findings).get(defect.get("id"))


def proven(finding: dict, replays: dict) -> bool:
    if finding.get("confidence") != "proven":
        return False
    rep = finding.get("replay") if isinstance(finding.get("replay"), dict) else None
    if rep:
        return rep.get("at_head") == "reproduced" and rep.get("isolated") is not False
    row = replays.get(str(finding.get("id")))
    if row:
        return row.get("result") == "reproduced" and row.get("isolated") is not False
    return False


def blocked(state: dict, finding: dict) -> bool:
    if state.get("verdict") != "fail":
        return False
    fid = str(finding.get("id"))
    blockers = " ".join(str(b) for b in state.get("release_blockers") or [])
    return fid in blockers or finding.get("severity") in ("Blocker", "Critical")


def cost_of(qa_root: Path) -> float | None:
    try:
        rows = [json.loads(line) for line in
                (qa_root / "usage.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError:
        return None
    total = 0.0
    seen = False
    for r in rows:
        u = r.get("usage") or {}
        if not u or not str(u.get("model", "")).startswith("claude"):
            continue
        seen = True
        total += (u.get("input_tokens", 0) * RATES["input"] + u.get("output_tokens", 0) * RATES["output"]
                  + u.get("cache_read_input_tokens", 0) * RATES["cache_read"]
                  + u.get("cache_creation_input_tokens", 0) * RATES["cache_write"]) / 1e6
    return round(total, 2) if seen else None


def load_replays(qa_root: Path) -> dict:
    latest = {}
    try:
        for line in (qa_root / "replays.jsonl").read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("id"):
                latest[str(row["id"])] = row
    except OSError:
        pass
    return latest


def score_case(case: dict, qa_root: Path) -> dict:
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    findings = [f for f in state.get("findings") or [] if isinstance(f, dict)]
    replays = load_replays(qa_root)
    rows, matched = [], set()
    chosen = assign(case.get("defects") or [], findings)
    for d in case.get("defects") or []:
        f = chosen.get(d.get("id"))
        if f is not None:
            matched.add(str(f.get("id")))
        rows.append({"defect": d.get("id"), "verified": bool(d.get("verified")),
                     "located": f is not None, "by": str(f.get("id")) if f else None,
                     "proven": bool(f and proven(f, replays)),
                     "blocked": bool(f and blocked(state, f))})
    extra = [str(f.get("id")) for f in findings
             if f.get("severity") in SEVERE and str(f.get("status", "open")).lower() == "open"
             and str(f.get("id")) not in matched]
    expect = case.get("expect_verdict")
    return {"case": case.get("key"), "sha": case.get("sha"), "verdict": state.get("verdict"),
            "expect_verdict": expect,
            "false_block": bool(expect in ("pass", "pass with risks") and state.get("verdict") == "fail"),
            "defects": rows, "extra_major_plus": extra, "cost_usd": cost_of(qa_root),
            "model": (state.get("last_run") or {}).get("model")}


def summarize(results) -> dict:
    defects = [r for res in results for r in res["defects"]]
    verified = [r for r in defects if r["verified"]]
    def tally(rows, key):
        return f"{sum(1 for r in rows if r[key])}/{len(rows)}"
    return {"cases": len(results),
            "located": tally(defects, "located"), "located_verified": tally(verified, "located"),
            "proven": tally(defects, "proven"), "proven_verified": tally(verified, "proven"),
            "blocked": tally(defects, "blocked"),
            "false_blocks": f"{sum(1 for r in results if r['false_block'])}/{sum(1 for r in results if r['expect_verdict'] in ('pass', 'pass with risks'))}",
            "extra_major_plus": sum(len(r["extra_major_plus"]) for r in results),
            "cost_usd": round(sum(r["cost_usd"] or 0 for r in results), 2)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cases", help="the case file (JSON: {cases: [...]})")
    ap.add_argument("--run", action="append", default=[], metavar="KEY=QA_ROOT",
                    help="a run to score: the case key and the QA root holding its state.json")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    cases = {c["key"]: c for c in json.loads(Path(args.cases).expanduser().read_text(encoding="utf-8"))["cases"]}
    results = []
    for spec in args.run:
        key, _, root = spec.partition("=")
        if key not in cases:
            print(f"score_recall: no case {key!r} in {args.cases}", file=sys.stderr)
            return 2
        results.append(score_case(cases[key], Path(os.path.expanduser(root))))
    if args.json:
        print(json.dumps({"results": results, "summary": summarize(results)}, indent=1))
        return 0
    for r in results:
        print(f"{r['case']:18} verdict {r['verdict']!s:16} "
              f"{'FALSE BLOCK ' if r['false_block'] else ''}cost ${r['cost_usd'] if r['cost_usd'] is not None else '?'}")
        for d in r["defects"]:
            print(f"   {d['defect']:24} {'located' if d['located'] else 'MISSED ':8} "
                  f"{'proven' if d['proven'] else 'unproven':8} {'blocked' if d['blocked'] else 'open   '}"
                  f"{'  ✓hand' if d['verified'] else ''}{('  by ' + d['by']) if d['by'] and d['by'] != d['defect'] else ''}")
        if r["extra_major_plus"]:
            print(f"   extra Major+ (read by hand): {', '.join(r['extra_major_plus'])}")
    s = summarize(results)
    print(f"\n{s['cases']} case(s): located {s['located']} (hand-verified {s['located_verified']}) · "
          f"proven {s['proven']} (hand-verified {s['proven_verified']}) · blocked {s['blocked']} · "
          f"false blocks {s['false_blocks']} · extra Major+ {s['extra_major_plus']} · ${s['cost_usd']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
