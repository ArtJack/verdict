"""The report is written under the QA root's reports/, wherever the judgment points.

finalize honoured `judgment.report` as given and rendered the report there: an
absolute path or a `..` named any `*.md` in the code under test — the README of
a team-mode checkout, proven by the 2026-10-02 audit (H-D-1) — and `topic` went
into the filename unsanitised, so `../../x` climbed out the same way. Every real
record names `reports/<file>.md` (16 QA roots and 132 history rows surveyed), so
the rule refuses nothing a run has ever legitimately written.
"""

import json
import subprocess
import sys
from datetime import datetime, timezone

import pytest

from verdict_mcp.harness import _report_name, _safe_topic, facts_main, finalize_main
from verdict_mcp.validate import report_outside_reports, validate


@pytest.mark.parametrize("report", [
    "/etc/motd.md", "../README.md", "reports/../README.md", "docs/notes.md",
    "escaped.md", "reports/sub/x.md", "reports//x.md", "C:\\x\\y.md", "reports/./x.md",
])
def test_a_report_outside_reports_is_named(report):
    assert report_outside_reports(report)


def test_a_report_directly_under_reports_is_fine():
    assert report_outside_reports("reports/2026-10-02-delta-run3.md") is None


def _state(report: str) -> dict:
    """A state the validator accepts but for its report — built here, not read from this
    repository's own `.qa/`: the first version read the committed state, and the release's
    own local gate, whose throwaway root holds a profile and nothing else, went red on it."""
    return {
        "project": "scratch", "schema_version": 1, "run_type": "delta", "run_number": 2,
        "last_run": {"timestamp_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                     "git_sha": "abc1234", "sha_range": "aaa..abc", "report": report},
        "isolation_check": {"result": "pass"}, "gates": {}, "tests": {"collected": 1},
        "flaky_quarantine": [], "findings": [], "verdict": "pass with risks",
        "release_blockers": [], "not_tested": ["everything but the shape of the report path"],
    }


def test_the_validator_refuses_a_report_that_left_reports(tmp_path):
    qa = tmp_path / ".qa"
    (qa / "reports").mkdir(parents=True)
    (qa / "reports" / "r.md").write_text("# report", encoding="utf-8")
    (tmp_path / "README.md").write_text("# not a report", encoding="utf-8")
    assert not [b for b in validate(_state("reports/r.md"), qa, None) if "report" in b]
    bad = validate(_state("../README.md"), qa, None)
    assert any("climbs out" in b for b in bad), bad
    bad = validate(_state(str(tmp_path / "README.md")), qa, None, at_rest=True)
    assert any("absolute path" in b for b in bad), bad


def test_topic_is_a_filename_fragment_never_a_path(tmp_path):
    assert _safe_topic("../../escaped topic", "run") == "escaped-topic"
    assert _safe_topic("delta — second opinion", "run") == "delta-second-opinion"
    assert _safe_topic("", "run") == "run"
    assert _report_name(tmp_path, "2026-10-02", "../../x", 1) == "reports/2026-10-02-x.md"


# ── end to end: facts → judgment → finalize on a scratch checkout ────────────

def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture()
def checkout(tmp_path, monkeypatch):
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "home"))   # never the real one
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "README.md").write_text("# scratch project\nDo not overwrite me.\n", encoding="utf-8")
    qa = repo / ".qa"
    qa.mkdir()
    (qa / "profile.md").write_text(
        f"---\ngates:\n  suite: {sys.executable} -c \"print('1 passed in 0.01s')\"\n---\n\n"
        "# QA profile — scratch\n\nProject-Key: scratch\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "x@y")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "baseline")
    return repo


JUDGMENT = {"verdict": "pass with risks", "findings": [],
            "isolation_check": {"result": "pass", "method": "no network"},
            "release_blockers": [], "not_tested": ["everything but the gate"]}


def _finalize(repo, judgment):
    qa = repo / ".qa"
    assert facts_main(["--repo", str(repo), "--qa-root", str(qa)]) == 0
    (qa / "judgment.json").write_text(json.dumps(judgment), encoding="utf-8")
    return finalize_main(["--qa-root", str(qa), "--judgment", str(qa / "judgment.json")])


def test_finalize_refuses_a_report_path_into_the_checkout(checkout, capsys):
    readme = checkout / "README.md"
    before = readme.read_text(encoding="utf-8")
    rc = _finalize(checkout, {**JUDGMENT, "report": str(readme)})
    assert rc == 1
    assert readme.read_text(encoding="utf-8") == before, "the README was overwritten"
    assert not (checkout / ".qa" / "state.json").exists()
    assert "refusing the report path" in capsys.readouterr().err


def test_finalize_refuses_a_relative_climb(checkout):
    rc = _finalize(checkout, {**JUDGMENT, "report": "../escaped.md"})
    assert rc == 1 and not (checkout / "escaped.md").exists()


def test_a_topic_cannot_climb_either(checkout):
    rc = _finalize(checkout, {**JUDGMENT, "topic": "../../escaped topic"})
    assert rc == 0
    state = json.loads((checkout / ".qa" / "state.json").read_text(encoding="utf-8"))
    report = state["last_run"]["report"]
    assert report.startswith("reports/") and report.endswith("-escaped-topic.md"), report
    assert (checkout / ".qa" / report).is_file()
    assert not (checkout.parent / "escaped topic.md").exists()
