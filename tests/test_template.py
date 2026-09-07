"""A template is copied, not studied (H-1) — and the prompt that judged is a hash (T-6).

Every headless run learned the judgment's shape by reading `docs/state-schema.md`
and ranges of `harness.py` during the run, and three of four still met the
validator on a shape. The package ships one complete judgment instead. These
tests keep it complete: the validator that refuses the agent's judgment must
accept the template, or the template teaches a shape the harness rejects.
"""

import hashlib
import json
from pathlib import Path

from verdict_mcp.harness import collect, judgment_template, merge, render_report
from verdict_mcp.validate import validate_judgment

REPO = Path(__file__).resolve().parent.parent


def test_the_template_is_the_one_shipped_in_the_package():
    path = judgment_template()
    assert path.is_file(), path
    assert path.parent.parent.name == "verdict_mcp", "the template must live inside the package, so a wheel ships it"


def test_the_validator_accepts_the_template():
    """The whole point: a shape the validator refuses cannot be in the file
    the agent is told to copy."""
    template = json.loads(judgment_template().read_text(encoding="utf-8"))
    problems = validate_judgment(template)
    assert problems == [], problems


def test_the_template_carries_every_shape_the_validator_has_refused():
    """The shapes real runs were rejected on (itsdangerous, changesets, run 14):
    `isolation_check` an object, `verified_intact` a list, `flaky_quarantine`
    (not `quarantine`) with an expiry, `release_blockers` present, `full_sweep`
    a bool, `prose.findings` a map, a finding with `root_cause.class` and a
    declared `verification_test`."""
    t = json.loads(judgment_template().read_text(encoding="utf-8"))
    assert isinstance(t["isolation_check"], dict) and t["isolation_check"].get("result")
    assert isinstance(t["verified_intact"], list) and t["verified_intact"]
    assert "quarantine" not in t and isinstance(t["flaky_quarantine"], list)
    assert all(q.get("quarantined_until") for q in t["flaky_quarantine"])
    assert isinstance(t["release_blockers"], list) and isinstance(t["full_sweep"], bool)
    assert isinstance(t["prose"]["findings"], dict)
    proven = [f for f in t["findings"] if f.get("root_cause")]
    assert proven and isinstance(proven[0]["root_cause"]["class"]["sites"], list)
    assert all(f.get("verification_test") for f in t["findings"]), "every example finding declares its test"


def test_the_template_finalizes_into_a_valid_state(repo, qa_root):
    """Copied verbatim onto a real measurement, the template must become a
    state and a report — the agent's first judgment is exactly this."""
    facts = collect(repo, qa_root, [])
    template = json.loads(judgment_template().read_text(encoding="utf-8"))
    template["findings"] = [dict(f, id=f["id"].replace("PRICER", facts["project"].upper()))
                            for f in template["findings"]]
    template["prose"]["findings"] = {k.replace("PRICER", facts["project"].upper()): v
                                     for k, v in template["prose"]["findings"].items()}
    state = merge(facts, template, None)
    assert state["verdict"] == "pass with risks"
    report = render_report(state)
    assert "Accepted risks" not in report or "none" in report.lower()
    assert "- Harness: verdict-qa-mcp" in report


def test_facts_name_the_template_and_the_prompt_that_judged(repo, qa_root):
    facts = collect(repo, qa_root, [])
    assert Path(facts["judgment_template"]).is_file()
    who = facts["last_run"]["harness"]
    shipped = REPO / "agents" / "verdict.md"
    assert who["prompt_sha256"] == hashlib.sha256(shipped.read_bytes()).hexdigest()
    assert "provisioned_prompt_sha256" not in who, "the test repo has no .claude/agents/verdict.md"
    (repo / ".claude" / "agents").mkdir(parents=True)
    (repo / ".claude" / "agents" / "verdict.md").write_text("# an older prompt\n", encoding="utf-8")
    facts = collect(repo, qa_root, [])
    who = facts["last_run"]["harness"]
    assert who["provisioned_prompt_sha256"] == hashlib.sha256(b"# an older prompt\n").hexdigest()
    assert who["provisioned_prompt_sha256"] != who["prompt_sha256"], "a drift between the two is visible"
    state = merge(facts, {"verdict": "pass", "findings": [], "not_tested": ["x"], "report": "reports/r.md"}, None)
    assert f"prompt {who['prompt_sha256'][:12]}" in render_report(state)


def test_the_prompt_points_at_the_template_not_the_schema_doc():
    prompt = (REPO / "agents" / "verdict.md").read_text(encoding="utf-8")
    assert "judgment_template" in prompt
    assert "Start your judgment from the template" in prompt
    # the schema doc survives as the reference for a field you do not understand, and in
    # the sentence that says not to read it during the run — never as "Full schema:"
    assert "Full schema:" not in prompt, "the schema doc is no longer the starting point"
    assert prompt.count("docs/state-schema.md") <= 2, prompt.count("docs/state-schema.md")


def test_the_handoff_is_capped_at_ten_lines():
    prompt = (REPO / "agents" / "verdict.md").read_text(encoding="utf-8")
    section = prompt[prompt.index("## 13. Handoff"):]
    assert "at most ten lines" in section
    assert "Recommended tasks" not in section.split("Hand off:")[1].split("You never spawn")[0], \
        "the closing message no longer carries a second report"
