"""The hygiene block as a run records it: the profile's `hygiene:` setting reaching
both engines, and tier 2 kept out of the file the tester reads.

The scan itself is tested in test_hygiene.py. What these guard is the wiring. A
setting that `verdict-facts` honours and the local tier ignores is a control that
works on one engine only, and the local tier is the one that runs every night.
"""

import json

import pytest

from verdict_mcp import small
from verdict_mcp.harness import facts_main
from verdict_mcp.profile import load as load_profile

from test_hygiene import make_repo  # noqa: E402


def root_with(tmp_path, front_matter: str):
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "profile.md").write_text(f"---\n{front_matter}---\n# p\n", encoding="utf-8")
    return qa


def harness_facts(repo, qa):
    """What `verdict-facts` writes, read back from the QA root."""
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    return json.loads((qa / "facts.json").read_text(encoding="utf-8"))


def local_facts(repo, qa):
    """What the local tier measures, the way `verdict-local` does it: `run` reads the
    profile, `measure` takes it from there. The real scan, and no model."""
    config, notes = load_profile(qa)
    return small.measure(repo, qa, [], config, None, notes)


ENGINES = pytest.mark.parametrize("measured", [harness_facts, local_facts],
                                  ids=["verdict-facts", "verdict-local"])


# ── the profile's `hygiene:` setting ──────────────────────────────────────

def test_the_local_tier_honours_hygiene_off(tmp_path):
    repo = make_repo(tmp_path, {"a.py": "import os\n"})
    facts = local_facts(repo, root_with(tmp_path, "hygiene: off\n"))
    assert facts["hygiene"]["filing"] == "off"
    assert facts["hygiene"]["counts_by_kind"] == {"unused_import": 1}, "counted, never filed"


@ENGINES
@pytest.mark.parametrize("value", ["false", "No"])
def test_false_and_no_turn_filing_off_in_any_case(tmp_path, measured, value):
    repo = make_repo(tmp_path, {"a.py": "import os\n"})
    facts = measured(repo, root_with(tmp_path, f"hygiene: {value}\n"))
    assert facts["hygiene"]["filing"] == "off"


@ENGINES
def test_a_setting_it_cannot_read_leaves_filing_on_and_says_so(tmp_path, measured):
    repo = make_repo(tmp_path, {"a.py": "import os\n"})
    facts = measured(repo, root_with(tmp_path, "hygiene: sometimes\n"))
    assert facts["hygiene"]["filing"] == "on"
    assert "hygiene: 'sometimes' is not understood — filing stays on" in facts.get("profile_notes", [])
