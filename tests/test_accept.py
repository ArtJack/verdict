"""Accepted risks — the maintainer's pen, and the one status the tester cannot write.

VERDICT-F-21 sat open for eight runs after its residual risk had been weighed,
accepted and written into a decision journal, because the state had no way to
say so: `open` re-reported it as a Major in every banner, and `withdrawn`
would have scored a correct finding as the tester's error. These tests are
about who may hold that pen — only `verdict-accept`, never a judgment, never
the agent's Write tool — and about every surface that must agree once it has
been used: the harness, the validator, the report, the track record, the
gate, the banner, the MCP server and the issue filer.
"""

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from verdict_mcp import accept as accept_cli
from verdict_mcp import server
from verdict_mcp.gate import _fmt_text, evaluate
from verdict_mcp.harness import finding_hash, merge, render_report
from verdict_mcp.state import (ACCEPTED_FILE, calibration, fold_accepted, is_open,
                               load_accepted, outcome_row)
from verdict_mcp.validate import validate, validate_judgment

HOOKS = Path(__file__).resolve().parent.parent / "hooks"
ISSUES = Path(__file__).resolve().parent.parent / "src" / "verdict_mcp" / "issues.py"
BANNER = HOOKS / "report_open_findings.py"
NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
CITE = "DECISIONS.md 2026-09-02 — the chain ratchet moves to the outcome ledger"
WHY = "deleting outcomes.json too defeats the anchor; the cost is the whole track record"


def finding(i=1, **over):
    f = {"id": f"D-F-{i}", "title": f"defect {i}", "evidence": [f"src/m{i}.py:10 the line"],
         "severity": "Major", "priority": "P1", "failure_classification": "REAL_DEFECT",
         "confidence": "proven", "status": "open", "first_seen": "2026-08-30",
         "age_days": 5, "delta": "STILL_OPEN"}
    f.update(over)
    f.setdefault("hash", finding_hash(f))
    return f


def state_with(*findings, **over):
    s = {"project": "demo", "schema_version": 1, "run_type": "delta", "run_number": 4,
         "last_run": {"timestamp_utc": NOW, "git_sha": "abc1234", "sha_range": "aaa..abc",
                      "report": "reports/r.md"},
         "isolation_check": {"result": "pass"}, "gates": {}, "tests": {"collected": 3},
         "flaky_quarantine": [], "findings": list(findings), "verdict": "fail",
         "release_blockers": [], "not_tested": ["concurrency"]}
    s.update(over)
    return s


@pytest.fixture()
def root(tmp_path):
    """A solo-style QA root addressed by path."""
    r = tmp_path / "qa"
    (r / "reports").mkdir(parents=True)
    (r / "reports" / "r.md").write_text("# report", encoding="utf-8")
    (r / "state.json").write_text(json.dumps(state_with(finding(1), finding(2))),
                                  encoding="utf-8")
    return r


def accept(root, fid="D-F-1", *extra, cite=CITE, reason=WHY):
    return accept_cli.main([str(root), fid, "--cite", cite, "--reason", reason,
                            "--by", "Art", "--today", "2026-09-04", *extra])


def facts(n=5):
    return {"project": "demo", "run_type": "delta", "run_number": n,
            "last_run": {"timestamp_utc": NOW, "git_sha": "abc1234"}, "gates": {}}


def judgment(findings):
    return {"findings": findings, "verdict": "pass with risks", "release_blockers": [],
            "not_tested": ["nothing"], "isolation_check": {"result": "pass"},
            "report": "reports/r.md"}


# ── the pen ──────────────────────────────────────────────────────────────────

def test_accept_writes_the_ledger_and_the_finding_leaves_the_open_counts(root, capsys):
    assert accept(root) == 0
    ledger = load_accepted(root)
    entry = ledger["D-F-1"]
    assert entry["by"] == "Art" and entry["on"] == "2026-09-04"
    assert entry["citation"] == CITE and entry["reason"] == WHY
    assert entry["hash"] == finding(1)["hash"], "identity travels with the decision"
    out = capsys.readouterr().out
    assert "out of the open counts now" in out and "next run" in out

    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    folded = {f["id"]: f for f in fold_accepted(state["findings"], ledger)}
    assert folded["D-F-1"]["status"] == "accepted" and not is_open(folded["D-F-1"])
    assert folded["D-F-1"]["accepted"]["citation"] == CITE
    assert folded["D-F-2"]["status"] == "open" and is_open(folded["D-F-2"])
    # …and the state file itself was not touched: the tester's artifact is not
    # the maintainer's to edit, and the signed history row must still re-derive.
    assert state["findings"][0]["status"] == "open"


def test_accept_refuses_without_a_real_citation_or_reason(root, capsys):
    assert accept(root, cite="") == 2
    assert accept(root, reason="tbd") == 2
    err = capsys.readouterr().err
    assert "mute button" in err
    assert not (root / ACCEPTED_FILE).exists(), "a refusal writes nothing"


def test_accept_refuses_an_unknown_or_closed_finding(root, capsys):
    assert accept(root, "D-F-9") == 2
    assert "no finding 'D-F-9'" in capsys.readouterr().err
    s = state_with(finding(1, status="resolved", delta="RESOLVED"))
    (root / "state.json").write_text(json.dumps(s), encoding="utf-8")
    assert accept(root, "D-F-1") == 2
    assert "nothing left to accept" in capsys.readouterr().err


def test_accept_refuses_a_duplicate_and_revoke_reverses_it(root, capsys):
    assert accept(root) == 0
    assert accept(root) == 2
    assert "already accepted" in capsys.readouterr().err
    assert accept_cli.main([str(root), "D-F-1", "--revoke", "--by", "Art",
                            "--today", "2026-09-05", "--reason", "the fix landed after all"]) == 0
    entry = json.loads((root / ACCEPTED_FILE).read_text(encoding="utf-8"))["accepted"]["D-F-1"]
    assert entry["revoked"] == {"by": "Art", "on": "2026-09-05",
                                "reason": "the fix landed after all"}
    assert load_accepted(root)["D-F-1"]["revoked"], "revoked entries stay on the record"
    state = json.loads((root / "state.json").read_text(encoding="utf-8"))
    folded = fold_accepted(state["findings"], load_accepted(root))[0]
    assert folded["status"] == "open" and is_open(folded)
    # revoking twice, and re-accepting after a revocation
    assert accept_cli.main([str(root), "D-F-1", "--revoke", "--reason", "twice is a mistake"]) == 2
    assert accept(root) == 0
    again = load_accepted(root)["D-F-1"]
    assert not again.get("revoked") and again["previously"]["revoked"]["on"] == "2026-09-05"


def test_list_prints_the_ledger(root, capsys):
    assert accept_cli.main([str(root), "--list"]) == 0
    assert "no accepted risks" in capsys.readouterr().out
    accept(root)
    assert accept_cli.main([str(root), "--list"]) == 0
    out = capsys.readouterr().out
    assert "D-F-1" in out and "in force" in out and CITE in out


def test_no_state_is_exit_4(tmp_path, capsys):
    assert accept_cli.main([str(tmp_path / "nowhere"), "D-F-1", "--cite", CITE,
                            "--reason", WHY]) == 4


# ── who may not hold it ──────────────────────────────────────────────────────

def filed(**over):
    """A finding as a judgment files it: no computed fields, which the
    judgment validator rightly refuses."""
    f = finding(**over)
    for computed in ("hash", "first_seen", "age_days", "delta"):
        f.pop(computed, None)
    return f


def test_the_tester_cannot_write_the_status():
    bad = validate_judgment(judgment([filed(status="accepted")]))
    assert any("verdict-accept" in b and "accepted" in b for b in bad), bad
    assert validate_judgment(judgment([filed()])) == []


def test_the_guards_refuse_the_ledger_to_the_tester(repo):
    """The write guard blocks the verdict agent from the file even inside the QA
    root, and the strict bash guard blocks a shell write of it; the tester's own
    files beside it stay writable."""
    qa = repo / ".qa"
    qa.mkdir()
    (qa / "state.json").write_text("{}", encoding="utf-8")

    def hook(script, payload, strict=None):
        env = {k: v for k, v in os.environ.items() if k not in ("VERDICT_STRICT", "VERDICT_HOME")}
        if strict:
            env["VERDICT_STRICT"] = strict
        p = subprocess.run([sys.executable, str(HOOKS / script)], input=json.dumps(payload),
                           capture_output=True, text=True, env=env, encoding="utf-8",
                           errors="replace")
        return p.returncode, p.stderr

    write = lambda path: {"tool_name": "Write", "tool_input": {"file_path": str(path)},
                          "agent_name": "verdict"}
    rc, err = hook("enforce_write_scope.py", write(qa / ACCEPTED_FILE))
    assert rc == 2 and "maintainer" in err, err
    rc, err = hook("enforce_write_scope.py", write(qa / "judgment.json"))
    assert rc == 0, err
    bash = lambda cmd: {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(repo)}
    rc, err = hook("enforce_bash_scope.py", bash(f"cp x.json {qa / ACCEPTED_FILE}"), strict="1")
    assert rc == 2 and "maintainer" in err, err
    rc, err = hook("enforce_bash_scope.py", bash(f"cp x.json {qa / 'facts.json'}"), strict="1")
    assert rc == 0, err


# ── the state contract ───────────────────────────────────────────────────────

def test_state_requires_a_citation_on_an_accepted_finding(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "r.md").write_text("# r", encoding="utf-8")
    bare = finding(1, status="accepted", delta="ACCEPTED")
    bad = validate(state_with(bare), tmp_path)
    assert any("citation" in b for b in bad), bad
    cited = finding(1, status="accepted", delta="ACCEPTED",
                    accepted={"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY})
    assert validate(state_with(cited), tmp_path) == []
    # the delta and the status must agree in both directions
    half = finding(1, status="open", delta="ACCEPTED")
    assert any("ACCEPTED" in b for b in validate(state_with(half), tmp_path))
    other = finding(1, status="accepted", delta="STILL_OPEN",
                    accepted={"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY})
    assert any("ACCEPTED" in b for b in validate(state_with(other), tmp_path))


def test_an_accepted_critical_does_not_block_a_pass(tmp_path):
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "r.md").write_text("# r", encoding="utf-8")
    crit = finding(1, severity="Critical", priority="P0", status="accepted", delta="ACCEPTED",
                   accepted={"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY})
    assert validate(state_with(crit, verdict="pass"), tmp_path) == []
    still_open = finding(1, severity="Critical", priority="P0")
    assert any("open Critical" in b for b in validate(state_with(still_open, verdict="pass"),
                                                       tmp_path))


# ── the harness folds it in ──────────────────────────────────────────────────

def ledger_for(*ids, revoked=()):
    out = {}
    for fid in ids:
        out[fid] = {"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY}
        if fid in revoked:
            out[fid]["revoked"] = {"by": "Art", "on": "2026-09-05", "reason": "fixed after all"}
    return out


def test_finalize_folds_the_ledger_whatever_the_tester_says():
    prev = state_with(finding(1), finding(2))
    ledger = ledger_for("D-F-1")
    # re-reported open: accepted anyway
    s = merge(facts(), judgment([finding(1), finding(2)]), prev, today=date.today(),
              accepted=ledger)
    by_id = {f["id"]: f for f in s["findings"]}
    f1 = by_id["D-F-1"]
    assert f1["status"] == "accepted" and f1["delta"] == "ACCEPTED" and not is_open(f1)
    assert f1["accepted"]["citation"] == CITE
    assert f1["outcome"] == "confirmed" and f1["outcome_basis"] == "accepted", f1
    assert "declined" in f1["outcome_reason"]
    assert by_id["D-F-2"]["status"] == "open" and by_id["D-F-2"]["delta"] == "STILL_OPEN"
    # silent about it: carried as accepted, not resolved by silence
    s2 = merge(facts(6), judgment([finding(2)]), s, today=date.today(), accepted=ledger)
    f1 = {f["id"]: f for f in s2["findings"]}["D-F-1"]
    assert f1["status"] == "accepted" and f1["delta"] == "ACCEPTED"
    assert "carried_forward" not in f1
    # resolved by the tester: the resolution wins — a defect that is gone has
    # nothing left to accept
    s3 = merge(facts(7), judgment([finding(1, status="resolved"), finding(2)]), s2,
               today=date.today(), accepted=ledger)
    f1 = {f["id"]: f for f in s3["findings"]}["D-F-1"]
    assert f1["status"] == "resolved" and f1["delta"] == "RESOLVED"
    assert f1["outcome"] == "confirmed", "the decided outcome sticks"


def test_a_revoked_acceptance_reopens_the_finding_at_the_next_run():
    accepted = finding(1, status="accepted", delta="ACCEPTED", outcome="confirmed",
                       outcome_basis="accepted",
                       accepted={"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY})
    prev = state_with(accepted)
    s = merge(facts(), judgment([]), prev, today=date.today(),
              accepted=ledger_for("D-F-1", revoked=("D-F-1",)))
    f1 = s["findings"][0]
    assert f1["status"] == "open" and f1["delta"] == "STILL_OPEN" and is_open(f1)
    assert "accepted" not in f1 and f1["accepted_revoked"]["reason"] == "fixed after all"
    assert f1["outcome"] == "confirmed", "an outcome, once decided, sticks"
    # and with the ledger gone entirely, the same
    s = merge(facts(), judgment([]), prev, today=date.today(), accepted={})
    assert s["findings"][0]["status"] == "open"


def test_accepted_findings_do_not_count_toward_the_silence_guardrail():
    """Six accepted, one open, a scoped run that mentions nothing: the open one
    resolves by silence as it always did — the accepted ones are not an
    'incoming open backlog' the run failed to sweep."""
    acc = [finding(i, status="accepted", delta="ACCEPTED",
                   accepted={"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY})
           for i in range(1, 7)]
    prev = state_with(*acc, finding(7))
    s = merge(facts(), judgment([]), prev, today=date.today(), accepted=ledger_for(*[f["id"] for f in acc]))
    by_id = {f["id"]: f for f in s["findings"]}
    assert by_id["D-F-7"]["delta"] == "RESOLVED"
    assert all(by_id[f"D-F-{i}"]["status"] == "accepted" for i in range(1, 7))


# ── every surface agrees ─────────────────────────────────────────────────────

def accepted_state():
    acc = finding(1, severity="Critical", priority="P0", status="accepted", delta="ACCEPTED",
                  outcome="confirmed", outcome_basis="accepted",
                  accepted={"by": "Art", "on": "2026-09-04", "citation": CITE, "reason": WHY})
    return state_with(acc, finding(2), verdict="pass with risks")


def test_the_report_lists_accepted_risks_apart():
    report = render_report(accepted_state())
    assert "## Findings — REGRESSED first (1 open of 2 tracked · 1 accepted)" in report
    assert "## Accepted risks (1)" in report
    section = report.split("## Accepted risks (1)", 1)[1]
    assert "D-F-1" in section and CITE in section and WHY in section and "Art" in section
    # no section at all when there is nothing to put in it
    assert "Accepted risks" not in render_report(state_with(finding(2)))


def test_the_track_record_counts_an_acceptance_apart():
    rows = {"h1": outcome_row(dict(finding(1), outcome="confirmed", outcome_basis="accepted")),
            "h2": outcome_row(dict(finding(2), outcome="confirmed", outcome_basis="measured"))}
    cal = calibration({"findings": []}, min_sample=1, ledger=rows)
    bucket = cal["by_confidence"]["proven"]
    assert bucket["confirmed"] == 2 and bucket["confirmed_accepted"] == 1
    assert bucket["confirmed_measured"] == 1
    assert "1 accepted by the maintainer" in bucket["reading"], bucket["reading"]
    assert any("accepted" in c for c in cal["caveats"])


def test_the_gate_keeps_an_accepted_finding_out_of_the_open_list(root):
    assert accept(root) == 0
    r = evaluate(str(root), "fail", None, None)
    assert [f["id"] for f in r["findings_open"]] == ["D-F-2"]
    assert r["accepted_risks"] == 1
    assert "accepted risks: 1" in _fmt_text(r, 10)
    assert r["verdict"] == "fail", "acceptance changes the next verdict, never the last one"


def test_the_mcp_server_serves_accepted_apart(root):
    assert accept(root) == 0
    assert [f["id"] for f in server.get_findings(str(root), "open")["findings"]] == ["D-F-2"]
    got = server.get_findings(str(root), "accepted")
    assert got["count"] == 1 and got["findings"][0]["accepted"]["citation"] == CITE
    assert server.get_verdict(str(root))["accepted_risks"] == 1
    assert "accepted" in server.get_findings(str(root), "nonsense")["allowed"]


def test_the_banner_counts_accepted_risks_apart(repo):
    qa = repo / ".qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "reports" / "r.md").write_text("# r", encoding="utf-8")
    (qa / "state.json").write_text(json.dumps(state_with(finding(1), finding(2))),
                                   encoding="utf-8")
    assert accept(qa) == 0
    env = {k: v for k, v in os.environ.items() if not k.startswith("VERDICT_")}
    p = subprocess.run([sys.executable, str(BANNER)], input=json.dumps({"cwd": str(repo)}),
                       capture_output=True, text=True, env=env, encoding="utf-8")
    assert p.returncode == 0
    assert "1 open finding" in p.stdout and "1 accepted risk" in p.stdout, p.stdout
    assert "D-F-1" not in p.stdout, "an accepted finding is not re-reported as open"


def test_verdict_issues_does_not_file_an_accepted_finding(root):
    assert accept(root) == 0
    p = subprocess.run([sys.executable, str(ISSUES), str(root), "--format", "json"],
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr
    would = json.loads(p.stdout)["would_create"]
    assert [w["id"] for w in would] == ["D-F-2"], would
