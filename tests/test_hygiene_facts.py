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


# ── tier 2 kept out of the file the tester reads ──────────────────────────
# On Sales the junk rows were 1,301 lines of facts.json, read by the tester on
# every run and needed by nobody in it: they belong to the ledger.

JUNK = {"svc/app.py": ("import os\n# TODO: remove\n\ndef f():\n    try:\n        return 1\n"
                       "    except Exception:\n        pass\n"),
        "web/app.js": "function f(){\n  debugger;\n}\n"}
KEPT = ["counts_by_kind", "filing", "items", "leads", "leads_total", "reading", "scope", "status",
        "tier2_count", "tier2_file"]


def split_run(tmp_path):
    """facts_main over a repository with one tier-1 item and three tier-2 rows."""
    repo = make_repo(tmp_path, JUNK)
    qa = tmp_path / "qa"
    qa.mkdir()
    return repo, qa, harness_facts(repo, qa)["hygiene"]


def test_facts_json_keeps_tier_one_and_every_count_but_no_tier_two_row(tmp_path):
    _repo, _qa, block = split_run(tmp_path)
    assert [(i["kind"], i["tier"]) for i in block["items"]] == [("debugger_statement", 1)]
    assert block["counts_by_kind"] == {"broad_swallow": 1, "debugger_statement": 1,
                                       "todo_comment": 1, "unused_import": 1}, "exact, all tiers"
    assert sorted(block) == KEPT
    assert "not here" in block["reading"]


def test_the_tier_two_rows_are_in_the_side_file_exactly(tmp_path):
    repo, qa, block = split_run(tmp_path)
    side = json.loads((qa / "hygiene-items.json").read_text(encoding="utf-8"))
    assert side["schema"] == 1 and block["tier2_file"] == "hygiene-items.json"
    assert block["tier2_count"] == len(side["items"]) == 3
    from verdict_mcp.hygiene import hygiene_census
    assert side["items"] == [i for i in hygiene_census(repo)["items"] if i["tier"] == 2], \
        "the same rows, every field, fingerprint included"


def test_tier2_items_reads_the_rows_back(tmp_path):
    from verdict_mcp import harness
    _repo, qa, block = split_run(tmp_path)
    side = json.loads((qa / "hygiene-items.json").read_text(encoding="utf-8"))
    assert harness.tier2_items(block, qa) == side["items"]


def test_tier2_items_is_empty_without_a_readable_side_file_and_reads_only_tier_two(tmp_path):
    from verdict_mcp import harness
    _repo, qa, block = split_run(tmp_path)
    side_file = qa / "hygiene-items.json"
    rows = json.loads(side_file.read_text(encoding="utf-8"))["items"]
    side_file.unlink()
    assert harness.tier2_items(block, qa) == []
    side_file.write_bytes(b"\xff{not json")
    assert harness.tier2_items(block, qa) == []
    side_file.write_text(json.dumps({"schema": 1, "items": [
        {"kind": "debugger_statement", "tier": 1, "path": "web/app.js", "line": 2}, "a row", 7,
        *rows]}), encoding="utf-8")
    assert harness.tier2_items(block, qa) == rows
    assert harness.tier2_items({"status": "unavailable", "reason": "no git"}, qa) == []


def test_the_local_tier_writes_the_same_split_before_it_finalizes(tmp_path):
    from test_local_delta import GATE, ScriptedModel
    repo = make_repo(tmp_path, {
        "mod.py": "import os\n\n\ndef kept(x):\n    return x + 1\n",
        "test_mod.py": "from mod import kept\n\n\ndef test_kept():\n    assert kept(1) == 2\n"})
    qa = root_with(tmp_path, f"gates:\n  suite: {GATE}\n")
    assert small.run(repo, qa, ScriptedModel(), limit=4, gate=None, reruns=0, prove=False) == 0
    block = json.loads((qa / "facts.json").read_text(encoding="utf-8"))["hygiene"]
    assert block["items"] == [] and block["counts_by_kind"] == {"unused_import": 1}
    side = json.loads((qa / "hygiene-items.json").read_text(encoding="utf-8"))
    assert [(i["kind"], i["path"]) for i in side["items"]] == [("unused_import", "mod.py")]


# ── what the ledger may read back: crafted side files ─────────────────────
# The side file sits in the QA root, where anything may have written it. Whatever
# is in it, the ledger gets well-formed tier-2 rows or nothing, and never an error.

ROW = {"kind": "todo_comment", "tier": 2, "path": "svc/app.py", "line": 2, "excerpt": "# TODO: remove",
       "why": "a TODO/FIXME/HACK left in the code", "fingerprint": "5d41402abc4b2a76"}
NAMED = {"tier2_file": "hygiene-items.json"}


def side_root(tmp_path, text: str):
    qa = tmp_path / "qa"
    qa.mkdir()
    (qa / "hygiene-items.json").write_text(text, encoding="utf-8")
    return qa


def test_a_side_file_nested_past_what_the_parser_holds_reads_as_empty(tmp_path):
    from verdict_mcp import harness
    qa = side_root(tmp_path, '{"schema": 1, "items": ' + "[" * 100_000 + "]" * 100_000 + "}")
    assert harness.tier2_items(NAMED, qa) == []


@pytest.mark.parametrize("schema", [True, 1.0])
def test_only_the_integer_schema_1_is_read(tmp_path, schema):
    from verdict_mcp import harness
    qa = side_root(tmp_path, json.dumps({"schema": schema, "items": [ROW]}))
    assert harness.tier2_items(NAMED, qa) == []


@pytest.mark.parametrize("field, value", [("path", ["svc/app.py"]), ("line", "2"), ("line", True),
                                          ("fingerprint", 7), ("excerpt", {"x": 1}), ("why", None)])
def test_a_row_with_a_field_of_the_wrong_type_is_passed_over(tmp_path, field, value):
    from verdict_mcp import harness
    qa = side_root(tmp_path, json.dumps({"schema": 1, "items": [{**ROW, field: value}, ROW]}))
    assert harness.tier2_items(NAMED, qa) == [ROW]


def test_a_block_that_was_never_split_is_read_where_its_rows_are(tmp_path):
    # A facts file written before the split, or reused by --reuse-if-fresh, still
    # holds tier 2 inline. Reading it as empty would tell a ledger every row resolved.
    from verdict_mcp import harness
    from verdict_mcp.hygiene import hygiene_census
    block = hygiene_census(make_repo(tmp_path, JUNK))
    rows = [i for i in block["items"] if i["tier"] == 2]
    qa = tmp_path / "qa"
    qa.mkdir()
    assert len(rows) == 3 and harness.tier2_items(block, qa) == rows


def test_a_side_file_that_cannot_be_written_costs_the_run_nothing(tmp_path):
    from verdict_mcp import harness
    repo = make_repo(tmp_path, JUNK)
    qa = tmp_path / "qa"
    (qa / "hygiene-items.json").mkdir(parents=True)
    block = harness_facts(repo, qa)["hygiene"]
    assert sorted(i["tier"] for i in block["items"]) == [1, 2, 2, 2], "tier 2 stays where it was"
    assert "tier2_file" not in block and "tier2_count" not in block
    assert block["tier2_note"].startswith("hygiene-items.json could not be written")
    assert [i["kind"] for i in harness.tier2_items(block, qa)] == ["unused_import", "todo_comment",
                                                                   "broad_swallow"]
    assert not list(qa.glob("*.tmp")), "a failed write leaves nothing half-written behind"


def test_every_unread_path_is_kept_for_the_ledger_though_the_display_is_capped(tmp_path, monkeypatch):
    # A ledger resolves a row when its file was read and the row is gone. A file in
    # none of the lists would have every row in it resolved by a scan that never
    # read it, so the side file keeps them all; scope shows twenty.
    from verdict_mcp import harness, hygiene
    broken = {f"m{n:02d}.py": "import os\n" for n in range(25)}
    repo = make_repo(tmp_path, {**broken, "ok.py": "import os\n"})
    real = hygiene._scan_file

    def breaks(rel, *args, **kwargs):
        if rel in broken:
            raise RuntimeError("a detector broke")
        return real(rel, *args, **kwargs)
    monkeypatch.setattr(hygiene, "_scan_file", breaks)
    qa = tmp_path / "qa"
    qa.mkdir()
    block = harness_facts(repo, qa)["hygiene"]
    assert block["status"] == "partial" and block["scope"]["failed"] == 25
    assert block["scope"]["failed_paths"] == sorted(broken)[:20], "the display stays capped"
    assert "unread_paths" not in block, "the full list is the side file's, not the tester's"
    side = json.loads((qa / "hygiene-items.json").read_text(encoding="utf-8"))
    assert side["unread_paths"] == sorted(broken)
    assert harness.unread_paths(block, qa) == set(broken)
    assert harness.unread_paths(hygiene.hygiene_census(repo), qa) == set(broken), "never split: inline"
    (qa / "hygiene-items.json").unlink()
    assert harness.unread_paths(block, qa) == set(sorted(broken)[:20]), "no side file: the capped list"
