"""The agent prompt is a contract with the code, and it can drift silently.

`agents/verdict.md` is the product — the judgment lives there — and it is the
largest surface in this repository with no automated coverage. Verdict has now
said so about itself in two consecutive runs.

What a model *does* with the prompt can only be measured by running one, which
is what `eval/run_eval.py` is for and what costs an API call. What can be
checked in plain CI is everything the prompt asserts about the system around
it: the files it tells the agent to read, the commands and scripts it tells it
to run, the enum values it tells it to write, and its own cross-references.
Every one of those is a thing a rename breaks, and a prompt that instructs a
model to read a deleted file or write a rejected enum value fails in the field
as confidently as it fails in CI — only later, and only on someone's real repo.

This does not measure behaviour. It measures that the prompt is still talking
about the system that exists.
"""

import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
PROMPT_PATH = REPO / "agents" / "verdict.md"
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


def test_the_prompt_is_where_the_plugin_says_it_is():
    assert PROMPT_PATH.is_file() and PROMPT.strip()


# ── what it tells the agent to read ───────────────────────────────────────

PLUGIN_ROOT_REFS = sorted(set(re.findall(r"\$\{CLAUDE_PLUGIN_ROOT\}(/[\w./-]*)", PROMPT)))


def test_the_prompt_names_plugin_root_paths_at_all():
    assert PLUGIN_ROOT_REFS, "no ${CLAUDE_PLUGIN_ROOT} references — the sweep is vacuous"


@pytest.mark.parametrize("ref", PLUGIN_ROOT_REFS)
def test_every_plugin_root_reference_resolves(ref):
    """${CLAUDE_PLUGIN_ROOT} is substituted as text, so a stale path becomes a
    read of a file that is not there — at runtime, in someone else's repo."""
    target = REPO / ref.lstrip("/")
    assert target.exists(), f"prompt reads ${{CLAUDE_PLUGIN_ROOT}}{ref}, which does not exist"


# ── what it tells the agent to run ────────────────────────────────────────

def test_every_command_it_names_is_shipped():
    shipped = {p.stem for p in (REPO / "commands").glob("*.md")}
    named = set(re.findall(r"/verdict:([a-z-]+)", PROMPT))
    assert named, "the prompt names no commands — the sweep is vacuous"
    assert named <= shipped, f"prompt routes to unshipped commands: {sorted(named - shipped)}"


def test_every_console_script_it_names_is_declared():
    declared = set(re.findall(r"^(verdict-[a-z]+)\s*=", 
                              (REPO / "pyproject.toml").read_text(encoding="utf-8"), re.M))
    named = set(re.findall(r"\b(verdict-[a-z]+)\b", PROMPT))
    assert named, "the prompt names no scripts — the sweep is vacuous"
    assert named <= declared, f"prompt runs undeclared scripts: {sorted(named - declared)}"


# ── what it tells the agent to write ──────────────────────────────────────
#
# The prompt instructs the model to produce specific enum values, and
# validate.py refuses a state that carries anything else. Drift between the two
# means the prompt teaches a model to write states the harness will reject —
# and the failure surfaces as the agent looking broken.

def _enums():
    src = (REPO / "src" / "verdict_mcp" / "validate.py").read_text(encoding="utf-8")
    out = {}
    for name in ("VERDICTS", "DELTAS", "SEVERITIES", "PRIORITIES",
                 "CLASSIFICATIONS", "CONFIDENCES", "OUTCOMES", "STATUSES"):
        m = re.search(rf"^{name} = \{{(.*?)\}}", src, re.M | re.S)
        assert m, f"{name} not found in validate.py"
        out[name] = set(re.findall(r'"([^"]+)"', m.group(1)))
    return out


ENUMS = _enums()


def test_every_shouty_token_the_prompt_teaches_is_a_real_enum_value():
    """The prompt tells the model to write `NEW`, `REAL_DEFECT` and friends, and
    validate.py refuses a state carrying anything else. A value taught here but
    rejected there makes the agent look broken while the prompt is at fault.

    Only screaming-case tokens are swept, and only against the two enums that
    use that shape — sweeping `Major` or `open` would collide with English.
    """
    accepted = ENUMS["DELTAS"] | ENUMS["CLASSIFICATIONS"]
    families = {v.split("_")[0] for v in accepted}
    claimed = {t for t in re.findall(r"\b([A-Z][A-Z_]{3,})\b", PROMPT)
               if t in accepted or t.split("_")[0] in families}
    assert claimed, "the prompt teaches no delta or classification values at all"
    assert claimed <= accepted, \
        f"prompt teaches values validate.py rejects: {sorted(claimed - accepted)}"


def test_every_delta_the_harness_computes_is_explained():
    """A delta the model meets in its own state file but has never been told
    about is a value it has to guess the meaning of."""
    for value in ENUMS["DELTAS"]:
        assert value in PROMPT, f"delta {value!r} is written by the harness but never taught"


def test_every_failure_classification_is_explained():
    """Classification is the judgment call §3 exists for; a class the prompt
    never names is one the agent will never assign."""
    for value in ENUMS["CLASSIFICATIONS"]:
        assert value in PROMPT, f"classification {value!r} is accepted but never taught"


def test_the_prompt_teaches_the_confidence_vocabulary_it_requires():
    """`confidence` is required on every NEW finding, so all three must be taught."""
    for value in ENUMS["CONFIDENCES"]:
        assert re.search(rf"`{value}`|\b{value}\b", PROMPT), \
            f"confidence value {value!r} is required by the schema but never explained"


def test_the_prompt_teaches_every_verdict_it_may_return():
    for value in ENUMS["VERDICTS"]:
        assert value in PROMPT, f"verdict {value!r} is accepted by the gate but never taught"


# ── its own cross-references ──────────────────────────────────────────────

def _sections():
    """{"8": {"1", "2", ...}} — each heading, and the numbered items beneath it.

    `§N.M` is written two ways here and both are legitimate: `§3.5` and `§4.5`
    are subsection headings, while `§8.2` is principle 2 *within* section 8.
    A checker that knows only one form reports the other as a dangling link,
    which is what the first version of this did.
    """
    out, current = {}, None
    for line in PROMPT.splitlines():
        head = re.match(r"^## (\d+(?:\.\d+)?)\.?\s", line)
        if head:
            current = head.group(1)
            out.setdefault(current, set())
            continue
        item = re.match(r"^(\d+)\. ", line)
        if item and current:
            out[current].add(item.group(1))
    return out


def test_every_section_reference_points_at_something_that_exists():
    sections = _sections()
    referenced = set(re.findall(r"§(\d+(?:\.\d+)?)", PROMPT))
    assert sections, "no numbered sections found — the heading format changed"
    assert referenced, "no § references found — the sweep is vacuous"
    dangling = []
    for ref in referenced:
        if ref in sections:
            continue
        parent, _, item = ref.partition(".")
        if parent in sections and item in sections[parent]:
            continue
        dangling.append(ref)
    assert not dangling, f"prompt cites sections that do not exist: {sorted(dangling)}"


# ── the harness contract ──────────────────────────────────────────────────

def test_the_prompt_does_not_promise_a_gate_exit_code_the_gate_cannot_emit():
    gate = (REPO / "src" / "verdict_mcp" / "gate.py").read_text(encoding="utf-8")
    real = set(re.findall(r"^  (\d)  ", gate, re.M))
    assert real, "gate.py's exit-code table is no longer parseable"
    claimed = set(re.findall(r"exit (?:code )?(\d)\b", PROMPT))
    assert claimed <= real, f"prompt promises exit codes the gate cannot emit: {sorted(claimed - real)}"


def test_plugin_manifest_points_at_this_agent():
    manifest = json.loads((REPO / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    assert manifest.get("name") == "verdict"
    assert (REPO / "agents" / f"{manifest['name']}.md").is_file()
