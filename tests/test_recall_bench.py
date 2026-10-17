"""The recall benchmark's scorer (0.91.0): located / proven / blocked / false block, model-free."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval" / "recall"))
import score_recall  # noqa: E402

CASE = {"key": "pricer", "sha": "abc", "expect_verdict": None, "defects": [
    {"id": "K-1", "severity": "Major", "verified": True, "anchors": ["src/pricer/money.py"],
     "match_any": ["to_cents", "truncat"]},
    {"id": "K-2", "severity": "Major", "verified": False, "anchors": ["src/pricer/tax.py"],
     "match_any": ["vat"]},
]}


def _root(tmp_path, findings, verdict="pass with risks", blockers=(), replay_rows=()):
    root = tmp_path / "qa"
    root.mkdir()
    (root / "state.json").write_text(json.dumps({"verdict": verdict, "release_blockers": list(blockers),
                                                 "findings": findings, "last_run": {"model": "claude-opus-5-5"}}),
                                     encoding="utf-8")
    if replay_rows:
        (root / "replays.jsonl").write_text("\n".join(json.dumps(r) for r in replay_rows) + "\n", encoding="utf-8")
    (root / "usage.jsonl").write_text(json.dumps({"usage": {"model": "claude-opus-5-5", "input_tokens": 100,
                                                            "output_tokens": 50_000, "cache_read_input_tokens": 1_000_000,
                                                            "cache_creation_input_tokens": 100_000}}) + "\n",
                                      encoding="utf-8")
    return root


def test_located_proven_blocked_and_the_extras(tmp_path):
    findings = [
        {"id": "P-F-1", "title": "`to_cents` truncates", "severity": "Critical", "status": "open", "confidence": "proven",
         "evidence": ["src/pricer/money.py:14 — int() truncates"], "anchors": [{"path": "src/pricer/money.py"}],
         "replay": {"at_head": "reproduced"}},
        {"id": "P-F-2", "title": "vat applied twice", "severity": "Major", "status": "open", "confidence": "proven",
         "evidence": ["src/pricer/tax.py:3"]},                       # proven by prose: no replay → unproven
        {"id": "P-F-3", "title": "a Major nobody expected", "severity": "Major", "status": "open",
         "evidence": ["src/pricer/other.py:1"]},
        {"id": "P-F-4", "title": "a Minor", "severity": "Minor", "status": "open", "evidence": ["x.py:1"]},
    ]
    root = _root(tmp_path, findings, verdict="fail", blockers=["P-F-1 (Critical): truncation"])
    r = score_recall.score_case(CASE, root)
    by = {d["defect"]: d for d in r["defects"]}
    assert by["K-1"] == {"defect": "K-1", "verified": True, "located": True, "by": "P-F-1", "proven": True, "blocked": True}
    assert by["K-2"] == {"defect": "K-2", "verified": False, "located": True, "by": "P-F-2", "proven": False, "blocked": False}
    assert r["extra_major_plus"] == ["P-F-3"] and r["false_block"] is False
    assert r["cost_usd"] == round((100 * 4 + 50_000 * 20 + 1_000_000 * 0.2 + 100_000 * 5) / 1e6, 2)
    s = score_recall.summarize([r])
    assert s["located"] == "2/2" and s["located_verified"] == "1/1" and s["proven"] == "1/2" and s["blocked"] == "1/2"


def test_a_missed_defect_a_ledger_replay_and_a_false_block(tmp_path):
    findings = [{"id": "P-F-9", "title": "to_cents truncates", "severity": "Major", "status": "open",
                 "confidence": "proven", "evidence": ["src/pricer/money.py:14"]}]
    root = _root(tmp_path, findings, verdict="fail", replay_rows=[{"id": "P-F-9", "result": "reproduced"}])
    case = dict(CASE, expect_verdict="pass")
    r = score_recall.score_case(case, root)
    by = {d["defect"]: d for d in r["defects"]}
    assert by["K-1"]["located"] and by["K-1"]["proven"], "a reproduced row in replays.jsonl proves it"
    assert by["K-1"]["blocked"] is False, "a Major that is not a named blocker does not block"
    assert by["K-2"]["located"] is False and by["K-2"]["by"] is None
    assert r["false_block"] is True
    assert score_recall.summarize([r])["false_blocks"] == "1/1"


def test_the_cli_prints_a_row_per_defect(tmp_path, capsys):
    cases = tmp_path / "cases.json"
    cases.write_text(json.dumps({"cases": [CASE]}), encoding="utf-8")
    root = _root(tmp_path, [], verdict="pass")
    assert score_recall.main([str(cases), "--run", f"pricer={root}"]) == 0
    out = capsys.readouterr().out
    assert "K-1" in out and "MISSED" in out and "located 0/2" in out
    assert score_recall.main([str(cases), "--run", f"nope={root}"]) == 2


def test_a_finding_that_names_two_defects_is_credited_once():
    """The first case file read 8 'extra' Major+ findings on records where every finding was a
    known defect: a greedy match let one finding claim several defects."""
    defects = [{"id": "K-1", "anchors": ["shop/ledger.py"], "match_any": ["subtotal", "rounding"]},
               {"id": "K-2", "anchors": ["shop/ledger.py"], "match_any": ["coupon", "expired"]}]
    findings = [{"id": "F-1", "title": "subtotal rounding drops a cent; the coupon total reads it", "evidence": ["shop/ledger.py:40"]},
                {"id": "F-2", "title": "an expired coupon still applies", "evidence": ["shop/ledger.py:90"]}]
    chosen = score_recall.assign(defects, findings)
    assert chosen["K-1"]["id"] == "F-1" and chosen["K-2"]["id"] == "F-2"
