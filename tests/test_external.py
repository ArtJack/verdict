"""The money-and-security key's deterministic half: what the tester is handed, how its
checkout is cut, how a verdict is read and how a refusal is counted — everything that runs
without a model, a container or a network.

The measurement it guards is "would the gate have stopped the change that introduced the
defect": a packet that named the fix, a checkout that still held the fix commit, or a
reader that took `ship` for `do not ship` would publish a rate that means nothing.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import external  # noqa: E402

INST = {
    "id": "prices-abc1234", "kind": "money", "repo": "mirumee/prices",
    "fix_commit": "f" * 40, "base_commit": "b" * 40, "introducing_commit": "1" * 40,
    "intro_subject": 'Add "flat" discounts', "python": "3.11",
    "install": "python -m venv .venv-qa && .venv-qa/bin/pip install -q -e . pytest",
    "withheld_tests": ["tests/test_discount.py::test_flat_rounding"],
    "defect_class": "fractional cent kept after a flat discount",
    "fix_url": "https://github.com/mirumee/prices/pull/99",
}


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                          text=True).stdout.strip()


def _repo(path: Path) -> dict:
    """A tiny history: intro → base → fix, a tag on base and one after it."""
    path.mkdir()
    _git(path, "init", "-q", "-b", "trunk")
    _git(path, "config", "user.email", "m@example.com")
    _git(path, "config", "user.name", "m")
    (path / "pkg").mkdir()
    (path / "tests").mkdir()
    (path / "pkg" / "money.py").write_text("def cents(x):\n    return int(x * 100)\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "intro")
    intro = _git(path, "rev-parse", "HEAD")
    (path / "README").write_text("later work\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "unrelated")
    base = _git(path, "rev-parse", "HEAD")
    _git(path, "tag", "v1.0")
    (path / "pkg" / "money.py").write_text("def cents(x):\n    return round(x * 100)\n")
    (path / "tests" / "test_money.py").write_text(
        "from pkg.money import cents\n\ndef test_half():\n    assert cents(1.005) == 101\n")
    _git(path, "add", "-A")
    _git(path, "commit", "-qm", "Fix rounding")
    fix = _git(path, "rev-parse", "HEAD")
    _git(path, "tag", "v1.1")
    return {"intro": intro, "base": base, "fix": fix}


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(external, "CONTAINER", "/home/dev/src/bin/qa-container")
    monkeypatch.setattr(external, "SRC", tmp_path / "src")
    monkeypatch.setattr(external, "QA_HOME", tmp_path / "qa")
    return tmp_path


# ── what the tester is handed ──────────────────────────────────────────────────

def test_the_packet_gates_the_introducing_change_and_names_nothing_of_the_fix(isolated):
    co, root = isolated / "src" / "prices", isolated / "qa" / "prices"
    text = external.packet_text(INST, co, root)
    assert "git diff 1111111^..1111111" in text and str(root) in text and str(co) in text
    assert "MONEY" not in text  # the risk class is the profile's to name, in its words
    lowered = text.lower()
    # the fix's commit, its URL, its test and the defect's name; the word "fix" itself is
    # the contract's ("Verdict reports and specifies; it does not fix")
    for leak in ("fffffff", INST["defect_class"], "test_flat_rounding", "advisory", "eval",
                 "pull/99", "withheld", "regression test"):
        assert leak not in lowered, leak
    assert "start with verdict-facts, end with verdict-finalize" in text
    assert "'Add 'flat' discounts'" not in text and "Add 'flat' discounts" in text


def test_the_control_prompt_asks_for_a_verdict_line_and_one_json_block(isolated):
    co = isolated / "src" / "prices"
    text = external.plain_prompt(INST, co, isolated / "qa" / "prices-scratch")
    assert "VERDICT: ship" in text and "VERDICT: do not ship" in text
    assert '[{"title": "..."' in text            # the template's braces came out single
    lowered = text.lower()
    for leak in (INST["defect_class"], "test_flat_rounding", "eval", "fffffff", "pull/99"):
        assert leak not in lowered, leak
    assert "/home/dev/src/bin/qa-container 3.11 " in text


def test_the_profile_runs_every_gate_inside_the_container_and_names_the_risk(isolated):
    co = isolated / "src" / "prices"
    text = external.profile_text(INST, "prices", co)
    gates = [ln for ln in text.splitlines() if ln.startswith(("  suite:", "test_ids_cmd:",
                                                               "test_one_cmd:"))]
    assert len(gates) == 3
    assert all(f"/home/dev/src/bin/qa-container 3.11 {co} --" in g for g in gates)
    assert 'pytest -q -p no:cacheprovider "{id}"' in text
    assert "Risk class: **MONEY**" in text and "Security-Pass: disabled" in text
    sec = dict(INST, kind="security")
    assert "Security-Pass: enabled" in external.profile_text(sec, "prices", co)
    assert "eval" not in text.lower()


def test_the_checkout_is_named_for_the_project_not_the_instance():
    assert external.name_of(INST) == "prices"
    assert external.name_of({"repo": "py-moneyed/py-moneyed"}) == "py-moneyed"
    assert external.name_of({"repo": "Some_Org/Odd Name!"}) == "odd-name"


@pytest.mark.parametrize("path,is_test", [
    ("tests/test_money.py", True), ("src/pkg/tests/helpers.py", True), ("conftest.py", True),
    ("testing/x.py", True), ("pkg/money_test.py", True), ("pkg/money.py", False),
    ("docs/testing.rst", False), ("pkg/contest.py", False),
])
def test_test_paths_are_told_from_source(path, is_test):
    assert external.is_test_path(path) is is_test


# ── the checkout and the fix ───────────────────────────────────────────────────

def test_the_checkout_ends_at_base_on_main_with_the_future_absent(isolated):
    shas = _repo(isolated / "upstream")
    dest = isolated / "src" / "prices"
    external.checkout_at(isolated / "upstream", shas["base"], dest)
    assert _git(dest, "rev-parse", "HEAD") == shas["base"]
    assert _git(dest, "branch", "--show-current") == "main"
    assert _git(dest, "branch", "--format=%(refname:short)").split() == ["main"]
    assert _git(dest, "tag").split() == ["v1.0"]                 # the later tag is the future
    assert _git(dest, "remote") == ""
    gone = subprocess.run(["git", "cat-file", "-e", f"{shas['fix']}^{{commit}}"], cwd=dest)
    assert gone.returncode != 0                                    # not unlisted: absent
    exclude = (dest / ".git" / "info" / "exclude").read_text()
    assert ".venv-qa/" in exclude and ".qa-home/" in exclude and ".claude/" in exclude
    deny = json.loads((dest / ".claude" / "settings.json").read_text())["permissions"]["deny"]
    assert "Bash(pip install:*)" in deny and "Bash(docker:*)" in deny and "Bash(curl:*)" in deny
    assert _git(dest, "status", "--porcelain") == ""             # the settings file is excluded


def test_the_fix_splits_into_its_tests_and_its_source(isolated):
    shas = _repo(isolated / "upstream")
    test_patch, src_patch, tests, source = external.fix_patches(
        isolated / "upstream", shas["base"], shas["fix"])
    assert tests == ["tests/test_money.py"] and source == ["pkg/money.py"]
    assert "test_half" in test_patch and "round(x * 100)" not in test_patch
    assert "round(x * 100)" in src_patch and "test_half" not in src_patch
    assert external.sb.gold_of(src_patch) == {"pkg/money.py": [[1, 2]]}


def test_build_byproducts_are_excluded_and_restore_keeps_them(isolated):
    shas = _repo(isolated / "upstream")
    dest = isolated / "src" / "prices"
    external.checkout_at(isolated / "upstream", shas["base"], dest)
    (dest / "pkg.egg-info").mkdir()
    (dest / "pkg.egg-info" / "PKG-INFO").write_text("x")
    (dest / ".venv-qa").mkdir()
    assert external.exclude_untracked(dest) == ["pkg.egg-info/"]
    assert external.porcelain(dest) == []
    (dest / "stray.txt").write_text("a tester's write")
    (dest / "pkg" / "money.py").write_text("changed\n")
    external.restore(dest)
    assert external.porcelain(dest) == []
    assert (dest / "pkg.egg-info" / "PKG-INFO").exists() and (dest / ".venv-qa").is_dir()


# ── reading a run ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("text,verdict", [
    ("VERDICT: do not ship\n\nThe change truncates.", "do not ship"),
    ("**VERDICT: ship**\nNothing found.", "ship"),
    ("Some preamble\nverdict: Do Not Ship\n", "do not ship"),
    ("I would not ship this.", None),
    ("", None),
])
def test_the_control_verdict_is_read_from_its_own_line(text, verdict):
    assert external.verdict_of_plain(text) == verdict


def test_a_gate_blocks_only_on_fail_or_do_not_ship():
    assert external.blocks("verdict", "fail") is True
    assert external.blocks("verdict", "pass with risks") is False
    assert external.blocks("verdict", None) is None
    assert external.blocks("plain", "do not ship") is True
    assert external.blocks("plain", "ship") is False


def test_models_efforts_and_refusals_are_counted_once_per_response(tmp_path):
    t = tmp_path / "s.jsonl"
    rows = [
        {"type": "assistant", "effort": "xhigh",
         "message": {"id": "m1", "model": "claude-opus-5-5", "stop_reason": "tool_use"}},
        {"type": "assistant", "effort": "xhigh",            # the same response, streamed twice
         "message": {"id": "m1", "model": "claude-opus-5-5", "stop_reason": "tool_use"}},
        {"type": "assistant", "effort": "xhigh",
         "message": {"id": "m2", "model": "claude-opus-5-5", "stop_reason": "refusal"}},
        {"type": "user", "message": {"content": "stop_reason refusal is not a response"}},
    ]
    t.write_text("\n".join(json.dumps(r) for r in rows) + "\nnot json\n")
    models, efforts, refusals = external.models_and_refusals([t])
    assert models == {"claude-opus-5-5": 2} and efforts == {"xhigh": 2} and refusals == 1


def test_the_ledger_resumes_by_instance_and_arm(tmp_path):
    external.append_result({"id": "a", "arm": "plain", "kind": "money"}, tmp_path)
    external.append_result({"id": "a", "arm": "verdict", "kind": "money"}, tmp_path)
    external.append_result({"id": "b", "arm": "plain", "kind": "money"}, tmp_path)
    assert external.done_ids("plain", tmp_path) == {"a", "b"}
    assert external.done_ids("verdict", tmp_path) == {"a"}


def test_the_table_scores_only_instances_both_arms_ran(tmp_path):
    common = {"kind": "money", "stopped": None, "refusals": 0, "cost_usd": 1.0, "wall_s": 60}
    external.append_result(dict(common, id="a", arm="verdict", verdict="fail", blocks=True,
                                any_hit="function", headline_hit="hunk"), tmp_path)
    external.append_result(dict(common, id="a", arm="plain", verdict="ship", blocks=False,
                                any_hit="file", headline_hit="file"), tmp_path)
    external.append_result(dict(common, id="b", arm="verdict", verdict="fail", blocks=True,
                                any_hit="none", headline_hit="none"), tmp_path)
    table = external.render_table(None, tmp_path)
    assert "Instances scored in both arms: 1" in table
    assert "| gate blocked the change | 1/1 | 0/1 |" in table
    assert "| located, any finding, function or better | 1/1 | 0/1 |" in table
    assert "| located, any finding, file or better | 1/1 | 1/1 |" in table
    assert "| a | money | fail · function · hunk | ship · file · file |" in table


def test_lanes_split_by_repository_and_cover_every_instance():
    insts = [{"repo": r, "id": f"{r}-{k}"} for r in ("a/x", "b/y", "c/z", "d/w") for k in range(3)]
    lanes = [[i["id"] for i in insts if external.in_lane(i, f"{n}/2")] for n in (0, 1)]
    assert sorted(lanes[0] + lanes[1]) == sorted(i["id"] for i in insts)
    for lane in lanes:                       # one repository never straddles two lanes
        repos = {iid.rsplit("-", 1)[0] for iid in lane}
        assert all(r not in {iid.rsplit("-", 1)[0] for iid in other} for r in repos
                   for other in lanes if other is not lane)
    assert external.in_lane(insts[0], None)
