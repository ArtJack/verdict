"""Scorer regression corpus: real, once-passing runs frozen as test data.

The scorer has produced two false negatives so far — the REGRESSED-first check
anchoring on narrative prose, and a matcher that knew only one identifier for
a finding the agent had described perfectly. Both times the agent was right.
This corpus makes that class of regression impossible to ship silently: every
entry is a real run that once scored full marks, and any change to score.py or
to an answer key must keep scoring it full marks — in plain CI, no model.

Curation: an entry is a mini QA root (state.json + reports/) plus meta.json
naming the answer key and mode. Add one with `run_eval.py --archive <name>`
whenever a passing run exhibits a phrasing the keys have not seen before.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

EVAL = Path(__file__).resolve().parent.parent / "eval"
CORPUS = EVAL / "corpus"

ENTRIES = sorted(p for p in CORPUS.iterdir() if (p / "meta.json").is_file()) \
    if CORPUS.is_dir() else []


def test_corpus_is_not_empty():
    assert ENTRIES, "the scorer regression corpus must never be empty"


@pytest.mark.parametrize("entry", ENTRIES, ids=lambda p: p.name)
def test_corpus_entry_still_scores_full(entry):
    meta = json.loads((entry / "meta.json").read_text(encoding="utf-8"))
    cmd = [sys.executable, str(EVAL / "score.py"),
           "--qa-root", str(entry),
           "--expected", str(EVAL / meta["expected"])]
    if meta.get("mode"):
        cmd += ["--mode", meta["mode"]]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = json.loads(proc.stdout)
    misses = [r for r in out["rows"] if r.get("point") == 0]
    assert out["hard_fails"] == [], (entry.name, out["hard_fails"])
    assert out["score"] == out["max"], (
        f"{entry.name}: {out['score']}/{out['max']} — a once-passing run no "
        f"longer scores full marks; the key or scorer regressed. Misses: "
        + ", ".join(f"{r['key']} ({r.get('note', '')})" for r in misses))
    assert proc.returncode == 0
