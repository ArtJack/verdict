"""Every skip pytest makes, in every spelling, is one the scan sees (`local_skips.SKIP_MARKER`).

Until 2026-11-27 the pattern required a parenthesis. So a bare `@pytest.mark.skip`, a skip
with no reason at all and the plainest abandoned test there is, was never filed. A `skipif`
with no condition was read as a guard, though pytest skips such a mark unconditionally.

The fixture's names carry the expected outcome:
- `test_skipped_*`: pytest skips it, and the scan files it.
- `test_dated_*`: pytest skips it, and the scan leaves it, because its note names an expiry.
- `test_runs_*`: pytest runs it, and the scan leaves it.

One test asks pytest itself, so the names are checked against the runner rather than
against this file's reading of it.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
from verdict_mcp.local_skips import skips_without_expiry  # noqa: E402

FIXTURE = '''import sys

import pytest


@pytest.mark.skip
def test_skipped_bare():
    pass


@pytest.mark.skip  # flaky on CI
def test_skipped_bare_with_a_note():
    pass


@pytest.mark.skip  # until 2099-01-01
def test_dated_bare_with_a_dated_note():
    pass


@pytest.mark.skipif
def test_skipped_skipif_with_no_condition():
    pass


@pytest.mark.skipif(reason="no condition given")
def test_skipped_skipif_with_only_a_reason():
    pass


@pytest.mark.skipif(sys.platform == "no-such-platform", reason="a guard")
def test_runs_guarded():
    pass


@pytest.mark.skipif(condition=False, reason="a guard by keyword")
def test_runs_guarded_by_keyword():
    pass


def test_runs_a_name_is_not_a_call():
    pytest.skip
'''


def _names(prefix):
    return set(re.findall(rf"^def ({prefix}\w+)\(", FIXTURE, re.M))


def _filed(tmp_path, text=FIXTURE):
    """The scan's findings for `text`, as {test name under the marker: reason}."""
    (tmp_path / "test_x.py").write_text(text, encoding="utf-8")
    lines = text.splitlines()
    out = {}
    for skip in skips_without_expiry(tmp_path, ["test_x.py"]):
        # The line after the marker (`line` is 1-based); a marker on the last line has none.
        below = lines[skip["line"]] if skip["line"] < len(lines) else ""
        name = re.match(r"\s*def (\w+)\(", below)
        out[name.group(1) if name else f"line {skip['line']}"] = skip["reason"]
    return out


def test_the_scan_files_every_skip_with_no_expiry_and_nothing_else(tmp_path):
    filed = _filed(tmp_path)
    assert set(filed) == _names("test_skipped_"), filed


def test_a_bare_marker_has_no_reason_but_the_comment_beside_it(tmp_path):
    filed = _filed(tmp_path)
    assert filed["test_skipped_bare"] == ""
    assert filed["test_skipped_bare_with_a_note"] == "# flaky on CI"
    assert "test_dated_bare_with_a_dated_note" not in filed, \
        "a dated note beside a bare marker is an expiry someone wrote"


def test_bare_unittest_skip_and_a_bare_name_are_told_apart(tmp_path):
    text = ("import unittest\n\nimport pytest\n\n\n"
            "class T(unittest.TestCase):\n"
            "    @unittest.skip\n"
            "    def test_skipped_unittest_bare(self):\n"
            "        pass\n\n"
            "    @pytest.mark.skipped_later\n"
            "    def test_runs_another_mark(self):\n"
            "        pytest.skip\n")
    filed = _filed(tmp_path, text)
    assert set(filed) == {"test_skipped_unittest_bare"}, filed


def test_pytest_itself_skips_what_the_fixture_says(tmp_path):
    """The ground truth: the names above are pytest's behaviour, not this file's guess."""
    (tmp_path / "test_x.py").write_text(FIXTURE, encoding="utf-8")
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k != "PYTEST_ADDOPTS"}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-v", "-p", "no:cacheprovider", "-o", "addopts=",
         "test_x.py"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    outcome = dict(re.findall(r"::(test_\w+) (PASSED|SKIPPED|FAILED|ERROR)", done.stdout))
    assert set(outcome) == _names("test_"), done.stdout + done.stderr
    skipped = {name for name, result in outcome.items() if result == "SKIPPED"}
    assert skipped == _names("test_skipped_") | _names("test_dated_"), done.stdout
    assert {name for name, result in outcome.items() if result == "PASSED"} \
        == _names("test_runs_"), done.stdout


def test_a_marker_inside_a_string_literal_is_a_fixture_not_a_skip(tmp_path):
    """The scan reads text, and a test of a skip scanner keeps markers in strings. The 0.95.0
    release gate filed this file's own FIXTURE three times before the scan learnt this."""
    text = ('import pytest\n\n'
            'PLAIN = """\n@pytest.mark.skip\ndef test_a():\n    pass\n"""\n\n'
            "FORMATTED = f'''\n@pytest.mark.skip(reason=\"{1}\")\ndef test_b():\n    pass\n'''\n\n\n"
            '@pytest.mark.skip\n'
            'def test_skipped_real():\n'
            '    pass\n')
    assert set(_filed(tmp_path, text)) == {"test_skipped_real"}


def test_a_file_the_tokenizer_cannot_read_has_every_marker_read(tmp_path):
    text = ('import pytest\n\n\n'
            '@pytest.mark.skip\n'
            'def test_skipped_real():\n'
            '    pass\n\n'
            'BROKEN = """never closed\n')
    assert set(_filed(tmp_path, text)) == {"test_skipped_real"}, \
        "an unreadable file hides nothing: its markers are read as written"


def test_this_file_files_nothing_from_its_own_fixtures():
    """Every marker in this file sits in a string. Scanned the way the gate scans it, it files
    nothing."""
    assert skips_without_expiry(REPO, ["tests/test_skip_markers.py"]) == []
