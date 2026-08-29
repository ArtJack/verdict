import json

import pytest

from verdict_mcp import server, state as state_mod


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
    (root / "state.json").write_text(json.dumps(STATE), encoding="utf-8")
    (root / "reports" / "INDEX.md").write_text(INDEX, encoding="utf-8")
    (root / "reports" / "2026-08-24-payment-retry.md").write_text(
        "# QA delta report — pricer run 4\n\nREGRESSED first, as always.\n",
        encoding="utf-8")
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "verdict-home"))
    return root


@pytest.fixture()
def team_repo(tmp_path, monkeypatch):
    # empty solo home so only the path-mode repo resolves
    monkeypatch.setenv("VERDICT_HOME", str(tmp_path / "empty-home"))
    repo = tmp_path / "myapp"
    (repo / ".qa" / "reports").mkdir(parents=True)
    (repo / ".qa" / "state.json").write_text(json.dumps({**STATE, "project": "myapp"}), encoding="utf-8")
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


def test_get_trends(solo_home):
    out = server.get_trends("pricer")
    assert out["project"] == "pricer"
    assert len(out["runs"]) == 2  # both INDEX rows parsed
    assert out["runs"][0]["verdict"] == "pass with risks"
    assert out["runs"][1]["tests_passed"] == 212
    cur = out["current"]
    assert cur["open_findings"] == 3
    assert cur["open_by_severity"] == {"Critical": 1, "Major": 1, "Minor": 1}
    assert cur["age_days"]["oldest"] == 5
    assert cur["quarantine_size"] == 2


def test_hotspots_merges_paths_cited_at_different_depths():
    # The same module cited as `marketplaces/x.py` in one run and
    # `core/src/pkg/marketplaces/x.py` in another must rank as one hotspot,
    # not two lukewarm ones (observed in the live sales state).
    state = {"run_number": 4, "findings": [
        {"severity": "Major", "status": "open",
         "evidence": ["marketplaces/grailed.py:12 short form"]},
        {"severity": "Major", "status": "open",
         "evidence": ["core/src/pkg/marketplaces/grailed.py:40 long form"]},
    ]}
    out = state_mod.hotspots(state)
    assert len(out["hotspots"]) == 1
    top = out["hotspots"][0]
    assert top["path"] == "core/src/pkg/marketplaces/grailed.py"
    assert top["findings"] == 2 and top["open"] == 2
    assert out["runs_of_history"] == 4


def test_hotspots_weight_outranks_raw_count():
    # Three Minors are not a Critical: weight must reorder against count.
    state = {"run_number": 2, "findings": [
        *[{"severity": "Minor", "status": "open", "evidence": [f"noisy.py:{i}"]}
          for i in range(3)],
        {"severity": "Critical", "status": "open", "evidence": ["money.py:9"]},
    ]}
    ranked = state_mod.hotspots(state)["hotspots"]
    assert [h["path"] for h in ranked] == ["money.py", "noisy.py"]
    assert ranked[0]["weight"] == 5.0 and ranked[1]["weight"] == 3.0


def test_hotspots_counts_resolved_in_history_but_not_in_open():
    state = {"run_number": 5, "findings": [
        {"severity": "Major", "status": "resolved", "evidence": ["legacy.py:3"]},
        {"severity": "Major", "status": "open", "evidence": ["legacy.py:8"]},
    ]}
    top = state_mod.hotspots(state)["hotspots"][0]
    assert top["findings"] == 2 and top["open"] == 1


def test_hotspots_reports_uncited_findings_and_ignores_prose():
    state = {"run_number": 1, "findings": [
        {"severity": "Major", "status": "open", "evidence": ["no file here, e.g. nothing"]},
        {"severity": "Major", "status": "open", "evidence": []},
        {"severity": "Major", "status": "open", "evidence": ["src/app.ts:1 real"]},
    ]}
    out = state_mod.hotspots(state)
    assert out["findings_without_a_cited_path"] == 2
    assert [h["path"] for h in out["hotspots"]] == ["src/app.ts"]


def test_get_trends_includes_hotspots(solo_home):
    out = server.get_trends("pricer")
    hot = out["hotspots"]
    assert hot["runs_of_history"] == 4
    assert [h["path"] for h in hot["hotspots"]] == ["pricer.py"]
    assert hot["hotspots"][0]["findings"] == 2  # F-003 (Critical) + F-002 (Major)


def test_get_state_raw(solo_home):
    out = server.get_state("pricer")
    assert out["schema_version"] == 1
    assert out["_qa_root"].endswith("pricer")


def test_severity_rank_case_insensitive():
    assert state_mod.sev_rank("critical") == 1
    assert state_mod.sev_rank(" BLOCKER ") == 0
    assert state_mod.sev_rank(None) == 99
    assert state_mod.sev_rank("banana") == 99


def test_is_path_like():
    assert state_mod.is_path_like("C:/repo")
    assert state_mod.is_path_like("C:\\repo")
    assert state_mod.is_path_like("~/work/app")
    assert state_mod.is_path_like("sub/dir")
    assert state_mod.is_path_like(".")
    assert not state_mod.is_path_like("myapp")
    assert not state_mod.is_path_like("sales")


def test_solo_key_lowercase_fallback(solo_home):
    out = server.get_verdict("PRICER")
    assert out["verdict"] == "fail"


def test_get_report_default_is_last_run(solo_home):
    out = server.get_report("pricer")
    assert out["path"] == "reports/2026-08-24-payment-retry.md"
    assert "REGRESSED first" in out["content"]
    assert out["truncated"] is False


def test_get_report_accepts_absolute_inside_root(solo_home):
    absolute = str(solo_home / "reports" / "2026-08-24-payment-retry.md")
    out = server.get_report("pricer", absolute)
    assert "content" in out and out["path"] == "reports/2026-08-24-payment-retry.md"


def test_get_report_rejects_traversal(solo_home, tmp_path):
    outside = tmp_path / "secret.md"
    outside.write_text("secret", encoding="utf-8")
    for attempt in ("../../secret.md", str(outside), "../" * 8 + "etc/passwd.md"):
        out = server.get_report("pricer", attempt)
        assert "error" in out and "content" not in out, attempt


def test_get_report_rejects_symlink_escape(solo_home, tmp_path):
    outside = tmp_path / "outside.md"
    outside.write_text("secret", encoding="utf-8")
    link = solo_home / "reports" / "link.md"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable on this platform")
    out = server.get_report("pricer", "reports/link.md")
    assert "error" in out and "content" not in out


def test_get_report_serves_markdown_only(solo_home):
    (solo_home / "reports" / "x.txt").write_text("t", encoding="utf-8")
    assert "error" in server.get_report("pricer", "reports/x.txt")


def test_get_report_truncates_oversize(solo_home):
    (solo_home / "reports" / "big.md").write_text("A" * (513 * 1024), encoding="utf-8")
    out = server.get_report("pricer", "reports/big.md")
    assert out["truncated"] is True and len(out["content"]) == 512 * 1024


def test_get_profile_absent_then_present(solo_home):
    out = server.get_profile("pricer")
    assert "error" in out and "hint" in out
    (solo_home / "profile.md").write_text("# QA Profile — pricer\n**Project-Key:** `pricer`\n", encoding="utf-8")
    out = server.get_profile("pricer")
    assert out["content"].startswith("# QA Profile")
    assert "lessons" not in out
    (solo_home / "lessons.md").write_text(
        "# Lessons — pricer\n\n- 2026-08-28 · called FLAKY; was BRITTLE_TEST (clock-seeded).\n",
        encoding="utf-8")
    out = server.get_profile("pricer")
    assert "clock-seeded" in out["lessons"]
