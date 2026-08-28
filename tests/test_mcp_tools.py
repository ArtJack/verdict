import json

import pytest

from verdict_mcp import server


STATE = {
    "project": "pricer",
    "schema_version": 1,
    "run_type": "delta",
    "run_number": 4,
    "last_run": {
        "timestamp_utc": "2026-08-24T17:30:00Z",
        "git_sha": "b4e2943",
        "sha_range": "2c67f47..b4e2943",
        "report": "reports/2026-08-24-payment-retry.md",
    },
    "isolation_check": {"result": "pass"},
    "gates": {"pytest": {"result": "pass", "summary": "212 passed, 1 skipped"}},
    "tests": {"collected": 213, "passed": 212, "skipped": 1, "failed": 0},
    "flaky_quarantine": [
        {
            "test_id": "test_pricer.py::test_bulk_discount_applies",
            "first_seen": "2026-08-20",
            "fail_count": 2,
            "run_count": 6,
            "quarantined_until": "2999-01-01",
        },
        {
            "test_id": "test_old.py::test_ancient",
            "first_seen": "2026-01-01",
            "fail_count": 5,
            "run_count": 9,
            "quarantined_until": "2026-02-01",
        },
    ],
    "findings": [
        {
            "id": "PRICER-F-003",
            "hash": "7a3f1c02",
            "first_seen": "2026-08-22",
            "status": "open",
            "delta": "STILL_OPEN",
            "age_days": 2,
            "title": "is_listable rejects a price exactly at the floor",
            "severity": "Critical",
            "priority": "P0",
            "evidence": ["pricer.py:14"],
        },
        {
            "id": "PRICER-F-009",
            "hash": "aa11bb22",
            "first_seen": "2026-08-24",
            "status": "open",
            "delta": "NEW",
            "age_days": 0,
            "title": "minor formatting nit",
            "severity": "Minor",
            "priority": "P3",
            "evidence": [],
        },
        {
            "id": "PRICER-F-002",
            "hash": "cc33dd44",
            "first_seen": "2026-08-19",
            "status": "open",
            "delta": "REGRESSED",
            "age_days": 5,
            "title": "round_cents banker's rounding is back",
            "severity": "Major",
            "priority": "P1",
            "evidence": ["pricer.py:17"],
        },
        {
            "id": "PRICER-F-001",
            "hash": "ee55ff66",
            "first_seen": "2026-08-18",
            "status": "resolved",
            "delta": "RESOLVED",
            "age_days": 6,
            "title": "fixed thing",
            "severity": "Major",
            "priority": "P1",
            "evidence": [],
        },
    ],
    "verdict": "fail",
    "release_blockers": ["PRICER-F-002"],
    "not_tested": ["concurrency under parallel checkout"],
}

INDEX = """# QA Reports Index

| Date | Project | Run type | Verdict | Tests (pass/skip/fail) | Δ tests | Findings (C/M/m) | Report |
|---|---|---|---|---|---|---|---|
| 2026-08-23 | pricer | baseline | pass with risks | 212 / 1 / 0 | n/a | 1 / 1 / 1 | [2026-08-23-baseline.md](2026-08-23-baseline.md) |
| 2026-08-24 | pricer | delta | fail | 212 / 1 / 0 | 0 | 1 / 2 / 1 | [2026-08-24-payment-retry.md](2026-08-24-payment-retry.md) |
"""


@pytest.fixture()
def solo_home(tmp_path, monkeypatch):
    root = tmp_path / "verdict-home" / "pricer"
    (root / "reports").mkdir(parents=True)
    (root / "state.json").write_text(json.dumps(STATE))
    (root / "reports" / "INDEX.md").write_text(INDEX)
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "verdict-home"))
    return root


@pytest.fixture()
def team_repo(tmp_path, monkeypatch):
    # empty solo home so only the path-mode repo resolves
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "empty-home"))
    repo = tmp_path / "myapp"
    (repo / ".qa" / "reports").mkdir(parents=True)
    (repo / ".qa" / "state.json").write_text(json.dumps({**STATE, "project": "myapp"}))
    return repo


def test_list_projects(solo_home):
    out = server.list_projects()
    assert [p["project"] for p in out["projects"]] == ["pricer"]
    assert out["projects"][0]["verdict"] == "fail"
    assert out["projects"][0]["run_number"] == 4


def test_get_verdict(solo_home):
    out = server.get_verdict("pricer")
    assert out["verdict"] == "fail"
    assert out["release_blockers"] == ["PRICER-F-002"]
    assert out["report"] == "reports/2026-08-24-payment-retry.md"
    assert out["not_tested"] == ["concurrency under parallel checkout"]


def test_findings_open_orders_regressed_first(solo_home):
    out = server.get_findings("pricer")  # default status="open"
    ids = [f["id"] for f in out["findings"]]
    # REGRESSED first, then remaining open by severity (Critical before Minor);
    # the resolved finding is excluded from "open".
    assert ids == ["PRICER-F-002", "PRICER-F-003", "PRICER-F-009"]
    assert out["count"] == 3


def test_findings_delta_filter_and_all(solo_home):
    assert [f["id"] for f in server.get_findings("pricer", "RESOLVED")["findings"]] == ["PRICER-F-001"]
    assert server.get_findings("pricer", "all")["count"] == 4


def test_findings_unknown_status(solo_home):
    out = server.get_findings("pricer", "banana")
    assert "error" in out and "open" in out["allowed"]


def test_quarantine_expired_flag(solo_home):
    out = server.get_quarantine("pricer")
    by_id = {q["test_id"]: q for q in out["quarantine"]}
    assert by_id["test_old.py::test_ancient"]["expired"] is True
    assert by_id["test_pricer.py::test_bulk_discount_applies"]["expired"] is False


def test_history_parses_index(solo_home):
    out = server.get_history("pricer")
    assert out["count"] == 2
    assert out["runs"][0]["Verdict"] == "pass with risks"
    assert out["runs"][1]["report_path"] == "2026-08-24-payment-retry.md"


def test_team_mode_path_resolution(team_repo):
    out = server.get_verdict(str(team_repo))
    assert out["verdict"] == "fail"
    assert out["project"] == "myapp"


def test_unknown_project_error(solo_home):
    out = server.get_verdict("nope")
    assert "error" in out
    assert out["known_projects"] == ["pricer"]


def test_get_state_raw(solo_home):
    out = server.get_state("pricer")
    assert out["schema_version"] == 1
    assert out["_qa_root"].endswith("pricer")


def test_severity_rank_case_insensitive():
    assert server._sev_rank("critical") == 1
    assert server._sev_rank(" BLOCKER ") == 0
    assert server._sev_rank(None) == 99
    assert server._sev_rank("banana") == 99


def test_is_path_like():
    assert server._is_path_like("C:/repo")
    assert server._is_path_like("C:\\repo")
    assert server._is_path_like("~/work/app")
    assert server._is_path_like("sub/dir")
    assert server._is_path_like(".")
    assert not server._is_path_like("myapp")
    assert not server._is_path_like("sales")


def test_solo_key_lowercase_fallback(solo_home):
    out = server.get_verdict("PRICER")
    assert out["verdict"] == "fail"
