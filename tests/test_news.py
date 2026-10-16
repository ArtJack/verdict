"""A standing verdict is not news; a new regression is (trace 2026-10-15, wave 3).

Sales stood at `fail` for 18 runs on two items that wait on a person, and the nightly — which
pages only when a night itself breaks — said nothing for weeks. A new regression under the
same `fail` exits 1 too, so it would have said nothing about that either.
"""

import json

from test_gate import gate, make_home
from verdict_mcp.gate import news_line, news_of


def _f(no, severity, delta, status="open"):
    return {"id": f"PRC-F-{no}", "severity": severity, "delta": delta, "status": status,
            "title": f"finding {no}"}


def test_a_standing_verdict_is_not_news_and_names_who_holds_it():
    state = {"run_number": 5, "verdict": "fail",
             "release_blockers": ["F-2 (Critical/P1) — waits on a decision",
                                  "F-3 (Critical/P1) — one command nobody ran"]}
    findings = [_f(2, "Critical", "STILL_OPEN"), _f(3, "Critical", "STILL_OPEN"),
                _f(9, "Minor", "NEW")]
    rows = [{"run_number": 4, "verdict": "fail"}, {"run_number": 5, "verdict": "fail"}]
    news = news_of(state, findings, rows, [{"id": "PRC-Q-1", "finding": "F-2"}])
    assert news["any"] is False, "a new Minor is not news"
    assert news["blockers_waiting_on_a_person"] == [
        {"blocker": "F-2 (Critical/P1)", "questions": ["PRC-Q-1"]}]
    assert news["blockers"] == [{"blocker": "F-3 (Critical/P1)"}]
    line = news_line({"verdict": "fail", "news": news})
    assert line.startswith("no news — the verdict stands at 'fail'")
    assert "waiting on a person: F-2 (Critical/P1) (PRC-Q-1)" in line
    assert "blockers: F-3 (Critical/P1)" in line


def test_a_new_regression_under_the_same_fail_is_news():
    state = {"run_number": 5, "verdict": "fail", "release_blockers": []}
    findings = [_f(2, "Critical", "REGRESSED"), _f(4, "Major", "NEW"),
                _f(5, "Major", "RESOLVED", status="resolved"), _f(6, "Critical", "STILL_OPEN")]
    rows = [{"run_number": 4, "verdict": "fail"}, {"run_number": 5, "verdict": "fail"}]
    news = news_of(state, findings, rows, [])
    assert news["any"] is True
    assert [f["id"] for f in news["new"]] == ["PRC-F-2", "PRC-F-4"]
    assert [f["id"] for f in news["resolved"]] == ["PRC-F-5"]
    assert news_line({"verdict": "fail", "news": news}) == (
        "news — 2 new at Major or worse: PRC-F-2 (Critical, REGRESSED), PRC-F-4 (Major, NEW); "
        "1 resolved: PRC-F-5")


def test_a_verdict_that_moved_is_news_and_a_first_run_has_nothing_to_compare():
    state = {"run_number": 5, "verdict": "pass with risks", "release_blockers": []}
    rows = [{"run_number": 4, "verdict": "fail"}, {"run_number": 5, "verdict": "pass with risks"}]
    news = news_of(state, [], rows, [])
    assert news["any"] and news["verdict_was"] == "fail"
    assert news_line({"verdict": "pass with risks", "news": news}) == \
        "news — verdict 'fail' → 'pass with risks'"
    first = news_of({"run_number": 1, "verdict": "fail", "release_blockers": []}, [],
                    [{"run_number": 1, "verdict": "fail"}], [])
    assert first["verdict_was"] is None and first["any"] is False


def test_the_gate_says_the_news_in_text_and_json(tmp_path):
    home = make_home(tmp_path)
    (home / "pricer" / "runs.jsonl").write_text(
        json.dumps({"run_number": 3, "verdict": "pass with risks"}) + "\n"
        + json.dumps({"run_number": 4, "verdict": "fail"}) + "\n", encoding="utf-8")
    out = gate(tmp_path, "pricer", home=home).stdout
    assert ("news — verdict 'pass with risks' → 'fail'; 1 new at Major or worse: "
            "PRC-F-2 (Critical, REGRESSED)") in out, out
    data = json.loads(gate(tmp_path, "pricer", "--format", "json", home=home).stdout)
    assert data["news"]["any"] is True and data["news"]["verdict_was"] == "pass with risks"


# ── a fix somebody claimed, that no run has verified ──────────────────────────

def _commit(repo, day, subject, path="a.py"):
    import os
    import subprocess
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    with open(repo / path, "a", encoding="utf-8") as fh:
        fh.write(f"# {subject}\n")
    stamp = f"{day}T12:00:00+00:00"
    env = dict(os.environ, GIT_AUTHOR_DATE=stamp, GIT_COMMITTER_DATE=stamp)
    for args in (["add", "-A"], ["commit", "-q", "-m", subject]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def test_a_commit_that_names_an_open_finding_is_a_claim_never_a_resolution(tmp_path):
    """Sales' commits name what they fix — "census: … (F-113) (#330)" — and on 2026-10-15 eight
    of its open findings had such a commit on main, weeks before the runs that went on carrying
    them open (trace 2026-10-15)."""
    import subprocess
    from verdict_mcp.state import fix_claims
    repo = tmp_path / "repo"
    repo.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "x@y"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    _commit(repo, "2026-08-30", "a fix that came before the finding (F-116)")
    _commit(repo, "2026-09-02", "census: excuse a dropped count only when handed it (F-113) (#330)")
    _commit(repo, "2026-09-03", "qa: run 15 — F-114 closed by counterfactual", path=".qa/state.json")
    _commit(repo, "2026-09-04", "a sibling project's finding (VERDICT-F-115)")
    _commit(repo, "2026-09-05", "a finding already resolved (F-117)")
    _commit(repo, "2026-09-06", "the body names it, the subject does not")
    sha = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True,
                         text=True, check=True).stdout.strip()
    findings = [
        {"id": "F-113", "status": "open", "severity": "Major", "first_seen": "2026-09-02"},
        {"id": "F-114", "status": "open", "severity": "Major", "first_seen": "2026-09-02"},
        {"id": "F-115", "status": "open", "severity": "Minor", "first_seen": "2026-09-02"},
        {"id": "F-116", "status": "open", "severity": "Minor", "first_seen": "2026-09-01"},
        {"id": "F-117", "status": "resolved", "severity": "Minor", "first_seen": "2026-09-01"},
    ]
    claims = fix_claims(repo, sha, findings)
    assert [c["id"] for c in claims] == ["F-113"], claims
    assert claims[0]["date"] == "2026-09-02" and claims[0]["subject"].startswith("census:")
    assert fix_claims(repo, "0" * 40, findings) == [], "a sha this clone cannot see is unknown"
    assert fix_claims(None, sha, findings) == []


def test_the_standing_line_names_the_claimed_fixes():
    news = news_of({"run_number": 2, "verdict": "fail", "release_blockers": []}, [],
                   [{"run_number": 1, "verdict": "fail"}, {"run_number": 2, "verdict": "fail"}], [],
                   [{"id": f"F-{n}", "commit": f"c{n}", "severity": "Major"} for n in range(1, 8)])
    assert news["any"] is False, "a claim is standing information, not a page"
    line = news_line({"verdict": "fail", "news": news})
    assert line.endswith("a commit names as fixed, no run has verified: F-1 (c1), F-2 (c2), "
                         "F-3 (c3), F-4 (c4), F-5 (c5) and 2 more")
