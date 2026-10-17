"""A coverage render that exceeds its budget falls back to the production files (0.91.1)."""

import json
import subprocess

from verdict_mcp import harness


def test_a_slow_full_render_retries_on_production_files(tmp_path, monkeypatch):
    calls = []
    real_run = subprocess.run

    def fake_run(cmd, *a, **kw):
        calls.append(cmd)
        if "coverage json" in str(cmd):
            if len([c for c in calls if "coverage json" in str(c)]) == 1:
                raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))
            out = str(cmd).split(" -o ", 1)[1].strip().strip("'\"")
            (tmp_path / "rendered.txt").write_text(open(kw["env"]["COVERAGE_RCFILE"]).read())
            with open(out, "w") as fh:
                json.dump({"files": {"pkg/pay.py": {"summary": {"num_statements": 3}}}}, fh)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 0, "1 passed", "")

    monkeypatch.setattr(harness.subprocess, "run", fake_run)
    scratch = tmp_path / "s"
    scratch.mkdir()
    files, meta = harness._run_coverage(tmp_path, scratch, "python -m coverage run -m pytest -q")
    monkeypatch.setattr(harness.subprocess, "run", real_run)
    assert files == {"pkg/pay.py": {"summary": {"num_statements": 3}}}
    assert meta["render_scope"].startswith("production files only (the full render exceeded 300 s)")
    rc = (tmp_path / "rendered.txt").read_text()
    assert "omit = tests/*" in rc and "*/conftest.py" in rc
    import configparser
    parsed = configparser.ConfigParser(interpolation=None)     # strict, as coverage.py reads it
    parsed.read_string(rc)
    assert parsed.get("report", "ignore_errors") == "True" and parsed.get("report", "omit").startswith("tests/*")


def test_a_test_file_absent_from_a_production_render_is_not_called_unexercised(tmp_path):
    meta = {"command": "x", "suite_exit_code": 0, "duration_s": 1.0, "render_scope": "production files only"}
    diff = harness._diff_from_files({}, {"tests/test_pay.py": {1, 2}, "pkg/pay.py": {5}}, meta, "a..b", tmp_path)
    assert diff["per_file"]["tests/test_pay.py"]["measured"] == 0
    assert diff["per_file"]["pkg/pay.py"]["measured"] == 1 and diff["per_file"]["pkg/pay.py"]["executed"] == 0


def test_the_fallback_render_runs_on_real_coverage(tmp_path, monkeypatch):
    """The same path against coverage.py itself: the first render is made to time out, the second
    renders the production file and leaves the test file out."""
    import sys
    repo = tmp_path / "r"
    (repo / "pkg").mkdir(parents=True)
    (repo / "tests").mkdir()
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "pkg" / "pay.py").write_text("def fee(x):\n    return x * 2\n", encoding="utf-8")
    (repo / "tests" / "test_pay.py").write_text("from pkg.pay import fee\n\n\ndef test_fee():\n    assert fee(2) == 4\n",
                                                encoding="utf-8")
    monkeypatch.setattr(harness, "RENDER_TIMEOUT_S", 0.001)
    scratch = tmp_path / "s"
    scratch.mkdir()
    files, meta = harness._run_coverage(repo, scratch, f"{sys.executable} -m coverage run -m pytest -q -p no:cacheprovider")
    assert files is not None, meta
    assert "pkg/pay.py" in files and not any(p.startswith("tests/") for p in files), sorted(files)
    assert meta["render_scope"].startswith("production files only")
