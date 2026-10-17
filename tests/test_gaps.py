"""Assertion gaps (0.91.0): code a passing suite executes without checking."""

import sys

from conftest import git
from verdict_mcp import gaps
from verdict_mcp.readfirst import read_first

PRICING = """def apply_discount(total, pct):
    if pct > 0:
        return total - total * pct // 100
    return total


def charge_fee(amount):
    fee = amount * 2 // 100
    return amount + fee
"""
TESTS = """from shop.pricing import apply_discount, charge_fee


def test_discount():
    assert apply_discount(200, 10) == 180
    assert apply_discount(200, 0) == 200


def test_fee_runs():
    charge_fee(100)
"""
CMD = f"{sys.executable} -m pytest {{id}} -q -p no:cacheprovider"


def _repo(tmp_path, tests=TESTS):
    repo = tmp_path / "shop"
    (repo / "shop").mkdir(parents=True)
    (repo / "tests").mkdir()
    git(["init", "-qb", "main"], repo)
    (repo / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "shop" / "pricing.py").write_text(PRICING, encoding="utf-8")
    (repo / "tests" / "test_pricing.py").write_text(tests, encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "shop"], repo)
    return repo


def _files():
    d = "tests/test_pricing.py::test_discount|run"
    f = "tests/test_pricing.py::test_fee_runs|run"
    return {"shop/pricing.py": {
        "functions": {"apply_discount": {"executed_lines": [2, 3, 4]},
                      "charge_fee": {"executed_lines": [8, 9]}},
        "contexts": {"2": [d], "3": [d], "4": [d], "8": [f], "9": [f]}},
        "tests/test_pricing.py": {"functions": {"test_discount": {"executed_lines": [5]}},
                                  "contexts": {"5": [d]}}}


def _tid(context):
    return context.split("|")[0]


def test_operators_never_touch_a_string_or_a_definition():
    assert [m["after"].strip() for m in gaps.mutants_of("    if amount and amount > total:")] == \
        ["if amount and amount >= total:", "if amount or amount > total:"]
    assert gaps.mutants_of("    msg = 'a < b and c'") == []
    assert gaps.mutants_of("def charge(x):") == [] and gaps.mutants_of("    # a > b") == []


def test_a_line_the_tests_run_without_checking_survives_and_a_checked_one_is_killed(tmp_path):
    repo = _repo(tmp_path)
    r = gaps.census(repo, _files(), CMD, is_test=lambda p: p.startswith("tests/"), test_id=_tid, budget_s=120)
    assert r["status"] == "measured" and "skipped" not in r, r
    by_fn = {}
    for s in r["survived"]:
        by_fn.setdefault(s["function"], []).append(s["line"])
    assert sorted(set(by_fn.get("charge_fee", []))) == [8, 9], r["survived"]
    assert all(s["tests"] == ["tests/test_pricing.py::test_fee_runs"] for s in r["survived"] if s["function"] == "charge_fee")
    assert r["killed"] >= 2, "flipping the discount's condition or its arithmetic breaks test_discount"
    assert r["functions"] == 2 and r["mutants"] == r["killed"] + len(r["survived"]) + r["errors"]
    assert (repo / "shop" / "pricing.py").read_text(encoding="utf-8") == PRICING, "the checkout is never touched"


def test_tests_that_import_the_original_checkout_are_caught_by_the_canary(tmp_path):
    repo = _repo(tmp_path)
    off_tree = f"cd {repo} && {CMD}"          # runs the original, not the mutated fresh tree
    r = gaps.census(repo, _files(), off_tree, is_test=lambda p: p.startswith("tests/"), test_id=_tid, budget_s=120)
    assert r["survived"] == [] and r["mutants"] == 0
    assert all("a canary did not fail its tests" in s for s in r["skipped"]), r["skipped"]


def test_a_function_whose_tests_fail_on_the_clean_tree_is_skipped(tmp_path):
    repo = _repo(tmp_path, tests=TESTS.replace("== 180", "== 181"))
    r = gaps.census(repo, _files(), CMD, is_test=lambda p: p.startswith("tests/"), test_id=_tid, budget_s=120)
    assert "shop/pricing.py::apply_discount (its tests do not pass on the clean tree)" in r["skipped"]
    assert {s["function"] for s in r["survived"]} == {"charge_fee"}


def test_only_risk_paths_and_tested_lines_are_candidates():
    files = _files()
    files["shop/util.py"] = {"functions": {"helper": {"executed_lines": [1]}},
                             "contexts": {"1": ["tests/test_pricing.py::test_discount|run"]}}
    names = [c["function"] for c in gaps.candidates(files, is_test=lambda p: p.startswith("tests/"), test_id=_tid)]
    assert names == ["apply_discount", "charge_fee"], "helper is on no risk path; test files are not targets"
    only_changed = gaps.candidates(files, changed={"shop/pricing.py": {9}}, test_id=_tid)
    assert [(c["function"], sorted(c["lines"])) for c in only_changed] == [("charge_fee", [9])]


def test_survivors_lead_read_first(tmp_path):
    g = {"survived": [{"path": "shop/pricing.py", "function": "charge_fee", "risk": "charge", "line": 9,
                       "operator": "arithmetic", "before": "return amount + fee", "after": "return amount - fee",
                       "tests": ["tests/test_pricing.py::test_fee_runs"]}]}
    rm = {"functions_never_entered": [{"path": "shop/other.py", "function": "refund", "missed": 5}]}
    r = read_first(tmp_path, None, rm, gaps=g)
    assert r["basis"].startswith("assertion gaps first")
    assert [i["function"] for i in r["items"]] == ["charge_fee", "refund"]
    assert "leaves 1 test(s) that run this line green" in r["items"][0]["gap"]


def test_without_coverage_the_census_says_what_it_needs(tmp_path):
    from verdict_mcp.harness import _coverage_with_gaps
    repo = _repo(tmp_path)
    _, _, _, g = _coverage_with_gaps(repo, None, None, [], {"test_one_cmd": CMD})
    assert g["status"] == "unavailable" and "coverage_suite_cmd" in g["reason"]


def test_two_survivors_in_one_function_are_one_read_first_item(tmp_path):
    one = {"path": "p/dummy.py", "function": "get_form", "risk": "form", "line": 27, "operator": "comparison",
           "before": "a == b", "after": "a != b", "tests": ["t::x"]}
    g = {"survived": [one, dict(one, operator="condition", after="not (a == b)")]}
    r = read_first(tmp_path, None, None, gaps=g)
    assert [(i["path"], i["function"]) for i in r["items"]] == [("p/dummy.py", "get_form")]
