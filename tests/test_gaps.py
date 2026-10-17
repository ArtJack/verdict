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


def _repo(tmp_path, tests=TESTS, pricing=PRICING):
    repo = tmp_path / "shop"
    (repo / "shop").mkdir(parents=True)
    (repo / "tests").mkdir()
    git(["init", "-qb", "main"], repo)
    (repo / "shop" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "shop" / "pricing.py").write_text(pricing, encoding="utf-8")
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


def test_a_call_made_for_its_effect_an_attribute_set_and_a_raise_become_pass():
    assert [m["after"] for m in gaps.mutants_of("        self.save(update_fields=['status'])")] == ["        pass"]
    assert [m["after"] for m in gaps.mutants_of("    order.paid_total = amount")] == ["    pass"]
    assert [m["after"] for m in gaps.mutants_of("        raise ValueError('negative')")][:1] == ["        pass"]
    assert [m["after"].strip() for m in gaps.mutants_of("    return amount + fee")] == ["return None", "return amount - fee"]
    assert gaps.mutants_of("    total = amount") == [], "a local name, no effect to check"
    assert gaps._structural("    amount=amount,") == [], "an argument inside a call is not a statement"


def test_a_mutant_that_does_not_parse_is_never_run():
    assert gaps._parses(["x = (\n", "    pass\n"]) is False and gaps._parses(["x = 1\n"]) is True



SPLIT_CALL = """def charge_fee(amount):
    fee = amount * 2 // 100
    log(
        record(fee)
    )
    return amount + fee


def log(x):
    return x


def record(x):
    return x
"""


def test_the_last_argument_of_a_split_call_is_never_run_as_a_statement(tmp_path):
    """`record(fee)` on its own line looks like a call made for its effect, but it is the last
    argument of `log(`: `pass` there does not parse, and running it would count an import error
    as a measurement of the suite."""
    tests = "from shop.pricing import charge_fee\n\n\ndef test_fee_runs():\n    charge_fee(100)\n"
    repo = _repo(tmp_path, tests=tests, pricing=SPLIT_CALL)
    f = "tests/test_pricing.py::test_fee_runs|run"
    files = {"shop/pricing.py": {"functions": {"charge_fee": {"executed_lines": [2, 3, 4, 6]}},
                                 "contexts": {"2": [f], "3": [f], "4": [f], "6": [f]}}}
    r = gaps.census(repo, files, CMD, is_test=lambda p: p.startswith("tests/"), test_id=_tid, budget_s=120)
    assert r["status"] == "measured" and "skipped" not in r, r
    assert r["errors"] == 0, r
    assert sorted({s["line"] for s in r["survived"]}) == [2, 6], r["survived"]

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


def test_a_function_whose_tests_fail_on_the_clean_tree_is_skipped_and_says_why(tmp_path):
    repo = _repo(tmp_path, tests=TESTS.replace("== 180", "== 181"))
    r = gaps.census(repo, _files(), CMD, is_test=lambda p: p.startswith("tests/"), test_id=_tid, budget_s=120)
    (skip,) = [s for s in r["skipped"] if s.startswith("shop/pricing.py::apply_discount")]
    assert "its tests do not pass on the clean tree: FAILED tests/test_pricing.py::test_discount" in skip
    assert {s["function"] for s in r["survived"]} == {"charge_fee"}


def test_a_test_that_fails_beside_a_passing_one_is_dropped_not_the_function(tmp_path):
    """2026-10-17: a money function's first six tests included ones that fail in a fresh
    worktree, and the whole function was skipped. Each test alone keeps the ones that pass."""
    extra = TESTS + "\n\ndef test_broken_elsewhere():\n    from shop.pricing import charge_fee\n    charge_fee(1)\n    assert False\n"
    repo = _repo(tmp_path, tests=extra)
    files = _files()
    broken = "tests/test_pricing.py::test_broken_elsewhere|run"
    for ln in ("8", "9"):
        files["shop/pricing.py"]["contexts"][ln] = [broken] + files["shop/pricing.py"]["contexts"][ln]
    r = gaps.census(repo, files, CMD, is_test=lambda p: p.startswith("tests/"), test_id=_tid, budget_s=120)
    fee = [s for s in r["survived"] if s["function"] == "charge_fee"]
    assert fee and all(s["tests"] == ["tests/test_pricing.py::test_fee_runs"] for s in fee), r


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



def _finalize_with_survivors(repo, qa_root, judgment_over, profile=None, sweep=False):
    import json as _json
    from conftest import judgment
    from verdict_mcp.harness import facts_main, finalize_main
    if profile:
        (qa_root / "profile.md").write_text(f"---\n{profile}\n---\n\n# QA Profile\n", encoding="utf-8")
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    facts = _json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    facts["assertion_gaps"] = {"status": "measured", "survived": [
        {"path": "shop/pricing.py", "function": "charge_fee", "line": 9, "operator": "arithmetic",
         "before": "return amount + fee", "after": "return amount - fee", "tests": ["t::x"]}]}
    (qa_root / "facts.json").write_text(_json.dumps(facts), encoding="utf-8")
    (qa_root / "judgment.json").write_text(_json.dumps(judgment(**judgment_over)), encoding="utf-8")
    rc = finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")]
                       + (["--sweep"] if sweep else []))
    state = _json.loads((qa_root / "state.json").read_text(encoding="utf-8")) if (qa_root / "state.json").is_file() else None
    return rc, state


def test_a_survivor_function_nobody_accounted_for_is_said_and_refused_when_strict(repo, qa_root, capsys):
    rc, state = _finalize_with_survivors(repo, qa_root, {"findings": []})
    err = capsys.readouterr().err
    assert rc == 0 and "1 assertion-gap survivor function(s) unaccounted: shop/pricing.py::charge_fee" in err
    assert state["assertion_gaps_accounting"]["unaccounted"] == ["shop/pricing.py::charge_fee"]
    (qa_root / "state.json").unlink()
    rc, state = _finalize_with_survivors(repo, qa_root, {"findings": []}, profile="repro_rule: on")
    assert rc == 2 and "read them, or name each in not_tested as path::function" in capsys.readouterr().err
    rc, state = _finalize_with_survivors(repo, qa_root, {"findings": [],
                                                         "not_tested": ["shop/pricing.py::charge_fee — out of budget"]},
                                         profile="repro_rule: on")
    assert rc == 0 and state["assertion_gaps_accounting"]["declared_untested"] == ["shop/pricing.py::charge_fee"]



def test_a_model_free_sweep_is_not_held_to_the_agents_accounting(repo, qa_root, capsys):
    """No agent ran: a sweep carries the record forward because nothing it rested on moved, so
    under repro_rule: on an unaccounted survivor is said, never a refusal of the night."""
    rc, state = _finalize_with_survivors(repo, qa_root, {"findings": []}, profile="repro_rule: on", sweep=True)
    err = capsys.readouterr().err
    assert rc == 0, err
    assert state["run_type"] == "sweep"
    assert "1 assertion-gap survivor function(s) unaccounted: shop/pricing.py::charge_fee" in err

def test_money_logic_is_measured_before_admin_ui():
    ctx = lambda n: {str(i): ["tests/t.py::t|run"] for i in range(1, n + 1)}
    files = {
        "shop/dashboard/orders/views.py": {"functions": {"OrderListView.get_queryset": {"executed_lines": list(range(1, 20))}},
                                           "contexts": ctx(19)},
        "shop/offer/benefits.py": {"functions": {"PercentageDiscountBenefit.apply": {"executed_lines": [1, 2, 3]}},
                                   "contexts": ctx(3)},
        "shop/order/utils.py": {"functions": {"helper": {"executed_lines": [1, 2, 3, 4]}}, "contexts": ctx(4)},
    }
    order = [c["function"] for c in gaps.candidates(files, test_id=lambda c: c.split("|")[0])]
    assert order == ["PercentageDiscountBenefit.apply", "helper", "OrderListView.get_queryset"], order



def test_an_asked_run_gets_the_census_unless_the_profile_says_off(monkeypatch):
    from verdict_mcp.profile import assertion_gaps_from
    monkeypatch.delenv("VERDICT_ASSERTION_GAPS", raising=False)
    assert assertion_gaps_from({}, [])[0] is False, "unset everywhere: off"
    monkeypatch.setenv("VERDICT_ASSERTION_GAPS", "on")
    assert assertion_gaps_from({}, [])[0] is True, "verdict-run's default"
    assert assertion_gaps_from({"assertion_gaps": "off"}, [])[0] is False, "the profile's word wins"
    assert assertion_gaps_from({"assertion_gaps": "on", "assertion_gaps_budget_s": "90"}, []) == (True, 90)


def test_verdict_run_sets_the_census_default_for_the_child():
    from verdict_mcp import runner
    src = __import__("inspect").getsource(runner)
    assert 'env.setdefault(GAPS_DEFAULT_ENV, "on")' in src and runner.GAPS_DEFAULT_ENV == "VERDICT_ASSERTION_GAPS"



def test_inside_an_agent_call_the_census_takes_what_is_left_of_the_window(tmp_path, monkeypatch):
    from verdict_mcp import harness
    seen = {}
    monkeypatch.setattr(harness, "measure_coverage",
                        lambda repo, rng, cmd, findings, on_files=None: (on_files({}, None), ({}, None, None))[1])
    monkeypatch.setattr(harness, "gap_census_of",
                        lambda *a, budget_s=None, **kw: seen.setdefault("budget", budget_s) and {"status": "measured"})
    monkeypatch.setattr(harness, "FACTS_WINDOW_S", 100)
    monkeypatch.setenv("CLAUDECODE", "1")
    harness._coverage_with_gaps(tmp_path, None, "cov", [], {"test_one_cmd": "x {id}", "budget_s": 480})
    assert harness.GAPS_MIN_S <= seen["budget"] <= 100
    seen.clear()
    monkeypatch.delenv("CLAUDECODE")
    monkeypatch.delenv("CLAUDE_CODE_ENTRYPOINT", raising=False)
    harness._coverage_with_gaps(tmp_path, None, "cov", [], {"test_one_cmd": "x {id}", "budget_s": 480})
    assert seen["budget"] == 480, "a nightly has no 10-minute call to fit in"
