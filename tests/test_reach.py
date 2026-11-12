"""What a function reaches for one step outside itself, carried below the question about it.

A model shown one function judges what it cannot see as missing: the callee that checks the token,
the validation call that returns first, the file's own `Response` type. These tests pin what is
carried (the callee, the state, the shape, the imported definition) and what is not: the function
itself, a lambda's call, a package, and anything outside the repository.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import reach, small  # noqa: E402

ROUTE = '''import { NextResponse } from "next/server";
import { validateContactInput } from "@/lib/contact-validation";
import { clientKey } from "./keys";

const limiter = createLimiter(5);
const seenEvents = new Set<string>();

type Reply = {
  status: "ok" | "error";
  message: string;
};

async function verifyTurnstile(token: unknown): Promise<boolean> {
  if (typeof token !== "string" || token.length === 0) return false;
  return true;
}

export async function POST(request: Request) {
  if (limiter.isLimited(clientKey(request))) return reply({ status: "error", message: "slow" });
  const body = await request.json();
  const ok = await verifyTurnstile(body.turnstileToken);
  seenEvents.add(String(body.id));
  useEffect(() => {
    validateContactInput(body);
  });
  return NextResponse.json({ ok });
}

function reply(r: Reply) {
  return NextResponse.json(r);
}
'''


def write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_a_file_defines_its_functions_state_and_shapes():
    defs = reach.definitions(ROUTE, "typescript")
    assert defs["verifyTurnstile"][2] == "function" and defs["POST"][2] == "function"
    assert defs["limiter"][2] == "state" and defs["seenEvents"][2] == "state"
    assert defs["Reply"][2] == "shape"
    assert "useEffect" not in defs, "a lambda passed to a call defines nothing"


def test_a_function_reaches_its_callee_its_state_and_its_imports(tmp_path):
    write(tmp_path, "src/app/api/contact/route.ts", ROUTE)
    write(tmp_path, "src/lib/contact-validation.ts",
          "export function validateContactInput(x: unknown) {\n  return typeof x === \"object\";\n}\n")
    write(tmp_path, "src/app/api/contact/keys.ts",
          "export function clientKey(r: Request): string {\n  return r.headers.get(\"x-ip\") ?? \"\";\n}\n")
    found = reach.reached(tmp_path, "src/app/api/contact/route.ts", ROUTE, "typescript", 18, 27)
    shown = {(r.name, r.path, r.kind) for r in found}
    assert ("verifyTurnstile", "src/app/api/contact/route.ts", "function") in shown
    assert ("limiter", "src/app/api/contact/route.ts", "state") in shown
    assert ("seenEvents", "src/app/api/contact/route.ts", "state") in shown
    assert ("reply", "src/app/api/contact/route.ts", "function") in shown
    assert ("clientKey", "src/app/api/contact/keys.ts", "function") in shown, "a relative import"
    assert ("validateContactInput", "src/lib/contact-validation.ts", "function") in shown, "`@/` is src/"
    assert not any(r.name in ("POST", "NextResponse") for r in found), "itself and a package: no"
    (turnstile,) = [r for r in found if r.name == "verifyTurnstile"]
    assert "typeof token !== \"string\"" in turnstile.source, "the callee's own check is shown"


def test_a_long_definition_is_shown_by_its_head_and_the_budget_holds():
    body = "\n".join(f"  step{i}();" for i in range(60))
    text = f"function big() {{\n{body}\n}}\n\nfunction caller() {{\n  big();\n}}\n"
    (item,) = reach.reached(Path("."), "x.ts", text, "typescript", 64, 66)
    assert item.name == "big" and item.end - item.start + 1 == reach.HEAD and item.hidden == 62 - reach.HEAD
    many = "\n".join(f"function f{i}() {{\n" + "\n".join("  x();" for _ in range(20)) + "\n}" for i in range(10))
    calls = "\n".join(f"  f{i}();" for i in range(10))
    text = many + f"\nfunction caller() {{\n{calls}\n}}\n"
    start = text.count("\n", 0, text.index("function caller")) + 1
    found = reach.reached(Path("."), "x.ts", text, "typescript", start, start + 11)
    assert sum(r.end - r.start + 1 for r in found) <= reach.BUDGET


def test_an_import_never_leaves_the_repository(tmp_path):
    repo = tmp_path / "repo"
    write(tmp_path, "outside.ts", "export function secret() {\n  return 1;\n}\n")
    write(repo, "src/a.ts", "import { secret } from \"../../outside\";\nfunction f() {\n  return secret();\n}\n")
    assert reach.resolve(repo, "src/a.ts", "../../outside") is None
    assert reach.reached(repo, "src/a.ts", (repo / "src/a.ts").read_text(), "typescript", 2, 4) == []


def test_a_ruby_action_reaches_the_methods_of_its_controller():
    text = ("class OrdersController < ApplicationController\n  def show\n    @order = find_order\n  end\n\n"
            "  private\n\n  def find_order\n    Order.find_by!(id: params[:id], user: current_user)\n  end\nend\n")
    (item,) = reach.reached(Path("."), "orders_controller.rb", text, "ruby", 2, 4)
    assert item.name == "find_order" and "current_user" in item.source


def test_the_question_carries_what_the_function_reaches_for(tmp_path):
    write(tmp_path, "src/app/api/contact/route.ts", ROUTE)
    (chunk,) = [c for c in small.chunks_in_range(tmp_path, "src/app/api/contact/route.ts", {20})
                if c.name == "POST"]
    question = small.contract_question(chunk)
    assert "It reaches for this code one step outside it." in question
    assert "src/app/api/contact/route.ts, `verifyTurnstile`:" in question
    assert "  14|   if (typeof token !== \"string\"" in question, "with the file's own line numbers"
    assert "It reaches for this code" in small.classify_question(chunk, "token may be undefined")
    chunk.reached = []
    assert "It reaches for" not in small.contract_question(chunk), "nothing reached, nothing added"
