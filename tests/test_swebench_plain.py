"""The control arm of the external key, its pure half: the prompt carries the issue
verbatim and none of the plugin's vocabulary, the answer is read from exactly one
place, and each answered item reaches the one scorer through the fields
`cited_refs()` already reads. No model, no network, no environment build.
"""

import hashlib
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import swebench  # noqa: E402

VOCABULARY = re.compile(r"\b(verdict|findings?|qa|harness)\b", re.I)
ITEM = {"title": "t", "severity": "Major", "file": "a.py", "line": 3, "mechanism": "m"}

SOURCE = "\n".join([
    "import os", "", "", "def visit(path, recurse):",           # 1-4
    "    entries = sorted(os.scandir(path))",                    # 5
    "    for entry in entries:",                                 # 6
    "        if entry.is_dir(follow_symlinks=False):",           # 7
    "            yield from visit(entry.path, recurse)",         # 8
    "", "", "def unrelated():", "    return 2", ""])             # 9-13


# ── the prompt ────────────────────────────────────────────────────────────────

def test_plain_prompt_carries_the_issue_verbatim_and_none_of_the_plugins_vocabulary():
    issue = ("\n  Symlinked directories are not collected since 6.1.0.\n\n"
             "A `{repo}` placeholder and a {problem_statement} in an issue stay as written:\n"
             "```python\nconfig = {'a': 1}\n```\n\n")
    cmd = "PYTHONDONTWRITEBYTECODE=1 /w/venv/bin/python -m pytest -q -p no:cacheprovider testing"
    prompt = swebench.build_plain_prompt({"repo": "pytest-dev/pytest"},
                                         {"problem_statement": issue}, cmd, "/w/scratch")
    assert prompt.startswith("You are working in a checkout of pytest-dev/pytest at the commit "
                             "where the bug report below was filed.")
    assert f"The project's tests run with: `{cmd}`." in prompt
    assert "write scratch files under /w/scratch." in prompt
    assert "Do not fix it and do not modify any file in the repository" in prompt
    # Stripped, exactly as the Verdict arm's build_prompt strips it — and never re-scanned
    # for slots, so an issue that happens to contain `{repo}` keeps it.
    assert prompt.endswith("## Bug report (verbatim, from the project's issue tracker)\n\n"
                           + issue.strip() + "\n")
    assert not VOCABULARY.search(prompt), VOCABULARY.search(prompt)
    for definition in ("P0", "P1", "release blocker", "fix today", "Blocker ="):
        assert definition not in prompt, "the scale's names only, no severity definitions"
    assert "Blocker|Critical|Major|Minor|Trivial" in prompt


def test_headless_is_not_reused_because_it_names_the_agent():
    assert VOCABULARY.search(swebench.HEADLESS)
    prompt = swebench.build_plain_prompt({"repo": "a/b"}, {"problem_statement": "x"}, "t", "/s")
    assert swebench.HEADLESS not in prompt and "IN THIS SESSION" not in prompt


def test_the_templates_example_block_is_the_shape_the_mapper_reads():
    example = swebench.parse_answer(swebench.PLAIN_TEMPLATE)
    assert isinstance(example, list) and len(example) == 1
    assert set(example[0]) == {"title", "severity", "file", "line", "mechanism"}
    assert swebench.PLAIN_TEMPLATE_SHA256 == \
        hashlib.sha256(swebench.PLAIN_TEMPLATE.encode("utf-8")).hexdigest()


def test_plain_test_command_is_the_suite_gate_write_profile_gives_the_verdict_arm(tmp_path):
    work = tmp_path / "work"
    checkout = work / "pytest-dev__pytest-7982"
    (checkout / "testing").mkdir(parents=True)
    vpy = str(work / "venv" / "bin" / "python")
    qa = work / "qa-home" / "KEY"
    swebench.write_profile(qa, "KEY", {"repo": "pytest-dev/pytest", "version": "6.2"},
                           checkout, vpy, work / "scratch")
    profile = (qa / "profile.md").read_text(encoding="utf-8")
    cmd = swebench.plain_test_command(profile)
    base = (f"PYTHONDONTWRITEBYTECODE=1 PYTEST_DEBUG_TEMPROOT={work / 'scratch' / 'pytest-tmp'} "
            f"{vpy} -m pytest -q -p no:cacheprovider")
    assert cmd == f"{base} testing"
    assert f"  suite: {base} --junitxml={{report}} testing\n" in profile
    assert "{report}" not in cmd, "a placeholder only Verdict's facts step fills"
    with pytest.raises(RuntimeError):
        swebench.plain_test_command("---\ngates: {}\n---\n")


# ── the answer ────────────────────────────────────────────────────────────────

BLOCK = json.dumps([ITEM])


@pytest.mark.parametrize("text, expected", [
    (f"draft:\n```json\n{BLOCK}\n```\nfinal:\n```json\n[]\n```\n", []),
    (f"```json\n[]\n```\nthen, after more work:\n```json\n{BLOCK}\n```", [ITEM]),
    (f"```json\n{BLOCK}\n```\n```json\n[{{\"title\": \n```\n", None),
    ("```json\n[]\n```", []),
    ("I looked everywhere: the defect is in a.py:3, where the guard is inverted.", None),
    (f"```json\n{BLOCK}\n", None),
    ('```json\n{"title": "t"}\n```', None),
    ("```python\n[1]\n```", None),
    (f"```JSON\r\n{BLOCK}\r\n```\r\n", [ITEM]),
    ("", None),
    (None, None),
], ids=["last-block-wins", "last-block-wins-2", "malformed-last-no-fallback", "empty-list",
        "prose-only", "unterminated", "not-a-list", "other-language", "crlf-uppercase",
        "empty", "none"])
def test_parse_answer_reads_only_the_last_json_block(text, expected):
    assert swebench.parse_answer(text) == expected


def test_answer_items_reach_cited_refs_through_the_fields_it_reads():
    items = [
        {"title": "Symlinked dirs skipped", "severity": "major", "file": "src/_pytest/pathlib.py",
         "line": 561, "mechanism": "passes follow_symlinks=False; see src/_pytest/main.py:12"},
        {"title": "line in the file field", "severity": "Minor",
         "file": "src/_pytest/pathlib.py:560", "line": None, "mechanism": ""},
        {"title": "a range", "severity": "Trivial", "file": "src/_pytest/pathlib.py",
         "line": "558-562", "mechanism": ""},
        {"title": "no line", "severity": "Critical", "file": "src/_pytest/pathlib.py",
         "mechanism": "somewhere in this module"},
        "not an object",
    ]
    findings = swebench.plain_findings(items)
    assert [f["id"] for f in findings] == ["PLAIN-1", "PLAIN-2", "PLAIN-3", "PLAIN-4"]
    assert [f["severity"] for f in findings] == ["Major", "Minor", "Trivial", "Critical"]
    assert findings[0]["anchors"] == [{"ref": "src/_pytest/pathlib.py:561",
                                       "path": "src/_pytest/pathlib.py", "line": 561}]
    assert swebench.cited_refs(findings[0]) == [("src/_pytest/pathlib.py", 561),
                                                ("src/_pytest/main.py", 12)]
    assert swebench.cited_refs(findings[1]) == [("src/_pytest/pathlib.py", 560)]
    assert swebench.cited_refs(findings[2]) == [("src/_pytest/pathlib.py", 558)]
    assert swebench.cited_refs(findings[3]) == [], \
        "a file with no line cites nothing — the rule a Verdict finding's anchors follow"


def test_plain_findings_are_graded_by_the_same_scorer(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "pathlib.py").write_text(SOURCE, encoding="utf-8")
    gold = {"src/pkg/pathlib.py": [[7, 7]]}
    answer = [
        {"title": "docs nit", "severity": "Minor", "file": "README.md", "line": 1, "mechanism": "x"},
        {"title": "follows symlinks", "severity": "Major", "file": "src/pkg/pathlib.py", "line": 5,
         "mechanism": "y"},
        {"title": "elsewhere", "severity": "Minor", "file": "src/pkg/pathlib.py", "line": 12,
         "mechanism": "z"},
    ]
    score = swebench.score_findings(gold, swebench.plain_findings(answer),
                                    swebench.checkout_source(tmp_path))
    assert score["findings"] == 3 and score["any_hit"] == "function"
    assert score["headline"] == "PLAIN-2" and score["headline_hit"] == "function"
    assert [f["hit"] for f in score["per_finding"]] == ["none", "function", "hunk"]
    empty = swebench.score_findings(gold, swebench.plain_findings([]), None)
    assert (empty["findings"], empty["any_hit"], empty["headline"]) == (0, "none", None)
