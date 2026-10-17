#!/usr/bin/env python3
"""Derive recall-benchmark cases from existing records: each open, proven Major+ finding becomes a
known defect with its anchor files and the words that name it (the title's code names and
distinctive words, as `verdict-dupes` derives them). `--verified ID …` marks the ones a hand
replay confirmed. Output is a case file for `score_recall.py`; keep it outside this repository
when a defect is undisclosed.

    python3 eval/recall/build_cases.py --out ~/.claude/verdict-bench/recall-cases.json \\
        fava=~/.claude/verdict/fava --verified FAVA-F-1 ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from verdict_mcp.dupes import terms_of  # noqa: E402

SEVERE = ("Blocker", "Critical", "Major")


def case_from(key: str, qa_root: Path, verified: set, expect_verdict: str | None) -> dict:
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    defects = []
    for f in state.get("findings") or []:
        if str(f.get("status", "open")).lower() != "open" or f.get("severity") not in SEVERE \
                or f.get("confidence") != "proven":
            continue
        anchors = sorted({(a.get("path") if isinstance(a, dict) else a) for a in f.get("anchors") or []
                          if (a.get("path") if isinstance(a, dict) else a)})
        defects.append({"id": f["id"], "severity": f["severity"], "title": f.get("title"),
                        "anchors": anchors, "match_any": terms_of(f, cap=4),
                        "verified": f["id"] in verified})
    return {"key": key, "qa_root_of_record": str(qa_root), "sha": (state.get("last_run") or {}).get("git_sha"),
            "mode": state.get("run_type"), "expect_verdict": expect_verdict, "defects": defects}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("runs", nargs="+", metavar="KEY=QA_ROOT")
    ap.add_argument("--verified", nargs="*", default=[], metavar="ID")
    ap.add_argument("--expect-verdict", default=None, help="for a clean change: pass | pass with risks")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(os.path.expanduser(args.out))
    existing = json.loads(out.read_text(encoding="utf-8"))["cases"] if out.exists() else []
    by_key = {c["key"]: c for c in existing}
    for spec in args.runs:
        key, _, root = spec.partition("=")
        by_key[key] = case_from(key, Path(os.path.expanduser(root)), set(args.verified), args.expect_verdict)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"cases": list(by_key.values())}, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    n = sum(len(c["defects"]) for c in by_key.values())
    print(f"{len(by_key)} case(s), {n} known defect(s) → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
