"""Escalation runs: verdict-local reads first, the tester gets only its leads and a cap (0.92.0)."""

import json
import subprocess
import sys

import pytest

from conftest import judgment
from verdict_mcp import escalate, runner, small
from verdict_mcp.harness import facts_main, finalize_main


def _finding(fid, title, severity, confidence, cls="REAL_DEFECT", delta="NEW", ref="shop/pay.py:10"):
    path, line = ref.split(":")
    return {"id": fid, "title": title, "severity": severity, "confidence": confidence,
            "failure_classification": cls, "delta": delta, "status": "open",
            "anchors": [{"ref": ref, "path": path, "line": int(line)}],
            "evidence": [f"{ref} — read by a small model"]}


def _scratch(tmp_path, findings=(), leads=(), owed=None):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    (scratch / "state.json").write_text(json.dumps({"findings": list(findings)}), encoding="utf-8")
    (scratch / escalate.LEADS_FILE).write_text(json.dumps({"leads": list(leads)}), encoding="utf-8")
    facts = {"last_run": {"local": {"model": "chat-120b", "functions_read": 24, "calls": 51,
                                    "seconds": 300.0}}}
    if owed:
        facts["needs_claude"] = owed
    (scratch / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    return scratch


def _survivor(path, fn, line, before="if a > b:", after="if a >= b:"):
    return {"path": path, "function": fn, "line": line, "operator": "comparison",
            "before": before, "after": after, "tests": ["tests/t.py::t"]}


FACTS = {"assertion_gaps": {"status": "measured", "survived": [
            _survivor("shop/fee.py", "charge_fee", 8), _survivor("shop/fee.py", "charge_fee", 9),
            _survivor("shop/fee.py", "charge_fee", 10), _survivor("shop/refund.py", "refund", 3)]},
         "read_first": {"items": [{"path": "shop/fee.py", "function": "charge_fee", "risk": "fee"},
                                  {"path": "shop/order.py", "function": "Order.pay", "risk": "pay"}]}}


def test_the_packet_puts_proven_claims_first_then_every_survivor_then_the_readings(tmp_path):
    scratch = _scratch(tmp_path, findings=[
        _finding("L-1", "the refund ignores the amount", "Critical", "hypothesis"),
        _finding("L-2", "a sale is recorded twice", "Major", "proven", ref="shop/sale.py:4"),
        _finding("L-3", "A test is skipped with no expiry", "Minor", "proven", cls="BRITTLE_TEST"),
        _finding("L-4", "carried from an older run", "Major", "proven", delta="STILL_OPEN")],
        leads=[{"path": "shop/x.py", "line": 7, "function": "f", "title": "an unproven reading",
                "severity": "Minor", "why": "the proof budget was spent"}],
        owed={"unexercised_changed_lines": 7})
    text, summary = escalate.compose(scratch, FACTS, 2.5)
    order = [text.index(s) for s in ("a sale is recorded twice", "shop/fee.py::charge_fee",
                                     "shop/refund.py::refund", "shop/order.py::Order.pay",
                                     "the refund ignores the amount", "an unproven reading",
                                     "unexercised_changed_lines: 7")]
    assert order == sorted(order), text
    assert "A test is skipped" not in text and "carried from an older run" not in text
    assert text.count("line 10") == 0, "two example lines per survivor function, not three"
    assert text.count("charge_fee") == 1, "a reading-map item a survivor already covers is not listed twice"
    assert "The run stops at $2.5" in text and "chat-120b read 24 function(s)" in text
    assert summary["proven_local"] == 1 and summary["unproven_local"] == 1
    assert summary["survivor_functions"] == 2 and summary["leads"] == 7 and summary["not_listed"] == 0


def test_the_packet_is_capped_and_says_how_many_items_it_left_out(tmp_path):
    many = [_finding(f"L-{n}", f"reading {n}", "Minor", "hypothesis", ref=f"shop/m{n}.py:1")
            for n in range(escalate.MAX_ITEMS + 4)]
    text, summary = escalate.compose(_scratch(tmp_path, findings=many), {}, 2.5)
    assert text.count("**Unproven reading**") == escalate.MAX_ITEMS
    assert "… 4 more item(s) were not listed" in text
    assert summary["leads"] == escalate.MAX_ITEMS and summary["not_listed"] == 4


def test_a_breadth_pass_that_passed_nothing_on_says_so(tmp_path):
    text, summary = escalate.compose(_scratch(tmp_path), {}, 2.5)
    assert "passed nothing on" in text and summary["leads"] == 0


def test_the_packet_and_its_summary_are_kept_beside_the_record(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "facts.json").write_text(json.dumps({"last_run": {"git_sha": "abc"}}), encoding="utf-8")
    escalate.record(qa, "PACKET", {"leads": 3})
    assert (qa / escalate.PACKET_FILE).read_text(encoding="utf-8") == "PACKET"
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert facts["last_run"] == {"git_sha": "abc", "escalation": {"leads": 3}}


def test_finalize_says_what_an_escalation_tester_was_handed_and_bills_it(repo, qa_root, capsys):
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    facts = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    facts["last_run"]["escalation"] = {"leads": 9, "local_model": "chat-120b", "functions_read": 24,
                                       "local_calls": 51, "budget_usd": 2.5}
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    (qa_root / "judgment.json").write_text(json.dumps(judgment()), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")]) == 0, \
        capsys.readouterr().err
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert any(n.startswith("escalation run: the tester was handed 9 item(s) from a breadth pass by "
                            "chat-120b, which read 24 function(s)") for n in state["not_tested"])
    row = json.loads((qa_root / "usage.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["escalation"] == {"leads": 9, "local_model": "chat-120b", "local_calls": 51,
                                 "functions_read": 24, "budget_usd": 2.5}


def test_the_local_tier_writes_its_leads_as_data(tmp_path):
    from test_local_delta import delta, git, project
    repo, qa = project(tmp_path)
    (repo / "cited.py").write_text("def rate(weight):\n    return weight * 3\n", encoding="utf-8")
    git(repo, "commit", "-qam", "change the cited function")
    assert delta(repo, qa) == 0
    data = json.loads((qa / escalate.LEADS_FILE).read_text(encoding="utf-8"))
    assert set(data) == {"engine", "model", "leads"} and isinstance(data["leads"], list)
    assert small.LEADS_FILE == escalate.LEADS_FILE


# ── the runner ────────────────────────────────────────────────────────────

def _head(repo):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                          text=True, check=True).stdout.strip()


@pytest.fixture()
def wired(repo, tmp_path, monkeypatch):
    """runner.main with every outside call replaced: the measurement is the real harness, the
    breadth pass and the CLI are recorders, and the gate answers at once."""
    home = tmp_path / "home"
    qa = home / "proj"
    (qa / "reports").mkdir(parents=True)
    monkeypatch.setenv("VERDICT_HOME", str(home))
    for name in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / "gateway.env"
    env_file.write_text("ANTHROPIC_BASE_URL=http://gateway.invalid\nANTHROPIC_AUTH_TOKEN=t\n", encoding="utf-8")
    seen = {"launches": [], "local": []}

    def premeasure(repo_, qa_root, env, sha_range=None, run=None):
        assert facts_main(["--repo", str(repo_), "--qa-root", str(qa_root)]) == 0
        return _head(repo_)

    def local_main(argv):
        seen["local"].append(argv)
        scratch = argv[argv.index("--qa-root") + 1]
        from pathlib import Path
        _scratch_into(Path(scratch))
        return seen.get("local_exit", 0)

    def run_streaming(cmd, repo_, env, timeout_s):
        seen["launches"].append(cmd)
        rc, output = seen.get("cli", (0, "done"))
        if rc == 0 and "wrote nothing" not in output:          # a run that finalized
            (qa / "state.json").write_text(json.dumps({"run_number": 1}), encoding="utf-8")
        return rc, output

    made = []
    real_mkdtemp = escalate.tempfile.mkdtemp

    def mkdtemp(prefix=None):
        path = real_mkdtemp(prefix=prefix, dir=str(tmp_path))
        made.append(path)
        return path

    monkeypatch.setattr(runner, "premeasure", premeasure)
    monkeypatch.setattr(small, "main", local_main)
    monkeypatch.setattr(small, "gateway_alive", lambda url, token=None, timeout_s=10.0: (seen.get("alive", True), "gateway answered"))
    monkeypatch.setattr(runner, "_run_streaming", run_streaming)
    monkeypatch.setattr(runner, "evaluate", lambda *a, **k: {"verdict": "pass with risks", "exit_code": 0, "reason": "ok"})
    monkeypatch.setattr(escalate.tempfile, "mkdtemp", mkdtemp)
    seen["argv"] = ["proj", "--repo", str(repo), "--escalate", "--local-env-file", str(env_file),
                    "--local-model", "chat-120b", "--claude-cmd", sys.executable, "--no-provision"]
    seen["qa"], seen["made"] = qa, made
    return seen


def _scratch_into(scratch):
    (scratch / "state.json").write_text(json.dumps({"findings": [
        _finding("L-2", "a sale is recorded twice", "Major", "proven")]}), encoding="utf-8")
    (scratch / escalate.LEADS_FILE).write_text(json.dumps({"leads": []}), encoding="utf-8")
    facts = json.loads((scratch / "facts.json").read_text(encoding="utf-8"))
    facts["last_run"]["local"] = {"model": "chat-120b", "functions_read": 24, "calls": 51}
    (scratch / "facts.json").write_text(json.dumps(facts), encoding="utf-8")


def _prompt(cmd):
    return cmd[cmd.index("-p") + 1]


def test_an_escalation_run_hands_the_tester_the_packet_and_a_cap(wired):
    assert runner.main(wired["argv"]) == 0
    (cmd,) = wired["launches"]
    assert cmd[cmd.index("--max-budget-usd") + 1] == "2.5"
    assert "This is an escalation run" in _prompt(cmd) and "a sale is recorded twice" in _prompt(cmd)
    (argv,) = wired["local"]
    assert "--reuse-facts" in argv and argv[argv.index("--model") + 1] == "chat-120b"
    facts = json.loads((wired["qa"] / "facts.json").read_text(encoding="utf-8"))
    assert facts["last_run"]["escalation"]["proven_local"] == 1
    assert (wired["qa"] / escalate.PACKET_FILE).is_file()
    from pathlib import Path
    assert wired["made"] and not any(Path(p).exists() for p in wired["made"]), "the scratch copy is removed"


def test_an_operators_cap_after_the_double_dash_is_the_one_the_packet_names(wired):
    assert runner.main(wired["argv"] + ["--", "--max-budget-usd", "4"]) == 0
    (cmd,) = wired["launches"]
    assert cmd.count("--max-budget-usd") == 1 and "The run stops at $4" in _prompt(cmd)


def test_no_tester_is_started_when_the_breadth_pass_fails(wired, capsys):
    wired["local_exit"] = 1
    assert runner.main(wired["argv"]) == 5
    assert wired["launches"] == [] and "no escalation run was started" in capsys.readouterr().err
    assert not (wired["qa"] / "run-in-progress.json").exists(), "the measurement's marker is dropped"


def test_no_tester_is_started_when_the_gateway_is_down(wired, capsys):
    wired["alive"] = False
    assert runner.main(wired["argv"]) == 5
    assert wired["launches"] == [] and wired["local"] == []


def test_an_escalation_run_without_a_gateway_is_refused_before_anything_runs(wired, capsys):
    argv = [a for a in wired["argv"]]
    i = argv.index("--local-env-file")
    del argv[i:i + 2]
    assert runner.main(argv) == 2
    assert wired["launches"] == [] and "needs the local gateway" in capsys.readouterr().err


def test_a_run_stopped_at_its_dollar_cap_is_not_retried(wired, capsys):
    wired["cli"] = (1, "Error: Exceeded USD budget (2.5)")
    runner.main(wired["argv"])
    assert len(wired["launches"]) == 1, "a second attempt would spend the cap again"
    assert "stopped at its dollar cap" in capsys.readouterr().err


def test_a_session_ending_without_state_is_still_retried_once(wired):
    wired["cli"] = (0, "looked around, wrote nothing")
    runner.main(wired["argv"])
    assert len(wired["launches"]) == 2



def test_the_bill_sums_every_run_the_invocation_wrote(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    rows = [{"run_number": 1, "usage": {"requests": 9, "output_tokens": 1000, "model": "claude-opus-5-5"}},
            {"run_number": 2, "usage": {"requests": 31, "output_tokens": 10000, "cache_read_input_tokens": 100000,
                                        "model": "claude-opus-5-5"}},
            {"run_number": 3, "usage": {"requests": 26, "output_tokens": 20000, "model": "claude-opus-5-5"}}]
    (qa / "usage.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    line = runner.bill_line(qa, before=1)
    assert line.startswith("57 request(s), 30,000 output and 100,000 cache-read token(s)")
    assert line.endswith("about $0.62 at list price")


def test_the_packet_names_the_functions_the_risk_focus_names(tmp_path):
    repo = tmp_path / "repo"
    (repo / "scales").mkdir(parents=True)
    (repo / "scales" / "rate.py").write_text(
        "class AverageRate:\n    def calc(self, base):\n        return 0\n\n    def other(self):\n        pass\n\n\n"
        "def set_input(x):\n    return x\n", encoding="utf-8")
    facts = {"repo": str(repo), "risk_focus": {"files": ["scales/rate.py"], "names": ["calc", "set_input"]}}
    assert escalate.named_functions(facts) == [("scales/rate.py", "AverageRate.calc"), ("scales/rate.py", "set_input")]
    assert escalate.named_functions(facts, skip={("scales/rate.py", "set_input")}) == [("scales/rate.py", "AverageRate.calc")]
    text, summary = escalate.compose(_scratch(tmp_path), facts, 2.5)
    assert "**Named in the risk focus** · `scales/rate.py::AverageRate.calc`" in text
    assert summary["named_functions"] == 2


def test_the_packet_lists_files_the_risk_focus_names(tmp_path):
    facts = {"repo": str(tmp_path), "risk_focus": {"files": [], "names": [], "named_files": ["shop/offer/benefits.py"]}}
    text, _ = escalate.compose(_scratch(tmp_path), facts, 2.5)
    assert "**Named in the risk focus** · `shop/offer/benefits.py` — the profile names this file" in text


def test_named_slots_go_round_the_files_skip_stubs_and_match_name_variants(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text(
        "class Port:\n    def settle(self):\n        ...\n\n\n"
        "class Base:\n    def settle(self):\n        msg = f'not for {self}'\n        raise NotImplementedError(msg)\n\n\n"
        "def set_input(x):\n    return x\n\n\ndef set_input_by_period(x):\n    return x\n\n\n"
        "def set_input_divide(x):\n    return x\n", encoding="utf-8")
    (repo / "b.py").write_text("def settle(x):\n    return x * 2\n", encoding="utf-8")
    facts = {"repo": str(repo), "risk_focus": {"files": ["a.py", "b.py"], "names": ["set_input", "settle"]}}
    assert escalate.named_functions(facts) == [("a.py", "set_input"), ("b.py", "settle"),
                                               ("a.py", "set_input_by_period")]


def test_a_module_in_the_reading_map_is_shown_as_a_module_with_its_coverage(tmp_path):
    facts = {"repo": str(tmp_path), "read_first": {"items": [
        {"path": "pkg/fees.py", "function": "Fees.total", "lines": "12", "risk": "fees"},
        {"path": "pkg/_babel.py", "percent": 0, "open_findings": 0, "risk": ""}]}}
    text, _ = escalate.compose(_scratch(tmp_path), facts, 2.5)
    assert "- **Read first** · `pkg/fees.py::Fees.total` (risk: fees)" in text
    assert "- **Read first** · `pkg/_babel.py` (0% of its lines covered)" in text
    assert "None" not in text and "(risk: )" not in text
