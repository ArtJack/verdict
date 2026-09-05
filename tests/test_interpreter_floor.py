"""The interpreter the plugin is actually invoked with is not the one CI runs.

`hooks/hooks.json` spells the command `python3`, and so does the agent contract.
On a stock Mac that resolves to /usr/bin/python3, which is 3.9 — while
`requires-python = ">=3.10"` binds pip, and a plugin is not installed by pip.
Measured on this project: `str | None` in a signature is evaluated when the
function is defined, so the Bash guard raised TypeError and exited 1 while
`enforce_write_scope.py` beside it kept denying with exit 2. A strict session
looked armed with half its controls missing (VERDICT-F-55).

These tests cannot run a 3.9 interpreter — CI has 3.10 and 3.13 — so they check
the property instead of the platform: no module the plugin invokes directly may
use syntax that a 3.9 import would evaluate and reject.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# Everything reachable from hooks.json or from the contract's own commands,
# plus the modules they import. Discovered, not listed: a new file must not be
# able to join the invoked set without meeting the floor.
MODULES = sorted([*(ROOT / "hooks").glob("*.py"),
                  *(ROOT / "src" / "verdict_mcp").glob("*.py"),
                  # `python3 eval/run_eval.py` is a README command and
                  # `eval/fixture_freshness.py` a declared gate, and three of
                  # these died on 3.9 while this set looked elsewhere (VERDICT-F-63)
                  *(ROOT / "eval").glob("*.py")])
FUTURE = "from __future__ import annotations"


def _future_annotations(tree) -> bool:
    """A real `from __future__ import annotations`, where the compiler accepts
    one: before any statement other than the docstring and other future
    imports. The first version asked whether the string appeared anywhere in
    the file, so a commented-out copy kept the suite green while the import it
    stood for was gone and F-55 was back on 3.9 (VERDICT-F-64) — the shape
    `test_the_floor_is_written_down` had already been fixed for, one function
    down."""
    for i, node in enumerate(tree.body):
        if (i == 0 and isinstance(node, ast.Expr)
                and isinstance(getattr(node, "value", None), ast.Constant)
                and isinstance(node.value.value, str)):
            continue                                   # the module docstring
        if isinstance(node, ast.ImportFrom) and node.module == "__future__":
            if any(a.name == "annotations" for a in node.names):
                return True
            continue                                   # another future import
        return False                                   # anything else closes the window
    return False


def _annotations(tree):
    """Every annotation node that a 3.9 import would evaluate."""
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            for a in [*args.args, *args.kwonlyargs, *getattr(args, "posonlyargs", []),
                      args.vararg, args.kwarg]:
                if a is not None and a.annotation is not None:
                    out.append(a.annotation)
            if node.returns is not None:
                out.append(node.returns)
        elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
            out.append(node.annotation)
    return out


def _has_union(node):
    return any(isinstance(n, ast.BinOp) and isinstance(n.op, ast.BitOr)
               for n in ast.walk(node))


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_new_style_unions_are_lazy(path):
    """`X | Y` in a signature is fine — evaluated at import time it is not."""
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    offenders = [ast.unparse(a) for a in _annotations(tree) if _has_union(a)]
    if offenders and not _future_annotations(tree):
        pytest.fail(f"{path.name} evaluates {offenders[0]!r} at import and lacks "
                    f"`{FUTURE}`; on a 3.9 `python3` that is a TypeError, not a "
                    f"type error")


@pytest.mark.parametrize("path", MODULES, ids=lambda p: p.name)
def test_no_syntax_the_floor_cannot_parse(path):
    """The future import rescues annotations and nothing else.

    A `match` statement or a `X | Y` used as a real expression — inside
    `isinstance`, as a default, in a comprehension — fails on 3.9 whatever the
    imports say. Compiling under the running interpreter would prove nothing,
    so the shapes are named.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    annotated = {id(n) for a in _annotations(tree) for n in ast.walk(a)}
    for node in ast.walk(tree):
        assert not isinstance(node, getattr(ast, "Match", ())), \
            f"{path.name} uses a match statement; the floor is 3.9"
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr)
                and id(node) not in annotated):
            call = ast.unparse(node)
            assert not any(t in call for t in ("None", "str", "int", "dict", "list",
                                               "Path", "float", "bool", "bytes")), \
                f"{path.name} builds a type union outside an annotation: {call!r}"


def test_the_test_can_fail():
    """The instrument, controlled: the detector must see the shape it hunts."""
    tree = ast.parse("def f(x: str | None) -> int | None: ...")
    assert [a for a in _annotations(tree) if _has_union(a)], \
        "the union detector matches nothing — it would pass every file"
    clean = ast.parse("def f(x: str) -> int: ...")
    assert not [a for a in _annotations(clean) if _has_union(a)]


def test_the_future_import_detector_reads_the_statement_not_the_text():
    """VERDICT-F-64, controlled: the detector must be blind to a comment, and
    to an import placed where every interpreter would refuse it."""
    present = ast.parse('"""doc"""\nfrom __future__ import annotations\nimport os\n')
    assert _future_annotations(present)
    two = ast.parse('from __future__ import division\nfrom __future__ import annotations\n')
    assert _future_annotations(two), "a second future import is still at the top"
    commented = ast.parse('"""doc"""\n# from __future__ import annotations\nimport os\n')
    assert not _future_annotations(commented), "a comment is not an import"
    late = ast.parse('import os\nfrom __future__ import annotations\n')
    assert not _future_annotations(late), "a late future import is a SyntaxError everywhere"
    other = ast.parse('from __future__ import division\n')
    assert not _future_annotations(other)


def test_the_floor_is_written_down():
    """A stranger installing this needs the number, not a traceback.

    The first version of this test asked whether "3.9" appeared anywhere in the
    README — and it does, inside a parenthetical, so gutting the actual claim
    left the test green. Asserting on the claim itself is the difference
    between checking the page and checking the sentence.
    """
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "**Python 3.9 or newer**" in readme, (
        "the README does not state the interpreter floor as a claim a reader "
        "can act on")
