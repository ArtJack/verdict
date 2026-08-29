"""Tests for the mutation census — the denominator of the recall number.

A recall figure is only as honest as the population it is measured over, so
what these tests protect is mostly exclusions: mutants the suite already kills
take no insight to find, and mutants that change the source without changing
the program are questions with no answer. Counting either against a tester
would inflate or deflate the number for free.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "eval"))

from mutate import apply_to, census, generate  # noqa: E402

FIXTURE = Path(__file__).resolve().parent.parent / "eval" / "fixtures" / "pricer_clean"


def test_every_mutant_changes_exactly_one_line():
    source = (FIXTURE / "pricer.py").read_text(encoding="utf-8")
    original = source.splitlines()
    for mutant in generate(source):
        changed = [i for i, (a, b) in enumerate(
            zip(original, apply_to(source, mutant).splitlines())) if a != b]
        assert changed == [mutant["line"] - 1], mutant


def test_mutants_keep_the_file_parseable():
    source = (FIXTURE / "pricer.py").read_text(encoding="utf-8")
    for mutant in generate(source):
        compile(apply_to(source, mutant), "pricer.py", "exec")


def test_indentation_survives_the_rewrite():
    source = "def f(x):\n    if x < 0:\n        return 1\n    return 2\n"
    mutant = next(m for m in generate(source) if m["line"] == 2)
    assert apply_to(source, mutant).splitlines()[1].startswith("    ")


def test_docstrings_and_imports_are_left_alone():
    source = '"""A module > with punctuation."""\nimport os\n\nx = 1 > 0\n'
    assert {m["line"] for m in generate(source)} == {4}


def test_census_separates_killed_equivalent_and_survivors():
    """The three populations are the whole point: only survivors that provably
    change behaviour belong in a recall denominator."""
    result = census(FIXTURE, "pricer.py", sys.executable)
    assert result["mutants"] == (result["killed_by_suite"] + result["equivalent"]
                                 + result["survivors"]), "every mutant lands in exactly one"
    assert result["survivors"] >= 1 and result["killed_by_suite"] >= 1
    for m in result["detail"]:
        if m["id"] in result["survivor_ids"]:
            assert not m["killed_by_suite"] and m["behaviour_changed"] is True


def test_a_mutant_that_changes_nothing_is_excluded_as_equivalent():
    result = census(FIXTURE, "pricer.py", sys.executable)
    equivalent = [m for m in result["detail"] if m["bucket"] == "equivalent"]
    assert equivalent, "the operator set should produce at least one no-op rewrite"
    assert not any(m["id"] in result["survivor_ids"] for m in equivalent)


def test_the_oracle_reports_its_own_blind_spots():
    """A mutant the suite killed but the probe called a no-op means the input
    grid has a hole — and the same hole would silently drop a real survivor out
    of the denominator. It is reported, not swallowed."""
    result = census(FIXTURE, "pricer.py", sys.executable)
    assert result["probe_blind_to"] == [], (
        "the probe's grid no longer exercises something the suite does: "
        + ", ".join(result["probe_blind_to"]))


def test_the_base_must_be_green_before_anything_is_broken(tmp_path):
    """Measuring recall against a fixture that was already failing would score
    the tester on defects it did not plant."""
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "m.py").write_text("def f():\n    return 1 > 0\n", encoding="utf-8")
    (broken / "test_m.py").write_text(
        "from m import f\n\n\ndef test_f():\n    assert not f()\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="must be green"):
        census(broken, "m.py", sys.executable)


def test_the_probe_fingerprints_the_module_not_its_source():
    """Equivalence is decided by behaviour over an input grid, so the probe has
    to actually exercise every public function."""
    out = subprocess.run([sys.executable, str(FIXTURE / "probe.py")],
                         cwd=FIXTURE, capture_output=True, text=True, check=True)
    source = (FIXTURE / "pricer.py").read_text(encoding="utf-8")
    for name in ("is_listable", "round_cents", "net_proceeds", "bulk_unit_price",
                 "shipping_cost"):
        assert f"def {name}" in source and f'"{name}"' in out.stdout
