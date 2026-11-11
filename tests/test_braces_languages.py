"""The brace reader past C#, TypeScript and JavaScript: Java, Kotlin, Scala, Groovy, Go, Rust, Swift,
Dart, C, C++, PHP and Solidity.

Each language brings literals that hide braces (Go's backtick strings, Rust's `r#"…"#`, Kotlin's
and Swift's templates, PHP's heredocs and the HTML around its tags) and characters that look like
literals and are not (Rust's lifetimes, C++'s digit separators). Each also has its own words for a
function and a type. A test here pins one shape that, read wrong, would hand the model the wrong lines
or none: a `'{'` taken for structure, a Swift `func` that ends in `async` taken for a control block,
a C function that returns a struct taken for the struct.
"""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp import braces  # noqa: E402


def names(found):
    return [(name, start, end) for name, start, end, _source, _context in found]


def contexts(found):
    return {name: context for name, _start, _end, _source, context in found}


# ── literals ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lang, text", [
    ("go", 'var raw = `{ not\n a block }`\nvar r = \'{\'\nvar s = "}"\n'),
    ("rust", 'let a = r#"{ "json": } "#;\nlet c = \'{\';\nlet s = "multi\n{ line";\nfn f<\'a>(x: &\'a str) {}\n'),
    ("kotlin", 'val t = """raw { ${items.map { it }} } text"""\nval c = \'}\'\nval s = "a ${b["{"]} c"\n'),
    ("swift", 'let s = "value: \\(f({ 1 }))"\nlet r = #"raw { "# \nlet m = """\n{ multi\n"""\n'),
    ("dart", "final s = 'value ${m['{']} {';\nfinal r = r'raw { text';\nfinal t = '''\n{ triple\n''';\n"),
    ("java", 'String t = """\n    { text block }\n    """;\nchar c = \'{\';\n'),
    ("cpp", '#define BLOCK { 1, \\\n  2 }\nauto r = R"x({ raw })x";\nint n = 1\'000\'000;\nchar c = \'}\';\n'),
    ("php", "<html>{ html }</html>\n<?php\n$a = 'it{s';\n# { hash comment\n$b = \"{$x->y} {\";\n"
            "$c = <<<SQL\n  { heredoc }\n  SQL;\n?>\n<p>{ after }</p>\n"),
    ("scala", 'val s = s"total ${xs.map { x => x }.sum} {"\nval plain = "${not a hole"\n'),
    ("solidity", 'string s = "{";\nstring t = \'}\';\n'),
])
def test_literals_hide_their_braces_and_keep_every_line(lang, text):
    masked = braces.mask(text, lang)
    assert len(masked) == len(text)
    assert masked.count("\n") == text.count("\n"), "lines are kept, so numbers stay true"
    assert masked.count("{") == masked.count("}"), masked


def test_a_rust_lifetime_is_not_a_character_and_hides_nothing():
    text = "fn f<'a>(x: &'a str) -> &'a str {\n    x\n}\n"
    assert braces.mask(text, "rust") == text
    assert names(braces.functions(text, "rust", 120)) == [("f", 1, 3)]


def test_php_reads_only_what_is_inside_its_tags():
    text = "<div>{{ x }}</div>\n<?php\nfunction total($xs) {\n    return array_sum($xs);\n}\n?>\n<p>{ }</p>\n"
    masked = braces.mask(text, "php")
    assert "<div>" not in masked and "<p>" not in masked
    assert names(braces.functions(text, "php", 120)) == [("total", 3, 5)]


def test_nested_parameter_lists_still_flatten():
    # `(xs []T, f func(T) U)` holds a group of its own; left unflattened, no function word matched.
    assert braces._flatten("func Map[T any](xs []T, f func(T) U) []U") == "func Map[T any]() []U"
    assert braces._flatten("function f(a = g(h(1)), b) {") == "function f() {"


# ── what each block is ───────────────────────────────────────────────────────

JAVA = '''package shop.api;

import java.util.List;

@RestController
@RequestMapping("/api/orders")
public class OrdersController {
    private final OrderService service;

    public OrdersController(OrderService service) {
        this.service = service;
    }

    /** One order, if the caller owns it. */
    @GetMapping("/{id}")
    public ResponseEntity<Order> get(@PathVariable Long id) throws NotFoundException {
        Order o = service.find(id);
        if (o == null) {
            throw new NotFoundException(id);
        }
        return ResponseEntity.ok(o);
    }

    static {
        System.out.println("loaded");
    }
}

interface Priced {
    default long cents() {
        return 0;
    }
}
'''


def test_java_methods_constructors_initializers_and_default_methods_are_found():
    found = braces.functions(JAVA, "java", 120)
    assert names(found) == [("OrdersController", 10, 12), ("get", 14, 22), ("static", 24, 26),
                            ("cents", 30, 32)]
    assert contexts(found)["get"] == ('@RestController @RequestMapping("/api/orders") '
                                      'public class OrdersController')


def test_a_changed_java_field_asks_nothing_and_a_changed_body_line_asks_about_its_method():
    assert names(braces.around(JAVA, "java", {8}, 120)) == []
    assert names(braces.around(JAVA, "java", {19, 21}, 120)) == [("get", 14, 22)]


GO = '''package main

import (
	"fmt"
	"net/http"
)

var raw = `{ not a block }`

type Server struct {
	db *DB
}

// ServeHTTP answers one request.
func (s *Server) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	if r.Method != "GET" {
		http.Error(w, "{method}", 405)
		return
	}
	handler := func(x int) {
		fmt.Println('{', x)
	}
	handler(1)
}

func Map[T, U any](xs []T, f func(T) U) []U {
	out := make([]U, 0, len(xs))
	for _, x := range xs {
		out = append(out, f(x))
	}
	return out
}
'''


def test_go_methods_generics_and_func_literals():
    assert names(braces.functions(GO, "go", 120)) == [("ServeHTTP", 14, 24), ("Map", 26, 32)]
    assert names(braces.around(GO, "go", {11}, 120)) == [], "a struct's field declares a shape"
    assert names(braces.around(GO, "go", {21}, 120)) == [("ServeHTTP", 14, 24)]


RUST = '''use std::fmt;

pub struct Money {
    cents: i64,
}

impl Money {
    /// Adds two amounts.
    pub fn add(&self, other: &Money) -> Money {
        let c = '{';
        Money { cents: self.cents + other.cents }
    }
}

#[cfg(test)]
mod tests {
    #[test]
    fn adds() {
        assert_eq!(1, 1);
    }
}
'''


def test_rust_reads_impl_methods_and_leaves_its_test_module():
    found = braces.functions(RUST, "rust", 120)
    assert names(found) == [("add", 8, 12)]
    assert contexts(found)["add"] == "impl Money"
    assert names(braces.around(RUST, "rust", {19}, 120)) == [], "a #[cfg(test)] module is a test"


KOTLIN = '''package shop

class Cart(private val repo: Repo) : Base() {
    private val items = mutableListOf<Item>()

    init {
        println("cart {")
    }

    fun total(): Long {
        return items.sumOf { it.price }
    }

    suspend fun checkout(user: User?) = when (user) {
        null -> throw IllegalStateException("no user")
        else -> repo.save(items)
    }

    val count: Int
        get() {
            return items.size
        }
}

fun String.slug(): String {
    return lowercase().replace(" ", "-")
}
'''


def test_kotlin_functions_initializers_accessors_and_extension_functions():
    assert names(braces.functions(KOTLIN, "kotlin", 120)) == [
        ("init", 6, 8), ("total", 10, 12), ("checkout", 14, 17), ("Cart.get", 20, 22), ("slug", 25, 27)]


def test_a_statement_without_a_semicolon_ends_at_its_line():
    assert names(braces.around(KOTLIN, "kotlin", {4}, 120)) == [("items", 4, 4)]
    assert names(braces.around(KOTLIN, "kotlin", {19}, 120)) == [], "a bare declaration asks nothing"


SWIFT = '''import SwiftUI

struct ContentView: View {
    @State private var count = 0

    var body: some View {
        Button("Tap {") { count += 1 }
    }

    func load() async throws -> Data {
        guard let url = URL(string: "x") else {
            throw URLError(.badURL)
        }
        return try await fetch(url)
    }

    init(count: Int) {
        self.count = count
    }
}
'''


def test_swift_computed_properties_async_functions_and_initializers():
    found = braces.functions(SWIFT, "swift", 120)
    assert names(found) == [("body", 6, 8), ("load", 10, 15), ("init", 17, 19)]
    assert contexts(found)["load"] == "struct ContentView: View"


DART = '''class Counter extends StatefulWidget {
  factory Counter.fromJson(Map<String, dynamic> json) {
    return Counter();
  }

  int get total {
    return 3;
  }

  Future<void> load() async {
    final s = 'value ${total} {';
  }
}
'''


def test_dart_named_constructors_getters_and_async_methods():
    assert names(braces.functions(DART, "dart", 120)) == [("fromJson", 2, 4), ("total", 6, 8),
                                                          ("load", 10, 12)]


C = '''#include <stdio.h>

struct point { int x; int y; };

struct point make_point(int x, int y) {
    struct point p = { x, y };
    return p;
}

static int sum(const int *xs, int n)
{
    int total = 0;
    for (int i = 0; i < n; i++) {
        total += xs[i];
    }
    return total;
}
'''


def test_a_c_function_returning_a_struct_is_a_function_not_the_struct():
    assert names(braces.functions(C, "c", 120)) == [("make_point", 5, 8), ("sum", 10, 17)]


CPP = '''namespace shop {
class Cart : public Base {
public:
    Cart(int n) : count(n) {
        auto f = [&](int x) -> int { return x + count; };
    }
    int total() const noexcept {
        return count;
    }
private:
    int count;
};
}
'''


def test_cpp_constructors_with_initializer_lists_and_const_methods():
    found = braces.functions(CPP, "cpp", 120)
    assert names(found) == [("Cart", 4, 6), ("total", 7, 9)]
    assert contexts(found)["total"] == "class Cart : public Base"


PHP = '''<?php
namespace App\\Http\\Controllers;

use App\\Models\\Order;

class OrderController extends Controller
{
    public function show(Request $request, $id)
    {
        $order = Order::find($id);
        if (!$order) {
            abort(404);
        }
        return view('orders.show', ['order' => $order]);
    }
}

Route::get('/orders', function () {
    return Order::all();
});
'''


def test_php_methods_and_route_closures():
    found = braces.functions(PHP, "php", 120)
    assert names(found) == [("show", 8, 15), ("get", 18, 20)]
    assert contexts(found)["show"] == "class OrderController extends Controller"
    assert names(braces.around(PHP, "php", {4}, 120)) == [], "a `use` statement asks nothing"


SOLIDITY = '''pragma solidity ^0.8.0;

contract Token is ERC20 {
    struct Order { uint id; }
    constructor() ERC20("T", "T") {
        _mint(msg.sender, 1000);
    }
    modifier onlyOwner() {
        require(msg.sender == owner, "not owner");
        _;
    }
    function transfer(address to, uint256 amt) public returns (bool) {
        unchecked {
            balances[to] += amt;
        }
        return true;
    }
}
'''


def test_solidity_constructors_modifiers_and_functions():
    assert names(braces.functions(SOLIDITY, "solidity", 120)) == [
        ("constructor", 5, 7), ("onlyOwner", 8, 11), ("transfer", 12, 17)]
    assert names(braces.around(SOLIDITY, "solidity", {1}, 120)) == [], "a pragma asks nothing"


SCALA = '''object Main extends App {
  def total(xs: List[Int]): Int = {
    xs.sum
  }
  def label(x: Int): String = x match {
    case 0 => "zero"
    case _ => "many"
  }
}
'''


def test_scala_defs_with_and_without_a_match_body():
    assert names(braces.functions(SCALA, "scala", 120)) == [("total", 2, 4), ("label", 5, 8)]


@pytest.mark.parametrize("head, lang, kind", [
    ("func load() async", "swift", "function"),
    ("if let x = y", "swift", "control"),
    ("guard let x = y else", "swift", "control"),
    ("DispatchQueue.main.async", "swift", "other"),
    ("struct point p =", "c", "object"),
    ("struct point", "c", "shape"),
    ("type Server struct", "go", "shape"),
    ("handler := func(x int)", "go", "lambda"),
    ("for _, x := range xs", "go", "control"),
    ("let f = |x: i32| -> i32", "rust", "lambda"),
    ("match x", "rust", "control"),
    ("impl<T> From<T> for Wrapper", "rust", "type"),
    ("trait Draw", "rust", "type"),
    ("val x = when (y)", "kotlin", "control"),
    ("companion object", "kotlin", "type"),
    ("list.forEach", "kotlin", "other"),
    ("$y = match($x)", "php", "control"),
    ("$f = function ($x) use ($y)", "php", "lambda"),
    ("list.forEach(x ->", "java", "lambda"),
    ("record Point(int x, int y)", "java", "type"),
    ("synchronized (lock)", "java", "control"),
    ("@Override public String toString()", "java", "function"),
    ("Future<void> load() async", "dart", "function"),
    ("on FormatException catch (e)", "dart", "control"),
])
def test_heads_are_judged_by_their_languages_words(head, lang, kind):
    assert braces.classify(head, lang)[0] == kind


def test_a_call_closed_on_its_own_line_ends_its_statement_and_an_annotation_does_not():
    kotlin = "val sizes = listOf(\n    1, 2\n)\nfun total(): Int {\n    return 3\n}\n"
    assert names(braces.functions(kotlin, "kotlin", 120)) == [("total", 4, 6)]
    ts = "@Component({\n  selector: 'x',\n})\nexport class Card {\n  render() {\n    return 1\n  }\n}\n"
    (render,) = braces.functions(ts, "typescript", 120)
    assert render[4] == "@Component({ selector: 'x', }) export class Card", "the decorator stays on the class"


def test_a_function_too_long_for_one_question_is_read_as_the_functions_inside_it():
    body = "\n".join(f"  const v{i} = {i};" for i in range(130))
    text = ("export function Form() {\n" + body + "\n  async function submit() {\n    setPending(true);\n"
            "    try {\n      await send();\n    } finally {\n      setPending(false);\n    }\n  }\n"
            "  return null;\n}\n")
    (found,) = braces.functions(text, "typescript", 120)
    assert found[0] == "submit" and "setPending(false)" in found[3], "the handler whole, its finally too"
    short = "function f() {\n  function g() {\n    return 1;\n  }\n  return g();\n}\n"
    assert names(braces.functions(short, "javascript", 120)) == [("f", 1, 6)], "a short one stays whole"


def test_a_class_behind_a_decorator_with_arguments_is_still_a_type():
    nest = ("@Controller('orders')\n@UseGuards(AuthGuard)\nexport class OrdersController {\n"
            "  @Get(':id')\n  find(@Param('id') id: string) {\n    return this.orders.find(id)\n  }\n}\n")
    (find,) = braces.functions(nest, "typescript", 120)
    assert find[0] == "find"
    assert find[4] == "@Controller('orders') @UseGuards(AuthGuard) export class OrdersController"


@pytest.mark.parametrize("head", ["void f() &" + "&&" * 40 + "!",
                                  "auto f() ->" + "\t\t->" * 40 + "{",
                                  "int g() const" + " const" * 200 + " x"])
def test_a_hostile_head_is_read_in_linear_time(head):
    # CodeQL (2026-11-11): a repeated group of overlapping trailers backtracked exponentially on
    # a long run of `&&` or `->`. The heads come from any file in any repository.
    import time
    began = time.perf_counter()
    braces.classify(head, "cpp")
    braces.classify(head, "c")
    assert time.perf_counter() - began < 1.0


def test_cpp_qualifiers_and_trailing_return_types_still_come_off():
    assert braces.classify("int total() const noexcept", "cpp") == ("function", "total")
    assert braces.classify("auto load() -> std::vector<int>", "cpp") == ("function", "load")
    assert braces.classify("Cart& operator=(Cart&& other) &", "cpp")[0] in ("function", "other")
    assert braces.classify("auto f = [&](int x) mutable -> int", "cpp") == ("lambda", "f")
