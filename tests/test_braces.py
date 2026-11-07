"""The brace-language reader: C#, TypeScript and JavaScript cut into the questions `verdict-local` asks.

A question is worth asking only if it carries the right lines with the file's own numbers. Each
test here pins one shape that, read wrong, would hand the model the wrong code or none at all:
a brace inside a string taken for structure, a React component with destructured props taken for
an object literal, a field swallowing the method below it, an `import` asked about.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import braces  # noqa: E402


def names(found):
    return [(name, start, end) for name, start, end, _source, _context in found]


# ── what this engine reads at all ────────────────────────────────────────────

@pytest.mark.parametrize("path, lang", [
    ("src/Api/OrdersController.cs", "csharp"), ("web/src/App.tsx", "typescript"),
    ("web/lib/util.mts", "typescript"), ("web/app.jsx", "javascript"), ("tools/a.cjs", "javascript"),
    ("scripts/seed.py", "python"), ("README.md", None), ("appsettings.json", None),
])
def test_the_language_comes_from_the_extension(path, lang):
    assert braces.language_of(path) == lang


@pytest.mark.parametrize("path", [
    "src/Api.Tests/OrdersTests.cs", "tests/Orders.cs", "web/src/App.test.tsx", "web/src/app.spec.ts",
    "web/src/__tests__/App.tsx", "web/e2e/login.ts",
    "web/node_modules/react/index.js", "src/Api/obj/Debug/Api.AssemblyInfo.cs", "web/dist/app.js",
    "src/Api/Migrations/20260101_Init.cs", "src/Api/Form1.Designer.cs", "web/src/types.d.ts",
    "web/public/vendor.min.js", "src/Api/wwwroot/lib/jquery/jquery.js",
])
def test_tests_generated_and_vendored_code_are_not_read(path):
    assert not braces.readable(path), path


@pytest.mark.parametrize("path", ["src/Api/OrdersController.cs", "web/src/pages/Checkout.tsx",
                                  "src/Api/wwwroot/js/site.js", "web/src/testing-utils-free.ts"])
def test_hand_written_source_is_read(path):
    assert braces.readable(path), path


# ── 1. what is not code becomes spaces ───────────────────────────────────────

CS_LITERALS = '''class A {
    string a = "{ not a block }";
    string b = @"c:\\{dir}"" also not";
    string c = $"{(ok ? "yes{" : "no}")} total {n:N2}";
    char d = '{', e = '\\'', f = '}';
    // a comment with { a brace
    /* and } another */
#region Don't { split
    string g = """
        raw { text }
        """;
#endregion
    void M() { }
}
'''


def test_csharp_strings_chars_comments_and_directives_hide_their_braces():
    masked = braces.mask(CS_LITERALS, "csharp")
    assert len(masked) == len(CS_LITERALS)
    assert masked.count("\n") == CS_LITERALS.count("\n"), "lines are kept, so numbers stay true"
    assert masked.count("{") == masked.count("}") == 2, masked
    assert "class A" in masked and "void M()" in masked


TS_LITERALS = '''export function f(x: string) {
  const a = `outer ${x ? `inner ${"}"}` : "{"} done`;
  const re = /\\{(\\w+)\\}/g;
  const ratio = total / count / 2;
  return <p>Don't {a} split</p>;
}
'''


def test_typescript_templates_regexes_and_jsx_text_keep_the_braces_honest():
    masked = braces.mask(TS_LITERALS, "typescript")
    assert len(masked) == len(TS_LITERALS)
    assert masked.count("{") == masked.count("}"), masked
    assert "total / count / 2" in masked, "a division is not a regular expression"
    assert names(braces.functions(TS_LITERALS, "typescript", 120)) == [("f", 1, 6)]


# ── 2. what each block is ────────────────────────────────────────────────────

CONTROLLER = '''using System;
using Shop.Orders;

namespace Shop.Api;

/// <summary>Orders, for one company at a time.</summary>
[ApiController]
[Route("api/orders")]
[Authorize(Policy = "Operator")]
public sealed class OrdersController(IOrders orders) : ControllerBase
{
    private static readonly TimeSpan Every = TimeSpan.FromMinutes(5);

    public string Label { get; init; } = "";

    /// <summary>One order, if the caller's company owns it.</summary>
    [HttpGet("{id}")]
    public async Task<IActionResult> Get(Guid id, CancellationToken ct)
    {
        var order = await orders.Find(id, ct);
        if (order is null)
        {
            return NotFound();
        }
        return Ok(new OrderView { Id = order.Id, Total = order.Total });
    }

    public OrdersController(IOrders orders, ILogger log) : this(orders)
    {
        log.LogInformation("created");
    }

    public static decimal Net(decimal gross, decimal rate) => gross / (1 + rate);

    public int Count
    {
        get { return orders.Count(); }
    }

    public T Pick<T>(IEnumerable<T> items) where T : class
    {
        T Local(T x) { return x; }
        foreach (var i in items) { return Local(i); }
        return null;
    }
}

public interface IOrders
{
    Task<Order?> Find(Guid id, CancellationToken ct);
}

public enum State { Open, Closed }
'''


def test_csharp_members_are_found_with_their_attributes_and_doc_comment():
    found = braces.functions(CONTROLLER, "csharp", 120)
    assert names(found) == [("Get", 16, 26), ("OrdersController", 28, 31), ("Count", 35, 38),
                            ("Pick", 40, 45)], "a property with code is a question; `{ get; init; }` is not"
    get = found[0]
    assert get[3].splitlines()[0].strip() == "/// <summary>One order, if the caller's company owns it.</summary>"
    assert "[HttpGet(" in get[3], "the attribute above a method is part of what it says it does"
    assert get[4].startswith("[ApiController] [Route(\"api/orders\")] [Authorize(Policy = \"Operator\")]"), \
        "the guard on the whole controller travels with every method of it"
    assert "class OrdersController" in get[4]


@pytest.mark.parametrize("head, kind", [
    ("if (order is null)", "control"), ("else", "control"), ("catch (Exception e) when (e.Retry)", "control"),
    ("for (var i = 0; i < n; i++)", "control"), ("switch (state)", "control"),
    ("return Ok(new OrderView", "object"), ("var v = new()", "object"), ("x switch", "object"),
    ("public sealed record Order(Guid Id)", "type"), ("public interface IOrders", "shape"),
    ("public enum State", "shape"), ("get", "accessor"),
    ("app.MapGet(\"/x\", async (HttpContext c) =>", "lambda"),
    ("public static IResult Handle<T>(T body) where T : class, new()", "function"),
    ("public Thing(int a) : base(a)", "function"), ("public decimal Total", "property"),
    ("public int this[int index]", "property"),
])
def test_csharp_heads_are_judged_by_their_shape(head, kind):
    masked = braces.mask(head, "csharp")
    assert braces.classify(masked, "csharp")[0] == kind


TSX = '''import React from "react";
import { api } from "./api";

type Props = {
  title: string;
  onSave?: () => void;
};

export default function Card({ title, onSave }: Props): React.ReactElement {
  const [open, setOpen] = React.useState(false);
  return <section className="card"><h2>{title}</h2>{open && <button onClick={() => onSave?.()}>Save</button>}</section>;
}

export const total = (items: Item[]): number => {
  return items.reduce((sum, i) => sum + i.price, 0);
};

export class Basket {
  private items: Item[] = [];

  async add(item: Item): Promise<Map<string, (x: number) => void>> {
    this.items.push(item);
    return new Map();
  }

  get size(): number {
    return this.items.length;
  }
}

export const routes = {
  home() { return "/"; },
};
'''


def test_typescript_functions_components_methods_and_arrows_are_found():
    assert names(braces.functions(TSX, "typescript", 120)) == [
        ("Card", 9, 12), ("total", 14, 16), ("add", 21, 24), ("size", 26, 28), ("home", 32, 32)]


# ── 3. the questions a change raises ─────────────────────────────────────────

def test_a_changed_line_asks_about_the_function_it_sits_in_once():
    found = braces.around(CONTROLLER, "csharp", {20, 21, 23}, 120)
    assert names(found) == [("Get", 16, 26)]


def test_a_changed_field_is_its_own_statement_and_swallows_no_method():
    found = braces.around(CONTROLLER, "csharp", {12, 20}, 120)
    assert names(found) == [("Every", 12, 12), ("Get", 16, 26)]


def test_an_expression_bodied_member_is_read_as_its_statement():
    assert names(braces.around(CONTROLLER, "csharp", {33}, 120)) == [("Net", 33, 33)]


def test_imports_type_heads_auto_properties_and_shapes_ask_nothing():
    asked = braces.around(CONTROLLER, "csharp", {1, 2, 4, 7, 8, 10, 14, 19, 50, 53}, 120)
    assert asked == [], names(asked)
    assert braces.around(TSX, "typescript", {1, 2, 4, 5, 6}, 120) == []


def test_a_function_too_long_for_one_question_is_read_around_the_change():
    body = "\n".join(f"        Step{i}();" for i in range(60))
    text = ("public static class Endpoints\n{\n    public static void Map(IApp app)\n    {\n"
            "        app.MapPost(\"/orders\", async (Order o) =>\n        {\n            await Save(o);\n"
            "        });\n" + body + "\n    }\n}\n")
    found = braces.around(text, "csharp", {7}, 30)
    assert names(found) == [("MapPost", 5, 8)], "the lambda fits where the method does not"
    found = braces.around(text, "csharp", {40}, 30)
    (name, start, end), = names(found)
    assert name == "Map" and start <= 40 <= end and end - start <= 30, \
        "no smaller function holds the line: a window of the method around it"


def test_a_jsx_component_is_one_question_however_many_lines_change():
    assert names(braces.around(TSX, "typescript", {10, 11}, 120)) == [("Card", 9, 12)]


def test_line_numbers_are_the_files_own():
    (_name, start, end, source, _context), = braces.around(CONTROLLER, "csharp", {33}, 120)
    assert CONTROLLER.splitlines()[start - 1] == source.splitlines()[0]
    assert end == start


@pytest.mark.parametrize("head, kind", [
    ("module.exports =", "object"), ("declare module \"x\"", "type"), ("export class Basket", "type"),
    ("export interface Props", "shape"), ("export type Row =", "shape"), ("export const total = (items) =>", "lambda"),
    ("async load(): Promise<Map<string, (x: number) => void>>", "function"), ("get size(): number", "function"),
])
def test_typescript_heads_are_judged_by_their_shape(head, kind):
    assert braces.classify(braces.mask(head, "typescript"), "typescript")[0] == kind


FIELDS = """public sealed class Repeater
{
    private readonly IOrders _orders;
    private readonly ILogger _log;
    public const string Actor = "Repeater";
    private readonly object _gate = new();

    public static int Worse(int a, int b) => Math.Max(a, b);
    public static int Rank(State s) => s == State.Open ? 1 : 0;

    public static string Stamp(DateTime t) => t.ToString("O");
}
"""


def test_a_declaration_with_nothing_to_run_asks_nothing():
    """Measured: asked about `private readonly X _y;` alone, a 120B reader invented a missing
    `await` on a line that only declares a field."""
    assert braces.around(FIELDS, "csharp", {3, 4, 5, 6}, 120) == []


def test_neighbouring_one_line_members_are_one_question():
    assert names(braces.around(FIELDS, "csharp", {8, 9, 11}, 120)) == [("lines 8-11", 8, 11)]
    assert names(braces.around(FIELDS, "csharp", {8}, 120)) == [("Worse", 8, 8)]


def test_a_pipeline_of_top_level_calls_is_read_in_order_as_one_question():
    program = ("var builder = WebApplication.CreateBuilder(args);\nvar app = builder.Build();\n"
               "app.UseAuthorization();\napp.UseAuthentication();\napp.MapControllers();\napp.Run();\n")
    assert names(braces.around(program, "csharp", {3, 4, 5}, 120)) == [("lines 3-5", 3, 5)]
