"""The scope a profile names steers the breadth pass (0.92.0)."""

import json

from conftest import git
from verdict_mcp import focus, small
from verdict_mcp.harness import facts_main

PROFILE = """# QA Profile — shop

## What this project is

A shop. `ignored_name` here is not a risk.

## Risk focus: money

- **Fees.** `shop/fees/`: `charge_fee`, `Refunds.apply()`, rounding of totals.
- **Budgets.** Proration across partial periods and the budgets report.
- **Out of scope:** `shop/admin/` and `render_widget`.

## Real commands
"""


def test_the_risk_section_gives_paths_names_and_words_and_nothing_out_of_scope():
    paths, names = focus.terms(PROFILE)
    assert paths == ["shop/fees"] and names == ["charge_fee", "apply"]
    stems = focus.words(PROFILE)
    assert "budget" in stems and "proration" in stems and "ignored_name" not in stems
    assert [focus._stem(w) for w in ("prices", "basis", "status", "class")] == ["price", "basis", "status", "class"]
    assert "render_widget" not in names and "shop/admin" not in paths


def _shop(tmp_path):
    repo = tmp_path / "shop"
    for rel, text in {"shop/fees/core.py": "def charge_fee(x):\n    return x\n",
                      "shop/fees/util.py": "def helper():\n    pass\n",
                      "shop/orders.py": "class Refunds:\n    def apply(self):\n        pass\n\ndef charge_fee(y):\n    pass\n",
                      "shop/budgets.py": "def report():\n    pass\n",
                      "shop/admin/views.py": "def render_widget():\n    pass\n",
                      "shop/migrations/0001_fees.py": "def charge_fee():\n    pass\n",
                      "tests/test_fees.py": "def charge_fee():\n    pass\n"}.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(["init", "-qb", "main"], repo)
    git(["add", "-A"], repo)
    git(["commit", "-qm", "shop"], repo)
    return repo


def test_files_that_define_named_code_come_first_then_named_paths_then_named_words(tmp_path):
    repo = _shop(tmp_path)
    got = focus.risk_focus(repo, PROFILE, is_test=lambda p: p.startswith("tests/"))
    assert got["files"][:2] == ["shop/orders.py", "shop/fees/core.py"], got
    assert got["files"][2] == "shop/fees/util.py" and got["files"][3] == "shop/budgets.py"
    assert not any(f.startswith(("tests/", "shop/migrations/", "shop/admin/")) for f in got["files"])
    assert focus.risk_focus(repo, "# QA Profile\n\nNo risk section.\n") is None


def test_the_breadth_pass_reads_survivors_then_the_named_scope_then_the_coverage_order(tmp_path):
    repo = _shop(tmp_path)
    facts = {"assertion_gaps": {"survived": [{"path": "shop/budgets.py", "function": "report"}]},
             "risk_focus": {"files": ["shop/orders.py", "shop/fees/core.py"], "names": ["apply"]},
             "reading_map": {"lowest": [{"path": "shop/fees/util.py"}]}}
    assert small.candidates(facts, repo)[:4] == ["shop/budgets.py", "shop/orders.py", "shop/fees/core.py",
                                                 "shop/fees/util.py"]
    # File order puts the top-level `charge_fee` before the method `apply`; the named one goes first.
    assert [c.name for c in small.ordered_chunks(repo, "shop/orders.py", None, None)][0] == "charge_fee"
    names = [c.name for c in small.ordered_chunks(repo, "shop/orders.py", None, None, {"apply"})]
    assert names[0] == "apply", names


def test_facts_record_the_scope_the_profile_names(tmp_path):
    repo = _shop(tmp_path)
    qa = tmp_path / "qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "profile.md").write_text(PROFILE, encoding="utf-8")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    facts = json.loads((qa / "facts.json").read_text(encoding="utf-8"))
    assert facts["risk_focus"]["paths"] == ["shop/fees"] and "shop/orders.py" in facts["risk_focus"]["files"]
    # The reading map counts the named scope as risk when the profile sets no risk_paths.
    (repo / "shop" / "orders.py").write_text("class Refunds:\n    def apply(self):\n        return 1\n",
                                             encoding="utf-8")
    git(["commit", "-qam", "apply returns"], repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa), "--range",
                       f"{facts['last_run']['git_sha']}..HEAD"]) == 0
    rf = json.loads((qa / "facts.json").read_text(encoding="utf-8"))["read_first"]
    assert rf["items"][0]["path"] == "shop/orders.py" and rf["items"][0]["risk"] == "risk focus", rf


def test_a_file_named_outright_ranks_first_and_specific_names_beat_generic_ones(tmp_path):
    repo = tmp_path / "shop"
    files = {"shop/offer/benefits.py": "def apply_benefit():\n    pass\n",
             "shop/a.py": "def total():\n    pass\n\ndef clone():\n    pass\n",
             "shop/b.py": "def total():\n    pass\n\ndef clone():\n    pass\n",
             "shop/d.py": "def total():\n    pass\n\ndef clone():\n    pass\n",
             "shop/z.py": "def settle_refund():\n    pass\n",
             "shop/holders/helpers.py": "def set_input_divide_by_period():\n    pass\n"}
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(["init", "-qb", "main"], repo)
    git(["add", "-A"], repo)
    git(["commit", "-qm", "shop"], repo)
    profile = ("## Risk focus\n\n- Offers: `shop/offer/` — `benefits.py`; `total`, `clone`, `settle_refund`, `set_input`.\n")
    got = focus.risk_focus(repo, profile)
    assert got["named_files"] == ["shop/offer/benefits.py"] and got["files"][0] == "shop/offer/benefits.py"
    # Two names each defined in three files weigh 2/3; one name defined once weighs 1.
    assert got["files"][1:3] == ["shop/holders/helpers.py", "shop/z.py"], got["files"]
    assert got["files"][3:6] == ["shop/a.py", "shop/b.py", "shop/d.py"], got["files"]


def test_a_bare_file_name_is_read_in_the_directory_its_bullet_named(tmp_path):
    repo = tmp_path / "shop"
    files = ["shop/offer/benefits.py", "shop/offer/results.py", "shop/offer/utils.py", "shop/admin/utils.py",
             "shop/x/utils.py", "shop/partner/prices.py", "shop/partner/strategy.py", "lib/strategy.py",
             "other/strategy.py", "a/helpers.py", "b/helpers.py", "c/helpers.py"]
    for rel in files:
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("def f():\n    return 1\n", encoding="utf-8")
    git(["init", "-qb", "main"], repo)
    git(["add", "-A"], repo)
    git(["commit", "-qm", "shop"], repo)
    profile = ("## Risk focus\n\n"
               "- **Offers:** `shop/offer/` — `benefits.py` and\n  `results.py`.\n"
               "- **Prices:** `shop/partner/prices.py` and `strategy.py`.\n"
               "- **Helpers:** `utils.py` and `helpers.py`.\n")
    paths, _ = focus.terms(profile)
    assert paths[:5] == ["shop/offer", "shop/offer/benefits.py", "shop/offer/results.py", "shop/partner/prices.py",
                         "shop/partner/strategy.py"], paths
    got = focus.risk_focus(repo, profile)
    # utils.py: three in the tree, one under a named directory; helpers.py: three, none — too vague to be named.
    assert got["named_files"] == ["shop/offer/benefits.py", "shop/offer/results.py", "shop/partner/prices.py",
                                  "shop/partner/strategy.py", "shop/offer/utils.py"], got["named_files"]
