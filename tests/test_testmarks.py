"""Tests a suite will not run, across the frameworks websites are tested with.

A skipped test with no expiry is a test deleted without a decision; a committed `it.only` is worse,
because the suite turns green while it runs one test. A skip under a condition is a guard and is
never reported, in any framework: that is the boundary every case here pins.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small, testmarks  # noqa: E402


def found(text, lang):
    return [(m["kind"], m["line"], m["reason"]) for m in testmarks.marks(text, lang)]


JEST = '''describe("checkout", () => {
  it.skip("charges the card", async () => {});
  xit('refunds a partial order', () => {});
  test.only("applies the coupon", () => {});
  fit(`totals in cents`, () => {});
  test.skip(browserName === "webkit", "flaky on webkit");
  test.skip(true, "switched off");
  test("waits", { skip: true }, () => {});
  // it.only("a comment is no focus")
  const query = { skip: 10, take: 5 };
});
'''


def test_jest_vitest_mocha_and_playwright_markers():
    assert found(JEST, "typescript") == [
        ("skip", 2, "charges the card"), ("skip", 3, "refunds a partial order"),
        ("focus", 4, "applies the coupon"), ("focus", 5, "totals in cents"),
        ("skip", 7, "switched off"), ("skip", 8, "waits")]


RSPEC = '''RSpec.describe Order do
  xit "charges the card" do
  end
  fit "applies the coupon" do
  end
  it "refunds", skip: "until the gateway is fixed" do
  end
  it "totals" do
    skip "needs a sandbox" unless ENV["SANDBOX"]
  end
  it "ships" do
    skip "abandoned"
  end
end
'''


def test_rspec_and_minitest_markers_and_their_guards():
    assert found(RSPEC, "ruby") == [("skip", 2, "charges the card"), ("focus", 4, "applies the coupon"),
                                    ("skip", 6, "refunds"), ("skip", 12, "abandoned")]


GO = '''func TestCharge(t *testing.T) {
	if testing.Short() {
		t.Skip("slow")
	}
}

func TestRefund(t *testing.T) {
	t.Skip("broken since the gateway moved")
}
'''


def test_go_skips_count_only_when_nothing_guards_them():
    assert found(GO, "go") == [("skip", 8, "broken since the gateway moved")]


@pytest.mark.parametrize("lang, text, expected", [
    ("java", '@Disabled("flaky")\n@Test\nvoid charges() {}\n', [("skip", 1, "flaky")]),
    ("kotlin", "@Ignore\n@Test\nfun refunds() {}\n", [("skip", 1, "(no reason given)")]),
    ("csharp", '[Fact(Skip = "until 2099-01-01")]\npublic void Charges() {}\n[Test, Ignore("broken")]\n',
     [("skip", 1, "until 2099-01-01"), ("skip", 3, "broken")]),
    ("php", "public function testCharge() {\n    $this->markTestSkipped('gateway down');\n}\n"
            "public function testRefund() {\n    if (!extension_loaded('gd')) {\n"
            "        $this->markTestSkipped('needs gd');\n    }\n}\n", [("skip", 2, "gateway down")]),
    ("rust", '#[test]\n#[ignore = "slow"]\nfn charges() {}\n', [("skip", 2, "slow")]),
    ("swift", 'func testCharge() throws {\n    throw XCTSkip("no sandbox")\n}\n', [("skip", 2, "no sandbox")]),
    ("elixir", '@tag :skip\ntest "charges" do\nend\n', [("skip", 1, "(no reason given)")]),
    ("dart", "test('charges', () {}, skip: 'flaky');\n", [("skip", 1, "charges")]),
])
def test_every_framework_marks_its_skips(lang, text, expected):
    assert found(text, lang) == expected


def test_a_skip_with_a_future_expiry_is_a_decision_and_a_focus_is_always_filed(tmp_path):
    spec = tmp_path / "web" / "checkout.test.ts"
    spec.parent.mkdir(parents=True)
    spec.write_text('it.skip("until 2099-01-01: the new gateway", () => {});\n'
                    'it.skip("abandoned", () => {});\n'
                    'it.only("the one that runs", () => {});\n', encoding="utf-8")
    marks = small.skips_without_expiry(tmp_path, ["web/checkout.test.ts"])
    assert [(m["kind"], m["reason"]) for m in marks] == [("skip", "abandoned"),
                                                         ("focus", "the one that runs")]
    grouped = small.group_skips(marks)
    focus = small.focus_finding([g for g in grouped if g["kind"] == "focus"][0], "WEB-F-1")
    assert focus["title"].startswith("A focused test switches off the rest of its suite")
    assert focus["evidence"][0].startswith("web/checkout.test.ts:3")


@pytest.mark.parametrize("path, suite", [
    ("web/src/App.test.tsx", True), ("spec/models/order_spec.rb", True), ("pkg/x/x_test.go", True),
    ("eval/fixtures/shop/cart.test.ts", False), ("examples/demo.spec.js", False),
    ("web/src/App.tsx", False), ("tests/test_x.py", False),
])
def test_the_suite_is_the_projects_own_tests_not_its_fixtures(path, suite):
    assert testmarks.is_suite_file(path) is suite
