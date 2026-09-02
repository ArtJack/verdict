"""Diff coverage: which changed lines any test executed — measured, not declared.

Every test builds a real two-commit repository and runs a real suite under
coverage.py, because the claim being made is about what the tracer saw.
"""

import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from verdict_mcp.harness import (
    _changed_lines, _render_cmd, _test_id_from_context, collect, merge, render_report)
from verdict_mcp.validate import validate

from conftest import judgment

CMD = f'"{sys.executable}" -m coverage run -m pytest -q -p no:cacheprovider'


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


MOD_A = "def a(x):\n    return x + 1\n"
TEST_A = "from mod import a\n\ndef test_a():\n    assert a(1) == 2\n"


def base_repo(tmp_path):
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "mod.py").write_text(MOD_A, encoding="utf-8")
    (r / "test_mod.py").write_text(TEST_A, encoding="utf-8")
    return r, commit(r, "base")


def qa_with_previous(tmp_path, sha):
    qa = tmp_path / "qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "reports" / "r.md").write_text("# r", encoding="utf-8")
    (qa / "state.json").write_text(json.dumps({
        "project": "proj", "run_number": 1, "run_type": "baseline", "findings": [],
        "last_run": {"git_sha": sha,
                     "timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
    }), encoding="utf-8")
    return qa


def test_changed_lines_are_split_into_executed_and_unexercised(tmp_path):
    """One changed line inside a tested function, and a new function nothing
    calls. The tracer sees the first and never enters the second."""
    r, sha_a = base_repo(tmp_path)
    (r / "mod.py").write_text("def a(x):\n    return x + 2\n\n\ndef b(x):\n    y = x * 2\n    return y\n",
                              encoding="utf-8")
    (r / "test_mod.py").write_text("from mod import a\n\ndef test_a():\n    assert a(1) == 3\n",
                                   encoding="utf-8")
    commit(r, "change a, add b")
    qa = qa_with_previous(tmp_path, sha_a)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    cov = facts["coverage"]
    assert cov["status"] == "measured", cov
    pf = cov["per_file"]["mod.py"]
    assert pf["executed"] == 1, pf                      # `return x + 2` ran, under test_a
    # b's `def` line ran at import — under no test — so the whole of b is
    # unexercised, def line included. That is the truthful statement.
    assert pf["unexercised_ranges"] == [[5, 7]], pf
    assert pf["unexercised_functions"] == ["b"]
    assert "test_mod.py::test_a" in pf["tests"]
    assert cov["changed_lines_executed"] < cov["changed_lines"]
    assert cov["unexercised_functions"] == ["mod.py:b"]
    assert "test_mod.py::test_a" in cov["tests_touching_diff"]

    state = merge(facts, judgment(), None)
    report = render_report(state)
    assert "Diff coverage:" in report and "mod.py: unexercised lines 5-7" in report
    assert "functions never entered: b" in report


def test_a_single_line_hunk_counts(tmp_path):
    """`@@ -2 +2 @@` carries no count; the default is one line, not zero."""
    r, sha_a = base_repo(tmp_path)
    (r / "mod.py").write_text("def a(x):\n    return x + 3\n", encoding="utf-8")
    commit(r, "one line")
    assert _changed_lines(r, f"{sha_a}..HEAD") == {"mod.py": {2}}


def test_a_pass_over_a_change_no_test_executed_is_refused(tmp_path):
    r, sha_a = base_repo(tmp_path)
    (r / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(r, "add b, test nothing")
    qa = qa_with_previous(tmp_path, sha_a)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    assert facts["coverage"]["changed_lines_executed"] == 0

    clean = merge(facts, judgment(verdict="pass", findings=[]), None)
    bad = validate(clean, qa)
    assert any("none of the" in b and "changed lines was executed" in b for b in bad), bad
    honest = merge(facts, judgment(verdict="pass with risks", findings=[]), None)
    assert validate(honest, qa) == []


def test_a_new_file_the_suite_never_imported_is_wholly_unexercised(tmp_path):
    r, sha_a = base_repo(tmp_path)
    (r / "extra.py").write_text("def z():\n    return 1\n", encoding="utf-8")
    commit(r, "new module, untested")
    qa = qa_with_previous(tmp_path, sha_a)
    pf = collect(r, qa, [], coverage_suite_cmd=CMD)["coverage"]["per_file"]["extra.py"]
    # The note says what was actually checked: no test, and no subprocess
    # either. "not imported by anything the suite executed" was the claim that
    # made VERDICT-F-28 a false statement rather than a gap.
    assert pf["executed"] == 0 and pf["measured"] == pf["changed"]
    assert "no test executed it" in pf["note"] and "no subprocess" in pf["note"]


def test_without_a_command_it_is_unmeasurable_and_says_how(tmp_path):
    r, sha_a = base_repo(tmp_path)
    (r / "mod.py").write_text(MOD_A + "x = 1\n", encoding="utf-8")
    commit(r, "change")
    qa = qa_with_previous(tmp_path, sha_a)
    facts = collect(r, qa, [])
    assert facts["coverage"]["status"] == "unavailable"
    assert "coverage_suite_cmd" in facts["coverage"]["reason"]
    state = merge(facts, judgment(verdict="pass", findings=[]), None)
    assert validate(state, qa) == [], "unmeasured is not the same as measured-zero"
    assert "Diff coverage: **unmeasurable**" in render_report(state)


def test_a_baseline_has_no_range_to_measure(tmp_path):
    r, _ = base_repo(tmp_path)
    qa = tmp_path / "qa"
    qa.mkdir()
    cov = collect(r, qa, [], coverage_suite_cmd=CMD)["coverage"]
    assert cov["status"] == "unavailable" and "no commit range" in cov["reason"]


def test_a_range_with_no_python_changes_measures_zero_honestly(tmp_path):
    r, sha_a = base_repo(tmp_path)
    (r / "README.md").write_text("docs\n", encoding="utf-8")
    commit(r, "docs only")
    qa = qa_with_previous(tmp_path, sha_a)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    cov = facts["coverage"]
    assert cov["status"] == "measured" and cov["changed_lines"] == 0
    state = merge(facts, judgment(verdict="pass", findings=[]), None)
    assert validate(state, qa) == []
    assert "no .py lines changed" in render_report(state)


def test_measured_coverage_outranks_a_written_block(tmp_path):
    r, sha_a = base_repo(tmp_path)
    (r / "mod.py").write_text("def a(x):\n    return x + 2\n", encoding="utf-8")
    (r / "test_mod.py").write_text("from mod import a\n\ndef test_a():\n    assert a(1) == 3\n",
                                   encoding="utf-8")
    commit(r, "change")
    qa = qa_with_previous(tmp_path, sha_a)
    facts = collect(r, qa, [], coverage_suite_cmd=CMD)
    state = merge(facts, judgment(coverage={"line_pct": 99, "command": "trust me"}), None)
    assert state["coverage"]["status"] == "measured"
    without = merge(collect(r, qa, []), judgment(coverage={"line_pct": 99}), None)
    assert without["coverage"]["status"] == "unavailable", "unavailable is still a measurement"


def test_both_context_forms_become_node_ids(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("", encoding="utf-8")
    assert _test_id_from_context("tests/test_x.py::test_a|run", tmp_path) == "tests/test_x.py::test_a"
    assert _test_id_from_context("tests.test_x.test_a", tmp_path) == "tests/test_x.py::test_a"
    assert _test_id_from_context("tests.test_x.TestK.test_m", tmp_path) == "tests/test_x.py::TestK::test_m"
    assert _test_id_from_context("", tmp_path) is None


def test_the_render_command_keeps_the_suite_interpreter():
    out = Path("/tmp/c.json")
    assert _render_cmd(".venv/bin/python -m coverage run -m pytest -q", out).startswith(
        ".venv/bin/python -m coverage json --show-contexts")
    assert _render_cmd("uv run python -m pytest --cov --cov-context=test", out).startswith(
        "uv run python -m coverage json --show-contexts")
    assert _render_cmd("./run_cov.sh", out).startswith("coverage json --show-contexts")


def test_the_coverage_run_leaves_nothing_in_the_qa_root(tmp_path):
    """VERDICT-F-29: the rc file, the database and a 95 MB rendered JSON were
    written into the QA root — which in team mode is the committed directory,
    ignored by nothing. Run 5 of this repository left 94,987,311 bytes there,
    one `git add .qa` from a permanent blob in the repository."""
    repo, sha_a = base_repo(tmp_path)
    (repo / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(repo, "add b")
    qa = qa_with_previous(tmp_path, sha_a)
    # Scoped to what THIS measurement creates: a stale directory from someone
    # else's crashed run must not fail this test, or the check becomes noise.
    tmpdir = Path(tempfile.gettempdir())
    before = set(tmpdir.glob("verdict-coverage-*"))
    facts = collect(repo, qa, [], coverage_suite_cmd=CMD)
    assert facts["coverage"]["status"] == "measured"
    left = sorted(p.name for p in qa.iterdir() if p.name.startswith("coverage"))
    assert left == [], left
    assert set(tmpdir.glob("verdict-coverage-*")) - before == set(), \
        "the scratch directory outlived the measurement"


def test_the_repository_is_not_written_to_either(tmp_path):
    """The other place scratch must not land. `coverage run` writes its data
    file where the rc says, and the rc is the harness's."""
    repo, sha_a = base_repo(tmp_path)
    (repo / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(repo, "add b")
    qa = qa_with_previous(tmp_path, sha_a)
    collect(repo, qa, [], coverage_suite_cmd=CMD)
    assert not [p.name for p in repo.iterdir() if p.name.startswith("coverage")]
    # `__pycache__` is pytest's, not the harness's; nothing coverage-shaped is
    # left for a `git add` to pick up.
    untracked = git(repo, "status", "--porcelain").splitlines()
    assert not [ln for ln in untracked if "coverage" in ln], untracked


# ── the suite's child processes are measured too (F-28) ─────────────────────

SPAWNING_TEST = """import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mod import a

HERE = str(Path(__file__).parent)


def test_a():
    assert a(1) == 2


def test_b_runs_in_a_child_process():
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([HERE, os.environ.get("PYTHONPATH", "")])}
        out = subprocess.run([sys.executable, "-c", "import mod; print(mod.b(21))"],
                             cwd=d, capture_output=True, text=True, env=env)
    assert out.stdout.strip() == "42", out
"""


def spawning_repo(tmp_path):
    """A suite that drives its code through a child process, run from another
    working directory — the shape every CLI test in this repository takes."""
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "mod.py").write_text(MOD_A, encoding="utf-8")
    (r / "test_mod.py").write_text(SPAWNING_TEST, encoding="utf-8")
    sha = commit(r, "base")
    (r / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(r, "add b, exercised only through a subprocess")
    return r, sha


def test_a_line_only_a_child_process_executed_is_measured(tmp_path):
    """VERDICT-F-28, live on run 5: coverage traces the process it starts, so
    217 changed lines of issues.py read as "0 executed, not imported by
    anything the suite executed" while eight tests exercised every one of them
    through a CLI subprocess. A false measured claim, and one that can refuse a
    clean pass through the zero-coverage rule."""
    repo, sha_a = spawning_repo(tmp_path)
    qa = qa_with_previous(tmp_path, sha_a)
    cov = collect(repo, qa, [], coverage_suite_cmd=CMD)["coverage"]
    assert cov["status"] == "measured"
    pf = cov["per_file"]["mod.py"]
    assert pf["executed"] >= 1, pf
    assert pf.get("executed_in_subprocess", 0) >= 1, pf
    assert cov["subprocess_coverage"] == "measured"
    assert cov["changed_lines_executed_in_subprocess"] >= 1
    assert pf["unexercised_ranges"] == [], pf


def test_the_subprocess_context_is_never_read_as_a_test(tmp_path):
    """It is a context the harness invented; a node id it is not."""
    repo, sha_a = spawning_repo(tmp_path)
    qa = qa_with_previous(tmp_path, sha_a)
    pf = collect(repo, qa, [], coverage_suite_cmd=CMD)["coverage"]["per_file"]["mod.py"]
    assert not [t for t in pf["tests"] if "subprocess" in t], pf["tests"]


def test_a_suite_that_spawns_nothing_says_so(tmp_path):
    """The flag must distinguish "children measured" from "no children" —
    a suite with none must not read as though its subprocesses were covered."""
    repo, sha_a = base_repo(tmp_path)
    (repo / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(repo, "add b")
    qa = qa_with_previous(tmp_path, sha_a)
    cov = collect(repo, qa, [], coverage_suite_cmd=CMD)["coverage"]
    assert cov["subprocess_coverage"] == "none recorded"
    assert cov["changed_lines_executed_in_subprocess"] == 0


# ── one unreadable file must not cost the whole measurement (F-31) ──────────

VANISHING_TEST = """import os
import subprocess
import sys
import tempfile
from pathlib import Path

from mod import a

HERE = str(Path(__file__).parent)


def test_a():
    assert a(1) == 2


def test_a_child_runs_a_file_that_will_not_exist_at_render_time():
    \"\"\"The shape every fixture-building test in this repository has: the child
    executes a file the test generated in a temp directory, and the directory
    is gone before anything renders the database.\"\"\"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "conftest.py").write_text("VALUE = 42\\n", encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": os.pathsep.join([HERE, d, os.environ.get("PYTHONPATH", "")])}
        out = subprocess.run([sys.executable, "-c", "import conftest, mod; print(mod.b(conftest.VALUE))"],
                             cwd=d, capture_output=True, text=True, env=env)
    assert out.stdout.strip() == "84", out


def test_b_is_reached_in_process_too():
    from mod import b
    assert b(2) == 4
"""


def test_a_file_the_render_cannot_read_does_not_lose_the_measurement(tmp_path):
    """VERDICT-F-31, a regression this repository shipped in 0.60.0: measuring
    the suite's children means the children record whatever they run, including
    files generated in temp directories. `coverage json` aborts on the first
    one it cannot find source for — "No source for code: 'conftest.py'" — and
    diff coverage went from 63% measured to unavailable on the whole run."""
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "mod.py").write_text(MOD_A, encoding="utf-8")
    (r / "test_mod.py").write_text(VANISHING_TEST, encoding="utf-8")
    sha = commit(r, "base")
    (r / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(r, "add b")
    qa = qa_with_previous(tmp_path, sha)
    cov = collect(r, qa, [], coverage_suite_cmd=CMD)["coverage"]
    assert cov["status"] == "measured", cov.get("reason")
    assert cov["per_file"]["mod.py"]["executed"] >= 1, cov["per_file"]["mod.py"]


# ── production and test code are two numbers (F-44) ────────────────────────

def test_the_production_percent_falls_when_production_coverage_falls(tmp_path):
    """VERDICT-F-44, and the probe the finding asked for: a diff that adds one
    unexercised production line and forty lines of passing test code. Blended,
    the percent *rises* on the strength of the test lines that happen to carry
    a context. Read by kind, production falls, which is the fact."""
    r = tmp_path / "proj"
    r.mkdir()
    git(r, "init", "-qb", "main")
    (r / "mod.py").write_text(MOD_A, encoding="utf-8")
    (r / "tests").mkdir()
    (r / "tests" / "test_mod.py").write_text(
        "import sys\nsys.path.insert(0, '.')\nfrom mod import a\n\n\n"
        "def test_a():\n    assert a(1) == 2\n", encoding="utf-8")
    sha = commit(r, "base")

    # one production line nothing calls…
    (r / "mod.py").write_text(MOD_A + "\n\ndef never_called(x):\n    return x * 3\n",
                              encoding="utf-8")
    # …and forty lines of test code that all run
    extra = "".join(f"\n\ndef test_extra_{i}():\n    assert a({i}) == {i + 1}\n"
                    for i in range(12))
    (r / "tests" / "test_mod.py").write_text(
        (r / "tests" / "test_mod.py").read_text(encoding="utf-8") + extra, encoding="utf-8")
    commit(r, "one dead production line, plenty of green tests")

    qa = qa_with_previous(tmp_path, sha)
    cov = collect(r, qa, [], coverage_suite_cmd=CMD)["coverage"]
    assert cov["status"] == "measured", cov.get("reason")
    kinds = cov["by_kind"]
    assert kinds["production"]["changed_lines_executed"] == 0, kinds
    assert kinds["production"]["percent"] == 0, kinds
    assert kinds["tests"]["changed_lines_executed"] > 0, kinds
    # the blended number is the one that hides it
    assert cov["percent"] > kinds["production"]["percent"], cov["percent"]


def test_the_report_reads_production_first(tmp_path):
    repo, sha_a = base_repo(tmp_path)
    (repo / "mod.py").write_text(MOD_A + "\n\ndef b(x):\n    return x * 2\n", encoding="utf-8")
    commit(repo, "add b")
    qa = qa_with_previous(tmp_path, sha_a)
    facts = collect(repo, qa, [], coverage_suite_cmd=CMD)
    state = merge(facts, judgment(), json.loads((qa / "state.json").read_text(encoding="utf-8")))
    text = render_report(state)
    assert "production" in text and "read production first" in text, text


def test_what_counts_as_a_test_file():
    from verdict_mcp.harness import is_test_file
    for path in ("tests/test_x.py", "tests/conftest.py", "src/pkg/test_helper.py",
                 "a/b/tests/c/d.py", "test/thing.py", "pkg/thing_test.py"):
        assert is_test_file(path), path
    for path in ("src/verdict_mcp/harness.py", "hooks/enforce_bash_scope.py",
                 "eval/fixture_freshness.py", "src/contest.py", "src/latest.py",
                 "src/pkg/attest.py"):
        assert not is_test_file(path), path
