"""The control arm of the external key: the same SWE-bench runs without Verdict.

What these tests keep from drifting is the fairness of the comparison, not the
model: the plain prompt carries the issue verbatim and none of the plugin's
vocabulary; the answer is read from exactly one place; each answered item reaches
the one scorer through the fields `cited_refs()` already reads; the launch is the
runner's launch with the plugin taken out; and nothing the plain arm does lands in
the Verdict arm's ledger. No model, no network, no environment build — the CLI is
a stub where one is launched at all.
"""

import ast
import hashlib
import inspect
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import swebench  # noqa: E402

RUNNER = REPO / "src" / "verdict_mcp" / "runner.py"
VOCABULARY = re.compile(r"\b(verdict|findings?|qa|harness)\b", re.I)
ITEM = {"title": "t", "severity": "Major", "file": "a.py", "line": 3, "mechanism": "m"}

SOURCE = "\n".join([
    "import os", "", "", "def visit(path, recurse):",           # 1-4
    "    entries = sorted(os.scandir(path))",                    # 5
    "    for entry in entries:",                                 # 6
    "        if entry.is_dir(follow_symlinks=False):",           # 7
    "            yield from visit(entry.path, recurse)",         # 8
    "", "", "def unrelated():", "    return 2", ""])             # 9-13


def git(args, cwd):
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
                   cwd=cwd, check=True, capture_output=True)


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


# ── the tables ────────────────────────────────────────────────────────────────

def _row(iid, status, anyh=None, head=None, wall=None, cost=None, **extra):
    r = {"instance_id": iid, "repo": "psf/requests", "difficulty": "<15 min fix",
         "status": status, **extra}
    if anyh is not None:
        r["score"] = {"findings": 1, "any_hit": anyh, "headline_hit": head, "headline": "X",
                      "per_finding": []}
    if wall is not None:
        r["run"] = {"wall_s": wall, "cost_usd": cost}
    return r


def test_compare_counts_only_instances_scored_in_both_arms_and_lists_disagreements():
    verdict = [
        _row("psf__requests-1", "scored", "function", "function", 600, 3.0, model="opus"),
        _row("psf__requests-2", "scored", "function", "function", 900, 4.0, model="opus"),
        _row("psf__requests-3", "blocked", "function", "function", 700, 5.0, model="opus"),
    ]
    plain = [
        _row("psf__requests-1", "scored", "function", "none", 300, 1.0, arm="plain", model="opus"),
        _row("psf__requests-2", "scored", "function", "function", 420, 2.0, arm="plain",
             model="opus"),
        _row("psf__requests-4", "no_answer", arm="plain", model="opus"),
    ]
    plain[0]["run"].update(models=["claude-opus-5"], outside_references=[
        {"tool": "Read", "why": ["archive"], "input": "/c/runs/psf__requests-1/qa/state.json"}])
    plain[1]["run"].update(models=["claude-opus-5"], outside_references=[])
    out = swebench.render_compare(verdict, plain)
    assert "Scored in both arms: 2" in out
    assert "Model: Verdict opus · plain opus (its CLI reported claude-opus-5)" in out
    assert "Plain sessions that reached past their instance: 1 of 2 — psf__requests-1" in out
    assert "| `function` | 2/2 (100%) | 2/2 (100%) | 2/2 (100%) | 1/2 (50%) |" in out
    assert "| `file` | 2/2 (100%) | 2/2 (100%) | 2/2 (100%) | 1/2 (50%) |" in out
    # medians over the two compared instances only, the table's own (upper) median
    assert "| wall time | 15 min | 7 min |" in out
    assert "| cost (CLI-reported) | $4.00 | $2.00 |" in out
    section = out.split("Instances where the arms disagree: 1", 1)[1]
    section = section.split("Not in the comparison", 1)[0]
    assert "| psf__requests-1 | function | function | function | none |" in section
    assert "psf__requests-2" not in section
    assert "- psf__requests-3: Verdict blocked, plain not run" in out
    assert "- psf__requests-4: Verdict not run, plain no_answer" in out


def test_compare_with_nothing_in_common_says_so():
    out = swebench.render_compare([_row("psf__requests-1", "scored", "file", "file", 60, 1.0)], [])
    assert "Scored in both arms: 0" in out and "|" not in out


def test_plain_table_counts_a_run_without_an_answer_and_publishes_modified_checkouts():
    rows = [
        _row("psf__requests-1", "scored", "function", "function", 600, 2.0, arm="plain",
             modified_checkout=[]),
        _row("psf__requests-2", "no_answer", arm="plain", run={"wall_s": 300, "cost_usd": 1.0},
             modified_checkout=[" M requests/models.py"],
             note="the final reply has no parseable ```json block"),
    ]
    rows[0]["run"]["outside_references"] = []
    rows[1]["run"]["outside_references"] = [{"tool": "WebSearch", "why": ["WebSearch"],
                                             "input": "{}"}]
    table = swebench.render_table(rows)
    assert "ran: 2 · scored: 1" in table
    assert "- sessions that reached past their instance (dataset, mirrors, archives, other " \
           "instances, network): 1 of 2 — psf__requests-2" in table
    assert "- checkout modified by the run (`git status --porcelain` after it): 1 of 2 — " \
           "psf__requests-2" in table
    assert "- psf__requests-2: no_answer — the final reply has no parseable" in table
    verdict_only = swebench.render_table([_row("psf__requests-1", "scored", "function",
                                               "function", 600, 2.0)])
    assert "checkout modified" not in verdict_only and "reached past" not in verdict_only, \
        "a Verdict ledger renders as it always has"


# ── the command line ──────────────────────────────────────────────────────────

def test_arm_defaults_to_verdict():
    parser = swebench.build_parser()
    assert parser.parse_args(["batch"]).arm == "verdict"
    assert parser.parse_args(["run", "psf__requests-1"]).arm == "verdict"
    table = parser.parse_args(["table"])
    assert table.arm == "verdict" and table.compare is False
    assert parser.parse_args(["batch", "--arm", "plain"]).arm == "plain"
    assert parser.parse_args(["table", "--compare"]).compare is True
    with pytest.raises(SystemExit):
        parser.parse_args(["batch", "--arm", "claude"])


def test_a_missing_env_file_is_a_usage_error_in_either_arm(tmp_path, capsys):
    """`main()` still owns the parser it reports errors through, after the parser moved into
    `build_parser()` — and no instance is looked up before the check."""
    for argv in (["batch"], ["batch", "--arm", "plain"], ["run", "psf__requests-1", "--arm", "plain"]):
        with pytest.raises(SystemExit) as exc:
            swebench.main([*argv, "--env-file", str(tmp_path / "missing.env")])
        assert exc.value.code == 2
        assert "missing.env does not exist" in capsys.readouterr().err


def test_batch_routes_each_arm_to_its_own_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(swebench, "OUT_DIR", tmp_path)
    monkeypatch.setattr(swebench, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(swebench, "RESULTS_PLAIN", tmp_path / "results-plain.jsonl")
    monkeypatch.setattr(swebench, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(swebench, "CLAUDE_CMD", sys.executable)
    inst = {"instance_id": "psf__requests-1", "repo": "psf/requests", "version": "2.0",
            "difficulty": "<15 min fix"}
    monkeypatch.setattr(swebench, "instances", lambda: [inst])
    monkeypatch.setattr(swebench, "resolve_root", lambda explicit: tmp_path)
    calls = []

    def fake_one(i, args, root):
        calls.append(("verdict", root))
        return {"instance_id": i["instance_id"], "repo": i["repo"], "status": "scored"}

    def fake_plain(i, args):
        calls.append(("plain", None))
        return {"instance_id": i["instance_id"], "repo": i["repo"], "status": "no_answer",
                "arm": "plain"}

    monkeypatch.setattr(swebench, "one", fake_one)
    monkeypatch.setattr(swebench, "one_plain", fake_plain)

    assert swebench.main(["batch"]) == 0
    assert calls == [("verdict", tmp_path)]
    assert not (tmp_path / "results-plain.jsonl").exists()

    assert swebench.main(["batch", "--arm", "plain"]) == 0
    assert calls[-1] == ("plain", None), "a Verdict row does not mark the instance done for plain"
    verdict_rows = swebench.load_results(tmp_path / "results.jsonl")
    plain_rows = swebench.load_results(tmp_path / "results-plain.jsonl")
    assert [r.get("arm") for r in verdict_rows] == [None]
    assert [r.get("arm") for r in plain_rows] == ["plain"]

    assert swebench.main(["batch", "--arm", "plain"]) == 0 and len(calls) == 2, "resumable"
    assert swebench.main(["batch", "--arm", "plain", "--retry", "no_answer"]) == 0
    assert calls[-1] == ("plain", None) and len(calls) == 3
    assert len(swebench.load_results(tmp_path / "results.jsonl")) == 1
    with pytest.raises(SystemExit):
        swebench.main(["batch", "--arm", "plain", "--plugin-root", str(tmp_path)])
    with pytest.raises(SystemExit, match="--reuse is refused"):
        swebench.main(["batch", "--arm", "plain", "--reuse"])
    assert len(calls) == 3, "refused before any instance"


def test_run_with_arm_plain_appends_to_the_plain_ledger_unless_dry(tmp_path, monkeypatch):
    monkeypatch.setattr(swebench, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(swebench, "RESULTS_PLAIN", tmp_path / "results-plain.jsonl")
    monkeypatch.setattr(swebench, "CLAUDE_CMD", sys.executable)
    monkeypatch.setattr(swebench, "instances",
                        lambda: [{"instance_id": "psf__requests-1", "repo": "psf/requests"}])
    monkeypatch.setattr(swebench, "resolve_root",
                        lambda explicit: pytest.fail("the plain arm resolves no plugin"))
    monkeypatch.setattr(swebench, "one", lambda *a: pytest.fail("the Verdict arm must not run"))
    monkeypatch.setattr(swebench, "one_plain", lambda i, args: {
        "instance_id": i["instance_id"], "repo": i["repo"], "status": "scored", "arm": "plain",
        "score": {"any_hit": "file"}})
    assert swebench.main(["run", "psf__requests-1", "--arm", "plain", "--dry"]) == 0
    assert not (tmp_path / "results-plain.jsonl").exists()
    assert swebench.main(["run", "psf__requests-1", "--arm", "plain"]) == 0
    assert [r["arm"] for r in swebench.load_results(tmp_path / "results-plain.jsonl")] == ["plain"]
    assert not (tmp_path / "results.jsonl").exists()


def test_table_reads_the_ledger_the_arm_names_and_compare_reads_both(tmp_path, monkeypatch,
                                                                    capsys):
    monkeypatch.setattr(swebench, "RESULTS", tmp_path / "results.jsonl")
    monkeypatch.setattr(swebench, "RESULTS_PLAIN", tmp_path / "results-plain.jsonl")
    assert swebench.main(["table", "--arm", "plain"]) == 0
    assert capsys.readouterr().out == "no results yet\n"
    swebench.append_result(_row("psf__requests-1", "scored", "function", "function", 600, 3.0,
                                model="opus"))
    swebench.append_result(_row("psf__requests-1", "scored", "file", "none", 300, 1.0,
                                arm="plain", model="opus"), tmp_path / "results-plain.jsonl")
    assert swebench.main(["table"]) == 0
    assert "| psf__requests-1 | <15 min fix | scored | 1 | function | function |" in \
        capsys.readouterr().out
    assert swebench.main(["table", "--arm", "plain"]) == 0
    assert "| psf__requests-1 | <15 min fix | scored | 1 | file | none |" in capsys.readouterr().out
    assert swebench.main(["table", "--compare"]) == 0
    compare = capsys.readouterr().out
    assert "Scored in both arms: 1" in compare
    assert "| psf__requests-1 | function | file | function | none |" in compare


@pytest.mark.skipif(os.name == "nt", reason="sh stub")
def test_claude_version_reads_the_cli_and_survives_its_absence(tmp_path, monkeypatch):
    stub = write_stub(tmp_path, 'import sys\nassert sys.argv[1:] == ["--version"]\n'
                                'print("2.1.263 (Claude Code)")', "claude-version")
    monkeypatch.setattr(swebench, "CLAUDE_CMD", str(stub))
    assert swebench.claude_version() == "2.1.263 (Claude Code)"
    monkeypatch.setattr(swebench, "CLAUDE_CMD", str(tmp_path / "no-such-cli"))
    assert swebench.claude_version() is None


# ── the launch ────────────────────────────────────────────────────────────────

def test_the_plain_argv_is_still_the_one_the_runner_builds():
    """A tripwire read from the source, not a run: when `verdict-run` changes the
    command or the variables it launches the CLI with, the control is re-derived."""
    tree = ast.parse(RUNNER.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")

    def assigned(name):
        return [n.value for n in ast.walk(main) if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == name for t in n.targets)]

    (cmd,) = assigned("cmd")
    shape = [e.value if isinstance(e, ast.Constant) else type(e).__name__ for e in cmd.elts]
    assert shape == ["Attribute", "-p", "Name", "--model", "Attribute", "--setting-sources",
                     "project,local", "Starred"]
    strings = {n.value for n in ast.walk(main) if isinstance(n, ast.Constant)}
    assert "--dangerously-skip-permissions" in strings
    env_calls = [v for v in assigned("env") if isinstance(v, ast.Call)]
    assert [sorted(k.arg for k in c.keywords) for c in env_calls] == \
        [["VERDICT_MODEL", "VERDICT_STRICT"]]
    harness = inspect.getsource(swebench.run_instance)
    assert '"--", "--output-format", "json"]' in harness
    assert 'env.pop("CLAUDE_PLUGIN_ROOT", None)' in harness
    assert swebench.plain_argv("P", "opus") == [
        swebench.CLAUDE_CMD, "-p", "P", "--model", "opus", "--setting-sources", "project,local",
        "--output-format", "json", "--dangerously-skip-permissions"]


def write_stub(tmp_path, body, name):
    """A stand-in for the claude CLI (the runner tests' pattern)."""
    stub = tmp_path / name
    stub.write_text(f"#!/bin/sh\nexec '{sys.executable}' - \"$@\" <<'PY'\n{body}\nPY\n",
                    encoding="utf-8")
    stub.chmod(0o755)
    return stub


RECORD = r'''
import json, os, sys
dump = os.environ["PLAIN_STUB_DUMP"]
calls = json.load(open(dump)) if os.path.exists(dump) else []
calls.append({"argv": sys.argv[1:], "cwd": os.getcwd(),
              "verdict_vars": sorted(k for k in os.environ if k.startswith("VERDICT_")),
              "plugin_root": os.environ.get("CLAUDE_PLUGIN_ROOT"),
              "config_dir": os.environ.get("CLAUDE_CONFIG_DIR")})
json.dump(calls, open(dump, "w"))
'''
ANSWER = RECORD + r'''
reply = "Traced it.\n\n```json\n[{\"title\": \"t\", \"severity\": \"Major\", \"file\": \"a.py\", \"line\": 3, \"mechanism\": \"m\"}]\n```\n"
print(json.dumps({"type": "result", "subtype": "success", "result": reply, "session_id": "sess-1",
                  "total_cost_usd": 1.25, "num_turns": 7,
                  "usage": {"input_tokens": 3, "output_tokens": 5},
                  "modelUsage": {"claude-opus-5": {"outputTokens": 5}}}))
'''
PROSE = RECORD + r'''
print(json.dumps({"type": "result", "subtype": "success", "session_id": "sess-%d" % len(calls),
                  "result": "The defect is in a.py around line 3."}))
'''
LIMITED_ONCE = RECORD + r'''
if len(calls) == 1:
    print("You've hit your session limit - resets 3:00am")
    sys.exit(1)
''' + ANSWER[len(RECORD):]


@pytest.fixture()
def plain_run(tmp_path, monkeypatch):
    work = tmp_path / "work"
    checkout = work / "psf__requests-1"
    checkout.mkdir(parents=True)
    (work / "logs").mkdir()
    for key in ("CLAUDE_CONFIG_DIR", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "qa-home"))
    monkeypatch.setenv("VERDICT_STRICT", "1")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "plugin"))
    monkeypatch.setenv("PLAIN_STUB_DUMP", str(tmp_path / "calls.json"))
    return {"work": str(work), "checkout": str(checkout)}, tmp_path


def _calls(tmp_path):
    return json.loads((tmp_path / "calls.json").read_text(encoding="utf-8"))


@pytest.mark.skipif(os.name == "nt", reason="sh stub")
def test_the_plain_launch_is_the_runners_launch_without_the_plugin(plain_run, monkeypatch):
    info, tmp_path = plain_run
    monkeypatch.setattr(swebench, "CLAUDE_CMD", str(write_stub(tmp_path, ANSWER, "claude-ok")))
    cfg = tmp_path / "cfg"
    run = swebench.run_plain_instance(info, "PROMPT TEXT", "opus", 60, 1,
                                      extra_env={"CLAUDE_CONFIG_DIR": str(cfg)})
    (call,) = _calls(tmp_path)
    assert call["argv"] == ["-p", "PROMPT TEXT", "--model", "opus", "--setting-sources",
                            "project,local", "--output-format", "json",
                            "--dangerously-skip-permissions"]
    checkout = Path(info["checkout"]).resolve()
    assert call["cwd"] == str(checkout)
    assert call["verdict_vars"] == [] and call["plugin_root"] is None, \
        "no VERDICT_* variable and no plugin root reach the CLI"
    assert call["config_dir"] == str(cfg)
    seeded = json.loads((cfg / ".claude.json").read_text(encoding="utf-8"))
    assert seeded["bypassPermissionsModeAccepted"] is True
    assert seeded["projects"][str(checkout)]["hasTrustDialogAccepted"] is True
    assert run["answer"] == [ITEM]
    assert (run["session_id"], run["cost_usd"], run["num_turns"]) == ("sess-1", 1.25, 7)
    assert run["tokens"]["output_tokens"] == 5 and run["models"] == ["claude-opus-5"]
    assert (run["session_attempts"], run["cli_exit"], run["session_limited"]) == (1, 0, False)
    log = Path(run["log"])
    assert log.name == "run1.log" and '"type": "result"' in log.read_text(encoding="utf-8")
    assert (Path(info["work"]) / "prompt.md").read_text(encoding="utf-8") == "PROMPT TEXT"


@pytest.mark.skipif(os.name == "nt", reason="sh stub")
def test_a_reply_without_an_answer_block_is_retried_once(plain_run, monkeypatch):
    info, tmp_path = plain_run
    monkeypatch.setattr(swebench, "CLAUDE_CMD", str(write_stub(tmp_path, PROSE, "claude-prose")))
    run = swebench.run_plain_instance(info, "P", "opus", 60, 1)
    assert len(_calls(tmp_path)) == 2 and run["session_attempts"] == 2, \
        "as the runner retries a run that wrote no state — once"
    assert run["answer"] is None and run["final_text"] == "The defect is in a.py around line 3."
    assert "retrying once" in run["output"] and not run["session_limited"]


@pytest.mark.skipif(os.name == "nt", reason="sh stub")
def test_a_session_limit_is_slept_through_and_retried(plain_run, monkeypatch):
    info, tmp_path = plain_run
    monkeypatch.setattr(swebench, "CLAUDE_CMD",
                        str(write_stub(tmp_path, LIMITED_ONCE, "claude-limited")))
    slept = []
    monkeypatch.setattr(swebench.time, "sleep", slept.append)
    run = swebench.run_plain_instance(info, "P", "opus", 60, 1)
    assert len(slept) == 1 and slept[0] > 0
    assert run["session_attempts"] == 2 and run["answer"] == [ITEM]
    assert run["session_limited"], "the output names the limit, as the Verdict arm's relay does"


# ── what else the session could see ───────────────────────────────────────────

def test_auto_memory_and_attached_instructions_are_read_from_the_config_directory(tmp_path):
    cwd = tmp_path / "work" / "psf__requests-1"
    project = tmp_path / "cfg" / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", str(cwd))
    (project / "memory").mkdir(parents=True)
    cfg = tmp_path / "cfg"
    assert swebench.auto_memory_files(cwd, cfg) == []
    (project / "memory" / "MEMORY.md").write_text("- a note", encoding="utf-8")
    assert swebench.auto_memory_files(cwd, cfg) == ["MEMORY.md"]

    assert swebench.instruction_files(cwd, "s-1", cfg) is None, "no transcript, nothing to say"
    attached = {"type": "attachment", "attachment": {"type": "instructions", "files": [
        {"path": "/home/u/.claude/CLAUDE.md", "type": "Project", "content": "rules"}]}}
    (project / "s-1.jsonl").write_text(json.dumps({"type": "user"}) + "\n"
                                       + json.dumps(attached) + "\n", encoding="utf-8")
    sub = project / "s-1" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-a.jsonl").write_text(json.dumps({"type": "attachment", "attachment": {
        "type": "instructions", "files": [{"path": "/w/CLAUDE.md"},
                                          {"path": "/home/u/.claude/CLAUDE.md"}]}}) + "\n",
        encoding="utf-8")
    assert swebench.instruction_files(cwd, "s-1", cfg) == ["/home/u/.claude/CLAUDE.md",
                                                           "/w/CLAUDE.md"]
    (project / "s-2.jsonl").write_text(json.dumps({"type": "user"}) + "\n", encoding="utf-8")
    assert swebench.instruction_files(cwd, "s-2", cfg) == []


def test_outside_references_name_what_a_session_reached_past_its_instance(tmp_path, monkeypatch):
    monkeypatch.setattr(swebench, "CACHE", tmp_path / "verdict-swebench")
    cwd = tmp_path / "verdict-swebench" / "work" / "psf__requests-1" / "psf__requests-1"
    cfg = tmp_path / "cfg"
    project = cfg / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", str(cwd))
    (project / "s-1" / "subagents").mkdir(parents=True)
    here = f"{tmp_path}/verdict-swebench/work/psf__requests-1"

    def call(name, **inp):
        return json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": name, "input": inp}]}})

    (project / "s-1.jsonl").write_text("\n".join([
        call("Bash", command=f"cd {here}/psf__requests-1 && {here}/venv/bin/python -m pytest -q"),
        call("Read", file_path=f"{here}/psf__requests-1/requests/models.py"),
        call("Bash", command=f"cat > {here}/scratch/notes.md <<'EOF'\ncurl github.com said so\nEOF"),
        call("Write", file_path=f"{here}/scratch/notes.md", content="see verified.json"),
        call("Bash", command="which curl && curl --version | head -2"),
        call("Read", file_path="/Users/u/.cache/verdict-swebench/runs/psf__requests-1/qa/state.json"),
        call("Bash", command="python3 - <<'PY'\nimport json\njson.load(open('../../../verified.json'))\nPY"),
        call("Bash", command="ls ../../../mirrors/psf__requests.git && "
                             "cat ../../psf__requests-2/logs/run1.log"),
    ]) + "\n", encoding="utf-8")
    (project / "s-1" / "subagents" / "agent-a.jsonl").write_text("\n".join([
        call("Grep", pattern="def send",
             path=f"{tmp_path}/verdict-swebench/work/pytest-dev__pytest-7982"),
        call("WebSearch", query="requests issue 1142 fix"),
        call("Bash", command="curl -s https://github.com/psf/requests/pull/1143.diff | head"),
        call("Bash", command="python -m pip download requests==2.0.1"),
    ]) + "\n", encoding="utf-8")
    hits = swebench.outside_references(cwd, "s-1", "psf__requests-1", cfg)
    assert [(h["tool"], h["why"]) for h in hits] == [
        ("Read", ["archive"]),
        ("Bash", ["dataset"]),
        ("Bash", ["mirrors", "instance psf__requests-2"]),
        ("Grep", ["instance pytest-dev__pytest-7982"]),
        ("WebSearch", ["WebSearch"]),
        ("Bash", ["network curl", "network github.com"]),
        ("Bash", ["network pip download"]),
    ], "its own checkout, venv and scratch are not past it; a write's content is not a read; " \
       "a heredoc'd note and `curl --version` are not network calls"
    assert hits[0]["input"].endswith("/qa/state.json")
    assert swebench.outside_references(cwd, "missing", "psf__requests-1", cfg) is None
    assert swebench.outside_references(cwd, None, "psf__requests-1", cfg) is None


def test_scrub_removes_what_was_left_for_the_verdict_arm_and_nothing_tracked(tmp_path):
    work = tmp_path / "work"
    checkout = work / "psf__requests-1"
    checkout.mkdir(parents=True)
    git(["init", "-qb", "base"], checkout)
    (checkout / "a.py").write_text("x = 1\n", encoding="utf-8")
    git(["add", "-A"], checkout)
    git(["commit", "-qm", "base"], checkout)
    (checkout / ".claude" / "agents").mkdir(parents=True)
    (checkout / ".claude" / "agents" / "verdict.md").write_text("agent", encoding="utf-8")
    (work / "qa-home" / "KEY").mkdir(parents=True)
    (work / "qa-home" / "KEY" / "profile.md").write_text("profile", encoding="utf-8")
    (work / "prompt.md").write_text("Use the verdict agent", encoding="utf-8")
    (work / "logs").mkdir()
    (work / "logs" / "run1.log").write_text("the agent's handoff", encoding="utf-8")
    info = {"work": str(work), "checkout": str(checkout), "qa_home": str(work / "qa-home")}

    assert swebench.scrub_for_plain(info) == ["qa-home", "prompt.md", "logs",
                                              "psf__requests-1/.claude"]
    assert not (work / "qa-home").exists() and not (work / "prompt.md").exists()
    assert (work / "logs").is_dir() and not any((work / "logs").iterdir())
    assert not (checkout / ".claude").exists() and (checkout / "a.py").is_file()
    assert swebench.scrub_for_plain(info) == [], "nothing left to remove the second time"

    assert swebench.porcelain(checkout) == []
    (checkout / "a.py").write_text("x = 2\n", encoding="utf-8")
    (checkout / "new.txt").write_text("n", encoding="utf-8")
    assert swebench.porcelain(checkout) == [" M a.py", "?? new.txt"]


# ── one instance, with the model and the environment stubbed ──────────────────

@pytest.fixture()
def stubbed_instance(tmp_path, monkeypatch):
    """`one_plain` with what would spend a model or build an environment replaced; the
    row, the statuses, the scrub, the grading source and the archive are the real code."""
    monkeypatch.setattr(swebench, "CACHE", tmp_path / "cache")
    iid = "psf__requests-1"
    inst = {"instance_id": iid, "repo": "psf/requests", "version": "2.0",
            "difficulty": "<15 min fix", "gold_files": ["src/pkg/pathlib.py"],
            "gold_hunks": {"src/pkg/pathlib.py": [[7, 7]]}, "base_commit": "0" * 40}
    base = tmp_path / "base"
    (base / "src" / "pkg").mkdir(parents=True)
    (base / "src" / "pkg" / "pathlib.py").write_text(SOURCE, encoding="utf-8")
    state = {"prepared": 0, "launches": [], "slept": []}

    def fake_prepare(inst_, row, keep_existing):
        state["prepared"] += 1
        work = swebench.workdir(iid)
        checkout = work / iid
        (checkout / "src" / "pkg").mkdir(parents=True)
        (checkout / "src" / "pkg" / "pathlib.py").write_text(SOURCE, encoding="utf-8")
        git(["init", "-qb", "base"], checkout)
        git(["add", "-A"], checkout)
        git(["commit", "-qm", "base"], checkout)
        (work / "logs").mkdir()
        profile = work / "qa-home" / "KEY" / "profile.md"
        profile.parent.mkdir(parents=True)
        profile.write_text("---\ngates:\n  suite: PYTHONDONTWRITEBYTECODE=1 py -m pytest -q "
                           "--junitxml={report} tests\n---\n", encoding="utf-8")
        return {"work": str(work), "checkout": str(checkout), "venv": str(work / "venv"),
                "qa_home": str(work / "qa-home"), "key": "KEY", "env_notes": [],
                "env_valid": state.get("env_valid", True), "base_date": "2021-01-01",
                "env_check": "1 of 1 withheld test(s) fail at base, all pass with the fix"}

    monkeypatch.setattr(swebench, "prepare", fake_prepare)
    monkeypatch.setattr(swebench, "row_for", lambda i: {"problem_statement": "Symlinks skipped.\n"})
    monkeypatch.setattr(swebench, "claude_version", lambda env=None: "2.1.263 (Claude Code)")
    monkeypatch.setattr(swebench, "mirror_source",
                        lambda repo, commit: swebench.checkout_source(base))
    monkeypatch.setattr(swebench, "transcript_usage", lambda *a: {"requests": 3})
    monkeypatch.setattr(swebench, "instruction_files", lambda *a: ["/home/u/.claude/CLAUDE.md"])
    monkeypatch.setattr(swebench, "outside_references", lambda *a: [])
    monkeypatch.setattr(swebench.time, "sleep", state["slept"].append)
    args = SimpleNamespace(model="opus", timeout_s=2700, reuse=False, keep=True,
                           _env={"CLAUDE_CONFIG_DIR": str(tmp_path / "cfg")})
    return inst, args, state


def fake_launch(state, replies):
    """`run_plain_instance` without a CLI: each attempt returns the next scripted reply."""
    def launch(info, prompt, model, timeout_s, attempt, extra_env=None):
        state["launches"].append({"prompt": prompt, "model": model, "timeout_s": timeout_s,
                                  "qa_root_gone": not Path(info["qa_home"]).exists()})
        reply = replies[attempt - 1]
        work = Path(info["work"])
        (work / "prompt.md").write_text(prompt, encoding="utf-8")
        (work / "logs" / f"run{attempt}.log").write_text("stub", encoding="utf-8")
        if reply.get("edit"):                     # the model writes into the checkout anyway
            (Path(info["checkout"]) / "src" / "pkg" / "pathlib.py").write_text(
                "def broken(:\n", encoding="utf-8")
        return {"cli_exit": 0, "wall_s": 61, "log": str(work / "logs" / f"run{attempt}.log"),
                "cost_usd": 1.5, "duration_api_ms": 900, "num_turns": 9,
                "session_id": f"s-{attempt}", "tokens": {"output_tokens": 9},
                "models": ["claude-opus-5"], "session_attempts": 1,
                "session_limited": bool(reply.get("limited")),
                "limit": "session" if reply.get("limited") else None, "output": reply["text"],
                "final_text": reply["text"], "answer": swebench.parse_answer(reply["text"])}
    return launch


def test_one_plain_writes_a_scored_row_graded_on_the_base_commits_source(stubbed_instance,
                                                                        monkeypatch):
    inst, args, state = stubbed_instance
    text = ("The walk never follows a symlinked directory.\n```json\n"
            + json.dumps([{"title": "symlinks not followed", "severity": "Major",
                           "file": "src/pkg/pathlib.py", "line": 5, "mechanism": "m"}])
            + "\n```\n")
    monkeypatch.setattr(swebench, "run_plain_instance",
                        fake_launch(state, [{"text": text, "edit": True}]))
    row = swebench.one_plain(inst, args)
    assert (row["status"], row["arm"], row["model"], row["attempts"]) == \
        ("scored", "plain", "opus", 1)
    assert row["prompt_template_sha256"] == swebench.PLAIN_TEMPLATE_SHA256
    assert row["claude_version"] == "2.1.263 (Claude Code)"
    assert row["modified_checkout"] == [" M src/pkg/pathlib.py"], "published, not hidden"
    assert row["score"]["headline_hit"] == "function", \
        "graded on the base commit: the checkout's copy of the file no longer parses"
    assert (row["score"]["items"], row["score"]["items_dropped"]) == (1, 0)
    assert row["run"]["transcript"] == {"requests": 3}
    assert row["run"]["instructions"] == ["/home/u/.claude/CLAUDE.md"]
    assert row["run"]["outside_references"] == []
    assert row["run"]["cost_usd"] == 1.5 and row["run"]["wall_s"] == 61
    assert not {"output", "final_text", "answer"} & set(row["run"])
    assert row["plain"] == {"test_command": "PYTHONDONTWRITEBYTECODE=1 py -m pytest -q tests",
                            "scrubbed": ["qa-home"]}
    (launch,) = state["launches"]
    assert launch["qa_root_gone"], "the generated QA profile is gone before the session"
    assert (launch["model"], launch["timeout_s"]) == ("opus", 2700)
    assert "Symlinks skipped." in launch["prompt"]
    archive = Path(row["archive"])
    assert archive == swebench.CACHE / "runs-plain" / "psf__requests-1"
    assert (archive / "final.txt").read_text(encoding="utf-8") == text
    assert json.loads((archive / "answer.json").read_text(encoding="utf-8"))[0]["line"] == 5
    assert (archive / "logs" / "run1.log").is_file() and (archive / "prompt.md").is_file()
    assert not (swebench.CACHE / "runs").exists(), "the Verdict arm's archive is never touched"


def test_one_plain_waits_out_a_session_limit_then_publishes_no_answer(stubbed_instance,
                                                                     monkeypatch):
    inst, args, state = stubbed_instance
    monkeypatch.setattr(swebench, "run_plain_instance", fake_launch(state, [
        {"text": "You've hit your session limit - resets 3:00am", "limited": True},
        {"text": "I ran out of ideas before I found it."},
    ]))
    row = swebench.one_plain(inst, args)
    assert len(state["launches"]) == 2 and row["attempts"] == 2 and len(state["slept"]) == 1
    assert row["status"] == "no_answer" and "score" not in row
    assert row["note"] == "the final reply has no parseable ```json block"
    archive = Path(row["archive"])
    assert (archive / "final.txt").read_text(encoding="utf-8") == \
        "I ran out of ideas before I found it.", "the raw final text is archived"
    assert not (archive / "answer.json").exists()


def test_one_plain_refuses_before_spending_anything(stubbed_instance, monkeypatch, tmp_path):
    inst, args, state = stubbed_instance
    monkeypatch.setattr(swebench, "run_plain_instance", fake_launch(state, []))
    cwd = (swebench.workdir(inst["instance_id"]) / inst["instance_id"]).resolve()
    memory = tmp_path / "cfg" / "projects" / re.sub(r"[^A-Za-z0-9-]", "-", str(cwd)) / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("- the bug is in pathlib", encoding="utf-8")
    row = swebench.one_plain(inst, args)
    assert row["status"] == "prepare_failed" and "auto-memory" in row["note"]
    assert state["prepared"] == 0 and not state["launches"], "no environment built, no launch"

    (memory / "MEMORY.md").unlink()
    state["env_valid"] = False
    row = swebench.one_plain(inst, args)
    assert row["status"] == "env_invalid" and state["prepared"] == 1 and not state["launches"]
