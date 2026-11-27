"""`verdict-local` on a website in any language: what it asks, how it words it, and what it owes.

The C#, TypeScript and JavaScript questions are unchanged. A function in any other language gets the
same question with its own language's name and fence, and the head of the class around it. An
excerpt, from a language read without function boundaries, is called an excerpt. A template gets
the questions a template raises: who sees what, and what is printed unescaped. Nothing outside
Python is executed, so a range that read such code is held below `pass`, and the reason a reading
stays unproven is written beside it.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import small  # noqa: E402

from test_local_delta import ScriptedModel, delta, git, project  # noqa: E402

MISMATCH = {"verdict": "mismatch", "line": 6,
            "mechanism": "refunds the whole order where the comment promises the remainder"}
REAL = {"is_real": True, "severity": "Major", "title": "Refund pays back more than was left",
        "impact": "a second partial refund overpays the customer"}

GO = '''package billing

// Refund pays back what is left of the order, never more.
func (s *Service) Refund(o *Order, amount int64) error {
	if amount > o.Total {
		return s.gateway.Refund(o.ID, o.Total)
	}
	return s.gateway.Refund(o.ID, amount)
}
'''

RUBY = '''class OrdersController < ApplicationController
  before_action :authenticate_user!, except: [:show]

  def show
    @order = Order.find(params[:id])
  end
end
'''

BLADE = '''<h1>{{ $order->id }}</h1>
@if ($user->isAdmin())
  {!! $order->notes !!}
@endif
'''


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_go_function_is_asked_about_in_go(tmp_path):
    write(tmp_path, "billing/refund.go", GO)
    (chunk,) = small.chunks_in_range(tmp_path, "billing/refund.go", {6})
    assert (chunk.name, chunk.start, chunk.end, chunk.lang, chunk.unit) == ("Refund", 3, 9, "go", "function")
    model = ScriptedModel(replies=[MISMATCH, REAL])
    claim = small.examine(model, chunk)
    first, second = model.prompts
    assert "one Go function" in first and "```go\n   3| // Refund pays back" in first
    assert "this Go function" in second
    assert claim["line"] == 6 and claim["severity"] == "Major"


def test_a_rails_action_carries_the_guard_its_class_declares(tmp_path):
    write(tmp_path, "app/controllers/orders_controller.rb", RUBY)
    (chunk,) = small.chunks_in_range(tmp_path, "app/controllers/orders_controller.rb", {5})
    question = small.contract_question(chunk)
    assert "one Ruby function" in question and "```ruby" in question
    assert ("It is declared inside: class OrdersController < ApplicationController; "
            "before_action :authenticate_user!, except: [:show]") in question


def test_a_template_is_asked_what_a_template_gets_wrong(tmp_path):
    write(tmp_path, "resources/views/orders/show.blade.php", BLADE)
    (chunk,) = small.chunks_in_range(tmp_path, "resources/views/orders/show.blade.php", {3})
    assert chunk.unit == "template"
    question = small.contract_question(chunk)
    assert "reading an excerpt of a Blade template from a\nwebsite" in question
    assert "printed without escaping" in question and "`{!! !!}`" in question
    assert "these lines of Blade template" in small.classify_question(chunk, "prints notes raw")


def test_a_language_with_no_reader_of_its_own_is_asked_about_as_an_excerpt(tmp_path):
    write(tmp_path, "scripts/deploy.sh", "#!/bin/sh\nset -e\nrm -rf \"$DIR\"/*\ncp -r dist/ \"$DIR\"\n")
    (chunk,) = small.chunks_in_range(tmp_path, "scripts/deploy.sh", {3})
    assert (chunk.lang, chunk.unit) == ("shell", "excerpt")
    question = small.contract_question(chunk)
    assert "reading an excerpt of shell from a larger\ncodebase: the lines around a change" in question
    assert "```sh" in question


def test_kotlin_swift_rust_and_dart_say_what_their_types_already_rule_out(tmp_path):
    write(tmp_path, "app/Cart.kt", "class Cart {\n    fun total(): Long {\n        return 1\n    }\n}\n")
    (chunk,) = small.chunks_in_range(tmp_path, "app/Cart.kt", {3})
    assert "a type without `?` cannot hold null" in small.contract_question(chunk)
    write(tmp_path, "src/lib.rs", "fn total() -> i64 {\n    1\n}\n")
    (chunk,) = small.chunks_in_range(tmp_path, "src/lib.rs", {2})
    assert "Rust has no null" in small.contract_question(chunk)


def test_a_website_with_no_range_and_no_map_is_read_by_risk(tmp_path):
    repo = tmp_path / "site"
    repo.mkdir()
    git(repo, "init", "-qb", "main")
    write(repo, "app/page.tsx", "export default function Page() {\n  return null\n}\n" * 40)
    write(repo, "app/api/checkout/route.ts", "export async function POST() {\n  return 1\n}\n")
    write(repo, "app/page.test.tsx", "it('renders', () => {})\n")
    write(repo, "styles/site.css", "body { color: red; }\n")
    write(repo, "db/schema.sql", "create table orders (id int);\n")
    write(repo, "node_modules/x/index.js", "module.exports = {}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "site")
    order = small.candidates({}, repo)
    assert order == ["app/api/checkout/route.ts", "app/page.tsx", "db/schema.sql"], \
        "money first, then the rest of the code by size, then the excerpts; no tests, styles or vendor"


def test_a_python_project_is_read_exactly_as_before(tmp_path):
    write(tmp_path, "b.py", "def f():\n    return 1\n")
    write(tmp_path, "a.py", "def g():\n    return 2\n")
    write(tmp_path, "test_a.py", "def test_g():\n    pass\n")
    assert small.candidates({}, tmp_path) == ["a.py", "b.py"]


def test_a_go_range_becomes_a_lead_held_below_pass(tmp_path):
    repo, qa = project(tmp_path)
    write(repo, "billing/refund.go", GO)
    write(repo, "web/site.css", "body { margin: 0; }\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "refunds")
    model = ScriptedModel(replies=[MISMATCH, REAL])
    assert delta(repo, qa, model, prove=True) == 0
    assert all("```go" in p for p in model.prompts)
    leads = json.loads((qa / small.LEADS_FILE).read_text(encoding="utf-8"))["leads"]
    assert [(x["path"], x["function"]) for x in leads] == [("billing/refund.go", "Refund")]
    assert leads[0]["why"] == small.NO_PROBE.format(language="Go")
    state = json.loads((qa / "state.json").read_text(encoding="utf-8"))
    assert state["verdict"] in ("pass with risks", "fail")
    assert small.READ_NOT_RUN in state["not_tested"]
    assert any("1 stylesheet(s)" in line for line in state["not_tested"]), \
        "what the range changed that no question read is named by kind"


def test_a_focused_jest_test_is_filed_by_a_regular_expression(tmp_path):
    repo, qa = project(tmp_path)
    write(repo, "web/checkout.test.ts", 'it.only("charges the card", () => {})\n'
                                        'it("refunds", () => {})\n')
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "focus")
    assert delta(repo, qa, ScriptedModel(), prove=False) == 0
    titles = [json.loads(p.read_text(encoding="utf-8"))["title"]
              for p in (qa / "findings").glob("*.json")]
    assert any(t.startswith("A focused test switches off the rest of its suite: charges the card")
               for t in titles), titles


def test_the_engine_starts_as_a_bare_script(tmp_path):
    """The plugin runs `python3 src/verdict_mcp/small.py` with no package installed: every new
    module must import beside it."""
    out = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
                          "import small, readers, languages, ends, regions, testmarks; print('ok')",
                          str(REPO / "src" / "verdict_mcp")], capture_output=True, text=True)
    assert out.stdout.strip() == "ok", out.stderr


def test_a_changed_site_reads_money_and_sign_in_before_its_copy(tmp_path):
    for rel in ("src/lib/insights-data.ts", "src/app/api/stripe/webhook/route.ts",
                "src/components/Hero.tsx", "src/app/pay/actions.ts"):
        write(tmp_path, rel, "export const x = 1\n")
    sizes = {"src/lib/insights-data.ts": 900, "src/app/api/stripe/webhook/route.ts": 12,
             "src/components/Hero.tsx": 80, "src/app/pay/actions.ts": 30}
    assert small.delta_candidates({}, tmp_path, sorted(sizes), sizes) == [
        "src/app/pay/actions.ts", "src/app/api/stripe/webhook/route.ts", "src/components/Hero.tsx",
        "src/lib/insights-data.ts"], "the 900 lines of copy are read last, not first"
