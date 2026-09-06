"""`eval/sweep.py` enumerates mutants from the code, not from a list.

The denominator is what the tool is for (VERDICT-F-65): every mutant inside a
named function, none outside it, and a name nobody can find is an error rather
than an empty sweep that reads as "nothing to kill".
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

import sweep  # noqa: E402

SOURCE = '''\
import re

TABLE = (
    ("a", 1),
    ("b", 2),
)
TABLE = tuple(x for x in TABLE)


def inside(x):
    if x > 10:
        return x - 1
    return x


def outside(y):
    if y >= 0:
        return y + 1
    return y
'''


def test_a_name_may_own_several_ranges_and_all_are_in_scope():
    ranges = sweep.line_ranges(SOURCE, ["TABLE"])
    assert ranges == [(3, 6), (7, 7)], ranges


def test_only_lines_inside_the_named_functions_are_mutated(tmp_path):
    (tmp_path / "mod.py").write_text(SOURCE, encoding="utf-8")
    mutants = sweep.enumerate_scope(tmp_path, {"mod.py": ["inside"]})
    lines = {m["line"] for m in mutants}
    assert lines and lines <= set(range(10, 14)), lines
    assert all(m["path"] == "mod.py" for m in mutants)
    assert any("if False:" in m["after"] for m in mutants), "the guard is asked about"
    assert not any("y >= 0" in m["before"] for m in mutants), "`outside` was swept"


def test_a_change_inside_a_trailing_comment_is_not_a_mutant():
    """The first sweep spent its first two suite runs on `0` -> `1` inside
    `# Failed: 0, Passed: 5` beside the dotnet dialect. A comment does not
    run; a `#` inside a string is not a comment."""
    assert sweep.comment_only('x = 10  # Total: 0', 'x = 10  # Total: 1')
    assert not sweep.comment_only('x = 10  # Total: 0', 'x = 11  # Total: 0')
    assert not sweep.comment_only('s = "a # 0"', 's = "a # 1"'), "a # inside a string is code"
    assert not sweep.comment_only("if x > 0:", "if x >= 0:")


def test_a_docstring_is_prose_not_a_mutation_site():
    src = 'def f(x):\n    """x > 0 means *up*."""\n    return x > 0\n'
    assert sweep.docstring_lines(src) == {2}


def test_a_name_nobody_can_find_is_an_error_not_an_empty_sweep():
    with pytest.raises(SystemExit, match="not swept"):
        sweep.line_ranges(SOURCE, ["inside", "nowhere"])


def test_the_default_scope_resolves_in_this_repository():
    """The names the F-65 closure was owed on must exist as top-level defs;
    a rename that orphaned one would otherwise sweep silently less."""
    mutants = sweep.enumerate_scope(sweep.ROOT, sweep.DEFAULT_SCOPE)
    assert len(mutants) > 100, len(mutants)
    assert {m["path"] for m in mutants} == set(sweep.DEFAULT_SCOPE)
