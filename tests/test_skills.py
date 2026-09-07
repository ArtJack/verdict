"""Skills for every coding agent (T-9): five `skills/*/SKILL.md` installable with
`npx skills add ArtJack/verdict`, an AGENTS.md, an llms.txt.

They restate the contract for agents that cannot run the `verdict` agent, so the
one thing that must not happen is drift: each skill names the harness it uses
and the doctrine it shares with `agents/verdict.md`, points Claude Code users at
the agent, and every file llms.txt lists exists.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS = sorted((ROOT / "skills").glob("*/SKILL.md"))
EXPECTED = {"verdict-release-risk", "verdict-verify-fix", "verdict-flaky-triage",
            "verdict-root-cause", "verdict-spec-review"}


def front_matter(text: str) -> dict:
    assert text.startswith("---\n"), "SKILL.md starts with YAML front matter"
    head = text.split("\n---\n", 1)[0][4:]
    out = {}
    for line in head.splitlines():
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def test_the_five_skills_exist_and_are_named_by_their_directory():
    assert {p.parent.name for p in SKILLS} == EXPECTED
    for path in SKILLS:
        fm = front_matter(path.read_text(encoding="utf-8"))
        assert fm["name"] == path.parent.name, path
        assert 40 <= len(fm["description"]) <= 1024, f"{path}: the description is what an agent matches on"


def test_every_skill_shares_the_contracts_doctrine_and_routes_claude_code_to_the_agent():
    for path in SKILLS:
        body = path.read_text(encoding="utf-8")
        assert "In Claude Code with the Verdict plugin" in body, path
        assert "verdict" in body.lower() and ("never fix" in body or "not yours" in body
                                              or "do not fix" in body.lower()), path


def test_the_skills_use_the_harness_the_package_ships():
    release = (ROOT / "skills" / "verdict-release-risk" / "SKILL.md").read_text(encoding="utf-8")
    for cmd in ("pip install verdict-qa-mcp", "verdict-facts", "verdict-finalize", "verdict-gate",
                "findings/<ID>.json", "still_open", "not_tested", "questions"):
        assert cmd in release, cmd
    verify = (ROOT / "skills" / "verdict-verify-fix" / "SKILL.md").read_text(encoding="utf-8")
    for term in ("verification_test", "test-ids.txt", "PYTHONDONTWRITEBYTECODE", "fix_verified"):
        assert term in verify, term
    # the isolation numbers the skills quote are the contract's, not paraphrased
    # (the contract wraps at 90 columns, so compare with whitespace folded)
    contract = " ".join((ROOT / "agents" / "verdict.md").read_text(encoding="utf-8").split())
    folded = " ".join(verify.split())
    for measured in ("0 of 4", "4 of 4", "4 of 5", "5 of 5"):
        assert measured in contract and measured in folded, measured


def test_agents_md_names_the_test_command_and_the_doctrine():
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for term in ("pytest", "eval/run_eval.py", "eval/pinned_mutants.json", "never fixes",
                 "verdict-accept", "verdict-answer", "npx skills add ArtJack/verdict"):
        assert term in text, term


def test_llms_txt_lists_files_that_exist():
    text = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert text.startswith("# Verdict\n")
    links = re.findall(r"\]\((https://raw\.githubusercontent\.com/ArtJack/verdict/main/[^)]+)\)", text)
    assert len(links) >= 12
    for url in links:
        rel = url.split("/main/", 1)[1]
        assert (ROOT / rel).is_file(), rel
