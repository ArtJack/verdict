"""The external key's deterministic half: instance selection, gold-patch parsing,
location scoring and the table — everything that runs without a model or a network.

The model half is `eval/swebench.py run`; these tests keep the parts that decide
whether a run *counted* from drifting: a scorer that matched a bare `utils.py` to
any `utils.py`, or read a hunk's new-side lines against a base-side anchor, would
publish a rate that means nothing.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import swebench  # noqa: E402

GOLD_PATCH = """\
diff --git a/src/pkg/pathlib.py b/src/pkg/pathlib.py
--- a/src/pkg/pathlib.py
+++ b/src/pkg/pathlib.py
@@ -558,7 +558,7 @@ def visit(
     entries = sorted(os.scandir(path), key=lambda entry: entry.name)
     yield from entries
     for entry in entries:
-        if entry.is_dir(follow_symlinks=False) and recurse(entry):
+        if entry.is_dir() and recurse(entry):
             yield from visit(entry.path, recurse)
diff --git a/src/pkg/other.py b/src/pkg/other.py
--- a/src/pkg/other.py
+++ b/src/pkg/other.py
@@ -10,0 +11,2 @@ def alpha():
+    x = 1
+    y = 2
"""

SOURCE = "\n".join(
    ["import os", "", "", "class Walker:", "    def visit(self, path):", "        pass", "",
     "    def other(self):", "        return 1", "", "", "def visit(path, recurse):",
     "    entries = sorted(os.scandir(path))", "    yield from entries",
     "    for entry in entries:", "        if entry.is_dir(follow_symlinks=False):",
     "            yield from visit(entry.path, recurse)", "", "", "def unrelated():",
     "    return 2", ""])


def test_gold_of_reads_the_base_side_ranges_and_anchors_insertions():
    gold = swebench.gold_of(GOLD_PATCH)
    assert gold == {"src/pkg/pathlib.py": [[558, 564]], "src/pkg/other.py": [[10, 10]]}


def test_same_file_needs_a_directory_qualified_suffix():
    assert swebench._same_file("src/pkg/pathlib.py", "src/pkg/pathlib.py")
    assert swebench._same_file("pkg/pathlib.py", "src/pkg/pathlib.py")
    assert swebench._same_file("./src/pkg/pathlib.py", "src/pkg/pathlib.py")
    assert not swebench._same_file("pathlib.py", "src/pkg/pathlib.py"), \
        "a bare filename matches nothing — every package has a utils.py"
    assert not swebench._same_file("src/pkg/pathlib2.py", "src/pkg/pathlib.py")


def test_enclosing_picks_the_innermost_definition():
    spans = swebench._spans(SOURCE)
    assert swebench.enclosing(spans, 5) == "Walker.visit"
    assert swebench.enclosing(spans, 16) == "visit"
    assert swebench.enclosing(spans, 1) is None


def test_level_of_grades_file_hunk_and_function(tmp_path):
    (tmp_path / "src" / "pkg").mkdir(parents=True)
    (tmp_path / "src" / "pkg" / "pathlib.py").write_text(SOURCE, encoding="utf-8")
    gold = {"src/pkg/pathlib.py": [[16, 17]]}          # the `is_dir` line, inside visit()
    src = swebench.checkout_source(tmp_path)
    assert swebench.level_of([("src/pkg/pathlib.py", 16)], gold, src)[0] == "function"
    assert swebench.level_of([("src/pkg/pathlib.py", 13)], gold, src)[0] == "function", \
        "same function counts even outside the hunk's slack"
    assert swebench.level_of([("src/pkg/pathlib.py", 21)], gold, src)[0] == "hunk", \
        "within slack of the hunk but a different function"
    far = {"src/pkg/pathlib.py": [[100, 101]]}
    assert swebench.level_of([("src/pkg/pathlib.py", 5)], far, src)[0] == "file"
    assert swebench.level_of([("src/pkg/zzz.py", 5)], gold, src)[0] == "none"
    assert swebench.level_of([], gold, src) == ("none", [])
    assert swebench.level_of([("src/pkg/pathlib.py", 16)], gold, None)[0] == "hunk", \
        "no source → no function grade, the hunk grade stands"


def test_level_of_survives_a_file_that_does_not_parse(tmp_path):
    (tmp_path / "a.py").write_text("def broken(:\n", encoding="utf-8")
    level, _ = swebench.level_of([("a.py", 3)], {"a.py": [[1, 5]]},
                                 swebench.checkout_source(tmp_path))
    assert level == "hunk", "no AST → the hunk grade still stands"


def test_cited_refs_takes_anchors_first_and_prose_second():
    finding = {
        "title": "`visit` follows symlinked dirs (src/pkg/pathlib.py:561)",
        "anchors": [{"ref": "src/pkg/pathlib.py:561", "path": "src/pkg/pathlib.py", "line": 561},
                    {"ref": "nowhere.py:1", "status": "unresolvable"}],
        "root_cause": {"mechanism": "see src/pkg/other.py:12", "origin": "abc123"},
    }
    assert swebench.cited_refs(finding) == [("src/pkg/pathlib.py", 561), ("src/pkg/other.py", 12)]


def test_score_instance_reads_state_and_grades_the_headline(tmp_path):
    qa = tmp_path / "qa"
    qa.mkdir()
    checkout = tmp_path / "co"
    (checkout / "src" / "pkg").mkdir(parents=True)
    (checkout / "src" / "pkg" / "pathlib.py").write_text(SOURCE, encoding="utf-8")
    inst = {"gold_hunks": {"src/pkg/pathlib.py": [[16, 17]]}}
    state = {
        "verdict": "fail", "run_number": 1,
        "last_run": {"report": "reports/r.md",
                     "harness": {"version": "0.86.0", "provisioned_prompt_sha256": "p" * 64}},
        "findings": [
            {"id": "X-F-1", "severity": "Minor", "status": "open", "title": "a docs nit",
             "anchors": [{"ref": "README.md:1", "path": "README.md", "line": 1}]},
            {"id": "X-F-2", "severity": "Major", "status": "open", "title": "the symlink follow",
             "anchors": [{"ref": "src/pkg/pathlib.py:16", "path": "src/pkg/pathlib.py",
                          "line": 16}]},
            {"id": "X-F-3", "severity": "Critical", "status": "resolved", "title": "closed",
             "anchors": [{"ref": "src/pkg/pathlib.py:16", "path": "src/pkg/pathlib.py",
                          "line": 16}]},
        ],
    }
    (qa / "state.json").write_text(json.dumps(state), encoding="utf-8")
    score = swebench.score_instance(inst, qa, swebench.checkout_source(checkout))
    assert score["state"] == "read" and score["findings"] == 2, "a resolved finding is not open"
    assert score["any_hit"] == "function"
    assert score["headline"] == "X-F-2" and score["headline_hit"] == "function"
    assert score["prompt_sha256"] == "p" * 64


def test_score_instance_without_state_is_missing(tmp_path):
    score = swebench.score_instance({"gold_hunks": {}}, tmp_path, None)
    assert score["state"] == "missing" and score["any_hit"] == "none"


def test_select_takes_every_instance_of_the_small_repositories():
    rows = []
    for repo, n in (("big/one", 25), ("small/a", 3), ("small/b", 19)):
        for i in range(n):
            rows.append({"instance_id": f"{repo.replace('/', '__')}-{i}", "repo": repo,
                         "version": "1.0", "difficulty": "<15 min fix", "base_commit": "0" * 40,
                         "created_at": "2024-01-01T00:00:00Z", "patch": GOLD_PATCH,
                         "FAIL_TO_PASS": '["t::x"]', "problem_statement": "x"})
    chosen = swebench.select_instances(rows)
    assert {c["repo"] for c in chosen} == {"small/a", "small/b"}
    assert len(chosen) == 22
    assert chosen[0]["gold_files"] == ["src/pkg/other.py", "src/pkg/pathlib.py"]
    assert chosen[0]["fail_to_pass"] == ["t::x"]


def test_result_line_finds_the_cli_result_in_the_runner_relay():
    output = ("verdict-run: project 'x'\n"
              '{"type":"system","subtype":"init"}\n'
              '{"type":"result","subtype":"success","total_cost_usd":1.25,'
              '"usage":{"input_tokens":10,"output_tokens":20},"num_turns":3}\n'
              "verdict-run: verdict 'fail' → exit 1\n")
    res = swebench.result_line(output)
    assert res["total_cost_usd"] == 1.25 and res["num_turns"] == 3
    assert swebench.result_line("nothing here") == {}


def test_build_prompt_carries_the_issue_verbatim_and_the_shipped_command(tmp_path):
    root = tmp_path / "root"
    (root / "commands").mkdir(parents=True)
    (root / "commands" / "bug.md").write_text(
        "---\ndescription: x\n---\n\nUse the `verdict` agent to process this bug:\n\n"
        "`$ARGUMENTS`\n\n- `${CLAUDE_PLUGIN_ROOT}/templates/bug-report.md`\n",
        encoding="utf-8")
    row = {"problem_statement": "Symlinked directories are not collected.\n\nSince 6.1.0 ..."}
    prompt = swebench.build_prompt(root, row)
    assert "Symlinked directories are not collected." in prompt
    assert str(root / "templates" / "bug-report.md") in prompt
    assert "$ARGUMENTS" not in prompt and "${CLAUDE_PLUGIN_ROOT}" not in prompt
    assert "IN THIS SESSION" in prompt and "does not fix" in prompt


def test_table_counts_levels_and_survives_unscored_rows():
    rows = [
        {"instance_id": "a-1", "repo": "psf/requests", "difficulty": "<15 min fix",
         "status": "scored", "score": {"findings": 2, "any_hit": "function",
                                       "headline_hit": "hunk"},
         "run": {"wall_s": 600, "cost_usd": 2.0}},
        {"instance_id": "a-2", "repo": "psf/requests", "difficulty": "<15 min fix",
         "status": "scored", "score": {"findings": 1, "any_hit": "none", "headline_hit": "none"},
         "run": {"wall_s": 900, "cost_usd": 3.0}},
        {"instance_id": "b-1", "repo": "pytest-dev/pytest", "difficulty": "1-4 hours",
         "status": "env_invalid", "note": "withheld tests already pass at base"},
    ]
    table = swebench.render_table(rows)
    assert "scored: 2" in table
    assert "located at `hunk` or better — any finding: 1/2 (50%); headline finding: 1/2 (50%)" \
        in table
    assert "| b-1 | 1-4 hours | env_invalid | — | — | — | — | — |" in table
    assert "total $5.00" in table


@pytest.mark.parametrize("bad", ["", "no patch here"])
def test_gold_of_empty(bad):
    assert swebench.gold_of(bad) == {}
