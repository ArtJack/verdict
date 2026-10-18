"""`read_first` (0.91.0): the changed code no test executes, money and auth paths first."""

import json

from conftest import git
from verdict_mcp.harness import facts_main
from verdict_mcp.readfirst import enclosing, read_first, risk_of

MODULE = """import os


class Cart:
    def total(self, items):
        s = 0
        for i in items:
            s += i
        return s


def helper(x):
    return x + 1
"""


def test_risk_is_a_whole_word_or_a_long_stem_never_a_substring():
    assert risk_of("billing/payments.py") == "payment"
    assert risk_of("src/shop/x.py", "apply_refund") == "refund"
    assert risk_of("lib/rates.py") == "rate" and risk_of("lib/generate.py") == ""
    assert risk_of("ui/border.py") == "" and risk_of("ui/order_form.py") == "order"
    assert risk_of("core/thing.py", "TaxScale") == "tax"
    assert risk_of("src/shop/x.py", "", globs=["src/shop/*"]) == "risk_paths: src/shop/*"
    assert risk_of("billing/payments.py", "", globs=["src/shop/*"]) == "", "globs replace the stems"


def test_each_line_goes_to_the_innermost_function(tmp_path):
    (tmp_path / "m.py").write_text(MODULE, encoding="utf-8")
    assert enclosing(tmp_path, "m.py", {1, 7, 13}) == {"(module)": [1], "Cart.total": [7], "helper": [13]}
    (tmp_path / "bad.py").write_text("def (:\n", encoding="utf-8")
    assert enclosing(tmp_path, "bad.py", {1}) == {"(module)": [1]}


def test_measured_coverage_ranks_risk_first_then_unexercised_lines(tmp_path):
    (tmp_path / "cart.py").write_text(MODULE, encoding="utf-8")
    (tmp_path / "util.py").write_text(MODULE.replace("Cart", "Box").replace("total", "size"), encoding="utf-8")
    cov = {"status": "measured", "per_file": {
        "util.py": {"unexercised_ranges": [[6, 9], [13, 13]]},       # 4 + 1 lines, no risk
        "cart.py": {"unexercised_ranges": [[7, 7]]},                  # 1 line, Cart.total — risk
        "tests/test_cart.py": {"unexercised_ranges": [[1, 3]]},
    }}
    r = read_first(tmp_path, cov, None, is_test=lambda p: p.startswith("tests/"))
    assert r["basis"].startswith("changed lines no test executes")
    assert [(i["path"], i["function"]) for i in r["items"]] == [
        ("cart.py", "Cart.total"), ("util.py", "Box.size"), ("util.py", "helper")]
    assert r["items"][0]["risk"] == "cart" and r["items"][0]["unexercised_changed_lines"] == 1
    assert r["items"][1]["unexercised_changed_lines"] == 4 and r["items"][1]["lines"] == "6-9"
    assert r["of"] == 3 and "name stems" in r["risk_from"]


def test_without_coverage_changed_lines_and_without_a_range_the_reading_map(tmp_path):
    (tmp_path / "cart.py").write_text(MODULE, encoding="utf-8")
    r = read_first(tmp_path, {"status": "not measured"}, None, changed={"cart.py": {7, 8, 13}})
    assert r["basis"].startswith("changed lines (coverage not measured")
    assert [(i["function"], i["changed_lines"]) for i in r["items"]] == [("Cart.total", 2), ("helper", 1)]
    rm = {"lowest": [{"path": "a/util.py", "percent": 10}, {"path": "a/payments.py", "percent": 60}]}
    r = read_first(tmp_path, None, rm)
    assert [i["path"] for i in r["items"]] == ["a/payments.py", "a/util.py"]
    assert read_first(tmp_path, None, None) is None


def test_facts_carries_read_first_for_a_range(repo, qa_root):
    (repo / "pricing.py").write_text("def charge(x):\n    return x\n", encoding="utf-8")
    git(["add", "-A"], repo)
    git(["commit", "-qm", "pricing"], repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    first = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    (repo / "pricing.py").write_text("def charge(x):\n    return x * 100 // 100\n", encoding="utf-8")
    git(["commit", "-qam", "change charge"], repo)
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root),
                       "--range", f"{first['last_run']['git_sha']}..HEAD"]) == 0
    facts = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    rf = facts["read_first"]
    assert rf["items"][0]["path"] == "pricing.py" and rf["items"][0]["function"] == "charge"
    assert rf["items"][0]["risk"] == "pricing", "the path names it before the function does"


def test_a_baseline_ranks_functions_no_test_entered_risk_first(tmp_path):
    rm = {"lowest": [{"path": "a/util.py", "percent": 10}],
          "functions_never_entered": [{"path": "a/util.py", "function": "big_helper", "missed": 40},
                                      {"path": "a/shop.py", "function": "apply_discount", "missed": 6}]}
    r = read_first(tmp_path, None, rm)
    assert r["basis"].startswith("no range: functions no test ever entered")
    assert [i["function"] for i in r["items"]] == ["apply_discount", "big_helper"]
    assert r["items"][0]["risk"] == "discount"


def test_the_reading_map_lists_functions_no_test_entered():
    from verdict_mcp.harness import reading_map_from
    files = {"pkg/shop.py": {"summary": {"num_statements": 20, "percent_covered": 50, "missing_lines": 10},
                             "functions": {"": {"executed_lines": [1], "missing_lines": []},
                                           "pay": {"executed_lines": [], "missing_lines": [5, 6, 7]},
                                           "list_items": {"executed_lines": [10], "missing_lines": [11]}}},
             "tests/test_shop.py": {"summary": {"num_statements": 5, "percent_covered": 100, "missing_lines": 0},
                                    "functions": {"helper": {"executed_lines": [], "missing_lines": [3]}}}}
    rm = reading_map_from(files, [])
    assert rm["functions_never_entered"] == [{"path": "pkg/shop.py", "function": "pay", "missed": 3}]


def test_the_state_says_which_ranked_functions_the_run_accounted_for():
    from verdict_mcp.harness import read_first_accounting
    items = [{"path": "pay/refund.py", "function": "Refund.apply"},
             {"path": "pay/cart.py", "function": "total"},
             {"path": "pay/tax.py", "function": "vat"},
             {"path": "pay/misc.py", "function": "(module)"}]
    findings = [{"id": "W-F-1", "title": "`apply` refunds the whole total",
                 "evidence": ["pay/refund.py:40 — the zero amount"], "anchors": [{"path": "pay/refund.py", "line": 40}]},
                {"id": "W-F-2", "title": "unrelated", "evidence": ["pay/cart.py:3 — imports"]}]   # cites the file, not `total`
    acc = read_first_accounting(items, findings, ["pay/tax.py::vat — not reached in the budget"])
    assert acc == {"cited": ["pay/refund.py::Refund.apply"], "declared_untested": ["pay/tax.py::vat"],
                   "unaccounted": ["pay/cart.py::total", "pay/misc.py::(module)"]}


def test_finalize_carries_the_accounting_into_the_state_and_the_report(repo, qa_root, capsys):
    from conftest import judgment
    from verdict_mcp.harness import finalize_main
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa_root)]) == 0
    facts = json.loads((qa_root / "facts.json").read_text(encoding="utf-8"))
    facts["read_first"] = {"basis": "no range: functions no test ever entered, risk paths first",
                           "items": [{"path": "a.py", "function": "charge", "risk": "charge"},
                                     {"path": "b.py", "function": "pay", "risk": "pay"}], "of": 2}
    (qa_root / "facts.json").write_text(json.dumps(facts), encoding="utf-8")
    j = judgment(not_tested=["b.py::pay — out of budget"])
    (qa_root / "judgment.json").write_text(json.dumps(j), encoding="utf-8")
    assert finalize_main(["--qa-root", str(qa_root), "--judgment", str(qa_root / "judgment.json")]) == 0
    err = capsys.readouterr().err
    assert "1 of 2 read_first functions are neither cited by a finding nor named in not_tested: a.py::charge" in err
    state = json.loads((qa_root / "state.json").read_text(encoding="utf-8"))
    assert state["read_first"]["unaccounted"] == ["a.py::charge"]
    assert state["read_first"]["declared_untested"] == ["b.py::pay"]
    report = (qa_root / state["last_run"]["report"]).read_text(encoding="utf-8")
    assert "## Read first" in report and "| `a.py::charge` | charge | **no**" in report


def test_files_the_risk_focus_points_at_are_risk_paths_when_the_profile_sets_none(tmp_path):
    assert risk_of("src/core/inventory.py", "", focus={"src/core/inventory.py"}) == "risk focus"
    assert risk_of("src/core/inventory.py", "", globs=["lib/*"], focus={"src/core/inventory.py"}) == "", \
        "risk_paths, when set, decide alone"
    rm = {"lowest": [{"path": "src/_babel.py", "percent": 0}, {"path": "src/core/inventory.py", "percent": 0},
                     {"path": "src/beans/abc.py", "percent": 0}]}
    r = read_first(tmp_path, None, rm, focus=["src/core/inventory.py"])
    assert [i["path"] for i in r["items"]][0] == "src/core/inventory.py", r["items"]
    assert r["risk_from"] == "the profile's risk focus, then name stems"
    assert read_first(tmp_path, None, rm)["items"][0]["path"] == "src/_babel.py"
